"""Drafting requests and statutory conflicts (PRD S3.2 - S3.4)."""

from flask import Blueprint

from auth import endpoint, require_senior
import calc
from counters import recompute_drafter, recompute_member, recompute_request_conflicts
from envelope import object_response
from errors import fail
from lookups import (
    get_conflict,
    get_drafter,
    get_request,
    get_session,
    require_active_session,
)
import serializers as S
from store import create_row, db, fmt_iso, parse_iso, touch
from validation import (
    body,
    peek_body,
    req_dt,
    req_enum,
    req_id,
    req_int,
    req_str,
    require_interval,
)

bp = Blueprint("drafting", __name__)

CONFIDENTIALITY = ("CONFIDENTIAL", "PUBLIC")
CONFLICT_TYPES = (
    "AMENDS_SAME_SECTION",
    "REPEALS_ACTIVE",
    "DUPLICATE_ENACTMENT",
    "STYLE_VIOLATION",
)
SEVERITIES = ("BLOCKING", "ADVISORY")
WITHDRAWABLE = (
    "SUBMITTED",
    "RESEARCH",
    "DRAFTING",
    "RETURNED_FOR_CLARIFICATION",
    "DRAFT_READY",
)


def _session_of(request_row):
    return db.sessions.get(request_row["session_id"])


def _recompute_sla(request_row, session_row, from_instant):
    request_row["actual_complexity_score"] = calc.post_research_actual(request_row)
    request_row["sla_due_utc"] = fmt_iso(
        calc.drafting_sla_due_utc(request_row, session_row, from_instant)
    )


# ---------------------------------------------------------------------------
# intake
# ---------------------------------------------------------------------------


@bp.post("/drafting-requests")
@endpoint(("Member",))
def create_drafting_request(user_id, role):
    payload = body()
    session_id = req_id(payload, "session_id")
    subject = req_str(payload, "subject")
    summary = req_str(payload, "summary")
    sections = req_int(payload, "requested_sections_count", minimum=1)
    chapter = req_str(payload, "target_code_chapter")
    confidentiality = req_enum(
        payload, "confidentiality", CONFIDENTIALITY, required=False, default="PUBLIC"
    )
    priority_flag = payload.get("priority_flag")
    if priority_flag is None:
        priority_flag = False
    elif not isinstance(priority_flag, bool):
        fail("ERR_INVALID_REQUEST", "Field 'priority_flag' must be a boolean.")
    appropriation = req_int(
        payload, "appropriation_requested_cents", required=False, default=0, minimum=0
    )

    session = get_session(session_id)
    member = db.members.get(user_id)
    if member is None:
        fail("ERR_MEMBER_NOT_FOUND")
    require_active_session(session)
    if member["intake_hold"]:
        fail("ERR_MEMBER_INTAKE_HOLD")
    if priority_flag and member["priority_slots_used"] >= member["priority_slots_total"]:
        fail("ERR_PRIORITY_SLOTS_EXHAUSTED")

    row = create_row(
        "drafting_requests",
        {
            "session_id": session["id"],
            "member_id": member["id"],
            "subject": subject,
            "summary": summary,
            "confidentiality": confidentiality,
            "priority_flag": priority_flag,
            "requested_sections_count": sections,
            "target_code_chapter": chapter,
            "appropriation_requested_cents": appropriation,
            "status": "SUBMITTED",
            "assigned_drafter_id": None,
            "engagement_start_utc": None,
            "engagement_end_utc": None,
            "affected_sections_count": None,
            "research_completed_utc": None,
            "intake_complexity_estimate": None,
            "actual_complexity_score": None,
            "sla_due_utc": None,
            "revision_round": 0,
            "blocking_conflict_count": 0,
            "open_blocking_conflict_count": 0,
            "advisory_conflict_count": 0,
            "style_findings_count": None,
        },
    )
    row["intake_complexity_estimate"] = calc.intake_complexity_estimate(row)
    recompute_member(member["id"])
    return object_response(S.drafting_request_out(row), 201)


# ---------------------------------------------------------------------------
# assignment and research
# ---------------------------------------------------------------------------


