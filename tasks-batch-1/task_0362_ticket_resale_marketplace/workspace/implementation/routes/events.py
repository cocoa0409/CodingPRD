from flask import Blueprint, request

import db
import validate
import response
from middleware import get_user_context, require_role
from services import lookup, serialize, paginate, event_ops
from services.recompute import recompute_event

bp = Blueprint("events", __name__)

READ_ROLES = ("PlatformAdmin", "Seller", "Buyer", "TrustSafety")


@bp.post("/events")
def create_event():
    body = validate.get_json_body()
    venue_id = validate.require_string(body, "venue_id")
    title = validate.require_string(body, "title")
    doors_open_at = validate.require_string(body, "doors_open_at")
    price_cap_multiplier = validate.require_number(
        body, "price_cap_multiplier", required=False, minimum=1.0, default=3.0
    )
    last_minute_cutoff_minutes = validate.require_int(
        body, "last_minute_cutoff_minutes", required=False, minimum=0, default=180
    )
    # validate doors_open_at is a parseable datetime
    import clock as _clock
    if _clock.parse_iso(doors_open_at) is None:
        import errors
        from errors import err
        raise err(errors.ERR_INVALID_REQUEST, "doors_open_at must be an ISO 8601 datetime")

    _, role = get_user_context()
    require_role(role, ("PlatformAdmin",))

    lookup.get_venue(venue_id)

    event = {
        "venue_id": venue_id,
        "title": title,
        "doors_open_at": doors_open_at,
        "status": "SCHEDULED",
        "price_cap_multiplier": price_cap_multiplier,
        "active_listing_count": 0,
        "last_minute_cutoff_minutes": last_minute_cutoff_minutes,
    }
    db.stamp_create(event)
    db.events[event["id"]] = event
    return response.object_response(serialize.public(event), 201)


@bp.get("/events/<event_id>")
def get_event(event_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    event = lookup.get_event(event_id)
    return response.object_response(serialize.public(event), 200)


@bp.get("/events")
def list_events():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    venue_id = request.args.get("venue_id")
    records = list(db.events.values())
    if venue_id is not None:
        records = [e for e in records if e["venue_id"] == venue_id]
    page, limit, offset, total = paginate.apply_pagination(records)
    return response.array_response(serialize.public_list(page), limit, offset, total)


def _transition(event_id, fn):
    _, role = get_user_context()
    require_role(role, ("PlatformAdmin",))
    event = lookup.get_event(event_id)
    fn(event)
    return response.object_response(serialize.public(event), 200)


@bp.post("/events/<event_id>/open-sales")
def open_sales(event_id):
    return _transition(event_id, event_ops.open_sales)


@bp.post("/events/<event_id>/enter-last-minute")
def enter_last_minute(event_id):
    return _transition(event_id, event_ops.enter_last_minute)


@bp.post("/events/<event_id>/complete")
def complete(event_id):
    return _transition(event_id, event_ops.complete)


@bp.post("/events/<event_id>/cancel")
def cancel(event_id):
    return _transition(event_id, event_ops.cancel)


@bp.post("/events/<event_id>/postpone")
def postpone(event_id):
    return _transition(event_id, event_ops.postpone)
