"""Storage bins, placements, FIFO withdrawals, and fumigation (PRD §3.5, §3.6)."""
from flask import Blueprint, request

import db
import response
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_ENUM, ERR_BIN_NOT_FOUND,
    ERR_LOT_NOT_FOUND, ERR_NOT_FOUND, ERR_FUMIGATION_NOT_FOUND,
    ERR_BIN_FUMIGATION_ACTIVE, ERR_BIN_PRODUCT_MISMATCH,
    ERR_BIN_CAPACITY_EXCEEDED, ERR_LOT_OUTPUT_EXCEEDED,
    ERR_INSUFFICIENT_STORED, ERR_FUMIGATION_TIME_CONFLICT,
    ERR_SCHEDULE_WINDOW_NOT_OPEN, ERR_INVALID_STATE,
)
from middleware import authenticate, require_roles, body
from validate import (
    req_string, req_number, req_int, req_enum, opt_enum_filter, check_range,
    check_state, PRODUCT_FORMS, BIN_STATUSES, PLACEMENT_STATUSES,
    FUMIGATION_STATUSES, FUMIGATION_TERMINAL,
)
from services import calc, cascade
from services.serialize import bin_out, placement_out, withdrawal_out, fumigation_out

bp = Blueprint("storage", __name__)

BIN_ROLES = ["PlantAdmin", "PlantOperator"]


def _get_bin_or_404(rid):
    rec = db.store.bins.get(rid)
    if rec is None:
        raise ApiError(ERR_BIN_NOT_FOUND, 404, "Bin not found: %s" % rid)
    return rec


def _check_bin_available(bin_rec):
    """Safety lockout (7); lazy clearance has already run for this request."""
    if bin_rec["status"] != "AVAILABLE":
        raise ApiError(ERR_BIN_FUMIGATION_ACTIVE, 422,
                       "Bin is in %s status (fumigation lockout)" % bin_rec["status"])


# -------------------------------------------------------------------- bins

@bp.route("/bins", methods=["POST"])
def create_bin():
    auth = authenticate()
    require_roles(auth, ["PlantAdmin"])
    b = body()
    bin_code = req_string(b, "bin_code")
    capacity = check_range(req_int(b, "capacity_lbs"), "capacity_lbs", gt=0)
    forms = b.get("allowed_product_forms")
    if forms is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: allowed_product_forms")
    if not isinstance(forms, list) or len(forms) == 0:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "allowed_product_forms must be a non-empty list")
    for f in forms:
        if not isinstance(f, str) or f not in PRODUCT_FORMS:
            raise ApiError(ERR_INVALID_ENUM, 400,
                           "allowed_product_forms entries must be in %s" % list(PRODUCT_FORMS))
    for x in db.store.bins.values():
        if x["bin_code"] == bin_code:
            raise ApiError(ERR_INVALID_REQUEST, 400, "bin_code must be unique across bins")
    rec = db.stamp({
        "id": db.new_id(),
        "bin_code": bin_code,
        "capacity_lbs": capacity,
        "allowed_product_forms": list(forms),
        "status": "AVAILABLE",
        "fumigation_cleared_at": None,
    })
    db.store.bins[rec["id"]] = rec
    return response.ok(bin_out(rec), 201)


@bp.route("/bins", methods=["GET"])
def list_bins():
    auth = authenticate()
    require_roles(auth, BIN_ROLES)
    status = opt_enum_filter(request.args, "status", BIN_STATUSES)
    items = list(db.store.bins.values())
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return response.paginate(items, bin_out)


@bp.route("/bins/<rid>", methods=["GET"])
def get_bin(rid):
    auth = authenticate()
    require_roles(auth, BIN_ROLES)
    return response.ok(bin_out(_get_bin_or_404(rid)))


# -------------------------------------------------------------- placements

