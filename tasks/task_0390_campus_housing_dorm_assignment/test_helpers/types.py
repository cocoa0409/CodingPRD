"""Domain types: entity TypedDicts, status enums, and the role enum.

Every entity in this domain is mutable, so each entity carries the common audit
fields id, created_at, updated_at, and version (see PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum (PRD §2.1) ─────────────────────────────────────────────────────

class UserRole(str, Enum):
    HOUSING_OFFICER = "HousingOfficer"
    STUDENT = "Student"
    RESIDENT_ADVISOR = "ResidentAdvisor"


# ─── Status / enum value sets ─────────────────────────────────────────────────

class BuildingType(str, Enum):
    TRADITIONAL = "TRADITIONAL"
    SUITE = "SUITE"
    APARTMENT = "APARTMENT"


class RoomType(str, Enum):
    SINGLE = "SINGLE"
    DOUBLE = "DOUBLE"
    TRIPLE = "TRIPLE"
    SUITE_DOUBLE = "SUITE_DOUBLE"


class GenderInclusivity(str, Enum):
    SINGLE_GENDER = "SINGLE_GENDER"
    ALL_GENDER = "ALL_GENDER"


class RoomStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    OFFLINE = "OFFLINE"


class ClassYear(str, Enum):
    FRESHMAN = "FRESHMAN"
    SOPHOMORE = "SOPHOMORE"
    JUNIOR = "JUNIOR"
    SENIOR = "SENIOR"


class GenderIdentity(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    NONBINARY = "NONBINARY"


class StudentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    HOLD = "HOLD"


class CyclePhase(str, Enum):
    APPLICATION_OPEN = "APPLICATION_OPEN"
    LOTTERY_RUN = "LOTTERY_RUN"
    ASSIGNMENT_OPEN = "ASSIGNMENT_OPEN"
    CLOSED = "CLOSED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    OFFERED = "OFFERED"
    WAITLISTED = "WAITLISTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class PreferredBuildingType(str, Enum):
    TRADITIONAL = "TRADITIONAL"
    SUITE = "SUITE"
    APARTMENT = "APARTMENT"
    NO_PREFERENCE = "NO_PREFERENCE"


class PreferredRoomType(str, Enum):
    SINGLE = "SINGLE"
    DOUBLE = "DOUBLE"
    TRIPLE = "TRIPLE"
    SUITE_DOUBLE = "SUITE_DOUBLE"
    NO_PREFERENCE = "NO_PREFERENCE"


class RoommateGroupStatus(str, Enum):
    FORMING = "FORMING"
    LOCKED = "LOCKED"
    DISBANDED = "DISBANDED"


class MembershipStatus(str, Enum):
    INVITED = "INVITED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    REMOVED = "REMOVED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SWAP_PENDING = "SWAP_PENDING"
    VACATED = "VACATED"
    CHECKED_OUT = "CHECKED_OUT"


class MealPlanTier(str, Enum):
    NONE = "NONE"
    COMMUTER = "COMMUTER"
    STANDARD = "STANDARD"
    UNLIMITED = "UNLIMITED"


class MealPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class WaitlistStatus(str, Enum):
    QUEUED = "QUEUED"
    PROMOTED = "PROMOTED"
    CANCELLED = "CANCELLED"


class DamageCategory(str, Enum):
    CLEANING = "CLEANING"
    REPAIR = "REPAIR"
    REPLACEMENT = "REPLACEMENT"
    LOST_KEY = "LOST_KEY"


class SplitBasis(str, Enum):
    SOLE = "SOLE"
    SHARED = "SHARED"


class DamageChargeStatus(str, Enum):
    PENDING = "PENDING"
    BILLED = "BILLED"
    WAIVED = "WAIVED"
    PAID = "PAID"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class BreakRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


# ─── Entity TypedDicts (all mutable → all carry updated_at + version) ──────────

class Building(TypedDict):
    id: str
    name: str
    building_type: str
    offers_break_housing: bool
    break_housing_capacity: int
    total_bed_count: int
    occupied_bed_count: int
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    building_id: str
    room_number: str
    room_type: str
    bed_capacity: int
    gender_inclusivity: str
    nightly_break_rate_cents: int
    occupied_bed_count: int
    open_incident_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    full_name: str
    class_year: str
    gender_identity: str
    lottery_number: int
    account_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HousingCycle(TypedDict):
    id: str
    term_label: str
    phase: str
    lottery_run_index: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    cycle_id: str
    student_id: str
    roommate_group_id: Optional[str]
    preferred_building_type: str
    preferred_room_type: str
    priority_rank: Optional[int]
    status: str
    offered_room_id: Optional[str]
    offer_lottery_index: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RoommateGroup(TypedDict):
    id: str
    cycle_id: str
    owner_student_id: str
    target_size: int
    accepted_member_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RoommateMembership(TypedDict):
    id: str
    group_id: str
    student_id: str
    membership_status: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    room_id: str
    student_id: str
    application_id: str
    swap_counterparty_assignment_id: Optional[str]
    status: str
    checkout_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MealPlan(TypedDict):
    id: str
    assignment_id: str
    tier: str
    weekly_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict):
    id: str
    cycle_id: str
    application_id: str
    priority_rank_snapshot: int
    lottery_number_snapshot: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageCharge(TypedDict):
    id: str
    assignment_id: str
    room_id: str
    category: str
    assessed_cents: int
    amount_cents: Optional[int]
    split_basis: str
    status: str
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict):
    id: str
    room_id: str
    reporter_student_id: str
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BreakHousingRequest(TypedDict):
    id: str
    assignment_id: str
    room_id: str
    check_in_date: str
    check_out_date: str
    night_count: int
    total_charge_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
