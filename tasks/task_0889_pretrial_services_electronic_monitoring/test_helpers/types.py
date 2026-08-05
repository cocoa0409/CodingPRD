"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD entity model. Entities that are mutable resources carry
id/created_at/updated_at/version; append-only records carry only id/created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────────────────────────

class DefendantStatus(str, Enum):
    PRETRIAL_PENDING = "PRETRIAL_PENDING"
    ACTIVE = "ACTIVE"
    DISCHARGED = "DISCHARGED"
    TERMINATED = "TERMINATED"


class SupervisionLevel(str, Enum):
    MINIMUM = "MINIMUM"
    MEDIUM = "MEDIUM"
    MAXIMUM = "MAXIMUM"


class RiskTier(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class InstrumentType(str, Enum):
    SCREENING = "SCREENING"
    FULL = "FULL"


class RecommendedLevel(str, Enum):
    MINIMUM = "MINIMUM"
    MEDIUM = "MEDIUM"
    MAXIMUM = "MAXIMUM"


class ReleaseOrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ORDERED = "ORDERED"
    DENIED = "DENIED"
    VACATED = "VACATED"


class ReleaseDecision(str, Enum):
    RELEASE = "RELEASE"
    DETAIN = "DETAIN"


class OrderedCondition(str, Enum):
    CURFEW = "CURFEW"
    NO_CONTACT = "NO_CONTACT"
    GPS_MONITORING = "GPS_MONITORING"
    DRUG_TESTING = "DRUG_TESTING"
    CHECK_IN = "CHECK_IN"


class CheckInStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"


class CheckInOrigin(str, Enum):
    MANUAL = "MANUAL"
    ESCALATION = "ESCALATION"


class EMEnrollmentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ViolationType(str, Enum):
    CURFEW = "CURFEW"
    MISSED_CHECK_IN = "MISSED_CHECK_IN"
    POSITIVE_TEST = "POSITIVE_TEST"
    FTA = "FTA"
    NEW_ARREST = "NEW_ARREST"
    OTHER = "OTHER"


class Severity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    MAJOR = "MAJOR"


class ViolationStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ADJUDICATED_SANCTION = "ADJUDICATED_SANCTION"
    ADJUDICATED_DISMISS = "ADJUDICATED_DISMISS"


class CourtEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    APPEARED = "APPEARED"
    FTA = "FTA"
    CONTINUED = "CONTINUED"


class DrugTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COLLECTED = "COLLECTED"
    RESULT_POSITIVE = "RESULT_POSITIVE"
    RESULT_NEGATIVE = "RESULT_NEGATIVE"
    MISSED = "MISSED"


class TestKind(str, Enum):
    DRUG = "DRUG"
    ALCOHOL = "ALCOHOL"


class LedgerEntryType(str, Enum):
    CHARGE = "CHARGE"
    PAYMENT = "PAYMENT"
    WAIVER = "WAIVER"
    REVERSAL = "REVERSAL"


class LedgerSource(str, Enum):
    SUPERVISION_FEE = "SUPERVISION_FEE"
    MANUAL = "MANUAL"


class LevelAdjustmentSource(str, Enum):
    MANUAL = "MANUAL"
    AUTO_ESCALATION = "AUTO_ESCALATION"


class UserRole(str, Enum):
    INTAKE_OFFICER = "IntakeOfficer"
    SUPERVISING_OFFICER = "SupervisingOfficer"
    JUDICIAL_OFFICER = "JudicialOfficer"
    PROGRAM_ADMIN = "ProgramAdmin"
    DEFENDANT = "Defendant"


# ─── Mutable resources (id + created_at + updated_at + version) ───────────

class Defendant(TypedDict):
    id: str
    case_number: str
    full_name: str
    date_of_birth: str
    indigent: bool
    supervision_status: str
    supervision_level: Optional[str]
    risk_tier: Optional[str]
    cumulative_violation_score: int
    balance_owed_cents: int
    created_at: str
    updated_at: str
    version: int


class RiskAssessment(TypedDict):
    id: str
    defendant_id: str
    instrument_type: str
    prior_failures: int
    pending_charges_count: int
    pending_violent_charge: bool
    employment_status: str
    residence_stability: str
    substance_flag: bool
    status: str
    raw_score: Optional[int]
    recommended_level: Optional[str]
    submitted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReleaseOrder(TypedDict):
    id: str
    defendant_id: str
    assessment_id: str
    decision: str
    ordered_conditions: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CheckIn(TypedDict):
    id: str
    defendant_id: str
    due_at: str
    completed_at: Optional[str]
    origin: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EMDevice(TypedDict):
    id: str
    model_name: str
    total_units: int
    available_units: int
    created_at: str
    updated_at: str
    version: int


class EMEnrollment(TypedDict):
    id: str
    defendant_id: str
    device_id: str
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ViolationEvent(TypedDict):
    id: str
    defendant_id: str
    violation_type: str
    severity: str
    severity_points: int
    status: str
    reported_by_user_id: Optional[str]
    adjudicated_by_user_id: Optional[str]
    adjudicated_at: Optional[str]
    source_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CourtEvent(TypedDict):
    id: str
    defendant_id: str
    hearing_at: str
    reminder_lead_days: int
    reminder_due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DrugTest(TypedDict):
    id: str
    defendant_id: str
    site_id: str
    test_kind: str
    slot_start: str
    slot_end: str
    status: str
    result_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TestingSite(TypedDict):
    id: str
    name: str
    slot_capacity: int
    created_at: str
    updated_at: str
    version: int


# ─── Append-only records (id + created_at only) ───────────────────────────

class CurfewWindow(TypedDict):
    id: str
    enrollment_id: str
    day_of_week: int
    start_minute: int
    end_minute: int
    created_at: str


class LocationPing(TypedDict):
    id: str
    enrollment_id: str
    pinged_at: str
    at_home: bool
    is_curfew_violation: bool
    created_at: str


class LedgerEntry(TypedDict):
    id: str
    defendant_id: str
    entry_type: str
    amount_cents: int
    reverses_entry_id: Optional[str]
    source: str
    created_at: str


class LevelAdjustment(TypedDict):
    id: str
    defendant_id: str
    from_level: Optional[str]
    to_level: str
    source: str
    reason: Optional[str]
    adjusted_by_user_id: Optional[str]
    created_at: str
