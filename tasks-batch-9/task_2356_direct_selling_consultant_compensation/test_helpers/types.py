"""Domain types: status enums, role enum and entity shapes for the API under test."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    APPLICANT = "Applicant"
    CONSULTANT = "Consultant"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    COMMISSION_ANALYST = "CommissionAnalyst"
    FINANCE_CONTROLLER = "FinanceController"
    LEGAL_REVIEWER = "LegalReviewer"
    PLATFORM_ADMIN = "PlatformAdmin"


class CompressionMode(str, Enum):
    DYNAMIC = "DYNAMIC"
    STATIC = "STATIC"


class TaxBasisMode(str, Enum):
    SRP = "SRP"
    NET_PRICE = "NET_PRICE"


class TaxRemitter(str, Enum):
    COMPANY = "COMPANY"
    CONSULTANT = "CONSULTANT"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class AgreementStatus(str, Enum):
    NOT_ACCEPTED = "NOT_ACCEPTED"
    ACCEPTED = "ACCEPTED"


class IdentityStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PENDING_REVIEW = "PENDING_REVIEW"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class KitStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"


class ConsultantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"
    TERMINATED = "TERMINATED"


class RankSource(str, Enum):
    ENROLLMENT = "ENROLLMENT"
    EARNED = "EARNED"
    ADMIN_ADJUSTED = "ADMIN_ADJUSTED"
    MAINTENANCE_DEMOTION = "MAINTENANCE_DEMOTION"
    REINSTATEMENT = "REINSTATEMENT"


class TerminationReason(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    ADMINISTRATIVE = "ADMINISTRATIVE"
    DISCIPLINARY = "DISCIPLINARY"


class OrderType(str, Enum):
    PERSONAL_INVENTORY = "PERSONAL_INVENTORY"
    RETAIL_CUSTOMER = "RETAIL_CUSTOMER"
    BUSINESS_SUPPLY = "BUSINESS_SUPPLY"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REFUNDED_PARTIAL = "REFUNDED_PARTIAL"
    REFUNDED_FULL = "REFUNDED_FULL"


class FulfillmentStatus(str, Enum):
    NEW = "NEW"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    RETURNED_PARTIAL = "RETURNED_PARTIAL"
    RETURNED_FULL = "RETURNED_FULL"


class PeriodStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class RunStatus(str, Enum):
    DRAFT = "DRAFT"
    CALCULATED = "CALCULATED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REVERSED = "REVERSED"


class StatementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    PAYABLE = "PAYABLE"
    CARRIED_FORWARD = "CARRIED_FORWARD"
    PAID = "PAID"
    VOIDED = "VOIDED"


class BuybackStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REFUNDED = "REFUNDED"


class BuybackCondition(str, Enum):
    RESALABLE = "RESALABLE"
    OPENED = "OPENED"
    DAMAGED = "DAMAGED"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    SANCTIONED = "SANCTIONED"
    DISMISSED = "DISMISSED"
    APPEALED = "APPEALED"


class ClaimType(str, Enum):
    INCOME_CLAIM = "INCOME_CLAIM"
    PRODUCT_CLAIM = "PRODUCT_CLAIM"
    PRICING_VIOLATION = "PRICING_VIOLATION"
    CROSS_RECRUITING = "CROSS_RECRUITING"


class SanctionLevel(str, Enum):
    WARNING = "WARNING"
    PROBATION = "PROBATION"
    SUSPENSION = "SUSPENSION"
    TERMINATION = "TERMINATION"


class DisclosureStatus(str, Enum):
    DRAFT = "DRAFT"
    LEGAL_REVIEW = "LEGAL_REVIEW"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class PopulationBasis(str, Enum):
    ALL_ENROLLED = "ALL_ENROLLED"
    PAID_ONLY = "PAID_ONLY"


class SupersedeReason(str, Enum):
    NEWER_PUBLICATION = "NEWER_PUBLICATION"
    RUN_REVERSED = "RUN_REVERSED"
    PERIOD_CORRECTION = "PERIOD_CORRECTION"


# --- Entity shapes -----------------------------------------------------------
# Every resource carries id + created_at (PRD §2.4). Almost every resource also
# carries updated_at + version; TaxJurisdiction is the single exception and
# carries neither.


class CompensationPlan(TypedDict, total=False):
    id: str
    plan_code: str
    name: str
    compression_mode: str
    point_value_cents: int
    payline_min_pv_points: int
    pv_bonus_min_points: int
    active_leg_min_points: int
    pv_bonus_bands: List[dict]
    senior_rank_bump_bp: int
    pv_bonus_cap_cents: int
    probation_keep_bp: int
    withhold_tier_threshold_cents: int
    withhold_low_bp: int
    withhold_high_bp: int
    min_payout_cents: int
    consecutive_qualifying_periods: int
    maintenance_grace_periods: int
    seventy_rule_bp: int
    buyback_rate_bp: int
    buyback_window_days: int
    restock_fee_bp: int
    restock_free_limit_cents: int
    sanction_cooloff_days: int
    appeal_window_days: int
    reinstatement_window_days: int
    max_identity_attempts: int
    flat_shipping_cents: int
    free_shipping_threshold_cents: int
    rank_ladder: List[dict]
    consultant_count: int
    created_at: str
    updated_at: str
    version: int


class TaxJurisdiction(TypedDict, total=False):
    """Immutable after creation — carries only id and created_at."""

    id: str
    state_code: str
    tax_rate_bp: int
    facilitator_agreement_active: bool
    tax_basis_mode: str
    remitter: str
    created_at: str


class Product(TypedDict, total=False):
    id: str
    sku: str
    name: str
    wholesale_price_cents: int
    srp_cents: int
    volume_points_per_unit: int
    commissionable: bool
    buyback_eligible: bool
    is_starter_kit: bool
    created_at: str
    updated_at: str
    version: int


class EnrollmentApplication(TypedDict, total=False):
    id: str
    applicant_email: str
    applicant_full_name: str
    applicant_state_code: str
    compensation_plan_id: str
    starter_kit_product_id: str
    sponsor_consultant_id: Optional[str]
    agreement_version: str
    identity_document_reference: Optional[str]
    identity_attempt_count: int
    identity_failure_reason: Optional[str]
    agreement_status: str
    identity_status: str
    kit_status: str
    status: str
    kit_charge_cents: int
    kit_tax_cents: int
    kit_total_cents: int
    kit_payment_reference: Optional[str]
    agreement_accepted_at: Optional[str]
    rejection_reason: Optional[str]
    created_consultant_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Consultant(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    state_code: str
    compensation_plan_id: str
    enrollment_application_id: str
    sponsor_consultant_id: Optional[str]
    reassigned_from_sponsor_consultant_id: Optional[str]
    upline_path: List[str]
    genealogy_depth: int
    direct_downline_count: int
    status: str
    rank_code: str
    rank_order: int
    rank_source: str
    consecutive_qualified_count: int
    grace_periods_used: int
    lifetime_commission_paid_cents: int
    carry_forward_cents: int
    clawback_balance_cents: int
    payout_hold: bool
    reinstatement_count: int
    reassignment_count: int
    open_case_count: int
    highest_sanction_order: int
    active_sanction_level: Optional[str]
    active_sanction_until: Optional[str]
    enrollment_completed_at: str
    terminated_at: Optional[str]
    termination_reason: Optional[str]
    reinstated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductOrder(TypedDict, total=False):
    id: str
    consultant_id: str
    order_type: str
    posted_period_code: str
    ship_to_state_code: str
    lines: List[dict]
    tax_basis_mode: str
    tax_remitter: str
    tax_rate_bp: int
    merchandise_subtotal_cents: int
    srp_basis_cents: int
    tax_total_cents: int
    shipping_cents: int
    total_due_cents: int
    total_volume_points: int
    commissionable_volume_points: int
    returned_volume_points: int
    refunded_cents: int
    payment_status: str
    fulfillment_status: str
    payment_reference: Optional[str]
    volume_posted: bool
    placed_at: str
    created_at: str
    updated_at: str
    version: int


class QualificationPeriod(TypedDict, total=False):
    id: str
    compensation_plan_id: str
    period_code: str
    period_start: str
    period_end: str
    status: str
    locked_at: Optional[str]
    closed_at: Optional[str]
    reopen_count: int
    correction_pending: bool
    qualification_count: int
    total_net_personal_volume_points: int
    created_at: str
    updated_at: str
    version: int


class PeriodQualification(TypedDict, total=False):
    id: str
    consultant_id: str
    qualification_period_id: str
    period_code: str
    personal_volume_points: int
    returned_volume_points: int
    net_personal_volume_points: int
    retail_volume_points: int
    inventory_volume_points: int
    group_volume_points: int
    active_leg_count: int
    attested_personal_use_points: int
    sell_through_bp: int
    qualified_rank_code: Optional[str]
    qualified_rank_order: int
    paid_as_rank_code: Optional[str]
    evaluated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommissionRun(TypedDict, total=False):
    id: str
    qualification_period_id: str
    period_code: str
    status: str
    compression_mode_snapshot: Optional[str]
    calculation_sequence: int
    calculated_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    statement_count: int
    paid_at: Optional[str]
    reversed_at: Optional[str]
    correction_flagged: bool
    gross_total_cents: int
    forfeited_to_company_cents: int
    distributable_pool_cents: int
    withheld_total_cents: int
    net_payable_total_cents: int
    paid_total_cents: int
    carry_forward_total_cents: int
    reversed_total_cents: int
    created_at: str
    updated_at: str
    version: int


class CommissionStatement(TypedDict, total=False):
    id: str
    commission_run_id: str
    consultant_id: str
    period_code: str
    calculation_sequence: int
    paid_as_rank_code: Optional[str]
    net_personal_volume_points: int
    retail_profit_cents: int
    pv_bonus_cents: int
    override_total_cents: int
    override_breakdown: List[dict]
    gross_commission_cents: int
    withhold_rate_bp: int
    withholding_cents: int
    net_payable_cents: int
    paid_cents: int
    carry_forward_cents: int
    status: str
    payout_status: str
    created_at: str
    updated_at: str
    version: int


class BuybackRequest(TypedDict, total=False):
    id: str
    consultant_id: str
    lines: List[dict]
    volume_reversal_period_code: str
    eligible_wholesale_cents: int
    requested_volume_points: int
    gross_refund_cents: int
    restocking_fee_bp: int
    restocking_fee_cents: int
    commission_clawback_cents: int
    net_refund_cents: int
    unrecovered_clawback_cents: int
    status: str
    decided_by_user_id: Optional[str]
    decision_reason: Optional[str]
    refunded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceCase(TypedDict, total=False):
    id: str
    consultant_id: str
    claim_type: str
    evidence_reference: str
    status: str
    reviewed_by_user_id: Optional[str]
    sanction_level: Optional[str]
    sanction_order: int
    effective_from: Optional[str]
    effective_until: Optional[str]
    decision_reason: Optional[str]
    appeal_deadline_at: Optional[str]
    appeal_count: int
    appeal_statement: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncomeDisclosureStatement(TypedDict, total=False):
    id: str
    commission_run_id: str
    period_code: str
    population_basis: str
    population_count: int
    total_earnings_cents: int
    mean_earnings_cents: int
    median_earnings_cents: int
    p90_earnings_cents: int
    top_decile_share_bp: int
    zero_earner_count: int
    distribution_buckets: List[dict]
    status: str
    revision_number: int
    revision_note: Optional[str]
    submitted_by_user_id: Optional[str]
    legal_reviewer_user_id: Optional[str]
    published_at: Optional[str]
    supersede_reason: Optional[str]
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
