"""Lookups, derived counters, serialisers and cascades.

Derived fields (PRD 2.7: "fully recomputed on every write that could change
them ... Full recomputation, rather than incremental adjustment, is required so
that no arithmetic drift can accumulate") are computed from the store whenever
they are read, which makes drift structurally impossible.
"""

from calc import claim_net_payable
from errors import fail
from store import (
    date_to_str,
    day_count,
    fmt_dt,
    now_iso,
    parse_date,
    sort_rows,
    store,
    touch,
)

LINES = ("PERSONAL_AUTO", "HOMEOWNERS", "COMMERCIAL_GENERAL_LIABILITY", "WORKERS_COMPENSATION")

INSOLVENCY_STATUSES = ("DECLARED", "TRIGGERED", "CLOSED")
POLICY_STATUSES = ("IMPORTED", "CANCELLED_BY_ORDER", "EXPIRED_BEFORE_ORDER")
TRANSFER_STATUSES = ("RECEIVED", "CONVERTED", "PARTIALLY_CONVERTED", "REJECTED")
CLAIM_STATUSES = (
    "RECEIVED",
    "SCREENED_ELIGIBLE",
    "DENIED_NOT_COVERED",
    "ADJUSTING",
    "RECOMMENDED",
    "REFERRAL_PENDING",
    "REFERRED_OUT",
    "APPROVED",
    "PARTIALLY_PAID",
    "PAID",
)
OIC_STATUSES = ("UNEXHAUSTED", "PURSUING", "EXHAUSTED", "CARRIER_DENIED")
VENDOR_STATUSES = ("ASSIGNED", "SUPERSEDED", "CLOSED")
VENDOR_TYPES = ("ADJUSTER", "DEFENSE_COUNSEL")
REFUND_STATUSES = ("PENDING", "PARTIALLY_PAID", "PAID")
REFUND_METHODS = ("PRO_RATA", "SHORT_RATE")
REFERRAL_STATUSES = ("OPEN", "ACCEPTED", "DECLINED")
REFERRAL_BASES = ("POLICYHOLDER_RESIDENCE", "CLAIMANT_RESIDENCE", "PROPERTY_LOCATION")
ASSESSMENT_STATUSES = ("DRAFT", "CERTIFIED", "SETTLED")
BILLING_STATUSES = ("INVOICED", "PARTIALLY_PAID", "PAID", "DELINQUENT")
RECOUPMENT_STATUSES = ("NOT_STARTED", "SURCHARGE_FILED", "RECOUPING", "RECOUPED")
ACCOUNT_STATUSES = ("ACTIVE", "IMPAIRED", "WITHDRAWN")
COVERAGE_TYPES = ("PRIMARY", "EXCESS", "UMBRELLA")
CAP_ORDER_MODES = ("OFFSET_THEN_CAP", "CAP_THEN_OFFSET")

# claim statuses that block closing the insolvency file (PRD 2.8 rule 40)
CLAIMS_OUTSTANDING_STATUSES = (
    "RECEIVED",
    "SCREENED_ELIGIBLE",
    "ADJUSTING",
    "RECOMMENDED",
    "REFERRAL_PENDING",
    "APPROVED",
    "PARTIALLY_PAID",
)


# --------------------------------------------------------------------------
# path-identifier lookups (PRD 2.8 priorities 6-11.5)
# --------------------------------------------------------------------------
def get_insolvency(insolvency_id):
    row = store.insolvencies.get(insolvency_id)
    if row is None:
        fail("ERR_INSOLVENCY_NOT_FOUND", "No insolvency file matches id '%s'." % insolvency_id)
    return row


def get_claim(claim_id):
    row = store.claims.get(claim_id)
    if row is None:
        fail("ERR_CLAIM_NOT_FOUND", "No covered claim matches id '%s'." % claim_id)
    return row


def get_policy(policy_id):
    row = store.policies.get(policy_id)
    if row is None:
        fail("ERR_POLICY_NOT_FOUND", "No transferred policy matches id '%s'." % policy_id)
    return row


def get_transfer(transfer_id):
    row = store.poc_transfers.get(transfer_id)
    if row is None:
        fail("ERR_TRANSFER_NOT_FOUND", "No proof-of-claim batch matches id '%s'." % transfer_id)
    return row


