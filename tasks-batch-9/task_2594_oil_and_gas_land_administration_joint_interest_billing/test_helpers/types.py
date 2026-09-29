"""Domain types: status enums, value enums, role enum and entity TypedDicts."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    LAND_ADMINISTRATOR = "LandAdministrator"
    JOINT_INTEREST_ACCOUNTANT = "JointInterestAccountant"
    AUDIT_REVIEWER = "AuditReviewer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PARTNER_REPRESENTATIVE = "PartnerRepresentative"


class LeaseTenureStatus(str, Enum):
    PRIMARY_TERM = "PRIMARY_TERM"
    HELD_BY_PRODUCTION = "HELD_BY_PRODUCTION"
    SHUT_IN_HELD = "SHUT_IN_HELD"
    CONTINUOUS_DEV_HELD = "CONTINUOUS_DEV_HELD"
    EXPIRED = "EXPIRED"


class LeaseObligationStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    OBLIGATION_DUE = "OBLIGATION_DUE"
    CURED = "CURED"
    IN_BREACH = "IN_BREACH"


class AllocationStatus(str, Enum):
    COMMITTED = "COMMITTED"
    WITHDRAWN = "WITHDRAWN"


class WithdrawnReason(str, Enum):
    LEASE_EXPIRED = "LEASE_EXPIRED"
    ASSIGNMENT = "ASSIGNMENT"
    OPERATOR_ELECTION = "OPERATOR_ELECTION"


class WellStatus(str, Enum):
    PROPOSED = "PROPOSED"
    DRILLING = "DRILLING"
    PRODUCING = "PRODUCING"
    SHUT_IN = "SHUT_IN"
    TEMPORARILY_ABANDONED = "TEMPORARILY_ABANDONED"
    PLUGGED = "PLUGGED"


class PoolingStatus(str, Enum):
    UNPOOLED = "UNPOOLED"
    POOLED_FORMING = "POOLED_FORMING"
    POOLED_EFFECTIVE = "POOLED_EFFECTIVE"
    POOLED_TERMINATED = "POOLED_TERMINATED"


class ProductType(str, Enum):
    OIL = "OIL"
    GAS = "GAS"


class OwnerType(str, Enum):
    WORKING_INTEREST_PARTNER = "WORKING_INTEREST_PARTNER"
    ROYALTY_OWNER = "ROYALTY_OWNER"
    OVERRIDING_ROYALTY_OWNER = "OVERRIDING_ROYALTY_OWNER"


class InterestStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    TERMINATED = "TERMINATED"


class OperationType(str, Enum):
    DRILL = "DRILL"
    COMPLETION = "COMPLETION"
    WORKOVER = "WORKOVER"
    RECOMPLETION = "RECOMPLETION"


class CostClass(str, Enum):
    CAPITAL = "CAPITAL"
    OPERATING = "OPERATING"


class AfeStatus(str, Enum):
    ELECTIONS_OPEN = "ELECTIONS_OPEN"
    FULLY_CONSENTED = "FULLY_CONSENTED"
    PARTIALLY_CONSENTED = "PARTIALLY_CONSENTED"
    FAILED = "FAILED"


class ElectionType(str, Enum):
    CONSENT = "CONSENT"
    NON_CONSENT = "NON_CONSENT"


class ElectionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    DEEMED_NON_CONSENT = "DEEMED_NON_CONSENT"
    VOIDED = "VOIDED"


class CostCategory(str, Enum):
    DRILLING = "DRILLING"
    COMPLETION = "COMPLETION"
    LEASE_OPERATING = "LEASE_OPERATING"
    WORKOVER = "WORKOVER"
    PLUGGING = "PLUGGING"


class CostStatus(str, Enum):
    ACCRUED = "ACCRUED"
    PAID = "PAID"


class CostBasis(str, Enum):
    ACCRUAL = "ACCRUAL"
    CASH = "CASH"


class ActivityClass(str, Enum):
    DRILLING = "DRILLING"
    PRODUCING = "PRODUCING"


class OverheadRateClass(str, Enum):
    FIXED_RATE = "FIXED_RATE"
    PERCENTAGE_BASIS = "PERCENTAGE_BASIS"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    ADJUSTED = "ADJUSTED"
    VOID = "VOID"


class DisputeKind(str, Enum):
    BILLING_DISPUTE = "BILLING_DISPUTE"
    AUDIT_EXCEPTION = "AUDIT_EXCEPTION"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    OPERATOR_RESPONDED = "OPERATOR_RESPONDED"
    ESCALATED = "ESCALATED"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_ADJUSTED = "RESOLVED_ADJUSTED"
    EXPIRED = "EXPIRED"


class ExchangeType(str, Enum):
    OPERATOR_RESPONSE = "OPERATOR_RESPONSE"
    PARTNER_REBUTTAL = "PARTNER_REBUTTAL"
    PARTNER_ESCALATION = "PARTNER_ESCALATION"


class ResolutionOutcome(str, Enum):
    UPHELD = "UPHELD"
    ADJUSTED = "ADJUSTED"


class DistributionStatus(str, Enum):
    ACCRUED = "ACCRUED"
    RELEASED = "RELEASED"
    SUSPENDED = "SUSPENDED"


class DisbursementStatus(str, Enum):
    ACCRUED = "ACCRUED"
    PAID = "PAID"
    SUSPENDED = "SUSPENDED"


class SuspenseReason(str, Enum):
    MISSING_TAX_ID = "MISSING_TAX_ID"
    NON_CONSENT_RECOVERY = "NON_CONSENT_RECOVERY"
    POOLING_TERMINATED = "POOLING_TERMINATED"


class InterestBasis(str, Enum):
    FROM_DUE_DATE = "FROM_DUE_DATE"
    FROM_PROCEEDS_RECEIPT = "FROM_PROCEEDS_RECEIPT"


class TransferStatus(str, Enum):
    NOTICED = "NOTICED"
    PPR_EXERCISED = "PPR_EXERCISED"
    PPR_WAIVED = "PPR_WAIVED"
    CLOSED = "CLOSED"


class PprElection(str, Enum):
    EXERCISE = "EXERCISE"
    WAIVE = "WAIVE"


class ObligationEventType(str, Enum):
    SHUT_IN_PAYMENT = "SHUT_IN_PAYMENT"
    CONTINUOUS_OPERATION = "CONTINUOUS_OPERATION"
    PRODUCTION_ESTABLISHED = "PRODUCTION_ESTABLISHED"


# --- Entity shapes ---------------------------------------------------------
# Every entity below carries id, created_at, updated_at and version, except
# JibLineItem, which carries only id and created_at.


class Lease(TypedDict):
    id: str
    lease_number: str
    lessor_name: str
    gross_acres: float
    royalty_rate: float
    primary_term_end_date: Optional[str]
    extension_option_months: int
    extension_bonus_per_acre_cents: int
    extension_exercised: bool
    extension_bonus_paid_cents: int
    shut_in_royalty_per_acre_cents: int
    shut_in_start_date: Optional[str]
    shut_in_payments_made: int
    shut_in_next_due_date: Optional[str]
    continuous_dev_window_days: int
    last_operation_end_date: Optional[str]
    continuous_dev_deadline: Optional[str]
    tenure_status: str
    obligation_status: str
    committed_acres_total: float
    held_acres: float
    created_at: str
    updated_at: str
    version: int


class WellLeaseAllocation(TypedDict):
    id: str
    well_id: str
    lease_id: str
    committed_acres: float
    allocation_factor: float
    allocation_status: str
    withdrawn_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Well(TypedDict):
    id: str
    well_name: str
    api_number: str
    product_type: str
    total_depth_ft: int
    spud_date: Optional[str]
    first_production_date: Optional[str]
    shut_in_since: Optional[str]
    well_status: str
    pooling_status: str
    allocation_factor_total: float
    consent_working_interest_pct: float
    plugging_liability_cents: int
    billed_to_date_cents: int
    created_at: str
    updated_at: str
    version: int


class InterestOwner(TypedDict):
    id: str
    owner_name: str
    owner_type: str
    contact_email: str
    tax_id_on_file: bool
    bond_posted_cents: int
    audit_window_days: int
    required_bond_cents: int
    suspense_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class WellInterest(TypedDict):
    id: str
    well_id: str
    owner_id: str
    working_interest_pct: float
    net_revenue_interest_pct: float
    effective_from: str
    effective_to: Optional[str]
    is_operator: bool
    preferential_right: bool
    interest_status: str
    non_consent_flag: bool
    non_consent_recoverable_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Afe(TypedDict):
    id: str
    well_id: str
    afe_number: str
    operation_type: str
    estimated_cost_cents: int
    cost_class: str
    election_deadline_date: str
    non_consent_penalty_multiple: float
    minimum_consent_pct: float
    afe_status: str
    consent_working_interest_pct: float
    non_consent_working_interest_pct: float
    elections_closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AfeElection(TypedDict):
    id: str
    afe_id: str
    owner_id: str
    election_type: str
    election_status: str
    wi_pct_snapshot: float
    estimated_penalty_cents: int
    submitted_at: str
    created_at: str
    updated_at: str
    version: int


class CostEntry(TypedDict):
    id: str
    well_id: str
    afe_id: Optional[str]
    cost_category: str
    cost_class: str
    amount_cents: int
    incurred_date: str
    paid_date: Optional[str]
    cost_status: str
    created_at: str
    updated_at: str
    version: int


class JibStatement(TypedDict):
    id: str
    well_id: str
    superseded_statement_id: Optional[str]
    statement_number: str
    billing_period_start: str
    billing_period_end: str
    cost_basis: str
    activity_class: str
    overhead_rate_class: str
    capital_direct_cents: int
    operating_direct_cents: int
    direct_cost_cents: int
    billable_months: int
    overhead_cents: int
    total_billed_cents: int
    prepared_by_user_id: str
    issued_at: Optional[str]
    payment_due_date: Optional[str]
    statement_status: str
    created_at: str
    updated_at: str
    version: int


class JibLineItem(TypedDict):
    """Joint interest billing line item: an immutable per-owner charge row.

    It carries no updated_at field and no version field at all.
    """
    id: str
    statement_id: str
    owner_id: str
    wi_pct_snapshot: float
    consent_normalized_wi_pct: float
    direct_capital_cents: int
    direct_operating_cents: int
    overhead_cents: int
    non_consent_reallocated_cents: int
    non_consent_withheld_cents: int
    penalty_accrued_cents: int
    rounding_residual_cents: int
    total_billed_cents: int
    created_at: str


class BillingDispute(TypedDict):
    id: str
    statement_id: str
    owner_id: str
    dispute_kind: str
    disputed_amount_cents: int
    basis_note: str
    filed_at: str
    response_due_date: str
    rebuttal_due_date: Optional[str]
    operator_responded_at: Optional[str]
    round_count: int
    dispute_status: str
    adjustment_amount_cents: Optional[int]
    resolved_by_user_id: Optional[str]
    deemed_in_favor_of_partner: bool
    created_at: str
    updated_at: str
    version: int


class ProductionRevenue(TypedDict):
    id: str
    well_id: str
    production_month: str
    gross_revenue_cents: int
    volume_units: float
    sale_date: str
    severance_tax_cents: int
    net_proceeds_cents: int
    total_royalty_cents: int
    total_disbursed_cents: int
    statutory_due_date: str
    released_at: Optional[str]
    distribution_status: str
    created_at: str
    updated_at: str
    version: int


class OwnerDisbursement(TypedDict):
    id: str
    revenue_id: str
    owner_id: str
    lease_id: str
    gross_share_cents: int
    withheld_recovery_cents: int
    net_amount_cents: int
    late_interest_cents: int
    interest_basis: Optional[str]
    paid_at: Optional[str]
    suspense_reason: Optional[str]
    disbursement_status: str
    created_at: str
    updated_at: str
    version: int


class AssignmentTransfer(TypedDict):
    id: str
    well_id: str
    assignor_owner_id: str
    assignee_owner_id: str
    ppr_holder_owner_id: Optional[str]
    transfer_wi_pct: float
    transfer_nri_pct: float
    sale_price_cents: int
    notice_date: str
    ppr_deadline_date: str
    ppr_eligible_count: int
    ppr_waiver_count: int
    bond_check_required_cents: int
    effective_date: str
    transfer_status: str
    created_at: str
    updated_at: str
    version: int
