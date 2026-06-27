"""Reviews and trust-incident routes (moderation + trust gate cascades)."""
from flask import Blueprint, request

import errors
from errors import err
from db import db
from middleware import get_caller, require_roles
from response import object_response, array_response
from services import core, reqs

bp = Blueprint("moderation", __name__)


# =============================================================================
# Reviews
# =============================================================================
@bp.route("/reviews", methods=["POST"])
def create_review():
    caller = get_caller()
    require_roles(caller, {"Client"})
    data = reqs.body()
    booking_id = reqs.require_str(data, "booking_id")
    booking = core.get_booking_or_404(booking_id)
    if caller.user_id != booking["client_id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Client may only review own booking")
    if booking["status"] != "COMPLETED":
        raise err(errors.ERR_BOOKING_NOT_COMPLETED, "Booking is not COMPLETED")
    # one review per booking
    for r in db.reviews.values():
        if r["booking_id"] == booking_id:
            raise err(errors.ERR_DUPLICATE_REVIEW, "A review already exists for this booking")
    rating_value = reqs.require_int(data, "rating_value", minimum=1, maximum=5)
    comment = data.get("comment")
    if comment is not None:
        if not isinstance(comment, str) or len(comment) > 500:
            reqs.invalid("comment must be a string of at most 500 chars")
    rec = {
        "booking_id": booking_id,
        "tasker_id": booking["tasker_id"],
        "rating_value": rating_value,
        "comment": comment,
        "status": "PUBLISHED",
    }
    core.stamp_create(rec)
    db.reviews[rec["id"]] = rec
    tasker = db.taskers.get(booking["tasker_id"])
    if tasker:
        core.recompute_tasker(tasker, bump_version=True)
    return object_response(core.serialize(rec), status=201)


@bp.route("/reviews", methods=["GET"])
def list_reviews():
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "TrustSafetyOfficer", "Client", "Tasker"})
    limit, offset = core.parse_pagination(request.args)
    items = list(db.reviews.values())
    for key in ("tasker_id", "booking_id"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    window, meta = core.paginate(items, limit, offset)
    return array_response([core.serialize(r) for r in window], pagination=meta)


@bp.route("/reviews/<rid>", methods=["GET"])
def get_review(rid):
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "TrustSafetyOfficer", "Client", "Tasker"})
    r = core.get_review_or_404(rid)
    return object_response(core.serialize(r))


def _moderate_review(rid, allowed_from, new_status):
    caller = get_caller()
    require_roles(caller, {"TrustSafetyOfficer"})
    r = core.get_review_or_404(rid)
    if r["status"] not in allowed_from:
        raise err(errors.ERR_REVIEW_INVALID_STATE, "Illegal review moderation transition")
    r["status"] = new_status
    core.touch(r)
    tasker = db.taskers.get(r["tasker_id"])
    if tasker:
        core.recompute_tasker(tasker, bump_version=True)
    return object_response(core.serialize(r))


@bp.route("/reviews/<rid>/hide", methods=["POST"])
def hide_review(rid):
    return _moderate_review(rid, {"PUBLISHED"}, "HIDDEN")


@bp.route("/reviews/<rid>/restore", methods=["POST"])
def restore_review(rid):
    return _moderate_review(rid, {"HIDDEN"}, "PUBLISHED")


@bp.route("/reviews/<rid>/remove", methods=["POST"])
def remove_review(rid):
    return _moderate_review(rid, {"PUBLISHED", "HIDDEN"}, "REMOVED")


# =============================================================================
# Trust incidents
# =============================================================================
@bp.route("/trust-incidents", methods=["POST"])
def create_incident():
    caller = get_caller()
    require_roles(caller, {"TrustSafetyOfficer"})
    data = reqs.body()
    tasker_id = reqs.require_str(data, "tasker_id")
    tasker = core.get_tasker_or_404(tasker_id)
    booking_id = data.get("booking_id")
    if booking_id is not None:
        # validate existence of referenced booking
        if booking_id not in db.bookings:
            raise err(errors.ERR_BOOKING_NOT_FOUND, "Booking not found")
    severity = reqs.require_enum(data, "severity", {"LOW", "MEDIUM", "HIGH"})
    rec = {
        "tasker_id": tasker_id,
        "booking_id": booking_id,
        "severity": severity,
        "status": "OPEN",
        "penalty_points": core.PENALTY[severity],
    }
    core.stamp_create(rec)
    db.trust_incidents[rec["id"]] = rec
    core.recompute_tasker(tasker, bump_version=True)
    return object_response(core.serialize(rec), status=201)


@bp.route("/trust-incidents", methods=["GET"])
def list_incidents():
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "TrustSafetyOfficer"})
    limit, offset = core.parse_pagination(request.args)
    items = list(db.trust_incidents.values())
    for key in ("tasker_id", "booking_id"):
        val = request.args.get(key)
        if val is not None:
            items = [i for i in items if i.get(key) == val]
    window, meta = core.paginate(items, limit, offset)
    return array_response([core.serialize(i) for i in window], pagination=meta)


@bp.route("/trust-incidents/<iid>", methods=["GET"])
def get_incident(iid):
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "TrustSafetyOfficer"})
    i = core.get_incident_or_404(iid)
    return object_response(core.serialize(i))


@bp.route("/trust-incidents/<iid>/uphold", methods=["POST"])
def uphold_incident(iid):
    caller = get_caller()
    require_roles(caller, {"TrustSafetyOfficer"})
    i = core.get_incident_or_404(iid)
    if i["status"] != "OPEN":
        raise err(errors.ERR_INCIDENT_INVALID_STATE, "Only OPEN incidents may be upheld")
    i["status"] = "UPHELD"
    core.touch(i)
    tasker = db.taskers.get(i["tasker_id"])
    if tasker:
        core.recompute_tasker(tasker, bump_version=True)
    return object_response(core.serialize(i))


@bp.route("/trust-incidents/<iid>/dismiss", methods=["POST"])
def dismiss_incident(iid):
    caller = get_caller()
    require_roles(caller, {"TrustSafetyOfficer"})
    i = core.get_incident_or_404(iid)
    if i["status"] not in ("OPEN", "UPHELD"):
        raise err(errors.ERR_INCIDENT_INVALID_STATE, "Only OPEN/UPHELD incidents may be dismissed")
    i["status"] = "DISMISSED"
    i["penalty_points"] = 0
    core.touch(i)
    tasker = db.taskers.get(i["tasker_id"])
    if tasker:
        core.recompute_tasker(tasker, bump_version=True)
    return object_response(core.serialize(i))
