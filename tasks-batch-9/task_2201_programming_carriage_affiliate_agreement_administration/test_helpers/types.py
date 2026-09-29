"""Domain types for the Carriage Affiliate Admin API.

Entity shapes, status enums and the role enum, all named exactly as the PRD
names them.
"""
from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    AFFILIATE_SALES_EXEC = "AffiliateSalesExec"
    DISTRIBUTOR_LIAISON = "DistributorLiaison"
    REVENUE_ACCOUNTANT = "RevenueAccountant"
    AUDIT_MANAGER = "AuditManager"
    RIGHTS_ADMINISTRATOR = "RightsAdministrator"
    NETWORK_ADMIN = "NetworkAdmin"


ALL_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class DistributorType(str, Enum):
    CABLE_MSO = "CABLE_MSO"
    DBS = "DBS"
    TELCO = "TELCO"
    VMVPD = "VMVPD"


class RateCardClass(str, Enum):
    CLASS_A = "CLASS_A"
    CLASS_B = "CLASS_B"
    CLASS_C = "CLASS_C"


class Tier(str, Enum):
    BASIC = "BASIC"
    EXPANDED_BASIC = "EXPANDED_BASIC"
    DIGITAL_TIER = "DIGITAL_TIER"
    PREMIUM = "PREMIUM"


class DistributorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class CreditHoldReason(str, Enum):
    NONE = "NONE"
    RECEIVABLE_LIMIT_BREACH = "RECEIVABLE_LIMIT_BREACH"
    AUDIT_RECOVERY_UNPAID = "AUDIT_RECOVERY_UNPAID"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class AgreementLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    NEGOTIATING = "NEGOTIATING"
    EXECUTED = "EXECUTED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class AgreementRenewalStatus(str, Enum):
    NOT_DUE = "NOT_DUE"
    RENEWAL_ANALYSIS = "RENEWAL_ANALYSIS"
    RENEWAL_OFFERED = "RENEWAL_OFFERED"
    RENEWED = "RENEWED"
    LAPSED = "LAPSED"


class SuspensionReason(str, Enum):
    NONE = "NONE"
    PENETRATION_BREACH = "PENETRATION_BREACH"
    DISTRIBUTOR_CREDIT_HOLD = "DISTRIBUTOR_CREDIT_HOLD"
    MANUAL_SUSPENSION = "MANUAL_SUSPENSION"


class PenetrationComplianceStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    COMPLIANT = "COMPLIANT"
    BREACH = "BREACH"


class MfnScope(str, Enum):
    DOMESTIC = "DOMESTIC"
    GLOBAL = "GLOBAL"


class MfnBenchmarkStatus(str, Enum):
    NOT_EVALUATED = "NOT_EVALUATED"
    BENCHMARKED = "BENCHMARKED"
    NO_COMPARABLE = "NO_COMPARABLE"


class MfnClauseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WAIVED = "WAIVED"


class ReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    DISPUTED = "DISPUTED"
    RESTATED = "RESTATED"
    ACCEPTED = "ACCEPTED"
    AUDIT_ADJUSTED = "AUDIT_ADJUSTED"
    SUPERSEDED = "SUPERSEDED"


class EngagementStatus(str, Enum):
    OPENED = "OPENED"
    FIELDWORK = "FIELDWORK"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    RECOVERY_INVOICED = "RECOVERY_INVOICED"
    COLLECTED = "COLLECTED"
    CLOSED_NO_FINDING = "CLOSED_NO_FINDING"


class RateBasis(str, Enum):
    PERIOD_RATE = "PERIOD_RATE"
    CLOSING_RATE = "CLOSING_RATE"


class RightsStatus(str, Enum):
    PENDING_CLEARANCE = "PENDING_CLEARANCE"
    OWNED_CLEARED = "OWNED_CLEARED"
    THIRD_PARTY_LICENSED = "THIRD_PARTY_LICENSED"
    EXPIRED_RIGHTS = "EXPIRED_RIGHTS"


class DistributionCoverageStatus(str, Enum):
    UNDISTRIBUTED = "UNDISTRIBUTED"
    LINEAR_ONLY = "LINEAR_ONLY"
    MULTIPLATFORM = "MULTIPLATFORM"
    EXCLUSIVE_UNCLEARED = "EXCLUSIVE_UNCLEARED"


class Platform(str, Enum):
    LINEAR = "LINEAR"
    VOD = "VOD"
    STREAMING = "STREAMING"
    INTERNATIONAL = "INTERNATIONAL"


