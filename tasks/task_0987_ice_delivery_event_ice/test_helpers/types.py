"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class DepotPosture(str, Enum):
    OPEN = "OPEN"
    SURGE_CONSTRAINED = "SURGE_CONSTRAINED"
    FROZEN = "FROZEN"


class CustomerKind(str, Enum):
    BAR_RESTAURANT = "BAR_RESTAURANT"
    EVENT_ORGANIZER = "EVENT_ORGANIZER"


class CustomerTier(str, Enum):
    STANDARD = "STANDARD"
    PRIORITY = "PRIORITY"


class CreditTerms(str, Enum):
    PREPAID = "PREPAID"
    NET_15 = "NET_15"
    NET_30 = "NET_30"


class Standing(str, Enum):
    GOOD = "GOOD"
    HOLD = "HOLD"


class CertStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class PriceBookStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class AdmissionPolicy(str, Enum):
    OPEN = "OPEN"
    RATIONED = "RATIONED"
    CLOSED = "CLOSED"


class SurgeWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class Weekday(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class RouteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    TERMINATED = "TERMINATED"


class OrderChannel(str, Enum):
    DELIVERY = "DELIVERY"
    WILL_CALL = "WILL_CALL"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    STAGED = "STAGED"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    PICKED_UP = "PICKED_UP"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"


class PricingMode(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ProductForm(str, Enum):
    BLOCK = "BLOCK"
    CUBE = "CUBE"
    DRY_ICE = "DRY_ICE"


class Packaging(str, Enum):
    BAG = "BAG"
    PALLET = "PALLET"


class SlotStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"


class HoldZone(str, Enum):
    GENERAL_FREEZER = "GENERAL_FREEZER"
    DRY_ICE_BUNKER = "DRY_ICE_BUNKER"


class HoldStatus(str, Enum):
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class RunStatus(str, Enum):
    PLANNED = "PLANNED"
    LOCKED = "LOCKED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    OVERDUE = "OVERDUE"
    PAID = "PAID"
    VOID = "VOID"


class PaymentMethod(str, Enum):
    ACH = "ACH"
    CARD = "CARD"
    CASH = "CASH"


class WaitlistStatus(str, Enum):
    QUEUED = "QUEUED"
    PROMOTED = "PROMOTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    DEPOT_MANAGER = "DepotManager"
    DISPATCHER = "Dispatcher"
    BILLING_CLERK = "BillingClerk"
    SAFETY_OFFICER = "SafetyOfficer"
    CUSTOMER_AGENT = "CustomerAgent"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.5).

class Depot(TypedDict, total=False):
    id: str
    name: str
    freezer_capacity_pallets: int
    freezer_reserved_pallets: int
    freezer_free_pallets: int
    posture: str
    ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    account_name: str
    kind: str
    tier: str
    credit_terms: str
    credit_limit_cents: int
    credit_balance_cents: int
    outstanding_exposure_cents: int
    standing: str
    created_at: str
    updated_at: str
    version: int


class HandlerCertification(TypedDict, total=False):
    id: str
    customer_id: str
    handler_name: str
    certificate_number: str
    max_dry_ice_lbs: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PriceBookLine(TypedDict, total=False):
    product_form: str
    packaging: str
    tier_min_units: int
    tier_max_units: Optional[int]
    unit_price_cents: int


class VolumeDiscountTier(TypedDict):
    threshold_cents: int
    discount_bps: int


class PriceBook(TypedDict, total=False):
    id: str
    scope_label: str
    effective_from: str
    status: str
    lines: List[PriceBookLine]
    pallet_deposit_cents: int
    delivery_fee_cents: int
    free_delivery_threshold_cents: int
    volume_discount_tiers: List[VolumeDiscountTier]
    surge_surcharge_bps: int
    created_at: str
    updated_at: str
    version: int


class SurgeWindow(TypedDict, total=False):
    id: str
    depot_id: str
    start_date: str
    end_date: str
    admission_policy: str
    daily_pallet_cap: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class StandingLine(TypedDict):
    product_form: str
    packaging: str
    quantity_units: int


class RecurringRoute(TypedDict, total=False):
    id: str
    customer_id: str
    depot_id: str
    weekday: str
    window_start: str
    window_end: str
    standing_lines: List[StandingLine]
    status: str
    last_generated_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    customer_id: str
    depot_id: str
    recurring_route_id: Optional[str]
    channel: str
    event_date: str
    window_start: str
    window_end: str
    fulfillment_status: str
    billing_status: str
    delivery_slot_id: Optional[str]
    dispatch_run_id: Optional[str]
    invoice_id: Optional[str]
    price_book_id: Optional[str]
    price_book_version: Optional[int]
    pricing_mode: Optional[str]
    pallets_required: int
    dry_ice_lbs: int
    merchandise_subtotal_cents: int
    discount_cents: int
    delivery_fee_cents: int
    surcharge_cents: int
    deposit_cents: int
    total_cents: int
    quoted_at: Optional[str]
    confirmed_at: Optional[str]
    fulfilled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    product_form: str
    packaging: str
    quantity_units: int
    unit_weight_lbs: int
    unit_price_cents: int
    line_total_cents: int
    created_at: str
    updated_at: str
    version: int


class DeliverySlot(TypedDict, total=False):
    id: str
    depot_id: str
    date: str
    window_start: str
    window_end: str
    capacity_pallets: int
    reserved_pallets: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ColdStorageHold(TypedDict, total=False):
    id: str
    depot_id: str
    order_id: str
    zone: str
    pallets_required: int
    interval_start: str
    interval_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DispatchRun(TypedDict, total=False):
    id: str
    depot_id: str
    run_date: str
    vehicle_label: str
    max_pallets: int
    ventilated_dry_ice_cap_lbs: int
    assigned_pallets: int
    assigned_dry_ice_lbs: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    customer_id: str
    period_start: str
    period_end: str
    status: str
    merchandise_subtotal_cents: int
    discount_cents: int
    delivery_fee_cents: int
    surcharge_cents: int
    deposit_cents: int
    total_cents: int
    amount_paid_cents: int
    balance_due_cents: int
    due_date: Optional[str]
    issued_by_user_id: Optional[str]
    voided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only ledger entries (PRD §2.5): only id + created_at are carried;
# updated_at and version are deliberately absent.
class Payment(TypedDict, total=False):
    id: str
    customer_id: str
    amount_cents: int
    method: str
    received_at: str
    applied_cents: int
    overpayment_cents: int
    allocations: List[dict]
    created_at: str


class WaitlistEntry(TypedDict, total=False):
    id: str
    order_id: str
    depot_id: str
    requested_pallets: int
    status: str
    queued_at: str
    promoted_at: Optional[str]
    created_at: str
