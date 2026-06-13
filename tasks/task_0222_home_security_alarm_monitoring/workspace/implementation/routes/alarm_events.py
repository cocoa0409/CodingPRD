"""AlarmEvent endpoints: ingest, read, list, route, dispatch, resolve."""
from flask import Blueprint, request

import clock
from db import db, new_id, new_common, touch
from errors import (
    err,
    ERR_REFERENCE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_TEST_MODE_ACTIVE,
    ERR_SIGNAL_DEBOUNCED,
)
from middleware import authenticate, require_role
from response import success, list_response
from services import validate, common, calc
from services.derive import (
    serialize_alarm_event,
    monitoring_status,
    permit_cycle_anchor,
)

bp = Blueprint("alarm_events", __name__)

SIGNAL_TYPES = {"BURGLARY", "FIRE", "MEDICAL", "PANIC"}
RESOLUTIONS = {"REAL", "FALSE_ALARM"}
OPEN_STATUSES = ("RECEIVED", "ROUTED", "DISPATCHED")


def _account_for_system(system_id):
    system = db.systems.get(system_id)
    if system is None:
        return None
    return db.accounts.get(system["account_id"])


@bp.route("/alarm-events", methods=["POST"])
def ingest_alarm_event():
    caller = authenticate()
    require_role(caller, {"MonitoringOperator", "Administrator"})
    body = validate.get_body()

    # FK presence + resolution (system_id then sensor_id)
    system_id = validate.require_str(body, "system_id")
    if system_id not in db.systems:
        raise err(ERR_REFERENCE_NOT_FOUND, "system_id does not resolve: %s" % system_id)
    sensor_id = validate.require_str(body, "sensor_id")
    if sensor_id not in db.sensors:
        raise err(ERR_REFERENCE_NOT_FOUND, "sensor_id does not resolve: %s" % sensor_id)

    signal_type = validate.require_enum(body, "signal_type", SIGNAL_TYPES)

    system = db.systems[system_id]
    now = clock.now()

    # Debounce (priority 14): reject if within window of a still-open prior event
    # from the SAME sensor.
    for ev in db.alarm_events.values():
        if ev["sensor_id"] != sensor_id:
            continue
        if ev["status"] not in OPEN_STATUSES:
            continue
        delta = (now - ev["raised_utc"]).total_seconds()
        if abs(delta) < calc.SIGNAL_DEBOUNCE_SECONDS:
            raise err(ERR_SIGNAL_DEBOUNCED, "Signal debounced against a still-open prior event")

    eid = new_id()
    event = {"id": eid}
    event.update(new_common())
    account = db.accounts.get(system["account_id"])
    event.update({
        "system_id": system_id,
        "sensor_id": sensor_id,
        "signal_type": signal_type,
        "status": "RECEIVED",
        "routed_service": None,
        "raised_utc": now,
        "resolution": None,
        "chargeable_ordinal": None,
        "_account_id": system["account_id"],
    })

    # Auto-suppression: test_mode, or (DISARMED and BURGLARY)
    if system["test_mode"] or (
        system["arming_state"] == "DISARMED" and signal_type == "BURGLARY"
    ):
        event["status"] = "SUPPRESSED"

    db.alarm_events[eid] = event
    return success(serialize_alarm_event(event), http_status=201)


@bp.route("/alarm-events/<eid>", methods=["GET"])
def get_alarm_event(eid):
    caller = authenticate()
    require_role(caller, {"Administrator", "MonitoringOperator", "Subscriber"})
    event = common.lookup(db.alarm_events, eid)
    return success(serialize_alarm_event(event))


