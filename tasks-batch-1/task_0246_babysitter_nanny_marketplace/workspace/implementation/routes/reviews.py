"""Review endpoints (PRD §3.10)."""

from flask import Blueprint, request

import errors
from db import store
from errors import err
from middleware import authenticate, require_roles, get_json, parse_pagination, paginate
from response import ok
from services import validate as v
from services.common import base_record, touch
from services.ledger import recompute_caregiver_rating
from services.lookup import (get_family, get_caregiver, get_booking, get_review,
                             sorted_by_created)
from services.serialize import review_out

bp = Blueprint("reviews", __name__)

DECISIONS = {"PUBLISH", "HIDE"}


@bp.route("/marketplace/reviews", methods=["POST"])
def create_review():
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family"})
    body = get_json()
    booking_id = v.req_str(body, "booking_id")
    family_id = v.req_str(body, "family_id")
    caregiver_id = v.req_str(body, "caregiver_id")
    rating_value = v.req_int(body, "rating_value", minimum=1, maximum=5)
    comment = v.opt_str(body, "comment", default=None)

    if auth.is_family and auth.user_id != family_id:
        raise err(errors.ERR_FORBIDDEN, "Family may only author its own reviews")

    # Existence (priority 3): body FKs left to right.
    booking = get_booking(booking_id)
    get_family(family_id)
    get_caregiver(caregiver_id)

    # Review eligibility (priority 14): booking COMPLETED and authoring family
    # owns the booking.
    if booking["family_id"] != family_id:
        raise err(errors.ERR_FORBIDDEN, "Author family does not own the booking")
    if booking["status"] != "COMPLETED":
        raise err(errors.ERR_BOOKING_NOT_COMPLETED, "Booking is not COMPLETED")

    rec = base_record()
    rec.update({
        "booking_id": booking_id,
        "family_id": family_id,
        "caregiver_id": caregiver_id,
        "rating_value": rating_value,
        "comment": comment,
        "status": "PENDING_MODERATION",
    })
    store.reviews[rec["id"]] = rec
    return ok(review_out(rec), status=201)


@bp.route("/marketplace/reviews/<rid>", methods=["GET"])
def get_one_review(rid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family", "Caregiver"})
    r = get_review(rid)
    if auth.is_family and auth.user_id != r["family_id"]:
        raise err(errors.ERR_FORBIDDEN, "Family may only read its own reviews")
    if auth.is_caregiver and auth.user_id != r["caregiver_id"]:
        raise err(errors.ERR_FORBIDDEN, "Caregiver may only read its own reviews")
    return ok(review_out(r), status=200)


@bp.route("/marketplace/reviews", methods=["GET"])
def list_reviews():
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family", "Caregiver"})
    limit, offset = parse_pagination()
    booking_id = request.args.get("booking_id")
    family_id = request.args.get("family_id")
    caregiver_id = request.args.get("caregiver_id")
    status = request.args.get("status")

    items = list(store.reviews.values())
    if auth.is_family:
        items = [r for r in items if r["family_id"] == auth.user_id]
    if auth.is_caregiver:
        items = [r for r in items if r["caregiver_id"] == auth.user_id]
    if booking_id is not None:
        items = [r for r in items if r["booking_id"] == booking_id]
    if family_id is not None:
        items = [r for r in items if r["family_id"] == family_id]
    if caregiver_id is not None:
        items = [r for r in items if r["caregiver_id"] == caregiver_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items, limit, offset)
    return ok([review_out(r) for r in page], status=200, pagination=meta)


@bp.route("/marketplace/reviews/<rid>/moderate", methods=["POST"])
def moderate_review(rid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin"})
    r = get_review(rid)
    body = get_json()
    decision = v.req_enum(body, "decision", DECISIONS)

    if decision == "PUBLISH":
        if r["status"] != "PENDING_MODERATION":
            raise err(errors.ERR_INVALID_STATE, "PUBLISH requires PENDING_MODERATION")
        r["status"] = "PUBLISHED"
        touch(r)
        caregiver = get_caregiver(r["caregiver_id"])
        recompute_caregiver_rating(caregiver)
        touch(caregiver)
    else:  # HIDE
        if r["status"] not in {"PENDING_MODERATION", "PUBLISHED"}:
            raise err(errors.ERR_INVALID_STATE, "HIDE requires PENDING_MODERATION or PUBLISHED")
        was_published = r["status"] == "PUBLISHED"
        r["status"] = "HIDDEN"
        touch(r)
        if was_published:
            caregiver = get_caregiver(r["caregiver_id"])
            recompute_caregiver_rating(caregiver)
            touch(caregiver)

    return ok(review_out(r), status=200)
