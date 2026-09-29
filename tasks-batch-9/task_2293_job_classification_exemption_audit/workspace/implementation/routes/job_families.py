"""Job family tree (PRD 3.1, 3.6)."""
from flask import Blueprint

import db
from constants import ALL_ROLES
from errors import fail
from middleware import body, endpoint, pagination
from response import success, success_list
from services import derive, lookup, serialize
from validation import opt_str, req_str

bp = Blueprint("job_families", __name__)


@bp.post("/job-families")
@endpoint(["ProgramAdmin"])
def create_family():
    payload = body()
    project_id = req_str(payload, "audit_project_id")
    name = req_str(payload, "name")
    code = req_str(payload, "code")
    parent_family_id = opt_str(payload, "parent_family_id", default=None)

    # rank 5: foreign keys
    project = lookup.project(project_id)
    if parent_family_id is not None:
        lookup.family(parent_family_id)

    # rank 6: engagement posture
    if derive.remediation_posture(project) == "FROZEN":
        fail("ERR_PROJECT_POSTURE_FROZEN")

    # rank 13: code unique within the engagement
    for existing in derive.families_of_project(project["id"]):
        if existing["code"] == code:
            fail("ERR_DUPLICATE_CODE")

    row = db.make_row(
        audit_project_id=project["id"],
        parent_family_id=parent_family_id,
        name=name,
        code=code,
        remediation_priority_rank=None,
    )
    db.job_families[row["id"]] = row
    return success(serialize.job_family(row), 201)


@bp.get("/job-families/<family_id>")
@endpoint(ALL_ROLES)
def get_family(family_id):
    family = lookup.family(family_id)
    return success(serialize.job_family(family), 200)


@bp.get("/job-families/<family_id>/child-families")
@endpoint(ALL_ROLES)
def list_child_families(family_id):
    family = lookup.family(family_id)
    limit, offset = pagination()
    rows = db.ordered(
        [f for f in db.job_families.values() if f["parent_family_id"] == family["id"]]
    )
    items, total = serialize.paginate(rows, limit, offset, serialize.job_family)
    return success_list(items, limit, offset, total)


@bp.get("/job-families/<family_id>/positions")
@endpoint(ALL_ROLES)
def list_family_positions(family_id):
    family = lookup.family(family_id)
    limit, offset = pagination()
    rows = derive.positions_of_family(family["id"])
    items, total = serialize.paginate(rows, limit, offset, serialize.position)
    return success_list(items, limit, offset, total)
