"""Domain types: entity TypedDicts, status enums, role enum.

All field names are exactly as named in the PRD. Entities that carry only
`id` + `created_at` (Crew, CrewShift) omit `updated_at` and `version`.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum (PRD §2.1) ─────────────────────────────────────────────
class UserRole(str, Enum):
    SALES_REP = "SalesRep"
    BID_ESTIMATOR = "BidEstimator"
    OPERATIONS_MANAGER = "OperationsManager"
    ACCOUNT_MANAGER = "AccountManager"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Status enums (PRD §3) ────────────────────────────────────────────
class AccountLifecycleStage(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE_CUSTOMER = "ACTIVE_CUSTOMER"
    CHURNED = "CHURNED"


class RfpStatus(str, Enum):
    OPEN = "OPEN"
    WALKTHROUGH_SCHEDULED = "WALKTHROUGH_SCHEDULED"
    BIDDING = "BIDDING"
    PROPOSED = "PROPOSED"
    WON = "WON"
    LOST = "LOST"


class WalkthroughStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class BidEstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    PRICED = "PRICED"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class ContractLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    STARTUP = "STARTUP"
    SERVICING = "SERVICING"
    ENDED = "ENDED"


class ContractBillingStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class StartupPlanStatus(str, Enum):
    PLANNING = "PLANNING"
    CREWED = "CREWED"
    READY = "READY"
    LIVE = "LIVE"
    ABORTED = "ABORTED"


class CrewStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RETIRED = "RETIRED"


class CrewShiftStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CANCELLED = "CANCELLED"


class SupplyRequisitionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    CANCELLED = "CANCELLED"


class RenewalCycleStatus(str, Enum):
    DRAFT = "DRAFT"
    OFFERED = "OFFERED"
    RENEWED = "RENEWED"
    LAPSED = "LAPSED"


# ─── Entity TypedDicts ────────────────────────────────────────────────
# common_fields: true → id + created_at + updated_at + version
class Account(TypedDict):
    id: str
    legal_name: str
    industry: str
    owner_user_id: Optional[str]
    lifecycle_stage: str
    health_score: int
    created_at: str
    updated_at: str
    version: int


class RfpOpportunity(TypedDict):
    id: str
    account_id: str
    title: str
    due_at: str
    estimated_total_sqft: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Walkthrough(TypedDict):
    id: str
    rfp_id: str
    site_contact_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SiteContact(TypedDict):
    id: str
    account_id: str
    full_name: str
    avail_start_at: str
    avail_end_at: str
    created_at: str
    updated_at: str
    version: int


class ServiceArea(TypedDict):
    id: str
    rfp_id: str
    label: str
    sqft: int
    soil_level: str
    frequency_per_week: int
    weekly_hours: float
    created_at: str
    updated_at: str
    version: int


class BidEstimate(TypedDict):
    id: str
    rfp_id: str
    base_wage_cents: int
    target_margin_pct: float
    loading_method: str
    monthly_labor_hours: float
    labor_cost_cents: int
    supply_cost_cents: int
    total_cost_cents: int
    base_bid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Proposal(TypedDict):
    id: str
    rfp_id: str
    bid_estimate_id: str
    monthly_price_cents: int
    achieved_margin_pct: float
    revision_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CleaningContract(TypedDict):
    id: str
    account_id: str
    proposal_id: str
    monthly_value_cents: int
    term_months: int
    lifecycle_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class StartupPlan(TypedDict):
    id: str
    contract_id: str
    planned_monthly_hours: float
    allocated_hours: float
    go_live_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplyBudget(TypedDict):
    id: str
    contract_id: str
    total_cents: int
    committed_cents: int
    remaining_cents: int
    created_at: str
    updated_at: str
    version: int


class SupplyRequisition(TypedDict):
    id: str
    supply_budget_id: str
    item_label: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RenewalCycle(TypedDict):
    id: str
    contract_id: str
    escalation_method: str
    proposed_monthly_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false → ONLY id + created_at (no updated_at, no version)
class Crew(TypedDict):
    id: str
    name: str
    weekly_capacity_hours: float
    status: str
    created_at: str


class CrewShift(TypedDict):
    id: str
    startup_plan_id: str
    crew_id: str
    start_at: str
    end_at: str
    shift_hours: float
    status: str
    created_at: str
