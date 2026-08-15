"""WorkOrder endpoints: create, dispatch, reschedule, start, complete (typed
cascades), verify, request-rework, cancel."""
from flask import Blueprint, request

from db import db, stamp_new, touch, now_iso
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_REFERENCED_ENTITY_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_NOT_ASSIGNED_TECHNICIAN, ERR_INVALID_STATE_TRANSITION, ERR_STALE_VERSION,
    ERR_STOP_NOT_ACTIONABLE, ERR_TECHNICIAN_WINDOW_CONFLICT,
    ERR_TECHNICIAN_NOT_ACTIVE, ERR_ACCOUNT_NOT_ACTIVE,
    ERR_EVIDENCE_PRESERVATION_HOLD, ERR_READ_ROLLBACK,
    ERR_METER_NOT_AVAILABLE_FOR_INSTALL,
)
from middleware import (
    require_roles, ALL_ROLES, body, req_str, req_enum, req_date, opt_str, req_int,
    req_dt,
)
from response import success, list_response, created_sorted
from serializers import ser_work_order, account_last_validated
from services.cascades import (
    technician_window_conflict, evidence_hold_active, create_read,
    withdraw_enrollments_for_meter, campaign_autocomplete_check,
)

bp = Blueprint("workorders", __name__)

WO_TYPES = ("RE_READ", "EXCHANGE", "TAMPER_CHECK", "ENDPOINT_SWAP")
SHIFTS = ("AM", "PM", "FULL")


def get_order(wid):
    w = db.work_orders.get(wid)
    if not w:
        raise ApiError(ERR_NOT_FOUND, "WorkOrder not found", 404)
    return w


def _ref(model, value, label):
    if value is not None and value not in model:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND, f"{label} not found", 404)


@bp.route("/work-orders", methods=["POST"])
def create():
    require_roles("Dispatcher")
    data = body()
    wo_type = req_enum(data, "work_order_type", WO_TYPES)
    account_id = req_str(data, "service_account_id")
    scheduled_date = req_date(data, "scheduled_date")
    work_shift = req_enum(data, "work_shift", SHIFTS)
    meter_id = opt_str(data, "meter_id")
    route_stop_id = opt_str(data, "route_stop_id")
    investigation_id = opt_str(data, "investigation_id")
    notes = opt_str(data, "notes")
    # type-specific reference requirements (body shape)
    if wo_type in ("EXCHANGE", "ENDPOINT_SWAP") and meter_id is None:
        raise ApiError(ERR_INVALID_REQUEST, f"{wo_type} requires meter_id", 400)
    if wo_type == "RE_READ" and route_stop_id is None:
        raise ApiError(ERR_INVALID_REQUEST, "RE_READ requires route_stop_id", 400)
    if wo_type == "TAMPER_CHECK" and investigation_id is None:
        raise ApiError(ERR_INVALID_REQUEST, "TAMPER_CHECK requires investigation_id", 400)
    # referenced entities
    _ref(db.accounts, account_id, "ServiceAccount")
    _ref(db.meters, meter_id, "Meter")
    _ref(db.stops, route_stop_id, "RouteStop")
    _ref(db.investigations, investigation_id, "Investigation")
    account = db.accounts[account_id]
    stop = db.stops.get(route_stop_id) if route_stop_id else None
    investigation = db.investigations.get(investigation_id) if investigation_id else None
    meter = db.meters.get(meter_id) if meter_id else None
    # stop actionability (priority 8) precedes the generic state gate
    if wo_type == "RE_READ" and stop["stop_status"] != "NO_READ_PENDING":
        raise ApiError(
            ERR_STOP_NOT_ACTIONABLE, "RE_READ requires a NO_READ_PENDING stop", 409
        )
    # generic state gate: TAMPER_CHECK requires a non-terminal investigation
    if wo_type == "TAMPER_CHECK" and investigation["investigation_status"] == "CLOSED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "TAMPER_CHECK requires a non-terminal investigation",
            409,
        )
    # evidence-preservation hold
    if wo_type in ("EXCHANGE", "ENDPOINT_SWAP") and meter and evidence_hold_active(meter):
        raise ApiError(
            ERR_EVIDENCE_PRESERVATION_HOLD,
            "Meter is under an evidence-preservation hold",
            409,
        )
    # account lifecycle gate
    if account["account_status"] != "ACTIVE":
        raise ApiError(ERR_ACCOUNT_NOT_ACTIVE, "Account is not ACTIVE", 409)
    rec = {
        "work_order_type": wo_type,
        "service_account_id": account_id,
        "meter_id": meter_id,
        "route_stop_id": route_stop_id,
        "investigation_id": investigation_id,
        "campaign_enrollment_id": None,
        "scheduled_date": scheduled_date,
        "work_shift": work_shift,
        "notes": notes,
        "technician_id": None,
        "work_order_status": "OPEN",
        "new_meter_id": None,
        "old_final_read_value": None,
        "new_initial_read_value": None,
        "reread_value": None,
        "reread_at": None,
        "evidence_note": None,
        "completed_at": None,
    }
    stamp_new(rec)
    db.work_orders[rec["id"]] = rec
    return success(ser_work_order(rec), code=201)


