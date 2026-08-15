"""Domain types: entity TypedDicts, status enums, role enum.

Money is integer micros; rates are integer basis points. Dates are
YYYY-MM-DD; datetimes are ISO 8601 UTC.

SupplyChainNode and AuctionRecord are ledger-style resources that carry
only ``id`` and ``created_at`` — both ``updated_at`` and ``version`` are
absent from them (PRD: common resource properties), so their TypedDicts
omit those fields.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    EXCHANGE_ADMIN = "ExchangeAdmin"
    PUBLISHER_MANAGER = "PublisherManager"
    DEMAND_SIDE = "DemandSide"
    FINANCE_OFFICER = "FinanceOfficer"


class PaymentTerms(str, Enum):
    SEQUENTIAL_LIABILITY = "SEQUENTIAL_LIABILITY"
    GUARANTEED = "GUARANTEED"


class PublisherStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DemandPartnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    THROTTLED = "THROTTLED"
    SUSPENDED = "SUSPENDED"


class AdFormat(str, Enum):
    DISPLAY = "DISPLAY"
    VIDEO = "VIDEO"
    NATIVE = "NATIVE"
    AUDIO = "AUDIO"


class PackageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class DealType(str, Enum):
    PMP_STANDARD = "PMP_STANDARD"
    PMP_EXCLUSIVE = "PMP_EXCLUSIVE"
    PREFERRED = "PREFERRED"
    PROGRAMMATIC_GUARANTEED = "PROGRAMMATIC_GUARANTEED"


class AuctionType(str, Enum):
    FIRST_PRICE = "FIRST_PRICE"
    SECOND_PRICE = "SECOND_PRICE"


class DealStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    RENEGOTIATING = "RENEGOTIATING"
    PAUSED = "PAUSED"
    EXPIRED = "EXPIRED"


class BlocklistScope(str, Enum):
    EXCHANGE = "EXCHANGE"
    PUBLISHER = "PUBLISHER"
    DEAL = "DEAL"


class BlocklistRuleType(str, Enum):
    ADVERTISER_DOMAIN = "ADVERTISER_DOMAIN"
    CATEGORY = "CATEGORY"


class BlocklistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class ReportStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"


class ResolutionType(str, Enum):
    ACCEPT_SSP = "ACCEPT_SSP"
    ACCEPT_DSP = "ACCEPT_DSP"
    MAKE_GOOD = "MAKE_GOOD"


class BatchStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"
    SETTLED = "SETTLED"


class LineStatus(str, Enum):
    PENDING = "PENDING"
    HELD = "HELD"
    ELIGIBLE = "ELIGIBLE"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Publisher(TypedDict):
    id: str
    name: str
    domain: str
    payment_terms: str
    status: str
    lifetime_net_micros: int
    accrued_open_micros: int
    paid_out_micros: int
    written_off_micros: int
    active_package_count: int
    created_at: str
    updated_at: str
    version: int


class DemandPartner(TypedDict):
    id: str
    name: str
    seat_id: str
    max_qps: int
    daily_cap_micros: int
    status: str
    spend_today_micros: int
    current_second_auction_count: int
    lifetime_spend_micros: int
    created_at: str
    updated_at: str
    version: int


class InventoryPackage(TypedDict):
    id: str
    publisher_id: str
    name: str
    ad_format: str
    category_tags: List[str]
    base_floor_cpm_micros: int
    status: str
    active_deal_count: int
    current_seasonal_multiplier_bps: int
    effective_floor_cpm_micros: int
    created_at: str
    updated_at: str
    version: int


class SeasonalPricingWindow(TypedDict):
    id: str
    package_id: str
    name: str
    start_date: str
    end_date: str
    multiplier_bps: int
    is_currently_applied: bool
    created_at: str
    updated_at: str
    version: int


class Deal(TypedDict):
    id: str
    package_id: str
    publisher_id: str
    demand_partner_id: str
    deal_type: str
    is_exclusive: bool
    auction_type: str
    floor_cpm_micros: int
    start_at: str
    end_at: str
    committed_impressions: Optional[int]
    delivered_impressions: int
    remaining_committed_impressions: Optional[int]
    approved_floor_cpm_micros: Optional[int]
    status: str
    renegotiation_count: int
    created_at: str
    updated_at: str
    version: int


class SupplyChainNode(TypedDict):
    # Ledger-style resource: carries ONLY id + created_at (no updated_at,
    # no version).
    id: str
    package_id: str
    parent_node_id: Optional[str]
    seller_domain: str
    fee_bps: int
    hop_index: int
    is_tail: bool
    created_at: str


class BlocklistEntry(TypedDict):
    id: str
    scope: str
    publisher_id: Optional[str]
    deal_id: Optional[str]
    rule_type: str
    value: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AuctionRecord(TypedDict):
    # Ledger-style resource: carries ONLY id + created_at (no updated_at,
    # no version).
    id: str
    deal_id: str
    publisher_id: str
    demand_partner_id: str
    auction_type: str
    winning_bid_cpm_micros: int
    clearing_cpm_micros: int
    impressions: int
    creative_domain: str
    gross_micros: int
    exchange_fee_micros: int
    supply_fee_micros: int
    publisher_net_micros: int
    dsp_fee_micros: int
    dsp_billed_micros: int
    dsp_confirmed_at: Optional[str]
    voided: bool
    voided_at: Optional[str]
    created_at: str


class ReconciliationReport(TypedDict):
    id: str
    deal_id: str
    period_start: str
    period_end: str
    ssp_impressions: int
    ssp_spend_micros: int
    dsp_impressions: int
    dsp_billed_micros: int
    discrepancy_pct: float
    auto_flagged: bool
    status: str
    resolution_type: Optional[str]
    adjustment_micros: Optional[int]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayoutBatch(TypedDict):
    id: str
    period_start: str
    period_end: str
    status: str
    created_by_user_id: str
    line_count: int
    total_gross_micros: int
    total_payable_micros: int
    created_at: str
    updated_at: str
    version: int


class PayoutLine(TypedDict):
    id: str
    batch_id: str
    publisher_id: str
    status: str
    gross_micros: int
    confirmed_micros: int
    unconfirmed_micros: int
    adjustment_micros: int
    payable_micros: int
    paid_micros: Optional[int]
    written_off_amount_micros: Optional[int]
    write_off_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
