"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


# --- Status enums (PRD §3) ---------------------------------------------------


class SubscriptionPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class PlanTier(str, Enum):
    STARTER = "STARTER"
    GROWTH = "GROWTH"
    SCALE = "SCALE"
    CUSTOM = "CUSTOM"


class MerchantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class BillingCycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"


class ShopperStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"


class ReturnMethod(str, Enum):
    LOCKER_QR = "LOCKER_QR"
    COUNTER_DROP = "COUNTER_DROP"
    HOME_PICKUP = "HOME_PICKUP"


class ReturnOrderStatus(str, Enum):
    INITIATED = "INITIATED"
    LABEL_ISSUED = "LABEL_ISSUED"
    DROPPED_OFF = "DROPPED_OFF"
    IN_TRANSIT = "IN_TRANSIT"
    INSPECTING = "INSPECTING"
    EXCEPTION_PENDING = "EXCEPTION_PENDING"
    RESOLVED = "RESOLVED"
    REFUND_POSTED = "REFUND_POSTED"
    CANCELLED = "CANCELLED"
    REJECTED_CLOSED = "REJECTED_CLOSED"


class ItemCondition(str, Enum):
    NEW = "NEW"
    LIGHT_USE = "LIGHT_USE"
    DAMAGED = "DAMAGED"
    DEFECTIVE = "DEFECTIVE"
    WRONG_ITEM = "WRONG_ITEM"


class ReturnItemStatus(str, Enum):
    PENDING = "PENDING"
    INSPECTED = "INSPECTED"


class LocationKind(str, Enum):
    LOCKER = "LOCKER"
    COUNTER = "COUNTER"


class DropoffLocationStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    OPERATIONAL = "OPERATIONAL"
    PAUSED = "PAUSED"
    DECOMMISSIONED = "DECOMMISSIONED"


class SlotSizeClass(str, Enum):
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"


class LockerSlotStatus(str, Enum):
    EMPTY = "EMPTY"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class SlotReservationStatus(str, Enum):
    HELD = "HELD"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class LabelType(str, Enum):
    QR_CODE = "QR_CODE"
    CARRIER_LABEL = "CARRIER_LABEL"


class LabelStatus(str, Enum):
    ISSUED = "ISSUED"
    CONSUMED = "CONSUMED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class PickupAppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    COLLECTED = "COLLECTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CarrierRouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    ARRIVED = "ARRIVED"
    CANCELLED = "CANCELLED"


class ConsolidationToteStatus(str, Enum):
    FILLING = "FILLING"
    SEALED = "SEALED"
    DISPATCHED = "DISPATCHED"
    ARRIVED = "ARRIVED"
    DISCREPANCY = "DISCREPANCY"
    RECONCILED = "RECONCILED"


class LedgerEntryKind(str, Enum):
    ESTIMATE = "ESTIMATE"
    FINAL = "FINAL"
    ADJUSTMENT = "ADJUSTMENT"
    CORRECTION = "CORRECTION"


class ExceptionKind(str, Enum):
    DAMAGED_ITEM = "DAMAGED_ITEM"
    LOST_PARCEL = "LOST_PARCEL"
    WRONG_ITEM = "WRONG_ITEM"
    LABEL_FRAUD = "LABEL_FRAUD"
    OVERSIZE_REJECT = "OVERSIZE_REJECT"


class ExceptionCaseStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    AWAITING_SHOPPER = "AWAITING_SHOPPER"
    RESOLVED_APPROVED = "RESOLVED_APPROVED"
    RESOLVED_REJECTED = "RESOLVED_REJECTED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"


