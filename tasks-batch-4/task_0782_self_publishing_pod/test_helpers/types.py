"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system are full first-class resources: each carries id,
created_at, updated_at, and an integer version (see PRD 2.4), so every TypedDict
below includes those four common fields.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PUBLISHER = "Publisher"
    REVIEWER = "Reviewer"
    PLATFORM_ADMIN = "PlatformAdmin"


class PublisherStatus(str, Enum):
    ACTIVE = "ACTIVE"


class PayoutMethod(str, Enum):
    BANK = "BANK"
    PAYPAL = "PAYPAL"


class TitleStatus(str, Enum):
    DRAFT = "DRAFT"
    LIVE = "LIVE"
    UNLISTED = "UNLISTED"


class FormatType(str, Enum):
    PRINT = "PRINT"
    EBOOK = "EBOOK"
    AUDIO = "AUDIO"


class FormatStatus(str, Enum):
    DRAFT = "DRAFT"
    CONTENT_LOCKED = "CONTENT_LOCKED"
    PUBLISHED = "PUBLISHED"
    UNLISTED = "UNLISTED"


class AssetType(str, Enum):
    INTERIOR = "INTERIOR"
    COVER = "COVER"


class AssetStatus(str, Enum):
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class IsbnStatus(str, Enum):
    FREE = "FREE"
    ASSIGNED = "ASSIGNED"
    LOCKED = "LOCKED"


class ChannelType(str, Enum):
    RETAIL = "RETAIL"
    LIBRARY = "LIBRARY"
    DIRECT = "DIRECT"


class Territory(str, Enum):
    US = "US"
    UK = "UK"
    EU = "EU"
    ROW = "ROW"


class ChannelPriceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ProofStatus(str, Enum):
    ORDERED = "ORDERED"
    APPROVED = "APPROVED"
    REVISION_REQUESTED = "REVISION_REQUESTED"


class DistributionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    LIVE = "LIVE"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class SalesLineType(str, Enum):
    SALE = "SALE"
    RETURN = "RETURN"


class SalesLineStatus(str, Enum):
    PENDING = "PENDING"
    STATEMENTED = "STATEMENTED"


class StatementStatus(str, Enum):
    ACCRUING = "ACCRUING"
    ISSUED = "ISSUED"
    PAID = "PAID"


class Publisher(TypedDict):
    id: str
    name: str
    email: str
    payout_method: str
    reserve_held_cents: int
    lifetime_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Title(TypedDict):
    id: str
    publisher_id: str
    title: str
    subtitle: Optional[str]
    language: str
    bisac_category: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Format(TypedDict):
    id: str
    title_id: str
    format_type: str
    trim_size: Optional[str]
    interior_color: Optional[str]
    page_count: Optional[int]
    file_size_mb: Optional[float]
    isbn_id: Optional[str]
    print_cost_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict):
    id: str
    format_id: str
    asset_type: str
    file_ref: str
    file_format: str
    declared_page_count: Optional[int]
    paper_type: Optional[str]
    declared_spine_mm: Optional[float]
    spine_width_mm: Optional[float]
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Isbn(TypedDict):
    id: str
    publisher_id: str
    isbn_13: str
    assigned_format_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Channel(TypedDict):
    id: str
    name: str
    channel_type: str
    supports_formats: list
    ebook_high_rate: Optional[float]
    ebook_low_rate: Optional[float]
    ebook_rate_low_threshold_cents: Optional[int]
    ebook_rate_high_threshold_cents: Optional[int]
    delivery_fee_per_mb_cents: int
    distribution_discount_standard: float
    distribution_discount_expanded: float
    returns_reserve_pct: float
    min_list_price_cents: int
    max_list_price_cents: int
    created_at: str
    updated_at: str
    version: int


class ChannelPrice(TypedDict):
    id: str
    format_id: str
    channel_id: str
    territory: str
    list_price_cents: int
    currency: str
    effective_from: str
    effective_to: Optional[str]
    expanded_reach: bool
    royalty_per_unit_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Proof(TypedDict):
    id: str
    format_id: str
    round_number: int
    revision_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionRequest(TypedDict):
    id: str
    format_id: str
    channel_id: str
    territory: str
    expanded_reach: bool
    reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesLine(TypedDict):
    id: str
    format_id: str
    channel_id: str
    territory: str
    units: int
    line_type: str
    sale_date: str
    royalty_per_unit_cents: int
    gross_royalty_cents: int
    reserve_held_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RoyaltyStatement(TypedDict):
    id: str
    publisher_id: str
    period_start: str
    period_end: str
    gross_royalty_cents: int
    reserve_held_cents: int
    reserve_released_cents: int
    provisional_net_cents: int
    net_payable_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
