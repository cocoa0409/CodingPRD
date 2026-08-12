"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    FAA_MANAGER = "FAAManager"
    SPONSOR_STAFF = "SponsorStaff"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FINANCE_OFFICER = "FinanceOfficer"
    AUDITOR = "Auditor"
    CONTRACTOR = "Contractor"


# ---------------------------------------------------------------------------
# Enumerated field values (PRD §3)
# ---------------------------------------------------------------------------
class AirportSizeTier(str, Enum):
    LARGE_HUB = "LARGE_HUB"
    MEDIUM_HUB = "MEDIUM_HUB"
    SMALL_HUB = "SMALL_HUB"
    NONHUB = "NONHUB"


class SponsorStatus(str, Enum):
    ACTIVE = "ACTIVE"


class FacilityType(str, Enum):
    RUNWAY = "RUNWAY"
    TAXIWAY = "TAXIWAY"
    APRON = "APRON"


class CapitalProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    AMENDMENT_DRAFT = "AMENDMENT_DRAFT"
    EXPIRED = "EXPIRED"


class ProjectType(str, Enum):
    RUNWAY_SAFETY = "RUNWAY_SAFETY"
    CAPACITY = "CAPACITY"
    PRESERVATION = "PRESERVATION"
    SECURITY = "SECURITY"
    ENVIRONMENTAL = "ENVIRONMENTAL"
    NOISE = "NOISE"


class CIPProjectStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SELECTED = "SELECTED"
    DEFERRED = "DEFERRED"
    DROPPED = "DROPPED"


class GrantApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED = "RETURNED"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class AssuranceCode(str, Enum):
    TITLE_VI = "TITLE_VI"
    BUY_AMERICAN = "BUY_AMERICAN"
    DBE_PROGRAM = "DBE_PROGRAM"
    ENVIRONMENTAL_REVIEW = "ENVIRONMENTAL_REVIEW"
    PREVAILING_WAGE = "PREVAILING_WAGE"
    AIRPORT_FEES = "AIRPORT_FEES"


class SponsorAssuranceStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    WAIVED = "WAIVED"


class GrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSEOUT_REQUESTED = "CLOSEOUT_REQUESTED"
    UNDER_AUDIT = "UNDER_AUDIT"
    CLOSED = "CLOSED"


class GrantAmendmentStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ContractorStatus(str, Enum):
    REGISTERED = "REGISTERED"
    SUSPENDED = "SUSPENDED"


class ContractStatus(str, Enum):
    AWARDED = "AWARDED"
    CLOSED = "CLOSED"


class DbePosture(str, Enum):
    UNEVALUATED = "UNEVALUATED"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class DBEReportStatus(str, Enum):
    PENDING = "PENDING"
    COMPLIANT = "COMPLIANT"
    SHORTFALL = "SHORTFALL"


class InvoiceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    INCLUDED = "INCLUDED"
    PAID = "PAID"
    WITHHELD = "WITHHELD"


class ReimbursementRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"


class FindingCode(str, Enum):
    INELIGIBLE_COST = "INELIGIBLE_COST"
    MISSING_DOCUMENTATION = "MISSING_DOCUMENTATION"
    DBE_SHORTFALL = "DBE_SHORTFALL"
    PROCUREMENT = "PROCUREMENT"
    OTHER = "OTHER"


class FindingSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AuditFindingStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class AssetKind(str, Enum):
    EQUIPMENT = "EQUIPMENT"
    LAND = "LAND"


class GrantAssetStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    DISPOSAL_REQUESTED = "DISPOSAL_REQUESTED"
    DISPOSED = "DISPOSED"


class ClosureType(str, Enum):
    FULL_CLOSURE = "FULL_CLOSURE"
    NIGHT_ONLY = "NIGHT_ONLY"


class ConstructionPhaseStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.5 common fields; §2.5 lean subordinate records)
# ---------------------------------------------------------------------------
class Sponsor(TypedDict):
    id: str
    sponsor_name: str
    loc_id: str
    airport_size_tier: str
    npe_entitlement_total: float
    npe_entitlement_available: float
    status: str
    created_at: str
    updated_at: str
    version: int


class AirfieldFacility(TypedDict):
    id: str
    sponsor_id: str
    facility_name: str
    facility_type: str
    created_at: str
    updated_at: str
    version: int


class CapitalProgram(TypedDict):
    id: str
    sponsor_id: str
    fiscal_year: int
    selection_budget: float
    selected_total_cost: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CIPProject(TypedDict):
    id: str
    program_id: str
    title: str
    project_type: str
    estimated_cost: float
    safety_score: int
    capacity_score: int
    preservation_score: int
    security_score: int
    environmental_score: int
    runway_safety_noncompliant: bool
    multi_airport_system: bool
    priority_score_sponsor: Optional[float]
    priority_score_federal: Optional[float]
    selection_rank: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class GrantApplication(TypedDict):
    id: str
    sponsor_id: str
    program_id: str
    project_ids: List[str]
    total_eligible_cost: float
    created_by_user_id: str
    assurances_total: int
    assurances_cleared: int
    submission_deadline: str
    offered_federal_obligated: Optional[float]
    offered_entitlement_portion: Optional[float]
    created_grant_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only checklist row: id + created_at only
class SponsorAssurance(TypedDict):
    id: str
    application_id: str
    assurance_code: str
    certified_by_user_id: Optional[str]
    status: str
    created_at: str


class Grant(TypedDict):
    id: str
    sponsor_id: str
    application_id: str
    grant_number: str
    federal_share_pct: float
    total_budget: float
    federal_obligated: float
    federal_drawn: float
    federal_available: float
    state_share_estimated: float
    local_share_estimated: float
    entitlement_portion: float
    status: str
    created_at: str
    updated_at: str
    version: int


class GrantAmendment(TypedDict):
    id: str
    grant_id: str
    added_scope_cost: float
    reason: str
    contingency_amount: float
    new_total_budget: float
    federal_delta: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Contractor(TypedDict):
    id: str
    sponsor_id: str
    contractor_name: str
    dbe_certified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    grant_id: str
    cip_project_id: str
    contractor_id: str
    awarded_value: float
    dbe_goal_pct: float
    retainage_pct: float
    invoiced_total: float
    remaining_value: float
    retainage_held: float
    dbe_posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — write-once adjudicated record: id + created_at only
class DBEReport(TypedDict):
    id: str
    contract_id: str
    reporting_period: str
    dbe_paid_amount: float
    total_paid_amount: float
    achieved_dbe_pct: float
    status: str
    created_at: str


class Invoice(TypedDict):
    id: str
    contract_id: str
    invoice_number: str
    period: str
    gross_amount: float
    retainage_withheld: float
    net_payable: float
    drawdown_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReimbursementRequest(TypedDict):
    id: str
    grant_id: str
    invoice_ids: List[str]
    total_net: float
    federal_amount: float
    prepared_by_user_id: str
    certified_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — audit record: id + created_at only
class AuditFinding(TypedDict):
    id: str
    grant_id: str
    finding_code: str
    severity: str
    description: str
    status: str
    created_at: str


class GrantAsset(TypedDict):
    id: str
    grant_id: str
    asset_kind: str
    description: str
    acquisition_federal_share: float
    useful_life_years: int
    in_service_date: str
    service_credit_value: float
    remaining_restricted_value: float
    payback_due: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ConstructionPhase(TypedDict):
    id: str
    grant_id: str
    cip_project_id: str
    facility_id: str
    contractor_id: str
    closure_type: str
    start_utc: str
    end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int
