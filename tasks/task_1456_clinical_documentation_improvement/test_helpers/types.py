"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    CDI_MANAGER = "CDIManager"
    CDI_SPECIALIST = "CDISpecialist"
    HIM_CODER = "HIMCoder"
    PROVIDER = "Provider"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"
    SYSTEM_ADMIN = "SystemAdmin"


class CDIProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class PatientCaseStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RECONCILED = "RECONCILED"
    FINAL_CODED = "FINAL_CODED"
    CLOSED = "CLOSED"


class ReconciliationStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    RESOLVED_CDI_PREVAILS = "RESOLVED_CDI_PREVAILS"
    RESOLVED_CODER_PREVAILS = "RESOLVED_CODER_PREVAILS"
    ESCALATED = "ESCALATED"


class CDIReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    CLOSED = "CLOSED"


class ReviewClosedReason(str, Enum):
    OPPORTUNITY_CAPTURED = "OPPORTUNITY_CAPTURED"
    NO_OPPORTUNITY = "NO_OPPORTUNITY"
    SUPERSEDED = "SUPERSEDED"
    CASE_DISCHARGED = "CASE_DISCHARGED"


class CDIQueryStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    RESPONDED = "RESPONDED"
    ESCALATED = "ESCALATED"
    NO_RESPONSE = "NO_RESPONSE"
    CANCELLED = "CANCELLED"


class ResponseType(str, Enum):
    AGREE = "AGREE"
    DISAGREE = "DISAGREE"
    CLARIFICATION_REQUESTED = "CLARIFICATION_REQUESTED"
    CLINICALLY_UNSUPPORTED = "CLINICALLY_UNSUPPORTED"


class ReconciliationEventStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED_CDI_PREVAILS = "RESOLVED_CDI_PREVAILS"
    RESOLVED_CODER_PREVAILS = "RESOLVED_CODER_PREVAILS"
    ESCALATED = "ESCALATED"


class ReconciliationOutcome(str, Enum):
    CDI_PREVAILS = "CDI_PREVAILS"
    CODER_PREVAILS = "CODER_PREVAILS"


class EducationFlag(str, Enum):
    NONE = "NONE"
    WATCH = "WATCH"
    COACHING = "COACHING"
    INTENSIVE_REVIEW = "INTENSIVE_REVIEW"


class PatternTag(str, Enum):
    LEADING_LANGUAGE = "LEADING_LANGUAGE"
    NO_RESPONSE_PATTERN = "NO_RESPONSE_PATTERN"
    CLINICALLY_UNSUPPORTED_PATTERN = "CLINICALLY_UNSUPPORTED_PATTERN"
    OVERDUE_PATTERN = "OVERDUE_PATTERN"


# All entities in this domain carry the full common-field set:
# id, created_at, updated_at, version.


class CDIProgram(TypedDict, total=False):
    id: str
    facility_name: str
    program_code: str
    baseline_cmi: float
    current_period_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EscalationPolicy(TypedDict, total=False):
    id: str
    cdi_program_id: str
    name: str
    response_due_periods: int
    escalation_stage_periods: int
    max_escalation_stage: int
    is_default: bool
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    cdi_program_id: str
    npi: str
    full_name: str
    specialty: str
    education_score: int
    pattern_tally_json: Dict[str, int]
    education_flag: str
    created_at: str
    updated_at: str
    version: int


class PatientCase(TypedDict, total=False):
    id: str
    cdi_program_id: str
    mrn: str
    admission_period: int
    discharge_period: int
    attending_provider_id: str
    initial_drg_code: str
    initial_drg_weight: float
    working_drg_code: str
    working_drg_weight: float
    working_soi: int
    working_rom: int
    priority_score: float
    reconciliation_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CDIReview(TypedDict, total=False):
    id: str
    patient_case_id: str
    cdi_program_id: str
    cdi_specialist_id: str
    opened_period: int
    opportunity_weight_delta: float
    opportunity_soi_delta: int
    opportunity_rom_delta: int
    closed_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CDIQuery(TypedDict, total=False):
    id: str
    cdi_review_id: str
    patient_case_id: str
    cdi_program_id: str
    provider_id: str
    escalation_policy_id: str
    query_text: str
    clinical_indicators: List[str]
    proposed_drg_code: str
    proposed_drg_weight: float
    proposed_soi: int
    proposed_rom: int
    compliant_language: bool
    lint_findings: List[str]
    sent_period: Optional[int]
    due_period: Optional[int]
    escalation_stage: int
    last_escalated_period: Optional[int]
    response_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class QueryResponse(TypedDict, total=False):
    id: str
    cdi_query_id: str
    patient_case_id: str
    responder_provider_id: str
    response_type: str
    response_text: str
    responded_period: int
    was_overdue: bool
    created_at: str
    updated_at: str
    version: int


class ReconciliationEvent(TypedDict, total=False):
    id: str
    patient_case_id: str
    cdi_program_id: str
    coder_user_id: str
    coder_drg_code: str
    coder_drg_weight: float
    cdi_drg_code: str
    cdi_drg_weight: float
    resolution_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DenialRiskTarget(TypedDict, total=False):
    id: str
    cdi_program_id: str
    drg_code: str
    required_evidence_tags: List[str]
    severity_floor: int
    active_from_period: int
    active_to_period: int
    created_at: str
    updated_at: str
    version: int


class ProviderEducationEvent(TypedDict, total=False):
    id: str
    provider_id: str
    cdi_program_id: str
    pattern_tag: str
    points_deducted: int
    source_query_id: str
    note: str
    recorded_period: int
    created_at: str
    updated_at: str
    version: int


class CMISnapshot(TypedDict, total=False):
    id: str
    cdi_program_id: str
    as_of_period: int
    case_count: int
    unadjusted_cmi: float
    adjusted_cmi: float
    cdi_lift: float
    denial_target_misses: int
    created_at: str
    updated_at: str
    version: int
