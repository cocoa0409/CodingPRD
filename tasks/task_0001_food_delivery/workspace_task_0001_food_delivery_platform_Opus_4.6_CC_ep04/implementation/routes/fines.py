from flask import Blueprint, request
from middleware.auth import require_roles
from storage import db
from response import success_response
from errors import raise_error, ERR_NOT_FOUND, ERR_FORBIDDEN, ERR_INVALID_STATE, ERR_VALIDATION
from services.fine_service import waive_fine

bp = Blueprint("fines", __name__)


@bp.route("/api/fines/<fine_id>", methods=["GET"])
@require_roles("PlatformAdmin", "CustomerService", "Rider", "Restaurant", "Customer")
def get_fine(fine_id):
    f = db.fines.get(fine_id)
    if not f:
        raise_error(ERR_NOT_FOUND, "Fine not found.")

    if request.user_role in ("Rider", "Restaurant", "Customer"):
        if request.user_id != f.subject_id:
            raise_error(ERR_FORBIDDEN, "Cannot view another entity's fine.")

    return success_response(f.to_dict())


@bp.route("/api/fines", methods=["GET"])
@require_roles("PlatformAdmin", "CustomerService", "Rider", "Restaurant", "Customer")
def list_fines():
    subject_type_filter = request.args.get("subject_type")
    subject_id_filter = request.args.get("subject_id")
    settlement_status_filter = request.args.get("settlement_status")
    limit = request.args.get("limit", 10, type=int)
    offset = request.args.get("offset", 0, type=int)

    if limit < 1 or limit > 100:
        raise_error(ERR_VALIDATION, "limit must be between 1 and 100.")
    if offset < 0:
        raise_error(ERR_VALIDATION, "offset must be >= 0.")

    if request.user_role in ("Rider", "Restaurant", "Customer"):
        if subject_id_filter and subject_id_filter != request.user_id:
            raise_error(ERR_FORBIDDEN, "Cannot view another entity's fines.")

    items = sorted(db.fines.values(), key=lambda f: f.created_at)
    if subject_type_filter:
        items = [f for f in items if f.subject_type == subject_type_filter]
    if subject_id_filter:
        items = [f for f in items if f.subject_id == subject_id_filter]
    if settlement_status_filter:
        items = [f for f in items if f.settlement_status == settlement_status_filter]

    if request.user_role in ("Rider", "Restaurant", "Customer"):
        items = [f for f in items if f.subject_id == request.user_id]

    total_count = len(items)
    page = items[offset:offset + limit]
    return success_response(
        [f.to_dict() for f in page],
        pagination={
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + limit < total_count,
        },
    )


@bp.route("/api/fines/<fine_id>/waive", methods=["POST"])
@require_roles("CustomerService", "PlatformAdmin")
def waive_fine_endpoint(fine_id):
    f = db.fines.get(fine_id)
    if not f:
        raise_error(ERR_NOT_FOUND, "Fine not found.")
    if f.settlement_status != "PENDING":
        raise_error(ERR_INVALID_STATE, "Fine must be in PENDING status to waive.")
    waive_fine(f)
    return success_response(f.to_dict())
