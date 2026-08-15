"""VisitEvent, VisitAssignment endpoints and the visit state machine."""
from flask import Blueprint, request

from db import DB, clock_now, fmt_iso, new_id
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import action_item_due_date, get_or_404
from util import (
    as_enum,
    as_str,
    body,
    paginate,
    pagination,
    parse_dt,
    required,
    stamp_new,
    touch,
)

bp = Blueprint("visits", __name__)

TEAM_ROLES = {"CHAIR", "MEMBER", "OBSERVER"}


def visit_view(v):
    return {k: v for k, v in v.items() if not k.startswith("_")}


def assignment_view(a):
    return {k: v for k, v in a.items() if not k.startswith("_")}


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open interval overlap: [a_start, a_end) vs [b_start, b_end)."""
    return a_start < b_end and b_start < a_end


@bp.post("/accreditation/terms/<id>/visits")
def create_visit(id):
    auth(["AccreditationOfficer"])
    term = get_or_404("terms", id, "AccreditationTerm")
    data = body()
    campus_id = data.get("campus_id")
    lead_reviewer_id = required(data, "lead_reviewer_id")
    starts_on_raw = required(data, "starts_on")
    ends_on_raw = required(data, "ends_on")
    starts_dt = parse_dt(starts_on_raw, "starts_on")
    ends_dt = parse_dt(ends_on_raw, "ends_on")
    if ends_dt <= starts_dt:
        raise ApiError(
            "ERR_VALIDATION", 400, "ends_on must be strictly after starts_on"
        )
    if campus_id is not None:
        campus = DB["campuses"].get(campus_id)
        if campus is None or campus["system_id"] != term["system_id"]:
            raise ApiError(
                "ERR_REFERENTIAL_INTEGRITY",
                422,
                "campus_id does not belong to the term's system",
            )
    lead = DB["reviewers"].get(lead_reviewer_id)
    if lead is None:
        raise ApiError(
            "ERR_REFERENTIAL_INTEGRITY", 422, "lead_reviewer_id does not exist"
        )
    record = {
        "id": new_id(),
        "term_id": id,
        "campus_id": campus_id,
        "lead_reviewer_id": lead_reviewer_id,
        "starts_on": fmt_iso(starts_dt),
        "ends_on": fmt_iso(ends_dt),
        "status": "REQUESTED",
        "_starts_on_dt": starts_dt,
        "_ends_on_dt": ends_dt,
    }
    stamp_new(record, with_version=True)
    DB["visits"][record["id"]] = record
    return ok(visit_view(record), status=201)


@bp.get("/accreditation/terms/<id>/visits")
def list_term_visits(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader", "Reviewer"])
    get_or_404("terms", id, "AccreditationTerm")
    limit, offset = pagination()
    rows = [v for v in DB["visits"].values() if v["term_id"] == id]
    rows.sort(key=lambda v: v["created_at"])
    campus_id = request.args.get("campus_id")
    status = request.args.get("status")
    if campus_id:
        rows = [r for r in rows if r["campus_id"] == campus_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([visit_view(r) for r in page], total, limit, offset)


@bp.get("/accreditation/visits/<id>")
def get_visit(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader", "Reviewer"])
    row = get_or_404("visits", id, "VisitEvent")
    return ok(visit_view(row))


@bp.post("/accreditation/visits/<id>/assignments")
def create_assignment(id):
    auth(["AccreditationOfficer"])
    visit = get_or_404("visits", id, "VisitEvent")
    data = body()
    reviewer_id = required(data, "reviewer_id")
    role_on_team = as_enum(required(data, "role_on_team"), "role_on_team", TEAM_ROLES)
    reviewer = DB["reviewers"].get(reviewer_id)
    if reviewer is None or reviewer["reviewer_status"] != "AVAILABLE":
        raise ApiError(
            "ERR_REFERENTIAL_INTEGRITY",
            422,
            "reviewer must exist and be AVAILABLE",
        )
    # Conflict-of-interest segregation: reviewer conflicted for the visit's system.
    term = DB["terms"].get(visit["term_id"])
    system_id = term["system_id"] if term else None
    if system_id is not None and system_id in reviewer.get("conflict_system_ids", []):
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            422,
            "Reviewer is conflicted for the visit's owning system",
        )
    record = {
        "id": new_id(),
        "visit_id": id,
        "reviewer_id": reviewer_id,
        "role_on_team": role_on_team,
    }
    stamp_new(record, with_version=True)
    DB["assignments"][record["id"]] = record
    return ok(assignment_view(record), status=201)


@bp.get("/accreditation/visits/<id>/assignments")
def list_assignments(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "Reviewer"])
    get_or_404("visits", id, "VisitEvent")
    limit, offset = pagination()
    rows = [a for a in DB["assignments"].values() if a["visit_id"] == id]
    rows.sort(key=lambda a: a["created_at"])
    page, total = paginate(rows, limit, offset)
    return ok_list([assignment_view(r) for r in page], total, limit, offset)


@bp.post("/accreditation/visits/<id>/confirm")
def confirm_visit(id):
    auth(["AccreditationOfficer"])
    visit = get_or_404("visits", id, "VisitEvent")
    if visit["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Visit is not REQUESTED")
    term = DB["terms"].get(visit["term_id"])
    if term is None or term["status"] != "REVIEW":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Owning term must be in REVIEW"
        )
    assignments = [a for a in DB["assignments"].values() if a["visit_id"] == id]
    if not any(a["role_on_team"] == "CHAIR" for a in assignments):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "At least one CHAIR assignment is required",
        )
    # Temporal-window rules precede referential integrity (PRD §2.5 priority):
    # both overlap checks run before the lead-availability check.
    # Same-campus overlap check.
    for other in DB["visits"].values():
        if other["id"] == visit["id"]:
            continue
        if other["status"] not in ("CONFIRMED", "IN_FIELD"):
            continue
        if other["campus_id"] != visit["campus_id"]:
            continue
        if _overlaps(
            visit["_starts_on_dt"], visit["_ends_on_dt"],
            other["_starts_on_dt"], other["_ends_on_dt"],
        ):
            raise ApiError(
                "ERR_TEMPORAL_WINDOW_VIOLATION",
                422,
                "Another visit for the same campus overlaps in time",
            )
    # Per-reviewer overlap check.
    assigned_ids = {a["reviewer_id"] for a in assignments}
    for other in DB["visits"].values():
        if other["id"] == visit["id"]:
            continue
        if other["status"] not in ("CONFIRMED", "IN_FIELD"):
            continue
        if not _overlaps(
            visit["_starts_on_dt"], visit["_ends_on_dt"],
            other["_starts_on_dt"], other["_ends_on_dt"],
        ):
            continue
        other_assigned = {
            a["reviewer_id"]
            for a in DB["assignments"].values()
            if a["visit_id"] == other["id"]
        }
        if assigned_ids & other_assigned:
            raise ApiError(
                "ERR_TEMPORAL_WINDOW_VIOLATION",
                422,
                "An assigned reviewer is committed to an overlapping visit",
            )
    lead = DB["reviewers"].get(visit["lead_reviewer_id"])
    if lead is None or lead["reviewer_status"] != "AVAILABLE":
        raise ApiError(
            "ERR_REFERENTIAL_INTEGRITY",
            422,
            "Lead reviewer must be AVAILABLE",
        )
    # Transition + reviewer cascade.
    visit["status"] = "CONFIRMED"
    touch(visit)
    for a in assignments:
        reviewer = DB["reviewers"].get(a["reviewer_id"])
        if reviewer is not None and reviewer["reviewer_status"] == "AVAILABLE":
            reviewer["reviewer_status"] = "ON_ASSIGNMENT"
            touch(reviewer)
    return ok(visit_view(visit))


@bp.post("/accreditation/visits/<id>/cancel")
def cancel_visit(id):
    auth(["AccreditationOfficer"])
    visit = get_or_404("visits", id, "VisitEvent")
    if visit["status"] == "REQUESTED":
        visit["status"] = "CANCELLED"
        touch(visit)
        return ok(visit_view(visit))
    if visit["status"] == "CONFIRMED":
        if clock_now() >= visit["_starts_on_dt"]:
            raise ApiError(
                "ERR_TEMPORAL_WINDOW_VIOLATION",
                422,
                "Confirmed visit can only be cancelled before starts_on",
            )
        visit["status"] = "CANCELLED"
        touch(visit)
        for a in DB["assignments"].values():
            if a["visit_id"] != id:
                continue
            reviewer = DB["reviewers"].get(a["reviewer_id"])
            if reviewer is not None and reviewer["reviewer_status"] == "ON_ASSIGNMENT":
                reviewer["reviewer_status"] = "AVAILABLE"
                touch(reviewer)
        return ok(visit_view(visit))
    raise ApiError(
        "ERR_INVALID_STATE",
        409,
        "Only REQUESTED or CONFIRMED visits may be cancelled",
    )


@bp.post("/accreditation/visits/<id>/issue-report")
def issue_report(id):
    user_id, _ = auth(["Reviewer"])
    visit = get_or_404("visits", id, "VisitEvent")
    if visit["status"] != "REPORT_DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Visit is not REPORT_DRAFT")
    if visit["lead_reviewer_id"] != user_id:
        raise ApiError(
            "ERR_FORBIDDEN", 403, "Only the lead reviewer may issue the report"
        )
    findings = [f for f in DB["findings"].values() if f["visit_id"] == id]
    if not findings:
        raise ApiError(
            "ERR_INVALID_STATE", 409, "At least one finding is required"
        )
    if any(f["status"] != "ISSUED" for f in findings):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Every finding must be ISSUED"
        )
    # Cascade: create RequiredActionItem for each REQUIRED_ACTION finding.
    for f in findings:
        if f["severity"] != "REQUIRED_ACTION":
            continue
        follow_up = f["follow_up_months"]
        due_dt = action_item_due_date(visit, follow_up)
        item = {
            "id": new_id(),
            "finding_id": f["id"],
            "description": f["narrative"],
            "due_date": fmt_iso(due_dt),
            "follow_up_months": follow_up,
            "status": "OPEN",
            "verified_by_user_id": None,
            "_due_date_dt": due_dt,
            # Tracks whether an evidence submission is pending while OVERDUE
            "_pending_overdue_submission": False,
        }
        stamp_new(item, with_version=True)
        DB["action_items"][item["id"]] = item
    # Free reviewers.
    for a in DB["assignments"].values():
        if a["visit_id"] != id:
            continue
        reviewer = DB["reviewers"].get(a["reviewer_id"])
        if reviewer is not None and reviewer["reviewer_status"] == "ON_ASSIGNMENT":
            reviewer["reviewer_status"] = "AVAILABLE"
            touch(reviewer)
    visit["status"] = "REPORT_ISSUED"
    touch(visit)
    return ok(visit_view(visit))
