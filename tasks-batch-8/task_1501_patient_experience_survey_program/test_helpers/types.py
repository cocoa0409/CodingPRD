"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    DATA_STEWARD = "DataSteward"
    VENDOR_OPERATOR = "VendorOperator"
    UNIT_MANAGER = "UnitManager"


class SamplingProtocol(str, Enum):
    SIMPLE_RANDOM = "SIMPLE_RANDOM"
    STRATIFIED_BY_UNIT = "STRATIFIED_BY_UNIT"
    CENSUS = "CENSUS"


class AdminMode(str, Enum):
    MAIL_ONLY = "MAIL_ONLY"
    PHONE_ONLY = "PHONE_ONLY"
    MIXED_MODE = "MIXED_MODE"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    SUPERSEDED = "SUPERSEDED"


class CycleStatus(str, Enum):
    DRAFT = "DRAFT"
    SAMPLING_OPEN = "SAMPLING_OPEN"
    FIELDING = "FIELDING"
    RECONCILIATION = "RECONCILIATION"
    SCORING = "SCORING"
    PUBLISHED = "PUBLISHED"
    VOIDED = "VOIDED"


class DischargeStatus(str, Enum):
    ELIGIBILITY_PENDING = "ELIGIBILITY_PENDING"
    ELIGIBLE = "ELIGIBLE"
    EXCLUDED = "EXCLUDED"


class DischargeDisposition(str, Enum):
    HOME = "HOME"
    SNF = "SNF"
    EXPIRED = "EXPIRED"
    PSYCH_FACILITY = "PSYCH_FACILITY"
    REHAB = "REHAB"
    HOSPICE = "HOSPICE"


class PrimaryDxGroup(str, Enum):
    MEDICAL = "MEDICAL"
    SURGICAL = "SURGICAL"
    PSYCHIATRIC = "PSYCHIATRIC"
    MATERNITY = "MATERNITY"


class Payer(str, Enum):
    MEDICARE = "MEDICARE"
    MEDICAID = "MEDICAID"
    COMMERCIAL = "COMMERCIAL"
    SELF_PAY = "SELF_PAY"


class CustodyStatus(str, Enum):
    NONE = "NONE"
    LAW_ENFORCEMENT = "LAW_ENFORCEMENT"


class SurveyMode(str, Enum):
    MAIL = "MAIL"
    PHONE = "PHONE"


class CaseStatus(str, Enum):
    SAMPLED = "SAMPLED"
    IN_FIELD = "IN_FIELD"
    RESPONDED = "RESPONDED"
    NONRESPONSE = "NONRESPONSE"
    UNDELIVERABLE = "UNDELIVERABLE"
    EXCLUDED_POST_SAMPLE = "EXCLUDED_POST_SAMPLE"
    VOIDED = "VOIDED"


class BillingStatus(str, Enum):
    CHARGED = "CHARGED"
    CREDITED = "CREDITED"


class ResponseStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    PENDING_REVIEW = "PENDING_REVIEW"
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"
    VOIDED = "VOIDED"


class Domain(str, Enum):
    NURSE_COMM = "NURSE_COMM"
    DOCTOR_COMM = "DOCTOR_COMM"
    CLEANLINESS = "CLEANLINESS"
    OVERALL_RATING = "OVERALL_RATING"


class InitiativeStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    UNDER_EVALUATION = "UNDER_EVALUATION"
    TARGET_MET = "TARGET_MET"
    TARGET_MISSED = "TARGET_MISSED"
    CANCELLED = "CANCELLED"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class TicketPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# ---------------------------------------------------------------------------
# Entity TypedDicts. All ten resources share the system-managed property set
# id / created_at / updated_at / version (PRD §2.5).
# ---------------------------------------------------------------------------


class SurveyProgram(TypedDict, total=False):
    id: str
    name: str
    sampling_protocol: str
    admin_mode: str
    active_vendor_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurveyVendor(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    cycle_budget_cents: int
    cycle_budget_remaining_cents: int
    status: str
    superseded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurveyCycle(TypedDict, total=False):
    id: str
    program_id: str
    label: str
    cycle_index: int
    discharge_window_start: str
    discharge_window_end: str
    fielding_start_date: str
    fielding_end_date: str
    target_sample_size: int
    status: str
    sampled_count: int
    completed_responses: int
    eligible_denominator: int
    response_rate: Optional[float]
    publication_eligible: bool
    scored_raw_composite_pcts: Optional[Dict[str, Any]]
    scored_adjusted_composite_pcts: Optional[Dict[str, Any]]
    scored_unit_breakdown: Optional[List[Dict[str, Any]]]
    scored_provider_breakdown: Optional[List[Dict[str, Any]]]
    scored_response_rate: Optional[float]
    scored_completed_responses: Optional[int]
    published_star_rating: Optional[int]
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CareUnit(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    unit_code: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    program_id: str
    full_name: str
    npi: str
    specialty: str
    created_at: str
    updated_at: str
    version: int


class Discharge(TypedDict, total=False):
    id: str
    program_id: str
    mrn: str
    unit_id: str
    provider_id: str
    admit_date: str
    discharge_date: str
    discharge_disposition: str
    primary_dx_group: str
    payer: str
    age_years: int
    address_country: str
    no_publicity_flag: bool
    custody_status: str
    status: str
    exclusion_reasons: List[str]
    created_at: str
    updated_at: str
    version: int


class SampleCase(TypedDict, total=False):
    id: str
    cycle_id: str
    discharge_id: str
    vendor_id: str
    unit_id: str
    provider_id: str
    mode_assigned: str
    postage_cost_cents: int
    billing_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SurveyResponse(TypedDict, total=False):
    id: str
    case_id: str
    cycle_id: str
    mode_used: str
    nurse_comm_score: int
    doctor_comm_score: int
    cleanliness_score: int
    overall_rating_score: int
    comment_text: Optional[str]
    received_at: str
    is_late: bool
    status: str
    has_escalated_recovery: bool
    created_at: str
    updated_at: str
    version: int


class ImprovementInitiative(TypedDict, total=False):
    id: str
    unit_id: str
    program_id: str
    domain: str
    baseline_cycle_id: str
    evaluation_cycle_id: str
    target_score: float
    baseline_score: Optional[float]
    status: str
    progress_pinned: Optional[float]
    progress_rolling: Optional[float]
    achieved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceRecoveryTicket(TypedDict, total=False):
    id: str
    unit_id: str
    program_id: str
    response_id: str
    domain: str
    priority: str
    status: str
    acknowledged_at: Optional[str]
    acknowledged_within_sla: Optional[bool]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int