def get_assessment(assessment_id):
    row = store.assessments.get(assessment_id)
    if row is None:
        fail("ERR_ASSESSMENT_NOT_FOUND", "No assessment matches id '%s'." % assessment_id)
    return row


def get_member_assessment(member_assessment_id):
    row = store.member_assessments.get(member_assessment_id)
    if row is None:
        fail(
            "ERR_MEMBER_ASSESSMENT_NOT_FOUND",
            "No member assessment invoice matches id '%s'." % member_assessment_id,
        )
    return row


def get_member_insurer(member_insurer_id):
    row = store.member_insurers.get(member_insurer_id)
    if row is None:
        fail(
            "ERR_MEMBER_INSURER_NOT_FOUND",
            "No member insurer matches id '%s'." % member_insurer_id,
        )
    return row


def profile_for_line(line_of_business):
    for row in store.coverage_profiles.values():
        if row["line_of_business"] == line_of_business:
            return row
    return None


# --------------------------------------------------------------------------
# collection helpers
# --------------------------------------------------------------------------
def policies_of_insolvency(insolvency_id):
    return [p for p in store.policies.values() if p["insolvency_id"] == insolvency_id]


def claims_of_insolvency(insolvency_id):
    return [c for c in store.claims.values() if c["insolvency_id"] == insolvency_id]


def claims_of_policy(policy_id):
    return [c for c in store.claims.values() if c["policy_id"] == policy_id]


def refunds_of_policy(policy_id):
    return [r for r in store.refunds.values() if r["policy_id"] == policy_id]


def refunds_of_insolvency(insolvency_id):
    policy_ids = set(p["id"] for p in policies_of_insolvency(insolvency_id))
    return [r for r in store.refunds.values() if r["policy_id"] in policy_ids]


def assignments_of_claim(claim_id):
    return [v for v in store.vendor_assignments.values() if v["claim_id"] == claim_id]


def assignments_of_insolvency(insolvency_id):
    claim_ids = set(c["id"] for c in claims_of_insolvency(insolvency_id))
    return [v for v in store.vendor_assignments.values() if v["claim_id"] in claim_ids]


def layers_of_claim(claim_id):
    return [o for o in store.other_insurance.values() if o["claim_id"] == claim_id]


def referrals_of_claim(claim_id):
    return [r for r in store.referrals.values() if r["claim_id"] == claim_id]


def assessments_of_insolvency(insolvency_id):
    return [a for a in store.assessments.values() if a["insolvency_id"] == insolvency_id]


def invoices_of_assessment(assessment_id):
    return [m for m in store.member_assessments.values() if m["assessment_id"] == assessment_id]


def invoices_of_member(member_insurer_id):
    return [
        m for m in store.member_assessments.values() if m["member_insurer_id"] == member_insurer_id
    ]


def insolvency_of_claim(claim):
    return store.insolvencies.get(claim["insolvency_id"])


def insolvency_of_policy(policy):
    return store.insolvencies.get(policy["insolvency_id"])


# --------------------------------------------------------------------------
# derived aggregates
# --------------------------------------------------------------------------
def other_insurance_recoverable(claim_id):
    """Sum of recovered_cents over layers in EXHAUSTED or CARRIER_DENIED (PRD 3.5)."""
    total = 0
    for layer in layers_of_claim(claim_id):
        if layer["status"] in ("EXHAUSTED", "CARRIER_DENIED"):
            total += int(layer.get("recovered_cents") or 0)
    return total


def aggregate_paid_cents(policy_id, exclude_claim_id=None):
    """Sum of net_payable_cents over sibling claims in APPROVED/PARTIALLY_PAID/PAID."""
    total = 0
    for claim in claims_of_policy(policy_id):
        if exclude_claim_id is not None and claim["id"] == exclude_claim_id:
            continue
        if claim["status"] in ("APPROVED", "PARTIALLY_PAID", "PAID"):
            total += int(claim.get("net_payable_cents") or 0)
    return total


def up_refund_filed(policy_id):
    return len(refunds_of_policy(policy_id)) > 0


def administrative_expense_cents(insolvency_id):
    total = 0
    for assignment in assignments_of_insolvency(insolvency_id):
        total += int(assignment.get("fees_accrued_cents") or 0)
    return total


def reserved_claim_cents(insolvency_id):
    total = 0
    for claim in claims_of_insolvency(insolvency_id):
        if claim["status"] in ("APPROVED", "PARTIALLY_PAID"):
            total += int(claim.get("net_payable_cents") or 0) - int(
                claim.get("paid_amount_cents") or 0
            )
    return total


