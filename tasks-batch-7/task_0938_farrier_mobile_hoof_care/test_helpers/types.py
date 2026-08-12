"""Domain types: entity TypedDicts, status enums, role enum (PRD 2.11)."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    DISPATCHER = "Dispatcher"
    FARRIER = "Farrier"
    CLIENT_USER = "ClientUser"
    VETERINARIAN = "Veterinarian"
    BILLING_CLERK = "BillingClerk"


class BarnZone(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class Weekday(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class ClientBillingStanding(str, Enum):
    ACTIVE = "ACTIVE"
    PREPAY_REQUIRED = "PREPAY_REQUIRED"
    SUSPENDED = "SUSPENDED"


class HorseLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class HorseHoldStatus(str, Enum):
    CLEAR = "CLEAR"
    HOLD = "HOLD"


class Limb(str, Enum):
    LF = "LF"
    RF = "RF"
    LH = "LH"
    RH = "RH"


class ShoeingState(str, Enum):
    BAREFOOT = "BAREFOOT"
    SHOD = "SHOD"
    SHOD_WITH_PAD = "SHOD_WITH_PAD"
    GLUED = "GLUED"


class CertificationLevel(str, Enum):
    APPRENTICE = "APPRENTICE"
    JOURNEYMAN = "JOURNEYMAN"
    CERTIFIED_THERAPEUTIC = "CERTIFIED_THERAPEUTIC"


class FarrierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DECERTIFIED = "DECERTIFIED"


class DeactivationReason(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    CERT_EXPIRED = "CERT_EXPIRED"


class ShoeMaterial(str, Enum):
    STEEL = "STEEL"
    ALUMINUM = "ALUMINUM"
    COMPOSITE = "COMPOSITE"


class BucketLocationKind(str, Enum):
    SHOP = "SHOP"
    VAN = "VAN"


class StockTransferStatus(str, Enum):
    REQUESTED = "REQUESTED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"
    ABORTED = "ABORTED"


class ShoeReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class RateCardStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class RouteStatus(str, Enum):
    DRAFT = "DRAFT"
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class RouteStopStatus(str, Enum):
    PENDING = "PENDING"
    ARRIVED = "ARRIVED"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class ReorderDirection(str, Enum):
    EARLIER = "EARLIER"
    LATER = "LATER"


class AppointmentStatus(str, Enum):
    UNROUTED = "UNROUTED"
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    CANCELLED_ADVANCE = "CANCELLED_ADVANCE"
    CANCELLED_LATE = "CANCELLED_LATE"
    CANCELLED_ONSITE = "CANCELLED_ONSITE"
    NO_SHOW = "NO_SHOW"


class AppointmentBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class VisitKind(str, Enum):
    ROUTINE = "ROUTINE"
    WARRANTY_REVISIT = "WARRANTY_REVISIT"


class WarrantyReason(str, Enum):
    SPRUNG_SHOE = "SPRUNG_SHOE"
    LOST_SHOE = "LOST_SHOE"
    QUICK = "QUICK"


class CycleSource(str, Enum):
    ROUTINE = "ROUTINE"
    THERAPEUTIC = "THERAPEUTIC"


class ServiceType(str, Enum):
    TRIM = "TRIM"
    RESET = "RESET"
    NEW_SHOES = "NEW_SHOES"
    CORRECTIVE = "CORRECTIVE"
    GLUE_ON = "GLUE_ON"


class ServiceLineStatus(str, Enum):
    PLANNED = "PLANNED"
    PERFORMED = "PERFORMED"
    OMITTED = "OMITTED"
    REMOVED = "REMOVED"


class LamenessCaseStatus(str, Enum):
    OPEN = "OPEN"
    PRESCRIBED = "PRESCRIBED"
    RESOLVED = "RESOLVED"


class PrescriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"


class InvoiceLineKind(str, Enum):
    LABOR = "LABOR"
    PRODUCT = "PRODUCT"
    PAD = "PAD"
    TRIP_FEE = "TRIP_FEE"
    CANCELLATION_FEE = "CANCELLATION_FEE"
    NO_SHOW_FEE = "NO_SHOW_FEE"
    MULTI_HORSE_DISCOUNT = "MULTI_HORSE_DISCOUNT"
    LOYALTY_DISCOUNT = "LOYALTY_DISCOUNT"
    TAX = "TAX"


class ReminderStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class DeliveryOutcome(str, Enum):
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


# --- Entity shapes (PRD 2.11). All carry id/created_at/updated_at/version
# --- except InvoiceLine, which carries only id and created_at.


class Barn(TypedDict):
    id: str
    name: str
    zone: str
    served_weekdays: List[str]
    access_open_minute: int
    access_close_minute: int
    blackout_dates: List[str]
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    display_name: str
    home_barn_id: str
    billing_standing: str
    deposit_balance_cents: int
    credit_balance_cents: int
    completed_visit_count: int
    no_show_count_rolling: int
    tax_exempt: bool
    created_at: str
    updated_at: str
    version: int


class Horse(TypedDict):
    id: str
    client_id: str
    barn_id: str
    name: str
    routine_cycle_weeks: int
    requires_sedation: bool
    shoe_size_code: str
    lifecycle_status: str
    hold_status: str
    active_prescription_id: Optional[str]
    next_due_on: Optional[str]
    last_completed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LimbState(TypedDict):
    id: str
    horse_id: str
    limb: str
    shoeing_state: str
    current_sku_code: Optional[str]
    last_serviced_on: Optional[str]
    consecutive_reset_count: int
    created_at: str
    updated_at: str
    version: int


class Farrier(TypedDict):
    id: str
    display_name: str
    certification_level: str
    cert_expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ShoeSku(TypedDict):
    id: str
    sku_code: str
    size_code: str
    material: str
    price_cents_per_pair: int
    created_at: str
    updated_at: str
    version: int


class InventoryBucket(TypedDict):
    id: str
    location_kind: str
    farrier_id: Optional[str]
    sku_id: str
    on_hand_pairs: int
    available_pairs: int
    reserved_pairs: int
    replenishment_flag: bool
    created_at: str
    updated_at: str
    version: int


class StockTransfer(TypedDict):
    id: str
    sku_id: str
    from_bucket_id: str
    to_bucket_id: str
    quantity_pairs: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShoeReservation(TypedDict):
    id: str
    appointment_id: str
    sku_id: str
    bucket_id: str
    pairs: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RateCard(TypedDict):
    id: str
    label: str
    effective_from: str
    supersedes_rate_card_id: Optional[str]
    price_trim_cents: int
    price_reset_cents: int
    price_new_shoes_cents: int
    price_corrective_cents: int
    price_glue_on_cents: int
    pad_price_cents: int
    trip_fee_zone_a_cents: int
    trip_fee_zone_b_cents: int
    trip_fee_zone_c_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    farrier_id: str
    route_date: str
    status: str
    committed_units: int
    committed_minutes: int
    stop_count: int
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict):
    id: str
    route_id: str
    barn_id: str
    sequence_index: int
    planned_start_minute: int
    status: str
    travel_minutes: int
    service_minutes: int
    end_minute: int
    trip_fee_cents: int
    billable_horse_count: int
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    horse_id: str
    route_stop_id: Optional[str]
    origin_appointment_id: Optional[str]
    rate_card_id: Optional[str]
    scheduled_date: str
    visit_kind: str
    warranty_reason: Optional[str]
    cycle_source: Optional[str]
    status: str
    billing_status: str
    vet_present: bool
    service_units: int
    service_minutes: int
    estimated_total_cents: int
    cancellation_fee_cents: int
    trip_fee_share_cents: int
    completed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceLine(TypedDict):
    id: str
    appointment_id: str
    limb_state_id: str
    prescription_id: Optional[str]
    sku_id: Optional[str]
    limb: str
    service_type: str
    with_pad: bool
    status: str
    labor_cents: int
    created_at: str
    updated_at: str
    version: int


class LamenessCase(TypedDict):
    id: str
    horse_id: str
    reported_on: str
    severity: int
    status: str
    hold_applied: bool
    created_at: str
    updated_at: str
    version: int


class VetPrescription(TypedDict):
    id: str
    lameness_case_id: str
    horse_id: str
    issued_on: str
    expires_on: str
    limb_scope: List[str]
    prescribed_cycle_weeks: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    appointment_id: str
    client_id: str
    rate_card_id: Optional[str]
    status: str
    issued_on: Optional[str]
    labor_subtotal_cents: int
    product_subtotal_cents: int
    multi_horse_discount_cents: int
    loyalty_discount_cents: int
    loyalty_discount_labor_cents: int
    loyalty_discount_product_cents: int
    labor_net_cents: int
    trip_fee_share_cents: int
    fee_cents: int
    taxable_product_base_cents: int
    tax_cents: int
    total_cents: int
    paid_cents: int
    balance_cents: int
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict):
    """Immutable once written: carries only id and created_at (PRD 2.4)."""

    id: str
    invoice_id: str
    line_kind: str
    description: str
    limb: Optional[str]
    service_type: Optional[str]
    sku_code: Optional[str]
    quantity: int
    unit_amount_cents: int
    amount_cents: int
    taxable: bool
    created_at: str


class Reminder(TypedDict):
    id: str
    appointment_id: str
    offset_days: int
    due_on: str
    status: str
    sent_on: Optional[str]
    created_at: str
    updated_at: str
    version: int
