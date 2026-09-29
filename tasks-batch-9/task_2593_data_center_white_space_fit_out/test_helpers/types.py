"""Domain types for the Data Center White Space Fit-Out API.

Status enums, role enum and entity TypedDicts, all named exactly as the PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Role enum (PRD §2.1 — the nine roles)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    FACILITY_PLANNER = "FacilityPlanner"
    ELECTRICAL_CONTRACTOR = "ElectricalContractor"
    MECHANICAL_CONTRACTOR = "MechanicalContractor"
    COMMISSIONING_AGENT = "CommissioningAgent"
    WITNESS_AUTHORITY = "WitnessAuthority"
    CHANGE_MANAGER = "ChangeManager"
    OPERATIONS_MANAGER = "OperationsManager"
    SECURITY_ADMINISTRATOR = "SecurityAdministrator"
    TENANT_REPRESENTATIVE = "TenantRepresentative"


# --------------------------------------------------------------------------
# Status / enum domains
# --------------------------------------------------------------------------
class HallStatus(str, Enum):
    PLANNING = "PLANNING"
    FIT_OUT = "FIT_OUT"
    COMMISSIONING = "COMMISSIONING"
    LIVE = "LIVE"


class TenantMode(str, Enum):
    SINGLE_TENANT = "SINGLE_TENANT"
    MULTI_TENANT = "MULTI_TENANT"


class CoolingRedundancy(str, Enum):
    N = "N"
    N_PLUS_1 = "N_PLUS_1"


class ThermalPosture(str, Enum):
    NOMINAL = "NOMINAL"
    CONSTRAINED = "CONSTRAINED"
    CRITICAL = "CRITICAL"


class ReleasePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    LOCKED = "LOCKED"


class FeedSide(str, Enum):
    A = "A"
    B = "B"


class PduStatus(str, Enum):
    PLANNED = "PLANNED"
    COMMISSIONED = "COMMISSIONED"


class BuswayStatus(str, Enum):
    INSTALLED = "INSTALLED"
    ENERGIZED = "ENERGIZED"
    ISOLATED = "ISOLATED"


class RedundancyTopology(str, Enum):
    N = "N"
    N_PLUS_1 = "N_PLUS_1"
    TWO_N = "TWO_N"


class UsableVariant(str, Enum):
    DESIGN = "DESIGN"
    COMMISSIONED = "COMMISSIONED"


class ZoneType(str, Enum):
    HOT_AISLE = "HOT_AISLE"
    COLD_AISLE = "COLD_AISLE"


class ContainmentKind(str, Enum):
    RIGID_ROOF = "RIGID_ROOF"
    CURTAIN = "CURTAIN"
    CHIMNEY = "CHIMNEY"


class LeakageStatus(str, Enum):
    UNTESTED = "UNTESTED"
    PASS = "PASS"
    FAIL = "FAIL"
    REMEDIATION = "REMEDIATION"


class CoolingUnitStatus(str, Enum):
    INSTALLED = "INSTALLED"
    COMMISSIONED = "COMMISSIONED"
    IN_SERVICE = "IN_SERVICE"
    MAINTENANCE = "MAINTENANCE"


class RedundancyRole(str, Enum):
    PRIMARY = "PRIMARY"
    REDUNDANT = "REDUNDANT"


class CageOperationalStatus(str, Enum):
    FIT_OUT = "FIT_OUT"
    SECURED = "SECURED"
    DEGRADED = "DEGRADED"
    RELEASED = "RELEASED"


class DeviceType(str, Enum):
    CAMERA = "CAMERA"
    CARD_READER = "CARD_READER"


class SecurityDeviceStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"


class RackStatus(str, Enum):
    PLANNED = "PLANNED"
    INSTALLED = "INSTALLED"
    POWERED = "POWERED"
    AT_RISK = "AT_RISK"
    RELEASED = "RELEASED"


class RackFeedStatus(str, Enum):
    RESERVED = "RESERVED"
    ENERGIZED = "ENERGIZED"
    DERATED = "DERATED"
    RELEASED = "RELEASED"


class CommissioningLevel(str, Enum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    L5 = "L5"


class ScriptStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    SCRIPT_APPROVED = "SCRIPT_APPROVED"
    EXECUTED = "EXECUTED"


class WitnessStatus(str, Enum):
    PENDING = "PENDING"
    WITNESSED = "WITNESSED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"


class PackageState(str, Enum):
    DRAFT = "DRAFT"
    IN_EXECUTION = "IN_EXECUTION"
    CERTIFIED = "CERTIFIED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    SUPERSEDED = "SUPERSEDED"


class WitnessDecision(str, Enum):
    WITNESSED = "WITNESSED"
    REJECTED = "REJECTED"


class LoadBankTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class LoadBankResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class MopStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    IN_EXECUTION = "IN_EXECUTION"
    CLOSED = "CLOSED"
    BACKED_OUT = "BACKED_OUT"
    REJECTED = "REJECTED"


class RiskClass(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class TargetResourceType(str, Enum):
    BUSWAY = "BUSWAY"
    COOLING_UNIT = "COOLING_UNIT"
    CONTAINMENT_ZONE = "CONTAINMENT_ZONE"
    RACK = "RACK"


class ApprovalDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_REVISION = "REQUEST_REVISION"
    REJECT = "REJECT"


class ReleasePacketStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    SUPERSEDED = "SUPERSEDED"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------
class Hall(TypedDict):
    id: str
    name: str
    code: str
    tenant_mode: str
    design_kw_capacity: float
    gross_area_sqm: float
    cooling_redundancy: str
    planned_rack_count: int
    status: str
    committed_kw: float
    commissioning_reserve_kw: float
    spare_kw: float
    chargeable_kw: float
    thermal_load_kw: float
    cooling_capacity_nameplate_kw: float
    cooling_capacity_airflow_kw: float
    cooling_capacity_kw: float
    cooling_margin_kw: float
    thermal_posture: str
    release_posture: str
    rack_total_count: int
    custody_ops_count: int
    custody_fitout_count: int
    at_risk_rack_count: int
    open_mop_count: int
    created_at: str
    updated_at: str
    version: int


class Tenant(TypedDict):
    id: str
    name: str
    code: str
    contracted_kw: float
    contract_start_date: str
    allocated_kw: float
    created_at: str
    updated_at: str
    version: int


class PowerDistributionUnit(TypedDict):
    id: str
    hall_id: str
    name: str
    feed_side: str
    rated_kw: float
    measured_derate_factor: float
    usable_cap_kw: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Busway(TypedDict):
    id: str
    pdu_id: str
    hall_id: str
    name: str
    feed_side: str
    rated_amps: int
    voltage_v: int
    redundancy_topology: str
    status: str
    raw_kw: float
    usable_kw: float
    usable_variant: str
    committed_kw: float
    feed_count: int
    created_at: str
    updated_at: str
    version: int


class ContainmentZone(TypedDict):
    id: str
    hall_id: str
    label: str
    zone_type: str
    containment_kind: str
    target_leakage_pct: float
    design_static_pressure_pa: float
    leakage_status: str
    measured_leakage_pct: Optional[float]
    measured_static_pressure_pa: Optional[float]
    test_count: int
    remediation_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoolingUnit(TypedDict):
    id: str
    hall_id: str
    name: str
    rated_sensible_kw: float
    design_airflow_cfm: int
    supply_delta_t_f: float
    redundancy_role: str
    status: str
    measured_airflow_cfm: Optional[int]
    airflow_capacity_kw: float
    created_at: str
    updated_at: str
    version: int


class Cage(TypedDict):
    id: str
    hall_id: str
    tenant_id: str
    label: str
    perimeter_length_m: float
    required_camera_coverage_pct: float
    required_reader_zone_count: int
    operational_status: str
    camera_coverage_pct: float
    active_reader_zone_count: int
    created_at: str
    updated_at: str
    version: int


class SecurityDevice(TypedDict):
    id: str
    cage_id: str
    device_type: str
    label: str
    covered_length_m: Optional[float]
    reader_zone_label: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Rack(TypedDict):
    id: str
    hall_id: str
    containment_zone_id: str
    cage_id: Optional[str]
    tenant_id: Optional[str]
    grid_row: str
    grid_col: int
    design_kw: float
    u_height: int
    required_feed_count: int
    asset_tag: Optional[str]
    status: str
    pre_risk_status: Optional[str]
    connected_kw: float
    energized_feed_count: int
    chargeable_kw: float
    created_at: str
    updated_at: str
    version: int


class RackFeed(TypedDict):
    id: str
    rack_id: str
    busway_id: str
    feed_side: str
    requested_kw: float
    allocated_kw: float
    breaker_amps: int
    status: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommissioningPackage(TypedDict):
    id: str
    hall_id: str
    level: str
    title: str
    target_load_kw: float
    script_status: str
    witness_status: str
    package_state: str
    script_revision: int
    executed_by_user_id: Optional[str]
    witnessed_by_user_id: Optional[str]
    superseded_by_package_id: Optional[str]
    measured_load_kw: Optional[float]
    created_at: str
    updated_at: str
    version: int


class LoadBankTest(TypedDict):
    id: str
    package_id: str
    target_kw: float
    window_start: str
    window_end: str
    step_pct_sequence: List[int]
    status: str
    measured_kw: Optional[float]
    measured_return_delta_t_f: Optional[float]
    result: Optional[str]
    abort_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MethodOfProcedure(TypedDict):
    id: str
    hall_id: str
    target_resource_type: str
    target_resource_id: str
    title: str
    risk_class: str
    backout_plan: str
    window_start: str
    window_end: str
    status: str
    author_user_id: str
    revision_count: int
    approval_count: int
    required_approval_count: int
    tenant_notified_ids: List[str]
    pre_execution_target_state: Optional[str]
    executed_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# The method-of-procedure approval record is immutable evidence: it carries only
# id and created_at, with no updated_at and no version at all (PRD §2.4).
class MopApproval(TypedDict):
    id: str
    mop_id: str
    approver_role: str
    approver_user_id: str
    decision: str
    comment: Optional[str]
    sequence: int
    created_at: str


class ReleasePacket(TypedDict):
    id: str
    hall_id: str
    cage_id: str
    as_built_drawing_ref: str
    supersedes_packet_id: Optional[str]
    status: str
    rack_in_scope_count: int
    released_kw: float
    asset_tag_completion_pct: float
    accepted_by_user_id: Optional[str]
    rejected_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
