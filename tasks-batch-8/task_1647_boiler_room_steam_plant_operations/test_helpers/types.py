"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLANT_MANAGER = "PlantManager"
    OPERATOR = "Operator"
    INSPECTOR = "Inspector"


class PlantPosture(str, Enum):
    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    EMERGENCY = "EMERGENCY"


class StateCode(str, Enum):
    MA = "MA"
    NY = "NY"
    CA = "CA"
    TX = "TX"


class BoilerOpsStatus(str, Enum):
    STANDBY = "STANDBY"
    WARMING = "WARMING"
    ONLINE = "ONLINE"
    BANKING = "BANKING"
    TRIPPED = "TRIPPED"
    DECOMMISSIONED = "DECOMMISSIONED"


class BoilerCertStatus(str, Enum):
    VALID = "VALID"
    EXPIRING = "EXPIRING"
    LAPSED = "LAPSED"
    SUSPENDED = "SUSPENDED"


class BoilerWaterStatus(str, Enum):
    IN_SPEC = "IN_SPEC"
    OUT_OF_SPEC = "OUT_OF_SPEC"
    CRITICAL = "CRITICAL"


class LicenseClass(str, Enum):
    CLASS_1 = "CLASS_1"
    CLASS_2 = "CLASS_2"
    CLASS_3 = "CLASS_3"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRING = "EXPIRING"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class LogEntryStatus(str, Enum):
    DRAFT = "DRAFT"
    VERIFIED = "VERIFIED"
    VOIDED = "VOIDED"


class ChemistryLogStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class InspectionKind(str, Enum):
    ANNUAL_INTERNAL = "ANNUAL_INTERNAL"
    ANNUAL_EXTERNAL = "ANNUAL_EXTERNAL"
    RELIEF_VALVE_POP = "RELIEF_VALVE_POP"
    POST_INCIDENT = "POST_INCIDENT"


class InspectionOutcome(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CONDITIONAL = "CONDITIONAL"


class SteamTrapCondition(str, Enum):
    UNKNOWN = "UNKNOWN"
    OK = "OK"
    LEAKING = "LEAKING"
    FAILED_OPEN = "FAILED_OPEN"
    FAILED_CLOSED = "FAILED_CLOSED"
    COLD = "COLD"


class SteamTrapStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    ISOLATED = "ISOLATED"
    REPLACED = "REPLACED"


class DispatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentKind(str, Enum):
    OVERPRESSURE = "OVERPRESSURE"
    LOW_WATER = "LOW_WATER"
    FLAME_FAILURE = "FLAME_FAILURE"
    RELIEF_VALVE_LIFT = "RELIEF_VALVE_LIFT"
    CHEMISTRY_EXCURSION = "CHEMISTRY_EXCURSION"
    OTHER = "OTHER"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    MITIGATED = "MITIGATED"
    CLOSED = "CLOSED"


# --- Mutable resources: full common property set (id, created_at, updated_at, version) ---


class Plant(TypedDict):
    id: str
    name: str
    state_code: str
    header_pressure_psi: float
    header_pressure_actual_psi: float
    fuel_inventory_gal: float
    total_fuel_received_gal: float
    total_fuel_consumed_gal: float
    posture: str
    lead_boiler_id: Optional[str]
    ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class Boiler(TypedDict):
    id: str
    plant_id: str
    tag: str
    rated_capacity_lb_hr: int
    relief_valve_setpoint_psi: float
    relief_valve_tolerance_pct: float
    ops_status: str
    cert_status: str
    water_status: str
    cycles_of_concentration: float
    total_steam_lb: float
    total_fuel_burned_gal: float
    total_blowdown_gal: float
    total_feedwater_gal: float
    efficiency_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Operator(TypedDict):
    id: str
    plant_id: str
    full_name: str
    license_class: str
    license_state: str
    license_expires_on: str
    license_status: str
    is_lead_qualified: bool
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    boiler_id: str
    inspection_kind: str
    scheduled_on: str
    inspector_name: str
    inspector_license_no: str
    relief_valve_lift_pressure_psi: Optional[float]
    outcome: str
    certificate_number: Optional[str]
    certificate_expires_on: Optional[str]
    posted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SteamTrap(TypedDict):
    id: str
    plant_id: str
    tag: str
    location: str
    orifice_diameter_in: float
    design_pressure_psi: float
    last_surveyed_at: Optional[str]
    condition: str
    leak_rate_lb_hr: float
    status: str
    created_at: str
    updated_at: str
    version: int


class LoadDispatch(TypedDict):
    id: str
    plant_id: str
    window_start_at: str
    window_end_at: str
    target_steam_lb_hr: int
    assigned_boiler_ids: List[str]
    expected_lead_boiler_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict):
    id: str
    plant_id: str
    raised_by_operator_id: str
    severity: str
    kind: str
    triggered_boiler_id: Optional[str]
    raised_at: str
    status: str
    resolution_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Append-only journal records: id + created_at ONLY (no updated_at, no version) ---


class BoilerLogEntry(TypedDict):
    id: str
    boiler_id: str
    recorded_by_operator_id: str
    recorded_at: str
    header_pressure_reading_psi: float
    steam_generated_lb: float
    fuel_burned_gal: float
    feedwater_intake_gal: float
    blowdown_gal: float
    status: str
    created_at: str


class ChemistryLog(TypedDict):
    id: str
    boiler_id: str
    recorded_by_operator_id: str
    recorded_at: str
    conductivity_boiler_umho: float
    conductivity_feedwater_umho: float
    sulfite_residual_ppm: float
    phosphate_residual_ppm: float
    status: str
    created_at: str


class FuelDelivery(TypedDict):
    id: str
    plant_id: str
    delivered_at: str
    quantity_gal: float
    supplier: str
    created_at: str


class LossProjection(TypedDict):
    leak_rate_lb_hr: float
    annual_steam_loss_lb: float
    annual_cost_usd: float
    method: str
