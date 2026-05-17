"""BillingClaim routes."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

from ..auth import require_roles
from ..clock import now
from ..errors import (
    err_claim_not_posted,
    err_not_found,
    err_validation,
    err_void_window_expired,
)
from ..helpers import paginate, parse_pagination
from ..responses import listing, ok
from ..services.calculations import (
    licensure_exam_eligible,
    compute_new_accrued,
)
from ..services.cascades import bump
from ..services.serialize import serialize_billing_claim
from ..store import store

bp = Blueprint("claims", __name__, url_prefix="/practice/claims")

CLAIM_STATUSES = ["POSTED", "VOIDED"]
BILLING_MODES = ["INSURANCE_IN_NETWORK", "SELF_PAY"]


@bp.get("/<cid>")
@require_roles("PracticeAdmin", "BillingClerk")
def get_claim(cid: str, **_):
    s = store()
    row = s.billing_claims.get(cid)
    if row is None:
        raise err_not_found("Claim not found")
    return ok(serialize_billing_claim(row))


@bp.get("")
@require_roles("PracticeAdmin", "BillingClerk")
def list_claims(**_):
    limit, offset = parse_pagination()
    patient_id = request.args.get("patient_id")
    status_filter = request.args.get("status")
    billing_mode = request.args.get("billing_mode")
    if status_filter is not None and status_filter not in CLAIM_STATUSES:
        raise err_validation("status filter invalid")
    if billing_mode is not None and billing_mode not in BILLING_MODES:
        raise err_validation("billing_mode filter invalid")
    s = store()
    rows = list(s.billing_claims.values())
    if patient_id:
        rows = [r for r in rows if r["patient_id"] == patient_id]
    if status_filter:
        rows = [r for r in rows if r["status"] == status_filter]
    if billing_mode:
        rows = [r for r in rows if r["billing_mode"] == billing_mode]
    rows.sort(key=lambda r: r["created_at"])
    return listing([serialize_billing_claim(r) for r in paginate(rows, limit, offset)],
                   total_count=len(rows), limit=limit, offset=offset)


@bp.post("/<cid>/void")
@require_roles("PracticeAdmin", "BillingClerk")
def void_claim(cid: str, **_):
    s = store()
    with s.lock:
        claim = s.billing_claims.get(cid)
        if claim is None:
            raise err_not_found("Claim not found")
        if claim["status"] != "POSTED":
            raise err_claim_not_posted()
        # Must be within 7-day window measured against the deterministic clock vs posted_at.
        if (now() - claim["posted_at"]) > timedelta(days=7):
            raise err_void_window_expired()
        # Mutate claim.
        claim["status"] = "VOIDED"
        bump(claim)

        # Compensating reversal — find owning session and appointment.
        appt = s.appointments[claim["appointment_id"]]
        sess = None
        for candidate in s.sessions.values():
            if candidate["appointment_id"] == appt["id"]:
                sess = candidate
                break

        # Restore deductible (in-network only).
        if claim["billing_mode"] == "INSURANCE_IN_NETWORK":
            consumed = claim.get("_deductible_consumed_cents", 0)
            if consumed:
                patient = s.patients[claim["patient_id"]]
                patient["deductible_remaining_cents"] += consumed
                bump(patient)

        # Reverse supervision-hour accrual using the owning session's credit hours.
        if sess is not None:
            therapist = s.therapists[appt["therapist_id"]]
            delta = -sess["supervision_credit_hours"]
            new_total = compute_new_accrued(therapist["supervision_hours_accrued"], delta)
            therapist["supervision_hours_accrued"] = new_total
            therapist["licensure_exam_eligible"] = licensure_exam_eligible(
                new_total, therapist["credential_status"]
            )
            bump(therapist)
            sess["status"] = "VOIDED"
            bump(sess)

        appt["status"] = "CANCELLED"
        appt["hold_reason"] = None
        bump(appt)
        return ok(serialize_billing_claim(claim))
