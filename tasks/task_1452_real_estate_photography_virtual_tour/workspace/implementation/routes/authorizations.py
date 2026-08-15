"""AirspaceAuthorization endpoints."""

from flask import Blueprint, request

from db import store
from errors import ApiError, not_found
import errors
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from serializers import authorization_json
from services.domain import touch, sweep_clock, active_drone_addons, maybe_advance_to_confirmed
from timeutil import now_dt, iso_now_ms

bp = Blueprint("authorizations", __name__)


def _get_booking_or_404(booking_id):
    b = store.bookings.get(booking_id)
    if not b:
        raise not_found("ShootBooking not found")
    return b


def _get_auth_under_booking(booking_id, auth_id):
    b = _get_booking_or_404(booking_id)
    a = store.airspace_authorizations.get(auth_id)
    if not a or a["booking_id"] != b["id"]:
        raise not_found("AirspaceAuthorization not found")
    return b, a


# Global ops queue
@bp.route("/airspace-authorizations", methods=["GET"])
def global_list_auths():
    require_roles("Coordinator", "OpsAdmin")
    sweep_clock()
    limit, offset = parse_pagination(request.args)
    items = sorted(store.airspace_authorizations.values(), key=lambda a: a["created_at"])
    for f in ("booking_id", "addon_id", "state"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if a.get(f) == v]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([authorization_json(a) for a in page], limit, offset, total)


@bp.route("/airspace-authorizations/<authId>", methods=["GET"])
def global_get_auth(authId):
    require_roles("Coordinator", "OpsAdmin")
    sweep_clock()
    a = store.airspace_authorizations.get(authId)
    if not a:
        raise not_found("AirspaceAuthorization not found")
    return success_object(authorization_json(a))


# Per-booking nested
@bp.route("/shoot-bookings/<booking_id>/airspace-authorizations", methods=["GET"])
def list_auths(booking_id):
    require_roles("ClientAgent", "Photographer", "Coordinator", "OpsAdmin")
    sweep_clock()
    b = _get_booking_or_404(booking_id)
    limit, offset = parse_pagination(request.args)
    items = sorted(
        (a for a in store.airspace_authorizations.values() if a["booking_id"] == b["id"]),
        key=lambda x: x["created_at"],
    )
    state = request.args.get("state")
    if state is not None:
        items = [a for a in items if a["state"] == state]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([authorization_json(a) for a in page], limit, offset, total)


@bp.route("/shoot-bookings/<booking_id>/airspace-authorizations/<authId>", methods=["GET"])
def get_auth(booking_id, authId):
    require_roles("ClientAgent", "Photographer", "Coordinator", "OpsAdmin")
    sweep_clock()
    _, a = _get_auth_under_booking(booking_id, authId)
    return success_object(authorization_json(a))


@bp.route("/shoot-bookings/<booking_id>/airspace-authorizations/<authId>/approve", methods=["POST"])
def approve(booking_id, authId):
    require_roles("OpsAdmin")
    b, a = _get_auth_under_booking(booking_id, authId)
    if a["state"] != "PENDING":
        raise ApiError(errors.ERR_AUTHORIZATION_NOT_PENDING, 409,
                       "approve requires PENDING")
    if a["window_end_utc"] is not None and a["window_end_utc"] <= now_dt():
        raise ApiError(errors.ERR_AUTHORIZATION_WINDOW_LAPSED, 422,
                       "Authorization window has lapsed")
    a["state"] = "APPROVED"
    a["decided_at_utc"] = now_dt()
    touch(a)
    # Auto-advance booking if no more pending
    maybe_advance_to_confirmed(b)
    return success_object(authorization_json(a))


@bp.route("/shoot-bookings/<booking_id>/airspace-authorizations/<authId>/reject", methods=["POST"])
def reject(booking_id, authId):
    require_roles("OpsAdmin")
    b, a = _get_auth_under_booking(booking_id, authId)
    if a["state"] != "PENDING":
        raise ApiError(errors.ERR_AUTHORIZATION_NOT_PENDING, 409,
                       "reject requires PENDING")
    a["state"] = "REJECTED"
    a["decided_at_utc"] = now_dt()
    touch(a)
    # If attempt cap reached, REFUSE the covered drone add-on
    if a["attempt_number"] >= 3:
        addon = store.addons.get(a["addon_id"])
        if addon and addon["state"] == "ACTIVE":
            addon["state"] = "REFUSED"
            touch(addon)
    maybe_advance_to_confirmed(b)
    return success_object(authorization_json(a))


@bp.route("/shoot-bookings/<booking_id>/airspace-authorizations/<authId>/resubmit", methods=["POST"])
def resubmit(booking_id, authId):
    require_roles("Coordinator")
    b, a = _get_auth_under_booking(booking_id, authId)
    if a["state"] != "REJECTED":
        raise ApiError(errors.ERR_AUTHORIZATION_NOT_REJECTED, 409,
                       "resubmit requires REJECTED")
    if a["attempt_number"] >= 3:
        raise ApiError(errors.ERR_AUTHORIZATION_ATTEMPTS_EXHAUSTED, 409,
                       "attempt cap 3 reached")
    if b["state"] != "AUTHORIZATION_PENDING":
        raise ApiError(errors.ERR_BOOKING_NOT_RESCHEDULABLE, 409,
                       "Booking not in AUTHORIZATION_PENDING")
    a["attempt_number"] += 1
    a["window_start_utc"] = b["scheduled_start_utc"]
    a["window_end_utc"] = b["scheduled_end_utc"]
    a["decided_at_utc"] = None
    a["state"] = "PENDING"
    touch(a)
    return success_object(authorization_json(a))
