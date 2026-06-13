"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this domain carries the full common-field set (id, created_at,
updated_at, version) per PRD §2.4 — there is no append-only entity that omits
updated_at and version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────────────────────────

class ChefStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BookingLifecycleStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    IN_PREP = "IN_PREP"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class BookingPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUNDED = "REFUNDED"


class GroceryRunStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"


class PaymentStatus(str, Enum):
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class RecurringPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class RescheduleRequestStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class AvailabilityBlockKind(str, Enum):
    BLACKOUT = "BLACKOUT"
    BOOKING_HOLD = "BOOKING_HOLD"


class AvailabilityBlockStatus(str, Enum):
    HELD = "HELD"
    RELEASED = "RELEASED"


class DietaryPattern(str, Enum):
    OMNIVORE = "OMNIVORE"
    VEGETARIAN = "VEGETARIAN"
    VEGAN = "VEGAN"
    PESCATARIAN = "PESCATARIAN"


class UserRole(str, Enum):
    CHEF = "Chef"
    CLIENT = "Client"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Entity TypedDicts (all carry common fields per PRD §2.4) ───────────────

class Chef(TypedDict):
    id: str
    display_name: str
    home_base_zip: str
    equipment_inventory: List[str]
    prep_buffer_minutes: int
    max_bookings_per_day: int
    status: str
    completed_bookings_count: int
    settled_reliability_score: int
    projected_reliability_score: int
    captured_payments_cents: int
    refunded_payments_cents: int
    payout_accrued_cents: int
    active_booking_count: int
    created_at: str
    updated_at: str
    version: int


class MenuPackage(TypedDict):
    id: str
    chef_id: str
    title: str
    base_price_per_guest_cents: int
    estimated_ingredient_per_guest_cents: int
    min_party_size: int
    max_party_size: int
    allergen_tags: List[str]
    required_equipment: List[str]
    is_listed: bool
    created_at: str
    updated_at: str
    version: int


class TravelZone(TypedDict):
    id: str
    chef_id: str
    zone_code: str
    zip_prefixes: List[str]
    travel_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class AvailabilityBlock(TypedDict):
    id: str
    chef_id: str
    kind: str
    booking_id: Optional[str]
    window_start_utc: str
    window_end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    full_name: str
    email: str
    allergen_restrictions: List[str]
    dietary_pattern: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    chef_id: str
    client_id: str
    menu_package_id: str
    travel_zone_id: str
    recurring_plan_id: Optional[str]
    party_size: int
    service_zip: str
    event_start_utc: str
    event_end_utc: str
    event_date: str
    locked_markup_rate: float
    labor_total_cents: int
    estimated_grocery_total_cents: int
    actual_grocery_total_cents: int
    travel_fee_cents: int
    quote_total_cents: int
    deposit_due_cents: int
    balance_due_cents: int
    amount_captured_cents: int
    amount_refunded_cents: int
    lifecycle_status: str
    payment_status: str
    cancellation_refund_rate: float
    created_at: str
    updated_at: str
    version: int


class GroceryRun(TypedDict):
    id: str
    booking_id: str
    raw_actual_subtotal_cents: int
    line_items: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    booking_id: str
    kind: str
    amount_cents: int
    refunded_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RecurringPlan(TypedDict):
    id: str
    chef_id: str
    client_id: str
    menu_package_id: str
    party_size: int
    service_zip: str
    weekday: int
    event_start_time_utc: str
    duration_minutes: int
    cadence_weeks: int
    occurrences_generated: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RescheduleRequest(TypedDict):
    id: str
    booking_id: str
    proposed_event_start_utc: str
    proposed_event_end_utc: str
    requested_by_role: str
    status: str
    created_at: str
    updated_at: str
    version: int
