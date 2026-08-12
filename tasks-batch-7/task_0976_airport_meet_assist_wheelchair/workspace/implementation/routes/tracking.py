"""Tracking events and logical clock."""
from flask import Blueprint

import db
from errors import bad_request, temporal_conflict
from middleware import require_roles
from response import success_object
from routes.util import (json_body, parse_datetime_field, require_enum,
                         require_fields, serialize_tracking_event)

bp = Blueprint("tracking", __name__)


@bp.post("/maa/tracking")
def publish_tracking():
    require_roles("Agent")
    body = json_body()
    require_fields(body, ["tracking_token", "event_kind", "occurred_at_utc"])
    token = body["tracking_token"]
    if not isinstance(token, str) or not token:
        raise bad_request("tracking_token must be a non-empty string")
    asg = None
    for a in db.assignments.values():
        if a.get("tracking_token") == token:
            asg = a
            break
    if asg is None:
        raise bad_request("tracking_token does not resolve")
    event_kind = require_enum(
        body["event_kind"],
        {"LOCATION_PING", "PICKUP_CONFIRM", "GATE_ARRIVAL", "HANDOFF_START", "HANDOFF_COMPLETE"},
        "event_kind")
    occurred = parse_datetime_field(body["occurred_at_utc"], "occurred_at_utc")
    if occurred > db.now():
        raise temporal_conflict("occurred_at_utc may not be in the future")
    lat = body.get("lat")
    lon = body.get("lon")
    if lat is not None and not isinstance(lat, (int, float)):
        raise bad_request("lat must be a number")
    if lon is not None and not isinstance(lon, (int, float)):
        raise bad_request("lon must be a number")
    event = {
        "id": db.new_id(),
        "created_at": db.iso_now_logical(),
        "assignment_id": asg["id"],
        "event_kind": event_kind,
        "lat": lat,
        "lon": lon,
        "occurred_at_utc": occurred,
    }
    db.tracking_events[event["id"]] = event
    return success_object(serialize_tracking_event(event), status=201)


@bp.post("/maa/_clock/set_current_utc")
def set_clock():
    require_roles("PlatformAdmin")
    body = json_body()
    require_fields(body, ["to_iso8601"])
    target = parse_datetime_field(body["to_iso8601"], "to_iso8601")
    db.set_now(target)
    return success_object({"now_utc": db.fmt_dt(db.now())})
