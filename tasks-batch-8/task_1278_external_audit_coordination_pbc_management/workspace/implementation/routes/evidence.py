"""EvidenceUpload read endpoints."""
from flask import Blueprint, request
from db import db
from middleware import get_user_context, require_roles, parse_pagination
from response import success_object, success_list
from errors import ApiError, ERR_EVIDENCE_NOT_FOUND

bp = Blueprint("evidence", __name__)


@bp.route("/api/evidence-uploads", methods=["GET"])
def list_evidence():
    ctx = get_user_context()
    require_roles(ctx, ["Controller", "Preparer", "ExternalAuditor"])
    limit, offset = parse_pagination()
    pbc_request_id = request.args.get("pbc_request_id")
    engagement_id = request.args.get("engagement_id")
    status = request.args.get("status")
    items = list(db.evidence_uploads.values())
    if pbc_request_id:
        items = [e for e in items if e["pbc_request_id"] == pbc_request_id]
    if engagement_id:
        items = [e for e in items if e["engagement_id"] == engagement_id]
    if status:
        items = [e for e in items if e["status"] == status]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([dict(e) for e in page], limit, offset, total)


@bp.route("/api/evidence-uploads/<evidence_id>", methods=["GET"])
def get_evidence(evidence_id):
    ctx = get_user_context()
    require_roles(ctx, ["Controller", "Preparer", "ExternalAuditor"])
    ev = db.evidence_uploads.get(evidence_id)
    if ev is None:
        raise ApiError(ERR_EVIDENCE_NOT_FOUND, "EvidenceUpload id not found", 404)
    return success_object(dict(ev))
