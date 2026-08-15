"""Finished lots: trace-lock, ship, recall; chill-chain logs."""

from datetime import timedelta
from decimal import Decimal
from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_TRACE_LOCK_BLOCKED_UNCERTIFIED,
    ERR_CHILLER_LIMIT_FRESH_BLOCKED,
    ERR_CHILL_NOT_COMPLIANT,
    ERR_INSUFFICIENT_PERMISSIONS,
)
from middleware import (
    require_roles,
    get_json_body,
    check_required,
    check_no_unknown,
    check_enum,
    check_number,
    check_string,
    parse_pagination,
)
from response import success_object, success_list
from services.core import (
    new_event,
    _touch,
    CHILL_TARGET_TEMP_C,
    CHILL_DEADLINE_HOURS,
    MIN_CHILL_HOURS,
    FRESH_YIELD_THRESHOLD_PCT,
)
from services.serializers import serialize_finished_lot, serialize_chill_log

bp = Blueprint("finished_lots", __name__)

ALL_ROLES = (
    "PlantManager", "ShiftSupervisor", "ReceivingClerk", "LineOperator",
    "QATechnician", "SanitationLead", "USDAInspector", "OrderPlanner",
)
LOCATIONS = ("CHILLER", "BLAST_FREEZER", "COLD_STORAGE", "DOCK")


@bp.route("/poultry/finished-lots", methods=["GET"])
def list_finished_lots():
    require_roles(*ALL_ROLES)
    items = list(db.finished_lots.values())
    deboning_batch_id = request.args.get("deboning_batch_id")
    order_id = request.args.get("order_id")
    if deboning_batch_id is not None:
        items = [f for f in items if f["deboning_batch_id"] == deboning_batch_id]
    if order_id is not None:
        items = [f for f in items if f["order_id"] == order_id]
    items.sort(key=lambda f: f["created_at"])
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    return success_list([serialize_finished_lot(f) for f in page], limit, offset, len(items))


@bp.route("/poultry/finished-lots/<flot_id>", methods=["GET"])
def get_finished_lot(flot_id):
    require_roles(*ALL_ROLES)
    flot = db.finished_lots.get(flot_id)
    if not flot:
        raise ApiError(ERR_NOT_FOUND, "Finished lot not found", 404)
    return success_object(serialize_finished_lot(flot))


def _source_run_reference(flot):
    """Latest completed_at among the source flock lot's COMPLETED|RECONCILED runs;
    tie-break latest created_at. Returns None when no such run exists."""
    batch = db.deboning_batches.get(flot["deboning_batch_id"])
    if not batch:
        return None
    lot = db.flock_lots.get(batch["flock_lot_id"])
    if not lot:
        return None
    runs = [
        r for r in db.line_runs.values()
        if r["flock_lot_id"] == lot["id"]
        and r["status"] in ("COMPLETED", "RECONCILED")
        and r.get("completed_at") is not None
    ]
    if not runs:
        return None
    runs.sort(key=lambda r: (r["completed_at"], r["created_at"]), reverse=True)
    return runs[0]["completed_at"]


def _chill_compliant(flot):
    ref = _source_run_reference(flot)
    if ref is None:
        return False
    deadline = ref + timedelta(hours=CHILL_DEADLINE_HOURS)
    min_dwell = ref + timedelta(hours=MIN_CHILL_HOURS)
    has_cold_log = any(
        log for log in db.chill_chain_logs.values()
        if log["finished_lot_id"] == flot["id"]
        and Decimal(str(log["temperature_c"])) <= CHILL_TARGET_TEMP_C
        and log["recorded_at"] <= deadline
    )
    if not has_cold_log:
        return False
    if db.clock_now() < min_dwell:
        return False
    return True


@bp.route("/poultry/finished-lots/<flot_id>/trace-lock", methods=["POST"])
def trace_lock(flot_id):
    require_roles("QATechnician")
    flot = db.finished_lots.get(flot_id)
    if not flot:
        raise ApiError(ERR_NOT_FOUND, "Finished lot not found", 404)
    get_json_body()  # tolerate empty/{} bodies

    if flot["status"] != "OPEN":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, "Trace-lock requires an OPEN finished lot", 409
        )

    batch = db.deboning_batches.get(flot["deboning_batch_id"])
    order = db.orders.get(flot["order_id"])
    lot = db.flock_lots.get(batch["flock_lot_id"]) if batch else None
    shift = db.shifts.get(batch["shift_id"]) if batch else None

    # Precondition 1: every condemnation record on source lot's runs CERTIFIED
    if lot:
        for r in db.line_runs.values():
            if r["flock_lot_id"] != lot["id"]:
                continue
            for c in db.condemnation_records.values():
                if c["line_run_id"] == r["id"] and c["status"] != "CERTIFIED":
                    raise ApiError(
                        ERR_TRACE_LOCK_BLOCKED_UNCERTIFIED,
                        "Trace-lock attempted while source-lot condemnation records are not all CERTIFIED",
                        409,
                    )

    temp_req = order["temperature_requirement"] if order else "FROZEN"

    if temp_req == "FRESH":
        # Precondition 2 (regulatory, first): chiller limit not breached
        if shift and shift.get("chiller_limit_breached"):
            raise ApiError(
                ERR_CHILLER_LIMIT_FRESH_BLOCKED,
                "FRESH trace-lock while the shift's chiller water limit is breached",
                409,
            )
        # Precondition 3: chill compliance
        if not _chill_compliant(flot):
            raise ApiError(
                ERR_CHILL_NOT_COMPLIANT,
                "FRESH trace-lock without a compliant chill log",
                409,
            )
        flot["routing_status"] = "FRESH"
    elif temp_req == "FROZEN":
        flot["routing_status"] = "FROZEN"
    else:  # FLEXIBLE
        chill_ok = _chill_compliant(flot)
        chiller_breached = bool(shift.get("chiller_limit_breached")) if shift else False
        if (not chill_ok) or chiller_breached:
            flot["routing_status"] = "FROZEN"
        else:
            certified = lot.get("certified_yield_pct") if lot else None
            if certified is not None and Decimal(str(certified)) >= FRESH_YIELD_THRESHOLD_PCT:
                flot["routing_status"] = "FRESH"
            else:
                flot["routing_status"] = "FROZEN"

    flot["status"] = "TRACE_LOCKED"
    flot["locked_at"] = db.clock_now()
    _touch(flot)
    return success_object(serialize_finished_lot(flot))


