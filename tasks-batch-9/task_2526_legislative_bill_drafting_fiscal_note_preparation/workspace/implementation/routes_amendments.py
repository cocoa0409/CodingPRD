"""Amendment request, drafting, adoption, rejection and rescission, including
the four-level fiscal re-opening cascade and its compensating action
(PRD S3.8)."""

from flask import Blueprint

from auth import endpoint
import calc
from counters import post_to_ledger, recompute_agency, recompute_drafter
from envelope import object_response
from errors import fail
from lookups import get_amendment, get_bill, get_referral, require_active_session
import serializers as S
from store import all_rows, create_row, db, fmt_iso, parse_iso, touch
from validation import body, req_dt, req_enum, req_id, req_int, req_str, require_interval

bp = Blueprint("amendments", __name__)

TERMINAL_BILL_STATES = ("DEAD", "TRANSMITTED")


def _session_of_bill(bill):
    return db.sessions.get(bill["session_id"])


def _bill_of(amendment):
    return db.bills.get(amendment["bill_id"])


# ---------------------------------------------------------------------------
# request
# ---------------------------------------------------------------------------


@bp.post("/amendments")
@endpoint(("Member",))
def create_amendment(user_id, role):
    payload = body()
    expected = req_int(payload, "expected_bill_version")
    bill_id = req_id(payload, "bill_id")
    stage = req_enum(payload, "stage", ("COMMITTEE", "FLOOR"))
    summary = req_str(payload, "summary")
    delta = req_int(payload, "fiscal_impact_delta_cents")
    start = req_dt(payload, "drafting_start_utc")
    end = req_dt(payload, "drafting_due_utc")
    require_interval(start, end, "drafting window")
    referral_id = req_id(payload, "committee_referral_id", required=False)
    supersedes_id = req_id(payload, "supersedes_amendment_id", required=False)

    bill = get_bill(bill_id)
    referral = get_referral(referral_id) if referral_id is not None else None
    supersedes = get_amendment(supersedes_id) if supersedes_id is not None else None
    if expected != bill["version"]:
        fail("ERR_STALE_BILL_VERSION")
    session = _session_of_bill(bill)
    require_active_session(session)
    if bill["legislative_status"] in TERMINAL_BILL_STATES:
        fail("ERR_INVALID_BILL_STATE")
    if stage == "COMMITTEE":
        if (
            referral is None
            or referral["bill_id"] != bill["id"]
            or referral["status"] != "IN_COMMITTEE"
        ):
            fail("ERR_AMENDMENT_STAGE_MISMATCH")
    else:
        if referral is not None or bill["legislative_status"] != "REPORTED":
            fail("ERR_AMENDMENT_STAGE_MISMATCH")
    if supersedes is not None and (
        supersedes["bill_id"] != bill["id"]
        or supersedes["status"] not in ("REJECTED", "LAPSED")
    ):
        fail("ERR_SUPERSEDE_TARGET_INVALID")

    requested = db.now()
    amendment = create_row(
        "amendments",
        {
            "bill_id": bill["id"],
            "committee_referral_id": referral["id"] if referral is not None else None,
            "requested_by_member_id": user_id,
            "drafted_by_drafter_id": None,
            "supersedes_amendment_id": supersedes["id"] if supersedes is not None else None,
            "stage": stage,
            "summary": summary,
            "fiscal_impact_delta_cents": delta,
            "drafting_start_utc": fmt_iso(start),
            "drafting_due_utc": fmt_iso(end),
            "requested_utc": fmt_iso(requested),
            "turnaround_deadline_utc": fmt_iso(
                calc.amendment_turnaround_deadline(stage, requested, session)
            ),
            "status": "REQUESTED",
            "drafted_utc": None,
            "adopted_utc": None,
            "rescind_count": 0,
        },
    )
    touch(bill)
    return object_response(S.amendment_out(amendment), 201)


# ---------------------------------------------------------------------------
# drafting
# ---------------------------------------------------------------------------


@bp.post("/amendments/<aid>/draft")
@endpoint(("Drafter",))
def draft_amendment(user_id, role, aid):
    amendment = get_amendment(aid)
    drafter = db.drafters.get(user_id)
    if drafter is None:
        fail("ERR_NOT_RESOURCE_OWNER")
    payload = body()
    req_str(payload, "draft_text")
    bill = _bill_of(amendment)
    require_active_session(_session_of_bill(bill) if bill else None)
    if amendment["status"] != "REQUESTED":
        fail("ERR_INVALID_AMENDMENT_STATE")
    if db.now() > parse_iso(amendment["turnaround_deadline_utc"]):
        fail("ERR_AMENDMENT_TURNAROUND_EXPIRED")
    start = parse_iso(amendment["drafting_start_utc"])
    end = parse_iso(amendment["drafting_due_utc"])
    if not calc.drafter_admits(drafter, start, end, exclude_amendment_id=amendment["id"]):
        fail("ERR_DRAFTER_ENGAGEMENT_CAPACITY_EXCEEDED")

    amendment["status"] = "DRAFTED"
    amendment["drafted_by_drafter_id"] = user_id
    amendment["drafted_utc"] = db.now_iso()
    touch(amendment)
    recompute_drafter(user_id)
    return object_response(S.amendment_out(amendment))


# ---------------------------------------------------------------------------
# adoption and the fiscal re-opening cascade
# ---------------------------------------------------------------------------


