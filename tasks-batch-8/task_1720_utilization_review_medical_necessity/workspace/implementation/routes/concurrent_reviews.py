"""ConcurrentReview endpoints: create, list, payer-decision."""
from datetime import timedelta
from flask import Blueprint

import db
from db import now_iso
from errors import (
    ApiError, ERR_CASE_CLOSED, ERR_INVALID_STATE, ERR_REVIEW_OVERDUE,
    ERR_BED_DAY_BUDGET_EXCEEDED, ERR_CERTIFIED_DAY_OVERLAP,
)
from middleware import require_roles
from response import success_object
from routes.helpers import paginate, lookup, any_authenticated
from services.case_service import recompute_certified_counts, intervals_overlap
from services.clock import logical_now, parse_iso
from services.common import init_common, touch, append_audit
from services.validation import (
    get_json_body, reject_unknown_fields, validate_enum, validate_int, validate_string,
)

bp = Blueprint("concurrent_reviews", __name__)

DECISIONS = {"APPROVE", "PARTIAL", "DENY"}
DENIAL_REASON_CODES = {"CRITERIA_NOT_MET", "DOC_INSUFFICIENT", "LEVEL_OF_CARE"}

CREATE_FIELDS = ["clinical_update", "requested_additional_day_count"]
DECISION_FIELDS = ["decision", "approved_day_count", "certified_day_start", "denial_reason_code"]


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


