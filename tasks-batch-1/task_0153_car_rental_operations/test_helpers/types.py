"""Domain types: entity TypedDicts, status enums, role enum for the Car Rental Operations API."""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum -------------------------------------------------------------
class UserRole(str, Enum):
    FLEET_MANAGER = "FleetManager"
    RENTAL_AGENT = "RentalAgent"
    MEMBER = "Member"


# --- Status enums ----------------------------------------------------------
class VehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    ON_RENT = "ON_RENT"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class ReservationStatus(str, Enum):
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    EXPIRED = "EXPIRED"


class RentalAgreementStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    WRITE_OFF = "WRITE_OFF"


class IncidentStatus(str, Enum):
    FILED = "FILED"
    RESOLVED = "RESOLVED"
    VOID = "VOID"


class MemberTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    TOTAL = "TOTAL"


class LedgerKind(str, Enum):
    BASE_RENTAL = "BASE_RENTAL"
    MILEAGE_OVERAGE = "MILEAGE_OVERAGE"
    FUEL = "FUEL"
    ADDONS = "ADDONS"
    YOUNG_DRIVER = "YOUNG_DRIVER"
    ONE_WAY_DROP = "ONE_WAY_DROP"
    DAMAGE = "DAMAGE"
    LOYALTY_DISCOUNT = "LOYALTY_DISCOUNT"
    INCIDENT_REVERSAL = "INCIDENT_REVERSAL"


class AccrualKind(str, Enum):
    ACCRUAL = "ACCRUAL"
    REDEMPTION = "REDEMPTION"
    REVERSAL = "REVERSAL"


# --- Full entities (common_fields: true -> id, created_at, updated_at, version) ---
class Location(TypedDict):
    id: str
    code: str
    name: str
    one_way_drop_fee_cents: int
    young_driver_surcharge_per_day_cents: int
    created_at: str
    updated_at: str
    version: int


class VehicleClass(TypedDict):
    id: str
    code: str
    tier_rank: int
    daily_rate_cents: int
    weekly_rate_cents: int
    included_miles_per_day: int
    overage_per_mile_cents: int
    ldw_per_day_cents: int
    pai_per_day_cents: int
    total_count: int
    available_count: int
    created_at: str
    updated_at: str
    version: int


class RatePlan(TypedDict):
    id: str
    location_id: str
    class_id: str
    daily_rate_cents: int
    weekly_rate_cents: int
    active: bool
    effective_from: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    location_id: str
    class_id: str
    plate: str
    status: str
    odometer_miles: int
    fuel_level_eighths: int
    held_by_reservation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LoyaltyMember(TypedDict):
    id: str
    email: str
    full_name: str
    driver_age: int
    tier: str
    points_balance: int
    lifetime_points: int
    no_show_strikes: int
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    member_id: str
    pickup_location_id: str
    dropoff_location_id: str
    class_id: str
    pickup_at: str
    dropoff_at: str
    rental_days: int
    ldw_selected: bool
    pai_selected: bool
    status: str
    quoted_total_cents: Optional[int]
    hold_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RentalAgreement(TypedDict):
    id: str
    reservation_id: str
    vehicle_id: str
    odometer_out: int
    fuel_out_eighths: int
    odometer_in: Optional[int]
    fuel_in_eighths: Optional[int]
    status: str
    final_total_cents: Optional[int]
    miles_driven: int
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict):
    id: str
    agreement_id: str
    severity: str
    assessed_damage_cents: int
    member_liability_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only entities (common_fields: false -> only id + created_at) ---
class LedgerEntry(TypedDict):
    id: str
    agreement_id: str
    kind: str
    amount_cents: int
    memo: str
    created_at: str


class LoyaltyAccrual(TypedDict):
    id: str
    member_id: str
    agreement_id: Optional[str]
    kind: str
    delta_points: int
    created_at: str
