"""Domain types for the SALT Apportionment Filing API.

Entity shapes, status enumerations and the practice role enumeration, exactly as
described in the PRD.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    TAX_MANAGER = "TaxManager"
    STATE_ANALYST = "StateAnalyst"
    CONTROLLER = "Controller"
    AUDITOR = "Auditor"


# ─── Status enumerations ──────────────────────────────────────────────────────

class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    EXPOSED = "EXPOSED"
    DELINQUENT = "DELINQUENT"


class NexusStatus(str, Enum):
    NONE = "NONE"
    PROTECTED_PL86272 = "PROTECTED_PL86272"
    ECONOMIC = "ECONOMIC"
    PHYSICAL = "PHYSICAL"
    VOLUNTARY = "VOLUNTARY"


class RegistrationStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REGISTRATION_REQUIRED = "REGISTRATION_REQUIRED"
    REGISTERED = "REGISTERED"
    WITHDRAWN = "WITHDRAWN"


class FactorFormula(str, Enum):
    EQUAL_WEIGHTED_THREE = "EQUAL_WEIGHTED_THREE"
    DOUBLE_WEIGHTED_SALES = "DOUBLE_WEIGHTED_SALES"
    SINGLE_SALES_FACTOR = "SINGLE_SALES_FACTOR"


class ThrowbackRule(str, Enum):
    THROWBACK = "THROWBACK"
    THROWOUT = "THROWOUT"
    NONE = "NONE"


class ServiceSourcingRule(str, Enum):
    MARKET_BASED = "MARKET_BASED"
    COST_OF_PERFORMANCE = "COST_OF_PERFORMANCE"


class SafeHarborBasis(str, Enum):
    PRIOR_YEAR_100 = "PRIOR_YEAR_100"
    PRIOR_YEAR_110 = "PRIOR_YEAR_110"
    CURRENT_YEAR_90 = "CURRENT_YEAR_90"


class EntityType(str, Enum):
    CORP = "CORP"
    LLC = "LLC"
    PARTNERSHIP = "PARTNERSHIP"
    DISREGARDED = "DISREGARDED"


class ElectionBasis(str, Enum):
    COMBINED_UNITARY = "COMBINED_UNITARY"
    SEPARATE_ENTITY = "SEPARATE_ENTITY"
    CONSOLIDATED = "CONSOLIDATED"


class ElectionStatus(str, Enum):
    ELECTED = "ELECTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class PreparationStatus(str, Enum):
    DRAFT = "DRAFT"
    FACTORS_LOCKED = "FACTORS_LOCKED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    FILED = "FILED"
    AMENDED = "AMENDED"


class PaymentStatusAxis(str, Enum):
    """The settlement axis of a state return."""
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERPAID = "OVERPAID"
    REFUND_CLAIMED = "REFUND_CLAIMED"


class ApportionmentVariant(str, Enum):
    JOYCE = "JOYCE"
    FINNIGAN = "FINNIGAN"


class FactorType(str, Enum):
    SALES = "SALES"
    PROPERTY = "PROPERTY"
    PAYROLL = "PAYROLL"


class ModificationDirection(str, Enum):
    ADDITION = "ADDITION"
    SUBTRACTION = "SUBTRACTION"


class CreditClaimStatus(str, Enum):
    PENDING = "PENDING"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    FULLY_APPLIED = "FULLY_APPLIED"
    CARRIED_FORWARD = "CARRIED_FORWARD"
    EXPIRED = "EXPIRED"


class EstimatedPaymentStatus(str, Enum):
    RECEIVED = "RECEIVED"
    APPLIED = "APPLIED"
    UNAPPLIED = "UNAPPLIED"
    REFUNDED = "REFUNDED"


class ExtensionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class ExtensionDecision(str, Enum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class NoticeType(str, Enum):
    MATH_ERROR = "MATH_ERROR"
    NEXUS_INQUIRY = "NEXUS_INQUIRY"
    PROPOSED_ASSESSMENT = "PROPOSED_ASSESSMENT"
    FINAL_ASSESSMENT = "FINAL_ASSESSMENT"


class NoticeStatus(str, Enum):
    OPEN = "OPEN"
    RESPONDED = "RESPONDED"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPEAL_FILED = "APPEAL_FILED"
    APPEAL_SUSTAINED = "APPEAL_SUSTAINED"
    APPEAL_DENIED = "APPEAL_DENIED"
    CLOSED = "CLOSED"


class AppealOutcome(str, Enum):
    SUSTAINED = "SUSTAINED"
    DENIED = "DENIED"


class ExposureVariant(str, Enum):
    LOOKBACK_LIMITED = "LOOKBACK_LIMITED"
    FULL_EXPOSURE = "FULL_EXPOSURE"


class VDAStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    EXECUTED = "EXECUTED"
    WITHDRAWN = "WITHDRAWN"


# ─── Entity shapes ────────────────────────────────────────────────────────────
# Every entity below carries id + created_at + updated_at + version, with the
# single exception of ActivityRecord, which is immutable and carries only id and
# created_at.

class TaxpayerGroup(TypedDict):
    id: str
    name: str
    base_state_code: str
    fiscal_year_end_month: int
    everywhere_sales: float
    everywhere_property: float
    everywhere_payroll: float
    open_registration_obligations: int
    compliance_posture: str
    nowhere_sales_pool: float
    created_at: str
    updated_at: str
    version: int


class LegalEntity(TypedDict):
    id: str
    group_id: str
    name: str
    entity_type: str
    incorporation_state_code: str
    is_unitary_member: bool
    vda_shield_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StateRegistration(TypedDict):
    id: str
    group_id: str
    state_code: str
    factor_formula: str
    tax_rate: float
    throwback_rule: str
    service_sourcing_rule: str
    economic_nexus_sales_threshold: float
    economic_nexus_employee_days_threshold: int
    nexus_status: str
    registration_status: str
    state_account_number: Optional[str]
    registered_on_date: Optional[str]
    due_month: int
    due_day: int
    extension_months: int
    estimated_installment_count: int
    safe_harbor_basis: str
    prior_year_tax: float
    current_year_estimated_tax: float
    state_permits_early_revocation: bool
    calendar_rolled_through_year: int
    total_payments_received: float
    unapplied_payment_balance: float
    created_at: str
    updated_at: str
    version: int


class ActivityRecord(TypedDict):
    """Immutable: carries only id and created_at — no updated_at, no version."""
    id: str
    registration_id: str
    legal_entity_id: str
    tax_year: int
    destination_sales: float
    origin_sales: float
    purchaser_taxable_in_state: bool
    service_receipts: float
    cost_of_performance_state_code: Optional[str]
    property_average_value: float
    rented_property_annual_rent: float
    payroll_compensation: float
    employee_days_in_state: int
    protected_solicitation_only: bool
    created_at: str


class FilingElection(TypedDict):
    id: str
    registration_id: str
    election_basis: str
    effective_tax_year: int
    binding_years: int
    expires_after_tax_year: int
    status: str
    revocation_tax_year: Optional[int]
    reinstatement_count: int
    reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StateFiling(TypedDict):
    id: str
    registration_id: str
    election_id: Optional[str]
    primary_legal_entity_id: Optional[str]
    tax_year: int
    filing_basis: str
    federal_taxable_income: float
    apportionment_variant: Optional[str]
    preparation_status: str
    payment_status: str
    apportionment_percentage: float
    modification_total: float
    state_taxable_income: float
    tax_before_credits: float
    credits_applied_total: float
    estimated_credits_applied: float
    assessment_added_total: float
    balance_due: float
    original_due_date: str
    extended_due_date: Optional[str]
    preparer_user_id: Optional[str]
    approver_user_id: Optional[str]
    confirmation_number: Optional[str]
    filed_on_date: Optional[str]
    amendment_count: int
    created_at: str
    updated_at: str
    version: int


class ApportionmentFactor(TypedDict):
    id: str
    filing_id: str
    factor_type: str
    numerator: float
    denominator: float
    ratio: float
    weight: float
    included: bool
    throwback_added: float
    throwout_removed: float
    created_at: str
    updated_at: str
    version: int


class Modification(TypedDict):
    id: str
    filing_id: str
    modification_code: str
    direction: str
    raw_amount: float
    allocation_ratio: float
    line_amount: float
    sequence_number: int
    created_at: str
    updated_at: str
    version: int


class CreditClaim(TypedDict):
    id: str
    filing_id: str
    credit_code: str
    granted_amount: float
    refundable: bool
    priority_order: int
    expires_after_years: int
    applied_amount: float
    carryforward_amount: float
    expired_amount: float
    status: str
    created_at: str
    updated_at: str
    version: int


class EstimatedPayment(TypedDict):
    id: str
    registration_id: str
    applied_filing_id: Optional[str]
    tax_year: int
    installment_number: int
    amount: float
    paid_on_date: str
    due_date: str
    is_timely: bool
    safe_harbor_required_amount: float
    underpayment_amount: float
    underpayment_penalty: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ExtensionRequest(TypedDict):
    id: str
    filing_id: str
    estimated_tax_paid: float
    requested_on_date: str
    required_prepayment: float
    status: str
    new_due_date: Optional[str]
    state_confirmation: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Notice(TypedDict):
    id: str
    filing_id: str
    notice_type: str
    state_notice_number: str
    assessed_tax: float
    notice_date: str
    response_due_days: int
    response_due_date: str
    appeal_due_date: str
    status: str
    response_round: int
    contested_amount: float
    sustained_amount: float
    penalty_amount: float
    interest_amount: float
    assessment_final_amount: float
    created_at: str
    updated_at: str
    version: int


class VDAAgreement(TypedDict):
    id: str
    registration_id: str
    legal_entity_id: str
    anchor_tax_year: int
    lookback_years: int
    exposure_variant: str
    estimated_exposure_tax: float
    effective_lookback_years: int
    lookback_start_year: int
    lookback_end_year: int
    computed_exposure_tax: float
    waived_penalty_amount: float
    negotiated_tax: Optional[float]
    negotiated_interest: float
    settlement_total: float
    status: str
    executed_on_date: Optional[str]
    shield_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


ALL_ROLES: List[str] = [
    UserRole.TAX_MANAGER.value,
    UserRole.STATE_ANALYST.value,
    UserRole.CONTROLLER.value,
    UserRole.AUDITOR.value,
]
