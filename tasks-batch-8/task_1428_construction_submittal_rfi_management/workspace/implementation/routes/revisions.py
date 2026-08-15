"""SubmittalRevision routes: create (OCC), list, route, return."""
from flask import Blueprint, request

import calc
from authz import ALL_ROLES, PROJECT_ENGINEER, REVIEWER, SUBCONTRACTOR_REP, require_roles
from db import store
from errors import (
    discipline_mismatch,
    invalid_request,
    no_eligible_reviewer,
    project_not_found,
    reviewer_at_capacity,
    reviewer_not_assigned,
    reviewer_not_found,
    revision_not_found,
    revision_not_submitted,
    revision_not_under_review,
    stale_submittal_version,
    subcontractor_suspended,
    submittal_not_accepting_revisions,
    submittal_not_found,
    submittal_terminal,
    wrong_subcontractor,
)
from respond import success
from serialize import ser_revision
from services import require_active
from store_ops import (
    json_body,
    new_common_fields,
    new_id,
    opt_str,
    paginate,
    req_enum,
    req_int,
    req_str,
    sorted_by_creation,
    touch,
)

bp = Blueprint("revisions", __name__)

ACTION_CODES = ("A", "B", "C", "D")


def get_revision_or_404(revision_id):
    r = store.revisions.get(revision_id)
    if r is None:
        raise revision_not_found()
    return r


@bp.route("/v1/submittals/<submittalId>/revisions", methods=["POST"])
def create_revision(submittalId):
    uid, role = require_roles([SUBCONTRACTOR_REP])
    sub = store.submittals.get(submittalId)
    if sub is None:
        raise submittal_not_found()
    project = store.projects.get(sub["project_id"])
    if project is None:
        raise project_not_found()
    section = store.spec_sections.get(sub["spec_section_id"])
    data = json_body()
    document_ref = req_str(data, "document_ref")
    notes = opt_str(data, "notes", "")
    expected_submittal_version = req_int(data, "expected_submittal_version")

    # Priority 3: entity-backed ownership — sub rep must be the responsible sub
    if section is not None:
        if section.get("responsible_subcontractor_id") is None or uid != section["responsible_subcontractor_id"]:
            raise wrong_subcontractor()
    else:
        raise wrong_subcontractor()

    # Priority 6 (PRD §2.10): OCC version match precedes posture and state
    if sub["version"] != expected_submittal_version:
        raise stale_submittal_version()

    # Priority 7: posture gate
    require_active(project)

    # Priority 8: state check on submittal
    if sub["review_status"] in ("CLOSED", "VOID"):
        raise submittal_terminal()
    if sub["review_status"] not in ("REGISTERED", "RETURNED_NEEDS_RESUBMIT"):
        raise submittal_not_accepting_revisions()

    # Standing gate
    sub_entity = store.subcontractors.get(uid)
    if sub_entity is not None and sub_entity["standing"] == "SUSPENDED":
        raise subcontractor_suspended()

    # Supersede prior C/D RETURNED revision
    for rev in store.revisions.values():
        if rev["submittal_id"] == sub["id"] and rev["status"] == "RETURNED" and rev.get("action_code") in ("C", "D"):
            rev["status"] = "SUPERSEDED"
            touch(rev)

    revision = {
        "id": new_id(),
        "_seq": next(store.seq),
        **new_common_fields(),
        "submittal_id": sub["id"],
        "revision_number": sub["revision_count"],
        "document_ref": document_ref,
        "notes": notes,
        "status": "SUBMITTED",
        "action_code": None,
        "reviewer_id": None,
        "submitted_date": calc.clock_date(),
        "routed_date": None,
        "review_due_date": None,
        "returned_date": None,
        "is_late_return": False,
        "return_comments": "",
    }
    store.revisions[revision["id"]] = revision
    sub["revision_count"] += 1
    sub["review_status"] = "IN_REVIEW"
    touch(sub)
    return success(ser_revision(revision), status=201)


@bp.route("/v1/submittals/<submittalId>/revisions", methods=["GET"])
def list_revisions(submittalId):
    require_roles(ALL_ROLES)
    sub = store.submittals.get(submittalId)
    if sub is None:
        raise submittal_not_found()
    items = [r for r in store.revisions.values() if r["submittal_id"] == submittalId]
    items.sort(key=lambda r: r["revision_number"])
    page, pagination = paginate(items)
    return success([ser_revision(r) for r in page], response_type="array", pagination=pagination)


