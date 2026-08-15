"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    ADVISOR = "Advisor"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CLIENT = "Client"
    COMMITTEE_MEMBER = "CommitteeMember"
    COMMITTEE_CHAIR = "CommitteeChair"
    PLATFORM_ADMIN = "PlatformAdmin"


class ClientStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class BenchmarkStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class IpsStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_COMPLIANCE = "PENDING_COMPLIANCE"
    PENDING_CLIENT = "PENDING_CLIENT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class AssetClass(str, Enum):
    US_EQUITY = "US_EQUITY"
    INTL_EQUITY = "INTL_EQUITY"
    FIXED_INCOME = "FIXED_INCOME"
    CASH_EQUIVALENT = "CASH_EQUIVALENT"
    ALTERNATIVES = "ALTERNATIVES"


class PortfolioLifecycle(str, Enum):
    OPEN = "OPEN"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class DriftStatus(str, Enum):
    WITHIN_BANDS = "WITHIN_BANDS"
    BREACHED = "BREACHED"
    UNTRACKED = "UNTRACKED"


class TaxStatus(str, Enum):
    TAXABLE = "TAXABLE"
    TAX_DEFERRED = "TAX_DEFERRED"
    TAX_EXEMPT = "TAX_EXEMPT"


class TradingStatus(str, Enum):
    LISTED = "LISTED"
    HALTED = "HALTED"
    DELISTED = "DELISTED"


class CashFlowKind(str, Enum):
    MANUAL_DEPOSIT = "MANUAL_DEPOSIT"
    MANUAL_WITHDRAWAL = "MANUAL_WITHDRAWAL"
    TRADE_EXECUTION = "TRADE_EXECUTION"
    TRADE_VOID = "TRADE_VOID"
    WITHDRAWAL_DISBURSEMENT = "WITHDRAWAL_DISBURSEMENT"
    SETTLEMENT_PROCEEDS = "SETTLEMENT_PROCEEDS"


class CashFlowSourceType(str, Enum):
    MANUAL = "MANUAL"
    TRADE = "TRADE"
    WITHDRAWAL = "WITHDRAWAL"


class RestrictionLevel(str, Enum):
    NO_BUY = "NO_BUY"
    NO_TRADE = "NO_TRADE"


class RestrictionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class TriggerType(str, Enum):
    DRIFT_BREACH = "DRIFT_BREACH"
    CASH_FLOW = "CASH_FLOW"
    MANUAL = "MANUAL"


class ProposalStatus(str, Enum):
    PROPOSED = "PROPOSED"
    NEEDS_REVISION = "NEEDS_REVISION"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class TradeSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class TradeStatus(str, Enum):
    PENDING = "PENDING"
    BLOCKED = "BLOCKED"
    EXECUTED = "EXECUTED"
    VOIDED = "VOIDED"
    CANCELLED = "CANCELLED"


class FundingMode(str, Enum):
    CASH_FIRST = "CASH_FIRST"
    PRO_RATA = "PRO_RATA"
    TAX_AWARE = "TAX_AWARE"


class WithdrawalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    MODELED = "MODELED"
    APPROVED = "APPROVED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class CalculationMethod(str, Enum):
    TIME_WEIGHTED = "TIME_WEIGHTED"
    MONEY_WEIGHTED = "MONEY_WEIGHTED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class AmendmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    QUORUM_REACHED = "QUORUM_REACHED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class VoteDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class MinuteStatus(str, Enum):
    DRAFT = "DRAFT"
    RATIFIED = "RATIFIED"