def pending_up_liability_cents(insolvency_id):
    total = 0
    for refund in refunds_of_insolvency(insolvency_id):
        if refund["status"] in ("PENDING", "PARTIALLY_PAID"):
            total += int(refund.get("computed_refund_cents") or 0) - int(
                refund.get("paid_amount_cents") or 0
            )
    return total


def referral_pending_count(insolvency_id):
    return len(
        [c for c in claims_of_insolvency(insolvency_id) if c["status"] == "REFERRAL_PENDING"]
    )


def assessment_shortfall_cents(insolvency_id):
    total = 0
    for assessment in assessments_of_insolvency(insolvency_id):
        if assessment["status"] in ("CERTIFIED", "SETTLED"):
            total += int(assessment.get("shortfall_cents") or 0)
    return total


def collected_amount_cents(assessment_id):
    total = 0
    for invoice in invoices_of_assessment(assessment_id):
        total += int(invoice.get("paid_amount_cents") or 0)
    return total


def estate_undistributed_cents(insolvency):
    return (
        int(insolvency["estate_remitted_cents"])
        - int(insolvency["estate_distributed_cents"])
        - int(insolvency["estate_returned_cents"])
    )


# --------------------------------------------------------------------------
# claim payable recompute (calculation 1)
# --------------------------------------------------------------------------
def recompute_claim_payable(claim):
    """Re-run claim_net_payable and write the computed terms onto the claim row."""
    policy = store.policies.get(claim["policy_id"])
    if policy is None:
        return None
    profile = profile_for_line(policy["line_of_business"])
    result = claim_net_payable(
        claim,
        policy,
        profile,
        other_insurance_recoverable(claim["id"]),
        aggregate_paid_cents(policy["id"], exclude_claim_id=claim["id"]),
    )
    claim["covered_basis_cents"] = result["covered_basis_cents"]
    claim["attachment_point_cents"] = result["attachment_point_cents"]
    claim["covered_layer_cents"] = result["covered_layer_cents"]
    claim["net_payable_cents"] = result["net_payable_cents"]
    claim["alt_net_payable_cents"] = result["alt_net_payable_cents"]
    claim["cap_binding"] = result["cap_binding"]
    return result


def claim_payable_terms(claim):
    """Live evaluation of the intermediate terms, used by the settlement worksheet."""
    policy = store.policies.get(claim["policy_id"])
    if policy is None:
        return None
    profile = profile_for_line(policy["line_of_business"])
    return claim_net_payable(
        claim,
        policy,
        profile,
        other_insurance_recoverable(claim["id"]),
        aggregate_paid_cents(policy["id"], exclude_claim_id=claim["id"]),
    )


def close_assigned_vendor_assignments(claim_id):
    """PRD 3.6: a claim entering DENIED_NOT_COVERED, REFERRED_OUT or PAID closes
    every engagement still in ASSIGNED, freezing fees_accrued_cents."""
    for assignment in assignments_of_claim(claim_id):
        if assignment["status"] == "ASSIGNED":
            assignment["status"] = "CLOSED"
            touch(assignment)


# --------------------------------------------------------------------------
# serialisers
# --------------------------------------------------------------------------
def _common(row, include_version=True):
    out = {"id": row["id"], "created_at": row["created_at"]}
    if include_version:
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    return out


def serialize_coverage_profile(row):
    # PRD 2.4: the configuration row carries only id and created_at.
    out = _common(row, include_version=False)
    out.update(
        {
            "line_of_business": row["line_of_business"],
            "per_claim_cap_cents": row["per_claim_cap_cents"],
            "per_policy_aggregate_cap_cents": row["per_policy_aggregate_cap_cents"],
            "unearned_premium_cap_cents": row["unearned_premium_cap_cents"],
            "statutory_deductible_cents": row["statutory_deductible_cents"],
            "net_worth_exclusion_threshold_cents": row["net_worth_exclusion_threshold_cents"],
            "covers_punitive_damages": row["covers_punitive_damages"],
            "refund_priority_class": row["refund_priority_class"],
            "cap_order_mode": row["cap_order_mode"],
        }
    )
    return out


