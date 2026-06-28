"""Claim, Disbursement filing & adjudication endpoints (PRD §3.8, §3.9).

Claim machine (branching with revert):
  SUBMITTED -> UNDER_REVIEW -> {APPROVED, DENIED}
  APPROVED  -> {PAID (disburse), UNDER_REVIEW (reopen), VOIDED}
  Disbursement SETTLED -> RETURNED reverts the claim to APPROVED.
Three reversal paths (reopen, void, return) credit the benefit ledger back.
"""

from flask import Blueprint, request

import calculations
import errors
import serializers
import services
from clock import format_iso8601_ms
from db import db
from middleware import require_roles
from response import success, list_success
from validation import (
    get_json_body, require_str, require_datetime, parse_pagination, paginate,
)

bp = Blueprint("claims", __name__)


# --------------------------------------------------------------------------- #
# File a claim (PRD §3.8)                                                      #
# --------------------------------------------------------------------------- #

@bp.route("/benefits/claims", methods=["POST"])
@require_roles("Employee", "BenefitsAdmin")
def create_claim():
    body = get_json_body()
    enrollment_id = require_str(body, "enrollment_id")
    disbursement_account_id = require_str(body, "disbursement_account_id")
    event_code = require_str(body, "event_code")
    event_date = require_datetime(body, "event_date")

    # Existence (priority 3) — left-to-right.
    enrollment = services.find_enrollment(enrollment_id)
    if enrollment is None:
        raise errors.not_found("Enrollment not found")
    account = services.find_account(disbursement_account_id)
    if account is None:
        raise errors.not_found("Disbursement account not found")

    # Referential consistency (priority 4): the named disbursement account must
    # belong to the same employee that owns the enrollment (PRD §2.7).
    if account["employee_id"] != enrollment["employee_id"]:
        raise errors.reference_mismatch("Disbursement account does not belong to the enrollee")

    # Temporal coverage (priority 7): event_date on/after enrolled_at AND the
    # enrollment must be ACTIVE at filing (PRD §3.8).
    enrolled_at = enrollment["_enrolled_at_dt"]
    if event_date < enrolled_at or enrollment["lifecycle_status"] != "ACTIVE":
        raise errors.event_before_coverage(
            "Claim event_date before coverage, or enrollment not ACTIVE at filing"
        )

    # Covered event (priority 8): event_code must match a schedule item on the
    # enrolled product (PRD §3.8).
    schedule_item = services.schedule_item_for_event(enrollment["plan_product_id"], event_code)
    if schedule_item is None:
        raise errors.event_not_covered("event_code not covered by the enrolled product")

    claimed_cents = calculations.claim_provisional(schedule_item)

    with db.lock:
        record = {
            "enrollment_id": enrollment_id,
            "disbursement_account_id": disbursement_account_id,
            "event_code": event_code,
            "event_date": format_iso8601_ms(event_date),
            "claimed_cents": claimed_cents,
            "approved_cents": 0,
            "paid_cents": 0,
            "status": "SUBMITTED",
            "denial_reason": None,
            "_event_date_dt": event_date,
        }
        db.claims.insert(record)
    return success(serializers.claim(record), 201)


@bp.route("/benefits/claims", methods=["GET"])
@require_roles("BenefitsAdmin", "ClaimsAdjuster", "Employee")
def list_claims():
    limit, offset = parse_pagination()
    enrollment_id = request.args.get("enrollment_id")
    disbursement_account_id = request.args.get("disbursement_account_id")
    status = request.args.get("status")

    items = db.claims.all()
    if enrollment_id is not None:
        items = [c for c in items if c["enrollment_id"] == enrollment_id]
    if disbursement_account_id is not None:
        items = [c for c in items if c["disbursement_account_id"] == disbursement_account_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]

    page, total = paginate(items, limit, offset)
    return list_success([serializers.claim(c) for c in page], limit, offset, total)


@bp.route("/benefits/claims/<claim_id>", methods=["GET"])
@require_roles("BenefitsAdmin", "ClaimsAdjuster", "Employee")
def get_claim(claim_id):
    record = db.claims.get(claim_id)
    if record is None:
        raise errors.not_found("Claim not found")
    return success(serializers.claim(record), 200)


# --------------------------------------------------------------------------- #
# Claim state machine (PRD §3.8, §3.9)                                         #
# --------------------------------------------------------------------------- #