class Exclusivity(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    NON_EXCLUSIVE = "NON_EXCLUSIVE"


class WindowStatus(str, Enum):
    PLANNED = "PLANNED"
    CLEARED = "CLEARED"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"


class BlockReason(str, Enum):
    NONE = "NONE"
    AGREEMENT_SUSPENDED = "AGREEMENT_SUSPENDED"
    BLACKOUT_CONFLICT = "BLACKOUT_CONFLICT"
    RIGHTS_LAPSED = "RIGHTS_LAPSED"
    MANUAL_BLOCK = "MANUAL_BLOCK"


class BlackoutStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ENFORCED = "ENFORCED"
    WAIVED = "WAIVED"
    EXPIRED = "EXPIRED"


class CommitmentType(str, Enum):
    LAUNCH_FEE = "LAUNCH_FEE"
    COOP_ADVERTISING = "COOP_ADVERTISING"
    MARKETING_SUPPORT = "MARKETING_SUPPORT"


class CommitmentStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_EARNED = "PARTIALLY_EARNED"
    EARNED = "EARNED"
    FORFEITED = "FORFEITED"
    SETTLED = "SETTLED"


class InvoiceKind(str, Enum):
    LICENSE_FEE = "LICENSE_FEE"
    AUDIT_RECOVERY = "AUDIT_RECOVERY"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"
    VOID = "VOID"


class RenewalVariant(str, Enum):
    BASE_CASE = "BASE_CASE"
    DOWNSIDE = "DOWNSIDE"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class Distributor(TypedDict):
    id: str
    legal_name: str
    distributor_type: str
    rate_card_class: str
    total_subscribers: int
    credit_limit_cents: int
    receivable_balance_cents: int
    audit_recovery_balance_cents: int
    executed_agreement_count: int
    status: str
    credit_hold_reason: str
    created_at: str
    updated_at: str
    version: int


class CarriageAgreement(TypedDict):
    id: str
    distributor_id: str
    contract_code: str
    term_start_date: str
    term_end_date: str
    base_license_fee_cents_per_sub: float
    escalator_pct: float
    penetration_floor_pct: float
    committed_tier: str
    launch_fee_cents: int
    marketing_commitment_cents: int
    lifecycle_status: str
    renewal_status: str
    negotiation_round: int
    escalated_rate_cents_per_sub: float
    effective_rate_cents_per_sub: float
    mfn_capped: bool
    penetration_compliance_status: str
    penetration_breach_count: int
    consecutive_compliant_periods: int
    recognized_revenue_cents: int
    executed_at: Optional[str]
    suspension_reason: str
    created_at: str
    updated_at: str
    version: int


class RateCardEntry(TypedDict):
    """Immutable published card row — addressable by id alone (PRD §2.4)."""
    id: str
    rate_card_class: str
    tier: str
    published_rate_cents_per_sub: float
    min_subscribers: int
    effective_from: str
    effective_to: Optional[str]


class MfnClause(TypedDict):
    id: str
    agreement_id: str
    mfn_scope: str
    min_peer_subscribers: int
    rate_floor_cents: float
    benchmark_rate_cents: Optional[float]
    benchmark_peer_agreement_id: Optional[str]
    benchmark_status: str
    last_reset_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SubscriberReport(TypedDict):
    id: str
    agreement_id: str
    period_month: str
    reported_subscribers: int
    reported_tier: str
    restatement_of_report_id: Optional[str]
    invoice_id: Optional[str]
    penetration_pct: float
    billable_subscribers: Optional[int]
    rate_applied_cents_per_sub: float
    provisional_fee_cents: int
    license_fee_due_cents: int
    audit_adjustment_cents: int
    tier_placement_breach: bool
    status: str
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditEngagement(TypedDict):
    id: str
    agreement_id: str
    sample_period_start: str
    sample_period_end: str
    rate_basis: str
    total_variance_subscribers: int
    total_reported_subscribers: int
    underreporting_pct: float
    penalty_multiplier: float
    base_recovery_cents: int
    interest_cents: int
    audit_cost_shift_cents: int
    recovery_amount_cents: int
    recovery_invoice_id: Optional[str]
    findings_issued_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict):
    """Append-only judgement record — id and created_at only (PRD §2.4)."""
    id: str
    engagement_id: str
    subscriber_report_id: str
    period_month: str
    audited_subscribers: int
    reported_subscribers: int
    variance_subscribers: int
    rate_applied_cents_per_sub: float
    finding_recovery_cents: int
    created_at: str


class ContentTitle(TypedDict):
    id: str
    title: str
    home_territory_code: str
    linear_premiere_at: str
    rights_status: str
    cleared_window_count: int
    distribution_coverage_status: str
    created_at: str
    updated_at: str
    version: int


class RightsWindow(TypedDict):
    id: str
    agreement_id: str
    content_title_id: str
    platform: str
    territory_code: str
    window_start: str
    window_end: str
    exclusivity: str
    windowing_holdback_days: int
    concurrent_licensee_count: int
    status: str
    block_reason: str
    created_at: str
    updated_at: str
    version: int


class BlackoutRule(TypedDict):
    id: str
    agreement_id: str
    territory_code: str
    blackout_start: str
    blackout_end: str
    substitution_required: bool
    substitute_content_title_id: Optional[str]
    blackout_hours: float
    monthly_blackout_hours: float
    status: str
    enforced_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MarketingCommitment(TypedDict):
    id: str
    agreement_id: str
    commitment_type: str
    committed_cents: int
    performance_deadline: str
    earned_cents: int
    earned_unbilled_cents: int
    billed_cents: int
    forfeited_cents: int
    remaining_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    distributor_id: str
    agreement_id: str
    period_month: str
    invoice_kind: str
    audit_engagement_id: Optional[str]
    gross_license_fee_cents: int
    coop_cap_pct: float
    coop_offset_cents: int
    launch_fee_offset_cents: int
    recovery_adjustment_cents: int
    net_due_cents: int
    carryforward_cents: int
    paid_cents: int
    issued_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RenewalAnalysis(TypedDict):
    """Immutable model snapshot — id and created_at only (PRD §2.4)."""
    id: str
    agreement_id: str
    variant: str
    latest_accepted_report_id: Optional[str]
    subscriber_share: float
    penetration_ratio: float
    payment_score: float
    compliance_score: float
    leverage_score: float
    distribution_loss_subscribers: int
    annualized_revenue_at_risk_cents: int
    created_at: str


class LogicalClock(TypedDict):
    """Singleton logical clock — not a versioned resource (PRD §2.4)."""
    current_utc: str
    set_count: int
