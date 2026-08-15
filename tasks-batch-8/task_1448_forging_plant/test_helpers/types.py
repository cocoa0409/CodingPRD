"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class MillHeatStatus(str, Enum):
    RECEIVED = "RECEIVED"
    CERT_VERIFIED = "CERT_VERIFIED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"
    DEPLETED = "DEPLETED"


class BilletStatus(str, Enum):
    CUT = "CUT"
    CHARGED = "CHARGED"
    DISCHARGED = "DISCHARGED"
    CONSUMED = "CONSUMED"
    SCRAPPED = "SCRAPPED"


class FurnaceStatus(str, Enum):
    UP = "UP"
    DOWN = "DOWN"


class FurnaceChargeStatus(str, Enum):
    LOADING = "LOADING"
    SOAKING = "SOAKING"
    READY = "READY"
    DISCHARGED = "DISCHARGED"
    ABORTED = "ABORTED"


class DieSetStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    INSTALLED = "INSTALLED"
    WORN = "WORN"
    RESINKING = "RESINKING"
    RETIRED = "RETIRED"


class WorkCenterStatus(str, Enum):
    UP = "UP"
    DOWN = "DOWN"


class WorkCenterType(str, Enum):
    PRESS = "PRESS"
    HAMMER = "HAMMER"


class WorkOrderStatus(str, Enum):
    RELEASED = "RELEASED"
    IN_PROGRESS = "IN_PROGRESS"
    PRODUCED = "PRODUCED"
    CERTIFIED = "CERTIFIED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ForgeRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    FORGED = "FORGED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TrimTicketStatus(str, Enum):
    DRAFT = "DRAFT"
    ACCEPTED = "ACCEPTED"
    FLAGGED = "FLAGGED"
    VOIDED = "VOIDED"


class PartSerialStatus(str, Enum):
    FORGED = "FORGED"
    TRIMMED = "TRIMMED"
    INSPECTED = "INSPECTED"
    SHIPPED = "SHIPPED"
    SCRAPPED = "SCRAPPED"


class QualityCertStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"


class MacroEtchResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class InvoiceStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    PAID = "PAID"
    VOID = "VOID"


class UserRole(str, Enum):
    PLANT_MANAGER = "PlantManager"
    SAW_OPERATOR = "SawOperator"
    FURNACE_OPERATOR = "FurnaceOperator"
    FORGE_OPERATOR = "ForgeOperator"
    DIE_SHOP_TECHNICIAN = "DieShopTechnician"
    QUALITY_ENGINEER = "QualityEngineer"
    SALES_PLANNER = "SalesPlanner"


class AlloySpec(TypedDict, total=False):
    id: str
    grade_code: str
    name: str
    forge_temp_min_f: int
    forge_temp_max_f: int
    reheat_limit: int
    flash_allowance_pct: float
    strokes_per_part: int
    flow_stress_ksi: float
    carbon_max_pct: float
    manganese_max_pct: float
    grain_flow_min_rating: int
    macro_etch_required: bool
    created_at: str
    updated_at: str
    version: int


class MillHeat(TypedDict, total=False):
    id: str
    heat_number: str
    alloy_spec_id: str
    mill_name: str
    received_weight_lbs: float
    bar_lbs_per_in: float
    carbon_pct: Optional[float]
    manganese_pct: Optional[float]
    remaining_weight_lbs: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Billet(TypedDict, total=False):
    id: str
    mill_heat_id: str
    cut_seq: int
    cut_length_in: float
    cut_weight_lbs: float
    charge_count: int
    current_charge_id: Optional[str]
    consumed_by_run_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Furnace(TypedDict, total=False):
    id: str
    furnace_code: str
    capacity_lbs: float
    status: str
    active_charge_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FurnaceCharge(TypedDict, total=False):
    id: str
    furnace_id: str
    billet_ids: List[str]
    alloy_spec_id: str
    target_temp_f: int
    soak_minutes: int
    planned_load_start: str
    planned_unload: str
    charge_weight_lbs: float
    load_started_at: Optional[str]
    closed_at: Optional[str]
    ready_at: Optional[str]
    discharged_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DieSet(TypedDict, total=False):
    id: str
    die_set_code: str
    part_family: str
    wear_limit_hits: int
    max_resinks: int
    cumulative_hits: int
    resink_count: int
    installed_work_center_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkCenter(TypedDict, total=False):
    id: str
    code: str
    type: str
    rated_tonnage: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    order_number: str
    customer_name: str
    alloy_spec_id: str
    part_number: str
    ordered_qty: int
    part_net_weight_lbs: float
    billet_weight_lbs: float
    projected_area_in2: float
    required_process: str
    price_tier1_limit_tons: float
    price_tier1_cents_per_ton: int
    price_tier2_limit_tons: float
    price_tier2_cents_per_ton: int
    price_tier3_cents_per_ton: int
    scrap_recovery_rate_cents_per_lb: int
    required_tonnage: int
    forged_qty: int
    trimmed_qty: int
    shipped_qty: int
    scrapped_qty: int
    planned_billet_weight_lbs: float
    consumed_billet_weight_lbs: float
    trimmed_net_lbs: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ForgeRun(TypedDict, total=False):
    id: str
    work_order_id: str
    die_set_id: str
    work_center_id: str
    planned_start: str
    planned_end: str
    planned_qty: int
    operator_id: Optional[str]
    actual_started_at: Optional[str]
    parts_good_total: int
    parts_scrapped_total: int
    input_weight_lbs: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ForgeHeat(TypedDict, total=False):
    # Append-only event (PRD §2.4): carries ONLY id + created_at plus event fields.
    # No updated_at, no version.
    id: str
    forge_run_id: str
    furnace_charge_id: str
    billet_ids: List[str]
    parts_good: int
    parts_scrapped: int
    hits_added: int
    created_at: str


class TrimTicket(TypedDict, total=False):
    id: str
    forge_run_id: str
    gross_as_forged_lbs: float
    net_trimmed_lbs: float
    pierce_loss_lbs: float
    flash_scrap_lbs: float
    flash_yield_pct: float
    deviation_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PartSerial(TypedDict, total=False):
    id: str
    serial_seq: int
    serial_code: str
    work_order_id: str
    forge_run_id: str
    forge_heat_id: str
    mill_heat_id: str
    net_weight_lbs: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityCert(TypedDict, total=False):
    id: str
    work_order_id: str
    mill_heat_id: str
    sample_part_serial_id: Optional[str]
    grain_flow_rating: Optional[int]
    macro_etch_result: Optional[str]
    submitter_id: Optional[str]
    certifier_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SurchargeIndex(TypedDict, total=False):
    id: str
    alloy_spec_id: str
    effective_month: str
    surcharge_cents_per_ton: int
    energy_pct: float
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    work_order_id: str
    surcharge_index_id: str
    estimated_net_weight_lbs: float
    actual_shipped_net_weight_lbs: Optional[float]
    billable_weight_lbs: float
    billable_tons: float
    tier_rate_cents_per_ton: int
    base_amount_cents: int
    alloy_surcharge_cents: int
    energy_surcharge_cents: int
    scrap_credit_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
