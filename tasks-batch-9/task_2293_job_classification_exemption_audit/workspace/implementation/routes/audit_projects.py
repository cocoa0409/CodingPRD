"""Engagement lifecycle (PRD 3.1, 3.9)."""
from flask import Blueprint

import db
from constants import ALL_ROLES, LOOKBACK_POLICIES, PROJECT_STATUSES
from errors import fail
from middleware import body, endpoint, pagination
from response import success, success_list
from services import derive, lookup, serialize
from validation import opt_enum, req_enum, req_int, req_str

bp = Blueprint("audit_projects", __name__)

DECLARED_STAGE_EDGES = {
    ("PLANNING", "FIELDWORK"),
    ("FIELDWORK", "REMEDIATION"),
    ("REMEDIATION", "FIELDWORK"),
    ("REMEDIATION", "CLOSED"),
}


@bp.post("/audit-projects")
@endpoint(["ProgramAdmin"])
def create_project():
    payload = body()
    name = req_str(payload, "name")
    fiscal_year = req_int(payload, "fiscal_year", minimum=2000, maximum=2100)
    lookback_policy = opt_enum(
        payload, "lookback_policy", LOOKBACK_POLICIES, default="STANDARD_2Y"
    )

    row = db.make_row(
        name=name,
        fiscal_year=fiscal_year,
        lookback_policy=lookback_policy,
        status="PLANNING",
    )
    db.audit_projects[row["id"]] = row
    return success(serialize.audit_project(row), 201)


@bp.get("/audit-projects/<project_id>")
@endpoint(ALL_ROLES)
def get_project(project_id):
    project = lookup.project(project_id)
    return success(serialize.audit_project(project), 200)


@bp.post("/audit-projects/<project_id>/status")
@endpoint(["ProgramAdmin"])
def set_project_status(project_id):
    project = lookup.project(project_id)
    payload = body()
    target = req_enum(payload, "target_status", PROJECT_STATUSES)

    current = project["status"]
    if (current, target) not in DECLARED_STAGE_EDGES:
        fail("ERR_PROJECT_STAGE_INVALID")

    families = derive.families_of_project(project["id"])
    positions = derive.positions_of_project(project["id"])

    if target == "FIELDWORK" and current == "PLANNING":
        if not families:
            fail("ERR_PROJECT_STAGE_PRECONDITION_UNMET")
    elif target == "REMEDIATION":
        if any(p["classification_status"] == "UNREVIEWED" for p in positions):
            fail("ERR_PROJECT_STAGE_PRECONDITION_UNMET")
    elif target == "FIELDWORK" and current == "REMEDIATION":
        if not any(p["classification_status"] == "UNREVIEWED" for p in positions):
            fail("ERR_PROJECT_STAGE_PRECONDITION_UNMET")
    elif target == "CLOSED":
        if any(p["classification_status"] == "MISCLASSIFIED" for p in positions):
            fail("ERR_PROJECT_NOT_READY_TO_CLOSE")
        for case in derive.cases_of_project(project["id"]):
            if derive.case_status(case) != "COMPLETED":
                fail("ERR_PROJECT_NOT_READY_TO_CLOSE")
        for correction in derive.corrections_of_project(project["id"]):
            if correction["status"] not in ("APPROVED", "REJECTED"):
                fail("ERR_PROJECT_NOT_READY_TO_CLOSE")
        for review in derive.reviews_of_project(project["id"]):
            if review["status"] == "DRAFT":
                fail("ERR_PROJECT_NOT_READY_TO_CLOSE")

    # --- side effects ------------------------------------------------------
    if target == "REMEDIATION":
        ranked = sorted(
            families,
            key=lambda f: (
                -derive.family_view(f)["risk_score"],
                -derive.family_view(f)["family_headcount"],
                f["created_at"],
                f["_seq"],
            ),
        )
        for index, family in enumerate(ranked, start=1):
            family["remediation_priority_rank"] = index
    elif target == "FIELDWORK" and current == "REMEDIATION":
        for family in families:
            family["remediation_priority_rank"] = None

    project["status"] = target
    db.touch(project)
    return success(serialize.audit_project(project), 200)


@bp.get("/audit-projects/<project_id>/job-families")
@endpoint(ALL_ROLES)
def list_project_families(project_id):
    project = lookup.project(project_id)
    limit, offset = pagination()
    rows = derive.families_of_project(project["id"])
    items, total = serialize.paginate(rows, limit, offset, serialize.job_family)
    return success_list(items, limit, offset, total)


@bp.get("/audit-projects/<project_id>/contractor-reviews")
@endpoint(ALL_ROLES)
def list_project_reviews(project_id):
    project = lookup.project(project_id)
    limit, offset = pagination()
    rows = derive.reviews_of_project(project["id"])
    items, total = serialize.paginate(rows, limit, offset, serialize.contractor_review)
    return success_list(items, limit, offset, total)
