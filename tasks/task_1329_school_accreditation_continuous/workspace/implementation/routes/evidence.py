"""EvidenceItem endpoints."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import get_or_404
from util import as_enum, as_str, body, paginate, pagination, required, stamp_new, touch

bp = Blueprint("evidence", __name__)

DECISIONS = {"APPROVED", "REJECTED"}


def evidence_view(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


@bp.post("/accreditation/ratings/<id>/evidence")
def create_evidence(id):
    user_id, _ = auth(["SchoolLeader"])
    rating_row = get_or_404("ratings", id, "SelfStudyRating")
    data = body()
    title = as_str(required(data, "title"), "title")
    artifact_uri = as_str(required(data, "artifact_uri"), "artifact_uri")
    record = {
        "id": new_id(),
        "rating_id": id,
        "title": title,
        "artifact_uri": artifact_uri,
        "submitted_by_user_id": user_id,
        "review_status": "PENDING",
    }
    stamp_new(record, with_version=True)
    DB["evidence"][record["id"]] = record
    return ok(evidence_view(record), status=201)


@bp.get("/accreditation/ratings/<id>/evidence")
def list_evidence(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader"])
    get_or_404("ratings", id, "SelfStudyRating")
    limit, offset = pagination()
    rows = [e for e in DB["evidence"].values() if e["rating_id"] == id]
    rows.sort(key=lambda e: e["created_at"])
    review_status = request.args.get("review_status")
    if review_status:
        rows = [r for r in rows if r["review_status"] == review_status]
    page, total = paginate(rows, limit, offset)
    return ok_list([evidence_view(r) for r in page], total, limit, offset)


@bp.post("/accreditation/evidence/<id>/review")
def review_evidence(id):
    user_id, _ = auth(["AccreditationOfficer"])
    item = get_or_404("evidence", id, "EvidenceItem")
    data = body()
    decision = as_enum(required(data, "decision"), "decision", DECISIONS)
    if item["review_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Evidence is not PENDING")
    rating_row = DB["ratings"].get(item["rating_id"])
    if rating_row is None or rating_row["status"] not in ("SUBMITTED", "FINALIZED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Parent rating must be SUBMITTED or FINALIZED",
        )
    # Segregation of duties: officer may not review their own submission.
    if item["submitted_by_user_id"] == user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            422,
            "Officer may not review their own submission",
        )
    item["review_status"] = decision
    touch(item)
    return ok(evidence_view(item))


@bp.post("/accreditation/evidence/<id>/resubmit")
def resubmit_evidence(id):
    auth(["SchoolLeader"])
    item = get_or_404("evidence", id, "EvidenceItem")
    if item["review_status"] != "REJECTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Evidence is not REJECTED")
    rating_row = DB["ratings"].get(item["rating_id"])
    if rating_row is None or rating_row["status"] not in ("SUBMITTED", "REOPENED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Parent rating must be SUBMITTED or REOPENED",
        )
    item["review_status"] = "PENDING"
    touch(item)
    return ok(evidence_view(item))
