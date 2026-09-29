"""Domain types for the Custom Crush & Bonded Winery Services API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.  Every one of the thirteen stored resource types carries the
full system-managed set (``id``, ``created_at``, ``updated_at``, ``version``),
as PRD 2.4 states outright.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    FACILITY_ADMIN = "FacilityAdmin"
    CELLAR_SUPERVISOR = "CellarSupervisor"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CLIENT_REP = "ClientRep"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_SIGNATURE = "PENDING_SIGNATURE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class VesselType(str, Enum):
    TANK = "TANK"
    BARREL = "BARREL"


class FacilityZone(str, Enum):
    ZONE_A = "ZONE_A"
    ZONE_B = "ZONE_B"
    BARREL_HALL = "BARREL_HALL"


class VesselCondition(str, Enum):
    CLEAN = "CLEAN"
    DIRTY = "DIRTY"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class AllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class IntakeStatus(str, Enum):
    WEIGHED = "WEIGHED"
    SAMPLED = "SAMPLED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    ASSIGNED = "ASSIGNED"


class Varietal(str, Enum):
    CABERNET_SAUVIGNON = "CABERNET_SAUVIGNON"
    MERLOT = "MERLOT"
    CHARDONNAY = "CHARDONNAY"
    PINOT_NOIR = "PINOT_NOIR"
    ZINFANDEL = "ZINFANDEL"


class Appellation(str, Enum):
    NAPA_VALLEY = "NAPA_VALLEY"
    RUTHERFORD = "RUTHERFORD"
    OAKVILLE = "OAKVILLE"
    STAGS_LEAP = "STAGS_LEAP"
    HOWELL_MOUNTAIN = "HOWELL_MOUNTAIN"


class LotOrigin(str, Enum):
    INTAKE = "INTAKE"
    BLEND = "BLEND"


class ProductionStatus(str, Enum):
    JUICE = "JUICE"
    FERMENTING = "FERMENTING"
    PRESSED = "PRESSED"
    AGING = "AGING"
    BOTTLED = "BOTTLED"
    CONSUMED = "CONSUMED"


class BondStatus(str, Enum):
    IN_BOND = "IN_BOND"
    TAX_DETERMINED = "TAX_DETERMINED"
    REMOVED_TAXPAID = "REMOVED_TAXPAID"
    TRANSFERRED_IN_BOND = "TRANSFERRED_IN_BOND"


class BlendTrialStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    UNWOUND = "UNWOUND"


class OperationType(str, Enum):
    PUNCHDOWN = "PUNCHDOWN"
    PUMPOVER = "PUMPOVER"
    RACKING = "RACKING"
    PRESS = "PRESS"
    ADDITION = "ADDITION"
    TOPPING = "TOPPING"
    FILTRATION = "FILTRATION"


class WorkOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    BILLED = "BILLED"
    DISPUTED = "DISPUTED"
    CANCELLED = "CANCELLED"


class BottlingLineStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"


class BottlingRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SUPPLIES_RESERVED = "SUPPLIES_RESERVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DryGoodsItemType(str, Enum):
    BOTTLE = "BOTTLE"
    CORK = "CORK"
    CAPSULE = "CAPSULE"
    LABEL = "LABEL"
    CASE_BOX = "CASE_BOX"


class TTBReportStatus(str, Enum):
    OPEN = "OPEN"
    PREPARED = "PREPARED"
    FILED = "FILED"
    AMENDED = "AMENDED"


class TTBVariant(str, Enum):
    BONDED = "BONDED"
    GROSS = "GROSS"


class ReleaseType(str, Enum):
    TAXPAID_REMOVAL = "TAXPAID_REMOVAL"
    TRANSFER_IN_BOND = "TRANSFER_IN_BOND"


class ReleaseOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class StorageVariant(str, Enum):
    OCCUPANCY = "OCCUPANCY"
    VESSEL_FOOTPRINT = "VESSEL_FOOTPRINT"


# ─── Entity shapes ────────────────────────────────────────────────────────


class Client(TypedDict):
    id: str
    name: str
    ttb_permit_number: str
    contact_email: str
    status: str
    bond_gallons_in_bond: float
    taxpaid_gallons_ytd: float
    last_filed_period_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    client_id: str
    harvest_year: int
    committed_tons: float
    tank_gallons_entitled: float
    barrel_slots_entitled: int
    crush_rate_cents_per_ton: int
    storage_rate_cents_per_gallon_month: int
    labor_rate_cents_per_hour: int
    effective_from: str
    effective_to: str
    status: str
    tons_received: float
    gallons_allocated: float
    barrel_slots_used: int
    billed_total_cents: int
    storage_billed_through: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Vessel(TypedDict):
    id: str
    vessel_code: str
    vessel_type: str
    capacity_gallons: float
    facility_zone: str
    condition: str
    last_released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VesselAllocation(TypedDict):
    id: str
    contract_id: str
    vessel_id: str
    lot_id: Optional[str]
    start_at: str
    end_at: str
    allocated_gallons: float
    status: str
    committed_at: Optional[str]
    released_at: Optional[str]
    occupied_days: int
    created_at: str
    updated_at: str
    version: int


class HarvestIntake(TypedDict):
    id: str
    contract_id: str
    lot_id: Optional[str]
    delivery_ticket: str
    varietal: str
    appellation: str
    block_code: str
    gross_weight_lbs: float
    tare_weight_lbs: float
    net_weight_lbs: float
    brix: Optional[float]
    ph: Optional[float]
    estimated_gallons: float
    crush_fee_cents: int
    received_at: str
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict):
    id: str
    contract_id: str
    current_vessel_id: Optional[str]
    parent_lot_id: Optional[str]
    lot_code: str
    vintage_year: int
    varietal: str
    appellation: str
    varietal_label: str
    appellation_label: str
    volume_gallons: float
    loss_gallons: float
    brix_at_crush: Optional[float]
    alcohol_pct: Optional[float]
    origin: str
    production_status: str
    bond_status: str
    aging_start_at: Optional[str]
    aging_days: int
    cases_bottled: int
    source_intake_ids: List[str]
    component_manifest: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class BlendTrial(TypedDict):
    id: str
    contract_id: str
    result_lot_id: Optional[str]
    trial_name: str
    target_lot_code: str
    declared_loss_pct: float
    components: List[Dict[str, Any]]
    round_number: int
    status: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    revision_note: Optional[str]
    total_component_gallons: float
    projected_loss_gallons: float
    projected_blend_gallons: float
    projected_alcohol_pct: Optional[float]
    projected_varietal_label: Optional[str]
    projected_appellation_label: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    lot_id: str
    operation_type: str
    scheduled_at: str
    labor_hours: float
    crew_size: int
    material_cost_cents: int
    rush: bool
    status: str
    actual_labor_hours: Optional[float]
    executed_by_user_id: Optional[str]
    billed_by_user_id: Optional[str]
    base_labor_cents: int
    rush_surcharge_cents: int
    subtotal_cents: int
    volume_discount_pct: float
    billable_amount_cents: int
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BottlingLine(TypedDict):
    id: str
    line_code: str
    cases_per_hour: int
    changeover_minutes: int
    daily_capacity_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class BottlingRun(TypedDict):
    id: str
    lot_id: str
    line_id: str
    scheduled_start: str
    scheduled_end: str
    run_hours: float
    bottle_size_ml: int
    cases_planned: int
    cases_actual: Optional[int]
    gallons_consumed: float
    supply_reservations: List[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class DryGoodsItem(TypedDict):
    id: str
    client_id: str
    sku: str
    item_type: str
    units_per_case: int
    on_hand_units: int
    reserved_units: int
    available_units: int
    created_at: str
    updated_at: str
    version: int


class TTBReport(TypedDict):
    id: str
    client_id: str
    period_start: str
    period_end: str
    variant: str
    status: str
    prepared_by_user_id: Optional[str]
    filed_by_user_id: Optional[str]
    opening_gallons: float
    produced_gallons: float
    removed_taxpaid_gallons: float
    removed_in_bond_gallons: float
    loss_gallons: float
    closing_gallons: float
    variance_gallons: float
    amendment_count: int
    filed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReleaseOrder(TypedDict):
    id: str
    lot_id: str
    release_type: str
    gallons: float
    cases: Optional[int]
    destination_permit_number: Optional[str]
    status: str
    requested_by_user_id: str
    approved_by_user_id: Optional[str]
    excise_tax_cents: int
    executed_at: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
