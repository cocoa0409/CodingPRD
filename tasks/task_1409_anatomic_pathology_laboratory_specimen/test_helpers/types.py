"""Domain types: entity TypedDicts, status enums, role enum.

All resources carry the four common system-managed properties (id, created_at,
updated_at, version) per PRD section on common resource properties.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    LAB_ADMIN = "LabAdmin"
    HISTOTECH = "Histotech"
    PATHOLOGY_ASSISTANT = "PathologyAssistant"
    PATHOLOGIST = "Pathologist"


class Subspecialty(str, Enum):
    DERMATOPATH = "DERMATOPATH"
    GI = "GI"
    BREAST = "BREAST"
    HEME = "HEME"
    GU = "GU"
    GYN = "GYN"
    NEURO = "NEURO"
    GENERAL = "GENERAL"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    WORKUP = "WORKUP"
    PENDING_SIGNOUT = "PENDING_SIGNOUT"
    FINAL = "FINAL"
    AMENDING = "AMENDING"
    CANCELLED = "CANCELLED"


class ComplexityClass(str, Enum):
    SIMPLE = "SIMPLE"
    MODERATE = "MODERATE"
    COMPLEX = "COMPLEX"
    HIGH_COMPLEXITY = "HIGH_COMPLEXITY"


class TatMode(str, Enum):
    CALENDAR = "CALENDAR"
    BUSINESS_HOURS = "BUSINESS_HOURS"


class SpecimenType(str, Enum):
    BIOPSY = "BIOPSY"
    EXCISION = "EXCISION"
    RESECTION = "RESECTION"
    CYTOLOGY = "CYTOLOGY"


class SpecimenStatus(str, Enum):
    ACCESSIONED = "ACCESSIONED"
    GROSSING = "GROSSING"
    PROCESSING = "PROCESSING"
    COMPLETE = "COMPLETE"
    REJECTED = "REJECTED"


class FixativeType(str, Enum):
    FORMALIN = "FORMALIN"
    SALINE = "SALINE"
    FROZEN = "FROZEN"
    NONE = "NONE"


class BlockStatus(str, Enum):
    CREATED = "CREATED"
    EMBEDDED = "EMBEDDED"
    DEPLETED = "DEPLETED"


class SlideStatus(str, Enum):
    ORDERED = "ORDERED"
    SECTIONED = "SECTIONED"
    STAINED = "STAINED"
    QC_PASSED = "QC_PASSED"
    QC_FAILED = "QC_FAILED"
    CANCELLED = "CANCELLED"


class SlideStainType(str, Enum):
    H_E = "H_E"


class StainType(str, Enum):
    HER2_IHC = "HER2_IHC"
    PD_L1 = "PD_L1"
    KI67 = "KI67"
    PAX5 = "PAX5"
    CD20 = "CD20"
    MUCIN = "MUCIN"
    GRAM = "GRAM"
    GMS = "GMS"


class StainOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    IN_PROGRESS = "IN_PROGRESS"
    RESULTED = "RESULTED"
    CANCELLED = "CANCELLED"


class ResultValue(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    EQUIVOCAL = "EQUIVOCAL"


class ReportClass(str, Enum):
    FINAL = "FINAL"
    AMENDED = "AMENDED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class ConsultationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    ANSWERED = "ANSWERED"
    INCORPORATED = "INCORPORATED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class Concordance(str, Enum):
    CONCORDANT = "CONCORDANT"
    MINOR_DISCORDANT = "MINOR_DISCORDANT"
    MAJOR_DISCORDANT = "MAJOR_DISCORDANT"


class DiscrepancySeverity(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"


class DiscrepancyStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class DiscrepancySource(str, Enum):
    CONSULTATION = "CONSULTATION"
    INTERNAL_QA = "INTERNAL_QA"


class MaterialType(str, Enum):
    BLOCK = "BLOCK"
    SLIDE = "SLIDE"


class ReleaseRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SHIPPED = "SHIPPED"
    OVERDUE = "OVERDUE"
    RETURNED = "RETURNED"


class CoverageWindowType(str, Enum):
    CONSULT_SERVICE = "CONSULT_SERVICE"
    UNAVAILABLE = "UNAVAILABLE"


class CoverageWindowStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class Patient(TypedDict, total=False):
    id: str
    mrn: str
    full_name: str
    date_of_birth: str
    created_at: str
    updated_at: str
    version: int


class Pathologist(TypedDict, total=False):
    id: str
    full_name: str
    subspecialties: List[str]
    active: bool
    workload_score: float
    discrepancy_rate_simple: float
    discrepancy_rate_weighted: float
    last_assigned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoverageWindow(TypedDict, total=False):
    id: str
    pathologist_id: str
    window_type: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict, total=False):
    id: str
    patient_id: str
    subspecialty: str
    tat_mode: str
    status: str
    complexity_class: str
    complexity_score: float
    assigned_pathologist_id: Optional[str]
    tat_base_time: Optional[str]
    turnaround_deadline: Optional[str]
    finalized_at: Optional[str]
    tat_breached: bool
    breach_minutes: int
    current_signed_report_id: Optional[str]
    amender_pathologist_id: Optional[str]
    open_critical_discrepancy_count: int
    created_at: str
    updated_at: str
    version: int


class Specimen(TypedDict, total=False):
    id: str
    case_id: str
    accession_number: str
    specimen_type: str
    anatomical_site: str
    collection_datetime: str
    received_datetime: str
    container_count: int
    fixative_type: str
    cold_ischemia_minutes: int
    status: str
    gross_description: Optional[str]
    retention_until: Optional[str]
    wet_tissue_disposed_at: Optional[str]
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Block(TypedDict, total=False):
    id: str
    specimen_id: str
    block_label: str
    status: str
    tissue_remaining_pct: float
    on_loan: bool
    created_at: str
    updated_at: str
    version: int


class Slide(TypedDict, total=False):
    id: str
    block_id: str
    slide_label: str
    stain_type: str
    status: str
    consumption_pct: float
    qc_failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StainOrder(TypedDict, total=False):
    id: str
    case_id: str
    block_id: str
    stain_type: str
    ordered_by_pathologist_id: Optional[str]
    reflex_rule_id: Optional[str]
    parent_stain_order_id: Optional[str]
    status: str
    result_value: Optional[str]
    resulted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReflexRule(TypedDict, total=False):
    id: str
    name: str
    trigger_stain_type: str
    trigger_result: str
    followup_stain_type: str
    priority: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Report(TypedDict, total=False):
    id: str
    case_id: str
    report_class: str
    version_number: int
    supersedes_report_id: Optional[str]
    status: str
    diagnosis_text: str
    amendment_reason: Optional[str]
    signed_by_pathologist_id: Optional[str]
    signed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Consultation(TypedDict, total=False):
    id: str
    case_id: str
    requesting_pathologist_id: str
    consultant_pathologist_id: str
    subspecialty: str
    question_text: str
    due_at: str
    status: str
    opinion_text: Optional[str]
    concordance: Optional[str]
    answered_at: Optional[str]
    decline_reason: Optional[str]
    reroute_count: int
    created_at: str
    updated_at: str
    version: int


class Discrepancy(TypedDict, total=False):
    id: str
    case_id: str
    consultation_id: Optional[str]
    report_id: Optional[str]
    source: str
    severity: str
    description: str
    status: str
    attributed_pathologist_id: Optional[str]
    resolved_at: Optional[str]
    resolved_with_amendment: bool
    created_at: str
    updated_at: str
    version: int


class ReleaseRequest(TypedDict, total=False):
    id: str
    material_type: str
    block_id: Optional[str]
    slide_id: Optional[str]
    requesting_institution: str
    reason: str
    requested_out_at: str
    due_back_at: str
    status: str
    shipped_at: Optional[str]
    returned_at: Optional[str]
    returned_late: bool
    deny_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