@bp.route("/placements", methods=["POST"])
def create_placement():
    auth = authenticate()
    require_roles(auth, ["PlantOperator"])
    b = body()
    # existence (3): canonical FK order — lot_id before bin_id
    lot_id = b.get("lot_id")
    if lot_id is not None and lot_id not in db.store.lots:
        raise ApiError(ERR_LOT_NOT_FOUND, 404, "Lot not found: %s" % lot_id)
    bin_id = b.get("bin_id")
    if bin_id is not None and bin_id not in db.store.bins:
        raise ApiError(ERR_BIN_NOT_FOUND, 404, "Bin not found: %s" % bin_id)
    # shape (5)
    lot_id = req_string(b, "lot_id")
    bin_id = req_string(b, "bin_id")
    product_form = req_enum(b, "product_form", PRODUCT_FORMS)
    quantity = check_range(req_number(b, "quantity_lbs"), "quantity_lbs", gt=0)
    lot = db.store.lots[lot_id]
    bin_rec = db.store.bins[bin_id]
    # state (6): the source lot must be PROCESSED
    if lot["status"] != "PROCESSED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Source lot must be PROCESSED, is %s" % lot["status"])
    # safety (7)
    _check_bin_available(bin_rec)
    # physical (9): product form admissibility, capacity, lot output ceiling
    if product_form not in bin_rec["allowed_product_forms"]:
        raise ApiError(ERR_BIN_PRODUCT_MISMATCH, 422,
                       "Bin does not admit product form %s" % product_form)
    occupied, _, _ = calc.bin_capacity(bin_rec)
    if calc.D(occupied) + calc.D(quantity) > calc.D(bin_rec["capacity_lbs"]):
        raise ApiError(ERR_BIN_CAPACITY_EXCEEDED, 422,
                       "occupied_lbs + quantity_lbs exceeds bin capacity")
    placed = calc.cumulative_placed(lot_id, product_form)
    output = calc.lot_output_for_form(lot_id, product_form)
    if placed + calc.D(quantity) > calc.D(output):
        raise ApiError(ERR_LOT_OUTPUT_EXCEEDED, 422,
                       "Cumulative placed weight exceeds the lot's output of %s" % product_form)
    rec = db.stamp({
        "id": db.new_id(),
        "bin_id": bin_id,
        "lot_id": lot_id,
        "product_form": product_form,
        "quantity_lbs": calc.round2(quantity),
        "remaining_lbs": calc.round2(quantity),
        "placed_at": db.now_ts(),
        "status": "STORED",
    })
    db.store.placements[rec["id"]] = rec
    db.touch(bin_rec)
    return response.ok(placement_out(rec), 201)


