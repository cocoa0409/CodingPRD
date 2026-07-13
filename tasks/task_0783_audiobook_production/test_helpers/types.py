"""Domain types: entity TypedDicts, status enums, role enum.

All fields and states are named exactly as they appear in the PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    AUTHOR = "Author"
    NARRATOR = "Narrator"
    QC_REVIEWER = "QCReviewer"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Status enums ─────────────────────────────────────
class TitleStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN_FOR_AUDITION = "OPEN_FOR_AUDITION"
    CASTING = "CASTING"
    IN_PRODUCTION = "IN_PRODUCTION"
    IN_QC = "IN_QC"
    PUBLISHED = "PUBLISHED"
    REVERTED = "REVERTED"


class RightsStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVERTED = "REVERTED"


class AuditionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class ContractStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"
    TERMINATED = "TERMINATED"


class DealType(str, Enum):
    ROYALTY_SHARE = "ROYALTY_SHARE"
    PER_HOUR = "PER_HOUR"


class BookingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class MilestoneType(str, Enum):
    FIFTEEN_MIN = "FIFTEEN_MIN"
    FULL = "FULL"


class MilestoneStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    REJECTED = "REJECTED"


class QCOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ListingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class StatementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    PAID = "PAID"
    FROZEN = "FROZEN"
    REVERSED = "REVERSED"


class StatementVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class Territory(str, Enum):
    WORLD = "WORLD"
    US = "US"
    UK = "UK"
    EU = "EU"


class Exclusivity(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    NON_EXCLUSIVE = "NON_EXCLUSIVE"


# ─── Entity TypedDicts ────────────────────────────────
# Full-complement entities carry id + created_at + updated_at + version.

class Author(TypedDict):
    id: str
    name: str
    email: str
    payout_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Narrator(TypedDict):
    id: str
    name: str
    email: str
    hourly_rate_cents: int
    payout_balance_cents: int
    active_booked_days: int
    created_at: str
    updated_at: str
    version: int


class Title(TypedDict):
    id: str
    author_id: str
    title_name: str
    isbn: str
    exclusivity: str
    territory: str
    list_price_cents: int
    status: str
    rights_status: str
    finished_hours: float
    retail_sample_start_sec: Optional[int]
    retail_sample_end_sec: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Audition(TypedDict):
    id: str
    title_id: str
    narrator_id: str
    sample_url: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    title_id: str
    narrator_id: str
    deal_type: str
    royalty_share_pct: Optional[float]
    per_hour_rate_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionBooking(TypedDict):
    id: str
    narrator_id: str
    title_id: str
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionMilestone(TypedDict):
    id: str
    contract_id: str
    milestone_type: str
    audio_url: str
    finished_hours: Optional[float]
    status: str
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class DistributionChannel(TypedDict):
    id: str
    name: str
    supported_territories: List[str]
    retailer_cut_pct: float
    created_at: str
    updated_at: str
    version: int


class DistributionListing(TypedDict):
    id: str
    title_id: str
    channel_id: str
    territory: str
    effective_from: str
    effective_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RoyaltyStatement(TypedDict):
    id: str
    title_id: str
    period_start: str
    period_end: str
    variant: str
    narrator_share_pct_applied: float
    gross_sales_cents: int
    statement_net_cents: int
    narrator_royalty_cents: int
    author_royalty_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Lightweight, immutable audit records — carry ONLY id + created_at.

class QCReview(TypedDict):
    id: str
    milestone_id: str
    outcome: str
    notes: Optional[str]
    created_at: str


class SalesEvent(TypedDict):
    id: str
    listing_id: str
    units_sold: int
    units_returned: int
    unit_price_cents: int
    occurred_at: str
    created_at: str