@bp.route("/work-orders", methods=["GET"])
def list_all():
    require_roles(*ALL_ROLES)
    items = list(db.work_orders.values())
    for param in ("service_account_id", "meter_id", "technician_id", "route_stop_id",
                  "investigation_id", "campaign_enrollment_id", "new_meter_id",
                  "work_order_status", "work_order_type"):
        val = request.args.get(param)
        if val is not None:
            items = [w for w in items if w[param] == val]
    return list_response([ser_work_order(w) for w in created_sorted(items)])


@bp.route("/work-orders/<wid>", methods=["GET"])
def get_one(wid):
    require_roles(*ALL_ROLES)
    return success(ser_work_order(get_order(wid)), code=200)


def _check_dispatchable(wo, technician):
    """Ladder: window conflict (17) precedes technician-active (23)."""
    if technician_window_conflict(
        technician["id"], wo["scheduled_date"], wo["work_shift"],
        exclude_order_id=wo["id"],
    ):
        raise ApiError(
            ERR_TECHNICIAN_WINDOW_CONFLICT,
            "Technician has an overlapping commitment on that date/shift",
            409,
        )
    if technician["technician_status"] != "ACTIVE":
        raise ApiError(ERR_TECHNICIAN_NOT_ACTIVE, "Technician is not ACTIVE", 409)


@bp.route("/work-orders/<wid>/dispatch", methods=["POST"])
def dispatch(wid):
    require_roles("Dispatcher")
    data = body()
    technician_id = req_str(data, "technician_id")
    wo = get_order(wid)
    _ref(db.technicians, technician_id, "FieldTechnician")
    tech = db.technicians[technician_id]
    if wo["work_order_status"] not in ("OPEN", "REWORK"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, "Work order is not OPEN or REWORK", 409
        )
    _check_dispatchable(wo, tech)
    wo["technician_id"] = technician_id
    wo["work_order_status"] = "DISPATCHED"
    touch(wo)
    return success(ser_work_order(wo), code=200)


@bp.route("/work-orders/<wid>/reschedule", methods=["POST"])
def reschedule(wid):
    require_roles("Dispatcher")
    data = body()
    scheduled_date = req_date(data, "scheduled_date")
    work_shift = req_enum(data, "work_shift", SHIFTS)
    expected = data.get("expected_work_order_version")
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, "expected_work_order_version is required", 400)
    wo = get_order(wid)
    if expected != wo["version"]:
        raise ApiError(ERR_STALE_VERSION, "WorkOrder version does not match", 412)
    if wo["work_order_status"] not in ("OPEN", "DISPATCHED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Work order can be rescheduled only from OPEN or DISPATCHED",
            409,
        )
    if wo["work_order_status"] == "DISPATCHED" and wo["technician_id"]:
        if technician_window_conflict(
            wo["technician_id"], scheduled_date, work_shift, exclude_order_id=wo["id"]
        ):
            raise ApiError(
                ERR_TECHNICIAN_WINDOW_CONFLICT,
                "New schedule conflicts with another technician commitment",
                409,
            )
    wo["scheduled_date"] = scheduled_date
    wo["work_shift"] = work_shift
    touch(wo)  # self-loop: version bump is the observable mutation
    return success(ser_work_order(wo), code=200)


