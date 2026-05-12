"""Reviewer pool CRUD."""
from flask import Blueprint

import db
from errors import err
from middleware import require_auth
from response import success
from services.lookup import get_reviewer_or_404, check_version
from services.validation import get_body


bp = Blueprint("reviewers", __name__)


VALID_STATUSES = {"ACTIVE", "SUSPENDED"}


@bp.route("/reviewers", methods=["POST"])
@require_auth(roles={"SchoolAdmin"})
def create_reviewer():
    body = get_body()
    for f in ("full_name", "department_code"):
        if f not in body:
            raise err("ERR_BAD_REQUEST", f"Missing required field: {f}")

    fr = body.get("family_relation_student_ids", [])
    if not isinstance(fr, list):
        raise err("ERR_BAD_REQUEST", "family_relation_student_ids must be array")

    entity = {
        "full_name": body["full_name"],
        "department_code": body["department_code"],
        "family_relation_student_ids": list(fr),
        "status": "ACTIVE",
    }
    db.stamp_create(entity, common_fields=True)
    db.reviewers[entity["id"]] = entity
    return success(db.public(entity), 201)


@bp.route("/reviewers/<reviewer_id>", methods=["GET"])
@require_auth(roles={"SchoolAdmin", "DeptOfficer"})
def get_reviewer(reviewer_id):
    r = get_reviewer_or_404(reviewer_id)
    return success(db.public(r), 200)


@bp.route("/reviewers/<reviewer_id>", methods=["PATCH"])
@require_auth(roles={"SchoolAdmin"})
def update_reviewer(reviewer_id):
    r = get_reviewer_or_404(reviewer_id)
    body = get_body()
    check_version(r, body)

    if "status" in body:
        new_status = body["status"]
        if new_status not in VALID_STATUSES:
            raise err("ERR_BAD_REQUEST", f"Invalid status: {new_status}")
        r["status"] = new_status
    if "family_relation_student_ids" in body:
        fr = body["family_relation_student_ids"]
        if not isinstance(fr, list):
            raise err("ERR_BAD_REQUEST", "family_relation_student_ids must be array")
        r["family_relation_student_ids"] = list(fr)

    db.stamp_update(r)
    return success(db.public(r), 200)
