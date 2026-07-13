"""Domain types: entity TypedDicts, status enums, role enum.

All names follow the PRD (Recycling MRF & Commodity Settlement).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Enumerations -----------------------------------------------------------

class UserRole(str, Enum):
    SCALE_OPERATOR = "ScaleOperator"
    SORT_MANAGER = "SortManager"
    COMMODITY_TRADER = "CommodityTrader"
    SETTLEMENT_CLERK = "SettlementClerk"
    MUNICIPALITY = "Municipality"


class Commodity(str, Enum):
    OCC = "OCC"
    MIXED_PAPER = "MIXED_PAPER"
    PET = "PET"
    HDPE = "HDPE"
    ALUMINUM = "ALUMINUM"
    STEEL = "STEEL"
    GLASS = "GLASS"


class QualityGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class MunicipalityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MillStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CommodityIndexStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class SortLineStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    DOWN = "DOWN"


class InboundLoadStatus(str, Enum):
    RECEIVED = "RECEIVED"
    AUDITED = "AUDITED"
    PENDING_REAUDIT = "PENDING_REAUDIT"
    CLOSED = "CLOSED"


class BaleStatus(str, Enum):
    BALED = "BALED"
    STAGED = "STAGED"
    SHIPPED = "SHIPPED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class MillShipmentStatus(str, Enum):
    BUILDING = "BUILDING"
    SHIPPED = "SHIPPED"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"


class MunicipalStatementStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class PostingType(str, Enum):
    REVENUE_SHARE = "REVENUE_SHARE"
    REBATE = "REBATE"
    PENALTY = "PENALTY"
    REVERSAL = "REVERSAL"


# --- Entity shapes ----------------------------------------------------------
# common_fields: true -> id + created_at + updated_at + version
# common_fields: false -> id + created_at only (append-only)

class Municipality(TypedDict):
    id: str
    name: str
    contact_email: Optional[str]
    revenue_share_pct: float
    status: str
    revenue_share_accrued_cents: int
    lifetime_rebate_cents: int
    lifetime_penalty_cents: int
    balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Mill(TypedDict):
    id: str
    name: str
    commodity_focus: str
    freight_rate_cents_per_ton: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CommodityIndex(TypedDict):
    id: str
    commodity: str
    price_cents_per_ton: int
    effective_start: str
    effective_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SortLine(TypedDict):
    id: str
    name: str
    rated_tph: float
    scheduled_shift_minutes: int
    status: str
    total_processed_tons: float
    total_downtime_minutes: int
    throughput_tph: float
    created_at: str
    updated_at: str
    version: int


class DowntimeEvent(TypedDict):
    id: str
    sort_line_id: str
    start_at: str
    end_at: str
    reason: str
    downtime_minutes: int
    created_at: str
    updated_at: str
    version: int


class InboundLoad(TypedDict):
    id: str
    source_municipality_id: str
    sort_line_id: str
    hauler: str
    gross_tons: float
    tare_tons: float
    net_tons: float
    sampled_contamination_pct: Optional[float]
    audited_composition: Optional[list]
    provisional_adjustment_cents: int
    residual_tons: float
    final_adjustment_cents: int
    baled_tons: float
    unbaled_remaining_tons: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Bale(TypedDict):
    id: str
    source_load_id: str
    shipment_id: Optional[str]
    commodity: str
    net_tons: float
    moisture_pct: float
    quality_grade: str
    index_price_snapshot_cents: int
    provisional_value_cents: int
    final_value_cents: int
    freight_share_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MillShipment(TypedDict):
    id: str
    mill_id: str
    commodity: str
    freight_cost_cents: int
    total_net_tons: float
    gross_settlement_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MunicipalStatement(TypedDict):
    id: str
    municipality_id: str
    period_start: str
    period_end: str
    total_revenue_share_cents: int
    total_rebate_cents: int
    total_penalty_cents: int
    net_payable_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RevenueSharePosting(TypedDict):
    id: str
    municipality_id: str
    posting_type: str
    amount_cents: int
    related_bale_id: Optional[str]
    related_load_id: Optional[str]
    reversed: bool
    created_at: str