class ExceptionResolution(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RefundStatus(str, Enum):
    ESTIMATED = "ESTIMATED"
    POSTED = "POSTED"


class UserRole(str, Enum):
    SHOPPER = "Shopper"
    MERCHANT_ADMIN = "MerchantAdmin"
    LOCATION_OPERATOR = "LocationOperator"
    SUPPORT_AGENT = "SupportAgent"
    CARRIER_DISPATCHER = "CarrierDispatcher"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Entity TypedDicts (PRD §2.4: primary resources carry id, created_at,
# updated_at, version; RefundLedgerEntry carries only id and created_at) ------


class SubscriptionPlan(TypedDict):
    id: str
    tier: str
    monthly_fee_cents: int
    included_returns: int
    overage_fee_cents: int
    pickup_enabled: bool
    boxless_enabled: bool
    oversize_enabled: bool
    free_returns: bool
    oversize_surcharge_cents: int
    pickup_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MerchantAccount(TypedDict):
    id: str
    legal_name: str
    plan_id: str
    status: str
    ledger_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class BillingCycle(TypedDict):
    id: str
    merchant_id: str
    period_start: str
    period_end: str
    status: str
    fulfilled_count: int
    in_flight_count: int
    refunds_accrued_cents: int
    base_cents: int
    overage_count: int
    overage_fee_cents: int
    surcharge_cents: int
    gross_cents: int
    discount_cents: int
    total_cents: int
    closed_by_user_id: Optional[str]
    settled_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shopper(TypedDict):
    id: str
    email: str
    full_name: str
    postal_code: str
    status: str
    fraud_strikes: int
    created_at: str
    updated_at: str
    version: int


class ReturnOrder(TypedDict):
    id: str
    shopper_id: str
    merchant_id: str
    method: str
    boxless: bool
    status: str
    refund_estimate_cents: int
    refund_final_cents: Optional[int]
    resolved_at: Optional[str]
    tote_id: Optional[str]
    dropoff_location_id: Optional[str]
    total_units: int
    total_weight_grams: int
    has_oversize_item: bool
    created_at: str
    updated_at: str
    version: int


class ReturnItem(TypedDict):
    id: str
    return_order_id: str
    sku: str
    quantity: int
    unit_price_cents: int
    declared_condition: str
    condition: Optional[str]
    longest_side_cm: float
    weight_grams: int
    status: str
    deduction_cents: Optional[int]
    inspected_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DropoffLocation(TypedDict):
    id: str
    name: str
    kind: str
    postal_code: str
    status: str
    reserved_slot_count: int
    occupied_slot_count: int
    created_at: str
    updated_at: str
    version: int


class LockerSlot(TypedDict):
    id: str
    location_id: str
    size_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SlotReservation(TypedDict):
    id: str
    slot_id: str
    return_order_id: str
    status: str
    hold_start: str
    hold_until: str
    label_id: str
    created_at: str
    updated_at: str
    version: int


class Label(TypedDict):
    id: str
    return_order_id: str
    label_type: str
    status: str
    issued_at: str
    expires_at: str
    supersedes_label_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CourierZone(TypedDict):
    id: str
    zone_code: str
    window_capacity: int
    confirmed_load: int
    demand_load: int
    created_at: str
    updated_at: str
    version: int


class PickupAppointment(TypedDict):
    id: str
    return_order_id: str
    zone_id: str
    window_start: str
    window_end: str
    status: str
    attempt_count: int
    created_at: str
    updated_at: str
    version: int


class CarrierRoute(TypedDict):
    id: str
    origin_location_id: str
    destination_facility: str
    weight_capacity_grams: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsolidationTote(TypedDict):
    id: str
    route_id: str
    location_id: str
    status: str
    manifest_units: int
    manifest_weight_grams: int
    sealed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# PRD §2.4: RefundLedgerEntry is the deliberate exception — an immutable,
# append-only event log carrying only id and created_at.
class RefundLedgerEntry(TypedDict):
    id: str
    return_order_id: str
    kind: str
    amount_cents: int
    note: str
    actor_user_id: str
    created_at: str


class ExceptionCase(TypedDict):
    id: str
    return_order_id: str
    return_item_id: Optional[str]
    kind: str
    note: str
    status: str
    resolution: Optional[str]
    opened_by_user_id: str
    resolved_by_user_id: Optional[str]
    appeal_count: int
    created_at: str
    updated_at: str
    version: int


class RefundProjection(TypedDict):
    estimated_cents: int
    final_cents: Optional[int]
    payable_cents: int
    entry_count: int
    refund_status: str


class ChargePreview(TypedDict):
    variant: str
    fulfilled_count: int
    in_flight_count: int
    base_cents: int
    overage_count: int
    overage_fee_cents: int
    surcharge_cents: int
    gross_cents: int
    discount_cents: int
    total_cents: int
