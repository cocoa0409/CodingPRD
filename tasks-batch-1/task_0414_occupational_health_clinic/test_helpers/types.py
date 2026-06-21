"""Domain types: entity TypedDicts, status enums, role enum for the Occupational Health Clinic API."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Roles ────────────────────────────────────────────
class UserRole(str, Enum):
    CLINIC_ADMIN = "ClinicAdmin"
    CLINICIAN = "Clinician"
    COLLECTOR = "Collector"
    MRO = "MRO"


# ─── Status enums ─────────────────────────────────────
class EmployerStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ProtocolStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class HireStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    CLEARED = "CLEARED"
    DISQUALIFIED = "DISQUALIFIED"


class EncounterType(str, Enum):
    PHYSICAL = "PHYSICAL"
    DRUG_SCREEN = "DRUG_SCREEN"
    INJURY = "INJURY"
    SURVEILLANCE = "SURVEILLANCE"


class EncounterStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING_RESULTS = "PENDING_RESULTS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"


class PanelCode(str, Enum):
    PHYSICAL = "PHYSICAL"
    DRUG_DOT = "DRUG_DOT"
    DRUG_NON_DOT = "DRUG_NON_DOT"
    AUDIOMETRIC = "AUDIOMETRIC"
    RESPIRATOR_FIT = "RESPIRATOR_FIT"


class DrugScreenStatus(str, Enum):
    AWAITING_COLLECTION = "AWAITING_COLLECTION"
    COLLECTED = "COLLECTED"
    AT_LAB = "AT_LAB"
    LAB_REPORTED = "LAB_REPORTED"
    MRO_REVIEW = "MRO_REVIEW"
    VERIFIED = "VERIFIED"
    RECOLLECT_ORDERED = "RECOLLECT_ORDERED"
    CANCELLED = "CANCELLED"


class LabResult(str, Enum):
    NEGATIVE = "NEGATIVE"
    NON_NEGATIVE = "NON_NEGATIVE"
    REJECTED_FOR_TESTING = "REJECTED_FOR_TESTING"


class MroVerifiedResult(str, Enum):
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"
    REFUSAL = "REFUSAL"
    CANCELLED = "CANCELLED"


class CustodyStep(str, Enum):
    COLLECT = "COLLECT"
    SEAL = "SEAL"
    SHIP = "SHIP"
    LAB_RECEIVE = "LAB_RECEIVE"
    LAB_REPORT = "LAB_REPORT"
    MRO_RECEIVE = "MRO_RECEIVE"


class TreatmentLevel(str, Enum):
    FIRST_AID = "FIRST_AID"
    MEDICAL_TREATMENT = "MEDICAL_TREATMENT"
    LOST_TIME = "LOST_TIME"
    RESTRICTED_DUTY = "RESTRICTED_DUTY"
    FATALITY = "FATALITY"


class OshaColumn(str, Enum):
    NOT_RECORDABLE = "NOT_RECORDABLE"
    DEATH = "DEATH"
    DAYS_AWAY = "DAYS_AWAY"
    RESTRICTED_TRANSFER = "RESTRICTED_TRANSFER"
    OTHER_RECORDABLE = "OTHER_RECORDABLE"


class InjuryCaseStatus(str, Enum):
    OPEN = "OPEN"
    RTW_PENDING = "RTW_PENDING"
    CLOSED = "CLOSED"


class Disposition(str, Enum):
    FULL_DUTY = "FULL_DUTY"
    MODIFIED_DUTY = "MODIFIED_DUTY"
    OFF_WORK = "OFF_WORK"


class ExamKind(str, Enum):
    AUDIOMETRIC = "AUDIOMETRIC"
    RESPIRATOR_FIT = "RESPIRATOR_FIT"


class RespiratorClass(str, Enum):
    HALF_MASK = "HALF_MASK"
    FULL_FACEPIECE = "FULL_FACEPIECE"


class SurveillanceOutcome(str, Enum):
    PASS = "PASS"
    STS = "STS"
    FAIL = "FAIL"


class SurveillanceExamStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RECORDED = "RECORDED"
    FINALIZED = "FINALIZED"
    CANCELLED = "CANCELLED"


class Determination(str, Enum):
    FIT = "FIT"
    FIT_WITH_RESTRICTIONS = "FIT_WITH_RESTRICTIONS"
    NOT_FIT = "NOT_FIT"


class ClearanceStatus(str, Enum):
    ISSUED = "ISSUED"
    RESCINDED = "RESCINDED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    VOIDED = "VOIDED"


# ─── Entity TypedDicts ────────────────────────────────
# Entities carrying the full audit complement: id, created_at, updated_at, version.

class Employer(TypedDict):
    id: str
    legal_name: str
    account_status: str
    dot_regulated: bool
    mro_user_id: str
    net_terms_days: int
    current_date: str
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Protocol(TypedDict):
    id: str
    employer_id: str
    status: str
    effective_date: str
    panels: list
    created_at: str
    updated_at: str
    version: int


class Worker(TypedDict):
    id: str
    employer_id: str
    full_name: str
    job_category: str
    dob: str
    hire_status: str
    created_at: str
    updated_at: str
    version: int


class Encounter(TypedDict):
    id: str
    employer_id: str
    worker_id: str
    protocol_id: str
    encounter_type: str
    panel_code: Optional[str]
    clinician_user_id: str
    status: str
    billable_amount_cents: int
    is_billed: bool
    created_at: str
    updated_at: str
    version: int


class DrugScreen(TypedDict):
    id: str
    encounter_id: str
    employer_id: str
    is_dot: bool
    specimen_seal_intact: bool
    lab_result: Optional[str]
    mro_verified_result: Optional[str]
    mro_user_id: Optional[str]
    recollection_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InjuryCase(TypedDict):
    id: str
    encounter_id: str
    employer_id: str
    injury_date: str
    treatment_level: str
    days_away: int
    days_restricted: int
    is_osha_recordable: bool
    osha_column: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkStatus(TypedDict):
    id: str
    injury_case_id: str
    employer_id: str
    disposition: str
    restriction_text: Optional[str]
    valid_from: str
    valid_to: str
    superseded: bool
    created_at: str
    updated_at: str
    version: int


class SurveillanceExam(TypedDict):
    id: str
    encounter_id: str
    employer_id: str
    worker_id: str
    exam_kind: str
    baseline_threshold_db: Optional[int]
    current_threshold_db: Optional[int]
    fit_factor: Optional[int]
    respirator_class: Optional[str]
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Clearance(TypedDict):
    id: str
    encounter_id: str
    employer_id: str
    worker_id: str
    determination: str
    restriction_text: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    employer_id: str
    period_start: str
    period_end: str
    issue_date: Optional[str]
    due_date: Optional[str]
    line_item_encounter_ids: list
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only forensic log: carries ONLY id + created_at (no updated_at, no version).
class CustodyEvent(TypedDict):
    id: str
    drug_screen_id: str
    step: str
    actor_user_id: str
    seq: int
    note: Optional[str]
    created_at: str
