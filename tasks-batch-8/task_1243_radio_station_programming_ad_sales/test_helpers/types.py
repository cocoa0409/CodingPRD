"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3, §4)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_DIRECTOR = "ProgramDirector"
    TRAFFIC_DIRECTOR = "TrafficDirector"
    SALES_REP = "SalesRep"
    SALES_MANAGER = "SalesManager"
    BILLING_ADMIN = "BillingAdmin"


class Weekday(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class SlotType(str, Enum):
    MUSIC = "MUSIC"
    SPOT_BREAK = "SPOT_BREAK"
    LIVE_READ_WINDOW = "LIVE_READ_WINDOW"


class Daypart(str, Enum):
    MORNING_DRIVE = "MORNING_DRIVE"
    MIDDAY = "MIDDAY"
    AFTERNOON_DRIVE = "AFTERNOON_DRIVE"
    EVENING = "EVENING"
    OVERNIGHT = "OVERNIGHT"


class ClockStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class MusicCategoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class SongStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class RatingsBookStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class RateCardEntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ClearanceStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    DISAFFIRMED = "DISAFFIRMED"


class TradeAgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class LedgerEntryKind(str, Enum):
    DEBIT = "DEBIT"
    REVERSAL = "REVERSAL"
    ADJUSTMENT = "ADJUSTMENT"


class OrderKind(str, Enum):
    CASH = "CASH"
    TRADE = "TRADE"


class RateTier(str, Enum):
    FIXED = "FIXED"
    PREEMPTIBLE = "PREEMPTIBLE"


class RepricePolicy(str, Enum):
    LOCKED_AT_BOOKING = "LOCKED_AT_BOOKING"
    REPRICED_AT_AFFIDAVIT = "REPRICED_AT_AFFIDAVIT"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LogPosture(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    AS_RUN = "AS_RUN"
    RECONCILING = "RECONCILING"
    RECONCILED = "RECONCILED"
    AFFIDAVIT_ISSUED = "AFFIDAVIT_ISSUED"
    CLOSED = "CLOSED"


class SpotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    AIRED = "AIRED"
    MAKE_GOOD_PENDING = "MAKE_GOOD_PENDING"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class MakeGoodReason(str, Enum):
    PREEMPTED = "PREEMPTED"
    MISSED = "MISSED"


class BarterAvailStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    AIRED = "AIRED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    BREACHED = "BREACHED"
    CANCELLED = "CANCELLED"


class LiveReadStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    AIRED = "AIRED"
    MAKE_GOOD_PENDING = "MAKE_GOOD_PENDING"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class DiscrepancyKind(str, Enum):
    MISSED_SPOT = "MISSED_SPOT"
    MISSED_READ = "MISSED_READ"
    UNFILLED_BARTER = "UNFILLED_BARTER"


class DiscrepancyStatus(str, Enum):
    UNRESOLVED = "UNRESOLVED"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


class RemoteEventStatus(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    DELIVERED = "DELIVERED"
    DEFAULTED = "DEFAULTED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts -------------------------------------------------------
# All primary entities carry id + created_at + updated_at + version (PRD §2.5).
# TradeLedgerEntry is the single append-only exception: only id + created_at.


class ClockSlot(TypedDict):
    slot_type: str
    hour: int
    capacity_units: int
    capacity_seconds: int


class DaypartTarget(TypedDict):
    daypart: str
    units: int


class MusicPlacement(TypedDict):
    song_id: str
    hour: int
    placed_seq: int


class Station(TypedDict):
    id: str
    call_sign: str
    market_name: str
    default_share_fallback: float
    created_at: str
    updated_at: str
    version: int


class FormatClock(TypedDict):
    id: str
    station_id: str
    name: str
    applies_weekdays: List[str]
    slots: List[ClockSlot]
    status: str
    created_at: str
    updated_at: str
    version: int


class MusicCategory(TypedDict):
    id: str
    station_id: str
    code: str
    min_song_separation_min: int
    min_artist_separation_min: int
    max_spins_per_day: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Song(TypedDict):
    id: str
    station_id: str
    category_id: str
    title: str
    artist: str
    duration_sec: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RatingsBook(TypedDict):
    id: str
    station_id: str
    survey_name: str
    period_start: str
    period_end: str
    share_value: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RateCardEntry(TypedDict):
    id: str
    station_id: str
    daypart: str
    weekday_set: List[str]
    base_rate_cents: int
    min_rate_cents: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SyndicationClearance(TypedDict):
    id: str
    station_id: str
    program_name: str
    provider: str
    weekday_set: List[str]
    start_hour: int
    duration_hours: int
    barter_avails_per_hour: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TradeAgreement(TypedDict):
    id: str
    station_id: str
    vendor_name: str
    credit_limit_cents: int
    trade_ratio: float
    consumed_cents: int
    adjustments_cents: int
    available_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TradeLedgerEntry(TypedDict):
    # Append-only event log: id + created_at only — no updated_at, no version.
    id: str
    agreement_id: str
    entry_kind: str
    amount_cents: int
    spot_id: Optional[str]
    note: Optional[str]
    entry_seq: int
    created_at: str


class Order(TypedDict):
    id: str
    station_id: str
    advertiser_name: str
    order_kind: str
    trade_agreement_id: Optional[str]
    created_by_user_id: str
    flight_start: str
    flight_end: str
    rate_tier: str
    reprice_policy: str
    daypart_targets: List[DaypartTarget]
    units_scheduled: int
    units_aired: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DailyLog(TypedDict):
    id: str
    station_id: str
    log_date: str
    clock_id: Optional[str]
    clock_version: Optional[int]
    posture: str
    reconciled_by_user_id: Optional[str]
    affidavit_issued_by_user_id: Optional[str]
    unresolved_discrepancy_count: int
    affidavit_total_cents: Optional[int]
    music_placements: List[MusicPlacement]
    created_at: str
    updated_at: str
    version: int


class Spot(TypedDict):
    id: str
    station_id: str
    order_id: str
    log_id: str
    event_id: Optional[str]
    air_date: str
    daypart: str
    hour: int
    duration_sec: int
    unit_rate_cents: int
    billed_rate_cents: Optional[int]
    cash_equivalent_cents: Optional[int]
    makeup_of_spot_id: Optional[str]
    make_good_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BarterAvail(TypedDict):
    id: str
    station_id: str
    clearance_id: str
    log_id: str
    air_date: str
    hour: int
    duration_sec: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EndorsementContract(TypedDict):
    id: str
    station_id: str
    advertiser_name: str
    host_name: str
    program_weekdays: List[str]
    program_start_hour: int
    program_end_hour: int
    reads_per_week: int
    start_date: str
    end_date: str
    contracted_reads_total: int
    reads_completed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LiveRead(TypedDict):
    id: str
    station_id: str
    contract_id: str
    log_id: str
    air_date: str
    hour: int
    duration_sec: int
    makeup_of_live_read_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Discrepancy(TypedDict):
    id: str
    station_id: str
    log_id: str
    spot_id: Optional[str]
    live_read_id: Optional[str]
    barter_avail_id: Optional[str]
    discrepancy_kind: str
    status: str
    resolution_note: Optional[str]
    resolved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemoteEvent(TypedDict):
    id: str
    station_id: str
    event_name: str
    sponsor_name: str
    event_date: str
    spot_units_promised: int
    package_price_cents: int
    spots_delivered: int
    status: str
    created_at: str
    updated_at: str
    version: int
