"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity narratives (§2.5, §3) and endpoint table (§4).
TimingRead is the append-only exception of PRD §2.5: it carries only
`id` and `created_at` — no `updated_at`, no `version`.
"""
from enum import Enum
from typing import Optional, TypedDict


class CourseType(str, Enum):
    CERTIFIED_COURSE = "CERTIFIED_COURSE"
    UNCERTIFIED_COURSE = "UNCERTIFIED_COURSE"


class RaceStatus(str, Enum):
    DRAFT = "DRAFT"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    TIMING_LOCKED = "TIMING_LOCKED"
    IN_PROGRESS = "IN_PROGRESS"
    PROVISIONAL_PUBLISHED = "PROVISIONAL_PUBLISHED"
    FINALIZED = "FINALIZED"
    AMENDMENT_OPEN = "AMENDMENT_OPEN"


class WaveStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    STARTED = "STARTED"


class TimingPointKind(str, Enum):
    START = "START"
    SPLIT = "SPLIT"
    FINISH = "FINISH"


class TimingPointStatus(str, Enum):
    PLANNED = "PLANNED"
    DEPLOYED = "DEPLOYED"


class LifecycleStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    WITHDRAWN = "WITHDRAWN"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class Gender(str, Enum):
    M = "M"
    F = "F"


class ChipStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    LOST = "LOST"


class TimingReadStatus(str, Enum):
    SCORED = "SCORED"
    REJECTED = "REJECTED"
    EXCLUDED = "EXCLUDED"


class RejectReason(str, Enum):
    CHIP_NOT_CHECKED_IN = "CHIP_NOT_CHECKED_IN"


class ResultStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    OFFICIAL = "OFFICIAL"
    AMENDED = "AMENDED"
    EXCLUDED = "EXCLUDED"


class ExclusionReason(str, Enum):
    DNF = "DNF"
    DQ = "DQ"
    COURSE_CUT_SUSPECT = "COURSE_CUT_SUSPECT"


class FlagType(str, Enum):
    DNF = "DNF"
    DQ = "DQ"
    COURSE_CUT_SUSPECT = "COURSE_CUT_SUSPECT"


class FlagOrigin(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


class FlagStatus(str, Enum):
    RAISED = "RAISED"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class ProtestAction(str, Enum):
    EXCLUDE_READ = "EXCLUDE_READ"
    REINSTATE_READ = "REINSTATE_READ"
    ADJUST_READ_TIME = "ADJUST_READ_TIME"


class ProtestStatus(str, Enum):
    FILED = "FILED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class CorrectionKind(str, Enum):
    EXCLUDE_READ = "EXCLUDE_READ"
    REINSTATE_READ = "REINSTATE_READ"
    ADJUST_READ_TIME = "ADJUST_READ_TIME"


class CorrectionStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CertificationStatus(str, Enum):
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"


class AwardBasis(str, Enum):
    GUN = "GUN"
    CHIP = "CHIP"


class AwardStatus(str, Enum):
    PROJECTED = "PROJECTED"
    CONFIRMED = "CONFIRMED"
    REVOKED = "REVOKED"


class UserRole(str, Enum):
    RACE_DIRECTOR = "RaceDirector"
    TIMING_OPERATOR = "TimingOperator"
    REGISTRATION_CLERK = "RegistrationClerk"
    RACE_OFFICIAL = "RaceOfficial"
    CERTIFICATION_OFFICER = "CertificationOfficer"
    SPECTATOR = "Spectator"


class Race(TypedDict, total=False):
    id: str
    name: str
    race_date: str
    distance_km: float
    course_type: str
    course_time_limit_minutes: int
    qualifying_standard_ms: Optional[int]
    status: str
    timing_locked_at: Optional[str]
    locked_by_user_id: Optional[str]
    timing_config_fingerprint: Optional[str]
    provisional_published_at: Optional[str]
    protest_window_closes_at: Optional[str]
    finalized_at: Optional[str]
    amendment_count: int
    created_at: str
    updated_at: str
    version: int


class Wave(TypedDict, total=False):
    id: str
    race_id: str
    wave_index: int
    scheduled_start_time: str
    max_capacity: int
    actual_start_time: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TimingPoint(TypedDict, total=False):
    id: str
    race_id: str
    point_index: int
    kind: str
    distance_km: float
    device_id: str
    deploy_at: str
    expected_teardown_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict, total=False):
    id: str
    race_id: str
    wave_id: str
    chip_id: Optional[str]
    bib_number: str
    participant_name: str
    birth_date: str
    gender: str
    lifecycle_status: str
    payment_status: str
    age_on_race_day: int
    age_group: str
    created_at: str
    updated_at: str
    version: int


class Chip(TypedDict, total=False):
    id: str
    chip_code: str
    status: str
    current_registration_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only event log (PRD §2.5): carries ONLY id + created_at.
# No updated_at, no version.
class TimingRead(TypedDict, total=False):
    id: str
    timing_point_id: str
    chip_id: str
    read_timestamp: str
    status: str
    reject_reason: Optional[str]
    adjusted_by_correction_id: Optional[str]
    created_at: str


class Result(TypedDict, total=False):
    id: str
    race_id: str
    registration_id: str
    status: str
    exclusion_reason: Optional[str]
    chip_time_ms: Optional[int]
    gun_time_ms: Optional[int]
    finish_timestamp: Optional[str]
    completed_splits: int
    overall_rank_gun: Optional[int]
    age_group_rank_chip: Optional[int]
    qualified: bool
    revision: int
    created_at: str
    updated_at: str
    version: int


class ResultFlag(TypedDict, total=False):
    id: str
    registration_id: str
    flag_type: str
    origin: str
    status: str
    detail: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Protest(TypedDict, total=False):
    id: str
    race_id: str
    registration_id: str
    timing_read_id: str
    requested_action: str
    corrected_timestamp: Optional[str]
    reason: str
    filed_by_user_id: str
    status: str
    resolved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Correction(TypedDict, total=False):
    id: str
    race_id: str
    timing_read_id: str
    kind: str
    corrected_timestamp: Optional[str]
    reason: str
    protest_id: Optional[str]
    status: str
    adjudicated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict, total=False):
    id: str
    race_id: str
    status: str
    issued_by_user_id: str
    issued_at: str
    qualified_count: int
    revocation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Award(TypedDict, total=False):
    id: str
    race_id: str
    registration_id: str
    category: str
    place: int
    basis: str
    basis_time_ms: int
    status: str
    created_at: str
    updated_at: str
    version: int
