"""Domain types: entity TypedDicts, status enums, role enum (PRD 2.4, 3.x).

Every resource in this API carries the full system quadruple — id, created_at,
updated_at, version — per PRD 2.4 ("No entity in this domain is exempt").
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    APPLICANT = "Applicant"
    STAFF_REVIEWER = "StaffReviewer"
    DECISION_AUTHORITY = "DecisionAuthority"


class FeeScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    ADOPTED = "ADOPTED"
    SUPERSEDED = "SUPERSEDED"


class ProjectStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"
    COMPLETE = "COMPLETE"


class LandUseType(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL = "COMMERCIAL"


class ApplicationType(str, Enum):
    REZONE = "REZONE"
    CONDITIONAL_USE = "CONDITIONAL_USE"
    PLANNED_DEVELOPMENT = "PLANNED_DEVELOPMENT"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    DECISION_PENDING = "DECISION_PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class OppositionPosture(str, Enum):
    LOW = "LOW"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"


class Discipline(str, Enum):
    TRANSPORTATION = "TRANSPORTATION"
    PARKS = "PARKS"
    FIRE = "FIRE"
    WATER = "WATER"
    SEWER = "SEWER"
    PLANNING = "PLANNING"


class Severity(str, Enum):
    INFO = "INFO"
    REQUIRED = "REQUIRED"
    BLOCKING = "BLOCKING"


class CommentStatus(str, Enum):
    OPEN = "OPEN"
    ADDRESSED = "ADDRESSED"
    VERIFIED = "VERIFIED"
    WAIVED = "WAIVED"


class Disposition(str, Enum):
    SUPPORT = "SUPPORT"
    NEUTRAL = "NEUTRAL"
    OPPOSE = "OPPOSE"
    ORGANIZED_OPPOSITION = "ORGANIZED_OPPOSITION"


class HearingBody(str, Enum):
    PLANNING_COMMISSION = "PLANNING_COMMISSION"
    CITY_COUNCIL = "CITY_COUNCIL"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CONTINUED = "CONTINUED"
    CANCELLED = "CANCELLED"


class ConditionCategory(str, Enum):
    FEE = "FEE"
    IMPROVEMENT = "IMPROVEMENT"
    DESIGN = "DESIGN"
    ENVIRONMENTAL = "ENVIRONMENTAL"


class RequiredBefore(str, Enum):
    PERMIT_ISSUANCE = "PERMIT_ISSUANCE"
    CERTIFICATE_OF_OCCUPANCY = "CERTIFICATE_OF_OCCUPANCY"
    FINAL_INSPECTION = "FINAL_INSPECTION"


class ConditionStatus(str, Enum):
    PENDING = "PENDING"
    SATISFIED = "SATISFIED"
    WAIVED = "WAIVED"
    BREACHED = "BREACHED"


class AssessmentVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class AssessmentStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DEFERRED = "DEFERRED"
    REFUNDED = "REFUNDED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ADOPTED = "ADOPTED"
    EFFECTIVE = "EFFECTIVE"
    REPEALED = "REPEALED"


class VestingStatus(str, Enum):
    PENDING_REFERENDUM = "PENDING_REFERENDUM"
    VESTED = "VESTED"
    LAPSED = "LAPSED"
    INVALIDATED = "INVALIDATED"


class PetitionStatus(str, Enum):
    FILED = "FILED"
    CERTIFIED_QUALIFIED = "CERTIFIED_QUALIFIED"
    CERTIFIED_INSUFFICIENT = "CERTIFIED_INSUFFICIENT"
    REJECTED_UNTIMELY = "REJECTED_UNTIMELY"


class AppealStatus(str, Enum):
    FILED = "FILED"
    UPHELD = "UPHELD"
    REVERSED = "REVERSED"
    DISMISSED_UNTIMELY = "DISMISSED_UNTIMELY"


class DecisionValue(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class DecisionStatus(str, Enum):
    RENDERED = "RENDERED"
    FINAL = "FINAL"
    STAYED_ON_APPEAL = "STAYED_ON_APPEAL"
    REVERSED_ON_APPEAL = "REVERSED_ON_APPEAL"


class AppealRuling(str, Enum):
    UPHELD = "UPHELD"
    REVERSED = "REVERSED"
    DISMISS = "DISMISS"


class PermitType(str, Enum):
    GRADING = "GRADING"
    BUILDING = "BUILDING"
    UTILITY = "UTILITY"
    OCCUPANCY = "OCCUPANCY"


class PermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ISSUED = "ISSUED"
    BLOCKED = "BLOCKED"


class AuthorityBody(str, Enum):
    PLANNING_COMMISSION = "PLANNING_COMMISSION"
    CITY_COUNCIL = "CITY_COUNCIL"
    STAFF_DIRECTOR = "STAFF_DIRECTOR"


# --- Entity TypedDicts (all carry id/created_at/updated_at/version, PRD 2.4) ---


class FeeSchedule(TypedDict, total=False):
    id: str
    schedule_label: str
    effective_date: str
    rate_transportation_res: float
    rate_parks_res: float
    rate_fire_res: float
    rate_water_res: float
    rate_sewer_res: float
    rate_transportation_com: float
    rate_parks_com: float
    rate_fire_com: float
    rate_water_com: float
    rate_sewer_com: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class StaffReviewer(TypedDict, total=False):
    id: str
    full_name: str
    disciplines: List[str]
    created_at: str
    updated_at: str
    version: int


class DecisionAuthority(TypedDict, total=False):
    id: str
    full_name: str
    body: str
    created_at: str
    updated_at: str
    version: int


class EntitlementProject(TypedDict, total=False):
    id: str
    project_name: str
    applicant_id: str
    land_use_type: str
    dwelling_units: int
    affordable_units: int
    floor_area_sqft: int
    prior_use_basis: Dict[str, float]
    status: str
    created_at: str
    updated_at: str
    version: int


class EntitlementApplication(TypedDict, total=False):
    id: str
    project_id: str
    application_type: str
    submittal_package: List[str]
    improvement_credits: Dict[str, float]
    pinned_fee_schedule_id: str
    provisional_fee_total: float
    final_fee_total: float
    opposition_score: int
    opposition_posture: str
    decision_due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReviewComment(TypedDict, total=False):
    id: str
    application_id: str
    reviewer_id: str
    discipline: str
    comment_text: str
    severity: str
    round_number: int
    revises_comment_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OutreachEvent(TypedDict, total=False):
    id: str
    application_id: str
    event_date: str
    disposition: str
    attendee_count: int
    weight: int
    created_at: str
    updated_at: str
    version: int


class PublicHearing(TypedDict, total=False):
    id: str
    application_id: str
    hearing_date: str
    notice_posted_date: str
    hearing_body: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ConditionOfApproval(TypedDict, total=False):
    id: str
    application_id: str
    condition_text: str
    category: str
    required_before: str
    satisfied_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ImpactFeeAssessment(TypedDict, total=False):
    id: str
    application_id: str
    fee_schedule_id: str
    variant: str
    category_lines: List[Dict[str, Any]]
    gross_total: float
    prior_use_credit_total: float
    improvement_credit_total: float
    net_total: float
    due_date: str
    outstanding_balance: float
    status: str
    created_at: str
    updated_at: str
    version: int


class FeePayment(TypedDict, total=False):
    id: str
    assessment_id: str
    amount: float
    paid_at: str
    late_fee: float
    applied_amount: float
    created_at: str
    updated_at: str
    version: int


class DevelopmentAgreement(TypedDict, total=False):
    id: str
    application_id: str
    agreement_number: str
    adoption_date: str
    vesting_term_years: int
    registered_voters: int
    vesting_expires_at: str
    referendum_deadline: str
    vesting_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReferendumPetition(TypedDict, total=False):
    id: str
    development_agreement_id: str
    filed_at: str
    valid_signature_count: int
    required_signature_count: int
    qualifies: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    application_id: str
    appellant_name: str
    filed_at: str
    grounds: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EntitlementDecision(TypedDict, total=False):
    id: str
    application_id: str
    decision: str
    decided_by: str
    decision_effective_date: str
    appeal_deadline: str
    via_hearing: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PermitSequence(TypedDict, total=False):
    id: str
    application_id: str
    permit_type: str
    sequence_rank: int
    requested_at: str
    issued_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
