"""Introduction, companions, referrals, reporting, passage and enrollment
(PRD S3.5, S3.6 and the enrollment half of S3.9)."""

from datetime import timedelta

from flask import Blueprint

from auth import endpoint
import calc
from counters import (
    recompute_bill_rollups,
    recompute_committee,
    recompute_session_bill_counts,
)
from envelope import object_response
from errors import fail
from lookups import (
    get_bill,
    get_committee,
    get_referral,
    get_request,
    require_active_session,
)
import serializers as S
from store import all_rows, create_row, db, fmt_iso, parse_iso, touch
from validation import body, req_dt, req_enum, req_id, require_interval

bp = Blueprint("bills", __name__)

TERMINAL_BILL_STATES = ("DEAD", "TRANSMITTED")
FISCAL_CLEAR = ("NOT_REQUIRED", "NOTE_COMPLETE")


def _session_of_bill(bill):
    return db.sessions.get(bill["session_id"])


def _require_writable_bill(bill):
    if bill["legislative_status"] in TERMINAL_BILL_STATES:
        fail("ERR_INVALID_BILL_STATE")


# ---------------------------------------------------------------------------
# introduction
# ---------------------------------------------------------------------------


@bp.post("/bills")
@endpoint(("Clerk",))
def create_bill(user_id, role):
    payload = body()
    request_id = req_id(payload, "drafting_request_id")
    request_row = get_request(request_id)
    session = db.sessions.get(request_row["session_id"])
    require_active_session(session)
    if request_row["status"] != "DRAFT_READY":
        fail("ERR_INVALID_DRAFTING_REQUEST_STATE")
    if request_row["open_blocking_conflict_count"] > 0:
        fail("ERR_BLOCKING_CONFLICT_UNRESOLVED")
    if db.now() > parse_iso(session["introduction_deadline_utc"]):
        fail("ERR_INTRODUCTION_DEADLINE_PASSED")

    member = db.members.get(request_row["member_id"])
    chamber = member["chamber"] if member else "HOUSE"
    bill_number = calc.mint_bill_number(session, chamber)
    appropriation = request_row["appropriation_requested_cents"]
    bill = create_row(
        "bills",
        {
            "session_id": session["id"],
            "drafting_request_id": request_row["id"],
            "sponsor_member_id": request_row["member_id"],
            "companion_bill_id": None,
            "chamber": chamber,
            "bill_number": bill_number,
            "legislative_status": "INTRODUCED",
            "fiscal_status": "NOTE_PENDING" if appropriation > 0 else "NOT_REQUIRED",
            "appropriation_requested_cents": appropriation,
            "priority_bill": request_row["priority_flag"],
            "introduced_utc": db.now_iso(),
            "adopted_fiscal_delta_cents": 0,
            "adopted_amendment_count": 0,
            "referral_count": 0,
        },
    )
    request_row["status"] = "CONVERTED"
    touch(request_row)
    touch(session)
    recompute_session_bill_counts(session["id"])
    return object_response(S.bill_out(bill), 201)


# ---------------------------------------------------------------------------
# companion linkage
# ---------------------------------------------------------------------------


@bp.post("/bills/<bid>/companion")
@endpoint(("Clerk",))
def link_companion(user_id, role, bid):
    bill = get_bill(bid)
    payload = body()
    companion_id = req_id(payload, "companion_bill_id")
    if companion_id == bill["id"]:
        # Resolved as a body reference first; a self link cannot be missing.
        companion = bill
    else:
        companion = get_bill(companion_id)
    require_active_session(_session_of_bill(bill))
    _require_writable_bill(bill)
    if companion["id"] == bill["id"]:
        fail("ERR_COMPANION_SELF_LINK")
    if companion["chamber"] == bill["chamber"]:
        fail("ERR_COMPANION_CHAMBER_INVALID")
    if companion["session_id"] != bill["session_id"]:
        fail("ERR_COMPANION_SESSION_MISMATCH")
    if bill["companion_bill_id"] or companion["companion_bill_id"]:
        fail("ERR_COMPANION_ALREADY_LINKED")

    bill["companion_bill_id"] = companion["id"]
    companion["companion_bill_id"] = bill["id"]
    touch(bill)
    touch(companion)
    return object_response(S.bill_out(bill))


