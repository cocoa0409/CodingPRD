"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    OPERATIONS_MANAGER = "OperationsManager"
    CAPTAIN = "Captain"
    CUSTOMER = "Customer"
    CHARTER_SALES_AGENT = "CharterSalesAgent"
    GALLEY_MANAGER = "GalleyManager"
    DOCK_ATTENDANT = "DockAttendant"


class VesselStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class MenuTierCode(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    LUXE = "LUXE"


class Season(str, Enum):
    PEAK = "PEAK"
    SHOULDER = "SHOULDER"
    OFF = "OFF"


class CruiseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    BOARDING = "BOARDING"
    UNDERWAY = "UNDERWAY"
    COMPLETED = "COMPLETED"
    WEATHER_HOLD = "WEATHER_HOLD"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"
    CREDITED = "CREDITED"


class BookingStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    BOARDED = "BOARDED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"
    CONVERTED_TO_CHARTER = "CONVERTED_TO_CHARTER"


class ManifestStatus(str, Enum):
    DRAFT = "DRAFT"
    FROZEN = "FROZEN"
    FILED = "FILED"


class StaffRoleCode(str, Enum):
    SERVER = "SERVER"
    BARTENDER = "BARTENDER"
    GALLEY = "GALLEY"
    ENTERTAINER = "ENTERTAINER"
    DECKHAND = "DECKHAND"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class ProvisionOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    RECEIVED = "RECEIVED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class InquiryStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    CONVERTED = "CONVERTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class WeatherSeverity(str, Enum):
    ADVISORY = "ADVISORY"
    GALE_WARNING = "GALE_WARNING"
    CANCELLATION_REQUIRED = "CANCELLATION_REQUIRED"


class WeatherEventStatus(str, Enum):
    DECLARED = "DECLARED"
    CANCELLATION_ISSUED = "CANCELLATION_ISSUED"
    CREDITS_SETTLED = "CREDITS_SETTLED"
    CLOSED = "CLOSED"


class CreditStatus(str, Enum):
    ISSUED = "ISSUED"
    SETTLED = "SETTLED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"


class ParkingPassStatus(str, Enum):
    RESERVED = "RESERVED"
    REDEEMED = "REDEEMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


# --- Primary resources (PRD §2.5: id + created_at + updated_at + version) ---

class Vessel(TypedDict, total=False):
    id: str
    name: str
    coast_guard_capacity: int
    home_dock_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Dock(TypedDict, total=False):
    id: str
    name: str
    parking_capacity: int
    parking_in_use: int
    created_at: str
    updated_at: str
    version: int


class MenuTier(TypedDict, total=False):
    id: str
    code: str
    base_price_cents: int
    galley_load_per_cover: float
    bar_package_price_cents: int
    created_at: str
    updated_at: str
    version: int


class CruiseInstance(TypedDict, total=False):
    id: str
    vessel_id: str
    menu_tier_id: str
    depart_at: str
    return_at: str
    season: str
    is_holiday: bool
    reserved_covers: int
    boarded_count: int
    bar_service_enabled: bool
    charter_booking_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    cruise_id: str
    customer_id: str
    party_size: int
    booking_total_cents: int
    bar_package_count: int
    bar_package_total_cents: int
    payment_status: str
    booking_status: str
    created_at: str
    updated_at: str
    version: int


class BoardingManifest(TypedDict, total=False):
    id: str
    cruise_id: str
    passenger_count: int
    coast_guard_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict, total=False):
    id: str
    full_name: str
    role_code: str
    alcohol_cert_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffAssignment(TypedDict, total=False):
    id: str
    cruise_id: str
    staff_member_id: str
    assigned_role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GalleyProvisionOrder(TypedDict, total=False):
    id: str
    cruise_id: str
    provisional_covers: int
    final_covers: int
    provision_load_units: float
    restocking_rebate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CharterInquiry(TypedDict, total=False):
    id: str
    cruise_id: str
    customer_id: str
    quoted_total_cents: int
    quote_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WeatherEvent(TypedDict, total=False):
    id: str
    declared_at: str
    severity: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DockSlot(TypedDict, total=False):
    id: str
    dock_id: str
    vessel_id: str
    slot_start: str
    slot_end: str
    created_at: str
    updated_at: str
    version: int


class ParkingPass(TypedDict, total=False):
    id: str
    dock_id: str
    booking_id: str
    cruise_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Lighter resources (PRD §2.5: only id + created_at; no updated_at/version) ---

class BookingPassenger(TypedDict, total=False):
    id: str
    booking_id: str
    full_name: str
    date_of_birth: str
    is_minor: bool
    boarded_at: Optional[str]
    created_at: str


class CruiseCredit(TypedDict, total=False):
    id: str
    customer_id: str
    booking_id: str
    amount_cents: int
    final_amount_cents: int
    credit_status: str
    created_at: str
