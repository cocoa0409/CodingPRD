"""Dispatch events and dispatches (PRD §3.4, §3.5, §3.6)."""
from datetime import timedelta
from flask import Blueprint, request

from errors import err
from common import (require, ALL_ROLES, get_body, ok_object, list_response,
                    require_str, require_number, num)
from models import (get, get_or_404, insert, touch, recompute_aggregator_season_kwh)
from store import db, parse_iso
from calc import measure_dispatch, event_duration_hours

bp_events = Blueprint("events", __name__)

EVENT_BUFFER_MINUTES = 120
OPEN_EVENT_STATES = ("SCHEDULED", "NOTIFIED", "ACTIVE")
NON_CANCELLED = ("SCHEDULED", "NOTIFIED", "ACTIVE", "COMPLETED", "SETTLED")


def _require_iso(body, field):
    require_str(body, field)
    try:
        parse_iso(body[field])
    except (ValueError, TypeError):
        raise err("ERR_VALIDATION", "Field %s must be an ISO 8601 datetime." % field)
    return body[field]


def _device_of_dispatch(dispatch):
    enr = get("enrollments", dispatch["enrollment_id"])
    return get("devices", enr["device_id"]) if enr else None


# ---------------------------------------------------------------------------
# Dispatch events
# ---------------------------------------------------------------------------
@bp_events.route("/dr/dispatch-events", methods=["POST"])
def create_event():
    require(["ProgramOperator"])
    body = get_body()
    # step 4: FK existence
    if body.get("program_id") is not None:
        get_or_404("programs", body["program_id"])
    # step 6: required + typed
    program_id = require_str(body, "program_id")
    window_start = _require_iso(body, "window_start")
    window_end = _require_iso(body, "window_end")
    target = require_number(body, "target_reduction_kw", gt=0)
    program = get("programs", program_id)
    start_dt = parse_iso(window_start)
    end_dt = parse_iso(window_end)
    # business: window well-formed (PRD §3.4)
    if not start_dt < end_dt:
        raise err("ERR_VALIDATION", "window_start must be before window_end.")
    # business: season cap
    count = sum(1 for ev in db.data["dispatch_events"].values()
                if ev["program_id"] == program_id and ev["status"] in NON_CANCELLED)
    if count >= program["max_events_per_season"]:
        raise err("ERR_SEASON_EVENT_CAP_EXCEEDED",
                  "Program already has the maximum number of events this season.")
    # business: window conflict (padded by 120 minutes on each side)
    buf = timedelta(minutes=EVENT_BUFFER_MINUTES)
    for ev in db.data["dispatch_events"].values():
        if ev["program_id"] != program_id or ev["status"] not in NON_CANCELLED:
            continue
        es = parse_iso(ev["window_start"])
        ee = parse_iso(ev["window_end"])
        if start_dt < ee + buf and end_dt + buf > es:
            raise err("ERR_EVENT_WINDOW_CONFLICT",
                      "Event window collides with an existing event of this program.")
    rec = insert("dispatch_events", {
        "program_id": program_id,
        "window_start": window_start,
        "window_end": window_end,
        "target_reduction_kw": target,
        "baseline_method_snapshot": program["baseline_method"],
        "dispatched_by_user_id": None,
        "status": "SCHEDULED",
    })
    return ok_object(rec, status=201)


@bp_events.route("/dr/dispatch-events/<eid>", methods=["GET"])
def get_event(eid):
    require(ALL_ROLES)
    return ok_object(get_or_404("dispatch_events", eid))


@bp_events.route("/dr/dispatch-events", methods=["GET"])
def list_events():
    require(ALL_ROLES)
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    records = []
    for ev in db.data["dispatch_events"].values():
        if program_id is not None and ev["program_id"] != program_id:
            continue
        if status is not None and ev["status"] != status:
            continue
        records.append(ev)
    return list_response(records)


