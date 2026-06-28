"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class SessionStatus(str, Enum):
    PLANNING = "PLANNING"
    ENROLLING = "ENROLLING"
    RUNNING = "RUNNING"
    CLOSED = "CLOSED"


class RatioPosture(str, Enum):
    STAFFED = "STAFFED"
    MARGINAL = "MARGINAL"
    UNDERSTAFFED = "UNDERSTAFFED"


class CabinGenderBand(str, Enum):
    BOYS = "BOYS"
    GIRLS = "GIRLS"
    ALL = "ALL"


class StaffRoleKind(str, Enum):
    COUNSELOR = "COUNSELOR"
    CIT = "CIT"


class CabinAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class CamperGender(str, Enum):
    BOY = "BOY"
    GIRL = "GIRL"


class CamperHealthStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"


class EnrollStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    WAITLISTED = "WAITLISTED"
    OFFERED = "OFFERED"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    ENROLLED = "ENROLLED"
    WITHDRAWN = "WITHDRAWN"


class PaymentStatus(str, Enum):
    UNBILLED = "UNBILLED"
    DEPOSIT_DUE = "DEPOSIT_DUE"
    DEPOSIT_SETTLED = "DEPOSIT_SETTLED"
    BALANCE_DUE = "BALANCE_DUE"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUND_DUE = "REFUND_DUE"


class HealthFormStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"


class AidKind(str, Enum):
    NEED_GRANT = "NEED_GRANT"
    MERIT_SCHOLARSHIP = "MERIT_SCHOLARSHIP"


class AidStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"


class PaymentRecordStatus(str, Enum):
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class ActivityEnrollmentStatus(str, Enum):
    BOOKED = "BOOKED"
    DROPPED = "DROPPED"


class CanteenTxnKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    PURCHASE = "PURCHASE"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    GUARDIAN = "Guardian"
    CAMP_DIRECTOR = "CampDirector"
    INFIRMARY_NURSE = "InfirmaryNurse"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Entities below all carry id + created_at + updated_at + version,
# except CanteenTransaction which is append-only (id + created_at only).
# ---------------------------------------------------------------------------
class Camp(TypedDict):
    id: str
    name: str
    counselor_camper_ratio: int
    cit_counts_as_half: bool
    deposit_cents: int
    deposit_grace_days: int
    canteen_low_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    camp_id: str
    name: str
    starts_on: str
    ends_on: str
    visiting_day_on: str
    enrollment_open: bool
    capacity: int
    enrolled_count: int
    committed_count: int
    waitlist_length: int
    ratio_posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Cabin(TypedDict):
    id: str
    session_id: str
    name: str
    gender_band: str
    min_age: int
    max_age: int
    bunk_capacity: int
    occupied_bunks: int
    staff_weight_x10: int
    is_staffable: bool
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict):
    id: str
    camp_id: str
    full_name: str
    role_kind: str
    is_background_cleared: bool
    created_at: str
    updated_at: str
    version: int


class CabinAssignment(TypedDict):
    id: str
    cabin_id: str
    staff_member_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Camper(TypedDict):
    id: str
    guardian_user_id: str
    full_name: str
    age: int
    gender: str
    health_status: str
    created_at: str
    updated_at: str
    version: int


class Guardian(TypedDict):
    id: str
    email: str
    full_name: str
    phone: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    camper_id: str
    session_id: str
    cabin_id: Optional[str]
    enroll_status: str
    payment_status: str
    submitted_at: Optional[str]
    offer_expires_at: Optional[str]
    list_tuition_cents: int
    aid_cents: int
    estimated_balance_cents: int
    settled_balance_cents: int
    deposit_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class HealthForm(TypedDict):
    id: str
    camper_id: str
    has_life_threatening_allergy: bool
    epipen_on_file: bool
    daily_medication_count: int
    status: str
    review_note: str
    created_at: str
    updated_at: str
    version: int


class FinancialAidAward(TypedDict):
    id: str
    application_id: str
    kind: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    application_id: str
    kind: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ActivityOffering(TypedDict):
    id: str
    session_id: str
    name: str
    slot_day: int
    starts_minute: int
    ends_minute: int
    setup_buffer_minutes: int
    seat_capacity: int
    requires_swim_test: bool
    seats_taken: int
    created_at: str
    updated_at: str
    version: int


class ActivityEnrollment(TypedDict):
    id: str
    offering_id: str
    application_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CanteenAccount(TypedDict):
    id: str
    application_id: str
    balance_cents: int
    is_low: bool
    created_at: str
    updated_at: str
    version: int


# Append-only event: id + created_at only (no updated_at, no version)
class CanteenTransaction(TypedDict):
    id: str
    account_id: str
    kind: str
    amount_cents: int
    created_at: str
