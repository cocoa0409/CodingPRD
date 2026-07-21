"""Domain types: entity TypedDicts, status enums, role enum for the Student Travel EF API."""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Role enum
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    OPERATOR = "Operator"
    GROUP_LEADER = "GroupLeader"
    TRAVELER = "Traveler"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class DepartureStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    GUARANTEED = "GUARANTEED"
    DEPARTED = "DEPARTED"
    CANCELLED = "CANCELLED"


class EnrollmentLifecycleStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    TRAVELING = "TRAVELING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EnrollmentPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIAL = "PARTIAL"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUNDED = "REFUNDED"


class PaymentPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAID = "PAID"
    REFUND_DUE = "REFUND_DUE"
    REFUNDED = "REFUNDED"
    SUPERSEDED = "SUPERSEDED"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    INSTALLMENT = "INSTALLMENT"
    REFUND = "REFUND"
    PENALTY_RETAINED = "PENALTY_RETAINED"


class PermissionFormStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"


class ChaperoneStatus(str, Enum):
    CONFIRMED = "CONFIRMED"


class RoomingStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class SupplierBookingStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class Gender(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    NONBINARY = "NONBINARY"


class RoomType(str, Enum):
    DOUBLE = "DOUBLE"
    TRIPLE = "TRIPLE"
    QUAD = "QUAD"


class ServiceType(str, Enum):
    HOTEL = "HOTEL"
    BUS = "BUS"
    GUIDE = "GUIDE"
    FLIGHT = "FLIGHT"


class CancelReason(str, Enum):
    TRAVELER_REQUEST = "TRAVELER_REQUEST"
    DEPARTURE_CANCELLED = "DEPARTURE_CANCELLED"
    REBOOK = "REBOOK"


class RoleType(str, Enum):
    TEACHER = "TEACHER"
    ADULT = "ADULT"


class InsuranceTier(str, Enum):
    BASIC = "BASIC"
    PREMIUM = "PREMIUM"


class AddOn(str, Enum):
    SINGLE_ROOM = "SINGLE_ROOM"
    EXCURSION = "EXCURSION"
    STEM_LAB = "STEM_LAB"


# --------------------------------------------------------------------------
# Entity TypedDicts
# Entities carrying id + created_at + updated_at + version (common fields).
# --------------------------------------------------------------------------
class Tour(TypedDict):
    id: str
    name: str
    destination: str
    nights: int
    base_price_cents: int
    created_at: str
    updated_at: str
    version: int


class GroupLeader(TypedDict):
    id: str
    full_name: str
    email: str
    school_name: str
    free_spot_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Departure(TypedDict):
    id: str
    tour_id: str
    group_leader_id: str
    depart_date: str
    return_date: str
    enrollment_deadline: str
    early_bird_cutoff: str
    capacity: int
    price_per_traveler_cents: int
    min_to_guarantee: int
    chaperone_ratio: int
    status: str
    active_enrollment_count: int
    paid_in_full_count: int
    free_spots_earned: int
    available_seats: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    departure_id: str
    traveler_name: str
    traveler_dob: str
    traveler_gender: str
    add_ons: List[str]
    insurance_opted: bool
    insurance_tier: Optional[str]
    price_locked_cents: int
    lifecycle_status: str
    payment_status: str
    doc_complete: bool
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaymentPlan(TypedDict):
    id: str
    enrollment_id: str
    total_cents: int
    deposit_cents: int
    installment_count: int
    installment_amounts: List[int]
    amount_paid_cents: int
    amount_refunded_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PermissionForm(TypedDict):
    id: str
    enrollment_id: str
    passport_number: str
    passport_expiry: str
    guardian_consent: bool
    medical_notes: Optional[str]
    dietary: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Chaperone(TypedDict):
    id: str
    departure_id: str
    full_name: str
    email: str
    role_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RoomingAssignment(TypedDict):
    id: str
    departure_id: str
    room_label: str
    room_type: str
    room_gender: str
    capacity: int
    member_enrollment_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict):
    id: str
    name: str
    service_type: str
    city: str
    created_at: str
    updated_at: str
    version: int


class SupplierBooking(TypedDict):
    id: str
    departure_id: str
    supplier_id: str
    service_window_start: str
    service_window_end: str
    room_block: int
    cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only entity — Payment carries ONLY id + created_at
# (no updated_at, no version: it is an immutable ledger row).
# --------------------------------------------------------------------------
class Payment(TypedDict):
    id: str
    payment_plan_id: str
    amount_cents: int
    kind: str
    memo: Optional[str]
    created_at: str
