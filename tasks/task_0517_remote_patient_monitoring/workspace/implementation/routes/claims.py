"""Claim endpoints: submission compliance + settlement cycle (PRD §3.9)."""
from datetime import timedelta

from flask import Blueprint, request

import errors
import serializers
import validation as V
from clock import clock, parse_iso8601
from common import (get_json_body, parse_pagination, sort_by_created,
                    paginate)
from db import db, stamp_create, touch
from middleware import require_roles
from response import object_response, array_response
from services import lookups, periods

bp = Blueprint("claims", __name__)


def _get_period_or_404(period_id):
    rec = db.billing_periods.get(period_id)
    if rec is None:
        raise errors.not_found("Billing period not found.")
    return rec


def _get_claim_or_404(claim_id):
    rec = db.claims.get(claim_id)
    if rec is None:
        raise errors.not_found("Claim not found.")
    return rec


def _consent_covers_month(patient_id, year, month):
    """An ACTIVE consent interval [effective_at, revoked_at) must fully contain
    the billing month interval (PRD §3.9). A consent whose effective_at is
    after the month start, or whose revoked_at is before the month end, leaves
    an uncovered gap."""
    month_start, month_end = periods.month_interval(year, month)
    for c in lookups.consents_of(patient_id):
        if c["status"] != "ACTIVE":
            continue
        eff = parse_iso8601(c["effective_at"])
        if eff is None or eff > month_start:
            continue
        rev = c.get("revoked_at")
        if rev is not None:
            rev_dt = parse_iso8601(rev)
            if rev_dt is not None and rev_dt < month_end:
                continue
        return True
    return False


@bp.post("/billing-periods/<period_id>/claims")
@require_roles("BillingSpecialist")
def submit_claim(period_id):
    period = _get_period_or_404(period_id)
    patient = db.patients.get(period["patient_id"])
    payer = db.payers.get(patient["payer_id"]) if patient else None

    # State legality (priority 6): submit only on a FINALIZED period.
    if period["status"] != "FINALIZED":
        raise errors.invalid_state("A claim may only be submitted on a FINALIZED period.")

    # Is there a DENIED claim to resubmit?
    denied_claim = None
    for c in lookups.claims_of_period(period_id):
        if c["status"] == "DENIED":
            denied_claim = c
            break

    now = clock.now()

    # Compliance checks. Ordering follows validations table:
    #   timely filing (18) -> billing consent gap (19) -> nothing to claim (20).
    # Timely filing (priority 18): submission instant within timely_filing_days
    # of the period's last calendar day.
    deadline = periods.last_calendar_day_end(period["period_year"],
                                             period["period_month"]) \
        + timedelta(days=payer["timely_filing_days"])
    if now > deadline:
        raise errors.ApiError(errors.ERR_TIMELY_FILING_EXPIRED, 409,
                              "Claim submitted beyond the timely-filing window.")

    # Billing consent gap (priority 19): if payer requires active consent, an
    # ACTIVE consent must fully contain the billing month.
    if payer["requires_active_consent"]:
        if not _consent_covers_month(period["patient_id"],
                                     period["period_year"],
                                     period["period_month"]):
            raise errors.ApiError(errors.ERR_BILLING_CONSENT_GAP, 409,
                                  "No ACTIVE consent fully covers the billing month.")

    # Nothing to claim (priority 20): finalized_total_cents == 0.
    if (period["finalized_total_cents"] or 0) == 0:
        raise errors.ApiError(errors.ERR_NOTHING_TO_CLAIM, 409,
                              "Finalized total is zero; nothing to claim.")

    if denied_claim is not None:
        # Resubmit cycle: DENIED -> SUBMITTED, reset claimed_cents.
        denied_claim["status"] = "SUBMITTED"
        denied_claim["claimed_cents"] = period["finalized_total_cents"]
        touch(denied_claim)
        period["status"] = "CLAIMED"
        touch(period)
        return object_response(serializers.claim(denied_claim), 201)

    claim = {
        "billing_period_id": period_id,
        "payer_id": patient["payer_id"],
        "claimed_cents": period["finalized_total_cents"],
        "reimbursed_cents": 0,
        "status": "SUBMITTED",
        "expected_billing_period_version": None,
    }
    stamp_create(claim)
    db.claims[claim["id"]] = claim
    period["status"] = "CLAIMED"
    touch(period)
    return object_response(serializers.claim(claim), 201)