class CashDirection(str, Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"


# --- Entity payloads (common_fields: id + created_at + updated_at + version) ---

class Client(TypedDict, total=False):
    id: str
    full_name: str
    risk_tolerance_score: int
    status: str
    total_aum_cents: int
    created_at: str
    updated_at: str
    version: int


class Benchmark(TypedDict, total=False):
    id: str
    name: str
    description: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InvestmentPolicyStatement(TypedDict, total=False):
    id: str
    client_id: str
    benchmark_id: str
    objective_text: str
    risk_tolerance_score: int
    review_cadence_months: int
    status: str
    activated_at: Optional[str]
    next_review_due: Optional[str]
    review_overdue: bool
    supersedes_ips_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AllocationTarget(TypedDict, total=False):
    id: str
    ips_id: str
    asset_class: str
    target_pct: float
    band_pct: float
    created_at: str
    updated_at: str
    version: int


class Portfolio(TypedDict, total=False):
    id: str
    client_id: str
    name: str
    tax_status: str
    lifecycle_status: str
    drift_status: str
    cash_balance_cents: int
    total_value_cents: int
    lifetime_realized_gains_cents: int
    created_at: str
    updated_at: str
    version: int


class Security(TypedDict, total=False):
    id: str
    ticker: str
    asset_class: str
    price_cents: int
    trading_status: str
    created_at: str
    updated_at: str
    version: int


class Position(TypedDict, total=False):
    id: str
    portfolio_id: str
    security_id: str
    quantity: int
    cost_basis_cents: int
    market_value_cents: int
    unrealized_gain_cents: int
    created_at: str
    updated_at: str
    version: int


class CashFlowEvent(TypedDict, total=False):
    # Append-only ledger entry: id + created_at only from the standard set
    # (PRD §2.4) — NO updated_at, NO version.
    id: str
    portfolio_id: str
    occurred_at: str
    kind: str
    amount_cents: int
    balance_after_cents: int
    valuation_before_cents: int
    source_type: str
    source_id: Optional[str]
    created_at: str


class RestrictedListEntry(TypedDict, total=False):
    id: str
    security_id: str
    restriction_level: str
    effective_from: str
    effective_to: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RebalanceProposal(TypedDict, total=False):
    id: str
    portfolio_id: str
    trigger_type: str
    status: str
    ips_id: str
    pinned_ips_version: int
    generated_at: str
    expires_at: str
    total_buys_cents: int
    total_sells_cents: int
    est_tax_reserve_cents: int
    cash_delta_cents: int
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TradeInstruction(TypedDict, total=False):
    id: str
    proposal_id: str
    security_id: str
    side: str
    quantity: int
    pinned_price_cents: int
    est_proceeds_cents: int
    est_tax_impact_cents: int
    status: str
    executed_at: Optional[str]
    executed_price_cents: Optional[int]
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ModeledLot(TypedDict, total=False):
    position_id: str
    security_id: str
    quantity: int
    est_proceeds_cents: int
    est_gain_cents: int


class WithdrawalRequest(TypedDict, total=False):
    id: str
    portfolio_id: str
    amount_cents: int
    funding_mode: str
    status: str
    modeled_at: Optional[str]
    modeled_plan: List[ModeledLot]
    modeled_proceeds_cents: int
    modeled_tax_cost_cents: int
    modeled_cash_used_cents: int
    post_withdrawal_drift_status: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerformanceReport(TypedDict, total=False):
    id: str
    portfolio_id: str
    benchmark_id: str
    period_start: str
    period_end: str
    calculation_method: str
    beginning_value_cents: int
    ending_value_cents: int
    benchmark_return_bps: int
    portfolio_return_bps: int
    excess_return_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VoterEntry(TypedDict, total=False):
    voter_user_id: str
    decision: str


class IPSAmendment(TypedDict, total=False):
    id: str
    ips_id: str
    proposed_objective_text: Optional[str]
    proposed_review_cadence_months: Optional[int]
    proposed_risk_tolerance_score: Optional[int]
    proposed_benchmark_id: Optional[str]
    proposed_by_user_id: str
    status: str
    approve_votes: int
    reject_votes: int
    voter_user_ids: List[VoterEntry]
    ratified_minute_id: Optional[str]
    finalized_by_user_id: Optional[str]
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommitteeMinute(TypedDict, total=False):
    id: str
    meeting_date: str
    amendment_refs: List[str]
    decisions_text: str
    recorded_by_user_id: str
    status: str
    ratified_by_user_id: Optional[str]
    ratified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
