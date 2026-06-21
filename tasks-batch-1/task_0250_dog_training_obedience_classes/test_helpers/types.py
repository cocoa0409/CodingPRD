"""Domain types: entity TypedDicts, status/state enums, role enum.

Derived from the Dog Training & Obedience Classes PRD (§2.9 vocabularies, §3 workflows).
Append-only audit records (VaccinationRecord, PackageRedemption, Certificate) carry only
`id` + `created_at` per PRD §2.4 — their TypedDicts omit `updated_at` and `version`.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum (PRD §2.1) ──────────────────────────────────────────────────────
class UserRole(str, Enum):
    OWNER = "Owner"
    TRAINER = "Trainer"
    FRONT_DESK = "FrontDesk"
    ADMIN_MANAGER = "AdminManager"


# ─── Status / state enums (PRD §2.9) ───────────────────────────────────────────
class ClassSeriesStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class ClassSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    PENDING_PREREQS = "PENDING_PREREQS"
    ACTIVE = "ACTIVE"
    WAITLISTED = "WAITLISTED"
    SUSPENDED = "SUSPENDED"
    GRADUATED = "GRADUATED"
    WITHDRAWN = "WITHDRAWN"


class PackageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"


class MakeupBookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class AttendanceState(str, Enum):
    EXPECTED = "EXPECTED"
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    MISSED_PROVIDER = "MISSED_PROVIDER"
    MAKEUP_PENDING = "MAKEUP_PENDING"
    MAKEUP_DONE = "MAKEUP_DONE"


class TrainerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ClassLevel(str, Enum):
    PUPPY = "PUPPY"
    BASIC = "BASIC"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"


class PrerequisiteLevel(str, Enum):
    NONE = "NONE"
    PUPPY = "PUPPY"
    BASIC = "BASIC"
    INTERMEDIATE = "INTERMEDIATE"


class Modality(str, Enum):
    PRIVATE = "PRIVATE"
    GROUP = "GROUP"


class PackageTier(str, Enum):
    STARTER = "STARTER"
    VALUE = "VALUE"
    PRO = "PRO"


class VaccineType(str, Enum):
    RABIES = "RABIES"
    DHPP = "DHPP"
    BORDETELLA = "BORDETELLA"


class VaccinationPosture(str, Enum):
    UNKNOWN = "UNKNOWN"
    COMPLIANT = "COMPLIANT"
    NONCOMPLIANT = "NONCOMPLIANT"


class IntakeStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"


class IntakeOutcome(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    PACKAGE = "PACKAGE"


class RedemptionKind(str, Enum):
    DEBIT = "DEBIT"
    REVERSAL = "REVERSAL"


# ─── Entity TypedDicts (common_fields: true → id+created_at+updated_at+version) ──
class Owner(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    email: str
    phone: str


class Trainer(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    certified_levels: List[str]
    handles_private: bool
    status: str


class Dog(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    owner_id: str
    name: str
    breed: str
    birth_date: str
    vaccination_posture: str
    highest_completed_level: str
    intake_status: str


class BehavioralIntake(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    dog_id: str
    reactivity_score: int
    bite_history: bool
    recommended_level: str
    outcome: str
    requires_private_first: bool


class ClassSeries(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    title: str
    level: str
    prerequisite_level: str
    modality: str
    capacity: int
    session_count: int
    list_price_cents: int
    credit_cost: int
    enrolled_count: int
    seats_available: int
    status: str


class ClassSession(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    series_id: str
    trainer_id: str
    sequence_index: int
    starts_at: str
    ends_at: str
    is_makeup_slot: bool
    status: str


class Enrollment(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    dog_id: str
    series_id: str
    payment_method: str
    package_id: Optional[str]
    price_charged_cents: int
    credits_debited: int
    sessions_attended: int
    sessions_remaining: int
    graduation_eligible: bool
    refund_cents: int
    credits_refunded: int
    status: str


class Package(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    owner_id: str
    tier: str
    credits_total: int
    price_paid_cents: int
    credits_consumed: int
    credits_remaining: int
    status: str


class AttendanceRecord(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    enrollment_id: str
    session_id: str
    state: str
    makeup_eligible: bool


class MakeupBooking(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    attendance_id: str
    makeup_session_id: str
    status: str


# ─── Append-only audit records (common_fields: false → id+created_at only) ──────
class VaccinationRecord(TypedDict):
    id: str
    created_at: str
    dog_id: str
    vaccine_type: str
    administered_on: str
    expires_on: str
    voided: bool


class PackageRedemption(TypedDict):
    id: str
    created_at: str
    package_id: str
    enrollment_id: str
    kind: str
    credits: int


class Certificate(TypedDict):
    id: str
    created_at: str
    enrollment_id: str
    dog_id: str
    level: str
    serial: str
