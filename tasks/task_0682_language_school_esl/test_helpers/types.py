"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the Language School ESL API contract (PRD §3). Append-only entities
(AttendanceRecord, ComplianceEvent) carry only id + created_at — no updated_at
or version — per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    REGISTRAR = "Registrar"
    DSO = "DSO"
    INSTRUCTOR = "Instructor"
    STUDENT = "Student"
    CORPORATE_SPONSOR = "CorporateSponsor"
    ANONYMOUS = "Anonymous"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class VisaStatus(str, Enum):
    NONE = "NONE"
    INITIAL = "INITIAL"
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    TERMINATED = "TERMINATED"


class CertificationStatus(str, Enum):
    NONE = "NONE"
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"
    VOIDED = "VOIDED"


class Track(str, Enum):
    GENERAL = "GENERAL"
    ACADEMIC = "ACADEMIC"
    BUSINESS = "BUSINESS"
    EXAM_PREP = "EXAM_PREP"


class CEFRLevel(str, Enum):
    A1 = "A1"
    A2 = "A2"
    B1 = "B1"
    B2 = "B2"
    C1 = "C1"
    C2 = "C2"


class PlacementTestStatus(str, Enum):
    REGISTERED = "REGISTERED"
    SCORED = "SCORED"
    VOIDED = "VOIDED"


class CohortStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"


class EnrollmentStatus(str, Enum):
    PLACEMENT_PENDING = "PLACEMENT_PENDING"
    ENROLLED = "ENROLLED"
    WAITLISTED = "WAITLISTED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"
    TERMINATED = "TERMINATED"


class TerminationReason(str, Enum):
    VISA_NONCOMPLIANCE = "VISA_NONCOMPLIANCE"
    ATTENDANCE_FAILURE = "ATTENDANCE_FAILURE"
    CONTRACT_REVOKED = "CONTRACT_REVOKED"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"


class DiscountTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class AddOnType(str, Enum):
    CONVERSATION_CLUB = "CONVERSATION_CLUB"
    PRIVATE_TUTORING = "PRIVATE_TUTORING"
    IMMERSION_ABROAD = "IMMERSION_ABROAD"


class AddOnStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class AttendanceMark(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    EXCUSED = "EXCUSED"


class ComplianceEventType(str, Enum):
    I20_ISSUED = "I20_ISSUED"
    STATUS_ACTIVATED = "STATUS_ACTIVATED"
    PROBATION_PLACED = "PROBATION_PLACED"
    PROBATION_CLEARED = "PROBATION_CLEARED"
    I20_TERMINATED = "I20_TERMINATED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields:true carry id/created_at/updated_at/version
# ---------------------------------------------------------------------------
class Student(TypedDict):
    id: str
    full_name: str
    email: str
    is_international: bool
    corporate_contract_id: Optional[str]
    placement_level: Optional[str]
    track: str
    visa_status: str
    i20_required_weekly_hours: int
    certification_status: str
    final_progress_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class CorporateContract(TypedDict):
    id: str
    company_name: str
    contracted_seats: int
    seats_consumed: int
    discount_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PlacementTest(TypedDict):
    id: str
    student_id: str
    raw_score: Optional[int]
    assigned_level: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Cohort(TypedDict):
    id: str
    name: str
    level: str
    track: str
    capacity: int
    weekly_hours: int
    term_start: str
    term_end: str
    total_sessions: int
    base_tuition_cents: int
    seats_taken: int
    schedule_block: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    student_id: str
    cohort_id: str
    status: str
    enrolled_at: Optional[str]
    sessions_attended: int
    sessions_elapsed: int
    attendance_rate: float
    tuition_invoice_cents: int
    refund_cents: int
    completion_score: Optional[float]
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProgressReport(TypedDict):
    id: str
    enrollment_id: str
    speaking: int
    listening: int
    reading: int
    writing: int
    assessed_at: str
    created_at: str
    updated_at: str
    version: int


class AddOnSubscription(TypedDict):
    id: str
    student_id: str
    add_on_type: str
    enrollment_id: str
    units: int
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities (common_fields:false) — only id + created_at (PRD §2.4)
# ---------------------------------------------------------------------------
class AttendanceRecord(TypedDict):
    id: str
    enrollment_id: str
    session_index: int
    status: str
    recorded_at: str
    created_at: str


class ComplianceEvent(TypedDict):
    id: str
    student_id: str
    event_type: str
    prior_status: str
    new_status: str
    reason: Optional[str]
    recorded_at: str
    created_at: str