def _ownership(wo, uid):
    if wo["technician_id"] != uid:
        raise ApiError(
            ERR_NOT_ASSIGNED_TECHNICIAN,
            "Caller is not the assigned technician on this work order",
            403,
        )


@bp.route("/work-orders/<wid>/start", methods=["POST"])
def start(wid):
    uid, _role = require_roles("FieldTechnician")
    wo = get_order(wid)
    _ownership(wo, uid)
    if wo["work_order_status"] != "DISPATCHED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Work order is not DISPATCHED", 409)
    wo["work_order_status"] = "IN_PROGRESS"
    touch(wo)
    return success(ser_work_order(wo), code=200)


def _complete_re_read(wo):
    stop = db.stops.get(wo["route_stop_id"])
    last_value, _ = account_last_validated(wo["service_account_id"])
    if last_value is not None and wo["reread_value"] < last_value:
        raise ApiError(
            ERR_READ_ROLLBACK,
            "reread_value is below the account's last validated read value",
            422,
        )
    meter_id = next(
        (m["id"] for m in db.meters.values()
         if m["installed_service_account_id"] == wo["service_account_id"]
         and m["meter_status"] == "IN_SERVICE"),
        None,
    )
    rec = create_read(
        route_stop_id=stop["id"],
        service_account_id=wo["service_account_id"],
        meter_id=meter_id,
        read_value=wo["reread_value"],
        read_at=wo["reread_at"],
        read_source="REREAD",
        read_status="PROVISIONAL",
    )
    stop["stop_status"] = "READ_CAPTURED"
    stop["current_read_id"] = rec["id"]
    touch(stop)


def _complete_exchange(wo):
    old_meter = db.meters.get(wo["meter_id"])
    new_meter = db.meters.get(wo["new_meter_id"])
    last_value, _ = account_last_validated(wo["service_account_id"])
    if last_value is not None and wo["old_final_read_value"] < last_value:
        raise ApiError(
            ERR_READ_ROLLBACK,
            "old_final_read_value is below the account's last validated read value",
            422,
        )
    if (
        new_meter["meter_status"] != "IN_STOCK"
        or new_meter["id"] == wo["meter_id"]
    ):
        raise ApiError(
            ERR_METER_NOT_AVAILABLE_FOR_INSTALL,
            "new_meter_id must be an IN_STOCK meter different from the removed meter",
            409,
        )
    now = now_iso()
    create_read(
        route_stop_id=None,
        service_account_id=wo["service_account_id"],
        meter_id=old_meter["id"],
        read_value=wo["old_final_read_value"],
        read_at=now,
        read_source="EXCHANGE_FINAL",
        read_status="VALIDATED",
    )
    create_read(
        route_stop_id=None,
        service_account_id=wo["service_account_id"],
        meter_id=new_meter["id"],
        read_value=wo["new_initial_read_value"],
        read_at=now,
        read_source="EXCHANGE_INITIAL",
        read_status="VALIDATED",
    )
    old_meter["meter_status"] = "REMOVED"
    old_meter["installed_service_account_id"] = None
    touch(old_meter)
    new_meter["meter_status"] = "IN_SERVICE"
    new_meter["installed_service_account_id"] = wo["service_account_id"]
    touch(new_meter)
    withdraw_enrollments_for_meter(old_meter["id"])


def _complete_tamper_check(wo):
    inv = db.investigations.get(wo["investigation_id"])
    if inv["investigation_status"] != "EVIDENCE_GATHERING":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Linked investigation is not in EVIDENCE_GATHERING",
            409,
        )
    inv["evidence_notes"] = inv["evidence_notes"] + [wo["evidence_note"]]
    touch(inv)


def _complete_endpoint_swap(wo):
    meter = db.meters.get(wo["meter_id"])
    meter["endpoint_comms_status"] = "COMMUNICATING"
    meter["consecutive_missed_days"] = 0
    meter["non_communicating_since"] = None
    touch(meter)
    if wo["campaign_enrollment_id"]:
        enr = db.enrollments.get(wo["campaign_enrollment_id"])
        if enr and enr["enrollment_status"] == "WORK_ORDER_CREATED":
            enr["enrollment_status"] = "REPLACED"
            touch(enr)
            campaign_autocomplete_check(enr["campaign_id"])


