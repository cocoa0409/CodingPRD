"""Production runs: scheduling, setup, greige, backing and doffing (PRD 3.4, 3.5, 3.7)."""

from flask import Blueprint

import calc
from calc import dec
from db import insert, store, touch
from errors import ApiError
from routes.common import authenticate, created, fetch, listing, ok, unique
from routes.styles import GAUGE_CODES, PLANNER_ROLES
from services import cascades, ledgers
from validators import json_body, opt_id, opt_str, req_enum, req_instant, req_int, req_num, req_str

bp = Blueprint("runs", __name__)

RUN_STATUSES = (
    "SCHEDULED",
    "HELD",
    "TUFTING",
    "GREIGE",
    "BACKED",
    "BACKING_FAILED",
    "RELEASED",
    "ABORTED",
)
OCCUPYING_STATUSES = (
    "SCHEDULED",
    "HELD",
    "TUFTING",
    "GREIGE",
    "BACKED",
    "BACKING_FAILED",
)
BACKING_TYPES = ("ACTION_BAC", "WOVEN_POLYPROPYLENE", "CUSHION")
RUN_READ_ROLES = (
    "MillPlanner",
    "DyeHouseOperator",
    "QALabTechnician",
    "CertificationOfficer",
    "PlantAdmin",
)


def minute(dt):
    """Instants are compared at minute resolution (PRD 3.4)."""
    return dt.replace(second=0, microsecond=0)


def _occupancy(run, changeover_minutes):
    from datetime import timedelta

    start = minute(run["_start_dt"]) - timedelta(minutes=changeover_minutes)
    return start, minute(run["_end_dt"])


@bp.post("/mill/production-runs")
def schedule_run():
    authenticate(PLANNER_ROLES)
    body = json_body()
    run_code = req_str(body, "run_code")
    style_id = req_str(body, "style_id")
    machine_id = req_str(body, "machine_id")
    fiber_batch_id = req_str(body, "fiber_batch_id")
    start_dt, start_raw = req_instant(body, "scheduled_start_utc")
    end_dt, end_raw = req_instant(body, "scheduled_end_utc")
    if not end_dt > start_dt:
        from validators import bad

        bad("scheduled_end_utc must be strictly later than scheduled_start_utc")

    # Rung 6 — body reference existence.
    style = fetch("styles", style_id)
    machine = fetch("machines", machine_id)
    batch = fetch("fiber_batches", fiber_batch_id)

    # Rung 7 — natural-key uniqueness.
    unique("runs", "run_code", run_code)

    # Rung 8 — state legality of the creel.
    if batch["status"] != "RELEASED":
        raise ApiError(
            "ERR_FIBER_BATCH_NOT_RELEASED",
            "The creeled fiber batch is not in RELEASED",
        )

    # Rung 16 — the style-to-yarn dye-method coupling.
    if style["dye_method"] == "SOLUTION_DYED":
        if batch["dye_method"] != "SOLUTION_DYED" or batch.get(
            "solution_color_code"
        ) != style.get("solution_color_code"):
            raise ApiError(
                "ERR_DYE_METHOD_MISMATCH",
                "A SOLUTION_DYED style requires a matching solution-dyed creel",
            )
    else:
        if batch["dye_method"] != "PIECE_DYED_READY":
            raise ApiError(
                "ERR_DYE_METHOD_MISMATCH",
                "A PIECE_DYED style requires a PIECE_DYED_READY creel",
            )

    # Rung 22 — machine window exclusivity.
    candidate = {"_start_dt": start_dt, "_end_dt": end_dt}
    new_start, new_end = _occupancy(candidate, machine["changeover_minutes"])
    for other in store.runs.values():
        if other["machine_id"] != machine_id:
            continue
        if other["status"] not in OCCUPYING_STATUSES:
            continue
        other_start, other_end = _occupancy(other, machine["changeover_minutes"])
        if new_start < other_end and other_start < new_end:
            raise ApiError(
                "ERR_MACHINE_WINDOW_CONFLICT",
                "The occupancy window overlaps run %s" % other["run_code"],
            )

    # Rung 25 — a run may only be scheduled against an ACTIVE style.
    if style["status"] != "ACTIVE":
        raise ApiError("ERR_STYLE_NOT_ACTIVE", "The style is not ACTIVE")

    run = insert(
        store.runs,
        {
            "run_code": run_code,
            "style_id": style_id,
            "machine_id": machine_id,
            "fiber_batch_id": fiber_batch_id,
            "scheduled_start_utc": start_raw,
            "scheduled_end_utc": end_raw,
            "_start_dt": start_dt,
            "_end_dt": end_dt,
            "gauge_loaded_code": None,
            "pile_height_set_mm": None,
            "pattern_repeat_loaded_mm": None,
            "stitch_rate_per_inch": None,
            "greige_yards": None,
            "face_weight_oz_per_sy": None,
            "sbr_pct": None,
            "filler_load_pct": None,
            "cure_temp_c": None,
            "cure_seconds": None,
            "secondary_backing_type": None,
            "delamination_strength_lbf": None,
            "recoat_count": 0,
            "status": "SCHEDULED",
        },
    )

    batch["status"] = "ALLOCATED"
    touch(batch)
    return created("run", run)


