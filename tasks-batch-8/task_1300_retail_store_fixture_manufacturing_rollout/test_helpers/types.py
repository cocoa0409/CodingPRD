"""Domain types: entity TypedDicts, status enums, role enum.

All nine resources carry the standard system-managed fields (id, created_at,
updated_at, version) described in PRD section 2.4.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSEOUT_PENDING = "CLOSEOUT_PENDING"
    CLOSED = "CLOSED"


class PrototypeStatus(str, Enum):
    DRAFT = "DRAFT"
    ENGINEERING_REVIEW = "ENGINEERING_REVIEW"
    VALUE_ENGINEERING = "VALUE_ENGINEERING"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"


class KitStatus(str, Enum):
    DRAFT = "DRAFT"
    FROZEN = "FROZEN"
    RELEASED = "RELEASED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class WaveStatus(str, Enum):
    PLANNED = "PLANNED"
    COMMITTED = "COMMITTED"
    IN_PRODUCTION = "IN_PRODUCTION"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class DeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SignoffStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class LedgerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    DISPOSED = "DISPOSED"


class AtticValuationMethod(str, Enum):
    PROGRAM_AVERAGE = "PROGRAM_AVERAGE"
    LIQUIDATION = "LIQUIDATION"


class ClaimType(str, Enum):
    DAMAGED = "DAMAGED"
    MISSING = "MISSING"


class DispositionType(str, Enum):
    RETURN_VENDOR = "RETURN_VENDOR"
    SCRAP = "SCRAP"
    DONATE = "DONATE"


class UtilizationPosture(str, Enum):
    NORMAL = "NORMAL"
    AT_RISK = "AT_RISK"


class UserRole(str, Enum):
    PROGRAM_MANAGER = "ProgramManager"
    FIXTURE_ENGINEER = "FixtureEngineer"
    CONFIG_COORDINATOR = "ConfigCoordinator"
    PRODUCTION_PLANNER = "ProductionPlanner"
    WAREHOUSE_LEAD = "WarehouseLead"
    INSTALL_CREW_LEAD = "InstallCrewLead"
    HOTLINE_AGENT = "HotlineAgent"
    STORE_MANAGER = "StoreManager"
    PLATFORM_ADMIN = "PlatformAdmin"


class BomLine(TypedDict, total=False):
    part_number: str
    quantity: int
    list_unit_cost_cents: int
    negotiated_unit_cost_cents: int


class ConfigLine(TypedDict):
    part_number: str
    quantity: int
    unit_cost_cents: int


class RolloutProgram(TypedDict):
    id: str
    program_name: str
    retailer_code: str
    budget_total_cents: int
    contingency_budget_cents: int
    recalled_part_numbers: List[str]
    attic_valuation_method: str
    remaining_budget_cents: int
    contingency_spent_cents: int
    fulfilled_kit_count: int
    closeout_recovery_cents: int
    final_reconciliation_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class FixturePrototype(TypedDict):
    id: str
    program_id: str
    fixture_code: str
    bom_lines: List[BomLine]
    target_cost_cents: int
    provisional_cost_cents: int
    engineered_cost_cents: int
    final_cost_cents: Optional[int]
    ve_round_count: int
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StoreKitConfig(TypedDict):
    id: str
    program_id: str
    prototype_id: str
    store_code: str
    config_lines: List[ConfigLine]
    total_components: int
    kit_total_cost_cents: int
    wave_release_charge_cents: Optional[int]
    wave_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionWave(TypedDict):
    id: str
    program_id: str
    wave_label: str
    start_date: str
    end_date: str
    capacity_units: int
    committed_units: int
    utilization_pct: float
    utilization_posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StagingReservation(TypedDict):
    id: str
    kit_id: str
    staging_bay_code: str
    start_ts: str
    end_ts: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InstallDelivery(TypedDict):
    id: str
    kit_id: str
    crew_code: str
    delivery_date: str
    estimated_install_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict):
    id: str
    delivery_id: str
    part_number: str
    claim_type: str
    replacement_component_count: int
    replacement_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InstallSignoff(TypedDict):
    id: str
    delivery_id: str
    photo_urls: List[str]
    notes: Optional[str]
    submission_count: int
    submitted_by_user_id: str
    reviewed_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AtticStockLedger(TypedDict):
    id: str
    kit_id: str
    store_code: str
    quantity_on_hand: int
    reorder_point: int
    reorder_required: bool
    unit_cost_cents: int
    disposition_type: Optional[str]
    recovery_value_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
