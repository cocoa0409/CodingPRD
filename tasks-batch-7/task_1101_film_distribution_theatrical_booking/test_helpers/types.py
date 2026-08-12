"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BOOKER = "Booker"
    EXHIBITOR = "Exhibitor"
    SETTLEMENT_CLERK = "SettlementClerk"
    MARKETING_LEAD = "MarketingLead"
    AUDITOR = "Auditor"


class FilmLifecycleStatus(str, Enum):
    PRE_RELEASE = "PRE_RELEASE"
    IN_RELEASE = "IN_RELEASE"
    HOLDOVER_PHASE = "HOLDOVER_PHASE"
    ANCILLARY_PENDING = "ANCILLARY_PENDING"
    ANCILLARY_RELEASED = "ANCILLARY_RELEASED"
    PULLED = "PULLED"


class FilmGenre(str, Enum):
    NARRATIVE = "NARRATIVE"
    DOCUMENTARY = "DOCUMENTARY"
    ANIMATION = "ANIMATION"
    GENRE_HORROR = "GENRE_HORROR"


class FilmRating(str, Enum):
    G = "G"
    PG = "PG"
    PG13 = "PG13"
    R = "R"
    NC17 = "NC17"


class ReleasePattern(str, Enum):
    WIDE = "WIDE"
    LIMITED = "LIMITED"
    PLATFORM = "PLATFORM"


class DistributorPosture(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"


class TheatreStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DARK = "DARK"


class ScreenStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    BOOKED = "BOOKED"
    MAINTENANCE = "MAINTENANCE"


class ProjectionFormat(str, Enum):
    DCP_2K = "DCP_2K"
    DCP_4K = "DCP_4K"
    FILM_35MM = "FILM_35MM"


class PopulationTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class DealStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    IN_PLAY = "IN_PLAY"
    HELD_OVER = "HELD_OVER"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class PrintStatus(str, Enum):
    NOT_ORDERED = "NOT_ORDERED"
    DCP_QUEUED = "DCP_QUEUED"
    DCP_SHIPPED = "DCP_SHIPPED"
    DCP_DELIVERED = "DCP_DELIVERED"
    KDM_ISSUED = "KDM_ISSUED"
    KEY_LIVE = "KEY_LIVE"
    PRINT_STRUCK = "PRINT_STRUCK"
    PRINT_RETURNED = "PRINT_RETURNED"


class AggregateDealStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class DCPShipmentStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"
    LOST = "LOST"


class KDMKeyStatus(str, Enum):
    ISSUED = "ISSUED"
    LIVE = "LIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    EXTENDED = "EXTENDED"


class BoxOfficeReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    LOCKED = "LOCKED"
    VOIDED = "VOIDED"


class SettlementVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class SettlementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    PENDING_FINAL = "PENDING_FINAL"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    WRITTEN_OFF = "WRITTEN_OFF"


class HoldoverDecisionType(str, Enum):
    HOLD = "HOLD"
    RELEASE = "RELEASE"
    AUTO_HOLD = "AUTO_HOLD"
    AUTO_RELEASE = "AUTO_RELEASE"


class MarketingCommitmentStatus(str, Enum):
    DRAFT = "DRAFT"
    COMMITTED = "COMMITTED"
    ACCRUING = "ACCRUING"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class ZoneClearanceStatus(str, Enum):
    GRANTED = "GRANTED"
    CHALLENGED = "CHALLENGED"
    UPHELD = "UPHELD"
    OVERRULED = "OVERRULED"
    EXPIRED = "EXPIRED"


class AncillaryWindowKind(str, Enum):
    HOME_VIDEO = "HOME_VIDEO"
    TVOD = "TVOD"
    SVOD = "SVOD"
    AIRLINE = "AIRLINE"


class AncillaryWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HANDED_OFF = "HANDED_OFF"
    CANCELLED = "CANCELLED"
    VIOLATED = "VIOLATED"


# All resources carry the four common system-managed properties of PRD §2.4:
# id, created_at, updated_at, version.

class Distributor(TypedDict, total=False):
    id: str
    name: str
    territory: str
    week_epoch: int
    logical_clock_utc: str
    lifecycle_posture: str
    created_at: str
    updated_at: str
    version: int


class Film(TypedDict, total=False):
    id: str
    distributor_id: str
    title: str
    genre: str
    runtime_minutes: int
    rating: str
    release_pattern: str
    target_release_date: str
    min_screens_for_wide: int
    lifecycle_status: str
    screens_committed: int
    theatrical_window_end: str
    created_at: str
    updated_at: str
    version: int


class Theatre(TypedDict, total=False):
    id: str
    distributor_id: str
    name: str
    circuit: str
    market_code: str
    house_allowance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Screen(TypedDict, total=False):
    id: str
    theatre_id: str
    auditorium_label: str
    seat_count: int
    projection_format: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Market(TypedDict, total=False):
    id: str
    distributor_id: str
    code: str
    population_tier: str
    weekly_coop_budget_cents: int
    coop_committed_cents: int
    created_at: str
    updated_at: str
    version: int


class BookingAgreement(TypedDict, total=False):
    id: str
    film_id: str
    theatre_id: str
    screen_id: str
    deal_status: str
    print_status: str
    opening_date: str
    min_weeks_committed: int
    week_one_rental_pct: float
    rental_decay_per_week: float
    floor_pct: float
    per_capita_floor_cents: int
    weeks_played: int
    current_week_rental_pct: float
    aggregate_deal_id: Optional[str]
    holdover_eligible: bool
    created_at: str
    updated_at: str
    version: int


class AggregateDeal(TypedDict, total=False):
    id: str
    distributor_id: str
    film_id: str
    circuit: str
    deal_status: str
    aggregate_rental_pct: float
    min_screens: int
    aggregate_house_allowance_cents: int
    created_at: str
    updated_at: str
    version: int


class DCPShipment(TypedDict, total=False):
    id: str
    booking_agreement_id: str
    content_format: str
    tracking_number: str
    shipped_at: Optional[str]
    delivered_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class KDMKey(TypedDict, total=False):
    id: str
    booking_agreement_id: str
    valid_from_utc: str
    valid_until_utc: str
    screen_cert_fingerprint: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BoxOfficeReport(TypedDict, total=False):
    id: str
    booking_agreement_id: str
    report_date: str
    gross_cents: int
    admissions: int
    week_index: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    booking_agreement_id: str
    week_index: int
    gross_cents: int
    house_allowance_cents: int
    net_cents: int
    rental_pct_applied: float
    distributor_share_cents: int
    exhibitor_share_cents: int
    marketing_offset_cents: int
    final_distributor_payout_cents: int
    variant: str
    status: str
    created_at: str
    updated_at: str
    version: int


class HoldoverDecision(TypedDict, total=False):
    id: str
    booking_agreement_id: str
    week_index: int
    prior_week_gross_cents: int
    decision: str
    rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MarketingCommitment(TypedDict, total=False):
    id: str
    market_id: str
    film_id: str
    theatre_id: Optional[str]
    committed_cents: int
    spent_cents: int
    outstanding_cents: int
    status: str
    coop_share_pct: float
    created_at: str
    updated_at: str
    version: int


class ZoneClearance(TypedDict, total=False):
    id: str
    market_id: str
    film_id: str
    theatre_id: str
    clearance_radius_km: float
    effective_from_utc: str
    effective_until_utc: str
    parent_dispute_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AncillaryWindow(TypedDict, total=False):
    id: str
    film_id: str
    window_kind: str
    scheduled_start_utc: str
    actual_start_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
