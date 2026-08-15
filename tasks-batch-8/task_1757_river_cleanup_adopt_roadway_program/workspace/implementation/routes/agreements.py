"""AdoptionAgreement endpoints (PRD 3.2, 3.8): application, review, OCC
amendment, suspension, termination, renewal."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_SEGMENT_NOT_FOUND,
    ERR_GROUP_NOT_FOUND,
    ERR_AGREEMENT_NOT_PENDING,
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_AGREEMENT_NOT_IN_RENEWAL,
    ERR_AGREEMENT_TERMINAL,
    ERR_SEGMENT_NOT_AVAILABLE,
    ERR_RENEWAL_WINDOW_CLOSED,
    ERR_RENEWAL_NOT_ELIGIBLE,
    ERR_STALE_VERSION,
)
from middleware import get_caller, check_role, check_ownership, COORD, LEADER
from response import success_object
from routes.helpers import list_response
from services.compliance import anniversary_eligible, rolling_count, TERM_MONTHS
from services.core import (
    stamp_new, touch, public,
    suspend_cascade, terminate_cascade, expire_cascade,
)
from util import CLOCK, add_months, parse_date
from validate import (
    get_body, req_str, opt_nullable_str, ref_id, require_resource,
    maybe_resource,
)

bp = Blueprint("agreements", __name__)

AGREEMENT_STATUSES = [
    "PENDING_REVIEW", "ACTIVE", "SUSPENDED", "RENEWAL_REVIEW",
    "EXPIRED", "TERMINATED", "REJECTED",
]
RENEWAL_WINDOW_DAYS = 90


def _segment_has_open_hazard(segment_id):
    return any(
        h["segment_id"] == segment_id and h["status"] in ("REPORTED", "ACKNOWLEDGED")
        for h in db["hazards"].values()
    )


@bp.post("/program/agreements")
def create_agreement():
    caller = get_caller()
    check_role(caller, [LEADER])
    body = get_body()
    # family 3: body references that are present must resolve
    group_id = ref_id(body, "group_id")
    segment_id = ref_id(body, "segment_id")
    group = maybe_resource("groups", group_id, ERR_GROUP_NOT_FOUND)
    segment = maybe_resource("segments", segment_id, ERR_SEGMENT_NOT_FOUND)
    # family 4: the leader applies for their own group only
    if group is not None:
        check_ownership(caller, group["id"])
    # family 5: shape
    if group_id is None:
        raise_error(ERR_INVALID_REQUEST, "missing required field: group_id")
    if segment_id is None:
        raise_error(ERR_INVALID_REQUEST, "missing required field: segment_id")
    contact_email = req_str(body, "contact_email")
    special_instructions = opt_nullable_str(body, "special_instructions", None)
    # family 9: the segment must be AVAILABLE (not under a live agreement)
    if segment["status"] != "AVAILABLE":
        raise_error(ERR_SEGMENT_NOT_AVAILABLE,
                    "segment is spanned by another live agreement")
    rec = stamp_new({
        "group_id": group_id,
        "segment_id": segment_id,
        "contact_email": contact_email,
        "special_instructions": special_instructions,
        "status": "PENDING_REVIEW",
        "term_start_date": None,
        "term_end_date": None,
        "cleanups_completed_in_window": 0,
        "standing": "NOT_EVALUATED",
        "renewal_count": 0,
        "suspension_reason": None,
    })
    db["agreements"][rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.get("/program/agreements/<aid>")
def get_agreement(aid):
    caller = get_caller()
    check_role(caller, [COORD, LEADER])
    rec = require_resource("agreements", aid, ERR_AGREEMENT_NOT_FOUND)
    check_ownership(caller, rec["group_id"])
    return success_object(public(rec))


@bp.get("/program/agreements")
def list_agreements():
    caller = get_caller()
    check_role(caller, [COORD, LEADER])
    filters = {
        "group_id": request.args.get("group_id"),
        "segment_id": request.args.get("segment_id"),
        "status": request.args.get("status"),
    }
    return list_response("agreements", caller, filters=filters,
                         owner_of=lambda a: a["group_id"])


@bp.post("/program/agreements/<aid>/review-decision")
def review_decision(aid):
    caller = get_caller()
    check_role(caller, [COORD])
    rec = require_resource("agreements", aid, ERR_AGREEMENT_NOT_FOUND)
    body = get_body()
    decision = req_str(body, "decision")
    if decision not in ("APPROVE", "REJECT"):
        raise_error(ERR_INVALID_REQUEST, "decision must be APPROVE or REJECT")
    opt_nullable_str(body, "note", None)
    if rec["status"] != "PENDING_REVIEW":
        raise_error(ERR_AGREEMENT_NOT_PENDING, "agreement is not PENDING_REVIEW")
    if decision == "APPROVE":
        segment = db["segments"].get(rec["segment_id"])
        if segment is None or segment["status"] != "AVAILABLE":
            raise_error(ERR_SEGMENT_NOT_AVAILABLE,
                        "segment is no longer AVAILABLE (double approval)")
        segment["status"] = "ADOPTED"
        touch(segment)
        today = CLOCK.today()
        rec["term_start_date"] = today.isoformat()
        rec["term_end_date"] = add_months(today, TERM_MONTHS).isoformat()
        rec["standing"] = "NOT_EVALUATED"
        rec["status"] = "ACTIVE"
    else:
        rec["status"] = "REJECTED"
    touch(rec)
    return success_object(public(rec))


def _parse_expected_version(body):
    """OCC field: accept an integer or a decimal string (template substitution)."""
    v = body.get("expected_agreement_version")
    if isinstance(v, bool) or v is None:
        raise_error(ERR_INVALID_REQUEST, "missing or invalid field: expected_agreement_version")
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    raise_error(ERR_INVALID_REQUEST, "expected_agreement_version must be an integer")


@bp.patch("/program/agreements/<aid>")
def amend_agreement(aid):
    caller = get_caller()
    check_role(caller, [COORD, LEADER])
    rec = require_resource("agreements", aid, ERR_AGREEMENT_NOT_FOUND)
    check_ownership(caller, rec["group_id"])
    body = get_body()
    expected = _parse_expected_version(body)
    new_email = None
    if "contact_email" in body:
        new_email = req_str(body, "contact_email")
    new_notes = opt_nullable_str(body, "special_instructions", None)
    # family 6: state guard (PATCH also permits SUSPENDED), then OCC
    if rec["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_error(ERR_AGREEMENT_NOT_ACTIVE,
                    "amendment requires an ACTIVE or SUSPENDED agreement")
    if expected != rec["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_agreement_version does not match the current version")
    if new_email is not None:
        rec["contact_email"] = new_email
    if "special_instructions" in body:
        rec["special_instructions"] = new_notes
    touch(rec)
    return success_object(public(rec))


@bp.post("/program/agreements/<aid>/suspend")
def suspend_agreement(aid):
    caller = get_caller()
    check_role(caller, [COORD])
    rec = require_resource("agreements", aid, ERR_AGREEMENT_NOT_FOUND)
    body = get_body()
    reason = opt_nullable_str(body, "reason", None)
    if rec["status"] != "ACTIVE":
        raise_error(ERR_AGREEMENT_NOT_ACTIVE, "suspension requires an ACTIVE agreement")
    rec["status"] = "SUSPENDED"
    rec["suspension_reason"] = reason
    touch(rec)
    suspend_cascade(rec)
    return success_object(public(rec))


@bp.post("/program/agreements/<aid>/terminate")
def terminate_agreement(aid):
    caller = get_caller()
    check_role(caller, [COORD, LEADER])
    rec = require_resource("agreements", aid, ERR_AGREEMENT_NOT_FOUND)
    check_ownership(caller, rec["group_id"])
    opt_nullable_str(get_body(), "reason", None)
    if rec["status"] not in ("ACTIVE", "SUSPENDED", "RENEWAL_REVIEW"):
        raise_error(ERR_AGREEMENT_TERMINAL, "agreement is already terminal")
    rec["status"] = "TERMINATED"
    touch(rec)
    terminate_cascade(rec)
    return success_object(public(rec))


@bp.post("/program/agreements/<aid>/renewal-request")
def renewal_request(aid):
    caller = get_caller()
    check_role(caller, [LEADER])
    rec = require_resource("agreements", aid, ERR_AGREEMENT_NOT_FOUND)
    check_ownership(caller, rec["group_id"])
    if rec["status"] != "ACTIVE":
        raise_error(ERR_AGREEMENT_NOT_ACTIVE, "renewal-request requires an ACTIVE agreement")
    today = CLOCK.today()
    term_end = parse_date(rec["term_end_date"])
    window_open = term_end.fromordinal(term_end.toordinal() - RENEWAL_WINDOW_DAYS)
    if not (window_open <= today <= term_end):
        raise_error(ERR_RENEWAL_WINDOW_CLOSED,
                    "clock date is outside [term_end_date - 90 days, term_end_date]")
    rec["status"] = "RENEWAL_REVIEW"
    touch(rec)
    return success_object(public(rec))


@bp.post("/program/agreements/<aid>/renewal-decision")
def renewal_decision(aid):
    caller = get_caller()
    check_role(caller, [COORD])
    rec = require_resource("agreements", aid, ERR_AGREEMENT_NOT_FOUND)
    body = get_body()
    decision = req_str(body, "decision")
    if decision not in ("APPROVE", "DENY"):
        raise_error(ERR_INVALID_REQUEST, "decision must be APPROVE or DENY")
    opt_nullable_str(body, "note", None)
    if rec["status"] != "RENEWAL_REVIEW":
        raise_error(ERR_AGREEMENT_NOT_IN_RENEWAL, "agreement is not RENEWAL_REVIEW")
    if decision == "APPROVE":
        # family 9: ANNIVERSARY eligibility + zero open hazards on the segment
        if not anniversary_eligible(rec) or _segment_has_open_hazard(rec["segment_id"]):
            raise_error(ERR_RENEWAL_NOT_ELIGIBLE,
                        "a 12-month term window holds fewer than 3 completions or the segment has an open hazard")
        old_end = parse_date(rec["term_end_date"])
        rec["term_start_date"] = old_end.isoformat()
        rec["term_end_date"] = add_months(old_end, TERM_MONTHS).isoformat()
        rec["renewal_count"] += 1
        rec["standing"] = "NOT_EVALUATED"
        rec["cleanups_completed_in_window"] = rolling_count(rec["id"], CLOCK.today())
        rec["status"] = "ACTIVE"
    else:
        rec["status"] = "EXPIRED"
        expire_cascade(rec)
    touch(rec)
    return success_object(public(rec))
