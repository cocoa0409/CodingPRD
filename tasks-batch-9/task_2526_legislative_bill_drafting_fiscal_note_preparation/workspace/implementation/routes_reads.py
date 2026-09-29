"""The 24 read endpoints of SCAFFOLD S1.5.

List order is created_at ASC everywhere except the session collection, which is
a management view ordered created_at DESC (PRD S2.3).
"""

from flask import Blueprint

from auth import ALL_ROLES, endpoint
from envelope import list_response, object_response
from errors import fail
from lookups import (
    get_agency,
    get_amendment,
    get_bill,
    get_committee,
    get_conflict,
    get_correction,
    get_drafter,
    get_enrollment,
    get_member,
    get_note,
    get_referral,
    get_request,
    get_session,
    page,
)
import serializers as S
from store import all_rows
from validation import matches, q_bool, q_int, q_str

bp = Blueprint("reads", __name__)

NO_AGENCY_ANALYST = (
    "PlatformAdmin",
    "Clerk",
    "FiscalOfficer",
    "Member",
    "Drafter",
    "ReviewCounsel",
)
DRAFTER_SIDE = ("PlatformAdmin", "Clerk", "FiscalOfficer", "Drafter", "ReviewCounsel")
AGENCY_READERS = ("PlatformAdmin", "Clerk", "FiscalOfficer", "AgencyAnalyst")


def _asc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def _desc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]), reverse=True)


def _confidentiality_gate(request_row, user_id, role):
    """PRD S2.8: a non-sponsoring Member is kept out of a confidential file."""
    if role != "Member":
        return
    if request_row["confidentiality"] != "CONFIDENTIAL":
        return
    if request_row["member_id"] != user_id:
        fail("ERR_CONFIDENTIAL_ACCESS_DENIED")


# ---------------------------------------------------------------------------
# reference data
# ---------------------------------------------------------------------------


@bp.get("/sessions/<sid>")
@endpoint(ALL_ROLES)
def read_session(user_id, role, sid):
    return object_response(S.session_out(get_session(sid)))


@bp.get("/sessions")
@endpoint(ALL_ROLES)
def list_sessions(user_id, role):
    status = q_str("status")
    rows = [r for r in all_rows("sessions") if matches(r, "status", status)]
    window, limit, offset, total = page(_desc(rows))
    return list_response([S.session_out(r) for r in window], limit, offset, total)


@bp.get("/sessions/<sid>/committees")
@endpoint(ALL_ROLES)
def list_session_committees(user_id, role, sid):
    session = get_session(sid)
    chamber = q_str("chamber")
    is_fiscal = q_bool("is_fiscal_committee")
    rows = [
        r
        for r in all_rows("committees")
        if r["session_id"] == session["id"]
        and matches(r, "chamber", chamber)
        and matches(r, "is_fiscal_committee", is_fiscal)
    ]
    window, limit, offset, total = page(_asc(rows))
    return list_response([S.committee_out(r) for r in window], limit, offset, total)


@bp.get("/committees/<cid>")
@endpoint(ALL_ROLES)
def read_committee(user_id, role, cid):
    return object_response(S.committee_out(get_committee(cid)))


@bp.get("/members/<mid>")
@endpoint(NO_AGENCY_ANALYST)
def read_member(user_id, role, mid):
    return object_response(S.member_out(get_member(mid)))


@bp.get("/drafters/<did>")
@endpoint(DRAFTER_SIDE)
def read_drafter(user_id, role, did):
    return object_response(S.drafter_out(get_drafter(did)))


@bp.get("/agencies/<aid>")
@endpoint(AGENCY_READERS)
def read_agency(user_id, role, aid):
    agency = get_agency(aid)
    if role == "AgencyAnalyst" and agency["id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER")
    return object_response(S.agency_out(agency))


# ---------------------------------------------------------------------------
# drafting
# ---------------------------------------------------------------------------


@bp.get("/drafting-requests/<rid>")
@endpoint(NO_AGENCY_ANALYST)
def read_drafting_request(user_id, role, rid):
    row = get_request(rid)
    _confidentiality_gate(row, user_id, role)
    return object_response(S.drafting_request_out(row))


