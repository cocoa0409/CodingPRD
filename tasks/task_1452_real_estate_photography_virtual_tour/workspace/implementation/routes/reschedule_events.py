"""RescheduleEvent listing."""

from flask import Blueprint, request

from db import store
from errors import not_found
from middleware import require_roles
from response import success_list, parse_pagination
from serializers import reschedule_event_json
from services.domain import sweep_clock

bp = Blueprint("reschedule_events", __name__)


@bp.route("/shoot-bookings/<booking_id>/reschedule-events", methods=["GET"])
def list_events(booking_id):
    require_roles("ClientAgent", "Photographer", "Coordinator", "OpsAdmin")
    sweep_clock()
    b = store.bookings.get(booking_id)
    if not b:
        raise not_found("ShootBooking not found")
    limit, offset = parse_pagination(request.args)
    items = sorted(
        (e for e in store.reschedule_events.values() if e["booking_id"] == b["id"]),
        key=lambda x: x["created_at"],
    )
    kind = request.args.get("kind")
    if kind is not None:
        items = [e for e in items if e["kind"] == kind]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([reschedule_event_json(e) for e in page], limit, offset, total)