@bp_events.route("/dr/dispatch-events/<eid>/notify", methods=["POST"])
def notify_event(eid):
    uid, _ = require(["ProgramOperator"])
    ev = get_or_404("dispatch_events", eid)
    if ev["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Event is not SCHEDULED.")
    program = get("programs", ev["program_id"])
    lead = program["notification_lead_minutes"]
    threshold = parse_iso(ev["window_start"]) - timedelta(minutes=lead)
    if not db.current_utc <= threshold:
        raise err("ERR_NOTIFY_LEAD_NOT_MET",
                  "Notification must lead window_start by at least %d minutes." % lead)
    active_enrollments = [e for e in db.data["enrollments"].values()
                          if e["program_id"] == ev["program_id"] and e["status"] == "ACTIVE"]
    if not active_enrollments:
        raise err("ERR_NO_ELIGIBLE_ENROLLMENTS", "Program has no ACTIVE enrollments.")
    ev["status"] = "NOTIFIED"
    ev["dispatched_by_user_id"] = uid
    touch(ev)
    for enr in active_enrollments:
        insert("dispatches", {
            "dispatch_event_id": ev["id"],
            "enrollment_id": enr["id"],
            "assigned_reduction_kw": enr["committed_kw"],
            "baseline_kw": None,
            "avg_event_load_kw": None,
            "actual_reduction_kw": None,
            "delivered_kwh": None,
            "performance_ratio": None,
            "net_payment_cents": None,
            "status": "PENDING",
        })
    return ok_object(ev)


@bp_events.route("/dr/dispatch-events/<eid>/start", methods=["POST"])
def start_event(eid):
    require(["ProgramOperator"])
    ev = get_or_404("dispatch_events", eid)
    if ev["status"] != "NOTIFIED":
        raise err("ERR_INVALID_STATE", "Event is not NOTIFIED.")
    if not db.current_utc >= parse_iso(ev["window_start"]):
        raise err("ERR_EVENT_NOT_STARTED", "Event window has not started.")
    ev["status"] = "ACTIVE"
    touch(ev)
    return ok_object(ev)


@bp_events.route("/dr/dispatch-events/<eid>/complete", methods=["POST"])
def complete_event(eid):
    require(["ProgramOperator"])
    ev = get_or_404("dispatch_events", eid)
    if ev["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Event is not ACTIVE.")
    if not db.current_utc >= parse_iso(ev["window_end"]):
        raise err("ERR_EVENT_NOT_ENDED", "Event window has not ended.")
    duration = event_duration_hours(ev)
    measurable = [d for d in db.data["dispatches"].values()
                  if d["dispatch_event_id"] == eid
                  and d["status"] in ("PENDING", "ACKNOWLEDGED", "CURTAILING")]
    # Stage 1: compute all measurements first (atomic — raises before any write).
    results = []
    for d in measurable:
        results.append((d, measure_dispatch(d, ev, duration)))
    # Apply.
    affected_aggregators = set()
    for d, vals in results:
        d.update(vals)
        d["status"] = "COMPLETED"
        # Stage 2: accumulate enrollment.season_delivered_kwh.
        enr = get("enrollments", d["enrollment_id"])
        if enr is not None:
            prev = enr.get("season_delivered_kwh") or 0
            enr["season_delivered_kwh"] = num(prev + vals["delivered_kwh"], places=3)
            dev = get("devices", enr["device_id"])
            if dev is not None:
                affected_aggregators.add(dev["aggregator_id"])
    ev["status"] = "COMPLETED"
    touch(ev)
    # Stage 3: recompute each affected aggregator's season_delivered_kwh.
    recompute_aggregator_season_kwh(affected_aggregators)
    return ok_object(ev)


@bp_events.route("/dr/dispatch-events/<eid>/cancel", methods=["POST"])
def cancel_event(eid):
    require(["ProgramOperator"])
    ev = get_or_404("dispatch_events", eid)
    if ev["status"] not in ("SCHEDULED", "NOTIFIED"):
        raise err("ERR_INVALID_STATE", "Event cannot be cancelled from its current state.")
    was_notified = ev["status"] == "NOTIFIED"
    ev["status"] = "CANCELLED"
    touch(ev)
    if was_notified:
        for d in db.data["dispatches"].values():
            if d["dispatch_event_id"] == eid and d["status"] in ("PENDING", "ACKNOWLEDGED"):
                d["status"] = "OPTED_OUT"
    return ok_object(ev)


