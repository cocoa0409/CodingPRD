"""Document adjudication endpoints (verify/reject)."""
from flask import Blueprint

import db
from errors import ApiError, ERR_INVALID_STATE_TRANSITION
from middleware import require_roles
from response import success_object
from routes.common import get_json_body, lookup_or_404, require_str
from services.serializers import document_view

bp = Blueprint("documents", __name__)


def _now():
    return db.now_formatted()


def _bump(entity, now):
    entity["version"] += 1
    entity["updated_at"] = now


@bp.route("/documents/<did>/verify", methods=["POST"])
def verify_document(did):
    require_roles("SuitabilityReviewer")
    doc = lookup_or_404(db.documents, did, "CaseDocument")
    case = db.cases.get(doc["case_id"])
    if case is None:
        # Orphaned document shouldn't happen; treat as not found at case level
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Parent case not found", 409)
    if case["status"] not in ("SUITABILITY_REVIEW", "INFO_REQUESTED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Parent case must be in SUITABILITY_REVIEW or INFO_REQUESTED",
            409,
        )
    if doc["status"] != "SUBMITTED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Document must be SUBMITTED to verify",
            409,
        )
    doc["status"] = "VERIFIED"
    _bump(doc, _now())
    return success_object(document_view(doc), 200)


@bp.route("/documents/<did>/reject", methods=["POST"])
def reject_document(did):
    require_roles("SuitabilityReviewer")
    doc = lookup_or_404(db.documents, did, "CaseDocument")
    body = get_json_body()
    rationale = require_str(body, "rationale")
    case = db.cases.get(doc["case_id"])
    if case is None:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Parent case not found", 409)
    if case["status"] not in ("SUITABILITY_REVIEW", "INFO_REQUESTED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Parent case must be in SUITABILITY_REVIEW or INFO_REQUESTED",
            409,
        )
    if doc["status"] != "SUBMITTED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Document must be SUBMITTED to reject",
            409,
        )
    doc["status"] = "REJECTED"
    doc["rejection_reason"] = rationale
    _bump(doc, _now())
    return success_object(document_view(doc), 200)
