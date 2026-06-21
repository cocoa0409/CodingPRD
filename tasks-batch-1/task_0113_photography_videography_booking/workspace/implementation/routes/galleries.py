"""Galleries, proofing loop, and proof selections (PRD §3.7)."""
from __future__ import annotations

from flask import Blueprint, request, g

import db
from errors import (
    APIError,
    ERR_NOT_FOUND,
    ERR_INVALID_REFERENCE,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_DUPLICATE_RESOURCE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_REVISION_LIMIT,
    ERR_INSUFFICIENT_IMAGES,
)
from middleware import (
    require_auth, ROLE_CLIENT, ROLE_PHOTOGRAPHER, ROLE_STUDIO_ADMIN,
)
from response import ok_object, ok_array
from routes._helpers import (
    get_body, require_str, require_int, serialize, serialize_list,
    parse_pagination, paginate, order_by_created_at,
)
from services.common import stamp_create, touch

bp = Blueprint("galleries", __name__)

MAX_REVISION_ROUNDS = 2


@bp.post("/studio/galleries")
def create_gallery():
    require_auth([ROLE_PHOTOGRAPHER, ROLE_STUDIO_ADMIN])
    body = get_body()
    booking_id = require_str(body, "booking_id")

    booking = db.bookings.get(booking_id)
    if booking is None:
        raise APIError(ERR_INVALID_REFERENCE, 422, "Booking does not exist")

    # Ownership (priority 4): a Photographer creator must be the lead.
    if g.user_role == ROLE_PHOTOGRAPHER and g.user_id != booking["lead_photographer_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Caller is not the lead photographer")

    # One Gallery per booking (priority 18).
    for gl in db.galleries.values():
        if gl["booking_id"] == booking_id:
            raise APIError(ERR_DUPLICATE_RESOURCE, 409,
                           "A gallery already exists for this booking")

    gallery = {
        "booking_id": booking_id,
        "delivered_image_count": 0,
        "status": "PENDING_UPLOAD",
        "revision_round": 0,
    }
    stamp_create(gallery)
    db.galleries[gallery["id"]] = gallery
    return ok_object(serialize(gallery), 201)


def _find_gallery_or_404(id):
    gl = db.galleries.get(id)
    if gl is None:
        raise APIError(ERR_NOT_FOUND, 404, "Gallery not found")
    return gl


def _assert_gallery_read_owner(gallery):
    booking = db.bookings.get(gallery["booking_id"])
    if g.user_role == ROLE_CLIENT and (booking is None or g.user_id != booking["client_id"]):
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Caller does not own this gallery")
    if g.user_role == ROLE_PHOTOGRAPHER and (booking is None or g.user_id != booking["lead_photographer_id"]):
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Caller is not the lead photographer")


@bp.get("/studio/galleries/<id>")
def get_gallery(id):
    require_auth([ROLE_CLIENT, ROLE_PHOTOGRAPHER, ROLE_STUDIO_ADMIN])
    gl = _find_gallery_or_404(id)
    _assert_gallery_read_owner(gl)
    return ok_object(serialize(gl), 200)