def serialize_insolvency(row):
    out = _common(row)
    out.update(
        {
            "insurer_name": row["insurer_name"],
            "naic_code": row["naic_code"],
            "domiciliary_state_code": row["domiciliary_state_code"],
            "liquidation_order_date": row["liquidation_order_date"],
            "coverage_termination_date": row["coverage_termination_date"],
            "proof_of_claim_deadline_utc": row["proof_of_claim_deadline_utc"],
            "status": row["status"],
            "triggered_at_utc": row["triggered_at_utc"],
            "estate_remitted_cents": row["estate_remitted_cents"],
            "estate_distributed_cents": row["estate_distributed_cents"],
            "estate_undistributed_cents": estate_undistributed_cents(row),
            "estate_returned_cents": row["estate_returned_cents"],
            "administrative_expense_cents": administrative_expense_cents(row["id"]),
            "administrative_paid_cents": row["administrative_paid_cents"],
            "reserved_claim_cents": reserved_claim_cents(row["id"]),
            "pending_up_liability_cents": pending_up_liability_cents(row["id"]),
            "referral_pending_count": referral_pending_count(row["id"]),
            "assessment_shortfall_cents": assessment_shortfall_cents(row["id"]),
            "distribution_sequence": row["distribution_sequence"],
            "policy_count": len(policies_of_insolvency(row["id"])),
        }
    )
    return out


def serialize_member_insurer(row):
    out = _common(row)
    out.update(
        {
            "naic_code": row["naic_code"],
            "insurer_name": row["insurer_name"],
            "assessable_line": row["assessable_line"],
            "base_year": row["base_year"],
            "direct_written_premium_cents": row["direct_written_premium_cents"],
            "annual_cap_rate_bps": row["annual_cap_rate_bps"],
            "account_status": row["account_status"],
            "sequence": row["sequence"],
        }
    )
    return out


def serialize_assessment(row):
    out = _common(row)
    out.update(
        {
            "insolvency_id": row["insolvency_id"],
            "assessable_line": row["assessable_line"],
            "base_year": row["base_year"],
            "needed_amount_cents": row["needed_amount_cents"],
            "status": row["status"],
            "levied_amount_cents": row["levied_amount_cents"],
            "shortfall_cents": row["shortfall_cents"],
            "member_count": row["member_count"],
            "collected_amount_cents": collected_amount_cents(row["id"]),
            "certified_at_utc": row["certified_at_utc"],
        }
    )
    return out


def serialize_member_assessment(row):
    out = _common(row)
    out.update(
        {
            "assessment_id": row["assessment_id"],
            "member_insurer_id": row["member_insurer_id"],
            "premium_base_cents": row["premium_base_cents"],
            "cap_amount_cents": row["cap_amount_cents"],
            "levied_amount_cents": row["levied_amount_cents"],
            "paid_amount_cents": row["paid_amount_cents"],
            "capped": row["capped"],
            "billing_status": row["billing_status"],
            "recoupment_status": row["recoupment_status"],
            "surcharge_rate_bps": row["surcharge_rate_bps"],
            "surcharge_base_cents": row["surcharge_base_cents"],
            "projected_recoupment_cents": row["projected_recoupment_cents"],
            "recouped_amount_cents": row["recouped_amount_cents"],
            "sequence": row["sequence"],
        }
    )
    return out


def serialize_transfer(row):
    out = _common(row)
    out.update(
        {
            "insolvency_id": row["insolvency_id"],
            "receiver_batch_ref": row["receiver_batch_ref"],
            "records": row["records"],
            "record_count": row["record_count"],
            "converted_count": row["converted_count"],
            "rejected_count": row["rejected_count"],
            "rejection_reasons": row["rejection_reasons"],
            "status": row["status"],
        }
    )
    return out


def serialize_policy(row):
    out = _common(row)
    out.update(
        {
            "insolvency_id": row["insolvency_id"],
            "source_transfer_id": row["source_transfer_id"],
            "policy_number": row["policy_number"],
            "line_of_business": row["line_of_business"],
            "policyholder_name": row["policyholder_name"],
            "policyholder_state_code": row["policyholder_state_code"],
            "policyholder_net_worth_cents": row["policyholder_net_worth_cents"],
            "effective_date": row["effective_date"],
            "expiration_date": row["expiration_date"],
            "annual_premium_cents": row["annual_premium_cents"],
            "large_deductible_cents": row["large_deductible_cents"],
            "self_insured_retention_cents": row["self_insured_retention_cents"],
            "collateral_held_cents": row["collateral_held_cents"],
            "status": row["status"],
            "cancellation_date": row["cancellation_date"],
            "unexpired_days": row["unexpired_days"],
            "aggregate_paid_cents": aggregate_paid_cents(row["id"]),
            "up_refund_filed": up_refund_filed(row["id"]),
        }
    )
    return out


