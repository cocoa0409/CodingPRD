"""Domain types: entity TypedDicts, status enums, and the role enum.

All names and fields track the Weatherization PRD exactly. Diagnostic tests are
the sole append-only resource: they carry only ``id`` and ``created_at`` (no
``updated_at`` / ``version``); every other resource carries the full common set.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ------------------------------------------------------------
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    AUDITOR = "Auditor"
    INSTALLER = "Installer"
    HOMEOWNER = "Homeowner"


# --- Enumerations ---------------------------------------------------------
class FoundationType(str, Enum):
    SLAB = "SLAB"
    CRAWLSPACE = "CRAWLSPACE"
    BASEMENT = "BASEMENT"


class HeatingFuelType(str, Enum):
    GAS = "GAS"
    ELECTRIC = "ELECTRIC"
    OIL = "OIL"
    PROPANE = "PROPANE"


class ProgramTrack(str, Enum):
    WAP = "WAP"
    UTILITY = "UTILITY"
    MARKET = "MARKET"


class WapStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class JobStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InstallStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    INSTALLED = "INSTALLED"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class AuditStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DiagnosticKind(str, Enum):
    BLOWER_DOOR = "BLOWER_DOOR"
    DUCT_LEAKAGE = "DUCT_LEAKAGE"


class DiagnosticStage(str, Enum):
    BASELINE = "BASELINE"
    POST = "POST"


class ScopeCategory(str, Enum):
    ATTIC_INSULATION = "ATTIC_INSULATION"
    WALL_INSULATION = "WALL_INSULATION"
    CRAWL_INSULATION = "CRAWL_INSULATION"
    AIR_SEALING = "AIR_SEALING"
    DUCT_SEALING = "DUCT_SEALING"


class ScopeItemStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    INSTALLED = "INSTALLED"
    VERIFIED = "VERIFIED"
    FAILED_VERIFICATION = "FAILED_VERIFICATION"
    CANCELLED = "CANCELLED"


class CrewAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class RebateClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    VOIDED = "VOIDED"


class FinancingPlanStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version)
class Dwelling(TypedDict):
    id: str
    address: str
    year_built: int
    conditioned_area_sqft: float
    foundation_type: str
    heating_fuel_type: str
    created_at: str
    updated_at: str
    version: int


class WapApplication(TypedDict):
    id: str
    dwelling_id: str
    household_size: int
    annual_gross_income_cents: int
    income_limit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Job(TypedDict):
    id: str
    dwelling_id: str
    program_track: str
    rebate_budget_cap_cents: int
    job_status: str
    install_status: str
    verification_status: str
    total_estimated_cost_cents: int
    approved_rebate_total_cents: int
    tax_credit_cents: int
    estimated_out_of_pocket_cents: int
    estimated_annual_savings_kwh: float
    verified_annual_savings_kwh: Optional[float]
    created_at: str
    updated_at: str
    version: int


class EnergyAudit(TypedDict):
    id: str
    job_id: str
    auditor_user_id: str
    status: str
    estimated_annual_savings_kwh: float
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only measurement event: id + created_at ONLY.
class DiagnosticTest(TypedDict):
    id: str
    job_id: str
    kind: str
    stage: str
    cfm_measured: float
    baseline_test_id: Optional[str]
    tester_user_id: str
    created_at: str


class ScopeItem(TypedDict):
    id: str
    job_id: str
    audit_id: str
    category: str
    area_sqft: float
    target_r_value: float
    achieved_r_value: Optional[float]
    estimated_cost_cents: int
    actual_cost_cents: Optional[int]
    estimated_savings_kwh: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    name: str
    crew_size: int
    skills: List[str]
    capacity_days: int
    committed_days: int
    available_days: int
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict):
    id: str
    job_id: str
    crew_id: str
    scheduled_start_date: str
    scheduled_end_date: str
    duration_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RebateClaim(TypedDict):
    id: str
    job_id: str
    scope_item_id: str
    provisional_amount_cents: int
    finalized_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancingPlan(TypedDict):
    id: str
    job_id: str
    principal_cents: int
    term_months: int
    apr_bps: int
    monthly_payment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