@bp.route("/benefits/claims/<claim_id>/start-review", methods=["POST"])
@require_roles("ClaimsAdjuster")
def start_review(claim_id):
    record = db.claims.get(claim_id)
    if record is None:
        raise errors.not_found("Claim not found")
    with db.lock:
        if record["status"] != "SUBMITTED":
            raise errors.invalid_state("Claim must be SUBMITTED to start review")
        record["status"] = "UNDER_REVIEW"
        db.claims.touch(record)
    return success(serializers.claim(record), 200)


@bp.route("/benefits/claims/<claim_id>/approve", methods=["POST"])
@require_roles("ClaimsAdjuster")
def approve_claim(claim_id):
    record = db.claims.get(claim_id)
    if record is None:
        raise errors.not_found("Claim not found")

    with db.lock:
        # State (priority 5): allowed only from UNDER_REVIEW.
        if record["status"] != "UNDER_REVIEW":
            raise errors.invalid_state("Claim must be UNDER_REVIEW to approve")

        enrollment = services.find_enrollment(record["enrollment_id"])
        product = services.find_plan_product(enrollment["plan_product_id"])
        schedule_item = services.schedule_item_for_event(
            enrollment["plan_product_id"], record["event_code"]
        )

        # Lifetime-occurrence rule (priority 10): for a schedule line whose
        # lifetime_max_occurrences > 0, count prior APPROVED/PAID claims of this
        # event_code on this enrollment; reject if already >= the max (PRD §3.8).
        if schedule_item["lifetime_max_occurrences"] > 0:
            prior = sum(
                1 for c in db.claims.all()
                if c["enrollment_id"] == record["enrollment_id"]
                and c["event_code"] == record["event_code"]
                and c["status"] in ("APPROVED", "PAID")
            )
            if prior >= schedule_item["lifetime_max_occurrences"]:
                raise errors.lifetime_max_reached("Lifetime occurrence maximum already reached")

        # Adjudicate.
        approved_cents = calculations.claim_adjudicated(
            schedule_item,
            record["claimed_cents"],
            product["annual_benefit_cap_cents"],
            enrollment["benefit_paid_cents"],
        )

        # Annual-cap rule (priority 11): a non-wellness claim with no remaining
        # benefit (adjudicated 0) is exhausted (PRD §3.8).
        if not schedule_item["is_wellness"] and approved_cents == 0:
            raise errors.benefit_exhausted("Annual benefit remaining is 0")

        # Funding rule (priority 12): enrollment.funding_status must be CURRENT.
        if enrollment["funding_status"] != "CURRENT":
            raise errors.enrollment_not_funded("Enrollment is not CURRENT")

        record["approved_cents"] = approved_cents
        record["status"] = "APPROVED"
        db.claims.touch(record)

        # Debit the ledger for non-wellness approvals; wellness leaves it untouched.
        if not schedule_item["is_wellness"]:
            services.debit_benefit_ledger(enrollment, approved_cents)

    return success(serializers.claim(record), 200)


@bp.route("/benefits/claims/<claim_id>/deny", methods=["POST"])
@require_roles("ClaimsAdjuster")
def deny_claim(claim_id):
    record = db.claims.get(claim_id)
    if record is None:
        raise errors.not_found("Claim not found")
    body = get_json_body()
    denial_reason = require_str(body, "denial_reason")
    with db.lock:
        if record["status"] != "UNDER_REVIEW":
            raise errors.invalid_state("Claim must be UNDER_REVIEW to deny")
        record["status"] = "DENIED"
        record["denial_reason"] = denial_reason
        db.claims.touch(record)
    return success(serializers.claim(record), 200)


@bp.route("/benefits/claims/<claim_id>/reopen", methods=["POST"])
@require_roles("ClaimsAdjuster")
def reopen_claim(claim_id):
    record = db.claims.get(claim_id)
    if record is None:
        raise errors.not_found("Claim not found")
    with db.lock:
        if record["status"] != "APPROVED":
            raise errors.invalid_state("Claim must be APPROVED to reopen")
        # Blocked if a SETTLED disbursement exists (PRD §3.9).
        if services.settled_disbursement_for_claim(claim_id) is not None:
            raise errors.claim_already_paid("Claim has a SETTLED disbursement")

        _credit_back_for_claim(record)
        record["approved_cents"] = 0
        record["status"] = "UNDER_REVIEW"
        db.claims.touch(record)
    return success(serializers.claim(record), 200)