def serialize_claim(row):
    out = _common(row)
    out.update(
        {
            "insolvency_id": row["insolvency_id"],
            "policy_id": row["policy_id"],
            "source_transfer_id": row["source_transfer_id"],
            "claim_number": row["claim_number"],
            "claimant_name": row["claimant_name"],
            "claimant_state_code": row["claimant_state_code"],
            "loss_date": row["loss_date"],
            "filed_at_utc": row["filed_at_utc"],
            "gross_loss_cents": row["gross_loss_cents"],
            "punitive_damages_cents": row["punitive_damages_cents"],
            "covered_basis_cents": row["covered_basis_cents"],
            "other_insurance_recoverable_cents": other_insurance_recoverable(row["id"]),
            "attachment_point_cents": row["attachment_point_cents"],
            "covered_layer_cents": row["covered_layer_cents"],
            "net_payable_cents": row["net_payable_cents"],
            "alt_net_payable_cents": row["alt_net_payable_cents"],
            "cap_binding": row["cap_binding"],
            "paid_amount_cents": row["paid_amount_cents"],
            "status": row["status"],
            "screened_by_user_id": row["screened_by_user_id"],
            "approved_by_user_id": row["approved_by_user_id"],
            "recommended_by_vendor_name": row["recommended_by_vendor_name"],
            "recommended_amount_cents": row["recommended_amount_cents"],
            "recommended_at_utc": row["recommended_at_utc"],
            "remand_count": row["remand_count"],
            "pre_referral_status": row["pre_referral_status"],
            "referred_to_state_code": row["referred_to_state_code"],
            "denial_reason": row["denial_reason"],
            "sequence": row["sequence"],
        }
    )
    return out


def serialize_layer(row):
    out = _common(row)
    out.update(
        {
            "claim_id": row["claim_id"],
            "carrier_name": row["carrier_name"],
            "policy_number": row["policy_number"],
            "coverage_type": row["coverage_type"],
            "stated_limit_cents": row["stated_limit_cents"],
            "recovered_cents": row["recovered_cents"],
            "status": row["status"],
            "sequence": row["sequence"],
        }
    )
    return out


def serialize_assignment(row):
    out = _common(row)
    out.update(
        {
            "claim_id": row["claim_id"],
            "vendor_type": row["vendor_type"],
            "vendor_name": row["vendor_name"],
            "settlement_authority_cents": row["settlement_authority_cents"],
            "hourly_rate_cents": row["hourly_rate_cents"],
            "engagement_start": row["engagement_start"],
            "engagement_end": row["engagement_end"],
            "hours_logged": row["hours_logged"],
            "fees_accrued_cents": row["fees_accrued_cents"],
            "status": row["status"],
        }
    )
    return out


def serialize_refund(row):
    out = _common(row)
    out.update(
        {
            "policy_id": row["policy_id"],
            "refund_method": row["refund_method"],
            "computed_refund_cents": row["computed_refund_cents"],
            "alt_refund_cents": row["alt_refund_cents"],
            "capped": row["capped"],
            "priority_class": row["priority_class"],
            "paid_amount_cents": row["paid_amount_cents"],
            "status": row["status"],
            "sequence": row["sequence"],
        }
    )
    return out


def serialize_referral(row):
    out = _common(row)
    out.update(
        {
            "claim_id": row["claim_id"],
            "target_state_code": row["target_state_code"],
            "basis": row["basis"],
            "basis_state_code": row["basis_state_code"],
            "status": row["status"],
            "response_note": row["response_note"],
            "responded_at_utc": row["responded_at_utc"],
        }
    )
    return out


# --------------------------------------------------------------------------
# small shared date helpers
# --------------------------------------------------------------------------
def policy_term_days(policy):
    start = parse_date(policy["effective_date"])
    end = parse_date(policy["expiration_date"])
    if start is None or end is None:
        return 0
    return day_count(start, end)


__all__ = [name for name in dir() if not name.startswith("_")]