@bp.get("/studio/galleries")
def list_galleries():
    require_auth([ROLE_CLIENT, ROLE_PHOTOGRAPHER, ROLE_STUDIO_ADMIN])
    limit, offset = parse_pagination()
    items = list(db.galleries.values())
    for field in ("booking_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [gl for gl in items if gl[field] == val]
    if g.user_role == ROLE_CLIENT:
        owned = {b["id"] for b in db.bookings.values() if b["client_id"] == g.user_id}
        items = [gl for gl in items if gl["booking_id"] in owned]
    elif g.user_role == ROLE_PHOTOGRAPHER:
        owned = {b["id"] for b in db.bookings.values() if b["lead_photographer_id"] == g.user_id}
        items = [gl for gl in items if gl["booking_id"] in owned]
    items = order_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.post("/studio/galleries/<id>/upload")
def upload_images(id):
    require_auth([ROLE_PHOTOGRAPHER])
    gl = _find_gallery_or_404(id)
    booking = db.bookings.get(gl["booking_id"])

    # Ownership (priority 4): caller must be the lead photographer.
    if booking is None or g.user_id != booking["lead_photographer_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Caller is not the lead photographer")

    body = get_body()
    delivered_image_count = require_int(body, "delivered_image_count", min_value=1)

    if gl["status"] == "PENDING_UPLOAD":
        # First upload requires the booking to be SHOT.
        if booking["workflow_status"] != "SHOT":
            raise APIError(ERR_INVALID_STATE, 409, "Booking is not SHOT")
        gl["delivered_image_count"] = delivered_image_count
        gl["status"] = "PROOFING"
        touch(gl)
        return ok_object(serialize(gl), 200)

    if gl["status"] == "REVISION_REQUESTED":
        # Revision return: set new count, bump revision_round, re-enter PROOFING.
        gl["delivered_image_count"] = delivered_image_count
        gl["revision_round"] += 1
        gl["status"] = "PROOFING"
        touch(gl)
        return ok_object(serialize(gl), 200)

    raise APIError(ERR_INVALID_STATE, 409, "Gallery cannot accept an upload from its state")


@bp.post("/studio/galleries/<id>/request-revision")
def request_revision(id):
    require_auth([ROLE_CLIENT])
    gl = _find_gallery_or_404(id)
    booking = db.bookings.get(gl["booking_id"])

    # Ownership (priority 4): caller must own the gallery's booking.
    if booking is None or g.user_id != booking["client_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Caller does not own this gallery")

    # State legality (priority 6).
    if gl["status"] != "PROOFING":
        raise APIError(ERR_INVALID_STATE, 409, "Gallery is not PROOFING")

    # Revision limit (priority 13).
    if gl["revision_round"] >= MAX_REVISION_ROUNDS:
        raise APIError(ERR_REVISION_LIMIT, 409, "Revision limit reached")

    gl["status"] = "REVISION_REQUESTED"
    touch(gl)
    return ok_object(serialize(gl), 200)


@bp.post("/studio/galleries/<id>/finalize")
def finalize_gallery(id):
    require_auth([ROLE_PHOTOGRAPHER])
    gl = _find_gallery_or_404(id)
    booking = db.bookings.get(gl["booking_id"])

    # Ownership (priority 4): caller must be the lead photographer.
    if booking is None or g.user_id != booking["lead_photographer_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Caller is not the lead photographer")

    # State legality (priority 6).
    if gl["status"] != "PROOFING":
        raise APIError(ERR_INVALID_STATE, 409, "Gallery is not PROOFING")
    if booking["workflow_status"] != "SHOT":
        raise APIError(ERR_INVALID_STATE, 409, "Booking is not SHOT")

    # Image sufficiency (priority 14).
    package = db.session_packages[booking["package_id"]]
    if gl["delivered_image_count"] < package["included_edited_images"]:
        raise APIError(ERR_INSUFFICIENT_IMAGES, 422,
                       "Delivered image count is below the package threshold")

    gl["status"] = "FINALIZED"
    touch(gl)
    booking["workflow_status"] = "DELIVERED"
    touch(booking)
    return ok_object(serialize(gl), 200)


# ---- Proof selections (PRD §3.7) --------------------------------------------
@bp.post("/studio/galleries/<id>/proof-selections")
def create_proof_selection(id):
    require_auth([ROLE_CLIENT])
    gl = _find_gallery_or_404(id)
    booking = db.bookings.get(gl["booking_id"])

    # Ownership (priority 4): caller must own the gallery's booking.
    if booking is None or g.user_id != booking["client_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Caller does not own this gallery")

    # While the gallery is PROOFING the client may record a selection.
    if gl["status"] != "PROOFING":
        raise APIError(ERR_INVALID_STATE, 409, "Gallery is not PROOFING")

    body = get_body()
    selected_image_count = require_int(body, "selected_image_count", min_value=1)

    # ProofSelection is lean: id + created_at only (no updated_at / version).
    selection = {
        "gallery_id": gl["id"],
        "selected_image_count": selected_image_count,
        "round_index": gl["revision_round"],
    }
    stamp_create(selection, with_version=False)
    db.proof_selections[selection["id"]] = selection
    return ok_object(serialize(selection), 201)


@bp.get("/studio/galleries/<id>/proof-selections")
def list_proof_selections(id):
    require_auth([ROLE_CLIENT, ROLE_PHOTOGRAPHER, ROLE_STUDIO_ADMIN])
    gl = _find_gallery_or_404(id)
    _assert_gallery_read_owner(gl)
    limit, offset = parse_pagination()
    items = [s for s in db.proof_selections.values() if s["gallery_id"] == gl["id"]]
    items = order_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)
