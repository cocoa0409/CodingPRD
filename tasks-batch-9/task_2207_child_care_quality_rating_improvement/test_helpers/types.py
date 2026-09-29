"""Domain types: status enums, role enum and entity TypedDicts (PRD §2, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List, Dict


class UserRole(str, Enum):
    STATE_ADMINISTRATOR = "StateAdministrator"
    PROVIDER = "Provider"
    OBSERVER = "Observer"
    COACH = "Coach"
    APPEAL_REVIEWER = "AppealReviewer"
    FAMILY_VIEWER = "FamilyViewer"


class ProviderStatus(str, Enum):
    APPLIED = "APPLIED"
    ENROLLED = "ENROLLED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class RegionCode(str, Enum):
    URBAN = "URBAN"
    RURAL = "RURAL"
    FRONTIER = "FRONTIER"


class DomainCode(str, Enum):
    LEARNING_ENVIRONMENT = "LEARNING_ENVIRONMENT"
    STAFF_QUALIFICATIONS = "STAFF_QUALIFICATIONS"
    FAMILY_PARTNERSHIP = "FAMILY_PARTNERSHIP"
    ADMINISTRATION = "ADMINISTRATION"
    CHILD_ASSESSMENT = "CHILD_ASSESSMENT"


class RoleType(str, Enum):
    DIRECTOR = "DIRECTOR"
    LEAD_TEACHER = "LEAD_TEACHER"
    ASSISTANT = "ASSISTANT"


class RegistryStatus(str, Enum):
    UNLINKED = "UNLINKED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SEPARATED = "SEPARATED"


class CycleType(str, Enum):
    INITIAL = "INITIAL"
    RERATING = "RERATING"
    REMAND = "REMAND"


class RatingCycleStatus(str, Enum):
    DRAFT = "DRAFT"
    SELF_ASSESSMENT_SUBMITTED = "SELF_ASSESSMENT_SUBMITTED"
    DOCS_VERIFIED = "DOCS_VERIFIED"
    OBSERVATION_SCHEDULED = "OBSERVATION_SCHEDULED"
    OBSERVATION_FINALIZED = "OBSERVATION_FINALIZED"
    AWARDED = "AWARDED"
    ACTIVE = "ACTIVE"
    UNDER_APPEAL = "UNDER_APPEAL"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class PublicationStatus(str, Enum):
    UNPUBLISHED = "UNPUBLISHED"
    PUBLISHED = "PUBLISHED"
    SUPPRESSED = "SUPPRESSED"
    WITHDRAWN = "WITHDRAWN"


class SelfAssessmentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    VERIFIED = "VERIFIED"


class EvidenceType(str, Enum):
    POLICY = "POLICY"
    ROSTER = "ROSTER"
    LESSON_PLAN = "LESSON_PLAN"
    FAMILY_SURVEY = "FAMILY_SURVEY"
    TRAINING_LOG = "TRAINING_LOG"


class ToolCode(str, Enum):
    ERS_INFANT_TODDLER = "ERS_INFANT_TODDLER"
    ERS_EARLY_CHILDHOOD = "ERS_EARLY_CHILDHOOD"


class ObserverStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    RELIABLE = "RELIABLE"
    LAPSED = "LAPSED"
    RETIRED = "RETIRED"


class ObservationVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    SCORES_ENTERED = "SCORES_ENTERED"
    RELIABILITY_CHECK = "RELIABILITY_CHECK"
    FINALIZED = "FINALIZED"
    CANCELLED = "CANCELLED"


class SubscaleCode(str, Enum):
    SPACE_FURNISHINGS = "SPACE_FURNISHINGS"
    PERSONAL_CARE = "PERSONAL_CARE"
    LANGUAGE_REASONING = "LANGUAGE_REASONING"
    ACTIVITIES = "ACTIVITIES"
    INTERACTION = "INTERACTION"
    PROGRAM_STRUCTURE = "PROGRAM_STRUCTURE"


class BlockClearance(str, Enum):
    CLEARED = "CLEARED"
    NOT_CLEARED = "NOT_CLEARED"


class ScoreVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class AppealGrounds(str, Enum):
    SCORING_ERROR = "SCORING_ERROR"
    OBSERVER_RELIABILITY = "OBSERVER_RELIABILITY"
    DOCUMENTATION_OMITTED = "DOCUMENTATION_OMITTED"
    PROCEDURAL = "PROCEDURAL"


class AppealStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    SUSTAINED = "SUSTAINED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class DisputedField(str, Enum):
    PUBLISHED_TIER = "PUBLISHED_TIER"
    PUBLISHED_SCORE = "PUBLISHED_SCORE"
    DOMAIN_POINTS = "DOMAIN_POINTS"
    LICENSED_CAPACITY = "LICENSED_CAPACITY"
    COUNTY_CODE = "COUNTY_CODE"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    TRIAGE = "TRIAGE"
    INFO_REQUESTED = "INFO_REQUESTED"
    ESCALATED = "ESCALATED"
    CORRECTION_APPLIED = "CORRECTION_APPLIED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class GrantStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"
    DECLINED = "DECLINED"


class GrantComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    UNDER_REVIEW = "UNDER_REVIEW"
    FINDING_ISSUED = "FINDING_ISSUED"
    REMEDIATED = "REMEDIATED"
    RECOVERY = "RECOVERY"


class ExpenditureCategory(str, Enum):
    EQUIPMENT = "EQUIPMENT"
    PROF_DEV = "PROF_DEV"
    FACILITY = "FACILITY"
    ADMIN = "ADMIN"


class ExpenditureStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REIMBURSED = "REIMBURSED"
    VOIDED = "VOIDED"


class FundingSource(str, Enum):
    GRANT = "GRANT"
    STATE_BASE = "STATE_BASE"


class AllocationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    VOID = "VOID"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REJECTED = "REJECTED"
    RECONCILE_REQUIRED = "RECONCILE_REQUIRED"


class ClaimVariant(str, Enum):
    INTERIM = "INTERIM"
    RECONCILED = "RECONCILED"


class AgeBand(str, Enum):
    INFANT = "INFANT"
    TODDLER = "TODDLER"
    PRESCHOOL = "PRESCHOOL"


# --- Entity shapes -----------------------------------------------------------
# Every family below carries id + created_at + updated_at + version, except
# ObservationScore, which is append-only and carries only id + created_at.


class StandardDomain(TypedDict):
    id: str
    domain_code: str
    block_level: int
    max_points: int
    block_min_points: int
    weight: float
    observation_linked: bool
    min_composite_for_block: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    legal_name: str
    license_number: str
    county_code: str
    region_code: str
    licensed_capacity: int
    active_staff_fte: float
    weekly_onsite_cap_hours: float
    status: str
    enrolled_on: Optional[str]
    credential_compliance_pct: float
    reimbursement_adjustment_cents: int
    public_listing_visible: bool
    current_rating_cycle_id: Optional[str]
    current_tier: Optional[int]
    created_at: str
    updated_at: str
    version: int


class StaffCredential(TypedDict):
    id: str
    provider_id: str
    staff_registry_id: str
    role_type: str
    credential_level: int
    fte: float
    employment_status: str
    registry_status: str
    verified_on: Optional[str]
    expires_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RatingCycle(TypedDict):
    id: str
    provider_id: str
    cycle_type: str
    status: str
    publication_status: str
    opened_on: str
    supersedes_cycle_id: Optional[str]
    superseded_by_cycle_id: Optional[str]
    domain_points: Dict[str, int]
    weighted_total: Optional[float]
    points_tier: Optional[int]
    block_clearance: Optional[Dict[str, str]]
    highest_block_cleared: Optional[int]
    awarded_tier: Optional[int]
    score_variant: Optional[str]
    awarded_on: Optional[str]
    awarded_by_user_id: Optional[str]
    effective_date: Optional[str]
    expires_on: Optional[str]
    validity_months: Optional[int]
    rerating_window_opens_on: Optional[str]
    observation_composite: Optional[float]
    reliability_pct: Optional[float]
    appeal_adjusted: bool
    published_at: Optional[str]
    published_snapshot: Optional[dict]
    created_at: str
    updated_at: str
    version: int


class SelfAssessment(TypedDict):
    id: str
    rating_cycle_id: str
    status: str
    claimed_points: Dict[str, int]
    verified_points: Optional[Dict[str, int]]
    documented_domains: List[str]
    return_count: int
    verified_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Observer(TypedDict):
    id: str
    full_name: str
    tool_code: str
    status: str
    anchor_agreement_pct: Optional[float]
    reliability_certified_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ObservationVisit(TypedDict):
    id: str
    rating_cycle_id: str
    lead_observer_id: str
    secondary_observer_id: Optional[str]
    window_start: str
    window_end: str
    status: str
    composite: Optional[float]
    reliability_pct: Optional[float]
    rescore_count: int
    finalized_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ObservationScore(TypedDict):
    """Append-only score attempt: carries only id and created_at."""
    id: str
    observation_visit_id: str
    observer_id: str
    subscale_code: str
    raw_score: float
    attempt_no: int
    is_current: bool
    created_at: str


class Appeal(TypedDict):
    id: str
    rating_cycle_id: str
    grounds: str
    narrative: str
    status: str
    filed_on: str
    info_request_count: int
    reviewer_user_id: Optional[str]
    adjusted_tier: Optional[int]
    decided_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DataDispute(TypedDict):
    id: str
    rating_cycle_id: str
    disputed_field: str
    claimed_value: str
    status: str
    filed_on: str
    triage_round: int
    linked_appeal_id: Optional[str]
    resolved_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ImprovementGrant(TypedDict):
    id: str
    provider_id: str
    rating_cycle_id: str
    awarded_amount_cents: int
    spend_deadline: str
    status: str
    compliance_status: str
    committed_cents: int
    reimbursed_cents: int
    available_cents: int
    recovery_amount_cents: int
    category_spend_cents: Dict[str, int]
    created_at: str
    updated_at: str
    version: int


class GrantExpenditure(TypedDict):
    id: str
    improvement_grant_id: str
    category: str
    amount_cents: int
    invoice_date: str
    status: str
    reimbursable_cents: int
    disallowed_cents: int
    created_at: str
    updated_at: str
    version: int


class CoachingAllocation(TypedDict):
    id: str
    provider_id: str
    coach_user_id: str
    funding_source: str
    funding_grant_id: Optional[str]
    period_start: str
    period_end: str
    allocated_hours: float
    hourly_rate_cents: int
    base_hours_cost_cents: int
    admin_fee_cents: int
    total_cost_cents: int
    spend_cap_cents: int
    status: str
    scheduled_hours: float
    delivered_hours: float
    remaining_hours: float
    created_at: str
    updated_at: str
    version: int


class CoachingSession(TypedDict):
    id: str
    coaching_allocation_id: str
    scheduled_start: str
    scheduled_end: str
    scheduled_hours: float
    delivered_hours: Optional[float]
    iso_week_key: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SubsidyClaim(TypedDict):
    id: str
    provider_id: str
    rating_cycle_id: Optional[str]
    service_month: str
    child_days: Dict[str, int]
    status: str
    base_amount_cents: int
    tier_multiplier_applied: Optional[float]
    reimbursement_cents: int
    variant_applied: Optional[str]
    paid_on: Optional[str]
    created_at: str
    updated_at: str
    version: int
