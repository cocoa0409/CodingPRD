"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    MARKET_ADMIN = "MarketAdmin"
    RECEIVER = "Receiver"
    USDA_INSPECTOR = "USDAInspector"
    SALES_DESK = "SalesDesk"
    BILLING_CLERK = "BillingClerk"
    CUSTOMER_REP = "CustomerRep"


class ShipperStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class EthyleneClass(str, Enum):
    PRODUCER = "PRODUCER"
    SENSITIVE = "SENSITIVE"
    NEUTRAL = "NEUTRAL"


class LotStatus(str, Enum):
    ORDERED = "ORDERED"
    RECEIVED = "RECEIVED"
    INSPECTED = "INSPECTED"
    DISPUTED = "DISPUTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class InspectionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    VOIDED = "VOIDED"


class ColdChainStatus(str, Enum):
    OK = "OK"
    VIOLATED = "VIOLATED"


class BookingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROCESS = "IN_PROCESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ShrinkReason(str, Enum):
    DUMP = "DUMP"
    TRIM = "TRIM"
    DAMAGE = "DAMAGE"
    THEFT = "THEFT"


class ShrinkStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"


class CreditMemoStatus(str, Enum):
    ISSUED = "ISSUED"
    VOID = "VOID"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    ON_HOLD = "ON_HOLD"
    PICKED = "PICKED"
    DELIVERED = "DELIVERED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


class HoldReason(str, Enum):
    COLD_CHAIN = "COLD_CHAIN"
    CREDIT = "CREDIT"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PAST_DUE = "PAST_DUE"
    TRUST_CLAIMED = "TRUST_CLAIMED"
    PAID = "PAID"


class TicketType(str, Enum):
    HOURLY = "HOURLY"
    PIECE = "PIECE"


class DisputeOutcome(str, Enum):
    ACCEPT_AS_IS = "ACCEPT_AS_IS"
    PRICE_ADJUST = "PRICE_ADJUST"
    REJECT_TO_SHIPPER = "REJECT_TO_SHIPPER"


# --- Entity TypedDicts -------------------------------------------------------
# Common-field entities carry id + created_at + updated_at + version (PRD §2.4).
# TemperatureReading and Payment are append-only: id + created_at only.

class Shipper(TypedDict):
    id: str
    name: str
    paca_license: str
    status: str
    trust_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    name: str
    credit_limit_cents: int
    terms_days: int
    paca_special_agreement: bool
    status: str
    credit_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class Commodity(TypedDict):
    id: str
    code: str
    name: str
    ethylene_class: str
    temp_min_f: float
    temp_max_f: float
    max_violation_minutes: int
    created_at: str
    updated_at: str
    version: int


class DailyPrice(TypedDict):
    id: str
    commodity_id: str
    market_date: str
    low_price: float
    high_price: float
    mid_price: float
    created_at: str
    updated_at: str
    version: int


class PurchaseLot(TypedDict):
    id: str
    shipper_id: str
    commodity_id: str
    market_date: str
    quantity_units: int
    shipper_unit_price: float
    declared_grade: str
    status: str
    received_at: Optional[str]
    provisional_cost_cents: int
    adjusted_cost_cents: int
    payable_cents: int
    dumped_units: int
    reserved_units: int
    sold_units: int
    available_units: int
    cold_chain_status: str
    violation_minutes: int
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    purchase_lot_id: str
    inspected_grade: str
    defect_pct: float
    result: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TemperatureReading(TypedDict):
    # Append-only ledger row: id + created_at only, no updated_at / version (PRD §2.4).
    id: str
    purchase_lot_id: str
    recorded_at: str
    temp_f: float
    duration_minutes: int
    out_of_range: bool
    created_at: str


class RipeningRoom(TypedDict):
    id: str
    name: str
    capacity_pallets: int
    ethylene_capable: bool
    created_at: str
    updated_at: str
    version: int


class RipeningBooking(TypedDict):
    id: str
    room_id: str
    purchase_lot_id: str
    pallet_count: int
    start_time: str
    end_time: str
    ethylene_enabled: bool
    target_stage: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ShrinkRecord(TypedDict):
    id: str
    purchase_lot_id: str
    quantity: int
    reason: str
    status: str
    credit_memo_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditMemo(TypedDict):
    id: str
    purchase_lot_id: str
    amount_cents: int
    status: str
    issued_at: str
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict):
    id: str
    customer_id: str
    delivery_date: str
    window_start: str
    window_end: str
    pallet_count: int
    lines: list
    status: str
    hold_reason: Optional[str]
    subtotal_cents: int
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    sales_order_id: str
    customer_id: str
    invoice_date: str
    due_date: str
    discount_eligible_until: str
    subtotal_cents: int
    deposit_cents: int
    total_cents: int
    discount_taken_cents: int
    paid_cents: int
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    # Append-only ledger row: id + created_at only, no updated_at / version (PRD §2.4).
    id: str
    invoice_id: str
    amount_cents: int
    paid_at: str
    created_at: str


class LaborTicket(TypedDict):
    id: str
    purchase_lot_id: str
    ticket_type: str
    work_date: str
    hours: float
    pieces: Optional[int]
    hourly_rate: Optional[float]
    piece_rate: Optional[float]
    charge_cents: int
    created_at: str
    updated_at: str
    version: int