@bp.post("/mill/production-runs/<production_run_id>/load-setup")
def load_setup(production_run_id):
    authenticate(PLANNER_ROLES)
    body = json_body()
    gauge_loaded_code = req_enum(body, "gauge_loaded_code", GAUGE_CODES)
    pile_height_set_mm = req_num(body, "pile_height_set_mm", 1, gt=0)
    pattern_repeat_loaded_mm = req_num(body, "pattern_repeat_loaded_mm", 1, gt=0)
    stitch_rate_per_inch = req_num(body, "stitch_rate_per_inch", 1, gt=0)

    run = fetch("runs", production_run_id)
    style = store.styles.get(run["style_id"])
    machine = store.machines.get(run["machine_id"])
    batch = store.fiber_batches.get(run["fiber_batch_id"])

    # Rung 8 — state legality.
    if run["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED run may be loaded")
    if style is None or style["status"] != "ACTIVE":
        raise ApiError("ERR_STYLE_NOT_ACTIVE", "The style is not ACTIVE")
    if machine is None or machine["status"] != "IDLE":
        raise ApiError("ERR_MACHINE_UNAVAILABLE", "The tufter is not IDLE")
    if batch is None or batch["status"] != "ALLOCATED":
        raise ApiError("ERR_INVALID_STATE", "The creeled fiber batch is not ALLOCATED")

    # Rung 15 — the five tufter setup checks, in their fixed order.
    if gauge_loaded_code != style["gauge_code"]:
        raise ApiError("ERR_GAUGE_MISMATCH", "The loaded gauge differs from the style's")
    if gauge_loaded_code != machine["native_gauge_code"]:
        raise ApiError(
            "ERR_MACHINE_GAUGE_INCOMPATIBLE",
            "The loaded gauge differs from the tufter's needle bar",
        )
    if not (
        dec(machine["min_pile_height_mm"])
        <= dec(pile_height_set_mm)
        <= dec(machine["max_pile_height_mm"])
    ):
        raise ApiError(
            "ERR_PILE_HEIGHT_OUT_OF_RANGE",
            "The dialled pile height is outside the tufter's envelope",
        )
    if abs(dec(pile_height_set_mm) - dec(style["pile_height_mm"])) > calc.PILE_HEIGHT_SPEC_TOLERANCE_MM:
        raise ApiError(
            "ERR_PILE_HEIGHT_SPEC_DEVIATION",
            "The dialled pile height deviates from the style by more than 0.5 mm",
        )
    if dec(pattern_repeat_loaded_mm) != dec(style["pattern_repeat_mm"]):
        raise ApiError(
            "ERR_PATTERN_REPEAT_MISMATCH",
            "The loaded pattern repeat differs from the style's",
        )

    # Rung 24 — the booked window must have opened.
    if store.clock_dt < run["_start_dt"]:
        raise ApiError(
            "ERR_RUN_WINDOW_NOT_OPEN",
            "The logical clock has not reached scheduled_start_utc",
        )

    run["gauge_loaded_code"] = gauge_loaded_code
    run["pile_height_set_mm"] = pile_height_set_mm
    run["pattern_repeat_loaded_mm"] = pattern_repeat_loaded_mm
    run["stitch_rate_per_inch"] = stitch_rate_per_inch
    run["status"] = "TUFTING"
    touch(run)
    return ok("run", run)


@bp.post("/mill/production-runs/<production_run_id>/complete-greige")
def complete_greige(production_run_id):
    authenticate(PLANNER_ROLES)
    body = json_body()
    greige_yards = req_num(body, "greige_yards", 1, gt=0)

    run = fetch("runs", production_run_id)
    if run["status"] != "TUFTING":
        raise ApiError("ERR_INVALID_STATE", "Only a TUFTING run may close out greige")

    style = store.styles.get(run["style_id"])
    batch = store.fiber_batches.get(run["fiber_batch_id"])

    face_weight = calc.face_weight_oz_per_sy(
        style["gauge_code"],
        run["stitch_rate_per_inch"],
        run["pile_height_set_mm"],
        style["pile_construction"],
        batch["denier_actual"],
        style["plies"],
    )

    # Rung 18 — the face-weight tolerance gate, on the rounded figure.
    if not calc.face_weight_within_tolerance(face_weight, style["target_face_weight_oz"]):
        raise ApiError(
            "ERR_FACE_WEIGHT_OUT_OF_TOLERANCE",
            "The computed face weight of %.2f oz/sy is outside 1.60 oz/sy of target"
            % face_weight,
        )

    run["greige_yards"] = greige_yards
    run["face_weight_oz_per_sy"] = face_weight
    run["status"] = "GREIGE"
    touch(run)

    if batch["status"] == "ALLOCATED":
        batch["status"] = "CONSUMED"
        touch(batch)
    return ok("run", run)