@bp.post("/api/authorization-requests/<aid>/concurrent-reviews")
def create_concurrent_review(aid):
    user_id, role = require_roles(["URNurse"])
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    validate_string(body, "clinical_update")
    validate_int(body, "requested_additional_day_count", min_val=1)

    ar = lookup(db.authorization_requests, aid, "AuthorizationRequest")
    case = db.utilization_cases[ar["case_id"]]
    payer = db.payers[case["payer_id"]]

    # Case-open gate
    if case["review_status"] == "CLOSED":
        raise ApiError(ERR_CASE_CLOSED, "Case is CLOSED", 409)
    # Parent auth must be APPROVED; previous review must be decided; at most one SUBMITTED outstanding
    if ar["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, "Parent authorization request is not APPROVED", 409)
    siblings = sorted(
        (c for c in db.concurrent_reviews.values() if c["authorization_request_id"] == aid),
        key=lambda c: c["created_at"],
    )
    if siblings:
        prev = siblings[-1]
        if prev["status"] == "SUBMITTED":
            raise ApiError(ERR_INVALID_STATE,
                           "A SUBMITTED concurrent review is still outstanding on this authorization", 409)

    sequence_index = len(siblings) + 1
    if sequence_index == 1:
        anchor = parse_iso(ar["decided_at"])
    else:
        anchor = parse_iso(siblings[-1]["decided_at"])
    due = anchor + timedelta(hours=payer["concurrent_review_cadence_hours"])

    # Temporal gate: now <= review_due_at (equality allowed)
    if logical_now() > due:
        raise ApiError(ERR_REVIEW_OVERDUE, "Concurrent review submitted after review_due_at", 422)

    cr = {
        **init_common(),
        "authorization_request_id": aid,
        "sequence_index": sequence_index,
        "clinical_update": body["clinical_update"],
        "requested_additional_day_count": body["requested_additional_day_count"],
        "review_due_at": _iso(due),
        "submitted_at": now_iso(),
        "status": "SUBMITTED",
        "approved_day_count": None,
        "certified_day_start": None,
        "certified_day_end": None,
        "decided_at": None,
        "denial_reason_code": None,
    }
    db.concurrent_reviews[cr["id"]] = cr
    append_audit(case["id"], "CONCURRENT_REVIEW_SUBMITTED", role, user_id,
                 f"Concurrent review {cr['id']} submitted (seq {sequence_index})")
    return success_object(cr, 201)


@bp.get("/api/authorization-requests/<aid>/concurrent-reviews")
def list_concurrent_reviews(aid):
    any_authenticated()
    lookup(db.authorization_requests, aid, "AuthorizationRequest")
    items = sorted(
        (c for c in db.concurrent_reviews.values() if c["authorization_request_id"] == aid),
        key=lambda c: c["created_at"],
    )
    return paginate(items)


@bp.post("/api/concurrent-reviews/<cid>/payer-decision")
def concurrent_payer_decision(cid):
    user_id, role = require_roles(["PayerReviewer"])
    body = get_json_body()
    reject_unknown_fields(body, DECISION_FIELDS)
    validate_enum(body, "decision", DECISIONS)
    decision = body["decision"]

    cr = lookup(db.concurrent_reviews, cid, "ConcurrentReview")
    ar = db.authorization_requests[cr["authorization_request_id"]]
    case = db.utilization_cases[ar["case_id"]]
    payer = db.payers[case["payer_id"]]

    if decision in ("APPROVE", "PARTIAL"):
        validate_int(body, "certified_day_start", min_val=1)
    if decision == "PARTIAL":
        validate_int(body, "approved_day_count", min_val=1)
    if decision == "DENY":
        validate_enum(body, "denial_reason_code", DENIAL_REASON_CODES)

    if case["review_status"] == "CLOSED":
        raise ApiError(ERR_CASE_CLOSED, "Case is CLOSED", 409)
    if cr["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, f"Concurrent review is {cr['status']}, not SUBMITTED", 409)

    if decision == "APPROVE":
        approved = cr["requested_additional_day_count"]
        start = body["certified_day_start"]
        end = start + approved
        if intervals_overlap(case["id"], start, end):
            raise ApiError(ERR_CERTIFIED_DAY_OVERLAP,
                           "Proposed certified interval intersects an existing certified interval", 409)
        if case["certified_day_count"] + approved > payer["bed_day_budget_per_case"]:
            raise ApiError(ERR_BED_DAY_BUDGET_EXCEEDED,
                           "Approval would exceed payer bed_day_budget_per_case", 422)
        cr["status"] = "APPROVED"
        cr["approved_day_count"] = approved
        cr["certified_day_start"] = start
        cr["certified_day_end"] = end
        cr["decided_at"] = now_iso()
        touch(cr)
        recompute_certified_counts(case)
        touch(case)
        append_audit(case["id"], "CONCURRENT_REVIEW_APPROVED", role, user_id,
                     f"Concurrent review {cid} approved [{start},{end})")
        return success_object(cr, 200)

    if decision == "PARTIAL":
        approved = body["approved_day_count"]
        if not (1 <= approved < cr["requested_additional_day_count"]):
            raise ApiError(ERR_INVALID_STATE,
                           "approved_day_count must be strictly between 1 and requested_additional_day_count",
                           409)
        start = body["certified_day_start"]
        end = start + approved
        if intervals_overlap(case["id"], start, end):
            raise ApiError(ERR_CERTIFIED_DAY_OVERLAP,
                           "Proposed certified interval intersects an existing certified interval", 409)
        if case["certified_day_count"] + approved > payer["bed_day_budget_per_case"]:
            raise ApiError(ERR_BED_DAY_BUDGET_EXCEEDED,
                           "Approval would exceed payer bed_day_budget_per_case", 422)
        cr["status"] = "PARTIALLY_APPROVED"
        cr["approved_day_count"] = approved
        cr["certified_day_start"] = start
        cr["certified_day_end"] = end
        cr["decided_at"] = now_iso()
        touch(cr)
        recompute_certified_counts(case)
        touch(case)
        append_audit(case["id"], "CONCURRENT_REVIEW_PARTIAL", role, user_id,
                     f"Concurrent review {cid} partially approved ({approved} days)")
        return success_object(cr, 200)

    # DENY
    cr["status"] = "DENIED"
    cr["approved_day_count"] = 0
    cr["denial_reason_code"] = body["denial_reason_code"]
    cr["decided_at"] = now_iso()
    touch(cr)

    appeal_deadline = parse_iso(cr["decided_at"]) + timedelta(days=payer["appeal_deadline_days"])
    denial = {
        **init_common(),
        "case_id": case["id"],
        "authorization_request_id": ar["id"],
        "denial_type": "CONCURRENT",
        "denied_at": cr["decided_at"],
        "denied_day_count": cr["requested_additional_day_count"],
        "appeal_deadline_at": _iso(appeal_deadline),
        "status": "OPEN",
    }
    db.denial_cases[denial["id"]] = denial

    case["auth_status"] = "DENIED"
    touch(case)
    append_audit(case["id"], "CONCURRENT_REVIEW_DENIED", role, user_id,
                 f"Concurrent review {cid} denied ({body['denial_reason_code']}); denial {denial['id']} opened")
    return success_object(cr, 200)
