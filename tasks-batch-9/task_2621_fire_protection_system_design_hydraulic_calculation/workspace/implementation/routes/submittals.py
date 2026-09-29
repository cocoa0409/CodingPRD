"""Permit packages, the review pass and the resubmittal cycle (PRD 3.8)."""
from flask import Blueprint

import cascades
import clock
import db
import guards
import helpers
import ledger
import response
import validate
from errors import ApiError
from middleware import ALL_ROLES, authenticate
from utils import _dec

bp = Blueprint("submittals", __name__)

SEVERITIES = ["MAJOR", "MINOR", "INFORMATIONAL"]
SUBMITTAL_TERMINAL = ("APPROVED", "SUPERSEDED")
RESUBMITTABLE_STATES = ("COMMENTS_ISSUED", "RESPONSE_COMPLETE")
BEGIN_REVIEW_STATES = ("SUBMITTED", "RESPONSE_COMPLETE")


def _resolve_included_fks(data):
    """Step 5 over included_calculation_ids, in the order the ids are listed."""
    raw = data.get("included_calculation_ids")
    if isinstance(raw, list):
        for member in raw:
            if isinstance(member, str) and member.strip():
                guards.must("calculation", member)


def _require_packaged_calculations(project, calculation_ids):
    """Step 25 then step 26: sealed calculations over coordinated sheets."""
    for calc_id in calculation_ids:
        calc = db.calculations.get(calc_id)
        if calc is None or calc["project_id"] != project["id"] or calc["state"] != "SEALED":
            raise ApiError(
                "ERR_CALCULATION_NOT_SEALED",
                "Every included calculation must be a SEALED calculation of this project.",
            )
    for drawing in cascades.drawings_over(list(calculation_ids)):
        if drawing["state"] not in ("COORDINATED", "ISSUED"):
            raise ApiError(
                "ERR_DRAWING_NOT_COORDINATED",
                "Every shop drawing over a packaged calculation must be COORDINATED or ISSUED.",
            )


def _stamp_package(project, included, cycle_number, supersedes_id):
    row = {
        "project_id": project["id"],
        "supersedes_submittal_id": supersedes_id,
        "reviewed_by_ahj_reviewer_id": None,
        "included_calculation_ids": list(included),
        "cycle_number": cycle_number,
        "review_fee_usd": ledger.review_fee_for_cycle(cycle_number),
        "open_comment_count": 0,
        "major_comment_count": 0,
        "submitted_at": clock.now_iso(),
        "state": "SUBMITTED",
    }
    db.stamp_create(row)
    db.submittals[row["id"]] = row
    project["submittal_cycle_count"] = cycle_number
    ledger.accrue_review_fee(project, row["review_fee_usd"])
    return row


@bp.post("/submittals")
def create_submittal():
    actor = authenticate(["DesignEngineer"])
    data = validate.body()
    project = guards.must_fk("project", validate.raw_fk(data, "project_id"))
    _resolve_included_fks(data)
    guards.require_lead_engineer(actor, project)
    validate.req_str(data, "project_id")
    included = validate.req_id_list(data, "included_calculation_ids")
    pinned = validate.req_int(data, "expected_project_version")

    if pinned != project["version"]:
        raise ApiError(
            "ERR_STALE_PROJECT_VERSION",
            "expected_project_version does not match the project's current version.",
        )
    guards.require_not_frozen(project)
    guards.require_not_gated(project)
    _require_packaged_calculations(project, included)

    row = _stamp_package(
        project, included, (project["submittal_cycle_count"] or 0) + 1, None
    )
    if project["status"] == "DESIGN":
        project["status"] = "PERMIT_REVIEW"
    ledger.recompute_posture(project)
    db.touch(project)
    return response.created(response.public(row))


@bp.get("/submittals/<submittal_id>")
def get_submittal(submittal_id):
    authenticate(ALL_ROLES)
    return response.ok(response.public(guards.must("submittal", submittal_id)))


@bp.get("/submittals")
def list_submittals():
    authenticate(ALL_ROLES)
    rows = helpers.apply_filters(
        list(db.submittals.values()),
        ["project_id", "supersedes_submittal_id", "reviewed_by_ahj_reviewer_id", "state"],
    )
    rows = helpers.apply_membership_filter(rows, "included_calculation_ids")
    return helpers.list_response(rows)


@bp.post("/submittals/<submittal_id>/begin-review")
def begin_review(submittal_id):
    actor = authenticate(["AhjReviewer"])
    submittal = guards.must("submittal", submittal_id)
    project = guards.project_of(submittal)
    guards.require_assigned_reviewer(actor, project)

    if submittal["state"] in SUBMITTAL_TERMINAL:
        guards.terminal("This package is in a terminal state and cannot be reviewed further.")
    guards.require_project_open(project)
    if submittal["state"] not in BEGIN_REVIEW_STATES:
        guards.invalid_transition(
            "Review opens only from SUBMITTED or RESPONSE_COMPLETE."
        )
    if _dec(project["review_fee_balance_usd"]) > 0:
        raise ApiError(
            "ERR_REVIEW_FEE_OUTSTANDING",
            "The project's review fee balance must be zero before review opens.",
        )

    submittal["reviewed_by_ahj_reviewer_id"] = actor.user_id
    submittal["state"] = "UNDER_REVIEW"
    db.touch(submittal)
    return response.ok(response.public(submittal))


