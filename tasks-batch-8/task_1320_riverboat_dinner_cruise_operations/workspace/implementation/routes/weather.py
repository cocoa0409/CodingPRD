"""Weather events: declare, list, get, settle-credits, close."""
from flask import Blueprint, request

import clock
import db
from errors import ApiError, err_invalid_request, err_invalid_state
from response import ok
from serializers import serialize as _sz, serialize_list as _szl
from services import core as svc
from util import require_auth, get_json, paginate, get_or_404, check_enum

bp = Blueprint("weather", __name__)

OM = ["OperationsManager"]
READ = ["OperationsManager", "Captain"]

SEVERITIES = ["ADVISORY", "GALE_WARNING", "CANCELLATION_REQUIRED"]
EVENT_STATUSES = ["DECLARED", "CANCELLATION_ISSUED", "CREDITS_SETTLED", "CLOSED"]


@bp.post("/weather-events")
def declare_weather_event():
    require_auth(OM)
    body = get_json(required_fields=["severity", "window_start", "window_end"])
    severity = check_enum(body, "severity", SEVERITIES)
    ws = clock.parse_dt(body["window_start"])
    we = clock.parse_dt(body["window_end"])
    if ws is None or we is None:
        raise err_invalid_request("window_start and window_end must be ISO-8601 datetimes")
    if we <= ws:
        raise err_invalid_request("window_end must be later than window_start")
    now_z = clock.to_z(clock.now())
    event = {
        "id": db.new_id(), "created_at": now_z, "updated_at": now_z, "version": 1,
        "declared_at": now_z,
        "severity": severity,
        "window_start": clock.to_z(ws),
        "window_end": clock.to_z(we),
        "status": "DECLARED",
    }
    db.insert(db.weather_events, event)
    svc.hold_covered_cruises(event)
    return ok(_sz("weather_event", event), status=201)


@bp.get("/weather-events")
def list_weather_events():
    require_auth(READ)
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in EVENT_STATUSES:
        raise err_invalid_request("Invalid value for status")
    items = list(db.weather_events.values())
    if status_filter is not None:
        items = [e for e in items if e["status"] == status_filter]
    items.sort(key=lambda e: e["created_at"])
    page, meta = paginate(items)
    return ok(_szl("weather_event", page), pagination=meta)


@bp.get("/weather-events/<eid>")
def get_weather_event(eid):
    require_auth(READ)
    event = get_or_404(db.weather_events, eid, "weather_event", "Weather event not found")
    return ok(_sz("weather_event", event))


@bp.post("/weather-events/<eid>/settle-credits")
def settle_credits(eid):
    require_auth(OM)
    get_json()
    event = get_or_404(db.weather_events, eid, "weather_event", "Weather event not found")
    if event["status"] != "CANCELLATION_ISSUED":
        raise err_invalid_state("Weather event is not CANCELLATION_ISSUED")
    # Rung 12: every booking on every cruise cancelled under this event must
    # still stand at REFUND_PENDING
    for cruise in svc.cruises_cancelled_under(event):
        for b in db.bookings.values():
            if b["cruise_id"] == cruise["id"] and b.get("cancelled_by_event_id") == event["id"]:
                if b["payment_status"] != "REFUND_PENDING":
                    raise ApiError("ERR_CREDITS_NOT_PENDING", 409,
                                   "An affected booking is no longer REFUND_PENDING")
    svc.settle_credits_cascade(event)
    return ok(_sz("weather_event", event))


@bp.post("/weather-events/<eid>/close")
def close_weather_event(eid):
    require_auth(OM)
    get_json()
    event = get_or_404(db.weather_events, eid, "weather_event", "Weather event not found")
    if event["status"] != "DECLARED":
        raise err_invalid_state("Weather event is not DECLARED")
    ws, we = clock.parse_dt(event["window_start"]), clock.parse_dt(event["window_end"])
    for c in db.cruises.values():
        if (c["status"] == "WEATHER_HOLD"
                and ws <= clock.parse_dt(c["depart_at"]) <= we):
            raise ApiError("ERR_WEATHER_HOLDS_OUTSTANDING", 409,
                           "A covered cruise remains in WEATHER_HOLD")
    event["status"] = "CLOSED"
    from util import touch
    touch(event)
    return ok(_sz("weather_event", event))
