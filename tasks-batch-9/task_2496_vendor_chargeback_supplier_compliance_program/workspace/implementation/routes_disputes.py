"""Vendor disputes: opening, evidence, review rounds and adjudication."""

from decimal import Decimal

from flask import Blueprint

import lookup
import serializers as ser
from core import (
    DISPUTE_MAX_ROUNDS,
    DISPUTE_WINDOW_DAYS,
    EVIDENCE_KINDS,
    DISPUTE_REASON_CODES,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_VENDOR,
    ApiError,
    authenticate,
    body_dict,
    clock,
    days,
    new_append_only_record,
    new_record,
    object_response,
    opt_str,
    req_enum,
    req_int,
    req_str,
    store,
    touch,
)
from derive import (
    allocations_of_chargeback,
    dispute_determination,
    pinned_requirement,
    recompute_chargeback,
    recompute_deduction,
    reconcile_vendor,
)

bp = Blueprint("disputes", __name__)

VENDOR = (ROLE_VENDOR,)
OFFICER = (ROLE_COMPLIANCE_OFFICER,)
AWAITING = ("SUBMITTED", "INFO_REQUESTED")


@bp.post("/compliance/chargebacks/<identifier>/disputes")
def open_dispute(identifier):
    user_id, _role = authenticate(VENDOR)
    body = body_dict()
    reason_code = req_enum(body, "reason_code", DISPUTE_REASON_CODES)
    claimed_reversal_cents = req_int(body, "claimed_reversal_cents", 1)
    narrative = req_str(body, "narrative", 1, 1000)

    chargeback = lookup.chargeback(identifier)
    if chargeback["vendor_id"] != user_id:
        raise ApiError(
            "ERR_VENDOR_SCOPE_VIOLATION", "A vendor may only dispute its own chargebacks."
        )
    if chargeback["settlement_status"] == "WRITTEN_OFF":
        raise ApiError(
            "ERR_CHARGEBACK_WRITTEN_OFF", "This chargeback has already been written off."
        )
    if clock.now() >= chargeback["assessed_at"] + days(DISPUTE_WINDOW_DAYS):
        raise ApiError("ERR_DISPUTE_WINDOW_CLOSED", "The 30-day dispute window has closed.")
    if chargeback["dispute_status"] != "NONE":
        raise ApiError(
            "ERR_DISPUTE_ALREADY_EXISTS", "This chargeback already carries a dispute."
        )
    eligible = chargeback["gross_assessed_cents"] - chargeback["reversal_cents"]
    if claimed_reversal_cents > eligible:
        raise ApiError(
            "ERR_CLAIM_EXCEEDS_ASSESSMENT",
            "claimed_reversal_cents may not exceed the amount still assessed.",
        )

    dispute = new_record(
        chargeback_id=chargeback["id"],
        vendor_id=chargeback["vendor_id"],
        reason_code=reason_code,
        claimed_reversal_cents=claimed_reversal_cents,
        narrative=narrative,
        status="SUBMITTED",
        round_count=1,
        reason_ceiling_pct=None,
        approved_reversal_cents=0,
        goodwill_cents=0,
        submitted_at=clock.now(),
        decided_at=None,
        decided_by_user_id=None,
        information_request_note=None,
        review_note=None,
    )
    store.disputes[dispute["id"]] = dispute

    chargeback["dispute_status"] = "OPEN"
    touch(chargeback)
    return object_response(ser.dispute_out(dispute), 201)


@bp.post("/compliance/disputes/<identifier>/evidence")
def attach_dispute_evidence(identifier):
    user_id, _role = authenticate(VENDOR)
    body = body_dict()
    kind = req_enum(body, "kind", EVIDENCE_KINDS)
    reference_uri = req_str(body, "reference_uri", 1, 300)
    note = opt_str(body, "note", 1, 1000)

    dispute = lookup.dispute(identifier)
    if dispute["vendor_id"] != user_id:
        raise ApiError(
            "ERR_VENDOR_SCOPE_VIOLATION", "A vendor may only supplement its own dispute."
        )
    if dispute["status"] not in AWAITING:
        raise ApiError(
            "ERR_DISPUTE_NOT_AWAITING_DECISION", "This dispute has already been decided."
        )

    evidence = new_append_only_record(
        violation_id=None,
        dispute_id=dispute["id"],
        subject_type="DISPUTE",
        kind=kind,
        reference_uri=reference_uri,
        note=note,
        captured_by_user_id=user_id,
        captured_at=clock.now(),
    )
    store.evidence[evidence["id"]] = evidence
    return object_response(ser.evidence_out(evidence), 201)


