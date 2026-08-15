"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class SnowEventStatus(str, Enum):
    FORECAST = "FORECAST"
    ACTIVATED = "ACTIVATED"
    ESCALATED = "ESCALATED"
    STANDING_DOWN = "STANDING_DOWN"
    CLOSED = "CLOSED"


class ClosureStatus(str, Enum):
    NONE = "NONE"
    PROPOSED = "PROPOSED"
    RATIFIED = "RATIFIED"
    LIFTED = "LIFTED"


class SurfaceStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class SurfaceType(str, Enum):
    RUNWAY = "RUNWAY"
    TAXIWAY = "TAXIWAY"
    APRON = "APRON"


class ContaminantType(str, Enum):
    DRY = "DRY"
    WET = "WET"
    DRY_SNOW = "DRY_SNOW"
    WET_SNOW = "WET_SNOW"
    COMPACTED_SNOW = "COMPACTED_SNOW"
    ICE = "ICE"
    SLUSH = "SLUSH"
    STANDING_WATER = "STANDING_WATER"


class ReportStatus(str, Enum):
    FILED = "FILED"
    SUPERSEDED = "SUPERSEDED"


class BrakingAction(str, Enum):
    GOOD = "GOOD"
    MEDIUM = "MEDIUM"
    MEDIUM_POOR = "MEDIUM_POOR"
    POOR = "POOR"
    NIL = "NIL"


class AssessmentStatus(str, Enum):
    REPORTED = "REPORTED"
    SUPERSEDED = "SUPERSEDED"


class NotamType(str, Enum):
    SURFACE_CONDITION = "SURFACE_CONDITION"
    RUNWAY_CLOSURE = "RUNWAY_CLOSURE"
    CHEMICAL_TREATMENT = "CHEMICAL_TREATMENT"


class NotamStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    REISSUE_REQUIRED = "REISSUE_REQUIRED"
    RESCINDED = "RESCINDED"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONSTRAINED = "CONSTRAINED"


class ApplicationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    AUTHORIZED = "AUTHORIZED"
    DISPENSED = "DISPENSED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class UnitType(str, Enum):
    PLOW = "PLOW"
    BROOM = "BROOM"
    DEICER = "DEICER"
    BLOWER = "BLOWER"


class Readiness(str, Enum):
    READY = "READY"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    OPS_CONTROLLER = "OpsController"
    AIRFIELD_INSPECTOR = "AirfieldInspector"
    MAINTENANCE_LEAD = "MaintenanceLead"
    AIRLINE_COORDINATOR = "AirlineCoordinator"
    SYSTEM_ADMIN = "SystemAdmin"


# Every entity in this domain carries id + created_at + updated_at + version
# (PRD section 2.4: no entity omits updated_at or version).


class SnowEvent(TypedDict, total=False):
    id: str
    event_code: str
    season_label: str
    chemical_limit_lbs: float
    budget_cents: int
    status: str
    closure_status: str
    airline_acknowledged: bool
    activated_at: Optional[str]
    estimated_cost_cents: int
    actual_cost_cents: int
    chemical_used_lbs: float
    created_at: str
    updated_at: str
    version: int


class AirfieldSurface(TypedDict, total=False):
    id: str
    surface_code: str
    surface_type: str
    length_ft: float
    width_ft: float
    area_sqft: float
    priority_rank: int
    status: str
    current_condition_code: Optional[int]
    active_notam_count: int
    created_at: str
    updated_at: str
    version: int


class ConditionReport(TypedDict, total=False):
    id: str
    event_id: str
    surface_id: str
    contaminant_type: str
    coverage_pct: int
    depth_inches: float
    observed_at: str
    condition_code: int
    status: str
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FrictionAssessment(TypedDict, total=False):
    id: str
    event_id: str
    surface_id: str
    mu_value: float
    measured_at: str
    braking_action: str
    status: str
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Notam(TypedDict, total=False):
    id: str
    event_id: str
    surface_id: str
    notam_type: str
    effective_from: str
    effective_until: str
    message: str
    source_assessment_id: Optional[str]
    source_report_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ChemicalProduct(TypedDict, total=False):
    id: str
    product_code: str
    base_rate_lbs_per_1000sqft: float
    unit_cost_cents_per_lb: int
    seasonal_limit_lbs: float
    seasonal_reserved_lbs: float
    seasonal_dispensed_lbs: float
    seasonal_available_lbs: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ChemicalApplication(TypedDict, total=False):
    id: str
    event_id: str
    surface_id: str
    product_id: str
    pavement_temp_f: float
    raw_quantity_lbs: float
    authorized_quantity_lbs: Optional[float]
    capped: bool
    authorized_by: Optional[str]
    line_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentUnit(TypedDict, total=False):
    id: str
    unit_code: str
    unit_type: str
    hourly_rate_cents: int
    readiness: str
    created_at: str
    updated_at: str
    version: int


class OperatorShift(TypedDict, total=False):
    id: str
    operator_code: str
    event_id: str
    equipment_unit_id: Optional[str]
    base_rate_cents_per_hour: int
    start_utc: str
    end_utc: str
    worked_hours: Optional[float]
    line_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
