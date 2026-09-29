"""Domain types for the Repertory Cinema Programming & Rights Clearance API.

Status enumerations, value enumerations and entity shapes, all named exactly as
the PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    PROGRAMMER = "Programmer"
    RIGHTS_MANAGER = "RightsManager"
    TECHNICAL_MANAGER = "TechnicalManager"
    BOX_OFFICE_MANAGER = "BoxOfficeManager"
    EXECUTIVE_DIRECTOR = "ExecutiveDirector"
    MEMBER = "Member"
    ANONYMOUS = "Anonymous"


# ─── Value enumerations ───────────────────────────────────────────────────

class ProjectionFormat(str, Enum):
    DCP_2K = "DCP_2K"
    DCP_4K = "DCP_4K"
    PRINT_35MM = "PRINT_35MM"
    PRINT_16MM = "PRINT_16MM"
    DIGITAL_FILE_PRORES = "DIGITAL_FILE_PRORES"


class TermsVariant(str, Enum):
    SLIDING_SCALE_90_10 = "SLIDING_SCALE_90_10"
    PERCENTAGE_FLOOR = "PERCENTAGE_FLOOR"
    FLAT_FEE = "FLAT_FEE"


class Strand(str, Enum):
    FIRST_RUN = "FIRST_RUN"
    REPERTORY_SERIES = "REPERTORY_SERIES"
    FESTIVAL = "FESTIVAL"
    SPECIAL_EVENT = "SPECIAL_EVENT"


class ProposedBy(str, Enum):
    CINEMA = "CINEMA"
    DISTRIBUTOR = "DISTRIBUTOR"


class MembershipTier(str, Enum):
    PROSPECT = "PROSPECT"
    BASIC = "BASIC"
    SUPPORTER = "SUPPORTER"
    DONOR_CIRCLE = "DONOR_CIRCLE"


class EventType(str, Enum):
    FILMMAKER_QA = "FILMMAKER_QA"
    PANEL = "PANEL"
    FESTIVAL_SCREENING = "FESTIVAL_SCREENING"
    THEMED_INTRO = "THEMED_INTRO"


class RefundDestination(str, Enum):
    CASH = "CASH"
    MEMBER_CREDIT = "MEMBER_CREDIT"


class SettlementVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class PlaybackResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class SettlementOutcome(str, Enum):
    DISPUTED = "DISPUTED"
    PAID = "PAID"


# ─── Status enumerations ──────────────────────────────────────────────────

class BookingStatus(str, Enum):
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    CONFIRMED = "CONFIRMED"
    RUNNING = "RUNNING"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class BookingOfferOutcome(str, Enum):
    PENDING = "PENDING"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ClearanceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    CLEARED = "CLEARED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class DcpAssetStatus(str, Enum):
    REQUESTED = "REQUESTED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    INGESTING = "INGESTING"
    INGESTED = "INGESTED"
    RETURNED = "RETURNED"


class KdmKeyStatus(str, Enum):
    ISSUED = "ISSUED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ShowtimeStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SaleStatus(str, Enum):
    DRAFT = "DRAFT"
    ON_SALE = "ON_SALE"
    SOLD_OUT = "SOLD_OUT"
    SALES_CLOSED = "SALES_CLOSED"


class PlaybackStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    KEY_PENDING = "KEY_PENDING"
    PLAYBACK_VERIFIED = "PLAYBACK_VERIFIED"
    PLAYBACK_FAILED = "PLAYBACK_FAILED"


class SpecialEventStatus(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class TicketOrderStatus(str, Enum):
    RESERVED = "RESERVED"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    VOID = "VOID"


class MemberStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"


# ─── Entity shapes ────────────────────────────────────────────────────────
# Every one of the thirteen resource types carries id, created_at, updated_at
# and version (PRD §2.4).

class Venue(TypedDict):
    id: str
    name: str
    seat_capacity: int
    house_hold_seats: int
    trailer_reel_minutes: int
    turnaround_minutes: int
    min_useful_gap_minutes: int
    dcp_ingest_lane_count: int
    open_local_time: str
    last_start_local_time: str
    utc_offset_minutes: int
    max_first_run_share: float
    weekly_repertory_target: int
    supported_formats: List[str]
    base_house_nut_weekly_cents: int
    created_at: str
    updated_at: str
    version: int


class Distributor(TypedDict):
    id: str
    name: str
    contact_email: str
    default_terms_variant: str
    default_min_run_days: int
    default_distributor_share_pct: float
    requires_advance_guarantee: bool
    created_at: str
    updated_at: str
    version: int


class Title(TypedDict):
    id: str
    title_name: str
    release_year: int
    runtime_minutes: int
    is_first_run: bool
    native_format: str
    rights_holder_distributor_id: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    title_id: str
    distributor_id: str
    venue_id: str
    supersedes_booking_id: Optional[str]
    status: str
    terms_variant: str
    house_nut_cents: int
    distributor_share_pct: float
    guarantee_cents: int
    min_run_days: int
    engagement_start_date: str
    engagement_end_date: str
    round_count: int
    scheduled_showtime_count: int
    actual_playing_days: int
    min_run_compliant: bool
    min_run_penalty_cents: int
    cancel_reason: Optional[str]
    created_by_user_id: str
    confirmed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BookingOffer(TypedDict):
    id: str
    booking_id: str
    round_index: int
    proposed_by: str
    proposed_house_nut_cents: int
    proposed_distributor_share_pct: float
    proposed_min_run_days: int
    proposed_guarantee_cents: int
    outcome: str
    expires_at: str
    submitted_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class RightsClearance(TypedDict):
    id: str
    title_id: str
    booking_id: str
    licensor_name: str
    license_fee_cents: int
    territory: str
    window_start_date: str
    window_end_date: str
    max_screenings: int
    source_format: str
    status: str
    screenings_used: int
    screenings_remaining: int
    submitted_by_user_id: str
    cleared_by_user_id: Optional[str]
    change_request_note: Optional[str]
    revoked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DcpAsset(TypedDict):
    id: str
    title_id: str
    source_distributor_id: str
    venue_id: str
    format: str
    is_encrypted: bool
    carrier_ref: Optional[str]
    ingest_window_start_at: str
    ingest_window_end_at: str
    status: str
    received_at: Optional[str]
    ingested_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class KdmKey(TypedDict):
    id: str
    dcp_asset_id: str
    venue_id: str
    server_ref: str
    valid_from: str
    valid_until: str
    status: str
    revoked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Showtime(TypedDict):
    id: str
    venue_id: str
    title_id: str
    booking_id: str
    clearance_id: str
    dcp_asset_id: str
    strand: str
    series_label: Optional[str]
    start_at: str
    end_at: str
    blocked_until: str
    extra_minutes: int
    base_price_cents: int
    surcharge_cents: int
    public_sale_opens_at: str
    format: str
    status: str
    sale_status: str
    playback_status: str
    seats_sold: int
    seats_available: int
    gross_cents: int
    admissions_count: int
    cancel_reason: Optional[str]
    slot_score: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SpecialEvent(TypedDict):
    id: str
    showtime_id: str
    event_type: str
    guest_name: str
    extra_minutes: int
    surcharge_cents: int
    guest_fee_cents: int
    status: str
    displaced_showtime_ids: List[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TicketOrder(TypedDict):
    id: str
    showtime_id: str
    member_id: Optional[str]
    quantity: int
    comp_quantity: int
    purchaser_email: str
    unit_price_cents: int
    line_subtotal_cents: int
    facility_fee_cents: int
    applied_credit_cents: int
    total_cents: int
    status: str
    refund_destination: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    full_name: str
    email: str
    join_date: str
    status: str
    donations: List[dict]
    rolling_donation_cents: int
    fiscal_ytd_donation_cents: int
    rolling_tier: str
    fiscal_tier: str
    effective_tier: str
    discount_pct: float
    advance_access_hours: int
    comp_tickets_granted: int
    comp_tickets_remaining: int
    credit_balance_cents: int
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    booking_id: str
    variant: str
    status: str
    box_office_cents: int
    facility_fee_total_cents: int
    adjusted_gross_cents: int
    playing_days: int
    proration_factor: float
    house_nut_applied_cents: int
    film_rent_cents: int
    min_run_penalty_cents: int
    cinema_retained_cents: int
    submitted_by_user_id: Optional[str]
    finalized_by_user_id: Optional[str]
    dispute_note: Optional[str]
    created_at: str
    updated_at: str
    version: int
