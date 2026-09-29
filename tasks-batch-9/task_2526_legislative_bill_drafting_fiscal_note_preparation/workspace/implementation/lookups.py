"""Existence resolution, session-lifecycle gating and page slicing."""

from errors import fail
from store import db
from validation import pagination

_NOT_FOUND = {
    "sessions": "ERR_SESSION_NOT_FOUND",
    "members": "ERR_MEMBER_NOT_FOUND",
    "drafters": "ERR_DRAFTER_NOT_FOUND",
    "agencies": "ERR_AGENCY_NOT_FOUND",
    "committees": "ERR_COMMITTEE_NOT_FOUND",
    "drafting_requests": "ERR_DRAFTING_REQUEST_NOT_FOUND",
    "statutory_conflicts": "ERR_STATUTORY_CONFLICT_NOT_FOUND",
    "bills": "ERR_BILL_NOT_FOUND",
    "committee_referrals": "ERR_COMMITTEE_REFERRAL_NOT_FOUND",
    "fiscal_note_requests": "ERR_FISCAL_NOTE_REQUEST_NOT_FOUND",
    "amendments": "ERR_AMENDMENT_NOT_FOUND",
    "enrolled_bills": "ERR_ENROLLED_BILL_NOT_FOUND",
    "technical_corrections": "ERR_TECHNICAL_CORRECTION_NOT_FOUND",
}


def must_get(collection, row_id):
    row = getattr(db, collection).get(row_id)
    if row is None:
        fail(_NOT_FOUND[collection])
    return row


def get_session(row_id):
    return must_get("sessions", row_id)


def get_member(row_id):
    return must_get("members", row_id)


def get_drafter(row_id):
    return must_get("drafters", row_id)


def get_agency(row_id):
    return must_get("agencies", row_id)


def get_committee(row_id):
    return must_get("committees", row_id)


def get_request(row_id):
    return must_get("drafting_requests", row_id)


def get_conflict(row_id):
    return must_get("statutory_conflicts", row_id)


def get_bill(row_id):
    return must_get("bills", row_id)


def get_referral(row_id):
    return must_get("committee_referrals", row_id)


def get_note(row_id):
    return must_get("fiscal_note_requests", row_id)


def get_amendment(row_id):
    return must_get("amendments", row_id)


def get_enrollment(row_id):
    return must_get("enrolled_bills", row_id)


def get_correction(row_id):
    return must_get("technical_corrections", row_id)


def session_of_bill(bill_row):
    return db.sessions.get(bill_row["session_id"])


def require_active_session(session_row):
    """PRD S2.11 rung 10 -- ADJOURNED is reported before NOT_CONVENED."""
    if session_row is None:
        return
    if session_row["status"] == "ADJOURNED":
        fail("ERR_SESSION_ADJOURNED")
    if session_row["status"] != "CONVENED":
        fail("ERR_SESSION_NOT_CONVENED")


def page(rows):
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    return window, limit, offset, total
