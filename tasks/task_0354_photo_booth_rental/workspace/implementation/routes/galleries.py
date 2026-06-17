"""Gallery reads, photo upload, and cyclic publish/unpublish (PRD §3.9)."""
import random

from flask import Blueprint

import db
import errors
from errors import err
from middleware import authenticate, require_role
from response import success
import helpers
from services.serialize import plain_out

bp = Blueprint("galleries", __name__)


def _mint_pin():
    return "".join(random.choice("0123456789") for _ in range(6))


@bp.route("/galleries/<gal_id>", methods=["GET"])
def get_gallery(gal_id):
    user_id, role = authenticate()
    require_role(role, {"Customer", "OperationsManager", "PlatformAdmin"})
    rec = db.galleries.get(gal_id)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Gallery not found.")
    if role == "Customer":
        booking = db.bookings.get(rec["booking_id"])
        if not booking or booking["customer_id"] != user_id:
            raise err(errors.ERR_NOT_BOOKING_OWNER, "Gallery is not owned by the caller.")
    return success(plain_out(rec), 200)


@bp.route("/galleries/<gal_id>/photos", methods=["POST"])
def upload_photos(gal_id):
    _, role = authenticate()
    require_role(role, {"OperationsManager"})
    rec = db.galleries.get(gal_id)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Gallery not found.")
    body = helpers.get_json()
    count = helpers.require_int(body, "count", minimum=0)
    rec["photo_count"] = rec["photo_count"] + count
    db.touch(rec)
    return success(plain_out(rec), 200)


@bp.route("/galleries/<gal_id>/publish", methods=["POST"])
def publish_gallery(gal_id):
    _, role = authenticate()
    require_role(role, {"OperationsManager"})
    rec = db.galleries.get(gal_id)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Gallery not found.")
    booking = db.bookings.get(rec["booking_id"])

    # State (priority 30) before gallery-content (priority 60).
    if rec["status"] not in ("DRAFT", "UNPUBLISHED"):
        raise err(errors.ERR_INVALID_STATE, "Publish requires DRAFT or UNPUBLISHED state.")

    if rec["status"] == "DRAFT":
        # First publish: parent COMPLETED + PAID_IN_FULL.
        if not booking or booking["schedule_status"] != "COMPLETED":
            raise err(errors.ERR_INVALID_STATE, "Publish requires the parent booking COMPLETED.")
        if booking["payment_status"] != "PAID_IN_FULL":
            raise err(errors.ERR_INVALID_STATE, "Publish requires PAID_IN_FULL payment status.")
    else:  # UNPUBLISHED -> PUBLISHED: only PAID_IN_FULL required.
        if not booking or booking["payment_status"] != "PAID_IN_FULL":
            raise err(errors.ERR_INVALID_STATE, "Re-publish requires PAID_IN_FULL payment status.")

    if rec["photo_count"] < 1:
        raise err(errors.ERR_GALLERY_EMPTY, "Gallery must have at least one photo to publish.")

    rec["access_pin"] = _mint_pin()
    rec["status"] = "PUBLISHED"
    db.touch(rec)
    return success(plain_out(rec), 200)


@bp.route("/galleries/<gal_id>/unpublish", methods=["POST"])
def unpublish_gallery(gal_id):
    _, role = authenticate()
    require_role(role, {"OperationsManager"})
    rec = db.galleries.get(gal_id)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Gallery not found.")
    if rec["status"] != "PUBLISHED":
        raise err(errors.ERR_INVALID_STATE, "Unpublish requires PUBLISHED state.")
    rec["access_pin"] = None
    rec["status"] = "UNPUBLISHED"
    db.touch(rec)
    return success(plain_out(rec), 200)