@bp.route("/poultry/finished-lots/<flot_id>/advance", methods=["POST"])
def advance_finished_lot(flot_id):
    user_id, role = require_roles("ShiftSupervisor", "QATechnician", "USDAInspector")
    flot = db.finished_lots.get(flot_id)
    if not flot:
        raise ApiError(ERR_NOT_FOUND, "Finished lot not found", 404)
    body = get_json_body()
    check_no_unknown(body, {"to_status", "reason"})
    check_required(body, ["to_status"])
    check_enum(body["to_status"], ("SHIPPED", "RECALLED"), "to_status")
    to_status = body["to_status"]

    if to_status == "SHIPPED":
        if role != "ShiftSupervisor":
            raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, "Role not permitted for this action", 403)
        if flot["status"] != "TRACE_LOCKED":
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION, "SHIPPED permitted only from TRACE_LOCKED", 409
            )
        flot["status"] = "SHIPPED"
        flot["shipped_at"] = db.clock_now()
        _touch(flot)
        # Order fulfillment re-evaluation
        order = db.orders.get(flot["order_id"])
        if order and order["fulfillment_status"] == "IN_PRODUCTION":
            shipped_net = Decimal("0")
            for f in db.finished_lots.values():
                if f["order_id"] == order["id"] and f["status"] == "SHIPPED":
                    shipped_net += Decimal(str(f["net_weight_lb"]))
            if shipped_net >= Decimal(str(order["pounds_ordered"])):
                order["fulfillment_status"] = "FULFILLED"
                _touch(order)
    else:  # RECALLED
        if role not in ("QATechnician", "USDAInspector"):
            raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, "Role not permitted for this action", 403)
        if flot["status"] not in ("TRACE_LOCKED", "SHIPPED"):
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION,
                "RECALLED permitted only from TRACE_LOCKED or SHIPPED",
                409,
            )
        reason = body.get("reason")
        if not isinstance(reason, str) or not reason:
            raise ApiError(ERR_INVALID_REQUEST, "reason is required", 400)
        flot["status"] = "RECALLED"
        _touch(flot)

    return success_object(serialize_finished_lot(flot))


# --------------------------- Chill-chain logs ---------------------------

@bp.route("/poultry/chill-chain-logs", methods=["POST"])
def create_chill_log():
    require_roles("QATechnician")
    body = get_json_body()
    check_no_unknown(body, {"finished_lot_id", "location", "temperature_c"})
    check_required(body, ["finished_lot_id", "location", "temperature_c"])
    check_string(body["finished_lot_id"], "finished_lot_id")
    check_enum(body["location"], LOCATIONS, "location")
    check_number(body["temperature_c"], "temperature_c")
    temp = Decimal(str(body["temperature_c"]))
    if temp < Decimal("-40") or temp > Decimal("20"):
        raise ApiError(
            ERR_INVALID_REQUEST, "temperature_c must lie between -40 and 20 inclusive", 400
        )

    flot = db.finished_lots.get(body["finished_lot_id"])
    if not flot:
        raise ApiError(ERR_NOT_FOUND, "Finished lot not found", 404)

    log = new_event()
    log.update({
        "finished_lot_id": flot["id"],
        "location": body["location"],
        "temperature_c": body["temperature_c"],
        "recorded_at": db.clock_now(),
    })
    db.chill_chain_logs[log["id"]] = log
    return success_object(serialize_chill_log(log), 201)


@bp.route("/poultry/finished-lots/<flot_id>/chill-chain-logs", methods=["GET"])
def list_chill_logs(flot_id):
    require_roles(*ALL_ROLES)
    flot = db.finished_lots.get(flot_id)
    if not flot:
        raise ApiError(ERR_NOT_FOUND, "Finished lot not found", 404)
    items = [c for c in db.chill_chain_logs.values() if c["finished_lot_id"] == flot_id]
    items.sort(key=lambda c: c["created_at"])
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    return success_list([serialize_chill_log(c) for c in page], limit, offset, len(items))
