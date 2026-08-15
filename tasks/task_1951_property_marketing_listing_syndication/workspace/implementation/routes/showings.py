from flask import Blueprint, request

import clock
from db import store
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_POSTURE_SUSPENDED,
    ERR_WINDOW_OVERLAP,
    ERR_WINDOW_NOT_ENDED,
    ERR_FEEDBACK_ALREADY_EXISTS,
)
from middleware import (
    authenticate, require_roles, check_listing_ownership, get_body,
    f_int, f_str, f_dt, invalid, not_found, paginate,
)
from response import success_object, success_list
from services import derived
from services.ops import stamp, touch
from services.serialize import window_json, feedback_json

bp = Blueprint("showings", __name__)

READ_ROLES = ("ListingAgent", "MarketingCoordinator", "ComplianceOfficer",
              "MarketingDirector")
WRITE_ROLES = ("ListingAgent", "MarketingCoordinator")


@bp.route("/listings/<listing_id>/showing-windows", methods=["POST"])
def create_window(listing_id):
    uid, role = authenticate()
    require_roles(role, WRITE_ROLES)
    listing = store.listings.get(listing_id)
    if listing is None:
        raise not_found("Listing not found")
    check_listing_ownership(role, uid, listing)
    body = get_body()
    starts_at = f_dt(body, "starts_at", required=True)
    ends_at = f_dt(body, "ends_at", required=True)
    if not ends_at > starts_at:
        raise invalid("ends_at must be strictly later than starts_at")
    now = clock.now()
    if derived.compute_posture(listing, now) == "SUSPENDED":
        raise ApiError(ERR_POSTURE_SUSPENDED, 409,
                       "Mutation forbidden while posture is SUSPENDED")
    # Half-open [starts_at, ends_at) overlap against other SCHEDULED windows;
    # touching endpoints do not overlap (PRD 3.8).
    for w in store.windows.values():
        if w["listing_id"] == listing["id"] and w["status"] == "SCHEDULED":
            if starts_at < w["ends_at"] and w["starts_at"] < ends_at:
                raise ApiError(ERR_WINDOW_OVERLAP, 409,
                               "Window intersects another SCHEDULED window")
    window = stamp({
        "listing_id": listing["id"],
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": "SCHEDULED",
    }, now)
    store.windows[window["id"]] = window
    return success_object(window_json(window), status=201)


@bp.route("/listings/<listing_id>/showing-windows", methods=["GET"])
def list_windows(listing_id):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    if listing_id not in store.listings:
        raise not_found("Listing not found")
    items = sorted(
        (w for w in store.windows.values() if w["listing_id"] == listing_id),
        key=lambda w: (w["created_at"], w["_seq"]))
    page, limit, offset, total = paginate(items)
    return success_list([window_json(w) for w in page], limit, offset, total)


@bp.route("/showing-windows/<window_id>", methods=["GET"])
def get_window(window_id):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    window = store.windows.get(window_id)
    if window is None:
        raise not_found("ShowingWindow not found")
    return success_object(window_json(window))


@bp.route("/showing-windows/<window_id>/feedback", methods=["POST"])
def create_feedback(window_id):
    uid, role = authenticate()
    require_roles(role, WRITE_ROLES)
    window = store.windows.get(window_id)
    if window is None:
        raise not_found("ShowingWindow not found")
    listing = store.listings.get(window["listing_id"])
    if listing is not None:
        check_listing_ownership(role, uid, listing)
    body = get_body()
    rating = f_int(body, "rating", required=True)
    if rating < 1 or rating > 5:
        raise invalid("rating must be between 1 and 5 inclusive")
    comment = f_str(body, "comment")
    now = clock.now()
    # Window-ended check precedes the duplicate check (PRD 3.8).
    if now < window["ends_at"]:
        raise ApiError(ERR_WINDOW_NOT_ENDED, 422,
                       "Feedback not allowed before the window ends")
    if any(f["showing_window_id"] == window["id"]
           for f in store.feedbacks.values()):
        raise ApiError(ERR_FEEDBACK_ALREADY_EXISTS, 409,
                       "Window already has feedback")
    feedback = stamp({
        "showing_window_id": window["id"],
        "listing_id": window["listing_id"],
        "rating": rating,
        "comment": comment,
        "status": "INCLUDED",
    }, now)
    store.feedbacks[feedback["id"]] = feedback
    return success_object(feedback_json(feedback), status=201)


@bp.route("/showing-windows/<window_id>/feedback", methods=["GET"])
def window_feedback(window_id):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    window = store.windows.get(window_id)
    if window is None:
        raise not_found("ShowingWindow not found")
    items = sorted(
        (f for f in store.feedbacks.values()
         if f["showing_window_id"] == window["id"]),
        key=lambda f: (f["created_at"], f["_seq"]))
    page, limit, offset, total = paginate(items)
    return success_list([feedback_json(f) for f in page], limit, offset, total)


@bp.route("/listings/<listing_id>/feedbacks", methods=["GET"])
def listing_feedbacks(listing_id):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    if listing_id not in store.listings:
        raise not_found("Listing not found")
    status = request.args.get("status")
    items = sorted(
        (f for f in store.feedbacks.values() if f["listing_id"] == listing_id),
        key=lambda f: (f["created_at"], f["_seq"]))
    if status is not None:
        items = [f for f in items if f["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([feedback_json(f) for f in page], limit, offset, total)


@bp.route("/feedbacks/<feedback_id>/exclude", methods=["POST"])
def exclude_feedback(feedback_id):
    _, role = authenticate()
    require_roles(role, ("MarketingCoordinator",))
    feedback = store.feedbacks.get(feedback_id)
    if feedback is None:
        raise not_found("ShowingFeedback not found")
    get_body()
    if feedback["status"] != "INCLUDED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "exclude requires feedback status INCLUDED")
    feedback["status"] = "EXCLUDED"
    touch(feedback, clock.now())
    return success_object(feedback_json(feedback))
