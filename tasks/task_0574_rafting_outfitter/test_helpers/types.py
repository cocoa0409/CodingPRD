"""Domain types: entity TypedDicts, status enums, role enum for the Rafting Outfitter API."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    OUTFITTER_MANAGER = "OutfitterManager"
    RESERVATIONIST = "Reservationist"
    SAFETY_OFFICER = "SafetyOfficer"
    GUEST = "Guest"


class WhitewaterClass(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"
    CLASS_IV = "CLASS_IV"
    CLASS_V = "CLASS_V"


class RiverTripStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    FULL = "FULL"
    WEATHER_HOLD = "WEATHER_HOLD"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class BookingMode(str, Enum):
    GROUP = "GROUP"
    PRIVATE = "PRIVATE"


class GuideStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class GuideRole(str, Enum):
    LEAD = "LEAD"
    SAFETY = "SAFETY"
    SWEEP = "SWEEP"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class GuestStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    REMOVED = "REMOVED"


class WaiverStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED = "SIGNED"
    VOID = "VOID"


class GearType(str, Enum):
    RAFT = "RAFT"
    WETSUIT = "WETSUIT"
    PFD = "PFD"


class GearItemStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ShuttleDirection(str, Enum):
    TO_PUT_IN = "TO_PUT_IN"
    FROM_TAKE_OUT = "FROM_TAKE_OUT"


class ShuttleRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class FlowBand(str, Enum):
    SAFE = "SAFE"
    MARGINAL = "MARGINAL"
    UNSAFE = "UNSAFE"


# ── Entity TypedDicts ──────────────────────────────────────────────────────
# common_fields: true — id + created_at + updated_at + version


class RiverTrip(TypedDict):
    id: str
    river_name: str
    difficulty_class: str
    trip_date: str
    end_time: str
    put_in_location: str
    take_out_location: str
    max_capacity: int
    guide_ratio_max: int
    base_rate_cents: int
    min_age: int
    safe_flow_min: float
    safe_flow_max: float
    marginal_flow_max: float
    booking_mode: str
    committed_guests: int
    assigned_guide_count: int
    deposits_held_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Guide(TypedDict):
    id: str
    full_name: str
    max_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GuideAssignment(TypedDict):
    id: str
    trip_id: str
    guide_id: str
    role: str
    provisional_gratuity_share_cents: int
    final_gratuity_share_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    trip_id: str
    booking_type: str
    party_size: int
    photo_addon: bool
    deposit_cents: int
    gratuity_cents: int
    estimated_total_cents: int
    final_total_cents: int
    payment_status: str
    fulfillment_status: str
    checked_in_guest_count: int
    created_at: str
    updated_at: str
    version: int


class Guest(TypedDict):
    id: str
    reservation_id: str
    full_name: str
    age: int
    weight_lbs: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Waiver(TypedDict):
    id: str
    guest_id: str
    guardian_required: bool
    guardian_name: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class GearItem(TypedDict):
    id: str
    gear_type: str
    size_label: str
    min_weight_lbs: float
    max_weight_lbs: float
    status: str
    created_at: str
    updated_at: str
    version: int


class GearAssignment(TypedDict):
    id: str
    gear_item_id: str
    guest_id: str
    trip_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ShuttleVehicle(TypedDict):
    id: str
    name: str
    seat_capacity: int
    created_at: str
    updated_at: str
    version: int


class ShuttleRun(TypedDict):
    id: str
    trip_id: str
    shuttle_vehicle_id: str
    direction: str
    depart_time: str
    arrive_time: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only event record, carries ONLY id + created_at
class RiverConditionReading(TypedDict):
    id: str
    trip_id: str
    flow_cfs: float
    reading_time: str
    resulting_band: str
    created_at: str
