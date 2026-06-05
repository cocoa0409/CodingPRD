"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Roles (PRD §2.1) ───────────────────────────────────


class UserRole(str, Enum):
    SPONSOR = "Sponsor"
    IRB_REVIEWER = "IRBReviewer"
    COORDINATOR_STAFF = "CoordinatorStaff"
    INVESTIGATOR = "Investigator"
    SAFETY_OFFICER = "SafetyOfficer"


# ─── Status / enum value sets (PRD §3) ──────────────────


class RandomizationMethod(str, Enum):
    SIMPLE = "SIMPLE"
    PERMUTED_BLOCK = "PERMUTED_BLOCK"


class TrialIrbStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TrialPosture(str, Enum):
    SETUP = "SETUP"
    OPEN = "OPEN"
    FROZEN = "FROZEN"


class CriterionKind(str, Enum):
    INCLUSION = "INCLUSION"
    EXCLUSION = "EXCLUSION"


class CriterionAttribute(str, Enum):
    AGE_YEARS = "age_years"
    WEIGHT_KG = "weight_kg"
    HBA1C = "hba1c"
    PRIOR_TRIALS_COUNT = "prior_trials_count"
    BIOMARKER_POSITIVE = "biomarker_positive"


class Comparator(str, Enum):
    GE = "GE"
    GT = "GT"
    LE = "LE"
    LT = "LT"
    EQ = "EQ"


class ConsentDocumentStatus(str, Enum):
    DRAFT = "DRAFT"
    IRB_APPROVED = "IRB_APPROVED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class IRBReviewScope(str, Enum):
    PROTOCOL = "PROTOCOL"
    CONSENT = "CONSENT"


class IRBReviewDecision(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVISE_REQUESTED = "REVISE_REQUESTED"


class MatchResult(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class EnrollmentStatus(str, Enum):
    SCREENED = "SCREENED"
    CONSENTED = "CONSENTED"
    RANDOMIZED = "RANDOMIZED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class SafetyStatus(str, Enum):
    CLEAR = "CLEAR"
    FLAGGED = "FLAGGED"
    HOLD = "HOLD"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AdverseEventSeverity(str, Enum):
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    LIFE_THREATENING = "LIFE_THREATENING"


class AdverseEventReportStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ADJUDICATED_RELATED = "ADJUDICATED_RELATED"
    ADJUDICATED_UNRELATED = "ADJUDICATED_UNRELATED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"


# ─── Entity TypedDicts (PRD §2.4: all eleven carry id/created_at/
#     updated_at/version) ───────────────────────────────


class Trial(TypedDict):
    id: str
    title: str
    sponsor_user_id: str
    target_enrollment: int
    randomization_method: str
    block_size: Optional[int]
    irb_status: str
    posture: str
    enrolled_count: int
    active_safety_holds: int
    created_at: str
    updated_at: str
    version: int


class EligibilityCriterion(TypedDict):
    id: str
    trial_id: str
    kind: str
    attribute: str
    comparator: str
    threshold: float
    created_at: str
    updated_at: str
    version: int


class RandomizationArm(TypedDict):
    id: str
    trial_id: str
    name: str
    allocation_weight: int
    assigned_count: int
    created_at: str
    updated_at: str
    version: int


class ConsentDocument(TypedDict):
    id: str
    trial_id: str
    version_number: int
    body_hash: str
    status: str
    irb_review_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IRBReview(TypedDict):
    id: str
    trial_id: str
    scope: str
    consent_document_id: Optional[str]
    reviewer_user_id: Optional[str]
    decision: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict):
    id: str
    full_name: str
    age_years: int
    weight_kg: float
    hba1c: float
    prior_trials_count: int
    biomarker_positive: bool
    created_at: str
    updated_at: str
    version: int


class Screening(TypedDict):
    id: str
    trial_id: str
    participant_id: str
    match_result: str
    failed_criteria_count: int
    match_score: float
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    trial_id: str
    participant_id: str
    screening_id: str
    enrollment_status: str
    safety_status: str
    arm_id: Optional[str]
    signed_consent_document_id: Optional[str]
    signed_consent_version: Optional[int]
    completed_visits_count: int
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict):
    id: str
    enrollment_id: str
    sequence_index: int
    scheduled_at: str
    draw_window_minutes: int
    drawn_at: Optional[str]
    draw_in_window: bool
    draw_deviation_minutes: Optional[int]
    status: str
    payable_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class AdverseEvent(TypedDict):
    id: str
    enrollment_id: str
    reporter_user_id: str
    severity: str
    is_serious: bool
    occurred_at: str
    report_status: str
    adjudicator_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CompensationPayment(TypedDict):
    id: str
    enrollment_id: str
    amount_cents: int
    gross_cents: int
    visit_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int