@bp.post("/drafting-requests/<rid>/assign")
@endpoint(("ReviewCounsel",))
def assign_drafter(user_id, role, rid):
    require_senior(user_id)
    request_row = get_request(rid)
    payload = body()
    drafter_id = req_id(payload, "drafter_id")
    start = req_dt(payload, "engagement_start_utc")
    end = req_dt(payload, "engagement_end_utc")
    require_interval(start, end, "engagement window")

    drafter = get_drafter(drafter_id)
    require_active_session(_session_of(request_row))
    if request_row["status"] != "SUBMITTED":
        fail("ERR_INVALID_DRAFTING_REQUEST_STATE")
    if not calc.drafter_admits(drafter, start, end):
        fail("ERR_DRAFTER_ENGAGEMENT_CAPACITY_EXCEEDED")

    request_row["status"] = "RESEARCH"
    request_row["assigned_drafter_id"] = drafter["id"]
    request_row["engagement_start_utc"] = fmt_iso(start)
    request_row["engagement_end_utc"] = fmt_iso(end)
    touch(request_row)
    recompute_drafter(drafter["id"])
    return object_response(S.drafting_request_out(request_row))


@bp.post("/drafting-requests/<rid>/complete-research")
@endpoint(("Drafter",))
def complete_research(user_id, role, rid):
    request_row = get_request(rid)
    if request_row["assigned_drafter_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER")
    payload = body()
    affected = req_int(payload, "affected_sections_count", minimum=0)
    session = _session_of(request_row)
    require_active_session(session)
    if request_row["status"] != "RESEARCH":
        fail("ERR_INVALID_DRAFTING_REQUEST_STATE")

    request_row["status"] = "DRAFTING"
    request_row["affected_sections_count"] = affected
    request_row["research_completed_utc"] = db.now_iso()
    _recompute_sla(request_row, session, db.now())
    touch(request_row)
    return object_response(S.drafting_request_out(request_row))


@bp.post("/drafting-requests/<rid>/clarify")
@endpoint(("Member",))
def clarify_request(user_id, role, rid):
    request_row = get_request(rid)
    payload = body()
    req_str(payload, "clarification_note")
    session = _session_of(request_row)
    require_active_session(session)
    if request_row["status"] != "RETURNED_FOR_CLARIFICATION":
        fail("ERR_INVALID_DRAFTING_REQUEST_STATE")
    # The sponsor-identity requirement is part of this transition's own
    # preconditions (PRD S2.1 / S3.4).
    if request_row["member_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER")
    if request_row["open_blocking_conflict_count"] > 0:
        fail("ERR_BLOCKING_CONFLICT_UNRESOLVED")
    drafter = db.drafters.get(request_row["assigned_drafter_id"])
    start = parse_iso(request_row["engagement_start_utc"])
    end = parse_iso(request_row["engagement_end_utc"])
    if drafter is not None and start is not None and end is not None:
        if not calc.drafter_admits(drafter, start, end):
            fail("ERR_DRAFTER_ENGAGEMENT_CAPACITY_EXCEEDED")

    request_row["status"] = "DRAFTING"
    request_row["revision_round"] = request_row["revision_round"] + 1
    _recompute_sla(request_row, session, db.now())
    touch(request_row)
    if drafter is not None:
        recompute_drafter(drafter["id"])
    recompute_member(request_row["member_id"])
    return object_response(S.drafting_request_out(request_row))


@bp.post("/drafting-requests/<rid>/certify-draft")
@endpoint(("ReviewCounsel",))
def certify_draft(user_id, role, rid):
    require_senior(user_id)
    request_row = get_request(rid)
    payload = body()
    findings = req_int(payload, "style_findings_count", minimum=0)
    require_active_session(_session_of(request_row))
    if request_row["status"] != "DRAFTING":
        fail("ERR_INVALID_DRAFTING_REQUEST_STATE")
    if request_row["assigned_drafter_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")
    if request_row["open_blocking_conflict_count"] > 0:
        fail("ERR_BLOCKING_CONFLICT_UNRESOLVED")
    if findings > 0:
        # Uniquely in this specification the reported count is still recorded
        # even though the transition is refused (PRD S3.4).
        request_row["style_findings_count"] = findings
        touch(request_row)
        fail("ERR_STYLE_NONCOMPLIANT")

    request_row["style_findings_count"] = findings
    request_row["status"] = "DRAFT_READY"
    request_row["sla_due_utc"] = None
    touch(request_row)
    if request_row["assigned_drafter_id"]:
        recompute_drafter(request_row["assigned_drafter_id"])
    return object_response(S.drafting_request_out(request_row))