@bp.get("/drafting-requests")
@endpoint(NO_AGENCY_ANALYST)
def list_drafting_requests(user_id, role):
    session_id = q_str("session_id")
    member_id = q_str("member_id")
    drafter_id = q_str("assigned_drafter_id")
    status = q_str("status")
    confidentiality = q_str("confidentiality")
    priority_flag = q_bool("priority_flag")
    rows = []
    for r in all_rows("drafting_requests"):
        if not (
            matches(r, "session_id", session_id)
            and matches(r, "member_id", member_id)
            and matches(r, "assigned_drafter_id", drafter_id)
            and matches(r, "status", status)
            and matches(r, "confidentiality", confidentiality)
            and matches(r, "priority_flag", priority_flag)
        ):
            continue
        # PRD S2.8: unsponsored confidential rows are omitted from the page and
        # from total_count -- no error is raised on the collection read.
        if (
            role == "Member"
            and r["confidentiality"] == "CONFIDENTIAL"
            and r["member_id"] != user_id
        ):
            continue
        rows.append(r)
    window, limit, offset, total = page(_asc(rows))
    return list_response(
        [S.drafting_request_out(r) for r in window], limit, offset, total
    )


@bp.get("/drafting-requests/<rid>/statutory-conflicts")
@endpoint(NO_AGENCY_ANALYST)
def list_request_conflicts(user_id, role, rid):
    request_row = get_request(rid)
    _confidentiality_gate(request_row, user_id, role)
    severity = q_str("severity")
    resolution_status = q_str("resolution_status")
    rows = [
        r
        for r in all_rows("statutory_conflicts")
        if r["drafting_request_id"] == request_row["id"]
        and matches(r, "severity", severity)
        and matches(r, "resolution_status", resolution_status)
    ]
    window, limit, offset, total = page(_asc(rows))
    return list_response(
        [S.statutory_conflict_out(r) for r in window], limit, offset, total
    )


@bp.get("/statutory-conflicts/<cid>")
@endpoint(NO_AGENCY_ANALYST)
def read_conflict(user_id, role, cid):
    conflict = get_conflict(cid)
    from store import db

    parent = db.drafting_requests.get(conflict["drafting_request_id"])
    if parent is not None:
        _confidentiality_gate(parent, user_id, role)
    return object_response(S.statutory_conflict_out(conflict))


# ---------------------------------------------------------------------------
# bills
# ---------------------------------------------------------------------------


@bp.get("/bills/<bid>")
@endpoint(ALL_ROLES)
def read_bill(user_id, role, bid):
    return object_response(S.bill_out(get_bill(bid)))


@bp.get("/bills")
@endpoint(ALL_ROLES)
def list_bills(user_id, role):
    filters = {
        "session_id": q_str("session_id"),
        "drafting_request_id": q_str("drafting_request_id"),
        "sponsor_member_id": q_str("sponsor_member_id"),
        "companion_bill_id": q_str("companion_bill_id"),
        "chamber": q_str("chamber"),
        "legislative_status": q_str("legislative_status"),
        "fiscal_status": q_str("fiscal_status"),
        "priority_bill": q_bool("priority_bill"),
    }
    rows = [
        r
        for r in all_rows("bills")
        if all(matches(r, field, wanted) for field, wanted in filters.items())
    ]
    window, limit, offset, total = page(_asc(rows))
    return list_response([S.bill_out(r) for r in window], limit, offset, total)


@bp.get("/committee-referrals/<rid>")
@endpoint(NO_AGENCY_ANALYST)
def read_referral(user_id, role, rid):
    return object_response(S.committee_referral_out(get_referral(rid)))


@bp.get("/committee-referrals")
@endpoint(NO_AGENCY_ANALYST)
def list_referrals(user_id, role):
    filters = {
        "bill_id": q_str("bill_id"),
        "committee_id": q_str("committee_id"),
        "status": q_str("status"),
    }
    rows = [
        r
        for r in all_rows("committee_referrals")
        if all(matches(r, field, wanted) for field, wanted in filters.items())
    ]
    window, limit, offset, total = page(_asc(rows))
    return list_response(
        [S.committee_referral_out(r) for r in window], limit, offset, total
    )


# ---------------------------------------------------------------------------
# fiscal
# ---------------------------------------------------------------------------


@bp.get("/fiscal-note-requests/<nid>")
@endpoint(ALL_ROLES)
def read_note(user_id, role, nid):
    return object_response(S.fiscal_note_request_out(get_note(nid)))


