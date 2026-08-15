"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §2.9)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    CHANDLER_OPS_MANAGER = "ChandlerOpsManager"
    CHANDLER_SALES_REP = "ChandlerSalesRep"
    WAREHOUSE_SUPERVISOR = "WarehouseSupervisor"
    VESSEL_CATERING_OFFICER = "VesselCateringOfficer"
    PORT_CUSTOMS_OFFICER = "PortCustomsOfficer"
    FINANCE_CONTROLLER = "FinanceController"
    SHIP_AGENT_CLERK = "ShipAgentClerk"
    QUALITY_ASSURANCE_LEAD = "QualityAssuranceLead"


# ---------------------------------------------------------------------------
# Status enums (PRD §2.9, §3.x)
# ---------------------------------------------------------------------------

class VesselCallStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PORT = "IN_PORT"
    DEPARTED = "DEPARTED"
    CANCELLED = "CANCELLED"


class CustomsClearanceStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


class RequisitionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    QUOTED = "QUOTED"
    CLOSED = "CLOSED"


class QuotationStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class FulfillmentStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_DELIVERED = "PARTIALLY_DELIVERED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNINVOICED = "UNINVOICED"
    INVOICED = "INVOICED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    CREDITED = "CREDITED"


class DeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    CREDITED = "CREDITED"
    VOID = "VOID"


class ComplaintStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class CreditNoteStatus(str, Enum):
    APPLIED = "APPLIED"
    REVOKED = "REVOKED"


class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    SGD = "SGD"


class ItemCategory(str, Enum):
    PROVISIONS = "PROVISIONS"
    BONDED = "BONDED"
    DECK = "DECK"
    ENGINE = "ENGINE"
    CABIN = "CABIN"


class StorageTier(str, Enum):
    BONDED_WAREHOUSE = "BONDED_WAREHOUSE"
    COLD_STORE = "COLD_STORE"
    DRY_STORE = "DRY_STORE"


class ComplaintReason(str, Enum):
    SPOILED = "SPOILED"
    DAMAGED = "DAMAGED"
    WRONG_ITEM = "WRONG_ITEM"
    SHORT = "SHORT"


class CustomsDecision(str, Enum):
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4: every resource has id + created_at; full
# bookkeeping resources additionally carry updated_at + version. Payment is
# the single append-only exception: id + created_at only.)
# ---------------------------------------------------------------------------

class ShipAgent(TypedDict, total=False):
    id: str
    name: str
    settlement_currency: str
    credit_limit_cents: int
    payment_terms_days: int
    committed_exposure_cents: int
    settled_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class VesselCall(TypedDict, total=False):
    id: str
    vessel_name: str
    imo_number: str
    agent_id: str
    port_code: str
    scheduled_eta: str
    scheduled_etd: str
    actual_eta: Optional[str]
    actual_etd: Optional[str]
    foreign_going: bool
    status: str
    customs_clearance_status: str
    created_at: str
    updated_at: str
    version: int


class CatalogItem(TypedDict, total=False):
    id: str
    sku: str
    name: str
    category: str
    bonded_eligible: bool
    requires_cold_chain: bool
    base_price_cents: int
    duty_rate_pct: float
    created_at: str
    updated_at: str
    version: int


class StockLot(TypedDict, total=False):
    id: str
    catalog_item_id: str
    lot_code: str
    storage_tier: str
    received_qty: int
    on_hand_qty: int
    reserved_qty: int
    capacity_qty: int
    created_at: str
    updated_at: str
    version: int


class Requisition(TypedDict, total=False):
    id: str
    vessel_call_id: str
    title: str
    lines: List[Dict[str, Any]]
    status: str
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Quotation(TypedDict, total=False):
    id: str
    requisition_id: str
    lines: List[Dict[str, Any]]
    valid_until: str
    provisional_total_cents: int
    revision_count: int
    authored_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    quotation_id: str
    agent_id: str
    lines: List[Dict[str, Any]]
    subtotal_cents: int
    rebate_cents: int
    total_cents: int
    accepted_at: str
    reservation_window_end: str
    fulfillment_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class Delivery(TypedDict, total=False):
    id: str
    order_id: str
    window_start: str
    window_end: str
    lines: List[Dict[str, Any]]
    confirmed_lines: Optional[List[Dict[str, Any]]]
    receiver_name: Optional[str]
    signature_ref: Optional[str]
    confirmed_at: Optional[str]
    created_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    order_id: str
    settlement_currency: str
    fx_rate_to_settlement: float
    lines: List[Dict[str, Any]]
    duty_free_subtotal_cents: int
    dutiable_subtotal_cents: int
    total_duty_cents: int
    subtotal_cents: int
    rebate_cents: int
    total_usd_cents: int
    total_cents: int
    paid_amount_cents: int
    credited_amount_cents: int
    fx_writeoff_cents: int
    outstanding_cents: int
    issued_at: str
    due_date: str
    issued_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    # Append-only event log entry (PRD §2.4): id + created_at ONLY.
    # Neither updated_at nor version exists on payments.
    id: str
    created_at: str
    invoice_id: str
    amount_cents: int
    currency: str
    fx_rate_to_invoice_currency: Optional[float]
    converted_amount_cents: int
    writeoff_applied_cents: int
    recorded_by_user_id: str


class QualityComplaint(TypedDict, total=False):
    id: str
    delivery_id: str
    lines: List[Dict[str, Any]]
    evidence_note: str
    reopen_count: int
    last_reviewer_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditNote(TypedDict, total=False):
    id: str
    complaint_id: str
    invoice_id: str
    gross_amount_cents: int
    restocking_fee_cents: int
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