@bp.route("/work-orders/<wid>/complete", methods=["POST"])
def complete(wid):
    uid, _role = require_roles("FieldTechnician")
    data = body()
    wo = get_order(wid)
    wtype = wo["work_order_type"]
    # type-specific payload (body shape, priority 3)
    reread_value = reread_at = new_meter_id = None
    old_final = new_initial = evidence_note = None
    if wtype == "RE_READ":
        reread_value = req_int(data, "reread_value", minimum=0)
        reread_at = req_dt(data, "reread_at")
    elif wtype == "EXCHANGE":
        new_meter_id = req_str(data, "new_meter_id")
        old_final = req_int(data, "old_final_read_value", minimum=0)
        new_initial = req_int(data, "new_initial_read_value", minimum=0)
    elif wtype == "TAMPER_CHECK":
        evidence_note = req_str(data, "evidence_note")
    _ownership(wo, uid)
    if new_meter_id is not None:
        _ref(db.meters, new_meter_id, "Meter")
    # stop actionability (priority 8) precedes the order's own state gate
    if wtype == "RE_READ":
        stop = db.stops.get(wo["route_stop_id"])
        if not stop or stop["stop_status"] != "NO_READ_PENDING":
            raise ApiError(
                ERR_STOP_NOT_ACTIONABLE, "Linked stop is not NO_READ_PENDING", 409
            )
    if wo["work_order_status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Work order is not IN_PROGRESS", 409)
    wo["reread_value"] = reread_value
    wo["reread_at"] = reread_at
    wo["new_meter_id"] = new_meter_id
    wo["old_final_read_value"] = old_final
    wo["new_initial_read_value"] = new_initial
    wo["evidence_note"] = evidence_note
    if wtype == "RE_READ":
        _complete_re_read(wo)
    elif wtype == "EXCHANGE":
        _complete_exchange(wo)
    elif wtype == "TAMPER_CHECK":
        _complete_tamper_check(wo)
    elif wtype == "ENDPOINT_SWAP":
        _complete_endpoint_swap(wo)
    wo["completed_at"] = now_iso()
    wo["work_order_status"] = "COMPLETED"
    touch(wo)
    return success(ser_work_order(wo), code=200)


@bp.route("/work-orders/<wid>/verify", methods=["POST"])
def verify(wid):
    require_roles("MeterOpsAdmin")
    wo = get_order(wid)
    if wo["work_order_status"] != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Work order is not COMPLETED", 409)
    wo["work_order_status"] = "VERIFIED"
    touch(wo)
    return success(ser_work_order(wo), code=200)


@bp.route("/work-orders/<wid>/request-rework", methods=["POST"])
def request_rework(wid):
    require_roles("MeterOpsAdmin")
    data = body()
    req_str(data, "rework_reason")
    wo = get_order(wid)
    if wo["work_order_status"] != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Work order is not COMPLETED", 409)
    wo["work_order_status"] = "REWORK"
    touch(wo)
    return success(ser_work_order(wo), code=200)


@bp.route("/work-orders/<wid>/cancel", methods=["POST"])
def cancel(wid):
    require_roles("Dispatcher")
    wo = get_order(wid)
    if wo["work_order_status"] not in ("OPEN", "DISPATCHED", "REWORK"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Work order can be cancelled only from OPEN, DISPATCHED, or REWORK",
            409,
        )
    wo["work_order_status"] = "CANCELLED"
    touch(wo)
    # manual cancel returns a campaign enrollment to ENROLLED
    if wo["campaign_enrollment_id"]:
        enr = db.enrollments.get(wo["campaign_enrollment_id"])
        if enr and enr["enrollment_status"] == "WORK_ORDER_CREATED":
            enr["enrollment_status"] = "ENROLLED"
            enr["work_order_id"] = None
            touch(enr)
            campaign_autocomplete_check(enr["campaign_id"])
    return success(ser_work_order(wo), code=200)
