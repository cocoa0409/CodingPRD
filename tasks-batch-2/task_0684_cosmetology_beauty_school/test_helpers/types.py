"""Domain types: entity TypedDicts, status enums, and the role enum.

These mirror the entities and lifecycle states defined in the PRD. Every
entity in this domain carries the common id/created_at/updated_at/version
fields (PRD §2.4 states there are no version-less or immutable entities).
"""
from enum import Enum
from typing import TypedDict, List


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    REGISTRAR = "Registrar"
    FINANCIAL_AID_OFFICER = "FinancialAidOfficer"
    INSTRUCTOR = "Instructor"
    STUDENT = "Student"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class StudentStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ENROLLED = "ENROLLED"
    ARCHIVED = "ARCHIVED"


class StationType(str, Enum):
    HAIR = "HAIR"
    NAIL = "NAIL"
    SKIN = "SKIN"
    MAKEUP = "MAKEUP"


class StationStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SAP_WARNING = "SAP_WARNING"
    EXAM_PENDING = "EXAM_PENDING"
    GRADUATED = "GRADUATED"
    WITHDRAWN = "WITHDRAWN"


class PlacementStatus(str, Enum):
    UNREPORTED = "UNREPORTED"
    PLACED = "PLACED"
    UNPLACED = "UNPLACED"
    EXCLUDED = "EXCLUDED"


class AttendanceStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    VOIDED = "VOIDED"


class AttendanceType(str, Enum):
    REGULAR = "REGULAR"
    MAKEUP = "MAKEUP"


class ClinicTicketStatus(str, Enum):
    OPEN = "OPEN"
    SIGNED_OFF = "SIGNED_OFF"
    PAID = "PAID"
    VOIDED = "VOIDED"


class StationAssignmentStatus(str, Enum):
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"


class DisbursementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    POSTED = "POSTED"
    RETURNED = "RETURNED"


class ExamType(str, Enum):
    WRITTEN = "WRITTEN"
    PRACTICAL = "PRACTICAL"


class ExamApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class WithdrawalType(str, Enum):
    OFFICIAL = "OFFICIAL"
    UNOFFICIAL = "UNOFFICIAL"


class WithdrawalStatus(str, Enum):
    CALCULATED = "CALCULATED"
    FINALIZED = "FINALIZED"


# --------------------------------------------------------------------------
# Entity TypedDicts — every entity carries id/created_at/updated_at/version
# --------------------------------------------------------------------------
class Program(TypedDict):
    id: str
    name: str
    total_clock_hours: int
    tuition_cents: int
    kit_fee_cents: int
    lab_fee_cents: int
    clock_hours_per_credit: float
    clinic_phase_start_hour: int
    credit_hours: int
    admin_fee_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    full_name: str
    email: str
    ssn_last4: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict):
    id: str
    full_name: str
    license_number: str
    license_expires_on: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Station(TypedDict):
    id: str
    label: str
    station_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    student_id: str
    program_id: str
    enrolled_on_iso: str
    status: str
    scheduled_hours_to_date: int
    actual_hours: float
    pace_pct: float
    total_charges_cents: int
    total_credits_cents: int
    ledger_balance_cents: int
    projected_balance_cents: int
    sap_warning_count: int
    last_attendance_iso: str
    placement_status: str
    created_at: str
    updated_at: str
    version: int


class AttendanceRecord(TypedDict):
    id: str
    enrollment_id: str
    instructor_id: str
    session_date_iso: str
    scheduled_hours: float
    hours: float
    record_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ClinicTicket(TypedDict):
    id: str
    enrollment_id: str
    station_id: str
    instructor_id: str
    client_name: str
    start_iso: str
    end_iso: str
    line_items: List[dict]
    clinic_discount_pct: float
    ticket_total_cents: int
    clinic_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class StationAssignment(TypedDict):
    id: str
    station_id: str
    enrollment_id: str
    instructor_id: str
    start_iso: str
    end_iso: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict):
    id: str
    enrollment_id: str
    payment_period: int
    period_hours: int
    period_weeks: int
    gross_amount_cents: int
    origination_fee_cents: int
    net_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExamApplication(TypedDict):
    id: str
    enrollment_id: str
    exam_type: str
    mock_exam_avg: float
    competency_signoff_pct: float
    readiness_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Withdrawal(TypedDict):
    id: str
    enrollment_id: str
    withdrawal_type: str
    last_date_of_attendance_iso: str
    pct_completed: float
    title_iv_return_cents: int
    institutional_refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