@bp.route("/benefits/claims/<claim_id>/void", methods=["POST"])
@require_roles("ClaimsAdjuster")
def void_claim(claim_id):
    record = db.claims.get(claim_id)
    if record is None:
        raise errors.not_found("Claim not found")
    with db.lock:
        if record["status"] != "APPROVED":
            raise errors.invalid_state("Claim must be APPROVED to void")
        if services.settled_disbursement_for_claim(claim_id) is not None:
            raise errors.claim_already_paid("Claim has a SETTLED disbursement")

        _credit_back_for_claim(record)
        record["status"] = "VOIDED"
        db.claims.touch(record)
    return success(serializers.claim(record), 200)


def _credit_back_for_claim(claim):
    """Compensating credit-back of benefit_paid_cents by approved_cents, wellness
    excluded (those never debited) (PRD §3.9)."""
    enrollment = services.find_enrollment(claim["enrollment_id"])
    schedule_item = services.schedule_item_for_event(
        enrollment["plan_product_id"], claim["event_code"]
    )
    if schedule_item is not None and not schedule_item["is_wellness"]:
        services.credit_benefit_ledger(enrollment, claim["approved_cents"])


# --------------------------------------------------------------------------- #
# Disbursement (PRD §3.9)                                                      #
# --------------------------------------------------------------------------- #

@bp.route("/benefits/claims/<claim_id>/disburse", methods=["POST"])
@require_roles("ClaimsAdjuster")
def disburse_claim(claim_id):
    record = db.claims.get(claim_id)
    if record is None:
        raise errors.not_found("Claim not found")

    with db.lock:
        # State (priority 5): claim must be APPROVED.
        if record["status"] != "APPROVED":
            raise errors.invalid_state("Claim must be APPROVED to disburse")

        # Account-verified rule (priority 9): the target account must be VERIFIED.
        account = services.find_account(record["disbursement_account_id"])
        if account is None or account["verification_status"] != "VERIFIED":
            raise errors.account_not_verified("Disbursement account is not VERIFIED")

        amount_cents = record["approved_cents"]
        disbursement = {
            "claim_id": claim_id,
            "disbursement_account_id": record["disbursement_account_id"],
            "amount_cents": amount_cents,
            "status": "SETTLED",
        }
        db.disbursements.insert(disbursement)

        # Settlement side effect: claim.status = PAID, claim.paid_cents = amount.
        record["status"] = "PAID"
        record["paid_cents"] = amount_cents
        db.claims.touch(record)

    return success(serializers.disbursement(disbursement), 201)


@bp.route("/benefits/disbursements", methods=["GET"])
@require_roles("BenefitsAdmin", "ClaimsAdjuster", "Employee")
def list_disbursements():
    limit, offset = parse_pagination()
    claim_id = request.args.get("claim_id")
    disbursement_account_id = request.args.get("disbursement_account_id")
    status = request.args.get("status")

    items = db.disbursements.all()
    if claim_id is not None:
        items = [d for d in items if d["claim_id"] == claim_id]
    if disbursement_account_id is not None:
        items = [d for d in items if d["disbursement_account_id"] == disbursement_account_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]

    page, total = paginate(items, limit, offset)
    return list_success([serializers.disbursement(d) for d in page], limit, offset, total)


@bp.route("/benefits/disbursements/<disbursement_id>", methods=["GET"])
@require_roles("BenefitsAdmin", "ClaimsAdjuster", "Employee")
def get_disbursement(disbursement_id):
    record = db.disbursements.get(disbursement_id)
    if record is None:
        raise errors.not_found("Disbursement not found")
    return success(serializers.disbursement(record), 200)


@bp.route("/benefits/disbursements/<disbursement_id>/return", methods=["POST"])
@require_roles("ClaimsAdjuster")
def return_disbursement(disbursement_id):
    record = db.disbursements.get(disbursement_id)
    if record is None:
        raise errors.not_found("Disbursement not found")
    with db.lock:
        # Permitted only from SETTLED (PRD §3.9).
        if record["status"] != "SETTLED":
            raise errors.invalid_state("Disbursement must be SETTLED to return")

        record["status"] = "RETURNED"
        db.disbursements.touch(record)

        claim = db.claims.get(record["claim_id"])
        # Credit back the ledger by amount_cents (wellness excluded), revert the
        # claim to APPROVED, reset paid_cents to 0 (PRD §3.9).
        enrollment = services.find_enrollment(claim["enrollment_id"])
        schedule_item = services.schedule_item_for_event(
            enrollment["plan_product_id"], claim["event_code"]
        )
        if schedule_item is not None and not schedule_item["is_wellness"]:
            services.credit_benefit_ledger(enrollment, record["amount_cents"])

        claim["status"] = "APPROVED"
        claim["paid_cents"] = 0
        db.claims.touch(claim)

    return success(serializers.disbursement(record), 200)
