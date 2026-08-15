"""CallTicket endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from db import store, clock
from errors import (
    ApiError,
    ERR_CALL_TICKET_NOT_FOUND,
    ERR_CALL_TICKET_INVALID_STATE,
    ERR_STALE_CALL_TICKET_VERSION,
    ERR_UNIT_NOT_FOUND,
    ERR_TECHNICIAN_NOT_FOUND,
    ERR_TECHNICIAN_NOT_ON_SHIFT,
    ERR_FATIGUE_REST_REQUIRED,
    ERR_NOT_ASSIGNED_TECHNICIAN,
    ERR_INCIDENT_RECORD_NOT_SUBMITTED,
    ERR_RELOCATION_UNRESOLVED,
    ERR_INVALID_REQUEST,
)
from helpers import (
    body,
    req_string,
    req_enum,
    req_bool,
    new_id,
    serialize_call_ticket,
    serialize_work_order,
    touch,
    pagination_params,
    minutes_between,
)
from middleware import get_actor, require_role, require_supervisor_capable
from response import success_object, success_list
from services.calculations import (
    sla_target_for_category,
    compute_callback_pay,
    compute_callback_minutes_168h,
    fatigue_blocked,
    FATIGUE_CAP_MINUTES,
    REST_WINDOW_HOURS,
)

bp = Blueprint("call_tickets", __name__)

CATEGORIES = {
    "GAS_LEAK", "FLOOD", "NO_HEAT", "NO_POWER",
    "LOCKOUT", "LEAK_MINOR", "APPLIANCE", "OTHER",
}

READ_ROLES = {
    "PropertyAdmin", "Dispatcher", "OnCallTechnician", "MaintenanceSupervisor", "Vendor",
}


def _auto_work_order(ticket, priority):
    now = clock.now()
    wo = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 0,
        "call_ticket_id": ticket["id"],
        "unit_id": ticket["unit_id"],
        "parent_work_order_id": None,
        "title": f"{priority} follow-up for call ticket {ticket['id']}",
        "description": f"Auto-created {priority} work order",
        "priority": priority,
        "status": "OPEN",
        "assigned_technician_id": None,
        "_seq": store.next_seq(),
    }
    store.work_orders[wo["id"]] = wo
    return wo


@bp.route("/v1/call-tickets", methods=["POST"])
def create_ticket():
    actor = get_actor()
    require_role(actor, {"Dispatcher", "PropertyAdmin"})
    data = body()
    unit_id = data.get("unit_id")
    if not isinstance(unit_id, str) or not unit_id:
        raise ApiError(ERR_INVALID_REQUEST, "unit_id is required", 400)
    caller_name = req_string(data, "caller_name")
    caller_phone = req_string(data, "caller_phone")
    category = req_enum(data, "category", CATEGORIES)
    description = req_string(data, "description")
    unit = store.units.get(unit_id)
    if unit is None:
        raise ApiError(ERR_UNIT_NOT_FOUND, "Unit not found", 404)
    now = clock.now()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 0,
        "unit_id": unit_id,
        "caller_name": caller_name,
        "caller_phone": caller_phone,
        "category": category,
        "description": description,
        "received_at": now,
        "is_true_emergency": None,
        "status": "RECEIVED",
        "sla_target_minutes": None,
        "assigned_technician_id": None,
        "triaged_at": None,
        "dispatched_at": None,
        "on_scene_at": None,
        "mitigated_at": None,
        "closed_at": None,
        "response_minutes": None,
        "response_breach": None,
        "escalation_level": 0,
        "unit_declared_uninhabitable": False,
        "callback_minutes": None,
        "callback_pay_cents": None,
        "_seq": store.next_seq(),
    }
    store.call_tickets[rec["id"]] = rec
    return success_object(serialize_call_ticket(rec), 201)


@bp.route("/v1/call-tickets", methods=["GET"])
def list_tickets():
    actor = get_actor()
    require_role(actor, READ_ROLES)
    limit, offset = pagination_params()
    unit_id = request.args.get("unit_id")
    assigned = request.args.get("assigned_technician_id")
    status = request.args.get("status")
    category = request.args.get("category")
    items = list(store.call_tickets.values())
    if unit_id is not None:
        items = [t for t in items if t["unit_id"] == unit_id]
    if assigned is not None:
        items = [t for t in items if t["assigned_technician_id"] == assigned]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    if category is not None:
        items = [t for t in items if t["category"] == category]
    items.sort(key=lambda t: (t["created_at"], t["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_call_ticket(t) for t in page], limit, offset, total)


def _get_ticket_or_404(ticket_id):
    rec = store.call_tickets.get(ticket_id)
    if rec is None:
        raise ApiError(ERR_CALL_TICKET_NOT_FOUND, "Call ticket not found", 404)
    return rec


@bp.route("/v1/call-tickets/<callTicketId>", methods=["GET"])
def get_ticket(callTicketId):
    actor = get_actor()
    require_role(actor, READ_ROLES)
    rec = _get_ticket_or_404(callTicketId)
    return success_object(serialize_call_ticket(rec))


@bp.route("/v1/call-tickets/<callTicketId>/triage", methods=["POST"])
def triage_ticket(callTicketId):
    actor = get_actor()
    require_role(actor, {"Dispatcher"})
    rec = _get_ticket_or_404(callTicketId)
    data = body()
    is_true_emergency = req_bool(data, "is_true_emergency")
    if rec["status"] != "RECEIVED":
        raise ApiError(ERR_CALL_TICKET_INVALID_STATE, "Ticket is not RECEIVED", 409)
    now = clock.now()
    rec["is_true_emergency"] = is_true_emergency
    rec["triaged_at"] = now
    if is_true_emergency:
        rec["status"] = "TRIAGED"
        rec["sla_target_minutes"] = sla_target_for_category(rec["category"])
    else:
        rec["status"] = "DEFERRED"
        _auto_work_order(rec, "DEFERRED")
    touch(rec)
    return success_object(serialize_call_ticket(rec))


@bp.route("/v1/call-tickets/<callTicketId>/dispatch", methods=["POST"])
def dispatch_ticket(callTicketId):
    actor = get_actor()
    require_role(actor, {"Dispatcher", "MaintenanceSupervisor"})
    require_supervisor_capable(actor)
    rec = _get_ticket_or_404(callTicketId)
    data = body()
    technician_id = data.get("technician_id")
    if not isinstance(technician_id, str) or not technician_id:
        raise ApiError(ERR_INVALID_REQUEST, "technician_id is required", 400)
    expected_version = data.get("expected_call_ticket_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ApiError(ERR_INVALID_REQUEST, "expected_call_ticket_version is required", 400)
    # Body FK existence (priority 3)
    tech = store.technicians.get(technician_id)
    if tech is None:
        raise ApiError(ERR_TECHNICIAN_NOT_FOUND, "Technician not found", 404)
    # State (priority 5): TRIAGED or ESCALATED only
    if rec["status"] not in ("TRIAGED", "ESCALATED"):
        raise ApiError(ERR_CALL_TICKET_INVALID_STATE, "Ticket not in TRIAGED or ESCALATED", 409)
    # OCC (priority 5)
    if expected_version != rec["version"]:
        raise ApiError(ERR_STALE_CALL_TICKET_VERSION, "Stale call ticket version", 412)
    now = clock.now()
    # Fatigue (priority 6)
    if fatigue_blocked(tech, now):
        raise ApiError(ERR_FATIGUE_REST_REQUIRED, "Technician is rest-blocked", 409)
    # On-shift (priority 7): ACTIVE technician with ACTIVE shift covering now
    if tech["status"] != "ACTIVE":
        raise ApiError(ERR_TECHNICIAN_NOT_ON_SHIFT, "Technician is not ACTIVE", 409)
    on_shift = False
    for s in store.rotation_shifts.values():
        if (
            s["technician_id"] == technician_id
            and s["status"] == "ACTIVE"
            and s["start_at"] <= now < s["end_at"]
        ):
            on_shift = True
            break
    if not on_shift:
        raise ApiError(ERR_TECHNICIAN_NOT_ON_SHIFT, "Technician has no ACTIVE shift covering now", 409)
    rec["assigned_technician_id"] = technician_id
    rec["dispatched_at"] = now
    rec["escalation_level"] = 0
    rec["status"] = "DISPATCHED"
    touch(rec)
    return success_object(serialize_call_ticket(rec))


@bp.route("/v1/call-tickets/<callTicketId>/arrive", methods=["POST"])
def arrive_ticket(callTicketId):
    actor = get_actor()
    require_role(actor, {"OnCallTechnician"})
    rec = _get_ticket_or_404(callTicketId)
    if rec["status"] not in ("DISPATCHED", "ESCALATED"):
        raise ApiError(ERR_CALL_TICKET_INVALID_STATE, "Ticket not in DISPATCHED or ESCALATED", 409)
    if actor.user_id != rec["assigned_technician_id"]:
        raise ApiError(ERR_NOT_ASSIGNED_TECHNICIAN, "Not the assigned technician", 403)
    now = clock.now()
    rec["on_scene_at"] = now
    rec["response_minutes"] = minutes_between(rec["received_at"], now)
    rec["response_breach"] = rec["response_minutes"] > rec["sla_target_minutes"]
    rec["status"] = "ON_SCENE"
    touch(rec)
    return success_object(serialize_call_ticket(rec))


@bp.route("/v1/call-tickets/<callTicketId>/escalate", methods=["POST"])
def escalate_ticket(callTicketId):
    actor = get_actor()
    require_role(actor, {"Dispatcher", "OnCallTechnician", "MaintenanceSupervisor"})
    require_supervisor_capable(actor)
    rec = _get_ticket_or_404(callTicketId)
    if rec["status"] != "DISPATCHED":
        raise ApiError(ERR_CALL_TICKET_INVALID_STATE, "Ticket is not DISPATCHED", 409)
    rec["escalation_level"] = max(1, rec["escalation_level"] + 1)
    rec["status"] = "ESCALATED"
    touch(rec)
    return success_object(serialize_call_ticket(rec))


@bp.route("/v1/call-tickets/<callTicketId>/mitigate", methods=["POST"])
def mitigate_ticket(callTicketId):
    actor = get_actor()
    require_role(actor, {"OnCallTechnician"})
    rec = _get_ticket_or_404(callTicketId)
    data = body()
    unit_uninhabitable = req_bool(data, "unit_uninhabitable")
    # mitigation_notes accepted; free-text, not stored on ticket
    if rec["status"] != "ON_SCENE":
        raise ApiError(ERR_CALL_TICKET_INVALID_STATE, "Ticket is not ON_SCENE", 409)
    if actor.user_id != rec["assigned_technician_id"]:
        raise ApiError(ERR_NOT_ASSIGNED_TECHNICIAN, "Not the assigned technician", 403)
    now = clock.now()
    rec["mitigated_at"] = now
    rec["callback_minutes"] = minutes_between(rec["dispatched_at"], now)
    rec["unit_declared_uninhabitable"] = unit_uninhabitable
    rec["status"] = "MITIGATED"
    _auto_work_order(rec, "EMERGENCY_FOLLOWUP")
    touch(rec)
    return success_object(serialize_call_ticket(rec))


@bp.route("/v1/call-tickets/<callTicketId>/close", methods=["POST"])
def close_ticket(callTicketId):
    actor = get_actor()
    require_role(actor, {"Dispatcher", "MaintenanceSupervisor"})
    require_supervisor_capable(actor)
    rec = _get_ticket_or_404(callTicketId)
    # State (priority 5)
    if rec["status"] != "MITIGATED":
        raise ApiError(ERR_CALL_TICKET_INVALID_STATE, "Ticket is not MITIGATED", 409)
    # Cross-entity gates (priority 7): incident record then relocation
    record = None
    for r in store.incident_records.values():
        if r["call_ticket_id"] == rec["id"]:
            record = r
            break
    if record is None or record["status"] not in ("SUBMITTED", "UNDER_REVIEW", "FINALIZED"):
        raise ApiError(
            ERR_INCIDENT_RECORD_NOT_SUBMITTED,
            "Incident record missing or not submitted",
            409,
        )
    if rec["unit_declared_uninhabitable"]:
        resolved = False
        for c in store.relocation_cases.values():
            if c["call_ticket_id"] == rec["id"] and c["status"] in ("APPROVED", "ACTIVE", "ENDED"):
                resolved = True
                break
        if not resolved:
            raise ApiError(
                ERR_RELOCATION_UNRESOLVED,
                "Relocation unresolved for uninhabitable unit",
                409,
            )
    now = clock.now()
    rec["closed_at"] = now
    rec["status"] = "CLOSED"
    tech = store.technicians.get(rec["assigned_technician_id"])
    rec["callback_pay_cents"] = compute_callback_pay(rec, tech)
    touch(rec)
    # CASCADE B: fatigue
    previous_total = tech["callback_minutes_168h"]
    new_total = compute_callback_minutes_168h(tech["id"], now)
    tech["callback_minutes_168h"] = new_total
    if previous_total < FATIGUE_CAP_MINUTES and new_total >= FATIGUE_CAP_MINUTES:
        block_end = rec["mitigated_at"] + timedelta(hours=REST_WINDOW_HOURS)
        tech["fatigue_block_until"] = block_end
        for s in store.rotation_shifts.values():
            if (
                s["technician_id"] == tech["id"]
                and s["status"] == "PUBLISHED"
                and s["start_at"] < block_end
                and s["end_at"] > rec["mitigated_at"]
            ):
                s["needs_coverage"] = True
                touch(s)
        touch(tech)
    elif previous_total != new_total:
        touch(tech)
    return success_object(serialize_call_ticket(rec))
