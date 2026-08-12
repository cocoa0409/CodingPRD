"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity model. Every entity carries the common fields
id, created_at, updated_at, version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    FARM_MANAGER = "FarmManager"
    COMPOST_SUPERVISOR = "CompostSupervisor"
    GRADING_INSPECTOR = "GradingInspector"
    HARVEST_CREW_LEAD = "HarvestCrewLead"
    PAYROLL_CLERK = "PayrollClerk"
    SALES_MANAGER = "SalesManager"
    QUALITY_INSPECTOR = "QualityInspector"
    BUYER_PORTAL = "BuyerPortal"
    ANY = "Any"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class SubstrateRecipe(str, Enum):
    PHASE_II_COMPOST = "PHASE_II_COMPOST"
    STRAW_SAWDUST = "STRAW_SAWDUST"


class BuyerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class WorkerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CommitmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CommitmentLineStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class SettlementOutcome(str, Enum):
    FULFILLED = "FULFILLED"
    SHORTFALL = "SHORTFALL"


class Grade(str, Enum):
    A = "A"
    B = "B"


class BatchStatus(str, Enum):
    MIXED = "MIXED"
    PASTEURIZING = "PASTEURIZING"
    CONDITIONED = "CONDITIONED"
    SPAWNED = "SPAWNED"
    EXHAUSTED = "EXHAUSTED"
    RETIRED = "RETIRED"


class TunnelStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class PasteurizationCycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


class RoomOccupancyStatus(str, Enum):
    IDLE = "IDLE"
    OCCUPIED = "OCCUPIED"
    TURNAROUND = "TURNAROUND"


class RoomHealthStatus(str, Enum):
    CLEAR = "CLEAR"
    WATCH = "WATCH"
    QUARANTINED = "QUARANTINED"


class RoomCycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SPAWN_RUN = "SPAWN_RUN"
    CASING = "CASING"
    FRUITING = "FRUITING"
    TURNAROUND = "TURNAROUND"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    ABORTED = "ABORTED"


class FlushStatus(str, Enum):
    RECORDED = "RECORDED"
    GRADED = "GRADED"
    SETTLED = "SETTLED"


class PieceStatus(str, Enum):
    LOGGED = "LOGGED"
    APPROVED = "APPROVED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"


class Pathogen(str, Enum):
    TRICHODERMA = "TRICHODERMA"
    COBWEB = "COBWEB"
    BACTERIAL_BLOTCH = "BACTERIAL_BLOTCH"
    VIRUS = "VIRUS"


class ContaminationEventStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    REMEDIATING = "REMEDIATING"
    CLEARED = "CLEARED"
    DISMISSED = "DISMISSED"


class PackagedLotStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    EXPIRED = "EXPIRED"


class SpentLotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    DISPOSED = "DISPOSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all carry id / created_at / updated_at / version)
# ---------------------------------------------------------------------------

class Variety(TypedDict):
    id: str
    variety_code: str
    display_name: str
    substrate_recipe: str
    target_bioefficiency_pct: float
    shelf_life_days: int
    spawn_run_days: int
    casing_days: int
    max_flushes: int
    flush_yield_distribution: List[float]
    active_committed_kg: float
    planned_production_kg: float
    created_at: str
    updated_at: str
    version: int


class Buyer(TypedDict):
    id: str
    name: str
    status: str
    lifetime_shortfall_penalty_cents: int
    created_at: str
    updated_at: str
    version: int


class BuyerCommitment(TypedDict):
    id: str
    buyer_id: str
    reference: str
    status: str
    total_committed_kg: float
    total_delivered_kg: float
    total_shortfall_penalty_cents: int
    created_at: str
    updated_at: str
    version: int


class CommitmentLine(TypedDict):
    id: str
    commitment_id: str
    variety_id: str
    committed_kg: float
    week_start: str
    week_end: str
    min_grade: str
    delivered_kg: float
    allocated_kg: float
    status: str
    settlement_outcome: Optional[str]
    shortfall_kg: float
    penalty_cents: int
    supply_at_risk: bool
    created_at: str
    updated_at: str
    version: int


class SubstrateBatch(TypedDict):
    id: str
    recipe: str
    tonnage: float
    variety_id: Optional[str]
    spawn_kg: Optional[float]
    remaining_tonnage: float
    status: str
    spent_revenue_cents: int
    disposal_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class PasteurizationTunnel(TypedDict):
    id: str
    tunnel_code: str
    capacity_tonnes: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PasteurizationCycle(TypedDict):
    id: str
    batch_id: str
    tunnel_id: str
    planned_start: str
    planned_end: str
    actual_start: Optional[str]
    hours_at_target_temp: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class GrowingRoom(TypedDict):
    id: str
    room_code: str
    capacity_tonnes: float
    occupancy_status: str
    health_status: str
    created_at: str
    updated_at: str
    version: int


class RoomCycle(TypedDict):
    id: str
    room_id: str
    batch_id: str
    variety_id: str
    allocated_tonnage: float
    planned_start: str
    planned_end: str
    placed_at: Optional[str]
    phase_entered_at: Optional[str]
    status: str
    flush_count: int
    harvested_kg: float
    scheduled_projection_kg: float
    actualized_projection_kg: float
    created_at: str
    updated_at: str
    version: int


class FlushHarvest(TypedDict):
    id: str
    room_cycle_id: str
    flush_number: int
    recorded_at: str
    total_kg: float
    grade_a_kg: Optional[float]
    grade_b_kg: Optional[float]
    cull_kg: Optional[float]
    graded_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HarvestPiece(TypedDict):
    id: str
    flush_id: str
    worker_id: str
    logged_by_user_id: str
    kg_picked: float
    rate_cents_per_kg: int
    provisional_pay_cents: int
    final_pay_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Worker(TypedDict):
    id: str
    full_name: str
    crew_code: str
    piece_rate_cents_per_kg: int
    status: str
    accrued_unpaid_cents: int
    lifetime_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class ContaminationEvent(TypedDict):
    id: str
    room_id: str
    room_cycle_id: Optional[str]
    pathogen: str
    severity: int
    affected_zone_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PackagedLot(TypedDict):
    id: str
    flush_id: str
    variety_id: str
    grade: str
    units: int
    kg_per_unit: float
    lot_kg: float
    packed_at: str
    expires_at: str
    allocated_line_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SpentSubstrateLot(TypedDict):
    id: str
    room_cycle_id: str
    batch_id: str
    tonnage: float
    disposal_only: bool
    reserved_buyer_id: Optional[str]
    sale_price_cents: Optional[int]
    disposal_cost_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
