"""TypedDict shapes and status enums for the Insurance Premium Finance API.

Every entity below carries `id` and `created_at`.  All of them except
PremiumVerification additionally carry `updated_at` and `version`;
PremiumVerification is an immutable attestation record and therefore carries
only `id` and `created_at`.
"""

from enum import Enum
from typing import Optional, TypedDict


# ===========================================================================
# Roles
# ===========================================================================
class Role(str, Enum):
    FINANCE_ANALYST = "FinanceAnalyst"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PRODUCER_AGENT = "ProducerAgent"
    INSURER = "Insurer"
    INSURED = "Insured"


# ===========================================================================
# Status / enum vocabularies
# ===========================================================================
class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    PAID_IN_FULL = "PAID_IN_FULL"
    CANCELLED_DEFICIENT = "CANCELLED_DEFICIENT"
    CLOSED_ZERO = "CLOSED_ZERO"
    RESTRUCTURED = "RESTRUCTURED"
    VOID = "VOID"


class DelinquencyStage(str, Enum):
    CURRENT = "CURRENT"
    LATE = "LATE"
    NOIC_ISSUED = "NOIC_ISSUED"
    CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
    CANCELLED = "CANCELLED"


class QuoteBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class FinanceChargeMethod(str, Enum):
    ADD_ON = "ADD_ON"
    SIMPLE_INTEREST = "SIMPLE_INTEREST"


class UnearnedPremiumMethod(str, Enum):
    PRO_RATA = "PRO_RATA"
    SHORT_RATE = "SHORT_RATE"


class RebateMethod(str, Enum):
    RULE_OF_78 = "RULE_OF_78"
    ACTUARIAL = "ACTUARIAL"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProducerAgentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED_FOR_CHARGEBACKS = "SUSPENDED_FOR_CHARGEBACKS"
    SUSPENDED_BY_COMPLIANCE = "SUSPENDED_BY_COMPLIANCE"


class ChargebackBasis(str, Enum):
    COMMISSION_CAPPED = "COMMISSION_CAPPED"
    RESERVE_CAPPED = "RESERVE_CAPPED"


class InsurerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class PolicyStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    CANCELLED = "CANCELLED"


class DisputeReason(str, Enum):
    PARTY_REJECTED = "PARTY_REJECTED"
    PREMIUM_MISMATCH = "PREMIUM_MISMATCH"
    EFFECTIVE_DATE_MISMATCH = "EFFECTIVE_DATE_MISMATCH"


class VerificationParty(str, Enum):
    INSURER = "INSURER"
    PRODUCER_AGENT = "PRODUCER_AGENT"


class VerificationDecision(str, Enum):
    CONFIRMED = "CONFIRMED"
    CORRECTED = "CORRECTED"
    REJECTED = "REJECTED"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAST_DUE = "PAST_DUE"
    PAID = "PAID"
    VOIDED = "VOIDED"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class PaymentMethod(str, Enum):
    ACH = "ACH"
    CHECK = "CHECK"
    CARD = "CARD"


class AllocationVariant(str, Enum):
    STANDARD = "STANDARD"
    PAYOFF = "PAYOFF"


class LateFeeStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    PAID = "PAID"
    WAIVED = "WAIVED"
    REVERSED = "REVERSED"


class NoticeStatus(str, Enum):
    ISSUED = "ISSUED"
    CURED = "CURED"
    EXECUTED = "EXECUTED"
    SUPERSEDED = "SUPERSEDED"


class CancelRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RETURN_POSTED = "RETURN_POSTED"
    CLOSED_NO_RETURN = "CLOSED_NO_RETURN"


class EndorsementType(str, Enum):
    ADDITIONAL_PREMIUM = "ADDITIONAL_PREMIUM"
    RETURN_PREMIUM = "RETURN_PREMIUM"


class EndorsementStatus(str, Enum):
    PENDING = "PENDING"
    FINANCED = "FINANCED"
    DECLINED = "DECLINED"


class ChargebackStatus(str, Enum):
    PENDING = "PENDING"
    PARTIALLY_OFFSET = "PARTIALLY_OFFSET"
    OFFSET = "OFFSET"