@bp.route("/placements", methods=["GET"])
def list_placements():
    auth = authenticate()
    require_roles(auth, BIN_ROLES)
    bin_id = request.args.get("bin_id")
    lot_id = request.args.get("lot_id")
    status = opt_enum_filter(request.args, "status", PLACEMENT_STATUSES)
    items = list(db.store.placements.values())
    if bin_id is not None:
        items = [p for p in items if p["bin_id"] == bin_id]
    if lot_id is not None:
        items = [p for p in items if p["lot_id"] == lot_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return response.paginate(items, placement_out)


@bp.route("/placements/<rid>", methods=["GET"])
def get_placement(rid):
    auth = authenticate()
    require_roles(auth, BIN_ROLES)
    rec = db.store.placements.get(rid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Placement not found: %s" % rid)
    return response.ok(placement_out(rec))


# -------------------------------------------------------------- withdrawals

@bp.route("/withdrawals", methods=["POST"])
def create_withdrawal():
    auth = authenticate()
    require_roles(auth, ["PlantOperator"])
    b = body()
    bin_id = b.get("bin_id")
    if bin_id is not None and bin_id not in db.store.bins:
        raise ApiError(ERR_BIN_NOT_FOUND, 404, "Bin not found: %s" % bin_id)
    bin_id = req_string(b, "bin_id")
    product_form = req_enum(b, "product_form", PRODUCT_FORMS)
    quantity = check_range(req_number(b, "quantity_lbs"), "quantity_lbs", gt=0)
    bin_rec = db.store.bins[bin_id]
    # safety (7)
    _check_bin_available(bin_rec)
    # fiscal (10): FIFO free pool
    allocations, remaining_need = calc.fifo_allocate(bin_id, product_form, quantity)
    if remaining_need > 0:
        raise ApiError(ERR_INSUFFICIENT_STORED, 422,
                       "FIFO free pool of matching STORED placements is insufficient")
    # commit consumption
    for a in allocations:
        p = db.store.placements[a["placement_id"]]
        p["remaining_lbs"] = calc.round2(calc.D(p["remaining_lbs"]) - calc.D(a["quantity_lbs"]))
        if calc.D(p["remaining_lbs"]) <= 0:
            p["remaining_lbs"] = 0
            p["status"] = "WITHDRAWN"
        db.touch(p)
    rec = db.stamp({
        "id": db.new_id(),
        "bin_id": bin_id,
        "product_form": product_form,
        "quantity_lbs": calc.round2(quantity),
        "allocations": allocations,
        "withdrawn_at": db.now_ts(),
    })
    db.store.withdrawals[rec["id"]] = rec
    db.touch(bin_rec)
    return response.ok(withdrawal_out(rec), 201)


@bp.route("/withdrawals", methods=["GET"])
def list_withdrawals():
    auth = authenticate()
    require_roles(auth, BIN_ROLES)
    bin_id = request.args.get("bin_id")
    items = list(db.store.withdrawals.values())
    if bin_id is not None:
        items = [w for w in items if w["bin_id"] == bin_id]
    return response.paginate(items, withdrawal_out)


@bp.route("/withdrawals/<rid>", methods=["GET"])
def get_withdrawal(rid):
    auth = authenticate()
    require_roles(auth, BIN_ROLES)
    rec = db.store.withdrawals.get(rid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Withdrawal not found: %s" % rid)
    return response.ok(withdrawal_out(rec))


# -------------------------------------------------------------- fumigations

@bp.route("/fumigations", methods=["POST"])
def create_fumigation():
    auth = authenticate()
    require_roles(auth, ["PlantAdmin"])
    b = body()
    bin_id = b.get("bin_id")
    if bin_id is not None and bin_id not in db.store.bins:
        raise ApiError(ERR_BIN_NOT_FOUND, 404, "Bin not found: %s" % bin_id)
    bin_id = req_string(b, "bin_id")
    start_raw = req_string(b, "start_at")
    start_dt = db.parse_iso(start_raw)
    if start_dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "start_at must be an ISO 8601 timestamp")
    aeration_hours = check_range(req_int(b, "aeration_hours"), "aeration_hours", gt=0)
    # temporal (8): closed-interval overlap including the aeration buffer
    if calc.fumigation_conflict(bin_id, start_dt, aeration_hours):
        raise ApiError(ERR_FUMIGATION_TIME_CONFLICT, 409,
                       "Fumigation overlaps an existing event's [start_at, effective_end] interval")
    rec = db.stamp({
        "id": db.new_id(),
        "bin_id": bin_id,
        "start_at": start_raw,
        "aeration_hours": aeration_hours,
        "cleared_at": None,
        "status": "SCHEDULED",
        "_start_dt": start_dt,
        "_cleared_dt": None,
    })
    db.store.fumigations[rec["id"]] = rec
    return response.ok(fumigation_out(rec), 201)


@bp.route("/fumigations", methods=["GET"])
def list_fumigations():
    auth = authenticate()
    require_roles(auth, BIN_ROLES)
    bin_id = request.args.get("bin_id")
    status = opt_enum_filter(request.args, "status", FUMIGATION_STATUSES)
    items = list(db.store.fumigations.values())
    if bin_id is not None:
        items = [e for e in items if e["bin_id"] == bin_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return response.paginate(items, fumigation_out)


def _get_fumigation_or_404(rid):
    rec = db.store.fumigations.get(rid)
    if rec is None:
        raise ApiError(ERR_FUMIGATION_NOT_FOUND, 404, "Fumigation event not found: %s" % rid)
    return rec


@bp.route("/fumigations/<rid>", methods=["GET"])
def get_fumigation(rid):
    auth = authenticate()
    require_roles(auth, BIN_ROLES)
    return response.ok(fumigation_out(_get_fumigation_or_404(rid)))


@bp.route("/fumigations/<rid>/start", methods=["POST"])
def start_fumigation(rid):
    auth = authenticate()
    require_roles(auth, ["PlantAdmin"])
    event = _get_fumigation_or_404(rid)
    # state (6): event must be SCHEDULED and the bin AVAILABLE
    check_state(event, ("SCHEDULED",), FUMIGATION_TERMINAL, "FumigationEvent")
    bin_rec = db.store.bins[event["bin_id"]]
    if bin_rec["status"] != "AVAILABLE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Bin is in state %s, expected AVAILABLE" % bin_rec["status"])
    # temporal (8)
    if db.store.clock < event["_start_dt"]:
        raise ApiError(ERR_SCHEDULE_WINDOW_NOT_OPEN, 422,
                       "The logical clock has not reached start_at")
    event["status"] = "ACTIVE"
    db.touch(event)
    cascade.fumigation_start_cascade(event, bin_rec)
    return response.ok(fumigation_out(event))


@bp.route("/fumigations/<rid>/begin-aeration", methods=["POST"])
def begin_aeration(rid):
    auth = authenticate()
    require_roles(auth, ["PlantAdmin"])
    event = _get_fumigation_or_404(rid)
    check_state(event, ("ACTIVE",), FUMIGATION_TERMINAL, "FumigationEvent")
    from datetime import timedelta
    cleared_dt = db.store.clock + timedelta(hours=event["aeration_hours"])
    event["status"] = "AERATING"
    event["_cleared_dt"] = cleared_dt
    event["cleared_at"] = db.fmt_clock(cleared_dt)
    db.touch(event)
    bin_rec = db.store.bins[event["bin_id"]]
    bin_rec["status"] = "AERATING"
    bin_rec["fumigation_cleared_at"] = event["cleared_at"]
    db.touch(bin_rec)
    return response.ok(fumigation_out(event))


@bp.route("/fumigations/<rid>/cancel", methods=["POST"])
def cancel_fumigation(rid):
    auth = authenticate()
    require_roles(auth, ["PlantAdmin"])
    event = _get_fumigation_or_404(rid)
    check_state(event, ("SCHEDULED",), FUMIGATION_TERMINAL, "FumigationEvent")
    event["status"] = "CANCELLED"
    db.touch(event)
    return response.ok(fumigation_out(event))
