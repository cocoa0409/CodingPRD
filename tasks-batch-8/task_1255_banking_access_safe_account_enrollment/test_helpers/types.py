"""Domain types: entity TypedDicts, status enums, role enum (PRD §3, §4)."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    COALITION_ADMIN = "CoalitionAdmin"
    INSTITUTION_OFFICER = "InstitutionOfficer"
    AGENCY_NAVIGATOR = "AgencyNavigator"
    PARTICIPANT = "Participant"
    FINANCIAL_COACH = "FinancialCoach"


class AccountStandardStatus(str, Enum):
    DRAFT = "DRAFT"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class RubricMode(str, Enum):
    STANDARD_RUBRIC = "STANDARD_RUBRIC"
    REMEDIATION_RUBRIC = "REMEDIATION_RUBRIC"


class CertificationStatus(str, Enum):
    APPLIED = "APPLIED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"
    LAPSED = "LAPSED"
    DECERTIFIED = "DECERTIFIED"


class ReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    SCORED = "SCORED"
    FINALIZED_PASS = "FINALIZED_PASS"
    FINALIZED_CONDITIONAL = "FINALIZED_CONDITIONAL"
    FINALIZED_FAIL = "FINALIZED_FAIL"
    SUPERSEDED = "SUPERSEDED"


class ReviewOutcome(str, Enum):
    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"


class PipelineStage(str, Enum):
    REGISTERED = "REGISTERED"
    REFERRED = "REFERRED"
    DOCS_READY = "DOCS_READY"
    EVENT_BOOKED = "EVENT_BOOKED"
    APPLIED = "APPLIED"
    ACCOUNT_OPENED = "ACCOUNT_OPENED"


class PriorBankingRecord(str, Enum):
    NONE = "NONE"
    CLEAN = "CLEAN"
    FLAGGED = "FLAGGED"


class ReferralStatus(str, Enum):
    DOCS_PENDING = "DOCS_PENDING"
    DOCS_COMPLETE = "DOCS_COMPLETE"
    BOOKED = "BOOKED"
    APPLIED = "APPLIED"
    CLOSED_CONVERTED = "CLOSED_CONVERTED"
    CLOSED_LOST = "CLOSED_LOST"


class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    OPENED = "OPENED"
    DECLINED_CHEX = "DECLINED_CHEX"
    DECLINED_ID = "DECLINED_ID"
    DECLINED_FINAL = "DECLINED_FINAL"
    REINSTATED = "REINSTATED"
    CLOSED_EARLY = "CLOSED_EARLY"


class DeclineReason(str, Enum):
    CHEX = "CHEX"
    INSUFFICIENT_ID = "INSUFFICIENT_ID"
    OTHER = "OTHER"


class BarrierCaseStatus(str, Enum):
    OPEN = "OPEN"
    PLAN_PROPOSED = "PLAN_PROPOSED"
    COUNTERED = "COUNTERED"
    RESOLVED = "RESOLVED"
    DENIED_FINAL = "DENIED_FINAL"


class PairingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FOLLOW_UP_DUE = "FOLLOW_UP_DUE"
    FOLLOW_UP_DONE = "FOLLOW_UP_DONE"


class CheckpointKind(str, Enum):
    M6 = "M6"
    M12 = "M12"


class CheckpointStatus(str, Enum):
    PENDING = "PENDING"
    EVALUATED_RETAINED = "EVALUATED_RETAINED"
    EVALUATED_NOT_RETAINED = "EVALUATED_NOT_RETAINED"
    EXPIRED_UNCONFIRMED = "EXPIRED_UNCONFIRMED"


class GrantStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class EvaluationMode(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class CampaignStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class CharterType(str, Enum):
    BANK = "BANK"
    CREDIT_UNION = "CREDIT_UNION"


class IdDocType(str, Enum):
    STATE_ID = "STATE_ID"
    SSN_CARD = "SSN_CARD"
    ITIN_LETTER = "ITIN_LETTER"
    MATRICULA_CONSULAR = "MATRICULA_CONSULAR"
    MUNICIPAL_ID = "MUNICIPAL_ID"
    FOREIGN_PASSPORT = "FOREIGN_PASSPORT"
    PROOF_OF_ADDRESS = "PROOF_OF_ADDRESS"


class CourseCode(str, Enum):
    FOUNDATIONS = "FOUNDATIONS"
    CREDIT_BASICS = "CREDIT_BASICS"
    SAVINGS = "SAVINGS"


# All resources carry the common fields id / created_at / updated_at / version
# (PRD §2.4).

class AccountStandard(TypedDict, total=False):
    id: str
    code: str
    name: str
    effective_from: str
    monthly_fee_cap_cents: int
    overdraft_fee_allowed: bool
    min_opening_deposit_cap_cents: int
    accepted_alt_id_types: List[str]
    chex_second_look_required: bool
    requires_financial_education: bool
    rubric_mode: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PartnerInstitution(TypedDict, total=False):
    id: str
    legal_name: str
    charter_type: str
    certification_status: str
    certified_standard_id: Optional[str]
    certified_at: Optional[str]
    certification_expires_at: Optional[str]
    accounts_opened_total: int
    current_review_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CertificationReview(TypedDict, total=False):
    id: str
    institution_id: str
    standard_id: str
    period_start: str
    period_end: str
    criteria_ratings: List[dict]
    mandatory_floor_failed: Optional[bool]
    weighted_score: Optional[float]
    outcome: Optional[str]
    scored_by_user_id: Optional[str]
    finalized_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    contact_zip: str
    prior_banking_record: str
    id_documents: List[dict]
    docs_complete: bool
    pipeline_stage: str
    registered_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict, total=False):
    id: str
    participant_id: str
    campaign_id: Optional[str]
    created_via: str
    agency_user_id: Optional[str]
    status: str
    booked_event_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccountOpeningEvent(TypedDict, total=False):
    id: str
    institution_id: str
    venue_code: str
    starts_at: str
    ends_at: str
    capacity: int
    booked_count: int
    alt_id_accepted: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class AccountApplication(TypedDict, total=False):
    id: str
    participant_id: str
    institution_id: str
    referral_id: Optional[str]
    event_id: Optional[str]
    id_type_presented: str
    status: str
    decline_reason: Optional[str]
    account_number: Optional[str]
    opened_at: Optional[str]
    closed_at: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BarrierCase(TypedDict, total=False):
    id: str
    application_id: str
    participant_id: str
    institution_id: str
    status: str
    negotiation_rounds: int
    proposed_settlement_cents: Optional[int]
    final_settlement_cents: Optional[int]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EducationPairing(TypedDict, total=False):
    id: str
    participant_id: str
    coach_id: str
    course_code: str
    status: str
    completed_at: Optional[str]
    follow_up_due_at: Optional[str]
    follow_up_logged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetentionCheckpoint(TypedDict, total=False):
    id: str
    application_id: str
    kind: str
    due_date: str
    window_end: str
    status: str
    evaluated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundingGrant(TypedDict, total=False):
    id: str
    funder_name: str
    program_year: int
    total_cents: int
    per_report_cap_cents: int
    status: str
    reserved_cents: int
    disbursed_cents: int
    available_cents: int
    created_at: str
    updated_at: str
    version: int


class PartnerReport(TypedDict, total=False):
    id: str
    institution_id: str
    grant_id: str
    period_start: str
    period_end: str
    evaluation_mode: str
    status: str
    opened_count: int
    opening_claim_cents: int
    retention_rate_m6: Optional[float]
    retention_rate_m12: Optional[float]
    retention_bonus_cents: int
    education_stipend_cents: int
    claim_total_cents: int
    created_at: str
    updated_at: str
    version: int


class OutreachCampaign(TypedDict, total=False):
    id: str
    name: str
    zip_cluster: str
    window_start: str
    window_end: str
    budget_cents: int
    per_conversion_cents: int
    spent_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
