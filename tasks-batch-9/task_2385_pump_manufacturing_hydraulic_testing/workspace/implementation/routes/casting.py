"""Pouring, pattern wear and casting quality (PRD section 3.4)."""

from flask import Blueprint, g

from db import by_seq, db, new_record
from errors import ApiError
from helpers import (
    apply_filters,
    defects_of,
    lots_of_foundry,
    lots_of_pattern,
    paginate,
    path_lookup,
    ref_lookup,
    touch,
)
from middleware import ALL_ROLES, authorize
from response import list_response, object_response
from serializers import dump, dump_all
from services.cascades import (
    maybe_quarantine_lot,
    maybe_restore_lot,
    recompute_committed_build_count,
    recompute_lot_ledger,
    recompute_pattern_wear,
)
from validation import (
    ALLOYS,
    DEFECT_TYPES,
    DISPOSITIONS,
    SEVERITIES,
    check_keys,
    get_body,
    pagination,
    query_value,
    req_datetime,
    req_enum,
    req_int,
    req_string,
)

bp = Blueprint("casting", __name__)


def _no_body_allowed():
    check_keys(get_body(), ())


def _collection(records, limit, offset):
    window, total = paginate(records, limit, offset)
    return list_response(dump_all(window), limit, offset, total)


# ----------------------------------------------------------------- casting lots


@bp.post("/casting-lots")
def create_casting_lot():
    authorize("FoundryPartner")
    body = get_body()
    check_keys(
        body,
        (
            "pattern_asset_id",
            "foundry_id",
            "heat_number",
            "alloy_code",
            "qty_poured",
            "pour_window_start",
            "pour_window_end",
        ),
    )
    pattern_asset_id = req_string(body, "pattern_asset_id")
    foundry_id = req_string(body, "foundry_id")
    heat_number = req_string(body, "heat_number")
    alloy_code = req_enum(body, "alloy_code", ALLOYS)
    # Rung 3 checks the type only; the >= 1 bound is deferred to rung 13.
    qty_poured = req_int(body, "qty_poured")
    window_start = req_datetime(body, "pour_window_start")
    window_end = req_datetime(body, "pour_window_end")

    pattern = ref_lookup(db.pattern_assets, pattern_asset_id)
    foundry = ref_lookup(db.foundries, foundry_id)

    if g.user_id != foundry_id:
        raise ApiError("ERR_FOUNDRY_SCOPE_VIOLATION")
    if qty_poured < 1:
        raise ApiError("ERR_ZERO_QUANTITY")
    if pattern["status"] != "QUALIFIED":
        raise ApiError("ERR_PATTERN_INVALID_STATE")
    if foundry["status"] != "ACTIVE":
        raise ApiError("ERR_FOUNDRY_SUSPENDED")
    if alloy_code not in foundry["approved_alloys"]:
        raise ApiError("ERR_ALLOY_NOT_APPROVED")

    # Rung 51: the pattern is one physical object -- closed-interval comparison,
    # so windows that merely touch at an endpoint conflict.
    for lot in lots_of_pattern(pattern_asset_id):
        if lot["status"] == "SCRAPPED":
            continue
        if lot["pour_window_start"] <= window_end and window_start <= lot["pour_window_end"]:
            raise ApiError("ERR_PATTERN_WINDOW_CONFLICT")

    # Rung 52: foundry capacity counts simultaneous pours -- half-open comparison.
    overlapping = 0
    for lot in lots_of_foundry(foundry_id):
        if lot["status"] == "SCRAPPED":
            continue
        if lot["pour_window_start"] < window_end and window_start < lot["pour_window_end"]:
            overlapping += 1
    if overlapping >= foundry["concurrent_pour_capacity"]:
        raise ApiError("ERR_FOUNDRY_POUR_CAPACITY_EXCEEDED")

    if not window_start < window_end:
        raise ApiError("ERR_INVALID_WINDOW")

    record = new_record(
        "CastingLot",
        pattern_asset_id=pattern_asset_id,
        foundry_id=foundry_id,
        heat_number=heat_number,
        alloy_code=alloy_code,
        qty_poured=qty_poured,
        pour_window_start=window_start,
        pour_window_end=window_end,
        qty_scrapped=0,
        qty_rework_pending=0,
        qty_accepted=qty_poured,
        committed_build_count=0,
        status="POURED",
    )
    db.casting_lots[record["id"]] = record

    # Cascade C hop 1: the pour advances the tooling's wear curve.
    pattern["pours_since_refurb"] += 1
    recompute_pattern_wear(pattern)
    return object_response(dump(record), 201)


