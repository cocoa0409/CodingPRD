"""Domain types for the Small Engine & Outdoor Power Equipment Plant API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    PLANT_ADMIN = "PlantAdmin"
    CERTIFICATION_ENGINEER = "CertificationEngineer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    QUALITY_ENGINEER = "QualityEngineer"
    PRODUCTION_PLANNER = "ProductionPlanner"
    CHANNEL_PARTNER = "ChannelPartner"


# ---------------------------------------------------------------------------
# Certification families and engine platforms (PRD §3.1, §3.2, §2.7)
# ---------------------------------------------------------------------------


class CertificationFamilyStatus(str, Enum):
    DRAFT = "DRAFT"
    DURABILITY_TESTING = "DURABILITY_TESTING"
    DURABILITY_COMPLETE = "DURABILITY_COMPLETE"
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    AUDIT_HOLD = "AUDIT_HOLD"
    SUSPENDED = "SUSPENDED"


class EmissionStandard(str, Enum):
    EPA_PHASE3 = "EPA_PHASE3"
    CARB_2024 = "CARB_2024"


class CertificationPosture(str, Enum):
    PENDING = "PENDING"
    RESTRICTED = "RESTRICTED"
    OPEN = "OPEN"
    FROZEN = "FROZEN"


class DurabilityTestRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class DeteriorationMethod(str, Enum):
    MULTIPLICATIVE = "MULTIPLICATIVE"
    ADDITIVE = "ADDITIVE"


# ---------------------------------------------------------------------------
# Finished-goods models and safety certifications (PRD §3.3)
# ---------------------------------------------------------------------------


class ProductModelStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    SUSPENDED = "SUSPENDED"


class ProductLine(str, Enum):
    WALK_MOWER = "WALK_MOWER"
    RIDING_MOWER = "RIDING_MOWER"
    SNOW_THROWER = "SNOW_THROWER"
    GENERATOR = "GENERATOR"


class Channel(str, Enum):
    DEALER = "DEALER"
    MASS_RETAIL = "MASS_RETAIL"
    DUAL = "DUAL"


class BladeBrakeType(str, Enum):
    BLADE_BRAKE_CLUTCH = "BLADE_BRAKE_CLUTCH"
    ENGINE_KILL = "ENGINE_KILL"
    NONE = "NONE"


class OperatorPresenceType(str, Enum):
    BAIL = "BAIL"
    SEAT_SWITCH = "SEAT_SWITCH"
    TWO_HAND = "TWO_HAND"
    CO_SHUTOFF = "CO_SHUTOFF"


class SafetyStandardCode(str, Enum):
    ANSI_B71_1 = "ANSI_B71_1"
    ANSI_B71_3 = "ANSI_B71_3"
    UL_2201 = "UL_2201"


class SafetyCertificationResult(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Suppliers, lots and machining (PRD §3.4, §3.5)
# ---------------------------------------------------------------------------


class SupplierApprovalStatus(str, Enum):
    APPROVED = "APPROVED"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class IncomingInspectionLevel(str, Enum):
    SKIP_LOT = "SKIP_LOT"
    REDUCED = "REDUCED"
    NORMAL = "NORMAL"
    TIGHTENED = "TIGHTENED"


class Criticality(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"


class ComponentCategory(str, Enum):
    CARBURETOR = "CARBURETOR"
    IGNITION = "IGNITION"
    CASTING = "CASTING"


class ComponentLotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    DEVIATION_ACCEPTED = "DEVIATION_ACCEPTED"
    QUARANTINED = "QUARANTINED"


class MachiningRunStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CAPABILITY_HOLD = "CAPABILITY_HOLD"


class ComponentType(str, Enum):
    CRANKSHAFT = "CRANKSHAFT"
    CYLINDER_BORE = "CYLINDER_BORE"
    CAMSHAFT = "CAMSHAFT"


# ---------------------------------------------------------------------------
# Assembly lines, build orders, engine units, audits (PRD §3.6, §3.7, §3.8)
# ---------------------------------------------------------------------------


class AssemblyLineStatus(str, Enum):
    RUNNING = "RUNNING"
    DOWN = "DOWN"


class BuildOrderStatus(str, Enum):
    PLANNED = "PLANNED"
    RELEASED = "RELEASED"
    IN_PRODUCTION = "IN_PRODUCTION"
    HELD = "HELD"
    COMPLETED = "COMPLETED"


class AllocationStatus(str, Enum):
    UNALLOCATED = "UNALLOCATED"
    ALLOCATED = "ALLOCATED"


class HeldReason(str, Enum):
    FAMILY_AUDIT_HOLD = "FAMILY_AUDIT_HOLD"
    FAMILY_SUSPENDED = "FAMILY_SUSPENDED"


class Season(str, Enum):
    PRE_SEASON = "PRE_SEASON"
    IN_SEASON = "IN_SEASON"


class EngineUnitBuildState(str, Enum):
    STAGED = "STAGED"
    ASSEMBLED = "ASSEMBLED"
    HOT_TESTED = "HOT_TESTED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class EngineUnitConformanceState(str, Enum):
    PENDING = "PENDING"
    CONFORMING = "CONFORMING"
    NONCONFORMING = "NONCONFORMING"
    QUARANTINED = "QUARANTINED"


class ProductionLineAuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class AuditFailureReason(str, Enum):
    EMISSION_LIMIT_EXCEEDED = "EMISSION_LIMIT_EXCEEDED"
    FAILURE_RATE_EXCEEDED = "FAILURE_RATE_EXCEEDED"


# ---------------------------------------------------------------------------
# Service parts (PRD §3.9)
# ---------------------------------------------------------------------------


class ServicePartStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    OBSOLETE = "OBSOLETE"


class ServicePartCategory(str, Enum):
    CARBURETOR_KIT = "CARBURETOR_KIT"
    IGNITION_MODULE = "IGNITION_MODULE"
    BLADE_ASSEMBLY = "BLADE_ASSEMBLY"
    FILTER_KIT = "FILTER_KIT"


class PartsFulfillmentRequestStatus(str, Enum):
    BACKORDERED = "BACKORDERED"
    FILLED = "FILLED"
    SUBSTITUTED = "SUBSTITUTED"


# ---------------------------------------------------------------------------
# Entity shapes
#
# Every entity below carries id / created_at / updated_at / version, except
# SafetyCertification, which the PRD declares an immutable bench-test record
# carrying only id and created_at.
# ---------------------------------------------------------------------------


class CertificationFamily(TypedDict):
    id: str
    family_code: str
    model_year: int
    emission_standard: str
    displacement_min_cc: int
    displacement_max_cc: int
    durability_hours: int
    family_emission_limit_g_per_kwh: float
    declared_baseline_emission_g_per_kwh: float
    status: str
    deterioration_factor: Optional[float]
    certified_emission_g_per_kwh: Optional[float]
    compliance_margin_pct: Optional[float]
    cumulative_audit_failures: int
    submitted_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    audit_hold_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnginePlatform(TypedDict):
    id: str
    certification_family_id: str
    platform_code: str
    displacement_cc: int
    torque_spec_nm: float
    torque_tolerance_pct: float
    required_fastener_count: int
    hot_test_min_rpm: int
    hot_test_max_rpm: int
    certification_posture: str
    created_at: str
    updated_at: str
    version: int


class DurabilityTestRun(TypedDict):
    id: str
    certification_family_id: str
    engine_platform_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    target_hours: int
    initial_emission_g_per_kwh: float
    status: str
    df_method: str
    accumulated_hours: Optional[int]
    final_emission_g_per_kwh: Optional[float]
    computed_deterioration_factor: Optional[float]
    extrapolated: bool
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductModel(TypedDict):
    id: str
    engine_platform_id: str
    model_code: str
    product_line: str
    channel: str
    blade_brake_type: str
    operator_presence_type: str
    warranty_months: int
    standard_cost_cents: int
    msrp_cents: int
    dealer_share_pct: float
    dealer_cap_units: int
    mass_retail_cap_units: int
    status: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SafetyCertification(TypedDict):
    """Immutable bench-test record: carries only id and created_at."""

    id: str
    product_model_id: str
    standard_code: str
    blade_stop_time_ms: Optional[int]
    opc_stop_time_ms: int
    tested_on: str
    expires_on: str
    result: str
    tested_by_user_id: str
    created_at: str


class Supplier(TypedDict):
    id: str
    supplier_code: str
    name: str
    component_category: str
    criticality: str
    approval_status: str
    incoming_inspection_level: str
    rolling_defect_ppm: int
    inspected_lot_count: int
    consecutive_accepted_lots: int
    created_at: str
    updated_at: str
    version: int


class ComponentLot(TypedDict):
    id: str
    supplier_id: str
    lot_code: str
    lot_quantity: int
    component_category: str
    status: str
    inspection_level_at_receipt: str
    sample_size: int
    acceptance_number: int
    defects_found: Optional[int]
    defect_ppm: Optional[int]
    accepted_qty: int
    consumed_qty: int
    remaining_qty: int
    deviation_flag: bool
    inspected_by_user_id: Optional[str]
    deviation_approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MachiningRun(TypedDict):
    id: str
    engine_platform_id: str
    casting_lot_id: str
    component_type: str
    criticality: str
    lsl_mm: float
    usl_mm: float
    status: str
    measurements: Optional[List[float]]
    sample_count: int
    mean_mm: Optional[float]
    sigma_mm: Optional[float]
    cpk: Optional[float]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssemblyLine(TypedDict):
    id: str
    line_code: str
    supported_product_lines: List[str]
    weekly_capacity_units: int
    changeover_gap_weeks: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BuildOrder(TypedDict):
    id: str
    product_model_id: str
    assembly_line_id: str
    season: str
    production_week: str
    week_span: int
    planned_quantity: int
    status: str
    build_value_cents: int
    carry_rate: float
    carry_weeks: int
    carry_cost_cents: int
    total_committed_cents: int
    staged_quantity: int
    built_quantity: int
    allocation_status: str
    allocated_dealer_units: int
    allocated_mass_retail_units: int
    unallocated_units: int
    allocation_run_at: Optional[str]
    held_reason: Optional[str]
    status_before_hold: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EngineUnit(TypedDict):
    id: str
    build_order_id: str
    machining_run_id: str
    carburetor_lot_id: str
    ignition_lot_id: str
    serial_number: str
    build_state: str
    conformance_state: str
    deviation_sourced: bool
    rework_count: int
    torque_readings: Optional[List[dict]]
    torque_lower_bound_nm: Optional[float]
    torque_upper_bound_nm: Optional[float]
    out_of_spec_fastener_count: Optional[int]
    measured_rpm: Optional[int]
    measured_emission_g_per_kwh: Optional[float]
    hot_test_emission_threshold: Optional[float]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductionLineAudit(TypedDict):
    id: str
    build_order_id: str
    certification_family_id: str
    audit_week: str
    required_sample_size: int
    status: str
    units_tested: Optional[int]
    units_failed: Optional[int]
    max_measured_emission_g_per_kwh: Optional[float]
    failure_rate: Optional[float]
    failure_reason: Optional[str]
    recorded_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServicePart(TypedDict):
    id: str
    engine_platform_id: str
    part_number: str
    category: str
    on_hand_qty: int
    committed_availability_years: int
    last_production_year: int
    commitment_expires_year: int
    dealer_lead_time_days: int
    mass_retail_lead_time_days: int
    status: str
    superseded_by_part_id: Optional[str]
    filled_request_count: int
    substituted_request_count: int
    backordered_request_count: int
    fill_rate_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class PartsFulfillmentRequest(TypedDict):
    id: str
    service_part_id: str
    requested_quantity: int
    channel: str
    status: str
    shipped_from_part_id: Optional[str]
    promised_ship_date: Optional[str]
    requester_user_id: str
    created_at: str
    updated_at: str
    version: int