# ===========================================================================
# Entity shapes
# ===========================================================================
class StateRateRule(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    state_code: str
    finance_charge_method: str
    max_annual_rate_bps: int
    max_service_fee_cents: int
    min_down_payment_bps: int
    max_term_months: int
    late_fee_bps: int
    late_fee_min_cents: int
    late_fee_max_cents: int
    grace_period_days: int
    noic_notice_days: int
    unearned_premium_method: str
    short_rate_penalty_bps: int
    rebate_method: str
    max_late_fees_per_agreement: int
    license_required: bool
    active_agreement_count: int


class License(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    state_rule_id: str
    license_number: str
    status: str
    effective_date: str
    expiration_date: str
    is_effective: bool


class Insured(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    legal_name: str
    mailing_state_code: str
    email: str


class ProducerAgent(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    agency_name: str
    state_code: str
    agent_commission_bps: int
    chargeback_basis: str
    chargeback_liability_cap_cents: int
    chargeback_reserve_balance_cents: int
    outstanding_chargeback_cents: int
    status: str


class Insurer(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    carrier_name: str
    naic_code: str
    status: str


class PremiumFinanceAgreement(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    insured_id: str
    producer_agent_id: str
    state_rule_id: str
    restructured_from_agreement_id: Optional[str]
    originated_by_user_id: str
    status: str
    delinquency_stage: str
    down_payment_cents: int
    service_fee_cents: int
    installment_count: int
    first_installment_due_date: str
    rate_exception_approved: bool
    rate_exception_approved_by_user_id: Optional[str]
    approved_service_fee_cap_cents: Optional[int]
    approved_annual_rate_bps: Optional[int]
    total_premium_cents: int
    amount_financed_cents: int
    effective_annual_rate_bps: int
    finance_charge_cents: int
    total_of_payments_cents: int
    quote_basis: Optional[str]
    principal_balance_cents: int
    unpaid_finance_charge_cents: int
    late_fee_balance_cents: int
    late_fee_count: int
    unapplied_credit_cents: int
    unearned_premium_received_cents: int
    deficiency_balance_cents: int
    refund_due_cents: int
    agent_chargeback_cents: int
    policy_count: int
    verified_policy_count: int
    carried_over_balance_cents: int
    activated_at: Optional[str]


class FinancedPolicy(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    agreement_id: str
    insurer_id: str
    policy_number: str
    gross_premium_cents: int
    effective_date: str
    expiration_date: str
    min_earned_days: int
    fully_earned: bool
    carried_over: bool
    status: str
    verified_premium_cents: Optional[int]
    verified_effective_date: Optional[str]
    dispute_reason: Optional[str]
    endorsed_premium_cents: int
    financed_premium_cents: int
    cancellation_effective_date: Optional[str]
    earned_days: Optional[int]
    unearned_premium_estimate_cents: Optional[int]
    unearned_premium_returned_cents: int


class PremiumVerification(TypedDict):
    """Immutable attestation record: only `id` and `created_at` are carried.

    This entity has no `updated_at` and no `version`.
    """

    id: str
    created_at: str
    policy_id: str
    party: str
    party_user_id: str
    decision: str
    corrected_premium_cents: Optional[int]
    corrected_effective_date: Optional[str]
    effective_premium_cents: Optional[int]
    effective_date_asserted: Optional[str]
    note: Optional[str]
    superseded: bool


class Installment(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    agreement_id: str
    installment_number: int
    due_date: str
    amount_cents: int
    principal_component_cents: int
    finance_charge_component_cents: int
    paid_cents: int
    status: str


class Payment(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    agreement_id: str
    amount_cents: int
    received_date: str
    method: str
    status: str
    applied_late_fee_cents: int
    applied_finance_charge_cents: int
    applied_principal_cents: int
    applied_unapplied_cents: int
    rebate_applied_cents: int
    allocation_variant: str
    reversal_reason: Optional[str]
    reversed_at: Optional[str]


class LateFeeAssessment(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    agreement_id: str
    installment_number: int
    assessed_date: str
    amount_cents: int
    status: str
    waived_by_user_id: Optional[str]


class CancellationNotice(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    agreement_id: str
    issued_date: str
    issued_by_user_id: str
    notice_days: int
    effective_cancel_date: str
    past_due_amount_cents: int
    status: str
    cured_date: Optional[str]
    executed_date: Optional[str]


class CarrierCancellationRequest(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    agreement_id: str
    policy_id: str
    requested_date: str
    cancellation_effective_date: str
    requested_by_user_id: str
    computed_unearned_premium_cents: int
    estimate_method: str
    carrier_returned_cents: Optional[int]
    variance_cents: Optional[int]
    status: str


class PremiumEndorsement(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    policy_id: str
    endorsement_type: str
    amount_cents: int
    effective_date: str
    status: str
    signed_amount_cents: int
    financed_at: Optional[str]


class AgentChargeback(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    producer_agent_id: str
    agreement_id: str
    amount_cents: int
    basis: str
    offset_applied_cents: int
    status: str
    reason: str


# Entities that carry the full common-field block.
VERSIONED_ENTITIES = (
    "StateRateRule",
    "License",
    "Insured",
    "ProducerAgent",
    "Insurer",
    "PremiumFinanceAgreement",
    "FinancedPolicy",
    "Installment",
    "Payment",
    "LateFeeAssessment",
    "CancellationNotice",
    "CarrierCancellationRequest",
    "PremiumEndorsement",
    "AgentChargeback",
)

# The single entity that carries only `id` and `created_at`.
IMMUTABLE_ENTITIES = ("PremiumVerification",)
