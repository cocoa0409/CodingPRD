"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    COMMODITY_ADVISOR = "CommodityAdvisor"
    GROWER = "Grower"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class Commodity(str, Enum):
    CORN = "CORN"
    SOYBEAN = "SOYBEAN"
    WHEAT = "WHEAT"


class RiskProfile(str, Enum):
    CONSERVATIVE = "CONSERVATIVE"
    BALANCED = "BALANCED"
    AGGRESSIVE = "AGGRESSIVE"


class YieldMethod(str, Enum):
    APH = "APH"
    TREND = "TREND"


class BaselineStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"
    SUPERSEDED = "SUPERSEDED"


class PolicyStatus(str, Enum):
    QUOTED = "QUOTED"
    BOUND = "BOUND"
    CLAIM_SETTLED = "CLAIM_SETTLED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class TargetStatus(str, Enum):
    PENDING = "PENDING"
    TRIGGERED = "TRIGGERED"
    FILLED = "FILLED"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class RecommendationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"


class Instrument(str, Enum):
    FUTURES_SHORT = "FUTURES_SHORT"
    LONG_PUT = "LONG_PUT"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    OFFSET = "OFFSET"
    LIQUIDATED = "LIQUIDATED"


class MarginAccountStatus(str, Enum):
    FUNDED = "FUNDED"
    CALL_OUTSTANDING = "CALL_OUTSTANDING"
    RESTRICTED = "RESTRICTED"


class BuyerStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class BuyerType(str, Enum):
    ELEVATOR = "ELEVATOR"
    PROCESSOR = "PROCESSOR"
    EXPORTER = "EXPORTER"
    ETHANOL = "ETHANOL"


class CreditRating(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class ContractType(str, Enum):
    FLAT_PRICE = "FLAT_PRICE"
    HTA = "HTA"
    BASIS = "BASIS"


class PricingStatus(str, Enum):
    UNPRICED = "UNPRICED"
    PRICED = "PRICED"


class FulfillmentStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_DELIVERED = "PARTIALLY_DELIVERED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    DEFAULTED = "DEFAULTED"


class TicketStatus(str, Enum):
    RECORDED = "RECORDED"
    CONFIRMED = "CONFIRMED"
    VOIDED = "VOIDED"


class StorageLotStatus(str, Enum):
    STORED = "STORED"
    WITHDRAWN = "WITHDRAWN"


class FeeType(str, Enum):
    PER_BUSHEL = "PER_BUSHEL"
    FLAT_ANNUAL = "FLAT_ANNUAL"


class DisclosureStatus(str, Enum):
    NONE = "NONE"
    REQUIRED = "REQUIRED"
    DELIVERED = "DELIVERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    STALE = "STALE"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_SIGNATURE = "PENDING_SIGNATURE"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class TickKind(str, Enum):
    QUOTE = "QUOTE"
    SETTLEMENT = "SETTLEMENT"


class GrowerOperation(TypedDict, total=False):
    id: str
    name: str
    primary_commodity: str
    crop_year: int
    risk_profile: str
    yield_method: str
    over_sold_flag: bool
    created_at: str
    updated_at: str
    version: int


class ProductionBaseline(TypedDict, total=False):
    id: str
    operation_id: str
    planted_acres: int
    aph_yield_bushels: float
    trend_yield_bushels: float
    expected_bushels_aph: int
    expected_bushels_trend: int
    expected_bushels: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict, total=False):
    id: str
    operation_id: str
    baseline_id: str
    coverage_level_pct: float
    projected_price: float
    guarantee_bushels: int
    actual_harvested_bushels: int
    harvest_price: float
    indemnity_dollars: float
    status: str
    created_at: str
    updated_at: str
    version: int


class MarketingPlan(TypedDict, total=False):
    id: str
    operation_id: str
    baseline_id: str
    max_priced_pct: float
    expected_bushels_snapshot: int
    committed_contract_bushels: int
    uncommitted_bushels: int
    hedged_bushels: int
    priced_contract_bushels: int
    coverage_cap_bushels: int
    pending_recommendation_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PriceTarget(TypedDict, total=False):
    id: str
    plan_id: str
    contract_month: str
    target_price: float
    increment_bushels: int
    status: str
    recommendation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HedgeRecommendation(TypedDict, total=False):
    id: str
    plan_id: str
    price_target_id: Optional[str]
    instrument: str
    contract_month: str
    bushels: int
    strike_price: float
    premium_per_bushel: float
    rationale: str
    created_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BrokeragePosition(TypedDict, total=False):
    id: str
    recommendation_id: str
    operation_id: str
    margin_account_id: str
    instrument: str
    contract_month: str
    bushels: int
    entry_price: float
    exit_price: float
    initial_margin_dollars: float
    maintenance_margin_dollars: float
    unrealized_pnl: float
    realized_pnl: float
    status: str
    created_at: str
    updated_at: str
    version: int


class MarginAccount(TypedDict, total=False):
    id: str
    operation_id: str
    cash_balance: float
    initial_margin_required: float
    maintenance_margin_required: float
    margin_equity: float
    margin_call_amount: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Buyer(TypedDict, total=False):
    id: str
    name: str
    buyer_type: str
    credit_rating: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesContract(TypedDict, total=False):
    id: str
    operation_id: str
    plan_id: str
    buyer_id: str
    contract_type: str
    bushels: int
    fixed_price: float
    basis_level: float
    contract_month: str
    delivery_window_start: str
    delivery_window_end: str
    fixation_price: float
    effective_price: float
    delivered_bushels: int
    settled_value_dollars: float
    default_penalty_dollars: float
    pricing_status: str
    fulfillment_status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryTicket(TypedDict, total=False):
    id: str
    contract_id: str
    delivery_date: str
    gross_bushels: int
    moisture_pct: float
    shrink_pct: float
    net_bushels: float
    ticket_value_dollars: float
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageLot(TypedDict, total=False):
    id: str
    operation_id: str
    bin_id: str
    bushels: int
    start_date: str
    planned_end_date: str
    cost_per_bushel_month: float
    annual_interest_rate: float
    actual_end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AdvisoryAgreement(TypedDict, total=False):
    id: str
    operation_id: str
    fee_type: str
    rate_per_bushel: float
    flat_annual_fee: float
    annual_cap_dollars: float
    billable_bushels_accrued: int
    disclosure_status: str
    acknowledged_agreement_version: int
    submitted_by_user_id: str
    certified_by_user_id: str
    compliance_certified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class MarketTick(TypedDict, total=False):
    """Append-only price-feed record: carries only id + created_at."""
    id: str
    commodity: str
    contract_month: str
    price: float
    kind: str
    price_date: str
    created_at: str