# ---------------------------------------------------------------------------
# referral
# ---------------------------------------------------------------------------


@bp.post("/bills/<bid>/referrals")
@endpoint(("Clerk",))
def create_referral(user_id, role, bid):
    bill = get_bill(bid)
    payload = body()
    committee_id = req_id(payload, "committee_id")
    start = req_dt(payload, "hearing_window_start_utc")
    end = req_dt(payload, "hearing_window_end_utc")
    require_interval(start, end, "hearing window")
    committee = get_committee(committee_id)
    session = _session_of_bill(bill)
    require_active_session(session)
    if bill["legislative_status"] not in ("INTRODUCED", "REFERRED"):
        fail("ERR_INVALID_BILL_STATE")
    if committee["session_id"] != bill["session_id"]:
        fail("ERR_COMMITTEE_SESSION_MISMATCH")
    if committee["chamber"] != bill["chamber"]:
        fail("ERR_COMMITTEE_CHAMBER_MISMATCH")
    report_deadline = parse_iso(session["committee_report_deadline_utc"])
    if end > report_deadline:
        fail("ERR_HEARING_WINDOW_AFTER_DEADLINE")
    if calc.hearing_window_conflicts(committee["id"], start, end):
        fail("ERR_COMMITTEE_HEARING_WINDOW_CONFLICT")
    if committee["active_referral_count"] >= committee["max_concurrent_referrals"]:
        fail("ERR_COMMITTEE_REFERRAL_CAPACITY_EXCEEDED")

    referral = create_row(
        "committee_referrals",
        {
            "bill_id": bill["id"],
            "committee_id": committee["id"],
            "referral_order": bill["referral_count"] + 1,
            "hearing_window_start_utc": fmt_iso(start),
            "hearing_window_end_utc": fmt_iso(end),
            "report_deadline_utc": fmt_iso(min(end + timedelta(days=7), report_deadline)),
            "status": "IN_COMMITTEE",
            "reported_utc": None,
        },
    )
    if bill["legislative_status"] == "INTRODUCED":
        bill["legislative_status"] = "REFERRED"
        touch(bill)
    recompute_bill_rollups(bill["id"])
    touch(bill)
    recompute_committee(committee["id"])
    return object_response(S.committee_referral_out(referral), 201)


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------


@bp.post("/committee-referrals/<rid>/report")
@endpoint(("Clerk",))
def report_referral(user_id, role, rid):
    referral = get_referral(rid)
    payload = body()
    outcome = req_enum(payload, "outcome", ("FAVORABLE", "UNFAVORABLE"))
    bill = db.bills.get(referral["bill_id"])
    session = _session_of_bill(bill) if bill else None
    require_active_session(session)
    if referral["status"] != "IN_COMMITTEE":
        fail("ERR_INVALID_REFERRAL_STATE")
    if outcome == "FAVORABLE" and bill["fiscal_status"] not in FISCAL_CLEAR:
        fail("ERR_FISCAL_NOTE_REQUIRED")
    if db.now() > parse_iso(referral["report_deadline_utc"]):
        fail("ERR_COMMITTEE_REPORT_DEADLINE_PASSED")
    committee = db.committees.get(referral["committee_id"])
    if outcome == "FAVORABLE":
        has_positive_certified = any(
            note["bill_id"] == bill["id"]
            and note["status"] == "CERTIFIED"
            and (note["certified_total_cents"] or 0) > 0
            for note in db.fiscal_note_requests.values()
        )
        if (
            session["fiscal_posture"] == "CONSTRAINED"
            and has_positive_certified
            and not (committee is not None and committee["is_fiscal_committee"])
        ):
            fail("ERR_FISCAL_COMMITTEE_REFERRAL_REQUIRED")

    referral["reported_utc"] = db.now_iso()
    touched_committees = set()
    if committee is not None:
        touched_committees.add(committee["id"])
    if outcome == "FAVORABLE":
        referral["status"] = "REPORTED_FAVORABLE"
        touch(referral)
        remaining = any(
            r["bill_id"] == bill["id"] and r["status"] == "IN_COMMITTEE"
            for r in db.committee_referrals.values()
        )
        if not remaining and bill["legislative_status"] == "REFERRED":
            bill["legislative_status"] = "REPORTED"
    else:
        referral["status"] = "REPORTED_UNFAVORABLE"
        touch(referral)
        bill["legislative_status"] = "DEAD"
        for sibling in all_rows("committee_referrals"):
            if sibling["bill_id"] != bill["id"] or sibling["id"] == referral["id"]:
                continue
            if sibling["status"] == "IN_COMMITTEE":
                sibling["status"] = "DIED_IN_COMMITTEE"
                touch(sibling)
                touched_committees.add(sibling["committee_id"])
    touch(bill)
    for committee_id in touched_committees:
        recompute_committee(committee_id)
    return object_response(S.committee_referral_out(referral))


