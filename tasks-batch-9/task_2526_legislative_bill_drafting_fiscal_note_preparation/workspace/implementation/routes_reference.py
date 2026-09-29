"""The clock, sessions, committees, members, drafters and agencies (PRD S3.1)."""

from flask import Blueprint

from auth import endpoint
from counters import (
    recompute_agency,
    recompute_committee,
    recompute_drafter,
    recompute_enrollment_counts,
    recompute_member,
    recompute_session_bill_counts,
)
from envelope import empty_response, object_response
from errors import fail
from lookups import get_session
import serializers as S
from store import all_rows, create_row, db, fmt_iso, touch
from validation import (
    body,
    req_bool,
    req_dt,
    req_enum,
    req_int,
    req_int_array_ascending,
    req_str,
)

bp = Blueprint("reference", __name__)

CHAMBERS = ("HOUSE", "SENATE")


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------


@bp.post("/_clock/set_current_utc")
@endpoint(("PlatformAdmin",))
def set_clock(user_id, role):
    payload = body()
    instant = req_dt(payload, "current_utc")
    if instant < db.clock:
        fail("ERR_CLOCK_NOT_MONOTONIC")
    db.clock = instant
    return empty_response(200)


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------


@bp.post("/sessions")
@endpoint(("PlatformAdmin",))
def create_session(user_id, role):
    payload = body()
    name = req_str(payload, "name")
    introduction = req_dt(payload, "introduction_deadline_utc")
    report = req_dt(payload, "committee_report_deadline_utc")
    sine_die = req_dt(payload, "sine_die_utc")
    threshold = req_int(payload, "constrained_threshold_cents", minimum=0)
    cap = req_int(payload, "fiscal_cap_cents")
    years = req_int_array_ascending(payload, "required_fiscal_years")
    default_days = req_int(
        payload, "fiscal_note_default_days", required=False, default=21, minimum=1
    )
    if not (introduction < report < sine_die):
        fail(
            "ERR_INVALID_REQUEST",
            "introduction_deadline_utc < committee_report_deadline_utc < sine_die_utc is required.",
        )
    if cap < threshold:
        fail(
            "ERR_INVALID_REQUEST",
            "fiscal_cap_cents must be >= constrained_threshold_cents.",
        )
    row = create_row(
        "sessions",
        {
            "name": name,
            "introduction_deadline_utc": fmt_iso(introduction),
            "committee_report_deadline_utc": fmt_iso(report),
            "sine_die_utc": fmt_iso(sine_die),
            "fiscal_note_default_days": default_days,
            "constrained_threshold_cents": threshold,
            "fiscal_cap_cents": cap,
            "required_fiscal_years": years,
            "status": "PENDING",
            "convened_utc": None,
            "adjourned_utc": None,
            "next_house_bill_number": 1,
            "next_senate_bill_number": 1,
            "certified_fiscal_total_cents": 0,
            "fiscal_posture": "NORMAL",
            "bills_introduced_count": 0,
            "bills_enrolled_count": 0,
        },
    )
    return object_response(S.session_out(row), 201)


@bp.post("/sessions/<sid>/convene")
@endpoint(("Clerk",))
def convene_session(user_id, role, sid):
    session = get_session(sid)
    if session["status"] != "PENDING":
        fail("ERR_INVALID_SESSION_STATE")
    session["status"] = "CONVENED"
    session["convened_utc"] = db.now_iso()
    touch(session)
    return object_response(S.session_out(session))