@bp.get("/billing-periods/<period_id>/claims")
@require_roles("BillingSpecialist", "PayerAgent")
def list_period_claims(period_id):
    _get_period_or_404(period_id)
    limit, offset = parse_pagination()
    records = lookups.claims_of_period(period_id)
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    records = sort_by_created(records)
    page, total = paginate(records, limit, offset)
    return array_response([serializers.claim(r) for r in page],
                          limit, offset, total)


@bp.get("/claims")
@require_roles("BillingSpecialist", "PayerAgent")
def list_claims():
    limit, offset = parse_pagination()
    records = list(db.claims.values())
    payer_id = request.args.get("payer_id")
    if payer_id is not None:
        records = [r for r in records if r["payer_id"] == payer_id]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    records = sort_by_created(records)
    page, total = paginate(records, limit, offset)
    return array_response([serializers.claim(r) for r in page],
                          limit, offset, total)


@bp.get("/claims/<claim_id>")
@require_roles("BillingSpecialist", "PayerAgent")
def get_claim(claim_id):
    rec = _get_claim_or_404(claim_id)
    return object_response(serializers.claim(rec))


@bp.post("/claims/<claim_id>/accept")
@require_roles("PayerAgent")
def accept_claim(claim_id):
    rec = _get_claim_or_404(claim_id)
    if rec["status"] != "SUBMITTED":
        raise errors.invalid_state("Only a SUBMITTED claim can be accepted.")
    rec["status"] = "ACCEPTED"
    touch(rec)
    return object_response(serializers.claim(rec))


@bp.post("/claims/<claim_id>/deny")
@require_roles("PayerAgent")
def deny_claim(claim_id):
    rec = _get_claim_or_404(claim_id)
    if rec["status"] != "SUBMITTED":
        raise errors.invalid_state("Only a SUBMITTED claim can be denied.")
    rec["status"] = "DENIED"
    touch(rec)
    # Cascade: linked period CLAIMED -> FINALIZED for correction/resubmit.
    period = db.billing_periods.get(rec["billing_period_id"])
    if period is not None and period["status"] == "CLAIMED":
        period["status"] = "FINALIZED"
        touch(period)
    return object_response(serializers.claim(rec))


@bp.post("/claims/<claim_id>/remit")
@require_roles("PayerAgent")
def remit_claim(claim_id):
    rec = _get_claim_or_404(claim_id)
    body = get_json_body()
    remittance = V.require_int(body, "remittance_cents", minimum=0)

    # State legality (priority 6): remit from ACCEPTED or PARTIALLY_PAID.
    if rec["status"] not in ("ACCEPTED", "PARTIALLY_PAID"):
        raise errors.invalid_state("Only an ACCEPTED or PARTIALLY_PAID claim can be remitted.")

    new_total = rec["reimbursed_cents"] + remittance
    # Fiscal invariant (priority 21): never exceed claimed_cents.
    if new_total > rec["claimed_cents"]:
        raise errors.ApiError(errors.ERR_REMITTANCE_EXCEEDS_CLAIM, 422,
                              "Remittance would exceed claimed amount.")

    rec["reimbursed_cents"] = new_total
    if new_total == rec["claimed_cents"]:
        rec["status"] = "PAID"
    elif new_total > 0:
        rec["status"] = "PARTIALLY_PAID"
    # new_total == 0 (zero remittance from ACCEPTED) keeps status unchanged.
    touch(rec)
    return object_response(serializers.claim(rec))
