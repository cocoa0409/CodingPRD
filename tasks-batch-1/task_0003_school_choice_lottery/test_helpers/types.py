"""Domain types: entity TypedDicts, status enums, role enum.

All TypedDicts follow the envelope rules in PRD §2.4:
- Entities with id/created_at/updated_at/version carry all four.
- SiblingBond and SystemClock are leaner: id+created_at only (no updated_at,
  no version), per PRD §2.4 ("A `SiblingBond` carries only `id` and
  `created_at`... The `SystemClock` likewise carries no `updated_at` or
  `version`; it exposes only its `current_utc` reading.").
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    DISTRICT_ADMIN = "DistrictAdmin"
    GUARDIAN = "Guardian"
    ANONYMOUS = "Anonymous"


class DistrictStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class SchoolType(str, Enum):
    NEIGHBORHOOD = "NEIGHBORHOOD"
    MAGNET = "MAGNET"


class EnrollmentWindowStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    LOTTERY_RUN = "LOTTERY_RUN"
    FINALIZED = "FINALIZED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    WAITLISTED = "WAITLISTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    OFFERED = "OFFERED"
    DECLINED = "DECLINED"
    ENROLLED = "ENROLLED"


class OfferStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class OfferSource(str, Enum):
    LOTTERY = "LOTTERY"
    WAITLIST_PROMOTION = "WAITLIST_PROMOTION"


class WaitlistEntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROMOTED = "PROMOTED"
    REMOVED = "REMOVED"


# ---- Entities with full common-fields envelope (id/created_at/updated_at/version) ----

class District(TypedDict):
    id: str
    code: str
    name: str
    poverty_index_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class School(TypedDict):
    id: str
    district_id: str
    code: str
    name: str
    school_type: str
    grade_min: int
    grade_max: int
    total_seats: int
    created_at: str
    updated_at: str
    version: int


class BoundaryRule(TypedDict):
    id: str
    school_id: str
    zone_code: str
    is_in_boundary: bool
    created_at: str
    updated_at: str
    version: int


class EnrollmentWindow(TypedDict):
    id: str
    district_id: str
    cycle_label: str
    opens_at: str
    closes_at: str
    lottery_runs_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Family(TypedDict):
    id: str
    guardian_email: str
    residence_zone_code: str
    residence_district_id: str
    poverty_flag: bool
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    family_id: str
    full_name: str
    grade_for_cycle: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    window_id: str
    student_id: str
    school_id: str
    choice_rank: int
    inter_district_transfer: bool
    status: str
    lottery_weight: float
    lottery_rank: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict):
    id: str
    application_id: str
    status: str
    offered_at: str
    respond_by: str
    source: str
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict):
    id: str
    application_id: str
    school_id: str
    queue_rank: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---- Append-only / clock entities (PRD §2.4): id + created_at only ----

class SiblingBond(TypedDict):
    """Append-only declaration (PRD §2.4: carries only `id` and `created_at`)."""
    id: str
    student_id: str
    sibling_student_id: str
    school_id: str
    created_at: str


class SystemClock(TypedDict):
    """No id-collection lifecycle (PRD §2.4: exposes only its `current_utc`)."""
    current_utc: str
