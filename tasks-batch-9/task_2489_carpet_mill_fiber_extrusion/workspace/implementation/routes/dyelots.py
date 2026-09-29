"""The dye house: vessel booking, colour matching, shade banding and re-dye (PRD 3.6)."""

from decimal import Decimal

from flask import Blueprint

import calc
from calc import dec, rhu
from db import insert, store, touch
from errors import ApiError
from routes.common import authenticate, created, fetch, listing, ok, unique
from routes.runs import minute
from services import cascades, ledgers
from validators import bad, json_body, req_enum, req_instant, req_int, req_num, req_str

bp = Blueprint("dyelots", __name__)

DYE_LOT_STATUSES = (
    "FORMULATED",
    "DYEING",
    "MEASURED",
    "APPROVED",
    "REDYE_QUEUED",
    "EXHAUSTED",
    "REJECTED",
)
SHADE_BANDS = ("A", "B", "C", "OUT")
CONTENDING_STATUSES = ("FORMULATED", "DYEING")
DYE_RUN_STATUSES = ("GREIGE", "BACKED", "BACKING_FAILED", "RELEASED")

WRITE_ROLES = ("DyeHouseOperator", "PlantAdmin")
READ_ROLES = ("DyeHouseOperator", "MillPlanner", "QALabTechnician", "PlantAdmin")


def _window(lot):
    return minute(lot["_start_dt"]), minute(lot["_end_dt"])


def _contains(lot, instant):
    """The dye window is closed at both ends."""
    start, end = _window(lot)
    return start <= instant <= end


def _check_vessel_capacity(vessel, new_start, new_end, lot_kg):
    """Rung 23 — aggregate capacity at every probe instant (both ends closed)."""
    existing = [l for l in store.dye_lots.values() if l["vessel_id"] == vessel["id"]]

    probes = [new_start]
    for lot in existing:
        start, end = _window(lot)
        if new_start <= start <= new_end and start not in probes:
            probes.append(start)
        if new_start <= end <= new_end and end not in probes:
            probes.append(end)

    capacity = dec(vessel["capacity_kg"])
    for instant in probes:
        load = dec(lot_kg)
        for lot in existing:
            if lot["status"] not in CONTENDING_STATUSES:
                continue
            if _contains(lot, instant):
                load += dec(lot["lot_kg"])
        if rhu(load, 1) > capacity:
            raise ApiError(
                "ERR_VESSEL_CAPACITY_EXCEEDED",
                "Loading %s kg exceeds the vessel capacity of %s kg"
                % (rhu(load, 1), capacity),
            )


@bp.post("/mill/dye-lots")
def formulate_lot():
    authenticate(WRITE_ROLES)
    body = json_body()
    lot_code = req_str(body, "lot_code")
    production_run_id = req_str(body, "production_run_id")
    vessel_id = req_str(body, "vessel_id")
    color_code = req_str(body, "color_code")
    target_lab_l = req_num(body, "target_lab_l", 2)
    target_lab_a = req_num(body, "target_lab_a", 2)
    target_lab_b = req_num(body, "target_lab_b", 2)
    lot_kg = req_num(body, "lot_kg", 1, gt=0)
    start_dt, start_raw = req_instant(body, "dye_start_utc")
    end_dt, end_raw = req_instant(body, "dye_end_utc")
    dyed_yards = req_num(body, "dyed_yards", 1, gt=0)
    if not end_dt > start_dt:
        bad("dye_end_utc must be strictly later than dye_start_utc")

    # Rung 6 — body reference existence.
    run = fetch("runs", production_run_id)
    vessel = fetch("vessels", vessel_id)

    # Rung 7 — natural-key uniqueness.
    unique("dye_lots", "lot_code", lot_code)

    # Rung 8 — the run must have reached backing.
    if run["status"] not in DYE_RUN_STATUSES:
        raise ApiError(
            "ERR_INVALID_STATE",
            "The run has not reached greige goods ready for the dye house",
        )

    # Rung 16 — only a piece-dyed style passes through the dye house.
    style = store.styles.get(run["style_id"])
    if style is None or style["dye_method"] != "PIECE_DYED":
        raise ApiError(
            "ERR_DYE_METHOD_MISMATCH",
            "A dye lot may only be formulated against a PIECE_DYED style's run",
        )

    # Rung 23 — vessel capacity over the closed window.
    _check_vessel_capacity(vessel, minute(start_dt), minute(end_dt), lot_kg)

    lot = insert(
        store.dye_lots,
        {
            "lot_code": lot_code,
            "production_run_id": production_run_id,
            "vessel_id": vessel_id,
            "parent_dye_lot_id": None,
            "color_code": color_code,
            "target_lab_l": target_lab_l,
            "target_lab_a": target_lab_a,
            "target_lab_b": target_lab_b,
            "measured_lab_l": None,
            "measured_lab_a": None,
            "measured_lab_b": None,
            "delta_e": None,
            "shade_band": None,
            "lot_kg": lot_kg,
            "dye_start_utc": start_raw,
            "dye_end_utc": end_raw,
            "_start_dt": start_dt,
            "_end_dt": end_dt,
            "dyed_yards": dyed_yards,
            "scrapped_yards": 0.0,
            "uncommitted_yards": dyed_yards,
            "shipped_basis_uncommitted_yards": dyed_yards,
            "redye_count": 0,
            "status": "FORMULATED",
        },
    )
    return created("dye_lot", lot)


