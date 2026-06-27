"""AlarmEvent + DispatchAction endpoints (PRD 3.8, 3.9, 3.10)."""
from flask import Blueprint, request

from clock import clock
from db import store
from errors import err
from middleware import get_auth, require_role
from models import new_record, touch, serialize_alarm, serialize_dispatch
from response import object_response, array_response
from services.lookup import (get_device, get_alarm, get_contract, get_contact, get_dispatch,
                             active_contacts_for_subscriber)
from services.calculations import alarm_priority_score, sla_breach_check
from services.device_service import maybe_flag_needs_test
from util import (get_json_body, require_fields, require_enum, parse_pagination,
                  paginate, sort_by_created)

bp = Blueprint("alarms", __name__)

SIGNAL_TYPES = {"MANUAL_BUTTON", "FALL_DETECTED", "BATTERY_CRITICAL", "PERIODIC_CHECKIN_MISSED"}
ACTION_TYPES = {"CALL_SUBSCRIBER", "CALL_CONTACT", "DISPATCH_911", "MARK_FALSE_ALARM", "RESOLVE_OK"}
OUTCOMES = {"ANSWERED", "NO_ANSWER", "DISPATCHED", "CONFIRMED_OK", "CONFIRMED_FALSE"}
TERMINAL = {"RESOLVED_OK", "FALSE_ALARM", "DISPATCHED_911"}


# ---------------------------------------------------------------------------
# Raise an alarm (PRD 3.8)
# ---------------------------------------------------------------------------
@bp.route("/pers/devices/<did>/alarms", methods=["POST"])
def raise_alarm(did):
    _uid, role = get_auth()
    require_role(role, {"Subscriber", "CallCenterAgent"})
    d = get_device(did)
    body = get_json_body()
    require_fields(body, ["signal_type"])
    require_enum(body["signal_type"], SIGNAL_TYPES, "signal_type")

    # contract must be monitoring (service_status ACTIVE) — priority 10
    contract = get_contract(d["contract_id"])
    if contract["service_status"] != "ACTIVE":
        raise err("ERR_CONTRACT_NOT_MONITORING", "Contract service_status is not ACTIVE")

    # if device ACTIVE and overdue -> NEEDS_TEST first (PRD 3.8 / 3.5)
    maybe_flag_needs_test(d)

    priority = alarm_priority_score(body["signal_type"], d["fall_detection_enabled"], d["battery_health"])

    r = new_record()
    r.update({
        "device_id": did,
        "assigned_agent_id": None,
        "signal_type": body["signal_type"],
        "priority": priority,
        "status": "SIGNAL_RECEIVED",
        "signal_received_at_dt": clock.now(),
        "agent_assigned_at_dt": None,
        "resolved_at_dt": None,
        "sla_breached": False,
        "current_escalation_rank": 0,
        "dispatch_count": 0,
    })
    store.alarm_events[r["id"]] = r
    d["open_alarm_count"] += 1
    return object_response(serialize_alarm(r), 201)


@bp.route("/pers/alarms/<aid>", methods=["GET"])
def get_alarm_route(aid):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "CallCenterAgent", "Subscriber"})
    r = get_alarm(aid)
    return object_response(serialize_alarm(r), 200)


@bp.route("/pers/alarms", methods=["GET"])
def list_alarms():
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "CallCenterAgent", "Subscriber"})
    limit, offset = parse_pagination()
    items = list(store.alarm_events.values())
    if "device_id" in request.args:
        items = [a for a in items if a["device_id"] == request.args.get("device_id")]
    if "status" in request.args:
        items = [a for a in items if a["status"] == request.args.get("status")]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([serialize_alarm(a) for a in page], limit, offset, total)


