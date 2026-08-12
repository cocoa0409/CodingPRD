"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    AQUATICS_MANAGER = "AquaticsManager"
    GATE_ATTENDANT = "GateAttendant"
    LIFEGUARD = "Lifeguard"
    PASS_HOLDER = "PassHolder"


class FacilityStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED_CHEMISTRY = "CLOSED_CHEMISTRY"
    CLOSED_WEATHER = "CLOSED_WEATHER"
    CLOSED_STAFFING = "CLOSED_STAFFING"
    CLOSED_SEASON = "CLOSED_SEASON"


class ChemistryState(str, Enum):
    IN_RANGE = "IN_RANGE"
    WARNING = "WARNING"
    OUT_OF_RANGE = "OUT_OF_RANGE"


class SeasonStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"


class ResidencyStatus(str, Enum):
    RESIDENT = "RESIDENT"
    NON_RESIDENT = "NON_RESIDENT"


class SeasonPassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REFUNDED = "REFUNDED"
    REVOKED = "REVOKED"


class AdmissionStatus(str, Enum):
    ISSUED = "ISSUED"
    ENTERED = "ENTERED"
    EXITED = "EXITED"
    RAIN_CHECKED = "RAIN_CHECKED"
    VOID = "VOID"


class LessonSessionStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WAITLISTED = "WAITLISTED"
    COMPLETED = "COMPLETED"
    DROPPED = "DROPPED"


class CertStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COVERED = "COVERED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class LanePurpose(str, Enum):
    LAP_SWIM = "LAP_SWIM"
    SWIM_TEAM = "SWIM_TEAM"
    LESSON = "LESSON"


class LaneAllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class RentalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class IncidentType(str, Enum):
    RESCUE = "RESCUE"
    FIRST_AID = "FIRST_AID"
    RULE_VIOLATION = "RULE_VIOLATION"
    EQUIPMENT_FAILURE = "EQUIPMENT_FAILURE"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    MAJOR = "MAJOR"


class IncidentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class ClosureReason(str, Enum):
    WEATHER = "WEATHER"
    CHEMISTRY = "CHEMISTRY"
    STAFFING_SHORTAGE = "STAFFING_SHORTAGE"
    SEASON_END = "SEASON_END"


class ClosureStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"


class RainCheckIssuance(str, Enum):
    FULL_REFUND = "FULL_REFUND"
    PRO_RATA_CREDIT = "PRO_RATA_CREDIT"
    NONE = "NONE"


# --- Entity TypedDicts (common_fields: id, created_at, updated_at, version) ---

class Facility(TypedDict):
    id: str
    name: str
    address: str
    max_bather_capacity: int
    lap_lane_count: int
    current_bather_count: int
    required_lifeguard_count: int
    operational_status: str
    chemistry_state: str
    chemistry_out_of_range_since: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MembershipSeason(TypedDict):
    id: str
    facility_id: str
    season_name: str
    start_date: str
    end_date: str
    resident_pass_price_cents: int
    non_resident_pass_price_cents: int
    resident_daily_price_cents: int
    non_resident_daily_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PassHolder(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    residency_status: str
    email: str
    strike_count: int
    banned_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SeasonPass(TypedDict):
    id: str
    pass_holder_id: str
    season_id: str
    purchase_price_cents: int
    refunded_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DailyAdmission(TypedDict):
    id: str
    facility_id: str
    pass_holder_id: str
    season_pass_id: Optional[str]
    admission_date: str
    charge_cents: int
    entered_at: Optional[str]
    exited_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SwimLessonLevel(TypedDict):
    id: str
    level_code: str
    display_name: str
    min_age_years: int
    prerequisite_level_id: Optional[str]
    capacity_per_session: int
    created_at: str
    updated_at: str
    version: int


class LessonSession(TypedDict):
    id: str
    facility_id: str
    level_id: str
    season_id: str
    start_datetime: str
    end_datetime: str
    lanes_required: int
    enrolled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LessonEnrollment(TypedDict):
    id: str
    lesson_session_id: str
    pass_holder_id: str
    placement_evidence_level_id: Optional[str]
    status: str
    waitlist_position: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Lifeguard(TypedDict):
    id: str
    full_name: str
    certification_id: str
    cert_expires_on: str
    cert_status: str
    hired_on: str
    created_at: str
    updated_at: str
    version: int


class LifeguardShift(TypedDict):
    id: str
    facility_id: str
    lifeguard_id: str
    shift_start: str
    shift_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ChemistryLog(TypedDict):
    # Immutable water-chemistry record: carries ONLY id + created_at
    # (PRD §2.4 single exception — no updated_at, no version).
    id: str
    facility_id: str
    recorded_at: str
    free_chlorine_ppm: float
    ph: float
    combined_chlorine_ppm: float
    classification: str
    recorded_by_lifeguard_id: str
    created_at: str


class LaneAllocation(TypedDict):
    id: str
    facility_id: str
    purpose: str
    start_datetime: str
    end_datetime: str
    lane_count: int
    owning_lesson_session_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FacilityRental(TypedDict):
    id: str
    facility_id: str
    pass_holder_id: str
    party_size: int
    start_datetime: str
    end_datetime: str
    quoted_price_cents: int
    final_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict):
    id: str
    facility_id: str
    reporting_lifeguard_id: str
    involved_pass_holder_id: str
    incident_type: str
    occurred_at: str
    severity: str
    narrative: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PoolClosureEvent(TypedDict):
    id: str
    facility_id: str
    closure_reason: str
    started_at: str
    ended_at: Optional[str]
    rain_check_issuance: str
    status: str
    created_at: str
    updated_at: str
    version: int
