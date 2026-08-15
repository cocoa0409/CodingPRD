"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class MarketTier(str, Enum):
    MAJOR_METRO = "MAJOR_METRO"
    REGIONAL = "REGIONAL"
    SMALL_MARKET = "SMALL_MARKET"


class TheaterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DARK = "DARK"


class ScreenStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class ContentRating(str, Enum):
    G = "G"
    PG = "PG"
    PG13 = "PG13"
    R = "R"
    NC17 = "NC17"


class Daypart(str, Enum):
    MATINEE = "MATINEE"
    EVENING = "EVENING"


class AdvertiserType(str, Enum):
    NATIONAL = "NATIONAL"
    LOCAL = "LOCAL"


class AdvertiserCategory(str, Enum):
    AUTOMOTIVE = "AUTOMOTIVE"
    QSR = "QSR"
    RETAIL = "RETAIL"
    ENTERTAINMENT = "ENTERTAINMENT"
    TECH = "TECH"
    ALCOHOL = "ALCOHOL"
    POLITICAL = "POLITICAL"


class AdvertiserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"


class PartialCreditMode(str, Enum):
    STRICT = "STRICT"
    LENIENT = "LENIENT"


class ReelStatus(str, Enum):
    ASSEMBLING = "ASSEMBLING"
    LOCKED = "LOCKED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERY_FAILED = "DELIVERY_FAILED"
    DELIVERED = "DELIVERED"
    RECONCILED = "RECONCILED"


class SlotStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    PLAYED = "PLAYED"
    MISSED = "MISSED"
    CANCELED = "CANCELED"


class PlayLogOutcome(str, Enum):
    VERIFIED = "VERIFIED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class DeliveryOutcome(str, Enum):
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class ReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    DISPUTED = "DISPUTED"
    ACCEPTED = "ACCEPTED"
    AUDITED = "AUDITED"


class ReviewDecision(str, Enum):
    ACCEPT = "ACCEPT"
    DISPUTE = "DISPUTE"


class BillingStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SETTLED = "SETTLED"
    VOID = "VOID"


class AuditStatus(str, Enum):
    UNAUDITED = "UNAUDITED"
    CERTIFIED = "CERTIFIED"


class CreditStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    APPLIED = "APPLIED"


class MakeGoodDecision(str, Enum):
    APPROVE = "APPROVE"
    DECLINE = "DECLINE"


class UserRole(str, Enum):
    NETWORK_OPS = "NetworkOps"
    SALES_MANAGER = "SalesManager"
    THEATER_OPS = "TheaterOps"
    AUDITOR = "Auditor"


class Theater(TypedDict):
    id: str
    name: str
    market_tier: str
    theater_status: str
    created_at: str
    updated_at: str
    version: int


class Screen(TypedDict):
    id: str
    theater_id: str
    auditorium_label: str
    seat_count: int
    screen_status: str
    created_at: str
    updated_at: str
    version: int


class Feature(TypedDict):
    id: str
    title: str
    content_rating: str
    runtime_minutes: int
    release_date: str
    created_at: str
    updated_at: str
    version: int


class Showtime(TypedDict):
    id: str
    screen_id: str
    feature_id: str
    starts_at: str
    daypart: str
    forecast_attendance: int
    actual_attendance: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Advertiser(TypedDict):
    id: str
    name: str
    advertiser_type: str
    category: str
    advertiser_status: str
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict):
    id: str
    advertiser_id: str
    name: str
    flight_start_date: str
    flight_end_date: str
    contracted_impressions: int
    cpm_cents: int
    budget_cents: int
    partial_credit_mode: str
    campaign_status: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    reserved_estimated_cents: int
    delivered_impressions: int
    created_at: str
    updated_at: str
    version: int


class PreShowReel(TypedDict):
    id: str
    showtime_id: str
    reel_status: str
    capacity_seconds: int
    national_pool_seconds: int
    local_pool_seconds: int
    national_used_seconds: int
    local_used_seconds: int
    created_at: str
    updated_at: str
    version: int


class ReelSlot(TypedDict):
    id: str
    reel_id: str
    campaign_id: str
    start_offset_seconds: int
    duration_seconds: int
    slot_status: str
    estimated_cost_cents: int
    play_factor: Optional[float]
    attributed_impressions: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PlayLog(TypedDict):
    # Append-only record: carries ONLY id + created_at from the common set.
    id: str
    slot_id: str
    outcome: str
    played_at: str
    reported_by_user_id: str
    reported_by_theater_id: str
    created_at: str


class AttendanceReport(TypedDict):
    id: str
    showtime_id: str
    reported_attendance: int
    audited_attendance: Optional[int]
    report_status: str
    reported_by_user_id: str
    reviewed_by_user_id: Optional[str]
    audited_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    campaign_id: str
    period_start_date: str
    period_end_date: str
    billing_status: str
    audit_status: str
    provisional_impressions: int
    provisional_amount_cents: int
    audited_impressions: Optional[int]
    audited_amount_cents: Optional[int]
    applied_credit_cents: int
    final_amount_cents: Optional[int]
    issued_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MakeGoodCredit(TypedDict):
    id: str
    invoice_id: str
    shortfall_impressions: int
    under_delivery_pct: float
    credit_cents: int
    credit_status: str
    proposed_by_user_id: str
    reviewed_by_user_id: Optional[str]
    applied_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
