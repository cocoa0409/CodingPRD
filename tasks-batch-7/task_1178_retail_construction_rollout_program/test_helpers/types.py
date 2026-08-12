"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_DIRECTOR = "ProgramDirector"
    DESIGN_MANAGER = "DesignManager"
    PERMIT_COORDINATOR = "PermitCoordinator"
    PROCUREMENT_LEAD = "ProcurementLead"
    GC_VENDOR = "GCVendor"
    SITE_SUPERINTENDENT = "SiteSuperintendent"
    OPERATIONS_LEAD = "OperationsLead"
    FINANCE_CONTROLLER = "FinanceController"


class RolloutProgramStatus(str, Enum):
    SETUP = "SETUP"
    ACTIVE = "ACTIVE"
    COMPLETE = "COMPLETE"


class ProgramBudgetPosture(str, Enum):
    WITHIN_PLAN = "WITHIN_PLAN"
    GUARDED = "GUARDED"
    OVERRUN = "OVERRUN"


class MarketStatus(str, Enum):
    REGISTERED = "REGISTERED"
    BIDDING = "BIDDING"
    AWARDED = "AWARDED"


class SiteStatus(str, Enum):
    LISTED = "LISTED"
    DESIGN = "DESIGN"
    PERMITTING = "PERMITTING"
    MOBILIZED = "MOBILIZED"
    IN_BUILD = "IN_BUILD"
    PUNCH = "PUNCH"
    TURNOVER = "TURNOVER"
    OPEN = "OPEN"
    REMOVED = "REMOVED"


class SiteBudgetPosture(str, Enum):
    WITHIN = "WITHIN"
    WATCH = "WATCH"
    OVERRUN = "OVERRUN"


class ReadinessPosture(str, Enum):
    ROUGH = "ROUGH"
    FIXTURE_SET = "FIXTURE_SET"
    IT_LIVE = "IT_LIVE"
    SIGNAGE_HUNG = "SIGNAGE_HUNG"


class DrawingSetStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ISSUED = "ISSUED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class PermitType(str, Enum):
    BUILDING = "BUILDING"
    ELECTRICAL = "ELECTRICAL"
    SIGNAGE = "SIGNAGE"
    HEALTH = "HEALTH"


class ContractorStatus(str, Enum):
    PREQUALIFIED = "PREQUALIFIED"
    SUSPENDED = "SUSPENDED"


class BidPackageStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    AWARDED = "AWARDED"


class EvaluationMode(str, Enum):
    LOWEST_PRICE = "LOWEST_PRICE"
    BEST_VALUE = "BEST_VALUE"


class BidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    WITHDRAWN = "WITHDRAWN"
    AWARDED = "AWARDED"
    REJECTED = "REJECTED"


class VendorType(str, Enum):
    FIXTURE = "FIXTURE"
    IT = "IT"
    SIGNAGE = "SIGNAGE"


class VendorMobilizationStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    ON_SITE = "ON_SITE"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class ChangeOrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    RESCINDED = "RESCINDED"


class CostCategory(str, Enum):
    SCOPE = "SCOPE"
    SCHEDULE = "SCHEDULE"
    CODE_COMPLIANCE = "CODE_COMPLIANCE"
    OWNER_REQUEST = "OWNER_REQUEST"


class ChangeOrderTier(str, Enum):
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    CRITICAL = "CRITICAL"


class PunchSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class PunchItemStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    VERIFIED = "VERIFIED"
    WAIVED = "WAIVED"


class TurnoverStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ProtectionPosture(str, Enum):
    PROTECTED = "PROTECTED"
    WATCH = "WATCH"
    AT_RISK = "AT_RISK"
    BREACHED = "BREACHED"
    MET = "MET"


# All resources in this API carry the four system-managed properties
# id, created_at, updated_at, version (PRD common-properties rule).


class RolloutProgram(TypedDict, total=False):
    id: str
    name: str
    fiscal_year: int
    total_budget_cents: int
    contingency_pool_cents: int
    committed_cents: int
    actuals_cents: int
    contingency_reserved_cents: int
    contingency_free_cents: int
    budget_posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Market(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    state_code: str
    max_concurrent_vendor_crews: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MunicipalityProfile(TypedDict, total=False):
    id: str
    municipality_code: str
    statutory_review_days: int
    observed_avg_review_days: int
    permit_validity_days: int
    fee_base_cents: int
    fee_per_sqft_cents: int
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict, total=False):
    id: str
    program_id: str
    market_id: str
    municipality_code: str
    address: str
    square_footage: int
    phase_wave: int
    budget_allocation_cents: int
    target_open_date: str
    base_contract_cents: int
    approved_co_cents: int
    proposed_co_cents: int
    committed_cents: int
    variance_ratio_final_bp: int
    variance_ratio_provisional_bp: int
    budget_posture: str
    actuals_cents: int
    permit_fees_paid_cents: int
    readiness_posture: str
    punch_open_critical_count: int
    punch_open_total_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DrawingSet(TypedDict, total=False):
    id: str
    program_id: str
    jurisdiction_code: str
    revision: int
    review_round: int
    supersedes_set_id: Optional[str]
    variance_notes: Optional[str]
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    site_id: str
    drawing_set_id: str
    permit_type: str
    municipality_code: str
    round_number: int
    fee_cents: int
    filed_at: Optional[str]
    review_due_on: Optional[str]
    issued_at: Optional[str]
    expires_on: Optional[str]
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Contractor(TypedDict, total=False):
    id: str
    legal_name: str
    license_no: str
    license_state: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BidPackage(TypedDict, total=False):
    id: str
    market_id: str
    phase_wave: int
    scope_description: str
    bid_open_at: str
    bid_close_at: str
    evaluation_mode: str
    max_duration_days: int
    awarded_bid_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict, total=False):
    id: str
    bid_package_id: str
    contractor_id: str
    amount_cents: int
    duration_days: int
    tech_score: int
    is_responsive: bool
    evaluation_score: Optional[float]
    submitted_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VendorMobilization(TypedDict, total=False):
    id: str
    site_id: str
    vendor_type: str
    vendor_name: str
    planned_start_on: str
    planned_end_on: str
    actual_start_on: Optional[str]
    actual_end_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict, total=False):
    id: str
    site_id: str
    description: str
    amount_cents: int
    cost_category: str
    tier: str
    proposed_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PunchItem(TypedDict, total=False):
    id: str
    site_id: str
    description: str
    severity: str
    reopen_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Turnover(TypedDict, total=False):
    id: str
    site_id: str
    readiness_snapshot: Dict[str, Any]
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OpeningCommitment(TypedDict, total=False):
    id: str
    site_id: str
    committed_open_on: str
    forecast_open_on: Optional[str]
    forecast_optimistic_on: Optional[str]
    slip_days: int
    protection_posture: str
    created_at: str
    updated_at: str
    version: int
