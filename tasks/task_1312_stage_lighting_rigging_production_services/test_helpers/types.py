"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PRODUCTION_MANAGER = "ProductionManager"
    RIGGING_SUPERVISOR = "RiggingSupervisor"
    STRUCTURAL_ENGINEER = "StructuralEngineer"
    WAREHOUSE_CHIEF = "WarehouseChief"
    SAFETY_INSPECTOR = "SafetyInspector"
    CREW_CHIEF = "CrewChief"
    CLIENT_CONTACT = "ClientContact"


class UnionRuleset(str, Enum):
    IATSE = "IATSE"
    TEAMSTERS = "TEAMSTERS"
    NON_UNION = "NON_UNION"


class ProductionStatus(str, Enum):
    DRAFT = "DRAFT"
    PLANNING = "PLANNING"
    READY_FOR_LOADIN = "READY_FOR_LOADIN"
    LOAD_IN = "LOAD_IN"
    SHOW_READY = "SHOW_READY"
    SHOW_COMPLETE = "SHOW_COMPLETE"
    LOAD_OUT = "LOAD_OUT"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class Posture(str, Enum):
    BLOCKED = "BLOCKED"
    PARTIAL = "PARTIAL"
    READY = "READY"


class PlotStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class RiggingPointStatus(str, Enum):
    RESERVED = "RESERVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RELEASED = "RELEASED"


class HangType(str, Enum):
    STRAIGHT = "STRAIGHT"
    BRIDLE = "BRIDLE"
    DEAD_HANG = "DEAD_HANG"


class AssetStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    PREPPED = "PREPPED"
    DEPLOYED = "DEPLOYED"
    DAMAGED = "DAMAGED"
    LOST = "LOST"
    RETIRED = "RETIRED"


class AssetClass(str, Enum):
    MOVING_LIGHT = "MOVING_LIGHT"
    LED_PANEL = "LED_PANEL"
    TRUSS_12IN = "TRUSS_12IN"
    CHAIN_MOTOR = "CHAIN_MOTOR"
    DISTRO_BOX = "DISTRO_BOX"
    CABLE_FEEDER = "CABLE_FEEDER"
    CONSOLE = "CONSOLE"
    FOLLOWSPOT = "FOLLOWSPOT"


class PullEntryStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RESERVED = "RESERVED"
    PREPPED = "PREPPED"
    OUT = "OUT"
    RETURNED = "RETURNED"
    DAMAGED = "DAMAGED"
    LOST = "LOST"
    CANCELLED = "CANCELLED"


class CrewCallStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CONFIRMED = "CONFIRMED"
    WORKED = "WORKED"
    NO_SHOW = "NO_SHOW"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class Department(str, Enum):
    LIGHTING = "LIGHTING"
    RIGGING = "RIGGING"
    STAGEHANDS = "STAGEHANDS"


class Classification(str, Enum):
    LIGHTING_TECH = "LIGHTING_TECH"
    RIGGER = "RIGGER"
    STAGEHAND = "STAGEHAND"


class PowerPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class LoadDirection(str, Enum):
    LOAD_IN = "LOAD_IN"
    LOAD_OUT = "LOAD_OUT"


class LoadScheduleStatus(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    AUTHORIZED = "AUTHORIZED"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class InspectionType(str, Enum):
    RIGGING = "RIGGING"
    ELECTRICAL = "ELECTRICAL"
    FINAL = "FINAL"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ReportType(str, Enum):
    DAMAGE = "DAMAGE"
    LOSS = "LOSS"


class ValuationMethod(str, Enum):
    DEPRECIATED = "DEPRECIATED"
    REPAIR_QUOTE = "REPAIR_QUOTE"


class DamageReportStatus(str, Enum):
    FILED = "FILED"
    ASSESSED = "ASSESSED"
    CHARGED = "CHARGED"
    WAIVED = "WAIVED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"
    PAID = "PAID"


# --- Entity TypedDicts (all entities carry the full common field set) ---

class Venue(TypedDict):
    id: str
    name: str
    union_ruleset: str
    max_point_capacity_kg: float
    bay_aggregate_limit_kg: float
    house_power_amps_per_phase: int
    dock_doors: int
    min_call_hours: float
    ot1_threshold_hours: float
    ot2_threshold_hours: float
    turnaround_min_hours: float
    crew_call_publish_lead_hours: int
    engineering_submission_lead_hours: int
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    full_name: str
    union_card_no: str
    classification: str
    hourly_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class Production(TypedDict):
    id: str
    venue_id: str
    name: str
    load_in_at: str
    show_at: str
    load_out_at: str
    status: str
    posture: str
    created_at: str
    updated_at: str
    version: int


class LightingPlot(TypedDict):
    id: str
    production_id: str
    title: str
    revision: int
    status: str
    total_factored_load_kg: float
    rejection_reason: Optional[str]
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RiggingPoint(TypedDict):
    id: str
    plot_id: str
    point_label: str
    bay_index: int
    hang_type: str
    motor_count: int
    deadweight_kg: float
    factored_load_kg: float
    utilization: float
    status: str
    submitted_by_user_id: str
    reviewed_by_user_id: Optional[str]
    plot_version_at_submission: Optional[int]
    created_at: str
    updated_at: str
    version: int


class EquipmentAsset(TypedDict):
    id: str
    asset_tag: str
    asset_class: str
    weight_kg: float
    power_draw_watts: int
    daily_rate_cents: int
    replacement_cost_cents: int
    acquired_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PullListEntry(TypedDict):
    id: str
    production_id: str
    asset_id: str
    status: str
    prep_window_start: Optional[str]
    prep_window_end: Optional[str]
    load_schedule_id: Optional[str]
    out_at: Optional[str]
    returned_at: Optional[str]
    rental_charge_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CrewCall(TypedDict):
    id: str
    production_id: str
    department: str
    call_start: str
    call_end: str
    required_headcount: int
    status: str
    labor_cost_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict):
    id: str
    crew_call_id: str
    technician_id: str
    status: str
    worked_hours: Optional[float]
    labor_charge_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PowerPlan(TypedDict):
    id: str
    production_id: str
    phase_l1_watts: int
    phase_l2_watts: int
    phase_l3_watts: int
    feeder_length_m: int
    generator_required: bool
    total_load_watts: Optional[float]
    required_kva: Optional[float]
    selected_generator_tier_kva: Optional[int]
    max_phase_imbalance_pct: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Truck(TypedDict):
    id: str
    plate_no: str
    capacity_kg: float
    created_at: str
    updated_at: str
    version: int


class LoadSchedule(TypedDict):
    id: str
    production_id: str
    truck_id: str
    direction: str
    dock_door_index: int
    window_start: str
    window_end: str
    pack_weight_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SafetyInspection(TypedDict):
    id: str
    production_id: str
    inspection_type: str
    status: str
    attempt_no: int
    inspector_user_id: Optional[str]
    findings: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DamageReport(TypedDict):
    id: str
    production_id: str
    pull_list_entry_id: str
    report_type: str
    valuation_method: Optional[str]
    repair_quote_cents: Optional[int]
    assessed_charge_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class SettlementStatement(TypedDict):
    id: str
    production_id: str
    labor_total_cents: int
    equipment_total_cents: int
    damage_total_cents: int
    provisional_damage_cents: int
    grand_total_cents: int
    provisional_grand_total_cents: int
    dispute_adjustment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
