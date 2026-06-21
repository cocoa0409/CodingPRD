"""Domain types: entity TypedDicts, status enums, role enum.

All field names and enum values are taken verbatim from the PRD contract for the
K-12 Field Trip & Permission Management API.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    TEACHER = "Teacher"
    PRINCIPAL = "Principal"
    DISTRICT_ADMIN = "DistrictAdmin"
    GUARDIAN = "Guardian"


# ─── Status enums ─────────────────────────────────────────────────────────────
class FieldTripStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_PRINCIPAL = "PENDING_PRINCIPAL"
    PENDING_DISTRICT = "PENDING_DISTRICT"
    APPROVED = "APPROVED"
    ROSTER_LOCKED = "ROSTER_LOCKED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class GradeBand(str, Enum):
    ELEMENTARY = "ELEMENTARY"
    MIDDLE = "MIDDLE"
    HIGH = "HIGH"


class SignatureStatus(str, Enum):
    UNSIGNED = "UNSIGNED"
    SIGNED = "SIGNED"
    REVOKED = "REVOKED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class ParticipationStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    WITHDRAWN = "WITHDRAWN"


class ChaperoneStatus(str, Enum):
    INVITED = "INVITED"
    CONFIRMED = "CONFIRMED"
    CLEARED = "CLEARED"
    WITHDRAWN = "WITHDRAWN"


class TransportBookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class VehicleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ScholarshipGrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class ApprovalStep(str, Enum):
    PRINCIPAL = "PRINCIPAL"
    DISTRICT = "DISTRICT"


class ApprovalDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ActorRole(str, Enum):
    PRINCIPAL = "PRINCIPAL"
    DISTRICT_ADMIN = "DISTRICT_ADMIN"


class FeeKind(str, Enum):
    PAYMENT = "PAYMENT"
    REFUND = "REFUND"


class FeeReason(str, Enum):
    GUARDIAN_PAYMENT = "GUARDIAN_PAYMENT"
    TRIP_CANCELLATION = "TRIP_CANCELLATION"
    VOLUNTARY_WITHDRAWAL = "VOLUNTARY_WITHDRAWAL"


class Checkpoint(str, Enum):
    DEPARTURE = "DEPARTURE"
    RETURN = "RETURN"


# ─── Mutable, versioned entities (id + created_at + updated_at + version) ──────
class Student(TypedDict):
    id: str
    full_name: str
    grade_level: int
    special_needs: bool
    home_school_code: str
    created_at: str
    updated_at: str
    version: int


class Guardian(TypedDict):
    id: str
    full_name: str
    email: str
    phone: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    label: str
    seat_capacity: int
    status: str
    seats_reserved: int
    created_at: str
    updated_at: str
    version: int


class ScholarshipPool(TypedDict):
    id: str
    name: str
    total_cents: int
    granted_cents: int
    remaining_cents: int
    created_at: str
    updated_at: str
    version: int


class FieldTrip(TypedDict):
    id: str
    title: str
    organizer_teacher_id: str
    school_code: str
    grade_band: str
    depart_at: str
    return_at: str
    has_water_activity: bool
    capacity: int
    base_fee_cents: int
    transport_cost_cents: int
    deposit_cents: int
    status: str
    signed_count: int
    confirmed_count: Optional[int]
    required_chaperones: int
    collected_fees_cents: int
    per_student_final_fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PermissionSlip(TypedDict):
    id: str
    trip_id: str
    student_id: str
    guardian_id: str
    signature_status: str
    payment_status: str
    participation_status: str
    signed_at: Optional[str]
    medical_notes: Optional[str]
    allergies: List[str]
    fee_due_cents: int
    scholarship_award_cents: int
    net_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class ScholarshipGrant(TypedDict):
    id: str
    slip_id: str
    pool_id: str
    award_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Chaperone(TypedDict):
    id: str
    trip_id: str
    guardian_id: str
    assigned_student_id: Optional[str]
    status: str
    background_check_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransportBooking(TypedDict):
    id: str
    trip_id: str
    vehicle_id: str
    seat_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only / immutable records (id + created_at ONLY) ───────────────────
class TripApproval(TypedDict):
    id: str
    trip_id: str
    step: str
    decision: str
    actor_role: str
    actor_user_id: str
    comment: Optional[str]
    created_at: str


class EmergencyContact(TypedDict):
    id: str
    slip_id: str
    name: str
    phone: str
    relationship: str
    created_at: str


class FeeTransaction(TypedDict):
    id: str
    slip_id: str
    trip_id: str
    kind: str
    amount_cents: int
    reason: str
    created_at: str


class AttendanceRecord(TypedDict):
    id: str
    trip_id: str
    slip_id: str
    checkpoint: str
    present: bool
    created_at: str