@bp.get("/casting-lots")
def list_casting_lots():
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    records = apply_filters(
        by_seq(db.casting_lots.values()),
        [
            (query_value("pattern_asset_id"), "pattern_asset_id"),
            (query_value("foundry_id"), "foundry_id"),
            (query_value("status"), "status"),
        ],
    )
    return _collection(records, limit, offset)


@bp.get("/casting-lots/<resource_id>")
def read_casting_lot(resource_id):
    authorize(*ALL_ROLES)
    return object_response(dump(path_lookup(db.casting_lots, resource_id)))


@bp.post("/casting-lots/<resource_id>/inspect")
def inspect_casting_lot(resource_id):
    authorize("QualityInspector")
    _no_body_allowed()
    lot = path_lookup(db.casting_lots, resource_id)
    if lot["status"] not in ("POURED", "REWORK"):
        raise ApiError("ERR_CASTING_LOT_INVALID_STATE")
    lot["status"] = "INSPECTED"
    touch(lot)
    return object_response(dump(lot))


@bp.post("/casting-lots/<resource_id>/accept")
def accept_casting_lot(resource_id):
    authorize("QualityInspector")
    _no_body_allowed()
    lot = path_lookup(db.casting_lots, resource_id)
    if lot["status"] != "INSPECTED":
        raise ApiError("ERR_CASTING_LOT_INVALID_STATE")
    for defect in defects_of(lot["id"]):
        if defect["status"] == "REPORTED":
            raise ApiError("ERR_OPEN_DEFECTS_PRESENT")
    if lot["qty_accepted"] < 1:
        raise ApiError("ERR_NO_ACCEPTABLE_CASTINGS")
    lot["status"] = "ACCEPTED"
    touch(lot)
    return object_response(dump(lot))


@bp.post("/casting-lots/<resource_id>/rework-start")
def rework_casting_lot(resource_id):
    authorize("QualityInspector")
    _no_body_allowed()
    lot = path_lookup(db.casting_lots, resource_id)
    if lot["status"] != "QUARANTINED":
        raise ApiError("ERR_CASTING_LOT_INVALID_STATE")
    lot["status"] = "REWORK"
    touch(lot)
    return object_response(dump(lot))


@bp.post("/casting-lots/<resource_id>/scrap-lot")
def scrap_casting_lot(resource_id):
    authorize("QualityInspector")
    _no_body_allowed()
    lot = path_lookup(db.casting_lots, resource_id)
    if lot["status"] != "QUARANTINED":
        raise ApiError("ERR_CASTING_LOT_INVALID_STATE")
    lot["status"] = "SCRAPPED"
    lot["qty_scrapped"] = lot["qty_poured"]
    lot["qty_rework_pending"] = 0
    lot["qty_accepted"] = 0
    recompute_committed_build_count(lot)
    touch(lot)
    return object_response(dump(lot))


# --------------------------------------------------------------- casting defects


def _first_critical_since_refurb(pattern, lot, this_defect_id):
    """True when this CRITICAL defect is the first one on the lot since refurb."""
    boundary = pattern.get("_last_refurb_seq")
    for defect in defects_of(lot["id"]):
        if defect["id"] == this_defect_id or defect["severity"] != "CRITICAL":
            continue
        if boundary is not None and defect["_seq"] <= boundary:
            continue
        return False
    return True