@bp.route("/v1/revisions", methods=["GET"])
def list_all_revisions():
    require_roles(ALL_ROLES)
    items = list(store.revisions.values())
    submittal_id = request.args.get("submittal_id")
    if submittal_id:
        items = [r for r in items if r["submittal_id"] == submittal_id]
    reviewer_id = request.args.get("reviewer_id")
    if reviewer_id:
        items = [r for r in items if r.get("reviewer_id") == reviewer_id]
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_revision(r) for r in page], response_type="array", pagination=pagination)


@bp.route("/v1/revisions/<revisionId>", methods=["GET"])
def get_revision(revisionId):
    require_roles(ALL_ROLES)
    rev = get_revision_or_404(revisionId)
    return success(ser_revision(rev))


@bp.route("/v1/revisions/<revisionId>/route", methods=["POST"])
def route_revision(revisionId):
    require_roles([PROJECT_ENGINEER])
    rev = get_revision_or_404(revisionId)
    sub = store.submittals.get(rev["submittal_id"])
    if sub is None:
        raise submittal_not_found()
    project = store.projects.get(sub["project_id"])
    if project is None:
        raise project_not_found()
    section = store.spec_sections.get(sub["spec_section_id"])
    require_active(project)
    if rev["status"] != "SUBMITTED":
        raise revision_not_submitted()

    data = json_body()
    reviewer_id = opt_str(data, "reviewer_id", None)
    if reviewer_id is not None:
        reviewer = store.reviewers.get(reviewer_id)
        if reviewer is None or reviewer["project_id"] != project["id"]:
            raise reviewer_not_found()
        if reviewer["reviewer_status"] != "ACTIVE":
            raise no_eligible_reviewer("Reviewer is not ACTIVE")
        if section is not None and reviewer["discipline"] != section["required_discipline"]:
            raise discipline_mismatch()
        if reviewer["open_review_count"] >= reviewer["review_capacity"]:
            raise reviewer_at_capacity()
    else:
        required_discipline = section["required_discipline"] if section else "ARCH"
        reviewer = calc.select_reviewer(project["id"], required_discipline)
        if reviewer is None:
            raise no_eligible_reviewer()

    rev["reviewer_id"] = reviewer["id"]
    rev["routed_date"] = calc.clock_date()
    rev["review_due_date"] = calc.add_business_days(
        rev["routed_date"], section["review_days"] if section else 10, calc.holidays_set(project)
    )
    rev["status"] = "UNDER_REVIEW"
    reviewer["open_review_count"] += 1
    touch(reviewer)
    touch(rev)
    return success(ser_revision(rev))


@bp.route("/v1/revisions/<revisionId>/return", methods=["POST"])
def return_revision(revisionId):
    uid, role = require_roles([REVIEWER])
    rev = get_revision_or_404(revisionId)
    sub = store.submittals.get(rev["submittal_id"])
    if sub is None:
        raise submittal_not_found()
    project = store.projects.get(sub["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    if rev["status"] != "UNDER_REVIEW":
        raise revision_not_under_review()
    if uid != rev.get("reviewer_id"):
        raise reviewer_not_assigned()
    data = json_body()
    action_code = req_enum(data, "action_code", ACTION_CODES)
    comments = opt_str(data, "comments", "")
    rev["action_code"] = action_code
    rev["return_comments"] = comments
    rev["returned_date"] = calc.clock_date()
    rev["is_late_return"] = (
        rev["review_due_date"] is not None and rev["returned_date"] > rev["review_due_date"]
    )
    rev["status"] = "RETURNED"
    reviewer = store.reviewers.get(rev["reviewer_id"])
    if reviewer is not None:
        reviewer["open_review_count"] = max(0, reviewer["open_review_count"] - 1)
        touch(reviewer)
    sub["review_status"] = "APPROVED" if action_code in ("A", "B") else "RETURNED_NEEDS_RESUBMIT"
    touch(sub)
    touch(rev)
    return success(ser_revision(rev))
