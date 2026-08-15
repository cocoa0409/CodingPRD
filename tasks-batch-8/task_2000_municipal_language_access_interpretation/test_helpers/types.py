"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    COORDINATOR = "LanguageAccessCoordinator"
    LIAISON = "DepartmentLiaison"
    INTERPRETER = "Interpreter"
    REVIEWER = "QualityReviewer"
    OFFICER = "ComplianceOfficer"


class SignageStatus(str, Enum):
    CURRENT = "CURRENT"
    DEFICIENT = "DEFICIENT"
    MISSING = "MISSING"


class Posture(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    WATCH = "WATCH"
    NONCOMPLIANT = "NONCOMPLIANT"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"


class DocumentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class DocumentType(str, Enum):
    FORM = "FORM"
    NOTICE = "NOTICE"
    GUIDE = "GUIDE"
    POLICY = "POLICY"


class TranslationJobStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_TRANSLATION = "IN_TRANSLATION"
    QUALITY_REVIEW = "QUALITY_REVIEW"
    APPROVED = "APPROVED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class InterpreterTier(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    REGISTERED = "REGISTERED"
    CERTIFIED = "CERTIFIED"


class InterpreterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class Modality(str, Enum):
    PHONE = "PHONE"
    VIDEO = "VIDEO"
    IN_PERSON = "IN_PERSON"


class EncounterSetting(str, Enum):
    GENERAL = "GENERAL"
    MEDICAL = "MEDICAL"
    COURT = "COURT"


class RequestStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    UNFULFILLED = "UNFULFILLED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ComplaintStatus(str, Enum):
    RECEIVED = "RECEIVED"
    SUBSTANTIATED = "SUBSTANTIATED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class ComplaintCategory(str, Enum):
    NO_INTERPRETER_AVAILABLE = "NO_INTERPRETER_AVAILABLE"
    POOR_QUALITY = "POOR_QUALITY"
    CONFIDENTIALITY_BREACH = "CONFIDENTIALITY_BREACH"
    NOTICE_MISSING = "NOTICE_MISSING"
    OTHER = "OTHER"


class Remedy(str, Enum):
    NONE = "NONE"
    REFUND = "REFUND"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class ReviewDecision(str, Enum):
    CERTIFY = "CERTIFY"
    REJECT = "REJECT"


class JobReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_REVISION = "REQUEST_REVISION"


class AdjudicationOutcome(str, Enum):
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


# All nine resource types carry the four system-managed properties of PRD §2.4:
# id, created_at, updated_at, version.


class Department(TypedDict, total=False):
    id: str
    name: str
    service_area_code: str
    annual_budget_cents: int
    signage_status: str
    spent_cents: int
    remaining_cents: int
    compliance_score: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class LanguageAssessment(TypedDict, total=False):
    id: str
    department_id: str
    language_code: str
    plan_year: int
    period_start: str
    period_end: str
    lep_speaker_count: int
    service_area_population: int
    encounter_count: int
    total_encounters: int
    lep_share: float
    encounter_share: float
    threshold_language_safe: bool
    priority_language: bool
    status: str
    created_by_user_id: str
    reviewed_by_user_id: Optional[str]
    rejection_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VitalDocument(TypedDict, total=False):
    id: str
    department_id: str
    title: str
    document_type: str
    base_language: str
    status: str
    translated_language_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class TranslationJob(TypedDict, total=False):
    id: str
    document_id: str
    vendor_contract_id: str
    target_language_code: str
    word_count: int
    rush: bool
    provisional_cost_cents: int
    translator_id: Optional[str]
    reviewer_id: Optional[str]
    submitted_word_count: Optional[int]
    revision_count: int
    final_cost_cents: Optional[int]
    superseded_by_job_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Interpreter(TypedDict, total=False):
    id: str
    full_name: str
    language_codes: List[str]
    modalities: List[str]
    tier: str
    vendor_contract_id: str
    confidentiality_signed_at: Optional[str]
    quality_rating: int
    minutes_current_month: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InterpretationRequest(TypedDict, total=False):
    id: str
    department_id: str
    language_code: str
    modality: str
    encounter_setting: str
    scheduled_start: str
    scheduled_duration_minutes: int
    interpreter_id: Optional[str]
    estimated_cost_cents: Optional[int]
    actual_minutes: Optional[int]
    final_cost_cents: Optional[int]
    completed_at: Optional[str]
    refund_clawed_back: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict, total=False):
    id: str
    department_id: str
    interpretation_request_id: Optional[str]
    category: str
    description: str
    recorded_by_user_id: str
    status: str
    adjudicated_by_user_id: Optional[str]
    adjudicated_at: Optional[str]
    remedy: Optional[str]
    remediation_due_at: Optional[str]
    resolution_note: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VendorContract(TypedDict, total=False):
    id: str
    vendor_name: str
    ceiling_cents: int
    phone_per_minute_cents: int
    video_per_minute_cents: int
    in_person_per_minute_cents: int
    translation_per_word_cents: int
    in_person_travel_flat_cents: int
    committed_cents: int
    spent_cents: int
    available_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LanguageAccessPlan(TypedDict, total=False):
    id: str
    plan_year: int
    summary: Optional[str]
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
