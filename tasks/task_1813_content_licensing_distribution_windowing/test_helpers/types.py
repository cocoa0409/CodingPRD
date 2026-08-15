"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Every entity in this system carries
the four server-managed common fields id + created_at + updated_at + version
(PRD section on common resource properties).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class ContentType(str, Enum):
    FILM = "FILM"
    SERIES = "SERIES"


class PlatformType(str, Enum):
    SVOD = "SVOD"
    AVOD = "AVOD"
    TVOD = "TVOD"
    EST = "EST"


class WindowType(str, Enum):
    THEATRICAL = "THEATRICAL"
    EST = "EST"
    TVOD = "TVOD"
    SVOD = "SVOD"
    AVOD = "AVOD"
    FREE_TV = "FREE_TV"


class SlotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ENCUMBERED = "ENCUMBERED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class PackageStatus(str, Enum):
    DRAFT = "DRAFT"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_ACCEPTED = "PARTIALLY_ACCEPTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class LineStatus(str, Enum):
    PENDING = "PENDING"
    OFFERED = "OFFERED"
    BLOCKED = "BLOCKED"
    LICENSED = "LICENSED"
    NOT_SELECTED = "NOT_SELECTED"


class LicenseStatus(str, Enum):
    EXECUTED = "EXECUTED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class FeeModel(str, Enum):
    FLAT_FEE = "FLAT_FEE"
    REVENUE_SHARE = "REVENUE_SHARE"
    MINIMUM_GUARANTEE = "MINIMUM_GUARANTEE"


class ProrationMode(str, Enum):
    DAILY_PRORATION = "DAILY_PRORATION"
    MONTHLY_PRORATION = "MONTHLY_PRORATION"


class DeliveryStatus(str, Enum):
    QUEUED = "QUEUED"
    DELIVERED = "DELIVERED"
    REJECTED = "REJECTED"


class NoticeStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class ReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    REVERSED = "REVERSED"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    PAID = "PAID"


class AttributionMode(str, Enum):
    BY_REPORT_DATE = "BY_REPORT_DATE"
    BY_USAGE_PERIOD = "BY_USAGE_PERIOD"


class UserRole(str, Enum):
    RIGHTS_MANAGER = "RightsManager"
    PLATFORM_BUYER = "PlatformBuyer"
    FINANCE_ANALYST = "FinanceAnalyst"
    FINANCE_CONTROLLER = "FinanceController"


class Title(TypedDict, total=False):
    id: str
    title_code: str
    name: str
    content_type: str
    original_language: str
    production_year: int
    embargoed_territories: List[str]
    created_at: str
    updated_at: str
    version: int


class RightsHolder(TypedDict, total=False):
    id: str
    name: str
    payee_reference: str
    royalty_share_pct: float
    created_at: str
    updated_at: str
    version: int


class Platform(TypedDict, total=False):
    id: str
    name: str
    platform_type: str
    metadata_spec_version: str
    required_asset_profiles: List[str]
    created_at: str
    updated_at: str
    version: int


class RightsSlot(TypedDict, total=False):
    id: str
    title_id: str
    rights_holder_id: str
    territory_code: str
    language_code: str
    window_type: str
    sellable_from: str
    sellable_to: str
    slot_status: str
    created_at: str
    updated_at: str
    version: int


class PackageLine(TypedDict, total=False):
    slot_id: str
    license_start: str
    license_end: str
    exclusive: bool
    fee_model: str
    flat_fee_cents: int
    revenue_share_pct: float
    minimum_guarantee_cents: int
    proration_mode: str
    line_status: str
    created_license_id: Optional[str]


class AvailPackage(TypedDict, total=False):
    id: str
    platform_id: str
    name: str
    offer_expires_at: str
    package_status: str
    lines: List[PackageLine]
    guaranteed_total_cents: int
    discount_pct: Optional[float]
    discount_cents: Optional[int]
    net_total_cents: Optional[int]
    offered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LicenseAgreement(TypedDict, total=False):
    id: str
    package_id: Optional[str]
    platform_id: str
    slot_id: str
    territory_code: str
    language_code: str
    window_type: str
    license_start: str
    license_end: str
    exclusive: bool
    fee_model: str
    flat_fee_cents: int
    revenue_share_pct: float
    minimum_guarantee_cents: int
    proration_mode: str
    allocated_fee_cents: int
    recouped_cents: int
    royalty_payable_cents: int
    outstanding_recoupment_cents: int
    termination_credit_cents: Optional[int]
    holdback_until: Optional[str]
    license_status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeliveryBatch(TypedDict, total=False):
    id: str
    license_id: str
    asset_manifest: List[str]
    metadata_spec_version: str
    delivery_status: str
    missing_profiles: List[str]
    attempt_count: int
    submitted_at: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TakedownNotice(TypedDict, total=False):
    id: str
    license_id: str
    scheduled_for: str
    notice_status: str
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RevenueReport(TypedDict, total=False):
    id: str
    license_id: str
    period_start: str
    period_end: str
    gross_revenue_cents: int
    royalty_accrued_cents: int
    recoupment_applied_cents: int
    payable_cents: int
    report_status: str
    submitted_at: str
    created_at: str
    updated_at: str
    version: int


class RoyaltyStatement(TypedDict, total=False):
    id: str
    rights_holder_id: str
    period_start: str
    period_end: str
    attribution_mode: str
    included_report_ids: List[str]
    gross_revenue_cents: int
    studio_net_royalty_cents: int
    holder_royalty_due_cents: int
    statement_status: str
    finalized_by_user_id: Optional[str]
    paid_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