@bp.post("/compliance/disputes/<identifier>/request-info")
def request_dispute_info(identifier):
    authenticate(OFFICER)
    body = body_dict()
    note = req_str(body, "information_request_note", 1, 1000)

    dispute = lookup.dispute(identifier)
    if dispute["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_DISPUTE_NOT_AWAITING_DECISION",
            "Only a submitted dispute may be returned for more information.",
        )
    if dispute["round_count"] >= DISPUTE_MAX_ROUNDS:
        raise ApiError(
            "ERR_DISPUTE_ROUND_LIMIT_EXCEEDED", "The review round limit has been reached."
        )

    dispute["status"] = "INFO_REQUESTED"
    dispute["information_request_note"] = note
    touch(dispute)
    return object_response(ser.dispute_out(dispute))


@bp.post("/compliance/disputes/<identifier>/resubmit")
def resubmit_dispute(identifier):
    user_id, _role = authenticate(VENDOR)
    body = body_dict()
    claimed_reversal_cents = req_int(body, "claimed_reversal_cents", 1)
    narrative = req_str(body, "narrative", 1, 1000)

    dispute = lookup.dispute(identifier)
    if dispute["vendor_id"] != user_id:
        raise ApiError(
            "ERR_VENDOR_SCOPE_VIOLATION", "A vendor may only resubmit its own dispute."
        )
    if dispute["status"] != "INFO_REQUESTED":
        raise ApiError(
            "ERR_DISPUTE_NOT_INFO_REQUESTED",
            "Only a dispute awaiting information may be resubmitted.",
        )
    if dispute["round_count"] >= DISPUTE_MAX_ROUNDS:
        raise ApiError(
            "ERR_DISPUTE_ROUND_LIMIT_EXCEEDED", "The review round limit has been reached."
        )

    chargeback = store.chargebacks.get(dispute["chargeback_id"])
    eligible = chargeback["gross_assessed_cents"] - chargeback["reversal_cents"]
    if claimed_reversal_cents > eligible:
        raise ApiError(
            "ERR_CLAIM_EXCEEDS_ASSESSMENT",
            "claimed_reversal_cents may not exceed the amount still assessed.",
        )

    dispute["status"] = "SUBMITTED"
    dispute["claimed_reversal_cents"] = claimed_reversal_cents
    dispute["narrative"] = narrative
    dispute["round_count"] = dispute["round_count"] + 1
    dispute["information_request_note"] = None
    touch(dispute)
    return object_response(ser.dispute_out(dispute))


@bp.post("/compliance/disputes/<identifier>/decide")
def decide_dispute(identifier):
    user_id, _role = authenticate(OFFICER)
    body = body_dict()
    decision = req_enum(body, "decision", ("APPROVE", "DENY"))
    review_note = req_str(body, "review_note", 1, 1000)

    dispute = lookup.dispute(identifier)
    if dispute["status"] not in AWAITING:
        raise ApiError(
            "ERR_DISPUTE_NOT_AWAITING_DECISION", "This dispute has already been decided."
        )

    chargeback = store.chargebacks.get(dispute["chargeback_id"])
    violation = store.violations.get(chargeback["violation_id"])
    if violation is not None and violation["detected_by_user_id"] == user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The officer who detected the violation may not decide this dispute.",
        )

    vendor = store.vendors.get(chargeback["vendor_id"])
    requirement = pinned_requirement(chargeback)

    if decision == "DENY":
        outcome = {
            "reason_ceiling_pct": Decimal("0.00"),
            "goodwill_cents": 0,
            "approved_reversal_cents": 0,
            "status": "DENIED",
        }
    else:
        outcome = dispute_determination(dispute, chargeback, requirement, vendor)

    # Cascade link 1.
    dispute["status"] = outcome["status"]
    dispute["reason_ceiling_pct"] = outcome["reason_ceiling_pct"]
    dispute["goodwill_cents"] = outcome["goodwill_cents"]
    dispute["approved_reversal_cents"] = outcome["approved_reversal_cents"]
    dispute["decided_at"] = clock.now()
    dispute["decided_by_user_id"] = user_id
    dispute["review_note"] = review_note
    touch(dispute)

    # Cascade link 2.
    approved = outcome["approved_reversal_cents"]
    chargeback["reversal_cents"] = chargeback["reversal_cents"] + approved
    if outcome["status"] == "APPROVED_FULL":
        chargeback["dispute_status"] = "REVERSED"
    elif outcome["status"] == "APPROVED_PARTIAL":
        chargeback["dispute_status"] = "PARTIALLY_REVERSED"
    else:
        chargeback["dispute_status"] = "UPHELD"
    recompute_chargeback(chargeback, force_bump=True)

    # Cascade link 3.
    touched_deductions = set()
    for allocation in allocations_of_chargeback(chargeback["id"]):
        if allocation["effective_status"] != "EFFECTIVE":
            continue
        deduction_id = allocation["deduction_id"]
        if deduction_id is None or deduction_id in touched_deductions:
            continue
        touched_deductions.add(deduction_id)
        deduction = store.deductions.get(deduction_id)
        if deduction is not None:
            recompute_deduction(deduction)

    # Cascade link 4.
    if vendor is not None:
        reconcile_vendor(vendor, force_bump=approved > 0)
    return object_response(ser.dispute_out(dispute))