@bp_events.route("/dr/dispatch-events/<eid>/dispatches", methods=["GET"])
def list_event_dispatches(eid):
    require(ALL_ROLES)
    get_or_404("dispatch_events", eid)
    status = request.args.get("status")
    records = [d for d in db.data["dispatches"].values()
               if d["dispatch_event_id"] == eid
               and (status is None or d["status"] == status)]
    return list_response(records)


@bp_events.route("/dr/dispatch-events/<eid>/settlement", methods=["GET"])
def get_event_settlement(eid):
    require(ALL_ROLES)
    get_or_404("dispatch_events", eid)
    records = [s for s in db.data["settlements"].values()
               if s["dispatch_event_id"] == eid]
    return list_response(records)


# ---------------------------------------------------------------------------
# Dispatches
# ---------------------------------------------------------------------------
@bp_events.route("/dr/dispatches/<did>", methods=["GET"])
def get_dispatch(did):
    require(ALL_ROLES)
    return ok_object(get_or_404("dispatches", did))


@bp_events.route("/dr/dispatches", methods=["GET"])
def list_dispatches():
    require(ALL_ROLES)
    enrollment_id = request.args.get("enrollment_id")
    dispatch_event_id = request.args.get("dispatch_event_id")
    status = request.args.get("status")
    records = []
    for d in db.data["dispatches"].values():
        if enrollment_id is not None and d["enrollment_id"] != enrollment_id:
            continue
        if dispatch_event_id is not None and d["dispatch_event_id"] != dispatch_event_id:
            continue
        if status is not None and d["status"] != status:
            continue
        records.append(d)
    return list_response(records)


@bp_events.route("/dr/dispatches/<did>/acknowledge", methods=["POST"])
def acknowledge_dispatch(did):
    uid, _ = require(["Aggregator"])
    d = get_or_404("dispatches", did)
    device = _device_of_dispatch(d)
    if device is None or device["aggregator_id"] != uid:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "Aggregator does not own this dispatch's device.")
    if d["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Dispatch is not PENDING.")
    ev = get("dispatch_events", d["dispatch_event_id"])
    if ev is None or ev["status"] not in ("NOTIFIED", "ACTIVE"):
        raise err("ERR_INVALID_STATE", "Parent event is not NOTIFIED or ACTIVE.")
    d["status"] = "ACKNOWLEDGED"
    touch(d)
    return ok_object(d)


@bp_events.route("/dr/dispatches/<did>/start-curtailment", methods=["POST"])
def start_curtailment(did):
    uid, _ = require(["Aggregator"])
    d = get_or_404("dispatches", did)
    device = _device_of_dispatch(d)
    if device is None or device["aggregator_id"] != uid:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "Aggregator does not own this dispatch's device.")
    if d["status"] != "ACKNOWLEDGED":
        raise err("ERR_INVALID_STATE", "Dispatch is not ACKNOWLEDGED.")
    ev = get("dispatch_events", d["dispatch_event_id"])
    if ev is None or ev["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Parent event is not ACTIVE.")
    d["status"] = "CURTAILING"
    touch(d)
    return ok_object(d)


@bp_events.route("/dr/dispatches/<did>/override", methods=["POST"])
def override_dispatch(did):
    uid, _ = require(["Customer"])
    d = get_or_404("dispatches", did)
    device = _device_of_dispatch(d)
    if device is None or device["customer_id"] != uid:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "Customer does not own this dispatch's device.")
    if d["status"] not in ("PENDING", "ACKNOWLEDGED", "CURTAILING"):
        raise err("ERR_INVALID_STATE", "Dispatch cannot be overridden from its current state.")
    ev = get("dispatch_events", d["dispatch_event_id"])
    if not db.current_utc < parse_iso(ev["window_end"]):
        raise err("ERR_OVERRIDE_WINDOW_CLOSED", "Override window has closed.")
    d["status"] = "OVERRIDDEN"
    touch(d)
    return ok_object(d)
