"""Domain types: entity TypedDicts, status enums, role enum.

All resources carry the four system-managed fields id/created_at/updated_at/version
per PRD "Common Resource Properties".
"""
from enum import Enum
from typing import Optional, TypedDict


class EventPosture(str, Enum):
    DRAFT = "DRAFT"
    PERMITTED = "PERMITTED"
    PUBLISHED = "PUBLISHED"
    LIVE = "LIVE"
    FINALIZED = "FINALIZED"
    CANCELLED = "CANCELLED"


class SwimStatus(str, Enum):
    PENDING_DECISION = "PENDING_DECISION"
    SWIM_ON = "SWIM_ON"
    SWIM_CANCELLED = "SWIM_CANCELLED"
    NO_SWIM = "NO_SWIM"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class WaveStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"


class Division(str, Enum):
    AGE_GROUP = "AGE_GROUP"
    ELITE = "ELITE"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RegistrationStatus(str, Enum):
    ENTERED = "ENTERED"
    PAID = "PAID"
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    RACKED = "RACKED"
    RACING = "RACING"
    FINISHED = "FINISHED"
    DNF = "DNF"
    DSQ = "DSQ"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class BikeCheckStatus(str, Enum):
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"


class ReadinessStatus(str, Enum):
    UNDERSTAFFED = "UNDERSTAFFED"
    WATER_SHORT = "WATER_SHORT"
    READY = "READY"


class VolunteerAssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    CONFIRMED = "CONFIRMED"
    NO_SHOW = "NO_SHOW"
    DECLINED = "DECLINED"


class Discipline(str, Enum):
    SWIM = "SWIM"
    T1 = "T1"
    BIKE = "BIKE"
    T2 = "T2"
    FINISH = "FINISH"


class CorrectionDiscipline(str, Enum):
    SWIM = "SWIM"
    T1 = "T1"
    BIKE = "BIKE"
    T2 = "T2"
    RUN = "RUN"


class TimingRecordStatus(str, Enum):
    RECORDED = "RECORDED"
    VALIDATED = "VALIDATED"
    INVALIDATED = "INVALIDATED"


class ResultStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    OFFICIAL = "OFFICIAL"


class PenaltyKind(str, Enum):
    DRAFTING = "DRAFTING"
    COURSE_VIOLATION = "COURSE_VIOLATION"
    EQUIPMENT = "EQUIPMENT"


class PenaltyStatus(str, Enum):
    ASSESSED = "ASSESSED"
    CONFIRMED = "CONFIRMED"
    OVERTURNED = "OVERTURNED"


class AppealStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DECIDED = "DECIDED"


class AppealDecision(str, Enum):
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    REDUCED = "REDUCED"


class AssessmentOutcome(str, Enum):
    SWIM_OK = "SWIM_OK"
    SWIM_CANCEL = "SWIM_CANCEL"


class AssessmentStatus(str, Enum):
    RECORDED = "RECORDED"
    SUPERSEDED = "SUPERSEDED"


class UserRole(str, Enum):
    RACE_DIRECTOR = "RaceDirector"
    PERMIT_COORDINATOR = "PermitCoordinator"
    REFEREE = "Referee"
    TIMER = "Timer"
    VOLUNTEER_COORDINATOR = "VolunteerCoordinator"
    ATHLETE = "Athlete"


class Event(TypedDict):
    id: str
    name: str
    start_date: str
    has_swim: bool
    water_pool_units: int
    water_pool_remaining: int
    appeal_window_minutes: int
    posture: str
    swim_status: str
    ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class RoadSegment(TypedDict):
    id: str
    event_id: str
    name: str
    length_km: float
    closure_start: str
    closure_end: str
    created_at: str
    updated_at: str
    version: int


class CoursePermit(TypedDict):
    id: str
    road_segment_id: str
    authority_name: str
    requested_start: str
    requested_end: str
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Wave(TypedDict):
    id: str
    event_id: str
    label: str
    division: str
    scheduled_start_time: str
    actual_start_time: Optional[str]
    capacity: int
    assigned_count: int
    draft_legal: bool
    age_band_min: int
    age_band_max: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Athlete(TypedDict):
    id: str
    event_id: str
    full_name: str
    birth_date: str
    license_number: str
    license_status: str
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict):
    id: str
    event_id: str
    athlete_id: str
    wave_id: Optional[str]
    division: str
    entry_fee_cents: int
    age_at_event: Optional[int]
    status: str
    refund_destination: Optional[str]
    refund_estimate_cents: Optional[int]
    refund_final_cents: Optional[int]
    withdrawn_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BikeCheck(TypedDict):
    id: str
    registration_id: str
    bib_code: str
    status: str
    checked_in_at: str
    checked_out_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AidStation(TypedDict):
    id: str
    event_id: str
    name: str
    location_km: float
    required_volunteers: int
    required_water_units: int
    allocated_water_units: int
    confirmed_volunteer_count: int
    readiness_status: str
    created_at: str
    updated_at: str
    version: int


class VolunteerAssignment(TypedDict):
    id: str
    aid_station_id: str
    volunteer_id: str
    shift_start: str
    shift_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TimingRecord(TypedDict):
    id: str
    registration_id: str
    discipline: str
    recorded_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Result(TypedDict):
    id: str
    registration_id: str
    status: str
    swim_seconds: Optional[int]
    t1_seconds: Optional[int]
    bike_seconds: Optional[int]
    t2_seconds: Optional[int]
    run_seconds: Optional[int]
    penalty_seconds_total: int
    provisional_total_seconds: Optional[int]
    official_total_seconds: Optional[int]
    effective_total_seconds: Optional[int]
    division_rank: Optional[int]
    finish_timestamp: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Penalty(TypedDict):
    id: str
    registration_id: str
    kind: str
    notes: Optional[str]
    seconds: int
    triggers_dsq: bool
    status: str
    assessed_by_user_id: str
    assessed_at: str
    appeal_window_expires_at: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    penalty_id: str
    grounds: str
    status: str
    decision: Optional[str]
    reduced_seconds: Optional[int]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SafetyAssessment(TypedDict):
    id: str
    event_id: str
    water_temp_celsius: float
    lightning_within_10km: bool
    outcome: str
    status: str
    created_at: str
    updated_at: str
    version: int
