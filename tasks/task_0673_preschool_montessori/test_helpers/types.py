"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# ─── Enumerations ─────────────────────────────────────

class MontessoriLevel(str, Enum):
    TODDLER = "TODDLER"
    PRIMARY = "PRIMARY"
    ELEMENTARY = "ELEMENTARY"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    OVER_RATIO = "OVER_RATIO"
    OVER_CAPACITY = "OVER_CAPACITY"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    WAITLISTED = "WAITLISTED"
    OFFERED = "OFFERED"
    ENROLLED = "ENROLLED"
    WITHDRAWN = "WITHDRAWN"
    DECLINED = "DECLINED"


class PlacementStatus(str, Enum):
    PLACED = "PLACED"
    ON_LEAVE = "ON_LEAVE"
    WITHDRAWN = "WITHDRAWN"


class BillingStatus(str, Enum):
    DEPOSIT_DUE = "DEPOSIT_DUE"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    SETTLED = "SETTLED"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    INSTALLMENT = "INSTALLMENT"


class PaymentStatus(str, Enum):
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class RefundMethod(str, Enum):
    FORWARD = "FORWARD"
    CHRONOLOGICAL = "CHRONOLOGICAL"


class RefundStatus(str, Enum):
    COMPUTED = "COMPUTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    VOID = "VOID"


class StaffAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class WorkArea(str, Enum):
    PRACTICAL_LIFE = "PRACTICAL_LIFE"
    SENSORIAL = "SENSORIAL"
    LANGUAGE = "LANGUAGE"
    MATHEMATICS = "MATHEMATICS"
    CULTURAL = "CULTURAL"


class MasteryLevel(str, Enum):
    INTRODUCED = "INTRODUCED"
    PRACTICING = "PRACTICING"
    MASTERED = "MASTERED"


class ConferenceSlotStatus(str, Enum):
    OPEN = "OPEN"
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    REGISTRAR = "Registrar"
    GUIDE = "Guide"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PARENT = "Parent"


# ─── Entity TypedDicts ────────────────────────────────
# Every entity except Observation carries id + created_at + updated_at + version.
# Observation is immutable: id + created_at only.

class TuitionTier(TypedDict):
    id: str
    code: str
    level: str
    base_annual_cents: int
    deposit_pct: float
    installments: int
    extended_day_annual_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Classroom(TypedDict):
    id: str
    name: str
    level: str
    capacity: int
    min_age_months: int
    max_age_months: int
    placed_count: int
    assigned_staff_count: int
    compliance_status: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    parent_user_id: str
    full_name: str
    date_of_birth: str
    sibling_of_student_id: Optional[str]
    staff_child: bool
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    student_id: str
    classroom_id: str
    tier_id: str
    status: str
    priority_score: int
    waitlisted_at: Optional[str]
    enrollment_id: Optional[str]
    extended_day_opt_in: bool
    financial_aid_pct: float
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    application_id: str
    student_id: str
    classroom_id: str
    tier_id: str
    placement_status: str
    billing_status: str
    extended_day_opt_in: bool
    program_start_date: str
    net_annual_cents: int
    monthly_installment_cents: int
    deposit_cents: int
    paid_to_date_cents: int
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    enrollment_id: str
    kind: str
    amount_cents: int
    status: str
    captured_at: str
    created_at: str
    updated_at: str
    version: int


class RefundRequest(TypedDict):
    id: str
    enrollment_id: str
    effective_date: str
    method: str
    status: str
    earned_cents: int
    refund_cents: int
    balance_due_cents: int
    created_at: str
    updated_at: str
    version: int


class StaffAssignment(TypedDict):
    id: str
    classroom_id: str
    staff_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AssessmentRecord(TypedDict):
    id: str
    student_id: str
    enrollment_id: str
    work_area: str
    mastery_level: str
    work_cycle_date: str
    portfolio_included: bool
    created_at: str
    updated_at: str
    version: int


class ConferenceSlot(TypedDict):
    id: str
    guide_user_id: str
    classroom_id: str
    start_at: str
    end_at: str
    status: str
    booked_student_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Observation is immutable (no updated_at, no version).
class Observation(TypedDict):
    id: str
    classroom_id: str
    observer_name: str
    window_start_at: str
    window_end_at: str
    created_at: str
