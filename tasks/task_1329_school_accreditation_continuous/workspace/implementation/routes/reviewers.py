"""Reviewer endpoints."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import get_or_404
from util import as_str, body, paginate, pagination, required, stamp_new, touch

bp = Blueprint("reviewers", __name__)


def reviewer_view(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}


@bp.post("/accreditation/reviewers")
def create_reviewer():
    auth(["AccreditationOfficer"])
    data = body()
    full_name = as_str(required(data, "full_name"), "full_name")
    email = as_str(required(data, "email"), "email")
    conflict_system_ids = data.get("conflict_system_ids", [])
    if not isinstance(conflict_system_ids, list) or not all(
        isinstance(x, str) for x in conflict_system_ids
    ):
        raise ApiError(
            "ERR_VALIDATION", 400, "conflict_system_ids must be a list of strings"
        )
    for r in DB["reviewers"].values():
        if r["email"] == email:
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE", 409, f"Reviewer email {email} already exists"
            )
    record = {
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "reviewer_status": "AVAILABLE",
        "conflict_system_ids": list(conflict_system_ids),
    }
    stamp_new(record, with_version=True)
    DB["reviewers"][record["id"]] = record
    return ok(reviewer_view(record), status=201)


@bp.get("/accreditation/reviewers")
def list_reviewers():
    auth(["AccreditationOfficer", "AccreditationCommission"])
    limit, offset = pagination()
    rows = sorted(DB["reviewers"].values(), key=lambda r: r["created_at"])
    status = request.args.get("reviewer_status")
    if status:
        rows = [r for r in rows if r["reviewer_status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([reviewer_view(r) for r in page], total, limit, offset)


@bp.get("/accreditation/reviewers/<id>")
def get_reviewer(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "Reviewer"])
    row = get_or_404("reviewers", id, "Reviewer")
    return ok(reviewer_view(row))


@bp.post("/accreditation/reviewers/<id>/deactivate")
def deactivate_reviewer(id):
    auth(["AccreditationOfficer"])
    reviewer = get_or_404("reviewers", id, "Reviewer")
    if reviewer["reviewer_status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE", 409, "Reviewer is not AVAILABLE")
    blocking = {"REQUESTED", "CONFIRMED", "IN_FIELD", "REPORT_DRAFT"}
    for a in DB["assignments"].values():
        if a["reviewer_id"] != id:
            continue
        v = DB["visits"].get(a["visit_id"])
        if v is not None and v["status"] in blocking:
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Reviewer is assigned to a visit in an active state",
            )
    reviewer["reviewer_status"] = "INACTIVE"
    touch(reviewer)
    return ok(reviewer_view(reviewer))


@bp.get("/accreditation/reviewers/<id>/assignments")
def list_reviewer_assignments(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "Reviewer"])
    get_or_404("reviewers", id, "Reviewer")
    limit, offset = pagination()
    rows = [a for a in DB["assignments"].values() if a["reviewer_id"] == id]
    rows.sort(key=lambda a: a["created_at"])
    page, total = paginate(rows, limit, offset)
    from routes.visits import assignment_view
    return ok_list([assignment_view(r) for r in page], total, limit, offset)


@bp.get("/accreditation/reviewers/<id>/visits")
def list_reviewer_visits(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "Reviewer"])
    get_or_404("reviewers", id, "Reviewer")
    limit, offset = pagination()
    rows = [v for v in DB["visits"].values() if v["lead_reviewer_id"] == id]
    rows.sort(key=lambda v: v["created_at"])
    page, total = paginate(rows, limit, offset)
    from routes.visits import visit_view
    return ok_list([visit_view(r) for r in page], total, limit, offset)
