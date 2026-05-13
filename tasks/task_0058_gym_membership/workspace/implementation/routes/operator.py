"""Operator/test endpoints: clock advance, sweep, event emit, audit log."""
from flask import Blueprint, request, g
from clock import now, from_iso, set_clock
from db import state
from errors import raise_err
from response import success_object, success_array
from middleware import require_roles
from routes.helpers import get_json, parse_pagination, paginate, sort_by_created
from serializers import serialize_audit_log
from services import card as card_svc, pt as pt_svc, group as group_svc


bp = Blueprint("operator", __name__)


@bp.route("/_clock/advance", methods=["POST"])
def clock_advance():
    require_roles("system")
    body = get_json()
    to = body.get("to")
    if not to:
        raise_err("ERR_VALIDATION", "to required")
    try:
        to_dt = from_iso(to)
    except ValueError:
        raise_err("ERR_VALIDATION", "invalid timestamp")
    set_clock(to_dt)
    # Fire time-gated transitions
    # 1) Freeze episodes APPROVED -> SETTLED when now() >= ends_at
    for fe in list(state["freeze_episodes"].values()):
        if fe["status"] == "APPROVED" and now() >= fe["ends_at"]:
            card_svc.settle_freeze(fe)
    # 2) Group classes: bookings NO_SHOW when now() >= class.ends_at
    #    class SCHEDULED -> COMPLETED when now() >= ends_at
    for gc in list(state["group_classes"].values()):
        if gc["status"] == "SCHEDULED" and now() >= gc["ends_at"]:
            group_svc.auto_complete_class_if_due(gc)
    # 3) PT bookings CONFIRMED -> NO_SHOW after scheduled_starts_at + 15 min
    for b in list(state["pt_bookings"].values()):
        if b["status"] == "CONFIRMED":
            pt_svc.auto_no_show_if_due(b)
    # 4) Cards ACTIVE -> EXPIRED on clock crossing effective_expiry_date
    for c in list(state["cards"].values()):
        if c["status"] != "ACTIVE":
            continue
        eff = c.get("effective_expiry_date")
        if eff and now() >= eff:
            card_svc.expire_card(c)
            continue
        # PER_VISIT visit-exhaustion handled at access event time
    return success_object({"now": to})


@bp.route("/_sweep/run", methods=["POST"])
def sweep_run():
    require_roles("system")
    emitted = card_svc.run_renewal_sweep()
    return success_object({"reminders_dispatched": len(emitted)})


@bp.route("/_events/emit", methods=["POST"])
def emit_event():
    require_roles("system")
    body = get_json()
    event_type = body.get("event_type")
    payload = body.get("payload", {})
    if not event_type:
        raise_err("ERR_VALIDATION", "event_type required")
    # Just accept and acknowledge for external sync
    return success_object({"event_type": event_type, "payload": payload, "ack": True})


@bp.route("/audit-log", methods=["GET"])
def audit_log():
    require_roles("PlatformAdmin")
    limit, offset = parse_pagination()
    items = list(state["audit_log"].values())
    action = request.args.get("action")
    if action:
        items = [a for a in items if a["action"] == action]
    actor = request.args.get("actor_id")
    if actor:
        items = [a for a in items if a["actor_id"] == actor]
    items = sort_by_created(items)
    sliced, meta = paginate(items, limit, offset)
    return success_array([serialize_audit_log(a) for a in sliced], meta)