@bp.post("/submittals/<submittal_id>/comments")
def raise_comment(submittal_id):
    actor = authenticate(["AhjReviewer"])
    submittal = guards.must("submittal", submittal_id)
    project = guards.project_of(submittal)
    data = validate.body()
    guards.must_fk("engineer", validate.raw_fk(data, "assigned_engineer_id"))
    guards.require_assigned_reviewer(actor, project)
    code_section = validate.req_str(data, "code_section")
    severity = validate.req_str(data, "severity", enum=SEVERITIES)
    description = validate.req_str(data, "description")
    assigned = validate.opt_str(data, "assigned_engineer_id")

    if submittal["state"] in SUBMITTAL_TERMINAL:
        guards.terminal("This package is in a terminal state and accepts no comments.")
    guards.require_project_open(project)
    if submittal["state"] != "UNDER_REVIEW":
        guards.invalid_transition("Comments are raised only against an UNDER_REVIEW package.")

    row = {
        "submittal_id": submittal["id"],
        "raised_by_ahj_reviewer_id": actor.user_id,
        "assigned_engineer_id": assigned,
        "code_section": code_section,
        "severity": severity,
        "description": description,
        "response_note": None,
        "close_note": None,
        "disposition": None,
        "state": "OPEN",
    }
    db.stamp_create(row)
    db.review_comments[row["id"]] = row

    ledger.recount_submittal_comments(submittal)
    db.touch(submittal)
    ledger.recount_project_major_comments(project)
    ledger.recompute_posture(project)
    db.touch(project)
    return response.created(response.public(row))


@bp.post("/submittals/<submittal_id>/complete-review")
def complete_review(submittal_id):
    actor = authenticate(["AhjReviewer"])
    submittal = guards.must("submittal", submittal_id)
    project = guards.project_of(submittal)
    guards.require_assigned_reviewer(actor, project)

    if submittal["state"] in SUBMITTAL_TERMINAL:
        guards.terminal("This package is in a terminal state and its review is closed.")
    guards.require_project_open(project)
    if submittal["state"] != "UNDER_REVIEW":
        guards.invalid_transition("A review pass closes only from UNDER_REVIEW.")

    before_project = db.snapshot(project)
    ledger.recount_submittal_comments(submittal)
    outstanding = [
        c
        for c in ledger.comments_of(submittal["id"])
        if c["state"] in ledger.OUTSTANDING_COMMENT_STATES
    ]
    if not outstanding:
        submittal["state"] = "APPROVED"
        if project["status"] == "PERMIT_REVIEW":
            project["status"] = "PERMITTED"
        cascades.cascade_package_approved(submittal, project)
    else:
        submittal["state"] = "COMMENTS_ISSUED"
        if any(c["severity"] == "MAJOR" for c in outstanding):
            cascades.cascade_major_comment(submittal, project)

    db.touch(submittal)
    ledger.recount_project_major_comments(project)
    ledger.recompute_posture(project)
    db.touch_if_changed(project, before_project)
    return response.ok(response.public(submittal))


@bp.post("/submittals/<submittal_id>/resubmit")
def resubmit(submittal_id):
    actor = authenticate(["DesignEngineer"])
    target = guards.must("submittal", submittal_id)
    project = guards.project_of(target)
    data = validate.body()
    _resolve_included_fks(data)
    guards.require_lead_engineer(actor, project)
    included = validate.req_id_list(data, "included_calculation_ids")
    pinned = validate.req_int(data, "expected_project_version")

    if pinned != project["version"]:
        raise ApiError(
            "ERR_STALE_PROJECT_VERSION",
            "expected_project_version does not match the project's current version.",
        )
    guards.require_not_frozen(project)
    if target["state"] in SUBMITTAL_TERMINAL:
        guards.terminal("This package is in a terminal state and cannot be resubmitted.")
    if target["state"] not in RESUBMITTABLE_STATES:
        guards.invalid_transition(
            "Resubmittal is admissible only from COMMENTS_ISSUED or RESPONSE_COMPLETE."
        )
    _require_packaged_calculations(project, included)
    if (target["cycle_number"] or 0) >= ledger.RESUBMITTAL_CYCLE_LIMIT:
        raise ApiError(
            "ERR_RESUBMITTAL_CYCLE_LIMIT",
            "The authority accepts no cycle beyond the fourth.",
        )

    target["state"] = "SUPERSEDED"
    db.touch(target)
    row = _stamp_package(project, included, target["cycle_number"] + 1, target["id"])
    ledger.recompute_posture(project)
    db.touch(project)
    return response.created(response.public(row))
