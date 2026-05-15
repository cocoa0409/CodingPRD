"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the entity contract defined in PRD §2.4 and §3. Entities
declared as carrying the uniform system-managed fields (District,
School, Program, Family, Student, Application, TransferRequest) include
id, created_at, updated_at, and version. The audit-and-singleton
entities (LotteryRun, WaitlistEvent, Clock) per PRD §2.4 carry only id
and (where applicable) created_at — they expose neither updated_at nor
version.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    SYSTEM_OPERATOR = "SystemOperator"
    DISTRICT_ADMIN = "DistrictAdmin"
    FAMILY_USER = "FamilyUser"


# ---------------------------------------------------------------------------
# School enum — PRD §3.1
# ---------------------------------------------------------------------------
class SchoolType(str, Enum):
    NEIGHBORHOOD = "NEIGHBORHOOD"
    MAGNET = "MAGNET"
    CHARTER = "CHARTER"


# ---------------------------------------------------------------------------
# Program window status — PRD §3.1, §3.5, §3.7
# ---------------------------------------------------------------------------
class ProgramWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    LOTTERY_DRAWN = "LOTTERY_DRAWN"
    BACKFILL = "BACKFILL"


# ---------------------------------------------------------------------------
# Application lifecycle status — PRD §3.4 / §3.5 / §3.6
# ---------------------------------------------------------------------------
class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WAITLISTED = "WAITLISTED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


# ---------------------------------------------------------------------------
# Application priority category — PRD §3.4
# ---------------------------------------------------------------------------
class PriorityCategory(str, Enum):
    SIBLING_IN_DISTRICT = "SIBLING_IN_DISTRICT"
    IN_DISTRICT_DISADVANTAGED = "IN_DISTRICT_DISADVANTAGED"
    IN_DISTRICT_STANDARD = "IN_DISTRICT_STANDARD"
    INTER_DISTRICT_DISADVANTAGED = "INTER_DISTRICT_DISADVANTAGED"
    INTER_DISTRICT_STANDARD = "INTER_DISTRICT_STANDARD"


# ---------------------------------------------------------------------------
# TransferRequest lifecycle status — PRD §3.3
# ---------------------------------------------------------------------------
class TransferRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


# ---------------------------------------------------------------------------
# Primary persisted entities (PRD §2.4) — carry the uniform
# id / created_at / updated_at / version system-managed fields.
# ---------------------------------------------------------------------------
class District(TypedDict, total=False):
    id: str
    name: str
    state_code: str
    accepts_inter_district_transfers: bool
    poverty_index_threshold: float
    created_at: str
    updated_at: str
    version: int


class School(TypedDict, total=False):
    id: str
    district_id: str
    name: str
    school_type: str
    grade_levels_offered: List[int]
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict, total=False):
    id: str
    school_id: str
    grade_level: int
    academic_year: int
    seats_total: int
    seats_offered: int
    seats_accepted: int
    registration_open_at: str
    registration_close_at: str
    lottery_seed: Optional[str]
    window_status: str
    created_at: str
    updated_at: str
    version: int


class Family(TypedDict, total=False):
    id: str
    residency_district_id: str
    poverty_index_score: float
    head_household_application_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    family_id: str
    grade_level_next_year: int
    has_iep: bool
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    student_id: str
    program_id: str
    choice_rank: int
    status: str
    priority_category: Optional[str]
    lottery_weight: Optional[float]
    lottery_score: Optional[float]
    waitlist_position: Optional[int]
    offer_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferRequest(TypedDict, total=False):
    id: str
    application_id: str
    target_district_id: str
    status: str
    capacity_units_held: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Audit-and-singleton entities (PRD §2.4) — immutable once written or
# server-controlled state; they carry only id and (where applicable)
# created_at. Neither updated_at nor version is present.
# ---------------------------------------------------------------------------
class LotteryRun(TypedDict, total=False):
    id: str
    program_id: str
    seed_used: str
    drawn_at: str
    applications_ranked: List[dict]
    offers_issued_count: int
    created_at: str


class WaitlistEvent(TypedDict, total=False):
    id: str
    program_id: str
    triggered_by_application_id: str
    promoted_application_id: Optional[str]
    occurred_at: str
    created_at: str


class Clock(TypedDict, total=False):
    id: str
    now: str


__all__ = [
    "UserRole",
    "SchoolType",
    "ProgramWindowStatus",
    "ApplicationStatus",
    "PriorityCategory",
    "TransferRequestStatus",
    "District",
    "School",
    "Program",
    "Family",
    "Student",
    "Application",
    "TransferRequest",
    "LotteryRun",
    "WaitlistEvent",
    "Clock",
]