@bp.post("/mill/dye-lots/<dye_lot_id>/start-dyeing")
def start_dyeing(dye_lot_id):
    authenticate(WRITE_ROLES)
    lot = fetch("dye_lots", dye_lot_id)

    # Rung 8 — state legality plus vessel availability.
    if lot["status"] not in ("FORMULATED", "REDYE_QUEUED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a FORMULATED or REDYE_QUEUED lot may be charged",
        )
    vessel = store.vessels.get(lot["vessel_id"])
    if vessel is None or vessel["status"] != "AVAILABLE":
        raise ApiError("ERR_VESSEL_UNAVAILABLE", "The booked vessel is not AVAILABLE")

    # Rung 24 — the booked window must have opened.
    if store.clock_dt < lot["_start_dt"]:
        raise ApiError(
            "ERR_DYE_WINDOW_NOT_OPEN",
            "The logical clock has not reached dye_start_utc",
        )

    if lot["status"] == "REDYE_QUEUED":
        lot["redye_count"] = lot["redye_count"] + 1
        for field in (
            "measured_lab_l",
            "measured_lab_a",
            "measured_lab_b",
            "delta_e",
            "shade_band",
        ):
            lot[field] = None

    lot["status"] = "DYEING"
    touch(lot)
    return ok("dye_lot", lot)


@bp.post("/mill/dye-lots/<dye_lot_id>/measurements")
def record_measurement(dye_lot_id):
    authenticate(WRITE_ROLES)
    body = json_body()
    measured_lab_l = req_num(body, "measured_lab_l", 2)
    measured_lab_a = req_num(body, "measured_lab_a", 2)
    measured_lab_b = req_num(body, "measured_lab_b", 2)
    expected_version = req_int(body, "expected_dye_lot_version", ge=1)

    lot = fetch("dye_lots", dye_lot_id)

    # Rung 8 — state legality.
    if lot["status"] != "DYEING":
        raise ApiError("ERR_INVALID_STATE", "Only a DYEING lot may be measured")

    # Rung 10 — optimistic concurrency on the dye lot.
    if expected_version != lot["version"]:
        raise ApiError(
            "ERR_STALE_DYE_LOT_VERSION",
            "expected_dye_lot_version %d does not match the lot's version %d"
            % (expected_version, lot["version"]),
        )

    delta_e = calc.delta_e_cie76(
        lot["target_lab_l"],
        lot["target_lab_a"],
        lot["target_lab_b"],
        measured_lab_l,
        measured_lab_a,
        measured_lab_b,
    )

    lot["measured_lab_l"] = measured_lab_l
    lot["measured_lab_a"] = measured_lab_a
    lot["measured_lab_b"] = measured_lab_b
    lot["delta_e"] = delta_e
    lot["shade_band"] = calc.shade_band_for(delta_e)
    lot["status"] = "MEASURED"
    touch(lot)
    return ok("dye_lot", lot)


@bp.post("/mill/dye-lots/<dye_lot_id>/disposition")
def disposition(dye_lot_id):
    authenticate(WRITE_ROLES)
    body = json_body()
    choice = req_enum(body, "disposition", ("APPROVE", "REDYE", "REJECT"))

    lot = fetch("dye_lots", dye_lot_id)

    if choice == "APPROVE":
        # Rung 8 — state legality.
        if lot["status"] != "MEASURED":
            raise ApiError("ERR_INVALID_STATE", "Only a MEASURED lot may be approved")
        # Rung 19 — the band must be sellable.
        if lot["shade_band"] not in ("A", "B", "C"):
            raise ApiError(
                "ERR_SHADE_BAND_NOT_APPROVABLE",
                "A lot banded OUT cannot be approved",
            )
        lot["status"] = "APPROVED"
        touch(lot)
        ledgers.recompute_dye_lot_yards(lot)
        return ok("dye_lot", lot)

    if choice == "REDYE":
        # Rung 8 — state legality and the bounded revision loop.
        if lot["status"] != "MEASURED":
            raise ApiError("ERR_INVALID_STATE", "Only a MEASURED lot may be re-dyed")
        if lot["redye_count"] >= calc.MAX_REDYE_COUNT:
            raise ApiError(
                "ERR_REDYE_LIMIT_REACHED",
                "The lot has already completed the maximum of %d re-dye cycles"
                % calc.MAX_REDYE_COUNT,
            )
        # Rung 19 — only a marginal or failed match may be re-dyed.
        if lot["shade_band"] not in ("C", "OUT"):
            raise ApiError(
                "ERR_SHADE_BAND_NOT_REDYEABLE",
                "A lot banded A or B has nothing to gain from a second bath",
            )
        if not lot["parent_dye_lot_id"]:
            lot["parent_dye_lot_id"] = lot["id"]
        lot["status"] = "REDYE_QUEUED"
        touch(lot)
        return ok("dye_lot", lot)

    # REJECT — legal from MEASURED and from APPROVED.
    if lot["status"] not in ("MEASURED", "APPROVED"):
        raise ApiError(
            "ERR_INVALID_STATE", "Only a MEASURED or APPROVED lot may be rejected"
        )
    cascades.reject_dye_lot(lot)
    return ok("dye_lot", lot)


@bp.get("/mill/dye-lots/<dye_lot_id>")
def read_lot(dye_lot_id):
    authenticate(READ_ROLES)
    return ok("dye_lot", fetch("dye_lots", dye_lot_id))


@bp.get("/mill/dye-lots")
def list_lots():
    authenticate(READ_ROLES)
    return listing(
        "dye_lot",
        "dye_lots",
        enum_filters={"status": DYE_LOT_STATUSES, "shade_band": SHADE_BANDS},
        value_filters=("production_run_id", "vessel_id", "parent_dye_lot_id"),
    )
