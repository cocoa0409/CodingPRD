"""LicenseGrant endpoints."""

from flask import Blueprint

from db import store
from errors import ApiError, not_found
import errors
from middleware import require_roles
from response import success_object, success_list
from serializers import license_json
from services.domain import touch, sweep_clock
from timeutil import now_dt

bp = Blueprint("license", __name__)


def _get_booking_or_404(booking_id):
    b = store.bookings.get(booking_id)
    if not b:
        raise not_found("ShootBooking not found")
    return b


def _get_license_for_booking(booking_id):
    grants = [g for g in store.license_grants.values() if g["booking_id"] == booking_id]
    return grants[0] if grants else None


def _get_tour_for_booking(booking_id):
    tours = [t for t in store.virtual_tours.values() if t["booking_id"] == booking_id]
    return tours[0] if tours else None


@bp.route("/shoot-bookings/<booking_id>/license", methods=["GET"])
def get_license(booking_id):
    require_roles("ClientAgent", "Photographer", "Coordinator", "OpsAdmin")
    sweep_clock()
    b = _get_booking_or_404(booking_id)
    g = _get_license_for_booking(b["id"])
    items = [license_json(g)] if g else []
    return success_list(items, limit=10, offset=0, total_count=len(items))


@bp.route("/shoot-bookings/<booking_id>/license/suspend", methods=["POST"])
def suspend_license(booking_id):
    require_roles("OpsAdmin")
    b = _get_booking_or_404(booking_id)
    g = _get_license_for_booking(b["id"])
    if not g:
        raise not_found("LicenseGrant not found")
    if g["state"] != "ACTIVE":
        raise ApiError(errors.ERR_LICENSE_NOT_ACTIVE, 409, "suspend requires ACTIVE")
    g["state"] = "SUSPENDED"
    touch(g)
    t = _get_tour_for_booking(b["id"])
    if t and t["state"] == "PUBLISHED":
        t["state"] = "SUSPENDED"
        touch(t)
    return success_object(license_json(g))


@bp.route("/shoot-bookings/<booking_id>/license/reinstate", methods=["POST"])
def reinstate_license(booking_id):
    require_roles("OpsAdmin")
    b = _get_booking_or_404(booking_id)
    g = _get_license_for_booking(b["id"])
    if not g:
        raise not_found("LicenseGrant not found")
    if g["state"] != "SUSPENDED":
        raise ApiError(errors.ERR_LICENSE_NOT_SUSPENDED, 409, "reinstate requires SUSPENDED")
    g["state"] = "ACTIVE"
    touch(g)
    # Tour deliberately NOT auto-resumed
    return success_object(license_json(g))


@bp.route("/shoot-bookings/<booking_id>/license/revoke", methods=["POST"])
def revoke_license(booking_id):
    require_roles("OpsAdmin")
    b = _get_booking_or_404(booking_id)
    g = _get_license_for_booking(b["id"])
    if not g:
        raise not_found("LicenseGrant not found")
    if g["state"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(errors.ERR_LICENSE_NOT_ACTIVE, 409,
                       "revoke requires ACTIVE or SUSPENDED")
    g["state"] = "REVOKED"
    touch(g)
    t = _get_tour_for_booking(b["id"])
    if t and t["state"] != "UNPUBLISHED":
        t["state"] = "UNPUBLISHED"
        touch(t)
    return success_object(license_json(g))
