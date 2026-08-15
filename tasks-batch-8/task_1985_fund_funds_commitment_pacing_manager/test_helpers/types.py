"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.7, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class Posture(str, Enum):
    NORMAL = "NORMAL"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class ManagerStatus(str, Enum):
    PROSPECT = "PROSPECT"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    EXITED = "EXITED"


class VehicleStatus(str, Enum):
    SCREENING = "SCREENING"
    IN_DILIGENCE = "IN_DILIGENCE"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    CLOSED_TO_NEW = "CLOSED_TO_NEW"


class ReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    RECOMMENDED = "RECOMMENDED"
    IC_APPROVED = "IC_APPROVED"
    IC_REJECTED = "IC_REJECTED"
    WITHDRAWN = "WITHDRAWN"


class CommitmentStatus(str, Enum):
    PENDING_DOCS = "PENDING_DOCS"
    EXECUTED = "EXECUTED"
    REDUCED = "REDUCED"
    CANCELLED = "CANCELLED"


class CallStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"


class DistributionStatus(str, Enum):
    PENDING = "PENDING"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class BidStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class SnapshotStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    RESTATED = "RESTATED"


class ReportStatus(str, Enum):
    OPEN = "OPEN"
    PUBLISHED = "PUBLISHED"
    RESTATED = "RESTATED"


class StaffRole(str, Enum):
    ANALYST = "ANALYST"
    IC_MEMBER = "IC_MEMBER"
    OPS_ANALYST = "OPS_ANALYST"


class Strategy(str, Enum):
    BUYOUT = "BUYOUT"
    VENTURE = "VENTURE"
    GROWTH = "GROWTH"
    CREDIT = "CREDIT"
    REAL_ASSETS = "REAL_ASSETS"
    SECONDARIES = "SECONDARIES"


class LedgerEntryKind(str, Enum):
    CONTRIBUTION = "CONTRIBUTION"
    CAPITAL_CALL_PAYMENT = "CAPITAL_CALL_PAYMENT"
    DISTRIBUTION_RECEIPT = "DISTRIBUTION_RECEIPT"
    SECONDARY_SETTLEMENT_OUT = "SECONDARY_SETTLEMENT_OUT"
    SECONDARY_SETTLEMENT_IN = "SECONDARY_SETTLEMENT_IN"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"


class CallPurpose(str, Enum):
    INVESTMENT = "INVESTMENT"
    FEES = "FEES"
    EXPENSES = "EXPENSES"


class DistributionType(str, Enum):
    RETURN_OF_CAPITAL = "RETURN_OF_CAPITAL"
    GAIN = "GAIN"
    INCOME = "INCOME"


class BidSide(str, Enum):
    PURCHASE = "PURCHASE"
    SALE = "SALE"


class Sector(str, Enum):
    TECH = "TECH"
    HEALTHCARE = "HEALTHCARE"
    INDUSTRIALS = "INDUSTRIALS"
    CONSUMER = "CONSUMER"
    FINANCIALS = "FINANCIALS"
    ENERGY = "ENERGY"
    OTHER = "OTHER"


class Geography(str, Enum):
    NA = "NA"
    EU = "EU"
    APAC = "APAC"
    LATAM = "LATAM"
    MEA = "MEA"


class UserRole(str, Enum):
    CIO = "CIO"
    ANALYST = "Analyst"
    IC = "InvestmentCommittee"
    OPS = "OperationsAnalyst"
    COMPLIANCE = "ComplianceOfficer"


# ---------------------------------------------------------------------------
# Entity TypedDicts. Primary resources carry id/created_at/updated_at/version
# (PRD §2.7); CashLedgerEntry, LookThroughLine, and StaffUser are append-only
# and carry only id + created_at.
# ---------------------------------------------------------------------------


class FoFProgram(TypedDict, total=False):
    id: str
    program_name: str
    base_currency: str
    total_nav_budget: float
    strategy_cap_pct: float
    manager_cap_pct: float
    max_vintage_band_years: int
    liquidity_buffer_min: float
    overdue_grace_days: int
    secondary_premium_cap_pct: float
    secondary_discount_cap_pct: float
    status: str
    unrestricted_cash: float
    committed_total: float
    deployed_total: float
    returned_total: float
    unfunded_total: float
    secondary_purchase_unfunded_total: float
    posture: str
    created_at: str
    updated_at: str
    version: int


class PacingPlan(TypedDict, total=False):
    id: str
    program_id: str
    plan_label: str
    horizon_years: int
    start_vintage_year: int
    target_strategy_mix: List[Dict[str, Any]]
    status: str
    target_commit_by_year: List[Dict[str, Any]]
    projected_total_commit: float
    created_at: str
    updated_at: str
    version: int


class Manager(TypedDict, total=False):
    id: str
    legal_name: str
    domicile_country: str
    relationship_since_year: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FundVehicle(TypedDict, total=False):
    id: str
    manager_id: str
    fund_name: str
    strategy: str
    vintage_year: int
    fund_size_target: float
    mgmt_fee_rate_early: float
    mgmt_fee_rate_late: float
    investment_period_years: int
    carry_rate: float
    hurdle_rate: float
    status: str
    created_at: str
    updated_at: str
    version: int


class DueDiligenceReview(TypedDict, total=False):
    id: str
    vehicle_id: str
    round_index: int
    score_strategy_fit: float
    score_track_record: float
    score_operations: float
    score_compliance: float
    composite_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


class InvestmentProposal(TypedDict, total=False):
    id: str
    vehicle_id: str
    program_id: str
    pacing_plan_id: str
    proposed_amount: float
    recommended_by_analyst_id: str
    concentration_strategy_pct: float
    concentration_manager_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Commitment(TypedDict, total=False):
    id: str
    program_id: str
    vehicle_id: str
    proposal_id: Optional[str]
    sized_amount: float
    unfunded_amount: float
    status: str
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CapitalCall(TypedDict, total=False):
    id: str
    commitment_id: str
    program_id: str
    call_number: int
    amount: float
    purpose: str
    issued_on: str
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Distribution(TypedDict, total=False):
    id: str
    commitment_id: str
    program_id: str
    amount: float
    distribution_type: str
    received_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CashLedgerEntry(TypedDict, total=False):
    # Append-only audit row: id + created_at only (PRD §2.7).
    id: str
    program_id: str
    entry_kind: str
    amount: float
    ref_entity: Optional[str]
    ref_id: Optional[str]
    note: Optional[str]
    balance_after: float
    created_at: str


class SecondaryBid(TypedDict, total=False):
    id: str
    program_id: str
    vehicle_id: str
    side: str
    nav_basis: float
    price: float
    unfunded_assumed: float
    pricing_deviation_pct: float
    linked_commitment_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HoldingSnapshot(TypedDict, total=False):
    id: str
    commitment_id: str
    vehicle_id: str
    as_of_quarter: str
    reported_nav: float
    reported_at: str
    is_final: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class LookThroughLine(TypedDict, total=False):
    # Append-only audit row: id + created_at only (PRD §2.7).
    id: str
    snapshot_id: str
    sector: str
    geography: str
    exposure_amount: float
    created_at: str


class ValuationReport(TypedDict, total=False):
    id: str
    program_id: str
    as_of_quarter: str
    nav_provisional: float
    nav_final: float
    nav_reported: float
    irr_provisional_pct: float
    irr_final_pct: float
    total_fee_burden_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class StaffUser(TypedDict, total=False):
    # Staff appointment row: id + created_at only (PRD §2.7).
    id: str
    display_name: str
    staff_role: str
    email: str
    created_at: str
