"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CUSTOMER = "Customer"
    COORDINATOR = "Coordinator"
    VETERINARIAN = "Veterinarian"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    OPERATOR = "Operator"


# ---------------------------------------------------------------------------
# Status / field enums
# ---------------------------------------------------------------------------
class CustomerType(str, Enum):
    PRIVATE = "PRIVATE"
    SCHOOL = "SCHOOL"
    LIBRARY = "LIBRARY"


class VenueType(str, Enum):
    INDOOR = "INDOOR"
    OUTDOOR = "OUTDOOR"
    MIXED = "MIXED"


class SurfaceType(str, Enum):
    GRASS = "GRASS"
    PAVEMENT = "PAVEMENT"
    INDOOR_FLOOR = "INDOOR_FLOOR"


class TravelZone(str, Enum):
    ZONE_A = "ZONE_A"
    ZONE_B = "ZONE_B"
    ZONE_C = "ZONE_C"


class Species(str, Enum):
    GOAT = "GOAT"
    SHEEP = "SHEEP"
    PONY = "PONY"
    RABBIT = "RABBIT"
    CHICKEN = "CHICKEN"
    REPTILE = "REPTILE"


class WeightClass(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class AnimalStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINE = "QUARANTINE"
    RETIRED = "RETIRED"


class HealthResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class HandlerCertification(str, Enum):
    REPTILE_CERTIFIED = "REPTILE_CERTIFIED"
    PONY_RIDE_CERTIFIED = "PONY_RIDE_CERTIFIED"
    FIRST_AID = "FIRST_AID"


class HandlerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class BookingStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    WEATHER_HOLD = "WEATHER_HOLD"
    EN_ROUTE = "EN_ROUTE"
    ON_SITE_SETUP = "ON_SITE_SETUP"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    INVOICED = "INVOICED"
    CANCELLED_CUSTOMER = "CANCELLED_CUSTOMER"
    CANCELLED_WEATHER = "CANCELLED_WEATHER"
    CANCELLED_COMPLIANCE = "CANCELLED_COMPLIANCE"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUND_PARTIAL = "REFUND_PARTIAL"
    REFUND_FULL = "REFUND_FULL"
    FORFEITED = "FORFEITED"


class BookingAnimalRole(str, Enum):
    PETTING_ZOO = "PETTING_ZOO"
    PONY_RIDE = "PONY_RIDE"
    REPTILE_SHOW = "REPTILE_SHOW"


class BookingAnimalStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    REMOVED = "REMOVED"


class RemovalReason(str, Enum):
    MANUAL = "MANUAL"
    QUARANTINE = "QUARANTINE"
    RETIRED = "RETIRED"
    BOOKING_CANCELLED = "BOOKING_CANCELLED"


class StaffRole(str, Enum):
    LEAD = "LEAD"
    ASSISTANT = "ASSISTANT"


class StaffAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"


class ReleaseReason(str, Enum):
    MANUAL = "MANUAL"
    BOOKING_CANCELLED = "BOOKING_CANCELLED"


class AddOnType(str, Enum):
    PONY_RIDE = "PONY_RIDE"
    REPTILE_SHOW = "REPTILE_SHOW"


class AddOnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REMOVED = "REMOVED"


class PermitType(str, Enum):
    ANIMAL_EXHIBITION = "ANIMAL_EXHIBITION"
    HEALTH_DEPT = "HEALTH_DEPT"
    FIRE_SAFETY = "FIRE_SAFETY"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ISSUED = "ISSUED"
    DENIED = "DENIED"


class WaiverStatus(str, Enum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"


class InsuranceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class WeatherVerdict(str, Enum):
    PROCEED = "PROCEED"
    HOLD_RECOMMENDED = "HOLD_RECOMMENDED"
    MANDATORY_HOLD = "MANDATORY_HOLD"


class LedgerEntryType(str, Enum):
    PAYMENT = "PAYMENT"
    REFUND = "REFUND"
    FORFEIT = "FORFEIT"
    PENALTY = "PENALTY"
    CHARGE = "CHARGE"


class CancelReason(str, Enum):
    CUSTOMER = "CUSTOMER"
    WEATHER = "WEATHER"
    COMPLIANCE = "COMPLIANCE"


class BookingType(str, Enum):
    PRIVATE_PARTY = "PRIVATE_PARTY"
    SCHOOL_PROGRAM = "SCHOOL_PROGRAM"
    LIBRARY_PROGRAM = "LIBRARY_PROGRAM"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# common_fields entities carry id + created_at + updated_at + version.
# Immutable records (HealthRecord, WeatherAssessment, LedgerEntry) carry only
# id + created_at (PRD §2.4).
# ---------------------------------------------------------------------------
class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    customer_type: str
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict):
    id: str
    customer_id: str
    name: str
    address: str
    venue_type: str
    water_access: bool
    surface_type: str
    travel_zone: str
    distance_miles: int
    max_guest_capacity: int
    requires_animal_permit: bool
    requires_handwash_stations: bool
    created_at: str
    updated_at: str
    version: int


class Animal(TypedDict):
    id: str
    name: str
    species: str
    weight_class: str
    temperament_tier: int
    base_event_fee_cents: int
    rest_buffer_hours: int
    status: str
    current_health_cert_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HealthRecord(TypedDict):
    id: str
    animal_id: str
    exam_date: str
    result: str
    valid_until: str
    notes: str
    created_at: str


class Handler(TypedDict):
    id: str
    name: str
    certifications: List[str]
    status: str
    scheduled_minutes_total: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    customer_id: str
    venue_id: str
    start_time: str
    end_time: str
    guest_count: int
    child_guest_count: int
    booking_type: str
    planned_handwash_stations: int
    status: str
    payment_status: str
    quote_fresh: bool
    animal_subtotal_cents: Optional[int]
    addon_subtotal_cents: Optional[int]
    discount_cents: Optional[int]
    surcharge_cents: Optional[int]
    travel_fee_cents: Optional[int]
    guest_surcharge_cents: Optional[int]
    quoted_total_cents: Optional[int]
    final_total_cents: Optional[int]
    deposit_amount_cents: Optional[int]
    total_paid_cents: int
    required_handwash_stations: Optional[int]
    required_staff_count: Optional[int]
    compliance_screening_score: Optional[int]
    compliance_audited_score: Optional[int]
    actual_handwash_stations: Optional[int]
    actual_attendance_count: Optional[int]
    created_at: str
    updated_at: str
    version: int


class BookingAnimal(TypedDict):
    id: str
    booking_id: str
    animal_id: str
    role: str
    status: str
    removal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffAssignment(TypedDict):
    id: str
    booking_id: str
    handler_id: str
    role: str
    status: str
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AddOnRequest(TypedDict):
    id: str
    booking_id: str
    addon_type: str
    duration_minutes: int
    status: str
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    booking_id: str
    permit_type: str
    jurisdiction: str
    status: str
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Waiver(TypedDict):
    id: str
    booking_id: str
    required_signatures: int
    signed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InsuranceCertificate(TypedDict):
    id: str
    customer_id: str
    provider: str
    policy_number: str
    coverage_amount_cents: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WeatherAssessment(TypedDict):
    id: str
    booking_id: str
    assessed_at: str
    forecast_temp_f: int
    forecast_precip_pct: int
    wind_mph: int
    verdict: str
    created_at: str


class LedgerEntry(TypedDict):
    id: str
    booking_id: str
    entry_type: str
    amount_cents: int
    description: str
    created_at: str
