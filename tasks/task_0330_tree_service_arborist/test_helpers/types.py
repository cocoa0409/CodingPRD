"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this domain carries the four common fields (id, created_at,
updated_at, version) per PRD §2.4 — there are no version-less entities.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum (PRD §2.1) ───────────────────────────────


class UserRole(str, Enum):
    DISPATCHER = "Dispatcher"
    ARBORIST = "Arborist"
    FINANCE_CLERK = "FinanceClerk"
    CLIENT = "Client"


# ─── Status enums (PRD §3) ──────────────────────────────


class WorkOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ASSESSED = "ASSESSED"
    QUOTED = "QUOTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PricingMode(str, Enum):
    PER_JOB = "PER_JOB"
    HOURLY = "HOURLY"


class HazardTier(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class EstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"


class ServiceType(str, Enum):
    REMOVAL = "REMOVAL"
    STUMP_GRINDING = "STUMP_GRINDING"
    HAUL_OFF = "HAUL_OFF"
    UTILITY_CLEARANCE = "UTILITY_CLEARANCE"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class BookingStatus(str, Enum):
    RESERVED = "RESERVED"
    FINALIZED = "FINALIZED"
    RELEASED = "RELEASED"


class ResourceKind(str, Enum):
    CREW = "CREW"
    EQUIPMENT = "EQUIPMENT"


class EquipmentKind(str, Enum):
    CRANE = "CRANE"
    CHIPPER = "CHIPPER"
    STUMP_GRINDER = "STUMP_GRINDER"


class DisposalTicketStatus(str, Enum):
    RECORDED = "RECORDED"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class CrewStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RETIRED = "RETIRED"


class EquipmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RETIRED = "RETIRED"


# ─── Entity TypedDicts (PRD §3) ─────────────────────────
# All entities carry id, created_at, updated_at, version (PRD §2.4).


class ServiceArea(TypedDict):
    id: str
    name: str
    region_code: str
    disposal_fee_cents_per_ton: int
    requires_permit_authority: bool
    heritage_surcharge_pct: float
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    service_area_id: str
    name: str
    hourly_rate_cents: int
    certified_utility_clearance: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict):
    id: str
    service_area_id: str
    kind: str
    name: str
    hourly_rate_cents: int
    mobilization_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    service_area_id: str
    client_user_id: str
    site_address: str
    pricing_mode: str
    is_emergency: bool
    hazard_level: str
    requires_permit: bool
    accepted_estimate_id: Optional[str]
    labor_cost_accrued_cents: int
    disposal_cost_accrued_cents: int
    final_invoice_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TreeAsset(TypedDict):
    id: str
    work_order_id: str
    species: str
    dbh_inches: float
    is_protected: bool
    is_heritage: bool
    near_utility_line: bool
    lean_degrees: float
    has_visible_decay: bool
    hazard_score: float
    hazard_tier: str
    created_at: str
    updated_at: str
    version: int


class Estimate(TypedDict):
    id: str
    work_order_id: str
    pricing_mode: str
    line_items_subtotal_cents: int
    hazard_surcharge_cents: int
    heritage_surcharge_cents: int
    utility_surcharge_cents: int
    emergency_multiplier_applied: bool
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LineItem(TypedDict):
    id: str
    estimate_id: str
    tree_asset_id: Optional[str]
    service_type: str
    quantity: float
    unit_cost_cents: int
    extended_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    work_order_id: str
    authority_ref: str
    covers_heritage: bool
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    work_order_id: str
    resource_kind: str
    crew_id: Optional[str]
    equipment_id: Optional[str]
    start_at: str
    end_at: str
    expected_work_order_version: int
    actual_hours: Optional[float]
    billed_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DisposalTicket(TypedDict):
    id: str
    work_order_id: str
    debris_tons: float
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
