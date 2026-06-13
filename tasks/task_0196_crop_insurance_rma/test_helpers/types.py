"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Crop Insurance (USDA RMA) PRD. Entities that carry the uniform
system-managed field set (id, created_at, updated_at, version) are modeled with
all four; the two identity entities (Producer, Agent) carry only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────────────────────────

class CommodityProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class PolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class CoverageElectionStatus(str, Enum):
    ELECTED = "ELECTED"
    REPORTED = "REPORTED"
    INDEMNIFIED = "INDEMNIFIED"
    VOID = "VOID"


class UnitStatus(str, Enum):
    PENDING = "PENDING"
    REPORTED = "REPORTED"
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"
    VOID = "VOID"


class AcreageReportStatus(str, Enum):
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class LossClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class PreventedPlantingClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class AgentCommissionStatus(str, Enum):
    EARNED = "EARNED"
    CLAWED_BACK = "CLAWED_BACK"


class PlanType(str, Enum):
    YP = "YP"
    RP = "RP"
    RP_HPE = "RP_HPE"


class PreventedPlantingCause(str, Enum):
    EXCESS_MOISTURE = "EXCESS_MOISTURE"
    DROUGHT = "DROUGHT"
    FLOOD = "FLOOD"
    OTHER = "OTHER"


class AgentRoleKind(str, Enum):
    SELLING = "SELLING"
    ADJUSTING = "ADJUSTING"


class UserRole(str, Enum):
    RMA_ADMIN = "RmaAdmin"
    AGENT = "Agent"
    LOSS_ADJUSTER = "LossAdjuster"


# ─── Entities carrying the uniform system field set ───────────────────────

class CommodityProgram(TypedDict):
    id: str
    crop_code: str
    county_code: str
    crop_year: int
    projected_price: float
    harvest_price: Optional[float]
    base_premium_rate: float
    pp_coverage_factor: float
    final_planting_date: str
    acreage_reporting_deadline: str
    harvest_price_published: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    producer_id: str
    agent_id: str
    crop_year: int
    total_premium_cents: int
    producer_premium_cents: int
    subsidy_cents: int
    total_indemnity_cents: int
    total_insured_acres: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CoverageElection(TypedDict):
    id: str
    policy_id: str
    commodity_program_id: str
    plan_type: str
    aph_yield: float
    coverage_level: float
    yield_guarantee_bu: float
    dollar_liability_per_acre_cents: int
    total_premium_cents: int
    subsidy_factor: float
    subsidy_cents: int
    producer_premium_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    coverage_election_id: str
    unit_number: str
    acres: float
    share: float
    planted_acres: float
    prevented_acres: float
    status: str
    created_at: str
    updated_at: str
    version: int


class AcreageReport(TypedDict):
    id: str
    unit_id: str
    planted_acres: float
    prevented_acres: float
    planting_date: Optional[str]
    late_planted: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class LossClaim(TypedDict):
    id: str
    unit_id: str
    harvest_date: str
    production_to_count_bu: float
    assigned_adjuster_id: Optional[str]
    indemnity_cents: int
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PreventedPlantingClaim(TypedDict):
    id: str
    unit_id: str
    claimed_prevented_acres: float
    cause: str
    pp_indemnity_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AgentCommission(TypedDict):
    id: str
    agent_id: str
    coverage_election_id: str
    commission_rate: float
    commission_cents: int
    clawback_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Identity entities — id + created_at only (no updated_at, no version) ──

class Producer(TypedDict):
    id: str
    name: str
    tax_id: str
    created_at: str


class Agent(TypedDict):
    id: str
    name: str
    license_number: str
    role_kind: str
    created_at: str