@bp.post("/casting-lots/<resource_id>/defects")
def report_casting_defect(resource_id):
    authorize("FoundryPartner", "QualityInspector")
    body = get_body()
    check_keys(body, ("defect_code", "defect_type", "severity", "affected_qty"))
    defect_code = req_string(body, "defect_code")
    defect_type = req_enum(body, "defect_type", DEFECT_TYPES)
    severity = req_enum(body, "severity", SEVERITIES)
    affected_qty = req_int(body, "affected_qty")

    lot = path_lookup(db.casting_lots, resource_id)

    if affected_qty < 1:
        raise ApiError("ERR_ZERO_QUANTITY")
    if affected_qty > lot["qty_accepted"]:
        raise ApiError("ERR_AFFECTED_QTY_EXCEEDS_LEDGER")
    if lot["status"] == "SCRAPPED":
        raise ApiError("ERR_CASTING_LOT_INVALID_STATE")

    record = new_record(
        "CastingDefect",
        casting_lot_id=lot["id"],
        defect_code=defect_code,
        defect_type=defect_type,
        severity=severity,
        affected_qty=affected_qty,
        reported_by_user_id=g.user_id,
        dispositioned_by_user_id=None,
        disposition=None,
        status="REPORTED",
    )
    db.casting_defects[record["id"]] = record

    # Reporting never moves the piece ledger; a CRITICAL severity does move the
    # tooling's wear curve, and can withdraw the pattern inside this request.
    if severity == "CRITICAL":
        pattern = db.pattern_assets.get(lot["pattern_asset_id"])
        if pattern is not None and _first_critical_since_refurb(pattern, lot, record["id"]):
            pattern["defect_pours_since_refurb"] += 1
            recompute_pattern_wear(pattern)
    return object_response(dump(record), 201)


@bp.get("/casting-defects")
def list_casting_defects():
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    records = apply_filters(
        by_seq(db.casting_defects.values()),
        [
            (query_value("casting_lot_id"), "casting_lot_id"),
            (query_value("status"), "status"),
        ],
    )
    return _collection(records, limit, offset)


@bp.get("/casting-defects/<resource_id>")
def read_casting_defect(resource_id):
    authorize(*ALL_ROLES)
    return object_response(dump(path_lookup(db.casting_defects, resource_id)))


@bp.post("/casting-defects/<resource_id>/disposition")
def disposition_casting_defect(resource_id):
    authorize("QualityInspector")
    body = get_body()
    check_keys(body, ("disposition",))
    disposition = req_enum(body, "disposition", DISPOSITIONS)
    defect = path_lookup(db.casting_defects, resource_id)

    # Rung 8 sits above the state check at rung 17.
    if disposition == "USE_AS_IS" and defect["reported_by_user_id"] == g.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if defect["status"] != "REPORTED":
        raise ApiError("ERR_DEFECT_INVALID_STATE")

    defect["disposition"] = disposition
    defect["dispositioned_by_user_id"] = g.user_id
    if disposition == "USE_AS_IS":
        defect["status"] = "DISPOSITIONED_USE_AS_IS"
        touch(defect)
        return object_response(dump(defect))

    defect["status"] = "DISPOSITIONED_REPAIR" if disposition == "REPAIR_WELD" else "DISPOSITIONED_SCRAP"
    touch(defect)
    lot = db.casting_lots.get(defect["casting_lot_id"])
    if lot is not None:
        recompute_lot_ledger(lot)
        maybe_quarantine_lot(lot)
    return object_response(dump(defect))


@bp.post("/casting-defects/<resource_id>/revise-disposition")
def revise_disposition(resource_id):
    authorize("QualityInspector")
    body = get_body()
    check_keys(body, ("disposition",))
    disposition = req_enum(body, "disposition", DISPOSITIONS)
    defect = path_lookup(db.casting_defects, resource_id)

    if defect["status"] != "DISPOSITIONED_SCRAP":
        raise ApiError("ERR_DEFECT_INVALID_STATE")
    if disposition != "REPAIR_WELD":
        raise ApiError("ERR_DEFECT_INVALID_STATE")

    defect["status"] = "DISPOSITIONED_REPAIR"
    defect["disposition"] = "REPAIR_WELD"
    defect["dispositioned_by_user_id"] = g.user_id
    touch(defect)
    lot = db.casting_lots.get(defect["casting_lot_id"])
    if lot is not None:
        recompute_lot_ledger(lot)
        maybe_quarantine_lot(lot)
    return object_response(dump(defect))


@bp.post("/casting-defects/<resource_id>/repair-verified")
def repair_verified(resource_id):
    authorize("QualityInspector")
    _no_body_allowed()
    defect = path_lookup(db.casting_defects, resource_id)
    if defect["status"] != "DISPOSITIONED_REPAIR":
        raise ApiError("ERR_DEFECT_INVALID_STATE")
    defect["status"] = "REPAIR_VERIFIED"
    touch(defect)
    lot = db.casting_lots.get(defect["casting_lot_id"])
    if lot is not None:
        recompute_lot_ledger(lot)
        maybe_restore_lot(lot)
    return object_response(dump(defect))
