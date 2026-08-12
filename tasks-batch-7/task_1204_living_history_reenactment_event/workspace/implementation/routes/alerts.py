"""Contingency alert endpoints: raise, list, resolve."""

from flask import Blueprint, request

import db
import serializers
from errors import fail
from middleware import authenticate, get_alert, get_event
from response import success
from services import cascades, derived
from services.common import new_record, paginate, touch
from services.derived import sorted_all
from util import body, req_enum, req_str

bp = Blueprint("alerts", __name__)


@bp.post("/events/<event_id>/contingency-alerts")
def raise_alert(event_id):
    authenticate(["SafetyOfficer"], creation=True)
    ev = get_event(event_id)
    if ev["event_posture"] not in ("PUBLISHED", "EVENT_OPEN", "RESTRICTED"):
        fail("ERR_INVALID_EVENT_POSTURE", "alerts require PUBLISHED, EVENT_OPEN, or RESTRICTED")
    data = body(request)
    rec = new_record()
    rec.update(
        event_id=ev["id"],
        alert_kind=req_enum(data, "alert_kind", ("WEATHER", "FIRE", "SECURITY")),
        severity=req_enum(data, "severity", ("ADVISORY", "WATCH", "RED_FLAG")),
        message=req_str(data, "message"),
        status="OPEN",
        resolved_at=None,
    )
    db.alerts[rec["id"]] = rec
    # Recompute restriction level; a fresh RED while EVENT_OPEN forces restriction.
    if derived.restriction_level(ev) == "RED" and ev["event_posture"] == "EVENT_OPEN":
        cascades.restrict_event(ev)
    return success(serializers.contingency_alert(rec), 201)


@bp.get("/events/<event_id>/contingency-alerts")
def list_alerts(event_id):
    authenticate(["EventOrganizer", "SafetyOfficer"])
    ev = get_event(event_id)
    items = sorted_all(a for a in db.alerts.values() if a["event_id"] == ev["id"])
    page, meta = paginate(items)
    return success([serializers.contingency_alert(a) for a in page], 200, pagination=meta)


@bp.post("/contingency-alerts/<alert_id>/resolve")
def resolve_alert(alert_id):
    authenticate(["SafetyOfficer"])
    a = get_alert(alert_id)
    if a["status"] != "OPEN":
        fail("ERR_INVALID_ALERT_STATUS", "only an OPEN alert can be resolved")
    a["status"] = "RESOLVED"
    a["resolved_at"] = db.now()
    touch(a)
    # restriction_level is derived live; posture is never auto-lifted.
    return success(serializers.contingency_alert(a), 200)
