"""Community participation: quality issues, dataset requests and voting."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import services
from common import bad_state, dept_scope, find, member_scope
from core import (
    body,
    caller,
    db,
    err,
    new_row,
    now,
    ok,
    opt_enum,
    opt_str,
    page,
    req_enum,
    req_str,
    touch,
)

bp = Blueprint("community", __name__)

ISSUE_STATUSES = ("SUBMITTED", "TRIAGED", "ACCEPTED", "REJECTED", "CORRECTED", "CLOSED")
REQUEST_STATUSES = ("OPEN", "UNDER_REVIEW", "ACCEPTED", "DECLINED", "FULFILLED")
DEMAND_SIGNAL_FILTER = "demand_signal"


def enum_filter(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        err("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def blocking_privacy_issue(dataset_id, exclude_issue_id=None):
    for issue in db.issues.values():
        if issue["dataset_id"] != dataset_id:
            continue
        if exclude_issue_id is not None and issue["id"] == exclude_issue_id:
            continue
        if (
            issue["status"] == "ACCEPTED"
            and issue["severity"] == "CRITICAL"
            and issue["category"] == "PRIVACY"
        ):
            return True
    return False


# --------------------------------------------------------------------------
# Quality issues
# --------------------------------------------------------------------------
@bp.post("/quality-issues")
def create_issue():
    role, user_id = caller("CommunityMember")
    data = body()
    dataset_id = req_str(data, "dataset_id")
    reporter_member_id = req_str(data, "reporter_member_id")
    severity = req_enum(data, "severity", calc.SEVERITIES)
    category = req_enum(data, "category", calc.ISSUE_CATEGORIES)
    description = req_str(data, "description")
    find("datasets", dataset_id)
    member = find("members", reporter_member_id)
    member_scope(user_id, reporter_member_id)
    if member["status"] == "THROTTLED":
        err("ERR_MEMBER_THROTTLED", "A THROTTLED member may not file quality issues.")
    row = new_row()
    row.update(
        {
            "dataset_id": dataset_id,
            "reporter_member_id": reporter_member_id,
            "resolution_version_id": None,
            "severity": severity,
            "category": category,
            "description": description,
            "triage_due_at": row["created_at"]
            + timedelta(hours=calc.TRIAGE_SLA_HOURS[severity]),
            "triaged_at": None,
            "accepted_at": None,
            "correction_due_at": None,
            "triage_breached": False,
            "correction_breached": False,
            "reject_reason": None,
            "status": "SUBMITTED",
        }
    )
    db.issues[row["id"]] = row
    return ok(services.issue_out(row), 201)


@bp.get("/quality-issues")
def list_issues():
    caller()
    dataset_id = request.args.get("dataset_id")
    reporter_member_id = request.args.get("reporter_member_id")
    resolution_version_id = request.args.get("resolution_version_id")
    status = enum_filter("status", ISSUE_STATUSES)
    severity = enum_filter("severity", calc.SEVERITIES)
    rows = list(db.issues.values())
    if dataset_id is not None:
        rows = [r for r in rows if r["dataset_id"] == dataset_id]
    if reporter_member_id is not None:
        rows = [r for r in rows if r["reporter_member_id"] == reporter_member_id]
    if resolution_version_id is not None:
        rows = [r for r in rows if r["resolution_version_id"] == resolution_version_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    return page(rows, services.issue_out)


@bp.get("/quality-issues/<issue_id>")
def get_issue(issue_id):
    caller()
    return ok(services.issue_out(find("issues", issue_id)))


@bp.post("/quality-issues/<issue_id>/triage")
def triage_issue(issue_id):
    role, user_id = caller("DataCoordinator")
    issue = find("issues", issue_id)
    dataset = db.datasets.get(issue["dataset_id"])
    dept_scope(user_id, dataset["department_id"] if dataset else None)
    if issue["status"] != "SUBMITTED":
        bad_state("Only a SUBMITTED quality issue may be triaged.")
    if dataset is None or dataset["publication_status"] not in calc.PUBLISHED_STATES:
        err(
            "ERR_DATASET_NOT_PUBLISHED",
            "Triage requires the dataset to be PUBLISHED or UNDER_REMEDIATION.",
        )
    issue["status"] = "TRIAGED"
    issue["triaged_at"] = now()
    if now() > issue["triage_due_at"]:
        issue["triage_breached"] = True
    touch(issue)
    return ok(services.issue_out(issue))


@bp.post("/quality-issues/<issue_id>/decide")
def decide_issue(issue_id):
    role, user_id = caller("DataCoordinator")
    issue = find("issues", issue_id)
    data = body()
    decision = req_enum(data, "decision", ("ACCEPT", "REJECT"))
    reject_reason = opt_enum(data, "reject_reason", calc.REJECT_REASONS)
    if decision == "REJECT" and reject_reason is None:
        err("ERR_INVALID_REQUEST", "reject_reason is required when rejecting an issue.")
    dataset = db.datasets.get(issue["dataset_id"])
    department = services.dept_of_dataset(dataset) if dataset else None
    dept_scope(user_id, dataset["department_id"] if dataset else None)
    if issue["status"] != "TRIAGED":
        bad_state("Only a TRIAGED quality issue may be decided.")
    member = db.members.get(issue["reporter_member_id"])
    if decision == "REJECT":
        issue["status"] = "REJECTED"
        issue["reject_reason"] = reject_reason
        touch(issue)
        if member is not None:
            member["last_credited_at"] = now()
            services.recompute_member(member)
        return ok(services.issue_out(issue))

    if department is not None and department["compliance_posture"] == "SUSPENDED":
        err("ERR_DEPARTMENT_SUSPENDED", "The owning department's posture is SUSPENDED.")
    issue["status"] = "ACCEPTED"
    issue["accepted_at"] = now()
    issue["correction_due_at"] = now() + timedelta(
        days=calc.CORRECTION_SLA_DAYS[issue["severity"]]
    )
    touch(issue)
    if member is not None:
        member["last_credited_at"] = now()
        services.recompute_member(member)
    if (
        dataset is not None
        and issue["severity"] == "CRITICAL"
        and issue["category"] == "PRIVACY"
        and dataset["publication_status"] == "PUBLISHED"
    ):
        dataset["publication_status"] = "UNDER_REMEDIATION"
        dataset["public_access_suspended"] = True
        dataset["remediation_opened_at"] = now()
        touch(dataset)
        for pipeline in services.pipelines_of_dataset(dataset["id"]):
            if pipeline["status"] == "ARMED":
                services.suspend_pipeline(pipeline, "REMEDIATION_HOLD")
    services.recompute_department(department)
    return ok(services.issue_out(issue))


@bp.post("/quality-issues/<issue_id>/link-correction")
def link_correction(issue_id):
    role, user_id = caller("DataCoordinator")
    issue = find("issues", issue_id)
    data = body()
    dataset_version_id = req_str(data, "dataset_version_id")
    version = find("versions", dataset_version_id)
    dataset = db.datasets.get(issue["dataset_id"])
    dept_scope(user_id, dataset["department_id"] if dataset else None)
    if issue["status"] != "ACCEPTED":
        bad_state("Only an ACCEPTED quality issue may receive a correction.")
    if version["dataset_id"] != issue["dataset_id"] or version["change_type"] != "CORRECTION":
        bad_state("The version must belong to the same dataset and be a CORRECTION.")
    if version["status"] != "LIVE":
        err("ERR_VERSION_NOT_LIVE", "The correction version must be LIVE.")
    issue["resolution_version_id"] = version["id"]
    issue["status"] = "CORRECTED"
    issue["correction_breached"] = False
    touch(issue)
    version["correction_issue_id"] = issue["id"]
    touch(version)
    if (
        dataset is not None
        and dataset["publication_status"] == "UNDER_REMEDIATION"
        and not blocking_privacy_issue(dataset["id"], issue["id"])
    ):
        dataset["publication_status"] = "PUBLISHED"
        dataset["public_access_suspended"] = False
        dataset["remediation_opened_at"] = None
        touch(dataset)
        services.recompute_currency(dataset)
    services.recompute_department_of(dataset)
    return ok(services.issue_out(issue))


@bp.post("/quality-issues/<issue_id>/close")
def close_issue(issue_id):
    caller("DataCoordinator", "PortalAdmin")
    issue = find("issues", issue_id)
    if issue["status"] != "CORRECTED" or issue["resolution_version_id"] is None:
        bad_state("Only a CORRECTED issue carrying a resolution version may be closed.")
    issue["status"] = "CLOSED"
    touch(issue)
    return ok(services.issue_out(issue))


# --------------------------------------------------------------------------
# Dataset requests
# --------------------------------------------------------------------------
@bp.post("/dataset-requests")
def create_request():
    role, user_id = caller("CommunityMember")
    data = body()
    requester_member_id = req_str(data, "requester_member_id")
    title = req_str(data, "title")
    rationale = req_str(data, "rationale")
    find("members", requester_member_id)
    member_scope(user_id, requester_member_id)
    row = new_row()
    row.update(
        {
            "requester_member_id": requester_member_id,
            "linked_dataset_id": None,
            "title": title,
            "rationale": rationale,
            "votes": [],
            "weighted_vote_total": 0,
            "demand_signal": calc.ZERO,
            "decision_note": None,
            "status": "OPEN",
        }
    )
    db.requests[row["id"]] = row
    return ok(services.request_out(row), 201)


@bp.get("/dataset-requests")
def list_requests():
    caller()
    requester_member_id = request.args.get("requester_member_id")
    linked_dataset_id = request.args.get("linked_dataset_id")
    status = enum_filter("status", REQUEST_STATUSES)
    rows = list(db.requests.values())
    if requester_member_id is not None:
        rows = [r for r in rows if r["requester_member_id"] == requester_member_id]
    if linked_dataset_id is not None:
        rows = [r for r in rows if r["linked_dataset_id"] == linked_dataset_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page(rows, services.request_out)


@bp.get("/dataset-requests/<request_id>")
def get_request(request_id):
    caller()
    return ok(services.request_out(find("requests", request_id)))


@bp.post("/dataset-requests/<request_id>/votes")
def cast_vote(request_id):
    role, user_id = caller("CommunityMember")
    row = find("requests", request_id)
    data = body()
    member_id = req_str(data, "member_id")
    member = find("members", member_id)
    member_scope(user_id, member_id)
    for vote in row["votes"]:
        if vote["member_id"] == member_id:
            err("ERR_DUPLICATE_VOTE", "The member has already voted on this request.")
    if member["status"] == "THROTTLED":
        err("ERR_MEMBER_THROTTLED", "A THROTTLED member may not vote.")
    services.recompute_member(member)
    row["votes"].append(
        {"member_id": member_id, "weight": member["vote_weight"], "cast_at": now()}
    )
    services.recompute_request(row)
    if row["linked_dataset_id"] is not None:
        dataset = db.datasets.get(row["linked_dataset_id"])
        if dataset is not None:
            services.recompute_priority(dataset, dataset["priority_score_variant"])
    return ok(services.request_out(row))


@bp.post("/dataset-requests/<request_id>/review")
def review_request(request_id):
    caller("PortalAdmin")
    row = find("requests", request_id)
    data = body()
    decision_note = opt_str(data, "decision_note")
    if row["status"] != "OPEN":
        bad_state("Only an OPEN request may be taken under review.")
    if row["weighted_vote_total"] < calc.REVIEW_VOTE_MIN:
        err(
            "ERR_INSUFFICIENT_DEMAND",
            "weighted_vote_total must reach %d before review." % calc.REVIEW_VOTE_MIN,
        )
    row["status"] = "UNDER_REVIEW"
    if decision_note is not None:
        row["decision_note"] = decision_note
    touch(row)
    return ok(services.request_out(row))


@bp.post("/dataset-requests/<request_id>/decide")
def decide_request(request_id):
    caller("PortalAdmin")
    row = find("requests", request_id)
    data = body()
    decision = req_enum(data, "decision", ("ACCEPT", "DECLINE", "DEFER"))
    decision_note = req_str(data, "decision_note")
    if row["status"] != "UNDER_REVIEW":
        bad_state("Only an UNDER_REVIEW request may be decided.")
    if decision == "ACCEPT":
        row["status"] = "ACCEPTED"
    elif decision == "DECLINE":
        row["status"] = "DECLINED"
    else:
        row["status"] = "OPEN"
    row["decision_note"] = decision_note
    touch(row)
    return ok(services.request_out(row))


@bp.post("/dataset-requests/<request_id>/fulfill")
def fulfill_request(request_id):
    caller("PortalAdmin")
    row = find("requests", request_id)
    data = body()
    dataset_id = req_str(data, "dataset_id")
    dataset = find("datasets", dataset_id)
    if row["status"] != "ACCEPTED":
        bad_state("Only an ACCEPTED request may be fulfilled.")
    if dataset["publication_status"] not in ("SCREENING", "READY", "PUBLISHED"):
        bad_state("The fulfilling dataset must be SCREENING, READY or PUBLISHED.")
    row["status"] = "FULFILLED"
    row["linked_dataset_id"] = dataset_id
    touch(row)
    services.recompute_priority(dataset, dataset["priority_score_variant"])
    return ok(services.request_out(row))
