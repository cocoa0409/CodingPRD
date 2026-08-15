"""Regulatory referral lifecycle and the response clock (PRD §3.8)."""
from flask import Blueprint

import services as svc
from db import store
from errors import ApiError, ERR_INVALID_STATE_TRANSITION
from middleware import (
    get_body,
    pagination_params,
    req_nonempty_str,
    require_roles,
)
from response import ok, ok_list

bp = Blueprint("referrals", __name__)

REF_READERS = ("ComplaintManager", "CaseHandler", "QAReviewer", "ExecutiveReviewer", "Auditor")


@bp.get("/complaints/<cid>/referrals")
@require_roles(*REF_READERS)
def list_referrals(cid):
    svc.get_complaint(cid)
    limit, offset = pagination_params()
    recs = [r for r in store.referrals.values() if r.complaint_id == cid]
    items, total = svc.paged(recs, svc.ser_referral, limit, offset)
    return ok_list(items, total, limit, offset)


@bp.get("/referrals/<referralId>")
@require_roles(*REF_READERS)
def get_referral(referralId):
    return ok(svc.ser_referral(svc.get_referral(referralId)), 200)


@bp.post("/referrals/<referralId>/submit_response")
@require_roles("CaseHandler")
def submit_response(referralId):
    r = svc.get_referral(referralId)
    body = get_body()
    response_text = req_nonempty_str(body, "response_text")
    if r.status not in ("OPEN", "REOPENED_BY_REGULATOR"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            f"Referral status is {r.status}; submit_response requires OPEN or REOPENED_BY_REGULATOR.",
            409,
        )
    now = store.now()
    r.submitted_at = now
    # Inclusive boundary: submitted exactly at response_due_at is ON_TIME.
    # A regulator reopen never extends the deadline: same response_due_at.
    r.timeliness = "ON_TIME" if now <= r.response_due_at else "LATE"
    r.status = "RESPONSE_SUBMITTED"
    r.response_text = response_text
    svc.touch(r)
    complaint = svc.get_complaint(r.complaint_id)
    svc.recompute_timeliness_score(complaint)
    svc.append_event(complaint.id, "REFERRAL_RESPONDED", {"referral_id": r.id, "timeliness": r.timeliness})
    return ok(svc.ser_referral(r), 200)


@bp.post("/referrals/<referralId>/close")
@require_roles("ComplaintManager")
def close_referral(referralId):
    r = svc.get_referral(referralId)
    if r.status != "RESPONSE_SUBMITTED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            f"Referral status is {r.status}; close requires RESPONSE_SUBMITTED.",
            409,
        )
    r.status = "CLOSED_BY_REGULATOR"
    svc.touch(r)
    return ok(svc.ser_referral(r), 200)


@bp.post("/referrals/<referralId>/regulator_reopen")
@require_roles("ComplaintManager")
def regulator_reopen(referralId):
    r = svc.get_referral(referralId)
    if r.status != "RESPONSE_SUBMITTED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            f"Referral status is {r.status}; regulator_reopen requires RESPONSE_SUBMITTED.",
            409,
        )
    r.status = "REOPENED_BY_REGULATOR"
    svc.touch(r)
    # Cascade hop 2: a RESOLVED parent complaint transitions to REOPENED.
    complaint = svc.get_complaint(r.complaint_id)
    if complaint.status == "RESOLVED":
        complaint.status = "REOPENED"
        complaint.resolved_at = None
        complaint.retention_purge_at = None
        svc.touch(complaint)
        # Cascade hop 3: product counters and posture recompute.
        svc.recompute_posture(store.product_by_code[complaint.product_code])
    return ok(svc.ser_referral(r), 200)
