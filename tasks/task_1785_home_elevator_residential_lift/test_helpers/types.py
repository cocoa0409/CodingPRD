"""Domain types: entity TypedDicts, status enums, role enum.

All resources carry the common bookkeeping fields id / created_at /
updated_at / version (PRD §2.5).
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class SurveyStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FeasibilityVerdict(str, Enum):
    FEASIBLE = "FEASIBLE"
    CONDITIONAL = "CONDITIONAL"
    INFEASIBLE = "INFEASIBLE"


class ProductModelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class DriveType(str, Enum):
    HYDRAULIC = "HYDRAULIC"
    TRACTION = "TRACTION"
    PNEUMATIC = "PNEUMATIC"
    PLATFORM_LIFT = "PLATFORM_LIFT"


class Certification(str, Enum):
    CET = "CET"
    QEI = "QEI"
    CET_AND_QEI = "CET_AND_QEI"


class TechnicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ContractorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    PERMIT_IN_PROGRESS = "PERMIT_IN_PROGRESS"
    PERMIT_APPROVED = "PERMIT_APPROVED"
    STRUCTURAL_IN_PROGRESS = "STRUCTURAL_IN_PROGRESS"
    READY_FOR_INSTALL = "READY_FOR_INSTALL"
    INSTALL_SCHEDULED = "INSTALL_SCHEDULED"
    INSTALL_COMPLETE = "INSTALL_COMPLETE"
    AWAITING_REGISTRATION = "AWAITING_REGISTRATION"
    REGISTERED = "REGISTERED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ProjectType(str, Enum):
    NEW_INSTALLATION = "NEW_INSTALLATION"
    MODERNIZATION = "MODERNIZATION"


class FundingPosture(str, Enum):
    UNFUNDED = "UNFUNDED"
    PARTIALLY_FUNDED = "PARTIALLY_FUNDED"
    FULLY_FUNDED = "FULLY_FUNDED"


class PermitStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    CORRECTIONS_REQUIRED = "CORRECTIONS_REQUIRED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class WorkOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    WORK_COMPLETE = "WORK_COMPLETE"
    VERIFIED = "VERIFIED"
    CANCELLED = "CANCELLED"


class EquipmentStatus(str, Enum):
    INSTALLED = "INSTALLED"
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    UNDER_MODERNIZATION = "UNDER_MODERNIZATION"
    DECOMMISSIONED = "DECOMMISSIONED"


class RegistrationStatus(str, Enum):
    UNREGISTERED = "UNREGISTERED"
    REGISTERED = "REGISTERED"
    LAPSED = "LAPSED"
    SUSPENDED = "SUSPENDED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class InspectionType(str, Enum):
    ACCEPTANCE = "ACCEPTANCE"
    ANNUAL = "ANNUAL"
    REINSPECTION = "REINSPECTION"
    MODERNIZATION_ACCEPTANCE = "MODERNIZATION_ACCEPTANCE"


class CertificateStatus(str, Enum):
    PENDING_ISSUANCE = "PENDING_ISSUANCE"
    ACTIVE = "ACTIVE"
    RENEWAL_DUE = "RENEWAL_DUE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class ContractTier(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class CallType(str, Enum):
    MAINTENANCE_VISIT = "MAINTENANCE_VISIT"
    REPAIR = "REPAIR"
    ENTRAPMENT = "ENTRAPMENT"


class ServiceCallStatus(str, Enum):
    OPEN = "OPEN"
    DISPATCHED = "DISPATCHED"
    ON_SITE = "ON_SITE"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class ProgramStatus(str, Enum):
    OPEN = "OPEN"
    PAUSED = "PAUSED"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    DISBURSED = "DISBURSED"
    WITHDRAWN = "WITHDRAWN"
    CLAWED_BACK = "CLAWED_BACK"


class ChangeOrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class UserRole(str, Enum):
    DEALER_ADMIN = "DealerAdmin"
    PROJECT_COORDINATOR = "ProjectCoordinator"
    SURVEYOR = "Surveyor"
    INSTALLER = "Installer"
    INSPECTOR = "Inspector"
    CONTRACTOR = "Contractor"
    HOMEOWNER = "Homeowner"
    GRANT_OFFICER = "GrantOfficer"
    REGULATOR = "Regulator"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every resource carries the common bookkeeping fields
# (id, created_at, updated_at, version).
# ---------------------------------------------------------------------------

class Property(TypedDict, total=False):
    id: str
    owner_user_id: str
    address_line: str
    state_code: str
    has_existing_shaft: bool
    created_at: str
    updated_at: str
    version: int


class SiteSurvey(TypedDict, total=False):
    id: str
    property_id: str
    surveyor_technician_id: str
    scheduled_date: str
    measured_pit_depth_inches: Optional[float]
    measured_overhead_clearance_inches: Optional[float]
    shaft_width_inches: Optional[float]
    shaft_depth_inches: Optional[float]
    floors_served: Optional[int]
    feasibility_verdict: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductModel(TypedDict, total=False):
    id: str
    model_code: str
    drive_type: str
    min_pit_depth_inches: float
    min_overhead_clearance_inches: float
    capacity_lbs: int
    base_price: float
    install_labor_price: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    full_name: str
    certification: str
    home_region: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Contractor(TypedDict, total=False):
    id: str
    company_name: str
    license_number: str
    license_state_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict, total=False):
    id: str
    property_id: str
    survey_id: str
    project_type: str
    modernize_unit_id: Optional[str]
    product_model_id: Optional[str]
    lead_installer_technician_id: Optional[str]
    contractor_id: Optional[str]
    requires_structural: Optional[bool]
    structural_estimate: Optional[float]
    contract_price: Optional[float]
    approved_change_order_total: Optional[float]
    structural_adjustment: Optional[float]
    final_invoice: Optional[float]
    disbursed_grants: Optional[float]
    homeowner_balance: Optional[float]
    funding_posture: Optional[str]
    install_start_date: Optional[str]
    install_end_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PermitApplication(TypedDict, total=False):
    id: str
    project_id: str
    ahj_name: str
    fee: float
    revision_count: int
    approved_date: Optional[str]
    valid_through: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StructuralWorkOrder(TypedDict, total=False):
    id: str
    project_id: str
    contractor_id: str
    scope_description: str
    scheduled_start_date: str
    scheduled_end_date: str
    estimated_cost: float
    actual_cost: Optional[float]
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ElevatorUnit(TypedDict, total=False):
    id: str
    property_id: str
    project_id: str
    product_model_id: str
    modernized_from_unit_id: Optional[str]
    serial_number: str
    install_date: str
    equipment_status: str
    registration_status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    unit_id: str
    project_id: Optional[str]
    inspector_technician_id: str
    inspection_type: str
    scheduled_start: str
    scheduled_end: str
    deficiency_codes: Optional[List[str]]
    recorded_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RegistrationCertificate(TypedDict, total=False):
    id: str
    unit_id: str
    certificate_number: Optional[str]
    issued_date: Optional[str]
    expiration_date: Optional[str]
    renewal_count: int
    last_renewal_fee: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceContract(TypedDict, total=False):
    id: str
    unit_id: str
    tier: str
    annual_fee: float
    included_visits: int
    visits_consumed: int
    entrapment_sla_minutes: int
    contract_year_start: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceCall(TypedDict, total=False):
    id: str
    unit_id: str
    contract_id: Optional[str]
    technician_id: Optional[str]
    call_type: str
    description: Optional[str]
    reported_at: str
    arrived_at: Optional[str]
    resolved_at: Optional[str]
    sla_deadline: Optional[str]
    sla_breached: Optional[bool]
    provisional_estimate: Optional[float]
    final_billable: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class GrantProgram(TypedDict, total=False):
    id: str
    program_name: str
    funder_name: str
    max_award: float
    income_cap: float
    coverage_percent: float
    total_pool: float
    remaining_pool: float
    application_open_date: str
    application_close_date: str
    eligible_project_types: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class GrantApplication(TypedDict, total=False):
    id: str
    project_id: str
    program_id: str
    household_income: float
    verified_income: Optional[float]
    provisional_award: float
    final_award: Optional[float]
    disbursed: Optional[float]
    submitted_at: str
    approved_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict, total=False):
    id: str
    project_id: str
    description: str
    amount: float
    effective_amount: Optional[float]
    approved_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