@bp.get("/fiscal-note-requests")
@endpoint(ALL_ROLES)
def list_notes(user_id, role):
    filters = {
        "bill_id": q_str("bill_id"),
        "agency_id": q_str("agency_id"),
        "reopened_by_amendment_id": q_str("reopened_by_amendment_id"),
        "status": q_str("status"),
        "methodology": q_str("methodology"),
    }
    rows = [
        r
        for r in all_rows("fiscal_note_requests")
        if all(matches(r, field, wanted) for field, wanted in filters.items())
    ]
    window, limit, offset, total = page(_asc(rows))
    return list_response(
        [S.fiscal_note_request_out(r) for r in window], limit, offset, total
    )


@bp.get("/fiscal-note-requests/<nid>/cost-estimates")
@endpoint(ALL_ROLES)
def list_cost_estimates(user_id, role, nid):
    note = get_note(nid)
    fiscal_year = q_int("fiscal_year")
    scenario = q_str("scenario")
    revision_round = q_int("revision_round")
    included = q_bool("included_in_certification")
    rows = []
    for r in all_rows("cost_estimates"):
        if r["fiscal_note_request_id"] != note["id"]:
            continue
        if not (
            matches(r, "fiscal_year", fiscal_year)
            and matches(r, "scenario", scenario)
            and matches(r, "revision_round", revision_round)
        ):
            continue
        payload = S.cost_estimate_out(r)
        if included is not None:
            if included is False or included is True:
                if payload["included_in_certification"] != included:
                    continue
            else:
                continue
        rows.append((r, payload))
    rows.sort(key=lambda pair: (pair[0]["created_at"], pair[0]["_seq"]))
    window, limit, offset, total = page(rows)
    return list_response([payload for _, payload in window], limit, offset, total)


# ---------------------------------------------------------------------------
# amendments and enrollment
# ---------------------------------------------------------------------------


@bp.get("/amendments/<aid>")
@endpoint(NO_AGENCY_ANALYST)
def read_amendment(user_id, role, aid):
    return object_response(S.amendment_out(get_amendment(aid)))


@bp.get("/amendments")
@endpoint(NO_AGENCY_ANALYST)
def list_amendments(user_id, role):
    filters = {
        "bill_id": q_str("bill_id"),
        "committee_referral_id": q_str("committee_referral_id"),
        "requested_by_member_id": q_str("requested_by_member_id"),
        "drafted_by_drafter_id": q_str("drafted_by_drafter_id"),
        "supersedes_amendment_id": q_str("supersedes_amendment_id"),
        "stage": q_str("stage"),
        "status": q_str("status"),
    }
    rows = [
        r
        for r in all_rows("amendments")
        if all(matches(r, field, wanted) for field, wanted in filters.items())
    ]
    window, limit, offset, total = page(_asc(rows))
    return list_response([S.amendment_out(r) for r in window], limit, offset, total)


@bp.get("/enrolled-bills/<eid>")
@endpoint(NO_AGENCY_ANALYST)
def read_enrollment(user_id, role, eid):
    return object_response(S.enrolled_bill_out(get_enrollment(eid)))


@bp.get("/enrolled-bills")
@endpoint(NO_AGENCY_ANALYST)
def list_enrollments(user_id, role):
    filters = {"bill_id": q_str("bill_id"), "status": q_str("status")}
    rows = [
        r
        for r in all_rows("enrolled_bills")
        if all(matches(r, field, wanted) for field, wanted in filters.items())
    ]
    window, limit, offset, total = page(_asc(rows))
    return list_response([S.enrolled_bill_out(r) for r in window], limit, offset, total)


@bp.get("/technical-corrections/<tid>")
@endpoint(DRAFTER_SIDE)
def read_correction(user_id, role, tid):
    return object_response(S.technical_correction_out(get_correction(tid)))


@bp.get("/technical-corrections")
@endpoint(DRAFTER_SIDE)
def list_corrections(user_id, role):
    filters = {
        "enrolled_bill_id": q_str("enrolled_bill_id"),
        "proposed_by_drafter_id": q_str("proposed_by_drafter_id"),
        "applied_by_drafter_id": q_str("applied_by_drafter_id"),
        "correction_type": q_str("correction_type"),
        "status": q_str("status"),
    }
    rows = [
        r
        for r in all_rows("technical_corrections")
        if all(matches(r, field, wanted) for field, wanted in filters.items())
    ]
    window, limit, offset, total = page(_asc(rows))
    return list_response(
        [S.technical_correction_out(r) for r in window], limit, offset, total
    )
