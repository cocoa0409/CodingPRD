"""ServicePhoto endpoints."""
from flask import Blueprint
from datetime import timedelta
import db
from middleware import require_roles, get_pagination, get_json_body
from response import success_object, success_created, success_list
from errors import *
from services.helpers import _touch

bp = Blueprint("photos", __name__)

ALLOWED_FIELDS = {"visit_id", "phase", "image_uri"}
VALID_PHASES = {"BEFORE", "AFTER"}


@bp.route("/photos", methods=["POST"])
def upload_photo():
    user_id, role = require_roles("CrewLead", "Subcontractor")
    body = get_json_body()
    unknown = set(body.keys()) - ALLOWED_FIELDS
    if unknown:
        raise ApiError(ERR_INVALID_REQUEST, f"Unknown fields: {', '.join(unknown)}", 400)

    visit_id = body.get("visit_id")
    phase = body.get("phase")
    image_uri = body.get("image_uri")

    if not visit_id:
        raise ApiError(ERR_INVALID_REQUEST, "visit_id is required", 400)
    visit = db.visits.get(visit_id)
    if not visit:
        raise ApiError(ERR_NOT_FOUND, f"Visit {visit_id} not found", 404)

    if not phase or phase not in VALID_PHASES:
        raise ApiError(ERR_INVALID_REQUEST, "phase must be BEFORE or AFTER", 400)
    if not image_uri:
        raise ApiError(ERR_INVALID_REQUEST, "image_uri is required", 400)

    # Ownership
    if role == "CrewLead":
        if visit.get("assigned_subcontractor_id") is not None:
            raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "CrewLead can only upload for in-house visits", 403)
    elif role == "Subcontractor":
        if visit.get("assigned_subcontractor_id") != user_id:
            raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your assigned visit", 403)

    # Contract must be ACTIVE
    contract = db.contracts.get(visit.get("contract_id"))
    if contract and contract.get("status") != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, f"Contract is {contract.get('status')}", 409)

    # Phase vs execution status
    exec_status = visit.get("execution_status")
    if phase == "BEFORE":
        if exec_status not in ("SCHEDULED", "IN_PROGRESS"):
            raise ApiError(ERR_INVALID_STATE, f"BEFORE photos require SCHEDULED or IN_PROGRESS, got {exec_status}", 409)
    elif phase == "AFTER":
        if exec_status != "IN_PROGRESS":
            raise ApiError(ERR_INVALID_STATE, f"AFTER photos require IN_PROGRESS, got {exec_status}", 409)

    photo = {
        "id": db._new_id(),
        "visit_id": visit_id,
        "phase": phase,
        "image_uri": image_uri,
        "review_status": "UPLOADED",
        "reviewed_by_user_id": None,
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
    }
    db.photos.create(photo)
    return success_created(photo)


@bp.route("/visits/<id>/photos", methods=["GET"])
def list_visit_photos(id):
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClientContact", "ClaimsAdjuster", "CrewLead", "Subcontractor")
    visit = db.visits.get(id)
    if not visit:
        raise ApiError(ERR_NOT_FOUND, f"Visit {id} not found", 404)
    if role == "ClientContact":
        contract = db.contracts.get(visit.get("contract_id"))
        if contract and contract.get("client_id") != user_id:
            raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your visit", 403)
    elif role == "Subcontractor":
        if visit.get("assigned_subcontractor_id") != user_id:
            raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your assigned visit", 403)

    limit, offset = get_pagination()
    all_photos = sorted(
        [p for p in db.photos.list_all() if p.get("visit_id") == id],
        key=lambda p: p.get("created_at", ""),
    )
    total = len(all_photos)
    page = all_photos[offset:offset + limit]
    return success_list(page, total, limit, offset)


@bp.route("/photos/<id>/accept", methods=["POST"])
def accept_photo(id):
    user_id, role = require_roles("OpsDispatcher")
    photo = db.photos.get(id)
    if not photo:
        raise ApiError(ERR_NOT_FOUND, f"Photo {id} not found", 404)
    if photo["review_status"] in ("ACCEPTED", "REJECTED"):
        raise ApiError(ERR_ALREADY_TERMINAL, f"Photo already {photo['review_status']}", 409)
    if photo["review_status"] != "UPLOADED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot accept from {photo['review_status']}", 409)

    # If visit is COMPLETED, check photo accept window
    visit = db.visits.get(photo.get("visit_id"))
    if visit and visit.get("execution_status") == "COMPLETED" and photo.get("phase") == "AFTER":
        completed_at = db._parse_iso(visit.get("completed_at"))
        if completed_at:
            clock = db.get_clock()
            window_end = completed_at + timedelta(minutes=360)
            if clock > window_end:
                raise ApiError(ERR_PHOTO_WINDOW_EXPIRED, "Photo accept window expired", 422)

    photo["review_status"] = "ACCEPTED"
    photo["reviewed_by_user_id"] = user_id
    _touch(photo)
    db.photos.update(id, photo)
    return success_object(photo)


@bp.route("/photos/<id>/reject", methods=["POST"])
def reject_photo(id):
    user_id, role = require_roles("OpsDispatcher")
    photo = db.photos.get(id)
    if not photo:
        raise ApiError(ERR_NOT_FOUND, f"Photo {id} not found", 404)
    if photo["review_status"] in ("ACCEPTED", "REJECTED"):
        raise ApiError(ERR_ALREADY_TERMINAL, f"Photo already {photo['review_status']}", 409)
    if photo["review_status"] != "UPLOADED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot reject from {photo['review_status']}", 409)
    photo["review_status"] = "REJECTED"
    photo["reviewed_by_user_id"] = user_id
    _touch(photo)
    db.photos.update(id, photo)
    return success_object(photo)
