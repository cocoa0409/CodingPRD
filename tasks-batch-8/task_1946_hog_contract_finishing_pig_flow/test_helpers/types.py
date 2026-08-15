"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    INTEGRATOR_ADMIN = "IntegratorAdmin"
    FIELD_TECH = "FieldTech"
    GROWER = "Grower"
    FEED_MILL = "FeedMill"
    TRANSPORT_COORDINATOR = "TransportCoordinator"
    ENVIRONMENTAL_MANAGER = "EnvironmentalManager"


class SiteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DECOMMISSIONED = "DECOMMISSIONED"


class GrowerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class BarnStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    WASH_REQUIRED = "WASH_REQUIRED"
    WASHING = "WASHING"
    DOWNTIME = "DOWNTIME"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class GroupStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PLACED = "PLACED"
    MARKETING = "MARKETING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class Phase(str, Enum):
    STARTER = "STARTER"
    GROWER = "GROWER"
    FINISHER_1 = "FINISHER_1"
    FINISHER_2 = "FINISHER_2"


class FeedOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    SHORTED = "SHORTED"
    CANCELLED = "CANCELLED"


class ReasonCode(str, Enum):
    DISEASE = "DISEASE"
    INJURY = "INJURY"
    STRESS = "STRESS"
    OTHER = "OTHER"


class SlotStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"


class Shift(str, Enum):
    AM = "AM"
    PM = "PM"


class WashType(str, Enum):
    FULL_DISINFECT = "FULL_DISINFECT"
    WASH_ONLY = "WASH_ONLY"


class WashStatus(str, Enum):
    RECORDED = "RECORDED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class LoadStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    REJECTED_AT_PLANT = "REJECTED_AT_PLANT"
    CANCELLED = "CANCELLED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ApplicationStatus(str, Enum):
    RECORDED = "RECORDED"
    CONFIRMED = "CONFIRMED"
    VOIDED = "VOIDED"


class TicketCategory(str, Enum):
    STRUCTURAL = "STRUCTURAL"
    EQUIPMENT = "EQUIPMENT"
    ROUTINE = "ROUTINE"
    EMERGENCY = "EMERGENCY"


class TicketCause(str, Enum):
    WEAR = "WEAR"
    NEGLIGENCE = "NEGLIGENCE"
    ACT_OF_NATURE = "ACT_OF_NATURE"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    QUOTED = "QUOTED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    APPROVED = "APPROVED"
    PAID = "PAID"


# --- Entity shapes (PRD §2.5: id/created_at/updated_at/version on primary
# resources; mortality reports are append-only and carry only id + created_at) ---


class Site(TypedDict, total=False):
    id: str
    name: str
    state_code: str
    county: str
    site_status: str
    total_capacity_head: int
    created_at: str
    updated_at: str
    version: int


class Grower(TypedDict, total=False):
    id: str
    legal_name: str
    grower_code: str
    email: str
    grower_status: str
    balance_due_cents: int
    lifetime_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    grower_id: str
    site_id: str
    base_pay_cents_per_head: int
    bonus_cap_cents_per_head: int
    fcr_target: float
    adg_target_lbs: float
    mortality_threshold_pct: float
    feed_budget_lbs_per_head: int
    structural_owner_pct: int
    equipment_owner_pct: int
    routine_owner_pct: int
    effective_date: str
    expiry_date: str
    contract_status: str
    created_at: str
    updated_at: str
    version: int


class Barn(TypedDict, total=False):
    id: str
    site_id: str
    barn_code: str
    capacity_head: int
    floor_space_sqft: int
    barn_status: str
    wash_required: bool
    downtime_until: Optional[str]
    current_group_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PigGroup(TypedDict, total=False):
    id: str
    barn_id: str
    contract_id: str
    placement_date: str
    target_market_date: str
    head_placed: int
    avg_start_weight_lbs: float
    group_status: str
    current_phase: str
    placed_at: Optional[str]
    closed_at: Optional[str]
    mortality_total: int
    cull_total: int
    head_marketed: int
    head_unaccounted: int
    head_current: int
    total_live_weight_lbs: int
    cumulative_feed_lbs: int
    mortality_pct: float
    pending_deductions_cents: int
    created_at: str
    updated_at: str
    version: int


class FeedOrder(TypedDict, total=False):
    id: str
    group_id: str
    phase: str
    diet_code: str
    quantity_lbs: int
    requested_delivery_date: str
    scheduled_delivery_date: Optional[str]
    delivered_lbs: Optional[int]
    over_phase_plan: bool
    order_status: str
    created_at: str
    updated_at: str
    version: int


class MortalityReport(TypedDict, total=False):
    # Append-only event (PRD §2.5): only id + created_at, NO updated_at/version.
    id: str
    group_id: str
    report_date: str
    mortality_count: int
    cull_count: int
    reason_code: str
    created_at: str


class PackerSlot(TypedDict, total=False):
    id: str
    plant_code: str
    slot_date: str
    shift: str
    capacity_head: int
    min_weight_lbs: int
    max_weight_lbs: int
    reserved_head: int
    slot_status: str
    created_at: str
    updated_at: str
    version: int


class TruckWash(TypedDict, total=False):
    id: str
    truck_code: str
    washed_at: str
    wash_type: str
    recorded_by: str
    verified_by: Optional[str]
    wash_status: str
    created_at: str
    updated_at: str
    version: int


class MarketLoad(TypedDict, total=False):
    id: str
    group_id: str
    slot_id: str
    head_count: int
    truck_wash_id: Optional[str]
    live_weight_lbs_total: Optional[int]
    avg_weight_lbs: Optional[float]
    load_status: str
    created_at: str
    updated_at: str
    version: int


class BarnWash(TypedDict, total=False):
    id: str
    barn_id: str
    wash_type: str
    completed_at: str
    recorded_by: str
    verified_by: Optional[str]
    wash_status: str
    created_at: str
    updated_at: str
    version: int


class ManurePlan(TypedDict, total=False):
    id: str
    site_id: str
    plan_year: int
    lagoon_capacity_gal: int
    lagoon_start_gal: int
    n_budget_lbs: int
    p_budget_lbs: int
    submitted_by: Optional[str]
    plan_status: str
    n_applied_lbs: int
    p_applied_lbs: int
    lagoon_available_gal: int
    created_at: str
    updated_at: str
    version: int


class ManureApplication(TypedDict, total=False):
    id: str
    plan_id: str
    field_code: str
    applied_at: str
    gallons: int
    n_lbs: int
    p_lbs: int
    application_status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceTicket(TypedDict, total=False):
    id: str
    barn_id: str
    contract_id: str
    grower_id: str
    category: str
    description: str
    cause: str
    cost_cents: int
    quoted_by: str
    approved_by: Optional[str]
    approved_flag: bool
    owner_share_cents: int
    grower_share_cents: int
    completed_at: Optional[str]
    ticket_status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    group_id: str
    contract_id: str
    head_marketed: int
    total_live_weight_lbs: int
    days_on_feed: int
    fcr: Optional[float]
    adg_lbs: Optional[float]
    mortality_pct: float
    base_pay_cents: int
    bonus_cents: int
    deductions_cents: int
    adjustment_cents: int
    total_pay_cents: int
    approved_by: Optional[str]
    paid_by: Optional[str]
    settlement_status: str
    created_at: str
    updated_at: str
    version: int
