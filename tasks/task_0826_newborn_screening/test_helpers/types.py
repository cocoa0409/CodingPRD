"""Domain types: entity TypedDicts, status enums, role enum (Newborn Screening PRD)."""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum (PRD §2.1) ─────────────────────────────────────────────
class UserRole(str, Enum):
    BIRTH_FACILITY_USER = "BirthFacilityUser"
    LAB_TECHNICIAN = "LabTechnician"
    FOLLOW_UP_COORDINATOR = "FollowUpCoordinator"
    SPECIALTY_CLINICIAN = "SpecialtyClinician"
    PROGRAM_ADMIN = "ProgramAdmin"


# ─── Status enums ─────────────────────────────────────────────────────
class FacilityType(str, Enum):
    HOSPITAL = "HOSPITAL"
    BIRTHING_CENTER = "BIRTHING_CENTER"
    LAB = "LAB"


class ConsentStatus(str, Enum):
    PENDING = "PENDING"
    CONSENTED = "CONSENTED"
    REFUSED = "REFUSED"


class FollowupStatus(str, Enum):
    CLEAR = "CLEAR"
    ACTIVE = "ACTIVE"


class SpecimenStatus(str, Enum):
    COLLECTED = "COLLECTED"
    RECEIVED = "RECEIVED"
    SATISFACTORY = "SATISFACTORY"
    UNSATISFACTORY = "UNSATISFACTORY"
    IN_TESTING = "IN_TESTING"
    TESTED = "TESTED"
    VOIDED = "VOIDED"


class Acceptability(str, Enum):
    SATISFACTORY = "SATISFACTORY"
    UNSAT_QUANTITY = "UNSAT_QUANTITY"
    UNSAT_EARLY = "UNSAT_EARLY"
    UNSAT_TRANSIT = "UNSAT_TRANSIT"


class TimelinessProvisional(str, Enum):
    ON_TIME = "ON_TIME"
    LATE = "LATE"


class TimelinessFinal(str, Enum):
    TIMELY = "TIMELY"
    DELAYED = "DELAYED"


class MetabolicStatus(str, Enum):
    PENDING = "PENDING"
    REPORTED_NORMAL = "REPORTED_NORMAL"
    BORDERLINE = "BORDERLINE"
    PRESUMPTIVE_POSITIVE = "PRESUMPTIVE_POSITIVE"
    CANCELLED = "CANCELLED"


class HearingStatus(str, Enum):
    NOT_DONE = "NOT_DONE"
    PASS = "PASS"
    REFER = "REFER"


class CchdStatus(str, Enum):
    NOT_DONE = "NOT_DONE"
    PASS = "PASS"
    RETEST = "RETEST"
    FAIL = "FAIL"


class OverallDisposition(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"
    CANCELLED = "CANCELLED"


class RecollectionStatus(str, Enum):
    ORDERED = "ORDERED"
    COLLECTED = "COLLECTED"
    CANCELLED = "CANCELLED"


class CaseType(str, Enum):
    SHORT_TERM = "SHORT_TERM"
    LONG_TERM = "LONG_TERM"


class PriorityVariant(str, Enum):
    INITIAL = "INITIAL"
    REVISED = "REVISED"


class FollowUpCaseStatus(str, Enum):
    OPEN = "OPEN"
    REPEAT_REQUESTED = "REPEAT_REQUESTED"
    REPEAT_RECEIVED = "REPEAT_RECEIVED"
    CONFIRMED_POSITIVE = "CONFIRMED_POSITIVE"
    LONG_TERM_MONITORING = "LONG_TERM_MONITORING"
    RESOLVED_NORMAL = "RESOLVED_NORMAL"
    CLOSED = "CLOSED"


class Specialty(str, Enum):
    METABOLIC_GENETICS = "METABOLIC_GENETICS"
    AUDIOLOGY = "AUDIOLOGY"
    CARDIOLOGY = "CARDIOLOGY"


class ReferralStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    DECLINED = "DECLINED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class AssayRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


# ─── Entity TypedDicts (all entities carry id/created_at/updated_at/version) ──
class Facility(TypedDict):
    id: str
    name: str
    facility_type: str
    state_region: str
    total_booked_minutes: int
    created_at: str
    updated_at: str
    version: int


class Infant(TypedDict):
    id: str
    facility_id: str
    birth_datetime: str
    gestational_age_weeks: int
    birth_weight_grams: int
    sex: str
    multiple_birth: bool
    consent_status: str
    current_specimen_id: Optional[str]
    open_recollection_count: int
    open_case_count: int
    followup_status: str
    created_at: str
    updated_at: str
    version: int


class Specimen(TypedDict):
    id: str
    infant_id: str
    specimen_type: str
    collection_datetime: str
    received_datetime: Optional[str]
    reported_datetime: Optional[str]
    blood_spot_count: Optional[int]
    collection_age_hours: float
    transit_time_hours: Optional[float]
    acceptability: Optional[str]
    timeliness_provisional: Optional[str]
    timeliness_final: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Screen(TypedDict):
    id: str
    specimen_id: str
    metabolic_status: str
    hearing_status: str
    cchd_status: str
    spo2_right_hand: Optional[int]
    spo2_foot: Optional[int]
    critical_analyte_count: int
    overall_disposition: str
    created_at: str
    updated_at: str
    version: int


class RecollectionOrder(TypedDict):
    id: str
    specimen_id: str
    reason: str
    deadline_datetime: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FollowUpCase(TypedDict):
    id: str
    infant_id: str
    screen_id: str
    case_type: str
    critical_flag_count: int
    repeat_count: int
    opened_at_clock: str
    priority_variant: str
    priority_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SpecialtyClinic(TypedDict):
    id: str
    name: str
    specialty: str
    concurrent_capacity: int
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    follow_up_case_id: str
    specialty_clinic_id: str
    referral_reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ConfirmatoryAppointment(TypedDict):
    id: str
    referral_id: str
    specialty_clinic_id: str
    start_datetime: str
    end_datetime: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AssayRun(TypedDict):
    id: str
    facility_id: str
    instrument_code: str
    start_datetime: str
    end_datetime: str
    duration_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int
