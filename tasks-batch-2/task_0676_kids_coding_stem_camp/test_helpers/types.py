"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD entity model and lifecycle narratives. Every persisted
resource carries the full common-field set (id, created_at, updated_at, version)
per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum (PRD §2.1) ─────────────────────────────────────────────
class UserRole(str, Enum):
    CENTER_ADMIN = "CenterAdmin"
    INSTRUCTOR = "Instructor"
    GUARDIAN = "Guardian"


# ─── Status enums ─────────────────────────────────────────────────────
class BadgeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class MembershipStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class SessionStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FULL = "FULL"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class SessionFormat(str, Enum):
    AFTER_SCHOOL = "AFTER_SCHOOL"
    WEEKLY = "WEEKLY"
    CAMP = "CAMP"


class EnrollmentCoverage(str, Enum):
    DROP_IN = "DROP_IN"
    MEMBERSHIP = "MEMBERSHIP"


class AttendanceStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_IN = "CHECKED_IN"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    CHARGED = "CHARGED"
    COVERED = "COVERED"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


class BadgeAwardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class ShowcaseStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    JUDGING = "JUDGING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ShowcaseEntryStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    SCORED = "SCORED"


# ─── Entity TypedDicts (all carry the full common-field set per PRD §2.4) ─
class Center(TypedDict):
    id: str
    name: str
    device_count: int
    min_student_instructor_ratio: int
    timezone: str
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict):
    id: str
    name: str
    code: str
    min_age: int
    max_age: int
    drop_in_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class BeltLevel(TypedDict):
    id: str
    program_id: str
    name: str
    rank: int
    prereq_belt_level_id: Optional[str]
    required_badge_count: int
    created_at: str
    updated_at: str
    version: int


class Badge(TypedDict):
    id: str
    belt_level_id: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Guardian(TypedDict):
    id: str
    full_name: str
    email: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    guardian_id: str
    program_id: str
    full_name: str
    birth_date: str
    current_belt_level_id: str
    active_badge_count: int
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    member_id: str
    monthly_fee_cents: int
    included_sessions_per_cycle: int
    sessions_used_this_cycle: int
    status: str
    cycle_index: int
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    center_id: str
    program_id: str
    format: str
    week_count: int
    starts_at: str
    ends_at: str
    device_seats_requested: int
    assigned_instructor_count: int
    status: str
    confirmed_seat_count: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    session_id: str
    member_id: str
    coverage: str
    sibling_index: int
    price_cents: int
    wallet_applied_cents: int
    attendance_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class BadgeAward(TypedDict):
    id: str
    enrollment_id: str
    badge_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Showcase(TypedDict):
    id: str
    center_id: str
    program_id: str
    min_belt_rank: int
    capacity: int
    starts_at: str
    entry_deadline_at: str
    status: str
    accepted_entry_count: int
    created_at: str
    updated_at: str
    version: int


class ShowcaseEntry(TypedDict):
    id: str
    showcase_id: str
    member_id: str
    score: Optional[float]
    rank: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
