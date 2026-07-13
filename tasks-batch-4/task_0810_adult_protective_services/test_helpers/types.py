"""Domain types for the Adult Protective Services API: entity TypedDicts,
status enums, and the role enum. Field names mirror the PRD exactly."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles ---
class UserRole(str, Enum):
    INTAKE_WORKER = "IntakeWorker"
    CASEWORKER = "Caseworker"
    SUPERVISOR = "Supervisor"
    ADMIN = "Admin"


# --- Report enums ---
class ReporterType(str, Enum):
    MANDATORY = "MANDATORY"
    VOLUNTARY = "VOLUNTARY"
    ANONYMOUS = "ANONYMOUS"


class Priority(str, Enum):
    EMERGENCY = "EMERGENCY"
    PRIORITY = "PRIORITY"
    ROUTINE = "ROUTINE"


class AllegationType(str, Enum):
    PHYSICAL_ABUSE = "PHYSICAL_ABUSE"
    NEGLECT = "NEGLECT"
    FINANCIAL_EXPLOITATION = "FINANCIAL_EXPLOITATION"
    EMOTIONAL_ABUSE = "EMOTIONAL_ABUSE"
    SELF_NEGLECT = "SELF_NEGLECT"


class ReportStatus(str, Enum):
    RECEIVED = "RECEIVED"
    SCREENED_IN = "SCREENED_IN"
    SCREENED_OUT = "SCREENED_OUT"


class ScreenDecision(str, Enum):
    SCREEN_IN = "SCREEN_IN"
    SCREEN_OUT = "SCREEN_OUT"


# --- Client enums ---
class CapacityStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    INTACT = "INTACT"
    IMPAIRED = "IMPAIRED"


class ClientStatus(str, Enum):
    INTAKE = "INTAKE"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    SERVICES_PENDING = "SERVICES_PENDING"
    SERVICES_ACTIVE = "SERVICES_ACTIVE"
    CLOSED = "CLOSED"


class ClientPlacementStatus(str, Enum):
    NONE = "NONE"
    PLACED = "PLACED"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class AssessmentType(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    COMPREHENSIVE = "COMPREHENSIVE"


# --- FinancialAccount enums ---
class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"


# --- Case enums ---
class CaseStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    READY_FOR_CLOSURE = "READY_FOR_CLOSURE"
    CLOSED = "CLOSED"


class GuardianshipStatus(str, Enum):
    NONE = "NONE"
    REFERRED = "REFERRED"


class ServicePlanStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


# --- Investigation enums ---
class InvestigationStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    FINDINGS_SUBMITTED = "FINDINGS_SUBMITTED"
    DISPOSED = "DISPOSED"


class Disposition(str, Enum):
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"
    INCONCLUSIVE = "INCONCLUSIVE"


# --- EmergencyPlacement enums ---
class PlacementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCHARGED = "DISCHARGED"
    EXPIRED = "EXPIRED"


# --- FinancialFreeze enums ---
class FreezeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


# --- Entity TypedDicts (all entities carry the common id/created_at/updated_at/version) ---
class Report(TypedDict, total=False):
    id: str
    client_id: str
    reporter_type: str
    reporter_name: Optional[str]
    allegation_types: List[str]
    priority: str
    narrative: str
    status: str
    response_due_at: str
    screening_overdue: bool
    screen_out_reason: Optional[str]
    case_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    address: str
    capacity_status: str
    status: str
    placement_status: str
    risk_level: Optional[str]
    preliminary_risk_score: Optional[int]
    comprehensive_risk_score: Optional[int]
    open_case_count: int
    created_at: str
    updated_at: str
    version: int


class FinancialAccount(TypedDict, total=False):
    id: str
    client_id: str
    institution_name: str
    total_balance_cents: int
    frozen_amount_cents: int
    available_balance_cents: int
    status: str
    flagged_amount_cents: int
    restitution_cents: int
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict, total=False):
    id: str
    name: str
    total_beds: int
    occupied_beds: int
    available_beds: int
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict, total=False):
    id: str
    report_id: str
    client_id: str
    status: str
    allegation_types: List[str]
    risk_level: Optional[str]
    estimated_exposure_cents: int
    substantiated_exposure_cents: int
    frozen_account_count: int
    cross_report_agency: Optional[str]
    cross_reported_at: Optional[str]
    guardianship_status: str
    service_plan_status: str
    benefit_programs: List[str]
    closed_at: Optional[str]
    closure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Investigation(TypedDict, total=False):
    id: str
    case_id: str
    assigned_caseworker_id: str
    status: str
    finding_summary: Optional[str]
    disposition: Optional[str]
    return_count: int
    disposed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmergencyPlacement(TypedDict, total=False):
    id: str
    case_id: str
    client_id: str
    facility_id: str
    start_at: str
    end_at: str
    court_authorized: bool
    status: str
    expires_at: str
    discharged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FinancialFreeze(TypedDict, total=False):
    id: str
    case_id: str
    account_id: str
    flagged_amount_cents: int
    freeze_start: str
    freeze_end: str
    status: str
    lifted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