@bp.post("/mill/production-runs/<production_run_id>/apply-backing")
def apply_backing(production_run_id):
    authenticate(PLANNER_ROLES)
    body = json_body()
    sbr_pct = req_num(body, "sbr_pct", 1, ge=30, le=70)
    filler_load_pct = req_num(body, "filler_load_pct", 1, ge=0, le=60)
    cure_temp_c = req_int(body, "cure_temp_c", ge=100, le=200)
    cure_seconds = req_int(body, "cure_seconds", ge=1)
    secondary_backing_type = req_enum(body, "secondary_backing_type", BACKING_TYPES)

    run = fetch("runs", production_run_id)
    if run["status"] != "GREIGE":
        raise ApiError("ERR_INVALID_STATE", "Only a GREIGE run may take backing")

    strength = calc.delamination_strength_lbf(
        sbr_pct, filler_load_pct, cure_seconds, cure_temp_c, secondary_backing_type
    )

    run["sbr_pct"] = sbr_pct
    run["filler_load_pct"] = filler_load_pct
    run["cure_temp_c"] = cure_temp_c
    run["cure_seconds"] = cure_seconds
    run["secondary_backing_type"] = secondary_backing_type
    run["delamination_strength_lbf"] = strength
    run["status"] = "BACKED" if calc.delamination_passes(strength) else "BACKING_FAILED"
    touch(run)
    return ok("run", run)


@bp.post("/mill/production-runs/<production_run_id>/recoat")
def recoat(production_run_id):
    authenticate(PLANNER_ROLES)
    run = fetch("runs", production_run_id)
    if run["status"] != "BACKING_FAILED":
        raise ApiError("ERR_INVALID_STATE", "Only a BACKING_FAILED run may be recoated")
    if run["recoat_count"] >= calc.RECOAT_LIMIT:
        raise ApiError("ERR_RECOAT_LIMIT_REACHED", "The run has already been recoated")

    run["recoat_count"] = run["recoat_count"] + 1
    for field in (
        "sbr_pct",
        "filler_load_pct",
        "cure_temp_c",
        "cure_seconds",
        "secondary_backing_type",
        "delamination_strength_lbf",
    ):
        run[field] = None
    run["status"] = "GREIGE"
    touch(run)
    return ok("run", run)


@bp.post("/mill/production-runs/<production_run_id>/abort")
def abort(production_run_id):
    authenticate(PLANNER_ROLES)
    body = json_body()
    opt_str(body, "reason")
    run = fetch("runs", production_run_id)
    if run["status"] not in ("SCHEDULED", "HELD"):
        raise ApiError(
            "ERR_INVALID_STATE", "Only a SCHEDULED or HELD run may be aborted"
        )
    cascades.abort_run(run)
    return ok("run", run)


@bp.post("/mill/production-runs/<production_run_id>/roll-goods")
def doff_roll(production_run_id):
    authenticate(PLANNER_ROLES)
    body = json_body()
    roll_number = req_str(body, "roll_number")
    width_ft = req_num(body, "width_ft", 1, gt=0)
    initial_yards = req_num(body, "initial_yards", 1, gt=0)
    dye_lot_id = opt_id(body, "dye_lot_id")

    run = fetch("runs", production_run_id)
    lot = None
    if dye_lot_id is not None:
        lot = fetch("dye_lots", dye_lot_id)

    unique("roll_goods", "roll_number", roll_number)

    # Rung 8 — the run must have been backed.
    if run["status"] not in ("BACKED", "RELEASED"):
        raise ApiError("ERR_RUN_NOT_BACKED", "The run is not BACKED or RELEASED")

    # Rung 16 — the dye route decides whether the roll carries a lot.
    style = store.styles.get(run["style_id"])
    piece_dyed = style is not None and style["dye_method"] == "PIECE_DYED"
    if piece_dyed and dye_lot_id is None:
        raise ApiError(
            "ERR_DYE_LOT_REQUIRED", "A roll off a piece-dyed run must name a dye lot"
        )
    if not piece_dyed and dye_lot_id is not None:
        raise ApiError(
            "ERR_SOLUTION_DYED_NO_DYE_LOT",
            "A roll off a solution-dyed run must not name a dye lot",
        )

    shade_band = lot["shade_band"] if piece_dyed else "SOLUTION"

    roll = insert(
        store.roll_goods,
        {
            "roll_number": roll_number,
            "production_run_id": run["id"],
            "dye_lot_id": dye_lot_id,
            "parent_roll_id": None,
            "width_ft": width_ft,
            "initial_yards": initial_yards,
            "available_yards": initial_yards,
            "shade_band": shade_band,
            "is_remnant": False,
            "qa_status": "PENDING",
            "inventory_status": "IN_PROCESS",
            "_split_yards": 0.0,
        },
    )
    return created("roll_good", roll)


@bp.get("/mill/production-runs/<production_run_id>")
def read_run(production_run_id):
    authenticate(RUN_READ_ROLES)
    return ok("run", fetch("runs", production_run_id))


@bp.get("/mill/production-runs")
def list_runs():
    authenticate(RUN_READ_ROLES)
    return listing(
        "run",
        "runs",
        enum_filters={"status": RUN_STATUSES},
        value_filters=("style_id", "machine_id", "fiber_batch_id"),
    )
