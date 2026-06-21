"""Domain types: entity TypedDicts, status enums, role enum.

All field names and enum values mirror the Mobile Pet Grooming PRD exactly.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Role enum (PRD §2.1 — exactly four roles)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    DISPATCHER = "Dispatcher"
    CUSTOMER = "Customer"
    GROOMER = "Groomer"


# --------------------------------------------------------------------------
# Status / enumeration types
# --------------------------------------------------------------------------
class CoatType(str, Enum):
    SMOOTH = "SMOOTH"
    DOUBLE = "DOUBLE"
    CURLY = "CURLY"
    WIRE = "WIRE"
    HAIRLESS = "HAIRLESS"


class SizeClass(str, Enum):
    TOY = "TOY"
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"
    GIANT = "GIANT"


class ServiceTierCode(str, Enum):
    BATH_ONLY = "BATH_ONLY"
    FULL_GROOM = "FULL_GROOM"
    SHOW_CUT = "SHOW_CUT"


class AddOnCode(str, Enum):
    DESHED = "DESHED"
    NAIL_TRIM = "NAIL_TRIM"
    TEETH_CLEAN = "TEETH_CLEAN"


class CoatCondition(str, Enum):
    NORMAL = "NORMAL"
    MATTED = "MATTED"


class BehavioralFlag(str, Enum):
    CALM = "CALM"
    NERVOUS = "NERVOUS"
    AGGRESSIVE = "AGGRESSIVE"


class VaccinationStatus(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VaccineType(str, Enum):
    RABIES = "RABIES"
    BORDETELLA = "BORDETELLA"
    DISTEMPER = "DISTEMPER"


class SkillLevel(str, Enum):
    JUNIOR = "JUNIOR"
    SENIOR = "SENIOR"


class GroomerStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFF_DUTY = "OFF_DUTY"


class RouteDayStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class RouteStopStatus(str, Enum):
    RESERVED = "RESERVED"
    SERVICED = "SERVICED"
    NO_SHOW = "NO_SHOW"
    VOIDED = "VOIDED"


class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    QUOTED = "QUOTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class RecurringPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class FeeType(str, Enum):
    NO_SHOW = "NO_SHOW"
    LATE_CANCEL = "LATE_CANCEL"


class SettlementStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"


# --------------------------------------------------------------------------
# Entity TypedDicts
# Entities with id+created_at+updated_at+version carry the common-fields block;
# VaccinationRecord and AppointmentAddOn are immutable (id + created_at only).
# --------------------------------------------------------------------------
class Breed(TypedDict):
    id: str
    name: str
    coat_type: str
    size_class: str
    base_service_minutes: int
    created_at: str
    updated_at: str
    version: int


class ServiceTier(TypedDict):
    id: str
    code: str
    base_price_cents: int
    duration_multiplier: float
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    code: str
    price_cents: int
    duration_minutes: int
    requires_calm: bool
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    service_zip: str
    no_show_strikes: int
    account_status: str
    outstanding_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Pet(TypedDict):
    id: str
    customer_id: str
    breed_id: str
    name: str
    weight_lbs: float
    coat_condition: str
    behavioral_flag: str
    muzzle_required: bool
    vaccination_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable, id + created_at only.
class VaccinationRecord(TypedDict):
    id: str
    pet_id: str
    vaccine_type: str
    issued_on: str
    expires_on: str
    created_at: str


class Groomer(TypedDict):
    id: str
    email: str
    full_name: str
    skill_level: str
    handles_aggressive: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Van(TypedDict):
    id: str
    label: str
    max_stops: int
    has_show_equipment: bool
    created_at: str
    updated_at: str
    version: int


class RouteDay(TypedDict):
    id: str
    van_id: str
    service_date: str
    window_start: str
    window_end: str
    coverage_zip: str
    status: str
    booked_minutes: int
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict):
    id: str
    route_day_id: str
    slot_start: str
    scheduled_minutes: int
    slot_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    pet_id: str
    service_tier_id: str
    route_stop_id: Optional[str]
    groomer_id: Optional[str]
    recurring_plan_id: Optional[str]
    estimated_minutes: int
    quoted_price_cents: int
    final_price_cents: int
    quote_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable, id + created_at only.
class AppointmentAddOn(TypedDict):
    id: str
    appointment_id: str
    add_on_id: str
    price_cents_snapshot: int
    created_at: str


class RecurringPlan(TypedDict):
    id: str
    pet_id: str
    service_tier_id: str
    cadence_days: int
    discount_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeCharge(TypedDict):
    id: str
    customer_id: str
    appointment_id: str
    fee_type: str
    amount_cents: int
    settlement_status: str
    created_at: str
    updated_at: str
    version: int
