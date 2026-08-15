"""Domain types: entity TypedDicts, status enums, role enum for the septic-ops API."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (six roles from PRD section on access control)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROJECT_MANAGER = "ProjectManager"
    SYSTEM_DESIGNER = "SystemDesigner"
    SOIL_SCIENTIST = "SoilScientist"
    INSPECTOR = "Inspector"
    HEALTH_OFFICER = "HealthOfficer"


# ---------------------------------------------------------------------------
# Status / enum-valued fields
# ---------------------------------------------------------------------------
class SiteStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class ScienceStatus(str, Enum):
    """Shared lifecycle of soil evaluations and percolation tests."""
    RECORDED = "RECORDED"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class SoilClass(str, Enum):
    SAND = "SAND"
    LOAM = "LOAM"
    CLAY_LOAM = "CLAY_LOAM"
    CLAY = "CLAY"


class SystemType(str, Enum):
    GRAVITY = "GRAVITY"
    PRESSURE_DISTRIBUTION = "PRESSURE_DISTRIBUTION"
    MOUND = "MOUND"
    AEROBIC = "AEROBIC"


class DesignStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class PermitStatus(str, Enum):
    ISSUED = "ISSUED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    FINALIZED = "FINALIZED"
    REVOKED = "REVOKED"


class InstallationStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    ROUGH_IN_PROGRESS = "ROUGH_IN_PROGRESS"
    TANK_SET = "TANK_SET"
    FIELD_INSTALLED = "FIELD_INSTALLED"
    READY_FOR_FINAL = "READY_FOR_FINAL"
    COMPLETED = "COMPLETED"
    FAILED_HOLD = "FAILED_HOLD"
    ABANDONED = "ABANDONED"


class HoldPoint(str, Enum):
    TANK_SET = "TANK_SET"
    FIELD_LAYOUT = "FIELD_LAYOUT"
    FINAL = "FINAL"


class InspectionResult(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class MaterialKind(str, Enum):
    TANK = "TANK"
    PIPE = "PIPE"
    AGGREGATE = "AGGREGATE"
    CHAMBER = "CHAMBER"
    PUMP = "PUMP"


class ReliefKind(str, Enum):
    SETBACK_REDUCTION = "SETBACK_REDUCTION"
    AREA_REDUCTION = "AREA_REDUCTION"
    HIGH_WATER_TABLE = "HIGH_WATER_TABLE"
    REPAIR_IN_KIND = "REPAIR_IN_KIND"


class VarianceStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class FailureKind(str, Enum):
    HYDRAULIC_OVERLOAD = "HYDRAULIC_OVERLOAD"
    STRUCTURAL_COLLAPSE = "STRUCTURAL_COLLAPSE"
    ROOT_INTRUSION = "ROOT_INTRUSION"
    HIGH_WATER_INTRUSION = "HIGH_WATER_INTRUSION"


class Remedy(str, Enum):
    UNDECIDED = "UNDECIDED"
    REPAIR_IN_KIND = "REPAIR_IN_KIND"
    REPLACEMENT = "REPLACEMENT"


class RepairCaseStatus(str, Enum):
    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    IN_REMEDIATION = "IN_REMEDIATION"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry the four common properties:
# id, created_at, updated_at, version)
# ---------------------------------------------------------------------------
class InstallerCompany(TypedDict, total=False):
    id: str
    legal_name: str
    license_number: str
    county_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    installer_company_id: str
    full_name: str
    email: str
    phone: str
    education_completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict, total=False):
    id: str
    customer_id: str
    installer_company_id: str
    parcel_id: str
    address_line: str
    county_code: str
    current_period_index: int
    seasonal_freeze_until: int
    status: str
    high_water_table: bool
    created_at: str
    updated_at: str
    version: int


class SoilEvaluation(TypedDict, total=False):
    id: str
    site_id: str
    evaluator_id: str
    soil_class: str
    limiting_layer_inches: int
    evaluation_date_period: int
    superseded_by_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PercolationTest(TypedDict, total=False):
    id: str
    site_id: str
    evaluator_id: str
    minutes_per_inch: float
    test_pit_count: int
    test_date_period: int
    superseded_by_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SoilScientist(TypedDict, total=False):
    id: str
    installer_company_id: str
    full_name: str
    license_number: str
    created_at: str
    updated_at: str
    version: int


class SystemDesign(TypedDict, total=False):
    id: str
    site_id: str
    designer_id: str
    soil_evaluation_id: str
    percolation_test_id: str
    bedroom_count: int
    system_type: str
    design_daily_flow_gpd: float
    required_absorption_area_sqft: float
    tank_capacity_gal: float
    reserve_area_sqft: float
    provisional_estimate_cents: Optional[int]
    design_version: int
    supersedes_design_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SystemDesigner(TypedDict, total=False):
    id: str
    installer_company_id: str
    full_name: str
    license_number: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    site_id: str
    design_id: str
    permit_number: str
    issued_period: int
    expires_period: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Installation(TypedDict, total=False):
    id: str
    site_id: str
    permit_id: str
    crew_lead: str
    started_period: Optional[int]
    completed_period: Optional[int]
    final_absorption_area_sqft: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    installation_id: str
    hold_point: str
    inspector_id: str
    result: str
    scheduled_period: int
    decided_period: Optional[int]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaterialVerification(TypedDict, total=False):
    id: str
    installation_id: str
    material_kind: str
    quantity: float
    unit_cost_cents: int
    verified: bool
    verified_by: Optional[str]
    verified_period: Optional[int]
    created_at: str
    updated_at: str
    version: int


class VarianceRequest(TypedDict, total=False):
    id: str
    site_id: str
    design_id: str
    relief_kind: str
    justification: str
    decided_by: Optional[str]
    decision_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceContract(TypedDict, total=False):
    id: str
    site_id: str
    customer_id: str
    installation_id: str
    start_period: int
    end_period: int
    annual_fee_cents: int
    prorated_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceVisit(TypedDict, total=False):
    id: str
    contract_id: str
    visit_period: int
    findings: str
    alarm_condition: bool
    technician_name: str
    created_at: str
    updated_at: str
    version: int


class RepairCase(TypedDict, total=False):
    id: str
    site_id: str
    failed_installation_id: str
    failure_kind: str
    diagnosis_note: str
    remedy: str
    replacement_design_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict, total=False):
    id: str
    installer_company_id: str
    full_name: str
    license_number: str
    created_at: str
    updated_at: str
    version: int


class HealthOfficer(TypedDict, total=False):
    id: str
    installer_company_id: str
    full_name: str
    badge_number: str
    created_at: str
    updated_at: str
    version: int


class ProjectManager(TypedDict, total=False):
    id: str
    installer_company_id: str
    full_name: str
    employee_number: str
    created_at: str
    updated_at: str
    version: int
