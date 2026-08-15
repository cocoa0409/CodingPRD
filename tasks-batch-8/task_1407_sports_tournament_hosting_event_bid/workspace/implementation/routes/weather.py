"""WeatherAlert endpoints (PRD §3.6)."""

from flask import Blueprint, request

import services as svc
from db import STORE, base_entity, parse_dt, touch
from errors import (ERR_ALERT_WINDOW_INVALID, ERR_CROSS_EVENT_REFERENCE,
                    already_terminal, invalid_state, posture_forbids, raise_err)
from listing import list_response
from middleware import (get_body, opt_str, req_enum, require_any_authenticated,
                        require_roles)
from response import ok

bp = Blueprint("weather", __name__, url_prefix="/api/v1")


@bp.post("/events/<id>/weather-alerts")
def create_alert(id):
    require_roles("CommissionAdmin")
    e = svc.get_or_404(STORE.events, id, "event")
    data = get_body()
    severity = req_enum(data, "severity", svc.SEVERITIES)
    venue_id = opt_str(data, "venue_id")
    from errors import ApiError, ERR_VALIDATION
    try:
        w_start = parse_dt(data.get("window_start"))
        w_end = parse_dt(data.get("window_end"))
    except Exception:
        raise ApiError(*ERR_VALIDATION, "window_start and window_end must be ISO 8601 datetimes.")
    if w_end <= w_start:
        raise_err(ERR_ALERT_WINDOW_INVALID, "window_end must be strictly after window_start.")
    if venue_id is not None:
        v = svc.get_or_404(STORE.venues, venue_id, "venue")
        if v["event_id"] != e["id"]:
            raise_err(ERR_CROSS_EVENT_REFERENCE, "The venue belongs to a different event.")
    if e["posture"] == "CANCELLED":
        posture_forbids("Weather alerts may not be created for a cancelled event.")
    a = base_entity()
    a.update({
        "event_id": e["id"],
        "venue_id": venue_id,
        "severity": severity,
        "window_start": w_start,
        "window_end": w_end,
        "status": "ISSUED",
        "_delayed": [],  # matches delayed by this alert (drives resolve cascade)
    })
    STORE.alerts[a["id"]] = a
    return ok(svc.ser_alert(a), status=201)


@bp.get("/events/<id>/weather-alerts")
def list_event_alerts(id):
    require_any_authenticated()
    e = svc.get_or_404(STORE.events, id, "event")
    items = svc.alerts_of_event(e["id"])
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    severity = request.args.get("severity")
    if severity is not None:
        items = [a for a in items if a["severity"] == severity]
    items.sort(key=lambda a: (a["window_start"], a["created_at"], a["_seq"]))
    return list_response(items, svc.ser_alert)


@bp.get("/weather-alerts/<id>")
def get_alert(id):
    require_any_authenticated()
    a = svc.get_or_404(STORE.alerts, id, "weather alert")
    return ok(svc.ser_alert(a))


@bp.get("/weather-alerts")
def list_alerts():
    require_any_authenticated()
    items = list(STORE.alerts.values())
    for param in ("event_id", "venue_id", "status", "severity"):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a.get(param) == v]
    items.sort(key=lambda a: (a["window_start"], a["created_at"], a["_seq"]))
    return list_response(items, svc.ser_alert)


@bp.post("/weather-alerts/<id>/activate")
def activate_alert(id):
    require_roles("CommissionAdmin")
    a = svc.get_or_404(STORE.alerts, id, "weather alert")
    e = svc.get_or_404(STORE.events, a["event_id"], "event")
    if e["posture"] not in ("COMPETITION_SETUP", "LIVE"):
        posture_forbids("Weather alert activation requires COMPETITION_SETUP or LIVE posture.")
    if a["status"] in svc.ALERT_TERMINAL:
        already_terminal("weather alert")
    if a["status"] != "ISSUED":
        invalid_state("Only an ISSUED alert can be activated.")
    a["status"] = "ACTIVE"
    touch(a)
    # Cascade: overlapping matches on scoped venues -> WEATHER_DELAYED.
    if a["venue_id"] is not None:
        field_ids = {f["id"] for f in svc.fields_of_venue(a["venue_id"])}
    else:
        venue_ids = {v["id"] for v in svc.venues_of_event(e["id"])}
        field_ids = {f["id"] for f in STORE.fields.values() if f["venue_id"] in venue_ids}
    delayed = []
    for m in list(STORE.matches.values()):
        if m["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if m["field_id"] not in field_ids:
            continue
        if m["scheduled_start"] is None or m["scheduled_end"] is None:
            continue
        d = STORE.divisions.get(m["division_id"])
        if d is None or d["event_id"] != e["id"]:
            continue
        if svc._overlaps(m["scheduled_start"], m["scheduled_end"],
                         a["window_start"], a["window_end"]):
            svc.release_match_assignments(m, "WEATHER")
            m["status"] = "WEATHER_DELAYED"
            touch(m)
            delayed.append(m["id"])
    a["_delayed"] = delayed
    return ok(svc.ser_alert(a))


@bp.post("/weather-alerts/<id>/resolve")
def resolve_alert(id):
    require_roles("CommissionAdmin")
    a = svc.get_or_404(STORE.alerts, id, "weather alert")
    if a["status"] in svc.ALERT_TERMINAL:
        already_terminal("weather alert")
    if a["status"] == "ISSUED":
        # Resolving an un-activated alert expires it without any match cascade.
        a["status"] = "EXPIRED"
        touch(a)
        return ok(svc.ser_alert(a))
    a["status"] = "RESOLVED"
    touch(a)
    for mid in a.get("_delayed", []):
        m = STORE.matches.get(mid)
        if m is not None and m["status"] == "WEATHER_DELAYED":
            m["status"] = "RESCHEDULE_QUEUE"
            m["field_id"] = None
            m["scheduled_start"] = None
            m["scheduled_end"] = None  # queue holds only original_scheduled_start
            touch(m)
    return ok(svc.ser_alert(a))
