"""Domain types for the League Merch Licensing API: status enums, role enum, entity shapes.

Every enum value and field name is taken verbatim from the PRD.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1 — exactly seven recognised roles)
# ---------------------------------------------------------------------------


class Role(str, Enum):
    LEAGUE_LICENSING_MANAGER = "LeagueLicensingManager"
    MARK_COMPLIANCE_OFFICER = "MarkComplianceOfficer"
    FINANCE_CONTROLLER = "FinanceController"
    ROYALTY_AUDITOR = "RoyaltyAuditor"
    LICENSEE = "Licensee"
    CLUB_REPRESENTATIVE = "ClubRepresentative"
    PLAYER_AGENT = "PlayerAgent"


# ---------------------------------------------------------------------------
# Enumerated value sets
# ---------------------------------------------------------------------------


class MarkUsageClass(str, Enum):
    LEAGUE_ONLY = "LEAGUE_ONLY"
    LEAGUE_AND_CLUB = "LEAGUE_AND_CLUB"
    LEAGUE_CLUB_AND_PLAYER = "LEAGUE_CLUB_AND_PLAYER"


class MarkOwnerType(str, Enum):
    LEAGUE = "LEAGUE"
    CLUB = "CLUB"
    PLAYER_GROUP = "PLAYER_GROUP"
    PLAYER_INDIVIDUAL = "PLAYER_INDIVIDUAL"


class MarkUsagePlacement(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    HERITAGE = "HERITAGE"


class ChannelClass(str, Enum):
    DEPARTMENT = "DEPARTMENT"
    SPECIALTY = "SPECIALTY"
    MASS = "MASS"
    ECOMMERCE = "ECOMMERCE"
    OFF_PRICE = "OFF_PRICE"
    ALL = "ALL"


class SkuClass(str, Enum):
    HEADWEAR = "HEADWEAR"
    JERSEY = "JERSEY"
    NOVELTY = "NOVELTY"
    CONSOLE_GAME = "CONSOLE_GAME"
    TRADING_CARD = "TRADING_CARD"


class ExclusivityMode(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    NON_EXCLUSIVE = "NON_EXCLUSIVE"


class VenueType(str, Enum):
    EVENT = "EVENT"
    ONLINE = "ONLINE"


class SampleVerdict(str, Enum):
    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    FAIL = "FAIL"


class RiskIndexVariant(str, Enum):
    ROLLING_MONITOR = "ROLLING_MONITOR"
    STRICT_ASSESSMENT = "STRICT_ASSESSMENT"


class SettlementBasis(str, Enum):
    FINDINGS = "FINDINGS"
    NEGOTIATED = "NEGOTIATED"


# ---------------------------------------------------------------------------
# State machines
# ---------------------------------------------------------------------------


class LicenseeStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ClubStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class PlayerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class MarkRightStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    WITHDRAWN = "WITHDRAWN"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_SIGNATURE = "PENDING_SIGNATURE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class CompliancePosture(str, Enum):
    CLEAR = "CLEAR"
    WATCH = "WATCH"
    PROBATION = "PROBATION"
    FROZEN = "FROZEN"


class TerritoryGrantStatus(str, Enum):
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"


class ProductSubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    SAMPLE_REQUESTED = "SAMPLE_REQUESTED"
    SAMPLE_PASSED = "SAMPLE_PASSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class RetailerAuthorizationStatus(str, Enum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class RoyaltyReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    RETURNED = "RETURNED"
    ACCEPTED = "ACCEPTED"
    UNDER_AUDIT = "UNDER_AUDIT"
    ADJUSTED = "ADJUSTED"
    CLOSED = "CLOSED"


class AuditEngagementStatus(str, Enum):
    OPENED = "OPENED"
    FIELDWORK = "FIELDWORK"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"


class EnforcementActionStatus(str, Enum):
    REPORTED = "REPORTED"
    INVESTIGATING = "INVESTIGATING"
    SEIZURE_ORDERED = "SEIZURE_ORDERED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class DistributionRunStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    DISTRIBUTED = "DISTRIBUTED"


# ---------------------------------------------------------------------------
# Entity shapes
#
# Most resources carry id / created_at / updated_at / version. A SampleReview
# and a ClubDistribution are immutable once written and therefore carry only
# id and created_at (PRD §2.4).
# ---------------------------------------------------------------------------


class TierScheduleEntry(TypedDict):
    from_cents: int
    to_cents: Optional[int]
    rate_bps: int


class ProductCategory(TypedDict, total=False):
    id: str
    category_code: str
    display_name: str
    base_royalty_rate_bps: int
    tier_schedule: List[TierScheduleEntry]
    closeout_rate_bps: int
    closeout_cap_pct_bps: int
    closeout_hard_limit_bps: int
    deduction_cap_pct_bps: int
    deduction_hard_limit_bps: int
    exclusivity_allowed: bool
    minimum_guarantee_floor_cents: int
    advance_floor_bps_of_mg: int
    mark_usage_class: str
    central_licensing_default: bool
    created_at: str
    updated_at: str
    version: int


class Club(TypedDict, total=False):
    id: str
    club_code: str
    market_name: str
    revenue_share_units: int
    status: str
    lifetime_distributed_cents: int
    created_at: str
    updated_at: str
    version: int


class Player(TypedDict, total=False):
    id: str
    club_id: str
    full_name: str
    group_licensing_opt_in: bool
    individual_grant_category_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MarkRight(TypedDict, total=False):
    id: str
    mark_code: str
    owner_type: str
    club_id: Optional[str]
    player_id: Optional[str]
    usage_class: str
    royalty_share_bps: int
    status: str
    status_reason: Optional[str]
    withdrawn_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Licensee(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    home_country_code: str
    vendor_compliance_certified: bool
    status: str
    compliance_risk_index: int
    risk_index_as_of_quarter: Optional[str]
    outstanding_recovery_cents: int
    agreement_count: int
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LicenseAgreement(TypedDict, total=False):
    id: str
    licensee_id: str
    category_id: str
    exclusivity_mode: str
    minimum_guarantee_cents: int
    required_advance_cents: int
    term_start_date: str
    term_end_date: str
    central_licensing_flag: bool
    contract_status: str
    compliance_posture: str
    contract_year_start_quarter: str
    advance_paid_cents: int
    unrecouped_advance_cents: int
    recouped_advance_cents: int
    cumulative_royalty_cents: int
    mg_accrued_shortfall_cents: int
    mg_final_shortfall_cents: Optional[int]
    approved_sku_count: int
    authorized_channel_count: int
    distribution_ready: bool
    posture_as_of_quarter: Optional[str]
    countersigned_by: Optional[str]
    suspension_reason: Optional[str]
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TerritoryGrant(TypedDict, total=False):
    id: str
    agreement_id: str
    territory_code: str
    channel_class: str
    effective_from: str
    effective_to: str
    status: str
    exclusivity_mode_snapshot: str
    created_at: str
    updated_at: str
    version: int


class ApprovedMarkSnapshotEntry(TypedDict):
    mark_id: str
    mark_version: int
    usage_class: str


class ProductSubmission(TypedDict, total=False):
    id: str
    agreement_id: str
    sku_class: str
    product_name: str
    mark_ids: List[str]
    retail_price_cents: int
    sample_required: bool
    status: str
    revision_round: int
    review_hold: bool
    defect_codes: List[str]
    approved_mark_snapshot: List[ApprovedMarkSnapshotEntry]
    mark_snapshot_stale: bool
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    revocation_reason: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SampleReview(TypedDict, total=False):
    """Immutable evidence of one physical inspection: only id and created_at."""

    id: str
    submission_id: str
    verdict: str
    defect_codes: List[str]
    conditions: Optional[str]
    sample_round: int
    reviewer_user_id: str
    occurrence_quarter: str
    created_at: str


class RetailerAuthorization(TypedDict, total=False):
    id: str
    licensee_id: str
    retailer_name: str
    channel_class: str
    sku_classes: List[str]
    authorized_from: str
    authorized_to: str
    closeout_allowed: bool
    status: str
    approved_by_user_id: Optional[str]
    suspension_reason: Optional[str]
    suspended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChannelLine(TypedDict, total=False):
    channel_class: str
    retailer_authorization_id: str
    gross_sales_cents: int
    units: int
    closeout_sales_cents: int
    deductions_cents: int


class RoyaltyReport(TypedDict, total=False):
    id: str
    agreement_id: str
    period_quarter: str
    channel_lines: List[ChannelLine]
    status: str
    net_regular_total_cents: int
    closeout_eligible_total_cents: int
    applied_tier_rate_bps: int
    royalty_due_cents: int
    recoupment_applied_cents: int
    cash_due_pre_fee_cents: int
    late_days: int
    late_filing_interest_cents: int
    admin_fee_cents: int
    total_payable_cents: int
    adjusted_royalty_due_cents: Optional[int]
    audit_engagement_id: Optional[str]
    distribution_run_id: Optional[str]
    filed_at: Optional[str]
    return_reason: Optional[str]
    return_count: int
    accepted_by_user_id: Optional[str]
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditedQuarterEntry(TypedDict, total=False):
    period_quarter: str
    audited_gross_sales_cents: int
    audited_closeout_cents: int
    audited_deductions_cents: int
    recomputed_royalty_cents: int
    reported_royalty_cents: int
    underreported_cents: int


class AuditEngagement(TypedDict, total=False):
    id: str
    agreement_id: str
    scope_quarters: List[str]
    status: str
    opened_by_user_id: str
    opened_quarter: str
    audited_quarters: List[AuditedQuarterEntry]
    recomputed_royalty_cents: int
    reported_royalty_cents: int
    underreported_royalty_cents: int
    underreport_rate_bps: int
    interest_cents: int
    cost_shift_applied: bool
    audit_cost_recovery_cents: int
    recovery_assessed_cents: int
    findings_round: int
    findings_issued_by_user_id: Optional[str]
    findings_quarter: Optional[str]
    dispute_note: Optional[str]
    settlement_basis: Optional[str]
    settled_amount_cents: Optional[int]
    settled_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnforcementAction(TypedDict, total=False):
    id: str
    venue_type: str
    venue_reference: str
    target_name: str
    estimated_units: int
    estimated_retail_cents: int
    suspected_licensee_id: Optional[str]
    status: str
    seized_units: int
    recovered_cents: int
    occurrence_quarter: Optional[str]
    seizure_authority: Optional[str]
    disposition: Optional[str]
    dismissal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DistributionRun(TypedDict, total=False):
    id: str
    period_quarter: str
    league_admin_rate_bps: int
    status: str
    projected_pool_cents: int
    pool_gross_cents: int
    league_admin_cents: int
    player_pool_cents: int
    club_pool_cents: int
    report_count: int
    locked_at: Optional[str]
    distributed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClubDistribution(TypedDict, total=False):
    """Immutable evidence of one club's allocation: only id and created_at."""

    id: str
    run_id: str
    club_id: str
    club_code: str
    revenue_share_units_snapshot: int
    equal_component_cents: int
    weighted_component_cents: int
    remainder_cent_applied: int
    amount_cents: int
    created_at: str