@bp.post("/drafting-requests/<rid>/withdraw")
@endpoint(("Member",))
def withdraw_request(user_id, role, rid):
    request_row = get_request(rid)
    if request_row["member_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER")
    payload = body()
    req_str(payload, "withdrawal_reason", required=False)
    require_active_session(_session_of(request_row))
    if request_row["status"] not in WITHDRAWABLE:
        fail("ERR_INVALID_DRAFTING_REQUEST_STATE")

    drafter_id = request_row["assigned_drafter_id"]
    request_row["status"] = "WITHDRAWN"
    request_row["sla_due_utc"] = None
    touch(request_row)
    recompute_member(request_row["member_id"])
    if drafter_id:
        recompute_drafter(drafter_id)
    return object_response(S.drafting_request_out(request_row))


# ---------------------------------------------------------------------------
# statutory conflicts
# ---------------------------------------------------------------------------


@bp.post("/statutory-conflicts")
@endpoint(("Drafter",))
def create_conflict(user_id, role):
    payload = body()
    request_id = req_id(payload, "drafting_request_id")
    citation = req_str(payload, "code_citation")
    conflict_type = req_enum(payload, "conflict_type", CONFLICT_TYPES)
    severity = req_enum(payload, "severity", SEVERITIES)

    request_row = get_request(request_id)
    if request_row["assigned_drafter_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER")
    require_active_session(_session_of(request_row))
    if request_row["status"] not in ("RESEARCH", "DRAFTING"):
        fail("ERR_INVALID_CONFLICT_STATE")

    was_drafting = request_row["status"] == "DRAFTING"
    row = create_row(
        "statutory_conflicts",
        {
            "drafting_request_id": request_row["id"],
            "code_citation": citation,
            "conflict_type": conflict_type,
            "severity": severity,
            "resolution_status": "OPEN",
            "resolution_note": None,
            "resolved_utc": None,
        },
    )
    recompute_request_conflicts(request_row["id"])
    if severity == "BLOCKING" and was_drafting:
        # The three-level bounce-back cascade (PRD S3.4).
        request_row["status"] = "RETURNED_FOR_CLARIFICATION"
        request_row["sla_due_utc"] = None
        touch(request_row)
        if request_row["assigned_drafter_id"]:
            recompute_drafter(request_row["assigned_drafter_id"])
        recompute_member(request_row["member_id"])
    return object_response(S.statutory_conflict_out(row), 201)


@bp.post("/statutory-conflicts/<cid>/resolve")
@endpoint(("Drafter", "ReviewCounsel"))
def resolve_conflict(user_id, role, cid):
    # Rung 3: WAIVED is a ReviewCounsel-only disposition backed by a senior row,
    # so the disposition is peeked at before the path is resolved.
    if peek_body().get("resolution_status") == "WAIVED":
        if role != "ReviewCounsel":
            fail("ERR_SENIOR_COUNSEL_REQUIRED")
        require_senior(user_id)
    conflict = get_conflict(cid)
    payload = body()
    resolution_status = req_enum(payload, "resolution_status", ("RESOLVED", "WAIVED"))
    note = req_str(payload, "resolution_note")
    request_row = db.drafting_requests.get(conflict["drafting_request_id"])
    require_active_session(
        db.sessions.get(request_row["session_id"]) if request_row else None
    )
    if conflict["resolution_status"] != "OPEN":
        fail("ERR_INVALID_CONFLICT_STATE")
    if resolution_status == "RESOLVED" and role == "Drafter":
        if request_row is None or request_row["assigned_drafter_id"] != user_id:
            fail("ERR_NOT_RESOURCE_OWNER")

    conflict["resolution_status"] = resolution_status
    conflict["resolution_note"] = note
    conflict["resolved_utc"] = db.now_iso()
    touch(conflict)
    if request_row is not None:
        recompute_request_conflicts(request_row["id"])
    return object_response(S.statutory_conflict_out(conflict))