@bp.route("/alarm-events", methods=["GET"])
def list_alarm_events():
    caller = authenticate()
    require_role(caller, {"Administrator", "MonitoringOperator", "Subscriber"})
    limit, offset = common.parse_pagination()
    system_id = request.args.get("system_id")
    sensor_id = request.args.get("sensor_id")
    status = request.args.get("status")
    items = list(db.alarm_events.values())
    if system_id is not None:
        items = [e for e in items if e["system_id"] == system_id]
    if sensor_id is not None:
        items = [e for e in items if e["sensor_id"] == sensor_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items = common.sort_by_created(items)
    window, total = common.paginate(items, limit, offset)
    return list_response([serialize_alarm_event(e) for e in window], limit, offset, total)


@bp.route("/alarm-events/<eid>/route", methods=["POST"])
def route_alarm_event(eid):
    caller = authenticate()
    require_role(caller, {"MonitoringOperator"})
    event = common.lookup(db.alarm_events, eid)

    if event["status"] != "RECEIVED":
        raise err(ERR_INVALID_STATE, "Event is not RECEIVED")

    system = db.systems.get(event["system_id"])
    # business_safety (priority 7): cannot route when test_mode is active
    if system is not None and system["test_mode"]:
        raise err(ERR_TEST_MODE_ACTIVE, "Cannot route an event whose system is in test mode")

    account = db.accounts.get(event["_account_id"])
    if account is None or monitoring_status(account) != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Owning account monitoring_status is not ACTIVE")

    event["routed_service"] = calc.routed_service_for(event["signal_type"])
    event["status"] = "ROUTED"
    touch(event)
    return success(serialize_alarm_event(event))


@bp.route("/alarm-events/<eid>/dispatch", methods=["POST"])
def dispatch_alarm_event(eid):
    caller = authenticate()
    require_role(caller, {"MonitoringOperator"})
    event = common.lookup(db.alarm_events, eid)

    if event["status"] != "ROUTED":
        raise err(ERR_INVALID_STATE, "Event is not ROUTED")

    account = db.accounts.get(event["_account_id"])
    plan = db.monitoring_plans.get(account["plan_id"]) if account else None
    police_included = bool(plan["police_dispatch_included"]) if plan else False
    fee = calc.dispatch_fee(event["routed_service"], police_included)

    did = new_id()
    dispatch = {"id": did}
    dispatch.update(new_common())
    dispatch.update({
        "alarm_event_id": eid,
        "account_id": event["_account_id"],
        "service": event["routed_service"],
        "status": "ORDERED",
        "fee_cents": fee,
    })
    db.dispatches[did] = dispatch

    event["status"] = "DISPATCHED"
    touch(event)
    # monitoring_balance_cents is derived (sums ORDERED/CONFIRMED dispatch fees),
    # so the LEDGER SYNC happens automatically on the next account read.
    return success(serialize_alarm_event(event))


@bp.route("/alarm-events/<eid>/resolve", methods=["POST"])
def resolve_alarm_event(eid):
    caller = authenticate()
    require_role(caller, {"MonitoringOperator"})
    event = common.lookup(db.alarm_events, eid)
    body = validate.get_body()
    resolution = validate.require_enum(body, "resolution", RESOLUTIONS)

    if event["status"] != "DISPATCHED":
        raise err(ERR_INVALID_STATE, "Event is not DISPATCHED")

    # Linked dispatch -> CONFIRMED (fee retained) in both REAL and FALSE_ALARM
    for d in db.dispatches.values():
        if d["alarm_event_id"] == eid and d["status"] == "ORDERED":
            d["status"] = "CONFIRMED"
            touch(d)

    if resolution == "REAL":
        event["resolution"] = "REAL"
        event["status"] = "RESOLVED_REAL"
        touch(event)
        return success(serialize_alarm_event(event))

    # FALSE_ALARM
    event["resolution"] = "FALSE_ALARM"
    event["status"] = "RESOLVED_FALSE"
    touch(event)

    account = db.accounts.get(event["_account_id"])
    # HOP 2: assign chargeable_ordinal = position in non-waived FALSE_ALARM ordering
    ordinal = _compute_chargeable_ordinal(account, event)
    event["chargeable_ordinal"] = ordinal

    base = calc.false_alarm_fine_base(ordinal)
    has_active_permit = _account_has_active_permit(account)
    surcharge = 0 if has_active_permit else calc.NO_PERMIT_SURCHARGE_CENTS
    amount = base + surcharge

    fid = new_id()
    fine = {"id": fid}
    fine.update(new_common())
    fine.update({
        "account_id": event["_account_id"],
        "alarm_event_id": eid,
        "amount_cents": amount,
        "settlement_status": "ASSESSED",
    })
    db.fines[fid] = fine

    return success(serialize_alarm_event(event))


def _account_has_active_permit(account):
    if account is None:
        return False
    for p in db.permits.values():
        if p["account_id"] == account["id"] and p["status"] == "ACTIVE":
            return True
    return False


def _fine_for_event(alarm_event_id):
    for f in db.fines.values():
        if f["alarm_event_id"] == alarm_event_id:
            return f
    return None


def _compute_chargeable_ordinal(account, this_event):
    """1-based position of this_event among the account's non-waived FALSE_ALARM
    events at/after the permit cycle anchor, ordered by raised_utc ASC then
    created_at ASC (then insertion sequence as final tie-break)."""
    anchor = permit_cycle_anchor(account)
    qualifying = []
    for ev in db.alarm_events.values():
        if ev.get("_account_id") != account["id"]:
            continue
        if ev.get("resolution") != "FALSE_ALARM":
            continue
        # Exclude events whose fine is WAIVED (this event has no fine yet).
        fine = _fine_for_event(ev["id"])
        if fine is not None and fine["settlement_status"] == "WAIVED":
            continue
        if anchor is not None and ev["raised_utc"] < anchor:
            continue
        qualifying.append(ev)

    qualifying.sort(key=lambda e: (e["raised_utc"], e["created_at"], e["_seq"]))
    for idx, ev in enumerate(qualifying, start=1):
        if ev["id"] == this_event["id"]:
            return idx
    # Fallback (this_event should always be present)
    return len(qualifying)
