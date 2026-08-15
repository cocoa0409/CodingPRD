"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    OPERATIONS_MANAGER = "OperationsManager"
    DOCK_BUYER = "DockBuyer"
    VESSEL_AGENT = "VesselAgent"
    GRADING_INSPECTOR = "GradingInspector"
    INVENTORY_PLANNER = "InventoryPlanner"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CUSTOMER = "Customer"
    ANY = "Any"


# ---------------------------------------------------------------------------
# Shared enums (PRD §3)
# ---------------------------------------------------------------------------

class Grade(str, Enum):
    GRADE_A = "GRADE_A"
    GRADE_B = "GRADE_B"
    GRADE_C = "GRADE_C"


class ProcessingType(str, Enum):
    WHOLE = "WHOLE"
    FILLETED = "FILLETED"


class StorageType(str, Enum):
    FRESH = "FRESH"
    FROZEN = "FROZEN"


class ShipmentMode(str, Enum):
    AIR = "AIR"
    TRUCK = "TRUCK"


class TempZone(str, Enum):
    CHILLED = "CHILLED"
    FROZEN = "FROZEN"


class DocType(str, Enum):
    HEALTH_CERT = "HEALTH_CERT"
    CITES = "CITES"
    CUSTOMS_ENTRY = "CUSTOMS_ENTRY"


# ---------------------------------------------------------------------------
# Status enums (PRD §3 workflows)
# ---------------------------------------------------------------------------

class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class TicketStatus(str, Enum):
    DRAFT = "DRAFT"
    LANDED = "LANDED"
    GRADED = "GRADED"
    SETTLED = "SETTLED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class LotLifecycle(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"
    RECALLED = "RECALLED"


class LotHoldStatus(str, Enum):
    CLEAR = "CLEAR"
    ON_HOLD = "ON_HOLD"
    CONDEMNED = "CONDEMNED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    FULFILLED = "FULFILLED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


class AllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class ShipmentStatus(str, Enum):
    QUOTED = "QUOTED"
    BOOKED = "BOOKED"
    TENDERED = "TENDERED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ImportDocStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


class HoldRecordStatus(str, Enum):
    PLACED = "PLACED"
    RELEASED = "RELEASED"
    CONDEMNED = "CONDEMNED"


class SubstitutionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"


# ---------------------------------------------------------------------------
# Entity TypedDicts. Every resource carries the PRD §2.4 common fields
# (id, created_at, updated_at, version).
# ---------------------------------------------------------------------------

class Vessel(TypedDict, total=False):
    id: str
    vessel_name: str
    registration_number: str
    home_port: str
    payable_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    business_name: str
    credit_limit_cents: int
    discount_pct: float
    credit_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class CatchArea(TypedDict, total=False):
    id: str
    fao_code: str
    name: str
    region: str
    created_at: str
    updated_at: str
    version: int


class Species(TypedDict, total=False):
    id: str
    species_code: str
    common_name: str
    labeling_name: str
    substitution_group: str
    is_import: bool
    requires_cites: bool
    fresh_shelf_life_hours: int
    frozen_shelf_life_days: int
    created_at: str
    updated_at: str
    version: int


class MarketQuote(TypedDict, total=False):
    id: str
    species_id: str
    grade: str
    quote_date: str
    price_per_kg_cents: int
    status: str
    volatility_pct: float
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class DockTicket(TypedDict, total=False):
    id: str
    vessel_id: str
    catch_area_id: str
    landing_start_at: str
    landing_end_at: str
    status: str
    regrade_count: int
    provisional_total_cents: int
    final_total_cents: int
    created_at: str
    updated_at: str
    version: int


class LandingLine(TypedDict, total=False):
    id: str
    dock_ticket_id: str
    species_id: str
    declared_grade: str
    landed_weight_kg: float
    processing_type: str
    provisional_amount_cents: int
    processed_weight_kg: float
    final_amount_cents: int
    voided: bool
    created_at: str
    updated_at: str
    version: int


class GradeAssessment(TypedDict, total=False):
    id: str
    landing_line_id: str
    inspector_user_id: str
    assessed_grade: str
    yield_pct: float
    notes: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict, total=False):
    id: str
    landing_line_id: str
    species_id: str
    storage_type: str
    landed_at: str
    frozen_at: Optional[str]
    expires_at: str
    received_weight_kg: float
    available_weight_kg: float
    reserved_weight_kg: float
    committed_weight_kg: float
    shipped_weight_kg: float
    condemned_weight_kg: float
    spoiled_weight_kg: float
    recalled_weight_kg: float
    lifecycle_status: str
    hold_status: str
    unit_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict, total=False):
    id: str
    customer_id: str
    required_delivery_date: str
    status: str
    total_cents: int
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    sales_order_id: str
    species_id: str
    requested_grade: str
    requested_qty_kg: float
    min_remaining_shelf_life_hours: int
    allow_substitution: bool
    unit_price_cents: int
    line_total_cents: int
    allocated_qty_kg: float
    committed_qty_kg: float
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict, total=False):
    id: str
    order_line_id: str
    inventory_lot_id: str
    qty_kg: float
    transit_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    sales_order_id: str
    mode: str
    flight_number: str
    flight_date: str
    temp_zone: str
    booked_weight_kg: float
    actual_weight_kg: float
    volume_m3: float
    chargeable_weight_kg: float
    provisional_freight_cents: int
    final_freight_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ImportDocument(TypedDict, total=False):
    id: str
    dock_ticket_id: str
    species_id: str
    doc_type: str
    reference_number: str
    status: str
    submitted_by_user_id: str
    reviewed_by_user_id: str
    resubmit_count: int
    created_at: str
    updated_at: str
    version: int


class InspectionHold(TypedDict, total=False):
    id: str
    inventory_lot_id: str
    reason: str
    status: str
    placed_by_user_id: str
    resolved_by_user_id: str
    placed_at: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubstitutionApproval(TypedDict, total=False):
    id: str
    order_line_id: str
    original_species_id: str
    substitute_species_id: str
    status: str
    price_credit_cents: int
    auto_created: bool
    requested_by_user_id: str
    decided_by_user_id: str
    created_at: str
    updated_at: str
    version: int
