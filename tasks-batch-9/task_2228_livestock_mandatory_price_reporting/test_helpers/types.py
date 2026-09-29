"""Domain types for the Livestock Mandatory Price Reporting API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    REPORTER_AGENT = "ReporterAgent"
    PROGRAM_ADMIN = "ProgramAdmin"
    MARKET_ANALYST = "MarketAnalyst"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"
    PENALTY_OFFICER = "PenaltyOfficer"
    PUBLIC_USER = "PublicUser"


# ---------------------------------------------------------------------------
# Enumerated inputs (PRD §2.9, §3.1–§3.9)
# ---------------------------------------------------------------------------


class EntityType(str, Enum):
    PACKER = "PACKER"
    PACKER_PROCESSOR = "PACKER_PROCESSOR"
    IMPORTER = "IMPORTER"


class Species(str, Enum):
    CATTLE = "CATTLE"
    SWINE = "SWINE"
    LAMB = "LAMB"


class PlantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    IDLE = "IDLE"
    CLOSED = "CLOSED"


class BasisVariant(str, Enum):
    FIVE_YEAR_AVERAGE = "FIVE_YEAR_AVERAGE"
    PRIOR_YEAR_ACTUAL = "PRIOR_YEAR_ACTUAL"


class RegistrationStatus(str, Enum):
    DRAFT = "DRAFT"
    DETERMINED = "DETERMINED"
    UNDER_APPEAL = "UNDER_APPEAL"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class DeterminationOutcome(str, Enum):
    MANDATORY = "MANDATORY"
    EXEMPT = "EXEMPT"


class SuspendedReason(str, Enum):
    ADMIN_ACTION = "ADMIN_ACTION"
    DELINQUENCY_TIER_BREACH = "DELINQUENCY_TIER_BREACH"


class ReportClass(str, Enum):
    LIVE_ANIMAL = "LIVE_ANIMAL"
    BOXED_BEEF = "BOXED_BEEF"
    WHOLESALE_CUTS = "WHOLESALE_CUTS"


class WindowFrequency(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"


class ReportingWindowStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    PUBLISHED = "PUBLISHED"


class SubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNDER_CORRECTION = "UNDER_CORRECTION"
    RESUBMITTED = "RESUBMITTED"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class ReviewDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class PurchaseType(str, Enum):
    NEGOTIATED = "NEGOTIATED"
    NEGOTIATED_GRID = "NEGOTIATED_GRID"
    FORMULA = "FORMULA"
    FORWARD_CONTRACT = "FORWARD_CONTRACT"
    PACKER_OWNED = "PACKER_OWNED"


class ProductClass(str, Enum):
    BOXED_BEEF_CHOICE_CUTOUT = "BOXED_BEEF_CHOICE_CUTOUT"
    BOXED_BEEF_SELECT_CUTOUT = "BOXED_BEEF_SELECT_CUTOUT"
    GROUND_BEEF = "GROUND_BEEF"
    TRIMMINGS = "TRIMMINGS"


class SaleType(str, Enum):
    NEGOTIATED = "NEGOTIATED"
    FORMULA_NET = "FORMULA_NET"
    DELIVERED = "DELIVERED"


class ReportCategory(str, Enum):
    LIVE_STEER_HEIFER = "LIVE_STEER_HEIFER"
    LIVE_COW_BULL = "LIVE_COW_BULL"
    BOXED_BEEF_CUTOUT = "BOXED_BEEF_CUTOUT"
    WHOLESALE_PORK_CUTS = "WHOLESALE_PORK_CUTS"


class WeightingVariant(str, Enum):
    HEAD_WEIGHTED = "HEAD_WEIGHTED"
    WEIGHT_WEIGHTED = "WEIGHT_WEIGHTED"


class PurchaseTypeFilter(str, Enum):
    ALL_PRICED = "ALL_PRICED"
    NEGOTIATED_ONLY = "NEGOTIATED_ONLY"


class AggregationState(str, Enum):
    PENDING = "PENDING"
    COMPUTED = "COMPUTED"
    STALE = "STALE"


class DisclosureState(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    CLEARED = "CLEARED"
    WITHHELD = "WITHHELD"


class PublicationState(str, Enum):
    UNPUBLISHED = "UNPUBLISHED"
    PUBLISHED = "PUBLISHED"
    WITHDRAWN = "WITHDRAWN"


class SuppressionReason(str, Enum):
    NO_ELIGIBLE_DATA = "NO_ELIGIBLE_DATA"
    INSUFFICIENT_REPORTERS = "INSUFFICIENT_REPORTERS"
    DOMINANT_REPORTER = "DOMINANT_REPORTER"
    INSUFFICIENT_VOLUME = "INSUFFICIENT_VOLUME"


class AuditCaseStatus(str, Enum):
    OPEN = "OPEN"
    FIELDWORK = "FIELDWORK"
    RECONCILED = "RECONCILED"
    DISCREPANCY = "DISCREPANCY"
    CLOSED = "CLOSED"


class AuditFinding(str, Enum):
    IMMATERIAL = "IMMATERIAL"
    MATERIAL_HEAD = "MATERIAL_HEAD"
    MATERIAL_VALUE = "MATERIAL_VALUE"
    MATERIAL_BOTH = "MATERIAL_BOTH"


class ViolationType(str, Enum):
    LATE_FILING = "LATE_FILING"
    INACCURATE_DATA = "INACCURATE_DATA"
    NON_REGISTRATION = "NON_REGISTRATION"


class PenaltyStatus(str, Enum):
    ASSESSED = "ASSESSED"
    PAID = "PAID"
    WAIVED = "WAIVED"


class DelinquencyTier(str, Enum):
    TIER_0 = "TIER_0"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"


class MethodologyChangeStatus(str, Enum):
    COMMENT_OPEN = "COMMENT_OPEN"
    COMMENT_CLOSED = "COMMENT_CLOSED"
    ADOPTED = "ADOPTED"


class CommentStance(str, Enum):
    SUPPORT = "SUPPORT"
    OPPOSE = "OPPOSE"
    NEUTRAL = "NEUTRAL"


# ---------------------------------------------------------------------------
# Entities carrying id + created_at + updated_at + version (PRD §2.5)
# ---------------------------------------------------------------------------


class ReportingEntity(TypedDict):
    id: str
    legal_name: str
    entity_type: str
    species_scope: str
    delinquency_points: int
    assessed_penalty_cents: int
    paid_penalty_cents: int
    waived_penalty_cents: int
    outstanding_penalty_cents: int
    created_at: str
    updated_at: str
    version: int


class Plant(TypedDict):
    id: str
    reporting_entity_id: str
    plant_code: str
    species: str
    annual_head_history: dict
    boxed_beef_volume_lbs_prior_year: int
    forward_commitment_cap_head: int
    wholesale_reporting_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict):
    id: str
    reporting_entity_id: str
    determination_year: int
    basis_variant: str
    status: str
    measured_head: Optional[int]
    threshold_head: Optional[int]
    determination_outcome: Optional[str]
    registration_number: Optional[str]
    effective_from: Optional[str]
    appeal_count: int
    suspended_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReportingWindow(TypedDict):
    id: str
    species: str
    report_class: str
    frequency: str
    period_start: str
    period_end: str
    submission_deadline_utc: str
    correction_deadline_utc: str
    publication_release_utc: str
    min_reporter_count: int
    max_single_reporter_share_pct: float
    min_reported_head: int
    status: str
    accepted_submission_count: int
    total_head_reported: int
    created_at: str
    updated_at: str
    version: int


class Submission(TypedDict):
    id: str
    plant_id: str
    reporting_window_id: str
    supersedes_submission_id: Optional[str]
    status: str
    reported_head: int
    reported_cwt: float
    reported_value_dollars: float
    reported_pounds: float
    reported_load_count: int
    submitted_at: Optional[str]
    accepted_at: Optional[str]
    lateness_minutes: int
    is_late: bool
    days_late: int
    resubmission_count: int
    correction_reason: Optional[str]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MarketReport(TypedDict):
    id: str
    reporting_window_id: str
    category: str
    weighting_variant: str
    purchase_type_filter: str
    aggregation_state: str
    disclosure_state: str
    publication_state: str
    weighted_average_price_per_cwt: Optional[float]
    price_low_per_cwt: Optional[float]
    price_high_per_cwt: Optional[float]
    total_head: Optional[int]
    total_pounds: Optional[float]
    reporter_count: int
    max_reporter_share_pct: float
    source_submission_count: int
    suppression_reason: Optional[str]
    computed_at: Optional[str]
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditCase(TypedDict):
    id: str
    submission_id: str
    materiality_pct: float
    status: str
    opened_by_user_id: str
    finalized_by_user_id: Optional[str]
    verified_head: Optional[int]
    verified_value_dollars: Optional[float]
    head_discrepancy_rate_pct: Optional[float]
    value_discrepancy_rate_pct: Optional[float]
    finding: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PenaltyAssessment(TypedDict):
    id: str
    reporting_entity_id: str
    violation_type: str
    submission_id: Optional[str]
    audit_case_id: Optional[str]
    status: str
    base_amount_cents: int
    days_late: int
    day_tier_multiplier: float
    repeat_index: int
    repeat_multiplier: float
    volume_factor: float
    suspension_surcharge: float
    assessed_amount_cents: int
    points: int
    delinquency_tier_at_assessment: str
    assessed_by_user_id: str
    paid_amount_cents: Optional[int]
    waiver_reason: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MethodologyChange(TypedDict):
    id: str
    change_code: str
    affected_category: str
    proposed_weighting_variant: str
    comment_period_end: str
    effective_from: str
    status: str
    comment_count: int
    restated_report_count: int
    industry_notice_issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only ledger lines: id + created_at ONLY (PRD §2.5)
# ---------------------------------------------------------------------------


class TransactionRecord(TypedDict):
    id: str
    submission_id: str
    purchase_type: str
    head_count: int
    avg_net_price_per_cwt: float
    avg_carcass_weight_cwt: float
    formula_base_reference: Optional[str]
    grid_premium_discount_per_cwt: Optional[float]
    forward_delivery_start: Optional[str]
    forward_delivery_end: Optional[str]
    line_value_dollars: float
    created_at: str


class WholesaleLot(TypedDict):
    id: str
    submission_id: str
    product_class: str
    sale_type: str
    load_count: int
    total_pounds: float
    price_per_cwt: float
    lot_value_dollars: float
    created_at: str


class PublicComment(TypedDict):
    id: str
    methodology_change_id: str
    commenter_reference: str
    comment_text: str
    stance: str
    received_at: str
    created_at: str
