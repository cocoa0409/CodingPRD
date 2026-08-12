"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class BrandProgram(str, Enum):
    MARQUEE_SELECT = "MARQUEE_SELECT"
    MARQUEE_LUXE = "MARQUEE_LUXE"
    INDIE_SOFT = "INDIE_SOFT"


class BudgetCategory(str, Enum):
    FURNITURE = "FURNITURE"
    LIGHTING = "LIGHTING"
    TEXTILES = "TEXTILES"
    DECOR = "DECOR"
    APPLIANCES = "APPLIANCES"
    FREIGHT = "FREIGHT"
    INSTALLATION = "INSTALLATION"


class FFEProjectStatus(str, Enum):
    PLANNING = "PLANNING"
    PROCUREMENT = "PROCUREMENT"
    INSTALLATION = "INSTALLATION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ProcurementPosture(str, Enum):
    OPEN = "OPEN"
    SEALED = "SEALED"
    FROZEN = "FROZEN"


class SpecItemStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    BRAND_APPROVED = "BRAND_APPROVED"
    BRAND_REJECTED = "BRAND_REJECTED"
    LOCKED = "LOCKED"


class VendorBidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SAMPLE_APPROVED = "SAMPLE_APPROVED"
    SAMPLE_REJECTED = "SAMPLE_REJECTED"
    AWARDED = "AWARDED"
    ORDERED = "ORDERED"
    REJECTED = "REJECTED"


class POFulfillmentStatus(str, Enum):
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    READY_TO_SHIP = "READY_TO_SHIP"
    CONSOLIDATED = "CONSOLIDATED"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class POInvoiceStatus(str, Enum):
    UNBILLED = "UNBILLED"
    PARTIALLY_INVOICED = "PARTIALLY_INVOICED"
    INVOICED = "INVOICED"
    PAID = "PAID"


class POLineStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    FULLY_RECEIVED = "FULLY_RECEIVED"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class ShipmentStatus(str, Enum):
    PLANNED = "PLANNED"
    CONSOLIDATING = "CONSOLIDATING"
    SEALED = "SEALED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class FreightMode(str, Enum):
    FCL = "FCL"
    LTL = "LTL"


class ReceivingEventStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class DamageClaimStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    DISPUTED = "DISPUTED"
    RESOLVED_CREDIT = "RESOLVED_CREDIT"
    RESOLVED_REPLACEMENT = "RESOLVED_REPLACEMENT"
    DENIED = "DENIED"
    VOID = "VOID"


class DamageClaimType(str, Enum):
    DAMAGE = "DAMAGE"
    SHORTAGE = "SHORTAGE"


class RoomType(str, Enum):
    GUEST_KING = "GUEST_KING"
    GUEST_DOUBLE = "GUEST_DOUBLE"
    SUITE = "SUITE"
    CORRIDOR = "CORRIDOR"
    LOBBY = "LOBBY"


class InstallationWindowStatus(str, Enum):
    PLANNED = "PLANNED"
    RELEASED = "RELEASED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class InstallationTaskStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class AtticDirection(str, Enum):
    IN = "IN"
    OUT = "OUT"
    WRITE_OFF = "WRITE_OFF"


class ChangeOrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class UserRole(str, Enum):
    PURCHASING_AGENT = "PurchasingAgent"
    BRAND_APPROVER = "BrandApprover"
    VENDOR = "Vendor"
    WAREHOUSE_RECEIVER = "WarehouseReceiver"
    INSTALLATION_MANAGER = "InstallationManager"
    OWNER_REP = "OwnerRep"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4 common fields: id, created_at, updated_at, version)
# ---------------------------------------------------------------------------

class FFEProject(TypedDict):
    id: str
    name: str
    hotel_name: str
    brand_program: str
    total_budget_cents: int
    unallocated_contingency_cents: int
    default_crew_capacity_per_floor_day: int
    committed_cents: int
    actual_spend_cents: int
    sunk_fees_cents: int
    procurement_posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BudgetLine(TypedDict):
    id: str
    project_id: str
    category: str
    budgeted_cents: int
    committed_cents: int
    actual_cents: int
    variance_commitment_cents: int
    variance_final_cents: int
    created_at: str
    updated_at: str
    version: int


class SpecItem(TypedDict):
    id: str
    project_id: str
    category: str
    description: str
    brand_standard_ref: str
    quantity_per_room: int
    room_count: int
    total_qty: int
    unit_budget_cents: int
    required_lead_days: int
    is_critical: bool
    attic_target_pct: float
    attic_min_qty: int
    attic_max_qty: int
    attic_target_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VendorBid(TypedDict):
    id: str
    spec_item_id: str
    vendor_name: str
    unit_price_cents: int
    freight_estimate_cents: int
    lead_time_days: int
    sample_round: int
    evaluated_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict):
    id: str
    project_id: str
    vendor_name: str
    shipment_id: Optional[str]
    fulfillment_status: str
    invoice_status: str
    total_extended_cents: int
    total_cube_m3: int
    created_at: str
    updated_at: str
    version: int


class POLine(TypedDict):
    id: str
    purchase_order_id: str
    spec_item_id: str
    quantity_ordered: int
    declared_cube_m3: int
    unit_price_cents: int
    extended_cents: int
    qty_received: int
    qty_damaged_unresolved: int
    qty_damaged_credited: int
    qty_short: int
    qty_installable: int
    qty_installed: int
    qty_attic: int
    freight_alloc_provisional_cents: int
    freight_alloc_final_cents: Optional[int]
    damage_credit_cents: int
    actual_landed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    project_id: str
    carrier_name: str
    total_cube_m3: int
    freight_mode: Optional[str]
    freight_total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReceivingEventLine(TypedDict):
    po_line_id: str
    qty_received: int
    qty_damaged: int


class ReceivingEvent(TypedDict):
    id: str
    shipment_id: str
    lines: List[ReceivingEventLine]
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict):
    id: str
    po_line_id: str
    claim_type: str
    quantity: int
    claimed_credit_cents: int
    approved_credit_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    project_id: str
    floor_number: int
    room_number: str
    room_type: str
    created_at: str
    updated_at: str
    version: int


class InstallationWindow(TypedDict):
    id: str
    project_id: str
    floor_number: int
    start_date: str
    end_date: str
    crew_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InstallationTask(TypedDict):
    id: str
    window_id: str
    room_id: str
    po_line_id: str
    quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AtticStockMovement(TypedDict):
    # Append-only event (PRD §2.4): carries only id + created_at.
    # No updated_at, no version.
    id: str
    po_line_id: str
    direction: str
    quantity: int
    resulting_installable: int
    resulting_attic: int
    created_at: str


class ChangeOrderAdjustment(TypedDict):
    budget_line_id: str
    delta_cents: int


class ChangeOrder(TypedDict):
    id: str
    project_id: str
    title: str
    adjustments: List[ChangeOrderAdjustment]
    proposer_user_id: str
    fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