# ---------------------------------------------------------------------------
# passage
# ---------------------------------------------------------------------------


@bp.post("/bills/<bid>/pass")
@endpoint(("Clerk",))
def pass_bill(user_id, role, bid):
    bill = get_bill(bid)
    session = _session_of_bill(bill)
    require_active_session(session)
    if bill["legislative_status"] != "REPORTED":
        fail("ERR_INVALID_BILL_STATE")
    outstanding = any(
        a["bill_id"] == bill["id"] and a["status"] in ("REQUESTED", "DRAFTED")
        for a in db.amendments.values()
    )
    if outstanding:
        fail("ERR_INVALID_BILL_STATE")
    if bill["fiscal_status"] not in FISCAL_CLEAR:
        fail("ERR_FISCAL_NOTE_REQUIRED")
    if db.now() > parse_iso(session["sine_die_utc"]):
        fail("ERR_SINE_DIE_PASSED")

    bill["legislative_status"] = "PASSED_CHAMBER"
    touch(bill)
    return object_response(S.bill_out(bill))


# ---------------------------------------------------------------------------
# enrollment
# ---------------------------------------------------------------------------


@bp.post("/bills/<bid>/enroll")
@endpoint(("Clerk",))
def enroll_bill(user_id, role, bid):
    bill = get_bill(bid)
    session = _session_of_bill(bill)
    require_active_session(session)
    if bill["legislative_status"] != "PASSED_CHAMBER":
        fail("ERR_INVALID_BILL_STATE")
    if bill["companion_bill_id"]:
        companion = db.bills.get(bill["companion_bill_id"])
        if companion is not None and companion["legislative_status"] not in (
            "PASSED_CHAMBER",
            "ENROLLED",
            "TRANSMITTED",
            "DEAD",
        ):
            fail("ERR_INVALID_BILL_STATE")
    for existing in db.enrolled_bills.values():
        if existing["bill_id"] == bill["id"]:
            fail("ERR_INVALID_BILL_STATE")
    if bill["fiscal_status"] not in FISCAL_CLEAR:
        fail("ERR_FISCAL_NOTE_REQUIRED")

    count, net, sequence, origin = calc.enrollment_composition(bill)
    enrollment = create_row(
        "enrolled_bills",
        {
            "bill_id": bill["id"],
            "adopted_amendment_count": count,
            "net_fiscal_delta_cents": net,
            "enrollment_sequence": sequence,
            "origin_signature_role": origin,
            "expected_next_signature": origin,
            "status": "PREPARED",
            "corrections_applied_count": 0,
            "open_corrections_count": 0,
            "origin_signed_utc": None,
            "second_signed_utc": None,
            "transmitted_utc": None,
        },
    )
    bill["legislative_status"] = "ENROLLED"
    touch(bill)
    recompute_session_bill_counts(session["id"])
    return object_response(S.enrolled_bill_out(enrollment), 201)