def _reopen_note(bill, amendment, session):
    """Cascade levels 2 through 4 (PRD S3.8)."""
    note = None
    for row in all_rows("fiscal_note_requests"):
        if row["bill_id"] == bill["id"] and row["status"] == "CERTIFIED":
            note = row
    if note is None:
        return
    agency = db.agencies.get(note["agency_id"])
    routed = db.now()
    note["status"] = "ROUTED"
    note["revision_round"] = note["revision_round"] + 1
    note["reopened_by_amendment_id"] = amendment["id"]
    note["routed_utc"] = fmt_iso(routed)
    if agency is not None:
        note["due_utc"] = fmt_iso(calc.fiscal_note_due_utc(agency, session, routed))
    touch(note)
    for line in all_rows("cost_estimates"):
        if line["fiscal_note_request_id"] == note["id"]:
            line["included_in_certification"] = (
                line["revision_round"] == note["revision_round"]
            )
    if agency is not None:
        recompute_agency(agency["id"])
    post_to_ledger(session, -(note["certified_total_cents"] or 0))


@bp.post("/amendments/<aid>/adopt")
@endpoint(("Clerk",))
def adopt_amendment(user_id, role, aid):
    amendment = get_amendment(aid)
    bill = _bill_of(amendment)
    session = _session_of_bill(bill) if bill else None
    require_active_session(session)
    if amendment["status"] != "DRAFTED":
        fail("ERR_INVALID_AMENDMENT_STATE")
    if amendment["stage"] == "COMMITTEE":
        referral = db.committee_referrals.get(amendment["committee_referral_id"])
        if referral is None or referral["status"] != "IN_COMMITTEE":
            fail("ERR_AMENDMENT_STAGE_MISMATCH")
    elif bill["legislative_status"] != "REPORTED":
        fail("ERR_AMENDMENT_STAGE_MISMATCH")

    drafter_id = amendment["drafted_by_drafter_id"]
    amendment["status"] = "ADOPTED"
    amendment["adopted_utc"] = db.now_iso()
    touch(amendment)
    delta = amendment["fiscal_impact_delta_cents"]
    bill["adopted_amendment_count"] = bill["adopted_amendment_count"] + 1
    bill["adopted_fiscal_delta_cents"] = bill["adopted_fiscal_delta_cents"] + delta
    if delta != 0:
        if bill["fiscal_status"] == "NOT_REQUIRED":
            bill["fiscal_status"] = "NOTE_PENDING"
        elif bill["fiscal_status"] == "NOTE_COMPLETE":
            bill["fiscal_status"] = "NOTE_STALE"
            touch(bill)
            _reopen_note(bill, amendment, session)
    touch(bill)
    if drafter_id:
        recompute_drafter(drafter_id)
    return object_response(S.amendment_out(amendment))


# ---------------------------------------------------------------------------
# rejection
# ---------------------------------------------------------------------------


@bp.post("/amendments/<aid>/reject")
@endpoint(("Clerk",))
def reject_amendment(user_id, role, aid):
    amendment = get_amendment(aid)
    payload = body()
    req_str(payload, "rejection_reason", required=False)
    bill = _bill_of(amendment)
    require_active_session(_session_of_bill(bill) if bill else None)
    if amendment["status"] != "DRAFTED":
        fail("ERR_INVALID_AMENDMENT_STATE")

    drafter_id = amendment["drafted_by_drafter_id"]
    amendment["status"] = "REJECTED"
    touch(amendment)
    if drafter_id:
        recompute_drafter(drafter_id)
    return object_response(S.amendment_out(amendment))


# ---------------------------------------------------------------------------
# rescission and the compensating fiscal restoration
# ---------------------------------------------------------------------------


def _restore_note(bill, amendment, session):
    if bill["fiscal_status"] != "NOTE_STALE":
        return
    note = None
    for row in all_rows("fiscal_note_requests"):
        if (
            row["bill_id"] == bill["id"]
            and row["reopened_by_amendment_id"] == amendment["id"]
            and row["status"] == "ROUTED"
        ):
            note = row
    if note is None:
        return
    for other in db.amendments.values():
        if (
            other["bill_id"] == bill["id"]
            and other["status"] == "ADOPTED"
            and other["fiscal_impact_delta_cents"] != 0
        ):
            return
    note["status"] = "CERTIFIED"
    note["reopened_by_amendment_id"] = None
    touch(note)
    recompute_agency(note["agency_id"])
    post_to_ledger(session, note["certified_total_cents"] or 0)
    bill["fiscal_status"] = "NOTE_COMPLETE"
    touch(bill)


@bp.post("/amendments/<aid>/rescind")
@endpoint(("Clerk",))
def rescind_amendment(user_id, role, aid):
    amendment = get_amendment(aid)
    payload = body()
    req_str(payload, "rescission_reason")
    bill = _bill_of(amendment)
    session = _session_of_bill(bill) if bill else None
    require_active_session(session)
    if amendment["status"] != "ADOPTED":
        fail("ERR_INVALID_AMENDMENT_STATE")
    if bill["legislative_status"] in ("ENROLLED", "TRANSMITTED", "DEAD"):
        fail("ERR_INVALID_BILL_STATE")

    drafter_id = amendment["drafted_by_drafter_id"]
    amendment["status"] = "DRAFTED"
    amendment["rescind_count"] = amendment["rescind_count"] + 1
    amendment["adopted_utc"] = None
    touch(amendment)
    bill["adopted_amendment_count"] = bill["adopted_amendment_count"] - 1
    bill["adopted_fiscal_delta_cents"] = (
        bill["adopted_fiscal_delta_cents"] - amendment["fiscal_impact_delta_cents"]
    )
    touch(bill)
    _restore_note(bill, amendment, session)
    if drafter_id:
        recompute_drafter(drafter_id)
    return object_response(S.amendment_out(amendment))
