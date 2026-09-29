"""Domain assertions and the arithmetic the PRD specifies.

The helpers in the first block reimplement the PRD's stated formulas so tests
can assert against a derivation rather than a copied literal.  The helpers in
the second block check entity shape (common fields present / absent).  The
third block checks the two conservation identities.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    BPS_DENOMINATOR,
    DEFICIENCY_FEE_TIER1_CENTS,
    DEFICIENCY_FEE_TIER1_MAX_CENTS,
    DEFICIENCY_FEE_TIER2_CENTS,
    MONTHS_PER_YEAR,
    TIER1_MAX_AMOUNT_FINANCED_CENTS,
    TIER1_RATE_BPS,
    TIER2_MAX_AMOUNT_FINANCED_CENTS,
    TIER2_RATE_BPS,
    TIER3_RATE_BPS,
)

# ===========================================================================
# Arithmetic the PRD pins down
# ===========================================================================


def round_half_up(numerator: int, denominator: int) -> int:
    """Integer division rounded half up, as every money division requires."""
    return int(
        (Decimal(numerator) / Decimal(denominator)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def volume_tier_rate_bps(amount_financed_cents: int) -> int:
    """The volume-tier annual rate keyed on amount_financed_cents."""
    if amount_financed_cents <= TIER1_MAX_AMOUNT_FINANCED_CENTS:
        return TIER1_RATE_BPS
    if amount_financed_cents <= TIER2_MAX_AMOUNT_FINANCED_CENTS:
        return TIER2_RATE_BPS
    return TIER3_RATE_BPS


def effective_annual_rate_bps(
    amount_financed_cents: int,
    max_annual_rate_bps: int,
    approved_annual_rate_bps: Optional[int] = None,
) -> int:
    """min(approved rate or tier rate, statutory ceiling)."""
    candidate = (
        approved_annual_rate_bps
        if approved_annual_rate_bps is not None
        else volume_tier_rate_bps(amount_financed_cents)
    )
    return min(candidate, max_annual_rate_bps)


def add_on_finance_charge_cents(
    amount_financed_cents: int, rate_bps: int, installment_count: int
) -> int:
    """ADD_ON: one rounding of amount x rate x n / (10000 x 12)."""
    return round_half_up(
        amount_financed_cents * rate_bps * installment_count,
        BPS_DENOMINATOR * MONTHS_PER_YEAR,
    )


def simple_interest_periods(
    amount_financed_cents: int, rate_bps: int, installment_count: int
) -> List[int]:
    """SIMPLE_INTEREST: per-period interest on the declining balance.

    The base principal slice is floor(amount_financed / n) for every period,
    each period's interest is rounded before it is summed, and the final period
    carries the remaining principal.
    """
    base_slice = amount_financed_cents // installment_count
    outstanding = amount_financed_cents
    interest: List[int] = []
    for period in range(installment_count):
        interest.append(
            round_half_up(outstanding * rate_bps, BPS_DENOMINATOR * MONTHS_PER_YEAR)
        )
        if period == installment_count - 1:
            outstanding = 0
        else:
            outstanding -= base_slice
    return interest


def simple_interest_finance_charge_cents(
    amount_financed_cents: int, rate_bps: int, installment_count: int
) -> int:
    return sum(
        simple_interest_periods(amount_financed_cents, rate_bps, installment_count)
    )


def late_fee_cents(
    installment_amount_cents: int,
    late_fee_bps: int,
    late_fee_min_cents: int,
    late_fee_max_cents: int,
) -> int:
    """Round the raw fee first, then clamp it into the statutory band."""
    raw = round_half_up(installment_amount_cents * late_fee_bps, BPS_DENOMINATOR)
    return max(late_fee_min_cents, min(raw, late_fee_max_cents))


def rule_of_78_rebate_cents(
    finance_charge_cents: int, remaining: int, installment_count: int
) -> int:
    """round_half_up(fc x r x (r + 1) / (n x (n + 1)))."""
    return round_half_up(
        finance_charge_cents * remaining * (remaining + 1),
        installment_count * (installment_count + 1),
    )


def pro_rata_unearned_premium_cents(
    financed_premium_cents: int, unearned_days: int, term_days: int
) -> int:
    return round_half_up(financed_premium_cents * unearned_days, term_days)


def short_rate_unearned_premium_cents(
    pro_rata_cents: int, short_rate_penalty_bps: int
) -> int:
    """The penalty is applied to the already-rounded pro-rata figure."""
    return round_half_up(
        pro_rata_cents * (BPS_DENOMINATOR - short_rate_penalty_bps), BPS_DENOMINATOR
    )


def deficiency_fee_cents(pre_fee_residual_cents: int) -> int:
    """The cancellation fee tier is keyed on the residual BEFORE the fee."""
    if pre_fee_residual_cents <= 0:
        return 0
    if pre_fee_residual_cents <= DEFICIENCY_FEE_TIER1_MAX_CENTS:
        return DEFICIENCY_FEE_TIER1_CENTS
    return DEFICIENCY_FEE_TIER2_CENTS


def commission_cap_cents(total_premium_cents: int, commission_bps: int) -> int:
    return round_half_up(total_premium_cents * commission_bps, BPS_DENOMINATOR)


def level_installment_amounts(
    total_of_payments_cents: int, installment_count: int
) -> List[int]:
    """Level installments: floor base for all, exact remainder on the last."""
    base = total_of_payments_cents // installment_count
    amounts = [base] * installment_count
    amounts[-1] = total_of_payments_cents - base * (installment_count - 1)
    return amounts


def level_components(total_cents: int, installment_count: int) -> List[int]:
    """A split of `total_cents` into n rounded slices with remainder last."""
    base = round_half_up(total_cents, installment_count)
    slices = [base] * installment_count
    slices[-1] = total_cents - base * (installment_count - 1)
    return slices


# ===========================================================================
# Entity shape assertions
# ===========================================================================
def _assert_common_fields(entity: Dict[str, Any], entity_name: str) -> None:
    assert "id" in entity, f"{entity_name} must carry id"
    assert is_valid_uuid(entity["id"]), f"{entity_name}.id must be a uuid"
    assert "created_at" in entity, f"{entity_name} must carry created_at"
    assert is_iso8601_timestamp(
        entity["created_at"]
    ), f"{entity_name}.created_at must be ISO 8601, got {entity['created_at']!r}"
    assert "updated_at" in entity, f"{entity_name} must carry updated_at"
    assert is_iso8601_timestamp(
        entity["updated_at"]
    ), f"{entity_name}.updated_at must be ISO 8601, got {entity['updated_at']!r}"
    assert "version" in entity, f"{entity_name} must carry version"
    assert isinstance(
        entity["version"], int
    ), f"{entity_name}.version must be an integer"
    assert entity["version"] >= 1, f"{entity_name}.version starts at 1"


def _assert_fields_present(
    entity: Dict[str, Any], names: Iterable[str], entity_name: str
) -> None:
    for name in names:
        assert name in entity, f"{entity_name} must expose {name}"


def assert_state_rate_rule(rule: Dict[str, Any]) -> None:
    _assert_common_fields(rule, "StateRateRule")
    _assert_fields_present(
        rule,
        (
            "state_code",
            "finance_charge_method",
            "max_annual_rate_bps",
            "max_service_fee_cents",
            "min_down_payment_bps",
            "max_term_months",
            "late_fee_bps",
            "late_fee_min_cents",
            "late_fee_max_cents",
            "grace_period_days",
            "noic_notice_days",
            "unearned_premium_method",
            "short_rate_penalty_bps",
            "rebate_method",
            "max_late_fees_per_agreement",
            "license_required",
            "active_agreement_count",
        ),
        "StateRateRule",
    )


def assert_license(license_row: Dict[str, Any]) -> None:
    _assert_common_fields(license_row, "License")
    _assert_fields_present(
        license_row,
        (
            "state_rule_id",
            "license_number",
            "status",
            "effective_date",
            "expiration_date",
            "is_effective",
        ),
        "License",
    )


def assert_insured(insured: Dict[str, Any]) -> None:
    _assert_common_fields(insured, "Insured")
    _assert_fields_present(
        insured, ("legal_name", "mailing_state_code", "email"), "Insured"
    )


def assert_producer_agent(agent: Dict[str, Any]) -> None:
    _assert_common_fields(agent, "ProducerAgent")
    _assert_fields_present(
        agent,
        (
            "agency_name",
            "state_code",
            "agent_commission_bps",
            "chargeback_basis",
            "chargeback_liability_cap_cents",
            "chargeback_reserve_balance_cents",
            "outstanding_chargeback_cents",
            "status",
        ),
        "ProducerAgent",
    )


def assert_insurer(insurer: Dict[str, Any]) -> None:
    _assert_common_fields(insurer, "Insurer")
    _assert_fields_present(insurer, ("carrier_name", "naic_code", "status"), "Insurer")


def assert_agreement(agreement: Dict[str, Any]) -> None:
    _assert_common_fields(agreement, "PremiumFinanceAgreement")
    _assert_fields_present(
        agreement,
        (
            "insured_id",
            "producer_agent_id",
            "state_rule_id",
            "originated_by_user_id",
            "status",
            "delinquency_stage",
            "down_payment_cents",
            "service_fee_cents",
            "installment_count",
            "first_installment_due_date",
            "total_premium_cents",
            "amount_financed_cents",
            "effective_annual_rate_bps",
            "finance_charge_cents",
            "total_of_payments_cents",
            "quote_basis",
            "principal_balance_cents",
            "unpaid_finance_charge_cents",
            "late_fee_balance_cents",
            "late_fee_count",
            "unapplied_credit_cents",
            "unearned_premium_received_cents",
            "deficiency_balance_cents",
            "refund_due_cents",
            "agent_chargeback_cents",
            "policy_count",
            "verified_policy_count",
            "carried_over_balance_cents",
        ),
        "PremiumFinanceAgreement",
    )


def assert_financed_policy(policy: Dict[str, Any]) -> None:
    _assert_common_fields(policy, "FinancedPolicy")
    _assert_fields_present(
        policy,
        (
            "agreement_id",
            "insurer_id",
            "policy_number",
            "gross_premium_cents",
            "effective_date",
            "expiration_date",
            "min_earned_days",
            "fully_earned",
            "carried_over",
            "status",
            "verified_premium_cents",
            "verified_effective_date",
            "dispute_reason",
            "endorsed_premium_cents",
            "financed_premium_cents",
            "unearned_premium_returned_cents",
        ),
        "FinancedPolicy",
    )


def assert_premium_verification(verification: Dict[str, Any]) -> None:
    """PremiumVerification carries only id and created_at.

    It is an immutable attestation, so updated_at and version must be absent
    from the payload entirely.
    """
    assert "id" in verification, "PremiumVerification must carry id"
    assert is_valid_uuid(verification["id"]), "PremiumVerification.id must be a uuid"
    assert "created_at" in verification, "PremiumVerification must carry created_at"
    assert is_iso8601_timestamp(
        verification["created_at"]
    ), "PremiumVerification.created_at must be ISO 8601"
    assert (
        "updated_at" not in verification
    ), "PremiumVerification must not carry updated_at"
    assert "version" not in verification, "PremiumVerification must not carry version"
    _assert_fields_present(
        verification,
        (
            "policy_id",
            "party",
            "party_user_id",
            "decision",
            "effective_premium_cents",
            "effective_date_asserted",
            "superseded",
        ),
        "PremiumVerification",
    )


def assert_installment(installment: Dict[str, Any]) -> None:
    _assert_common_fields(installment, "Installment")
    _assert_fields_present(
        installment,
        (
            "agreement_id",
            "installment_number",
            "due_date",
            "amount_cents",
            "principal_component_cents",
            "finance_charge_component_cents",
            "paid_cents",
            "status",
        ),
        "Installment",
    )
    assert (
        installment["principal_component_cents"]
        + installment["finance_charge_component_cents"]
        == installment["amount_cents"]
    ), (
        "installment components must sum to the installment amount: "
        f"{installment['principal_component_cents']} + "
        f"{installment['finance_charge_component_cents']} != "
        f"{installment['amount_cents']}"
    )


def assert_payment(payment: Dict[str, Any]) -> None:
    _assert_common_fields(payment, "Payment")
    _assert_fields_present(
        payment,
        (
            "agreement_id",
            "amount_cents",
            "received_date",
            "method",
            "status",
            "applied_late_fee_cents",
            "applied_finance_charge_cents",
            "applied_principal_cents",
            "applied_unapplied_cents",
            "rebate_applied_cents",
            "allocation_variant",
        ),
        "Payment",
    )


def assert_late_fee(fee: Dict[str, Any]) -> None:
    _assert_common_fields(fee, "LateFeeAssessment")
    _assert_fields_present(
        fee,
        (
            "agreement_id",
            "installment_number",
            "assessed_date",
            "amount_cents",
            "status",
        ),
        "LateFeeAssessment",
    )


def assert_cancellation_notice(notice: Dict[str, Any]) -> None:
    _assert_common_fields(notice, "CancellationNotice")
    _assert_fields_present(
        notice,
        (
            "agreement_id",
            "issued_date",
            "issued_by_user_id",
            "notice_days",
            "effective_cancel_date",
            "past_due_amount_cents",
            "status",
        ),
        "CancellationNotice",
    )


def assert_carrier_cancellation_request(request: Dict[str, Any]) -> None:
    _assert_common_fields(request, "CarrierCancellationRequest")
    _assert_fields_present(
        request,
        (
            "agreement_id",
            "policy_id",
            "requested_date",
            "cancellation_effective_date",
            "requested_by_user_id",
            "computed_unearned_premium_cents",
            "estimate_method",
            "status",
        ),
        "CarrierCancellationRequest",
    )


def assert_premium_endorsement(endorsement: Dict[str, Any]) -> None:
    _assert_common_fields(endorsement, "PremiumEndorsement")
    _assert_fields_present(
        endorsement,
        (
            "policy_id",
            "endorsement_type",
            "amount_cents",
            "effective_date",
            "status",
            "signed_amount_cents",
        ),
        "PremiumEndorsement",
    )


def assert_agent_chargeback(chargeback: Dict[str, Any]) -> None:
    _assert_common_fields(chargeback, "AgentChargeback")
    _assert_fields_present(
        chargeback,
        (
            "producer_agent_id",
            "agreement_id",
            "amount_cents",
            "basis",
            "offset_applied_cents",
            "status",
            "reason",
        ),
        "AgentChargeback",
    )


# ===========================================================================
# Conservation identities
# ===========================================================================
def total_receivable_cents(agreement: Dict[str, Any]) -> int:
    """principal + unpaid finance charge + late fee balance - unapplied credit."""
    return (
        agreement["principal_balance_cents"]
        + agreement["unpaid_finance_charge_cents"]
        + agreement["late_fee_balance_cents"]
        - agreement["unapplied_credit_cents"]
    )


def assert_total_receivable(agreement: Dict[str, Any], expected_cents: int) -> None:
    actual = total_receivable_cents(agreement)
    assert actual == expected_cents, (
        "total_receivable_cents must equal principal_balance_cents + "
        "unpaid_finance_charge_cents + late_fee_balance_cents - "
        f"unapplied_credit_cents; expected {expected_cents}, got {actual} "
        f"(principal {agreement['principal_balance_cents']}, "
        f"unpaid fc {agreement['unpaid_finance_charge_cents']}, "
        f"fees {agreement['late_fee_balance_cents']}, "
        f"credit {agreement['unapplied_credit_cents']})"
    )


def note_settlement_residual_cents(
    total_of_payments_cents: int,
    assessed_late_fees_cents: int,
    posted_payments_cents: int,
    rebate_granted_cents: int,
    unearned_premium_received_cents: int,
    deficiency_before_fee_cents: int,
    unapplied_credit_cents: int,
) -> int:
    """The whole-life closure identity, which must be exactly 0 at settlement."""
    return (total_of_payments_cents + assessed_late_fees_cents) - (
        posted_payments_cents
        + rebate_granted_cents
        + unearned_premium_received_cents
        + deficiency_before_fee_cents
        + unapplied_credit_cents
    )


def assert_note_settlement_residual_zero(**kwargs: int) -> None:
    residual = note_settlement_residual_cents(**kwargs)
    assert residual == 0, (
        "note_settlement_residual_cents must be exactly 0 once the note is "
        f"settled, got {residual} from {kwargs}"
    )


def assert_installments_sum(
    installments: List[Dict[str, Any]],
    expected_total_of_payments: int,
    expected_finance_charge: int,
) -> None:
    total = sum(row["amount_cents"] for row in installments)
    fc = sum(row["finance_charge_component_cents"] for row in installments)
    principal = sum(row["principal_component_cents"] for row in installments)
    assert total == expected_total_of_payments, (
        "the installment amounts must sum to total_of_payments_cents: "
        f"expected {expected_total_of_payments}, got {total}"
    )
    assert fc == expected_finance_charge, (
        "the finance-charge components must sum to finance_charge_cents: "
        f"expected {expected_finance_charge}, got {fc}"
    )
    assert principal == expected_total_of_payments - expected_finance_charge, (
        "the principal components must sum to amount_financed_cents: expected "
        f"{expected_total_of_payments - expected_finance_charge}, got {principal}"
    )


def assert_no_common_field_drift(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    """A rejected write must leave version and updated_at untouched."""
    assert before["version"] == after["version"], (
        "a rejected write must not bump version: "
        f"{before['version']} -> {after['version']}"
    )
    assert before["updated_at"] == after["updated_at"], (
        "a rejected write must not restamp updated_at: "
        f"{before['updated_at']} -> {after['updated_at']}"
    )
