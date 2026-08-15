"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class ParticipantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MARGIN_CALL = "MARGIN_CALL"
    SUSPENDED = "SUSPENDED"


class CreditRatingTier(str, Enum):
    INVESTMENT_GRADE = "INVESTMENT_GRADE"
    BELOW_INVESTMENT_GRADE = "BELOW_INVESTMENT_GRADE"


class GeneratorStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_OUTAGE = "ON_OUTAGE"
    DECOMMISSIONED = "DECOMMISSIONED"


class OperatingDayStatus(str, Enum):
    DA_OPEN = "DA_OPEN"
    DA_GATED = "DA_GATED"
    RT_COMPLETE = "RT_COMPLETE"
    PRELIM_SETTLED = "PRELIM_SETTLED"
    FINAL_SETTLED = "FINAL_SETTLED"
    CLOSED = "CLOSED"


class OfferStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    CLEARED = "CLEARED"
    NOT_CLEARED = "NOT_CLEARED"


class TelemetryStatus(str, Enum):
    RECORDED = "RECORDED"
    SUPERSEDED = "SUPERSEDED"


class OutageStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class OutageType(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"


class StatementRunType(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    FINAL = "FINAL"
    RESETTLEMENT = "RESETTLEMENT"


class StatementStatus(str, Enum):
    ISSUED = "ISSUED"
    UNDER_DISPUTE = "UNDER_DISPUTE"
    SUPERSEDED = "SUPERSEDED"
    CLOSED = "CLOSED"
    PAID = "PAID"


class ChargeType(str, Enum):
    DA_ENERGY_CREDIT = "DA_ENERGY_CREDIT"
    RT_IMBALANCE = "RT_IMBALANCE"
    CONGESTION = "CONGESTION"
    LOSSES = "LOSSES"
    ANCILLARY = "ANCILLARY"
    CAPACITY = "CAPACITY"


class DisputeReason(str, Enum):
    PRICE_ERROR = "PRICE_ERROR"
    METER_DATA_ERROR = "METER_DATA_ERROR"
    CALCULATION_ERROR = "CALCULATION_ERROR"
    MISSING_ANCILLARY_CREDIT = "MISSING_ANCILLARY_CREDIT"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ServiceType(str, Enum):
    REGULATION = "REGULATION"
    SYNC_RESERVE = "SYNC_RESERVE"
    SUPPLEMENTAL_RESERVE = "SUPPLEMENTAL_RESERVE"


class AwardStatus(str, Enum):
    AWARDED = "AWARDED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class ObligationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    AT_RISK = "AT_RISK"
    CLOSED = "CLOSED"


class EventStatus(str, Enum):
    DECLARED = "DECLARED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class InstrumentType(str, Enum):
    CASH = "CASH"
    LETTER_OF_CREDIT = "LETTER_OF_CREDIT"


class PostingStatus(str, Enum):
    POSTED = "POSTED"
    RELEASED = "RELEASED"
    DRAWN = "DRAWN"


class MarginCallStatus(str, Enum):
    OPEN = "OPEN"
    CURED = "CURED"
    DEFAULTED = "DEFAULTED"


class UserRole(str, Enum):
    TRADER = "Trader"
    SETTLEMENT_ANALYST = "SettlementAnalyst"
    CREDIT_OFFICER = "CreditOfficer"
    ISO_OPERATOR = "IsoOperator"


class MarketParticipant(TypedDict, total=False):
    id: str
    company_name: str
    credit_rating_tier: str
    status: str
    posted_collateral_cents: int
    collateral_requirement_cents: int
    unsecured_allowance_cents: int
    created_at: str
    updated_at: str
    version: int


class GeneratorAsset(TypedDict, total=False):
    id: str
    market_participant_id: str
    unit_name: str
    pricing_node: str
    capacity_mw: float
    availability_mw: float
    status: str
    created_at: str
    updated_at: str
    version: int


class OperatingDay(TypedDict, total=False):
    id: str
    market_date: str
    da_gate_close_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PriceNode(TypedDict, total=False):
    id: str
    operating_day_id: str
    node_name: str
    da_energy_cents_per_mwh: int
    da_congestion_cents_per_mwh: int
    da_loss_cents_per_mwh: int
    rt_prelim_energy_cents_per_mwh: int
    rt_prelim_congestion_cents_per_mwh: int
    rt_prelim_loss_cents_per_mwh: int
    rt_final_energy_cents_per_mwh: int
    rt_final_congestion_cents_per_mwh: int
    rt_final_loss_cents_per_mwh: int
    created_at: str
    updated_at: str
    version: int


class DayAheadOffer(TypedDict, total=False):
    id: str
    operating_day_id: str
    generator_asset_id: str
    offered_mw: float
    offer_price_cents_per_mwh: int
    status: str
    cleared_mw: float
    da_lmp_cents_per_mwh: int
    created_at: str
    updated_at: str
    version: int


class RealTimeTelemetry(TypedDict, total=False):
    id: str
    generator_asset_id: str
    operating_day_id: str
    interval_index: int
    actual_mw: float
    status: str
    created_at: str
    updated_at: str
    version: int


class OutageReport(TypedDict, total=False):
    id: str
    generator_asset_id: str
    outage_type: str
    derate_pct: int
    start_at: str
    end_at: str
    reason: str
    denial_reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SettlementStatement(TypedDict, total=False):
    id: str
    market_participant_id: str
    operating_day_id: str
    run_type: str
    status: str
    da_energy_credit_cents: int
    imbalance_charge_cents: int
    congestion_charge_cents: int
    loss_charge_cents: int
    ancillary_revenue_cents: int
    capacity_charge_cents: int
    net_amount_cents: int
    paid_cents: int
    issued_at: str
    dispute_window_ends_at: str
    supersedes_statement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SettlementLine(TypedDict, total=False):
    id: str
    settlement_statement_id: str
    generator_asset_id: str
    charge_type: str
    mw_quantity: float
    amount_cents: int
    created_at: str
    updated_at: str
    version: int


class SettlementDispute(TypedDict, total=False):
    id: str
    settlement_statement_id: str
    market_participant_id: str
    dispute_reason: str
    disputed_line_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AncillaryServiceAward(TypedDict, total=False):
    id: str
    generator_asset_id: str
    operating_day_id: str
    service_type: str
    awarded_mw: float
    capacity_price_cents: int
    performance_price_cents: int
    mileage_ratio: float
    start_interval: int
    end_interval: int
    performance_score: float
    revenue_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CapacityObligation(TypedDict, total=False):
    id: str
    generator_asset_id: str
    delivery_period: str
    obligated_mw: float
    capacity_rate_cents_per_mw: int
    expected_output_mw: float
    accrued_penalty_cents: int
    accrued_bonus_cents: int
    gross_revenue_cents: int
    charged_penalty_cents: int
    forgiven_penalty_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CapacityPerformanceEvent(TypedDict, total=False):
    id: str
    operating_day_id: str
    start_interval: int
    end_interval: int
    penalties_collected_cents: int
    bonuses_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CollateralPosting(TypedDict, total=False):
    id: str
    market_participant_id: str
    amount_cents: int
    instrument_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MarginCall(TypedDict, total=False):
    id: str
    market_participant_id: str
    required_additional_cents: int
    due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
