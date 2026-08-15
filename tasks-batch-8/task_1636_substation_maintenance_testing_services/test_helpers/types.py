"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    OPERATIONS_MANAGER = "OperationsManager"
    OUTAGE_COORDINATOR = "OutageCoordinator"
    SWITCHING_SUPERVISOR = "SwitchingSupervisor"
    TECHNICIAN = "Technician"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# ---------------------------------------------------------------------------
# Status / enum vocabularies (PRD §3)
# ---------------------------------------------------------------------------

class SubstationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class AssetClass(str, Enum):
    POWER_TRANSFORMER = "POWER_TRANSFORMER"
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"
    RELAY = "RELAY"


class AssetCriticality(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AssetStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    DECOMMISSIONED = "DECOMMISSIONED"


class OutageWindowStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    SWITCHING = "SWITCHING"
    CLEARED = "CLEARED"
    RESTORED = "RESTORED"


class SwitchingStepStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    VERIFIED = "VERIFIED"


class TestType(str, Enum):
    INSULATION_RESISTANCE = "INSULATION_RESISTANCE"
    OIL_MOISTURE = "OIL_MOISTURE"
    RELAY_TIMING = "RELAY_TIMING"


class TestEventStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class TestResult(str, Enum):
    PASS = "PASS"
    MARGINAL = "MARGINAL"
    FAIL = "FAIL"


class DefectSeverity(str, Enum):
    C1 = "C1"
    C2 = "C2"
    C3 = "C3"


class DefectStatus(str, Enum):
    OPEN = "OPEN"
    WORK_ORDERED = "WORK_ORDERED"
    RESOLVED = "RESOLVED"
    VERIFIED = "VERIFIED"
    DEFERRED = "DEFERRED"


class WorkOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"
    CANCELLED = "CANCELLED"


class SpareUnitType(str, Enum):
    SPARE_TRANSFORMER = "SPARE_TRANSFORMER"
    MOBILE_SUBSTATION = "MOBILE_SUBSTATION"


class SpareUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    DEPLOYED = "DEPLOYED"
    DECOMMISSIONED = "DECOMMISSIONED"


class SpareReservationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    FULFILLED = "FULFILLED"


class RelaySettingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    VERIFIED = "VERIFIED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class TechnicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CertType(str, Enum):
    NETA_LEVEL_2 = "NETA_LEVEL_2"
    NETA_LEVEL_3 = "NETA_LEVEL_3"
    NETA_LEVEL_4 = "NETA_LEVEL_4"
    SWITCHING_QUALIFIED = "SWITCHING_QUALIFIED"


class CertificationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class InspectionMethod(str, Enum):
    SPCC_SIMPLE = "SPCC_SIMPLE"
    SPCC_WITH_FREEBOARD = "SPCC_WITH_FREEBOARD"


class InspectionCompliance(str, Enum):
    COMPLIANT = "COMPLIANT"
    DEFICIENT = "DEFICIENT"


class InspectionStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4: every entity carries id / created_at /
# updated_at / version — there are no exceptions to the common-fields rule)
# ---------------------------------------------------------------------------

class Substation(TypedDict, total=False):
    id: str
    name: str
    code: str
    region: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AssetClassPolicy(TypedDict, total=False):
    id: str
    asset_class: str
    interval_months: int
    condition_escalation_threshold: float
    condition_critical_threshold: float
    oil_warn_ppm: float
    oil_critical_ppm: float
    ir_min_mohm: float
    relay_timing_warn_pct: float
    relay_timing_fail_pct: float
    w_insulation: float
    w_oil: float
    w_relay: float
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict, total=False):
    id: str
    substation_id: str
    asset_class: str
    criticality: str
    nameplate_mva: Optional[float]
    voltage_kv: float
    install_date: str
    upstream_asset_id: Optional[str]
    status: str
    condition_score: float
    approved_outage_hours: float
    last_maintenance_completed_at: Optional[str]
    next_due_date: str
    created_at: str
    updated_at: str
    version: int


class OutageWindow(TypedDict, total=False):
    id: str
    substation_id: str
    asset_id: str
    start_ts: str
    end_ts: str
    purpose: str
    status: str
    requested_by: str
    approved_by: Optional[str]
    duration_hours: float
    committed_hours: float
    needs_revalidation: bool
    created_at: str
    updated_at: str
    version: int


class SwitchingStep(TypedDict, total=False):
    id: str
    outage_window_id: str
    sequence_no: int
    description: str
    status: str
    executed_by: Optional[str]
    executed_at: Optional[str]
    verified_by: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TestEvent(TypedDict, total=False):
    id: str
    asset_id: str
    outage_window_id: Optional[str]
    test_type: str
    technician_id: str
    value_primary: float
    value_secondary: Optional[float]
    ambient_temp_c: Optional[float]
    requires_outage: bool
    measured_at: str
    status: str
    result: Optional[str]
    reviewed_by: Optional[str]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Defect(TypedDict, total=False):
    id: str
    asset_id: str
    test_event_id: Optional[str]
    title: str
    description: str
    severity: str
    status: str
    deferral_count: int
    deferred_until: Optional[str]
    due_date: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    defect_id: str
    asset_id: str
    outage_window_id: Optional[str]
    assigned_technician_id: str
    title: str
    estimated_hours: float
    status: str
    labor_lines: list
    parts_lines: list
    cost_subtotal: float
    mobilization_fee: float
    total_cost: float
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpareUnit(TypedDict, total=False):
    id: str
    unit_type: str
    rating_mva: float
    voltage_class_kv: float
    impedance_pct: float
    home_location: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SpareReservation(TypedDict, total=False):
    id: str
    spare_unit_id: str
    work_order_id: Optional[str]
    unit_type: str
    required_mva: float
    required_voltage_kv: float
    preferred_impedance_pct: Optional[float]
    site_location: Optional[str]
    start_ts: str
    end_ts: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RelaySetting(TypedDict, total=False):
    id: str
    asset_id: str
    setting_group: str
    pickup_a: float
    time_dial: float
    curve: str
    status: str
    author_technician_id: str
    verified_by_technician_id: Optional[str]
    supersedes_setting_id: Optional[str]
    rejection_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    full_name: str
    employee_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TechnicianCertification(TypedDict, total=False):
    id: str
    technician_id: str
    cert_type: str
    issued_at: str
    expires_at: str
    revoked_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EnvironmentalInspection(TypedDict, total=False):
    id: str
    substation_id: str
    inspection_date: str
    largest_vessel_gal: float
    containment_capacity_gal: float
    rainfall_freeboard_gal: float
    method: str
    required_capacity_gal: float
    compliance: Optional[str]
    status: str
    remediation_note: Optional[str]
    next_inspection_due: str
    created_at: str
    updated_at: str
    version: int
