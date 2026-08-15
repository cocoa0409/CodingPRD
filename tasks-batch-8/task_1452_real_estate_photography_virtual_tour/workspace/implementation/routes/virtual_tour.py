"""VirtualTour endpoints."""

from flask import Blueprint

from db import store
from errors import ApiError, not_found
import errors
from middleware import require_roles
from response import success_object, success_list
from serializers import tour_json
from services.domain import touch, sweep_clock

bp = Blueprint("virtual_tour", __name__)


def _get_booking_or_404(booking_id):
    b = store.bookings.get(booking_id)
    if not b:
        raise not_found("ShootBooking not found")
    return b


def _get_tour_for_booking(booking_id):
    tours = [t for t in store.virtual_tours.values() if t["booking_id"] == booking_id]
    return tours[0] if tours else None


def _get_license_for_booking(booking_id):
    grants = [g for g in store.license_grants.values() if g["booking_id"] == booking_id]
    return grants[0] if grants else None


@bp.route("/shoot-bookings/<booking_id>/virtual-tour", methods=["GET"])
def get_tour(booking_id):
    require_roles("ClientAgent", "Photographer", "Coordinator", "OpsAdmin")
    sweep_clock()
    b = _get_booking_or_404(booking_id)
    t = _get_tour_for_booking(b["id"])
    items = [tour_json(t)] if t else []
    # This endpoint returns a 0-or-1 collection; wrap as array
    from response import success_list as _sl
    return _sl(items, limit=10, offset=0, total_count=len(items))


@bp.route("/shoot-bookings/<booking_id>/virtual-tour/suspend", methods=["POST"])
def suspend_tour(booking_id):
    require_roles("OpsAdmin")
    b = _get_booking_or_404(booking_id)
    t = _get_tour_for_booking(b["id"])
    if not t:
        raise not_found("VirtualTour not found")
    if t["state"] != "PUBLISHED":
        raise ApiError(errors.ERR_TOUR_NOT_PUBLISHED, 409, "suspend requires PUBLISHED")
    t["state"] = "SUSPENDED"
    touch(t)
    return success_object(tour_json(t))


@bp.route("/shoot-bookings/<booking_id>/virtual-tour/resume", methods=["POST"])
def resume_tour(booking_id):
    require_roles("OpsAdmin")
    b = _get_booking_or_404(booking_id)
    t = _get_tour_for_booking(b["id"])
    if not t:
        raise not_found("VirtualTour not found")
    if t["state"] != "SUSPENDED":
        raise ApiError(errors.ERR_TOUR_NOT_SUSPENDED, 409, "resume requires SUSPENDED")
    grant = _get_license_for_booking(b["id"])
    if b["state"] != "ACCEPTED" or grant is None or grant["state"] != "ACTIVE":
        raise ApiError(errors.ERR_LICENSE_NOT_ACTIVE, 409,
                       "Booking must be ACCEPTED with ACTIVE license")
    t["state"] = "PUBLISHED"
    touch(t)
    return success_object(tour_json(t))


@bp.route("/shoot-bookings/<booking_id>/virtual-tour/unpublish", methods=["POST"])
def unpublish_tour(booking_id):
    require_roles("OpsAdmin")
    b = _get_booking_or_404(booking_id)
    t = _get_tour_for_booking(b["id"])
    if not t:
        raise not_found("VirtualTour not found")
    if t["state"] not in ("PUBLISHED", "SUSPENDED"):
        raise ApiError(errors.ERR_TOUR_NOT_PUBLISHED, 409,
                       "unpublish requires PUBLISHED or SUSPENDED")
    t["state"] = "UNPUBLISHED"
    touch(t)
    return success_object(tour_json(t))