@bp.route("/pers/devices/<did>/alarms", methods=["GET"])
def list_device_alarms(did):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "CallCenterAgent", "Subscriber"})
    get_device(did)
    items = sort_by_created([a for a in store.alarm_events.values() if a["device_id"] == did])
    limit, offset = parse_pagination()
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([serialize_alarm(a) for a in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Assign (PRD 3.9)
# ---------------------------------------------------------------------------
@bp.route("/pers/alarms/<aid>/assign", methods=["POST"])
def assign_alarm(aid):
    uid, role = get_auth()
    require_role(role, {"CallCenterAgent"})
    a = get_alarm(aid)
    # state (priority 5)
    if a["status"] != "SIGNAL_RECEIVED":
        raise err("ERR_INVALID_STATE", "Alarm is not SIGNAL_RECEIVED")
    # shift coverage (priority 9): SCHEDULED shift for this agent covering now
    now = clock.now()
    covered = False
    for sh in store.agent_shifts.values():
        if sh["status"] == "SCHEDULED" and sh["agent_user_id"] == uid:
            if sh["starts_at_dt"] <= now < sh["ends_at_dt"]:
                covered = True
                break
    if not covered:
        raise err("ERR_NO_SHIFT_COVERAGE", "No SCHEDULED shift covers the current instant for this agent")

    a["assigned_agent_id"] = uid
    a["agent_assigned_at_dt"] = now
    # SLA breach via plan pinned on device's contract
    device = store.devices.get(a["device_id"])
    contract = store.contracts.get(device["contract_id"]) if device else None
    plan = store.monitoring_plans.get(contract["plan_id"]) if contract else None
    sla_seconds = plan["response_sla_seconds"] if plan else None
    if sla_seconds is not None:
        a["sla_breached"] = sla_breach_check(now, a["signal_received_at_dt"], sla_seconds)
    a["status"] = "AGENT_ASSIGNED"
    touch(a)
    return object_response(serialize_alarm(a), 200)


# ---------------------------------------------------------------------------
# Dispatch actions (PRD 3.10) — the branching protocol
# ---------------------------------------------------------------------------
def _terminal_bookkeeping(alarm):
    alarm["resolved_at_dt"] = clock.now()
    device = store.devices.get(alarm["device_id"])
    if device is not None and device["open_alarm_count"] > 0:
        device["open_alarm_count"] -= 1


def _has_authorizing_contact(alarm):
    """An answered CALL_CONTACT whose contact can_authorize_911 == true (PRD 3.10)."""
    for da in store.dispatch_actions.values():
        if da["alarm_event_id"] != alarm["id"]:
            continue
        if da["action_type"] == "CALL_CONTACT" and da["outcome"] == "ANSWERED":
            c = store.emergency_contacts.get(da.get("target_contact_id"))
            if c is not None and c.get("can_authorize_911"):
                return True
    return False


def _record_dispatch(alarm, action_type, outcome, target_contact_id):
    da = new_record()
    da.update({
        "alarm_event_id": alarm["id"],
        "action_type": action_type,
        "target_contact_id": target_contact_id,
        "outcome": outcome,
        "recorded_at_dt": clock.now(),
    })
    store.dispatch_actions[da["id"]] = da
    alarm["dispatch_count"] += 1
    return da


@bp.route("/pers/alarms/<aid>/dispatch-actions", methods=["POST"])
def create_dispatch(aid):
    uid, role = get_auth()
    require_role(role, {"CallCenterAgent"})
    a = get_alarm(aid)
    body = get_json_body()
    require_fields(body, ["action_type", "outcome"])
    require_enum(body["action_type"], ACTION_TYPES, "action_type")
    require_enum(body["outcome"], OUTCOMES, "outcome")
    action_type = body["action_type"]
    outcome = body["outcome"]
    target_contact_id = body.get("target_contact_id")

    # FK existence for target_contact_id (priority 3)
    if target_contact_id is not None:
        get_contact(target_contact_id)

    # assigned-agent ownership (priority 6)
    if a["assigned_agent_id"] != uid:
        raise err("ERR_NOT_ASSIGNED_AGENT", "Acting agent is not the assigned agent")

    status = a["status"]
    device = store.devices.get(a["device_id"])
    subscriber_id = None
    if device is not None:
        contract = store.contracts.get(device["contract_id"])
        if contract is not None:
            subscriber_id = contract["subscriber_id"]

    # ---- branch resolution by (status, action_type, outcome) ----
    if status == "AGENT_ASSIGNED":
        if action_type == "CALL_SUBSCRIBER":
            a["status"] = "CONTACTING_SUBSCRIBER"
            da = _record_dispatch(a, action_type, outcome, target_contact_id)
            touch(a)
            return object_response(serialize_dispatch(da), 201)
        raise err("ERR_INVALID_STATE", "Invalid action for AGENT_ASSIGNED")

    if status == "CONTACTING_SUBSCRIBER":
        if action_type == "RESOLVE_OK" and outcome == "CONFIRMED_OK":
            a["status"] = "RESOLVED_OK"
            da = _record_dispatch(a, action_type, outcome, target_contact_id)
            _terminal_bookkeeping(a)
            touch(a)
            return object_response(serialize_dispatch(da), 201)
        if action_type == "MARK_FALSE_ALARM" and outcome == "CONFIRMED_FALSE":
            a["status"] = "FALSE_ALARM"
            da = _record_dispatch(a, action_type, outcome, target_contact_id)
            _terminal_bookkeeping(a)
            touch(a)
            return object_response(serialize_dispatch(da), 201)
        if action_type == "CALL_SUBSCRIBER" and outcome == "NO_ANSWER":
            # escalate: requires at least one active contact
            actives = active_contacts_for_subscriber(subscriber_id) if subscriber_id else []
            if not actives:
                raise err("ERR_INVALID_STATE", "No active emergency contact to escalate to")
            lowest = min(actives, key=lambda c: c["priority_rank"])
            a["status"] = "ESCALATING"
            a["current_escalation_rank"] = lowest["priority_rank"]
            da = _record_dispatch(a, action_type, outcome, target_contact_id)
            touch(a)
            return object_response(serialize_dispatch(da), 201)
        if action_type == "DISPATCH_911" and outcome == "DISPATCHED":
            # direct 911 from CONTACTING requires CRITICAL priority (priority 8)
            if a["priority"] != "CRITICAL":
                raise err("ERR_911_NOT_AUTHORIZED", "911 requires CRITICAL priority or an authorizing contact")
            a["status"] = "DISPATCHED_911"
            da = _record_dispatch(a, action_type, outcome, target_contact_id)
            _terminal_bookkeeping(a)
            touch(a)
            return object_response(serialize_dispatch(da), 201)
        raise err("ERR_INVALID_STATE", "Invalid action for CONTACTING_SUBSCRIBER")

    if status == "ESCALATING":
        if action_type == "CALL_CONTACT":
            # escalation order: target must be the active contact whose rank == current_escalation_rank
            target = store.emergency_contacts.get(target_contact_id) if target_contact_id else None
            if (target is None or not target.get("active")
                    or target["subscriber_id"] != subscriber_id
                    or target["priority_rank"] != a["current_escalation_rank"]):
                raise err("ERR_ESCALATION_ORDER", "CALL_CONTACT must target the current-rank active contact")
            if outcome == "NO_ANSWER":
                nxt_id = target.get("escalates_to_contact_id")
                nxt = store.emergency_contacts.get(nxt_id) if nxt_id else None
                if nxt is not None and nxt.get("active"):
                    a["current_escalation_rank"] = nxt["priority_rank"]
                    da = _record_dispatch(a, action_type, outcome, target_contact_id)
                    touch(a)
                    return object_response(serialize_dispatch(da), 201)
                # no further active fallback: record the call but stay ESCALATING
                da = _record_dispatch(a, action_type, outcome, target_contact_id)
                touch(a)
                return object_response(serialize_dispatch(da), 201)
            # ANSWERED (or other) — just record the contact call, remains ESCALATING
            da = _record_dispatch(a, action_type, outcome, target_contact_id)
            touch(a)
            return object_response(serialize_dispatch(da), 201)
        if action_type == "RESOLVE_OK":
            a["status"] = "RESOLVED_OK"
            da = _record_dispatch(a, action_type, outcome, target_contact_id)
            _terminal_bookkeeping(a)
            touch(a)
            return object_response(serialize_dispatch(da), 201)
        if action_type == "DISPATCH_911" and outcome == "DISPATCHED":
            # gate (priority 8): CRITICAL OR an authorizing answered contact
            if a["priority"] != "CRITICAL" and not _has_authorizing_contact(a):
                raise err("ERR_911_NOT_AUTHORIZED", "911 requires CRITICAL priority or an authorizing contact")
            a["status"] = "DISPATCHED_911"
            da = _record_dispatch(a, action_type, outcome, target_contact_id)
            _terminal_bookkeeping(a)
            touch(a)
            return object_response(serialize_dispatch(da), 201)
        raise err("ERR_INVALID_STATE", "Invalid action for ESCALATING")

    # SIGNAL_RECEIVED or terminal statuses: no dispatch action legal
    raise err("ERR_INVALID_STATE", "No dispatch action legal from status %s" % status)


@bp.route("/pers/alarms/<aid>/dispatch-actions", methods=["GET"])
def list_dispatch(aid):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "CallCenterAgent", "Subscriber"})
    get_alarm(aid)
    items = [d for d in store.dispatch_actions.values() if d["alarm_event_id"] == aid]
    # ordered by recorded_at ASC (PRD 2.3 / 3.10)
    items = sorted(items, key=lambda d: (d["recorded_at_dt"], d.get("_seq", 0)))
    limit, offset = parse_pagination()
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([serialize_dispatch(d) for d in page], limit, offset, total)


@bp.route("/pers/dispatch-actions/<did>", methods=["GET"])
def get_dispatch_route(did):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "CallCenterAgent", "Subscriber"})
    r = get_dispatch(did)
    return object_response(serialize_dispatch(r), 200)


@bp.route("/pers/dispatch-actions", methods=["GET"])
def list_all_dispatch():
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "CallCenterAgent", "Subscriber"})
    limit, offset = parse_pagination()
    items = list(store.dispatch_actions.values())
    if "alarm_event_id" in request.args:
        items = [d for d in items if d["alarm_event_id"] == request.args.get("alarm_event_id")]
    if "target_contact_id" in request.args:
        items = [d for d in items if d.get("target_contact_id") == request.args.get("target_contact_id")]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([serialize_dispatch(d) for d in page], limit, offset, total)