@bp.post("/sessions/<sid>/adjourn")
@endpoint(("Clerk",))
def adjourn_session(user_id, role, sid):
    session = get_session(sid)
    # Rung 10 sits above rung 11: a second adjournment is ERR_SESSION_ADJOURNED.
    if session["status"] == "ADJOURNED":
        fail("ERR_SESSION_ADJOURNED")
    if session["status"] != "CONVENED":
        fail("ERR_INVALID_SESSION_STATE")

    session["status"] = "ADJOURNED"
    session["adjourned_utc"] = db.now_iso()
    touch(session)

    session_id = session["id"]
    bill_ids = set(b["id"] for b in db.bills.values() if b["session_id"] == session_id)

    members = set()
    drafters = set()
    committees = set()
    agencies = set()
    enrollments = set()

    for row in all_rows("drafting_requests"):
        if row["session_id"] != session_id:
            continue
        if row["status"] in (
            "SUBMITTED",
            "RESEARCH",
            "DRAFTING",
            "RETURNED_FOR_CLARIFICATION",
            "DRAFT_READY",
        ):
            row["status"] = "LAPSED"
            row["sla_due_utc"] = None
            touch(row)
            members.add(row["member_id"])
            if row["assigned_drafter_id"]:
                drafters.add(row["assigned_drafter_id"])

    for row in all_rows("amendments"):
        if row["bill_id"] not in bill_ids:
            continue
        if row["status"] in ("REQUESTED", "DRAFTED"):
            row["status"] = "LAPSED"
            touch(row)
            if row["drafted_by_drafter_id"]:
                drafters.add(row["drafted_by_drafter_id"])

    for row in all_rows("committee_referrals"):
        if row["bill_id"] not in bill_ids:
            continue
        if row["status"] == "IN_COMMITTEE":
            row["status"] = "DIED_IN_COMMITTEE"
            touch(row)
            committees.add(row["committee_id"])

    for row in all_rows("fiscal_note_requests"):
        if row["bill_id"] not in bill_ids:
            continue
        if row["status"] in ("ROUTED", "SUBMITTED", "RETURNED_FOR_REVISION"):
            row["status"] = "LAPSED"
            touch(row)
            agencies.add(row["agency_id"])

    session_enrollments = set(
        e["id"] for e in db.enrolled_bills.values() if e["bill_id"] in bill_ids
    )
    for row in all_rows("technical_corrections"):
        if row["enrolled_bill_id"] not in session_enrollments:
            continue
        if row["status"] == "PROPOSED":
            row["status"] = "REJECTED"
            touch(row)
            enrollments.add(row["enrolled_bill_id"])

    for row in all_rows("bills"):
        if row["session_id"] != session_id:
            continue
        if row["legislative_status"] in (
            "INTRODUCED",
            "REFERRED",
            "REPORTED",
            "PASSED_CHAMBER",
        ):
            row["legislative_status"] = "DEAD"
            touch(row)

    for member_id in members:
        recompute_member(member_id)
    for drafter_id in drafters:
        recompute_drafter(drafter_id)
    for committee_id in committees:
        recompute_committee(committee_id)
    for agency_id in agencies:
        recompute_agency(agency_id)
    for enrollment_id in enrollments:
        recompute_enrollment_counts(enrollment_id)
    recompute_session_bill_counts(session_id)
    # certified_fiscal_total_cents and fiscal_posture are deliberately untouched.
    return object_response(S.session_out(session))


# ---------------------------------------------------------------------------
# committees
# ---------------------------------------------------------------------------


@bp.post("/sessions/<sid>/committees")
@endpoint(("Clerk", "PlatformAdmin"))
def create_committee(user_id, role, sid):
    session = get_session(sid)
    payload = body()
    chamber = req_enum(payload, "chamber", CHAMBERS)
    name = req_str(payload, "name")
    is_fiscal = req_bool(payload, "is_fiscal_committee", required=False, default=False)
    max_referrals = req_int(
        payload, "max_concurrent_referrals", required=False, default=2, minimum=1
    )
    row = create_row(
        "committees",
        {
            "session_id": session["id"],
            "chamber": chamber,
            "name": name,
            "is_fiscal_committee": is_fiscal,
            "max_concurrent_referrals": max_referrals,
            "active_referral_count": 0,
        },
    )
    return object_response(S.committee_out(row), 201)


# ---------------------------------------------------------------------------
# members, drafters, agencies
# ---------------------------------------------------------------------------


@bp.post("/members")
@endpoint(("PlatformAdmin",))
def create_member(user_id, role):
    payload = body()
    full_name = req_str(payload, "full_name")
    chamber = req_enum(payload, "chamber", CHAMBERS)
    party = req_str(payload, "party")
    slots = req_int(payload, "priority_slots_total", required=False, default=2, minimum=0)
    row = create_row(
        "members",
        {
            "full_name": full_name,
            "chamber": chamber,
            "party": party,
            "priority_slots_total": slots,
            "priority_slots_used": 0,
            "clarification_pending_count": 0,
            "intake_hold": False,
        },
    )
    return object_response(S.member_out(row), 201)


@bp.post("/drafters")
@endpoint(("PlatformAdmin",))
def create_drafter(user_id, role):
    payload = body()
    full_name = req_str(payload, "full_name")
    is_senior = req_bool(payload, "is_senior", required=False, default=False)
    max_engagements = req_int(
        payload, "max_concurrent_engagements", required=False, default=2, minimum=1
    )
    row = create_row(
        "drafters",
        {
            "full_name": full_name,
            "is_senior": is_senior,
            "max_concurrent_engagements": max_engagements,
            "active_engagement_count": 0,
        },
    )
    return object_response(S.drafter_out(row), 201)


@bp.post("/agencies")
@endpoint(("PlatformAdmin",))
def create_agency(user_id, role):
    payload = body()
    name = req_str(payload, "name")
    agency_code = req_str(payload, "agency_code")
    status = req_enum(
        payload, "status", ("ACTIVE", "INACTIVE"), required=False, default="ACTIVE"
    )
    max_open = req_int(payload, "max_open_requests", required=False, default=3, minimum=1)
    for existing in db.agencies.values():
        if existing["agency_code"] == agency_code:
            fail("ERR_DUPLICATE_AGENCY_CODE")
    row = create_row(
        "agencies",
        {
            "name": name,
            "agency_code": agency_code,
            "status": status,
            "max_open_requests": max_open,
            "open_request_count": 0,
            "late_submission_count": 0,
            "revision_count": 0,
            "responsiveness_score": 100,
        },
    )
    return object_response(S.agency_out(row), 201)
