"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.6, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    EVENT_COORDINATOR = "EventCoordinator"
    VENDOR = "Vendor"
    JUROR = "Juror"
    TREASURER = "Treasurer"
    GATE_AGENT = "GateAgent"
    PLATFORM_ADMIN = "PlatformAdmin"


class MakerEventPosture(str, Enum):
    PLANNING = "PLANNING"
    APPLICATION_OPEN = "APPLICATION_OPEN"
    JURY_REVIEW = "JURY_REVIEW"
    SCHEDULING = "SCHEDULING"
    LIVE = "LIVE"
    WEATHER_HOLD = "WEATHER_HOLD"
    SETTLEMENT = "SETTLEMENT"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class WeatherFlag(str, Enum):
    CLEAR = "CLEAR"
    ADVISORY = "ADVISORY"
    SEVERE = "SEVERE"


class WeatherExposure(str, Enum):
    INDOOR = "INDOOR"
    COVERED = "COVERED"
    OPEN_AIR = "OPEN_AIR"


class CraftCategory(str, Enum):
    CERAMICS = "CERAMICS"
    TEXTILES = "TEXTILES"
    JEWELRY = "JEWELRY"
    WOODWORK = "WOODWORK"
    FOOD = "FOOD"
    MIXED = "MIXED"


class BoothTier(str, Enum):
    STANDARD = "STANDARD"
    CORNER = "CORNER"
    ANCHOR = "ANCHOR"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    WAITLISTED = "WAITLISTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    FORFEITED = "FORFEITED"


class ChargeKind(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    SURCHARGE = "SURCHARGE"
    REFUND = "REFUND"


class SlotKind(str, Enum):
    LOAD_IN = "LOAD_IN"
    LOAD_OUT = "LOAD_OUT"


class SlotBay(str, Enum):
    NORTH = "NORTH"
    SOUTH = "SOUTH"


class TicketKind(str, Enum):
    GA = "GA"
    EARLY_BIRD = "EARLY_BIRD"
    VIP = "VIP"


class TicketState(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    REFUNDED = "REFUNDED"
    VOIDED = "VOIDED"


class SettlementStatus(str, Enum):
    PENDING = "PENDING"
    COMPUTED = "COMPUTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    CANCELLED = "CANCELLED"


class DecideOutcome(str, Enum):
    APPROVE = "APPROVE"
    WAITLIST = "WAITLIST"
    REJECT = "REJECT"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.6).
# Append-only records (JuryScore, Attendance, SalesLedgerEntry) carry ONLY
# id + created_at — updated_at and version are absent from them (PRD §2.6).


class MakerEvent(TypedDict, total=False):
    id: str
    name: str
    opens_at: str
    closes_at: str
    venue_capacity: int
    posture: str
    weather_flag: str
    application_window_start: str
    application_window_end: str
    jury_quorum: int
    commission_pct_standard: float
    commission_pct_anchor: float
    created_at: str
    updated_at: str
    version: int


class BoothZone(TypedDict, total=False):
    id: str
    maker_event_id: str
    label: str
    weather_exposure: str
    category: str
    category_cap: int
    created_at: str
    updated_at: str
    version: int


class Booth(TypedDict, total=False):
    id: str
    booth_zone_id: str
    code: str
    tier: str
    footprint_sqm: int
    price_cents: int
    assigned_application_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VendorProfile(TypedDict, total=False):
    id: str
    display_name: str
    contact_email: str
    home_region: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VendorApplication(TypedDict, total=False):
    id: str
    maker_event_id: str
    vendor_profile_id: str
    requested_category: str
    requested_tier: str
    status: str
    jury_score_total: int
    jury_score_count: int
    waitlist_rank: Optional[int]
    created_at: str
    updated_at: str
    version: int


class JuryScore(TypedDict, total=False):
    # Append-only: NO updated_at, NO version (PRD §2.6)
    id: str
    vendor_application_id: str
    juror_user_id: str
    craftsmanship: int
    originality: int
    booth_presentation: int
    total: int
    created_at: str


class BoothAssignment(TypedDict, total=False):
    id: str
    vendor_application_id: str
    booth_id: str
    status: str
    assigned_at: str
    payment_due_at: str
    expected_event_version: int
    created_at: str
    updated_at: str
    version: int


class BoothFeeCharge(TypedDict, total=False):
    id: str
    booth_assignment_id: str
    charge_kind: str
    amount_cents: int
    computed_at: str
    rounding_trace: str
    created_at: str
    updated_at: str
    version: int


class LoadInSlot(TypedDict, total=False):
    id: str
    maker_event_id: str
    booth_assignment_id: str
    kind: str
    starts_at: str
    ends_at: str
    bay: str
    created_at: str
    updated_at: str
    version: int


class Ticket(TypedDict, total=False):
    id: str
    maker_event_id: str
    purchaser_email: str
    kind: str
    price_cents: int
    state: str
    redeemed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Attendance(TypedDict, total=False):
    # Append-only: NO updated_at, NO version (PRD §2.6)
    id: str
    maker_event_id: str
    ticket_id: str
    entered_at: str
    exited_at: Optional[str]
    created_at: str


class SalesLedgerEntry(TypedDict, total=False):
    # Append-only: NO updated_at, NO version (PRD §2.6)
    id: str
    maker_event_id: str
    booth_assignment_id: str
    gross_cents: int
    recorded_at: str
    reversal_of_entry_id: Optional[str]
    created_at: str


class Settlement(TypedDict, total=False):
    id: str
    booth_assignment_id: str
    status: str
    gross_sales_cents: int
    commission_cents: int
    net_payout_cents: int
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
