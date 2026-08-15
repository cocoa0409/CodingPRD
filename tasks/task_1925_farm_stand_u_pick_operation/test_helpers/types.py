"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class SeasonStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class FieldStatus(str, Enum):
    DORMANT = "DORMANT"
    OPEN = "OPEN"
    PICKED_OUT = "PICKED_OUT"
    ROTATION_REST = "ROTATION_REST"
    RETIRED = "RETIRED"


class WindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class WindowCancelReason(str, Enum):
    WEATHER = "WEATHER"
    DEPLETED = "DEPLETED"
    MANUAL = "MANUAL"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class WaiverStatus(str, Enum):
    SIGNED = "SIGNED"
    VOIDED = "VOIDED"


class VisitStatus(str, Enum):
    CHECKED_IN = "CHECKED_IN"
    FIELD_ACTIVE = "FIELD_ACTIVE"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class CheckoutMode(str, Enum):
    NORMAL = "NORMAL"
    WEATHER_FORCED = "WEATHER_FORCED"
    DAY_END_FORCED = "DAY_END_FORCED"


class SyncOutcome(str, Enum):
    APPLIED = "APPLIED"
    SYNC_CONFLICT = "SYNC_CONFLICT"


class SessionOrigin(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class HarvestLineStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class AddonKind(str, Enum):
    WAGON_RIDE = "WAGON_RIDE"
    CAFE_VOUCHER = "CAFE_VOUCHER"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    REDEEMED = "REDEEMED"
    RELEASED = "RELEASED"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CARD = "CARD"
    OFFLINE_CARD = "OFFLINE_CARD"


class PaymentRowStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    FAILED = "FAILED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class DayType(str, Enum):
    WEEKDAY = "WEEKDAY"
    WEEKEND = "WEEKEND"


class SalesDayStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    CLOSED_NORMAL = "CLOSED_NORMAL"
    CLOSED_WEATHER = "CLOSED_WEATHER"


class BatchStatus(str, Enum):
    APPLIED = "APPLIED"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"


class UserRole(str, Enum):
    FARM_MANAGER = "FarmManager"
    GATE_STAFF = "GateStaff"
    FIELD_STAFF = "FieldStaff"
    KIOSK_DEVICE = "KioskDevice"
    ANONYMOUS = "Anonymous"


# All resources carry the four common properties of PRD §2.5:
# id, created_at, updated_at, version.

class Season(TypedDict, total=False):
    id: str
    name: str
    start_date: str
    end_date: str
    waiver_text: str
    current_waiver_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Crop(TypedDict, total=False):
    id: str
    season_id: str
    name: str
    price_per_lb_cents: int
    season_picked_oz: int
    created_at: str
    updated_at: str
    version: int


class Field(TypedDict, total=False):
    id: str
    season_id: str
    name: str
    rotation_group: str
    rotation_order: int
    estimated_harvest_oz: int
    committed_picked_oz: int
    projected_remaining_oz: int
    status: str
    rest_until: Optional[str]
    rotation_successor_field_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FieldDayWindow(TypedDict, total=False):
    id: str
    field_id: str
    date: str
    open_time: str
    close_time: str
    picking_capacity_slots: int
    booked_slots: int
    status: str
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PricingPolicy(TypedDict, total=False):
    id: str
    season_id: str
    admission_per_person_cents: int
    container_fee_cents: int
    weekend_surge_bps: int
    bundle_discount_bps: int
    bundle_cap_cents: int
    policy_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Waiver(TypedDict, total=False):
    id: str
    season_id: str
    signer_name: str
    signer_email: str
    party_member_names: List[str]
    waiver_version_signed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VisitSession(TypedDict, total=False):
    id: str
    window_id: str
    waiver_id: str
    pricing_policy_id: str
    party_size: int
    container_count: int
    parking_spaces: int
    origin: str
    offline_ref: Optional[str]
    device_id: Optional[str]
    visit_status: str
    payment_status: str
    admission_charge_cents: int
    final_total_cents: Optional[int]
    bundle_discount_cents: int
    total_paid_cents: int
    total_refunded_cents: int
    checkout_mode: Optional[str]
    sync_outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HarvestLine(TypedDict, total=False):
    id: str
    session_id: str
    field_id: str
    crop_id: str
    gross_weight_oz: int
    container_count: int
    tare_oz: int
    net_oz: int
    line_charge_cents: int
    status: str
    offline_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AddonProduct(TypedDict, total=False):
    id: str
    season_id: str
    kind: str
    name: str
    price_cents: int
    slot_capacity: int
    created_at: str
    updated_at: str
    version: int


class AddonBooking(TypedDict, total=False):
    id: str
    session_id: str
    addon_product_id: str
    booking_date: str
    slot_time: str
    qty: int
    booked_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    session_id: str
    kind: str
    method: str
    amount_cents: int
    idempotency_key: str
    refunded_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesDay(TypedDict, total=False):
    id: str
    season_id: str
    date: str
    day_type: str
    parking_capacity: int
    staff_on_duty: int
    status: str
    closed_at_time: Optional[str]
    booked_parking: int
    revenue_cents: int
    created_at: str
    updated_at: str
    version: int


class OfflineBatch(TypedDict, total=False):
    id: str
    device_id: str
    batch_id: str
    records: list
    status: str
    results: list
    applied_count: int
    conflict_count: int
    created_at: str
    updated_at: str
    version: int
