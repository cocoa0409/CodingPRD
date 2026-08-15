"""Domain types: entity TypedDicts, status enums, role enum (PRD Section 3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    SHOW_DIRECTOR = "ShowDirector"
    OPERATIONS_STAFF = "OperationsStaff"
    JURY_MEMBER = "JuryMember"
    EXHIBITOR = "Exhibitor"
    ANONYMOUS = "Anonymous"


class ConventionPhase(str, Enum):
    SETUP = "SETUP"
    APPLICATIONS_OPEN = "APPLICATIONS_OPEN"
    JURY_REVIEW = "JURY_REVIEW"
    PLACEMENT = "PLACEMENT"
    LOGISTICS = "LOGISTICS"
    LIVE = "LIVE"
    LOAD_OUT = "LOAD_OUT"
    CLOSED = "CLOSED"


class ExhibitorCategory(str, Enum):
    ARTIST_ALLEY = "ARTIST_ALLEY"
    DEALER = "DEALER"
    PUBLISHER = "PUBLISHER"
    STUDIO = "STUDIO"
    NONPROFIT = "NONPROFIT"


class Hall(str, Enum):
    MAIN = "MAIN"
    ARTIST_ALLEY_HALL = "ARTIST_ALLEY_HALL"
    SMALL_PRESS = "SMALL_PRESS"


class SpaceKind(str, Enum):
    BOOTH_10X10 = "BOOTH_10X10"
    BOOTH_10X20 = "BOOTH_10X20"
    CORNER_BOOTH = "CORNER_BOOTH"
    ENDCAP = "ENDCAP"
    FEATURED_ISLAND = "FEATURED_ISLAND"
    ARTIST_TABLE = "ARTIST_TABLE"
    NONPROFIT_TABLE = "NONPROFIT_TABLE"


class SpaceUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    ASSIGNED = "ASSIGNED"


class ExhibitorStanding(str, Enum):
    GOOD = "GOOD"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    EVICTED = "EVICTED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_REVISION = "NEEDS_REVISION"
    JURIED_ACCEPTED = "JURIED_ACCEPTED"
    JURIED_WAITLISTED = "JURIED_WAITLISTED"
    JURIED_REJECTED = "JURIED_REJECTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    CONTRACTED = "CONTRACTED"
    PLACED = "PLACED"
    CANCELLED = "CANCELLED"


class PermitStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    EXEMPT = "EXEMPT"


class ApplicationChannel(str, Enum):
    RENEWAL = "RENEWAL"
    OPEN = "OPEN"


class CancellationReason(str, Enum):
    EXHIBITOR = "EXHIBITOR"
    DIRECTOR = "DIRECTOR"
    EVICTION = "EVICTION"
    OFFER_EXPIRED = "OFFER_EXPIRED"


class JuryDecision(str, Enum):
    ACCEPTED = "ACCEPTED"
    WAITLISTED = "WAITLISTED"
    REJECTED = "REJECTED"


class PlacementStatus(str, Enum):
    TENTATIVE = "TENTATIVE"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class NeighborRequestKind(str, Enum):
    ADJACENT_TO = "ADJACENT_TO"
    AWAY_FROM = "AWAY_FROM"


class NeighborRequestStatus(str, Enum):
    PENDING = "PENDING"
    HONORED = "HONORED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    MOOT = "MOOT"


class BadgeStatus(str, Enum):
    NONE = "NONE"
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"


class LoadDirection(str, Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class LoadSlotStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"


class FreightBookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class IssueCategory(str, Enum):
    ENCROACHMENT = "ENCROACHMENT"
    NOISE = "NOISE"
    PROHIBITED_ITEM = "PROHIBITED_ITEM"
    COPYRIGHT = "COPYRIGHT"
    CONDUCT = "CONDUCT"


class IssueSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class IssueStatus(str, Enum):
    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class IssueOutcome(str, Enum):
    GUILTY = "GUILTY"
    UNFOUNDED = "UNFOUNDED"


class SalesReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Convention(TypedDict, total=False):
    id: str
    name: str
    starts_at: str
    ends_at: str
    renewal_open_at: str
    application_open_at: str
    application_close_at: str
    early_bird_deadline: str
    deposit_window_days: int
    tax_permit_required: bool
    sales_tax_rate_bp: int
    phase: str
    ops_run_count: int
    created_at: str
    updated_at: str
    version: int


class CategoryQuota(TypedDict, total=False):
    id: str
    convention_id: str
    category: str
    max_accepted: int
    max_waitlisted: int
    accepted_count: int
    waitlisted_count: int
    created_at: str
    updated_at: str
    version: int


class SpaceUnit(TypedDict, total=False):
    id: str
    convention_id: str
    space_code: str
    block: str
    unit_number: int
    hall: str
    kind: str
    base_price_cents: int
    status: str
    current_application_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Exhibitor(TypedDict, total=False):
    id: str
    legal_name: str
    category: str
    prior_years_completed: int
    prior_on_time_payments: int
    strike_points: int
    standing: str
    renewal_priority_score: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    exhibitor_id: str
    convention_id: str
    category: str
    channel: str
    requested_space_kinds: List[str]
    requested_space_count: int
    estimated_daily_sales_cents: int
    conflicted_juror_user_ids: List[str]
    status: str
    permit_status: str
    permit_number: Optional[str]
    permit_expires_at: Optional[str]
    submitted_at: Optional[str]
    decided_at: Optional[str]
    jury_composite_score: Optional[float]
    provisional_quote_cents: Optional[int]
    final_invoice_cents: Optional[int]
    deposit_cents: Optional[int]
    amount_paid_cents: int
    badge_fees_cents: int
    balance_due_cents: int
    refund_cents: Optional[int]
    included_badges: int
    purchased_extra_badges: int
    tax_estimate_cents: Optional[int]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class JuryScore(TypedDict, total=False):
    """Immutable score: carries only id + created_at plus scoring fields.

    No updated_at / version (PRD Section 2.4).
    """
    id: str
    application_id: str
    juror_user_id: str
    originality: int
    craft: int
    category_fit: int
    professionalism: int
    weighted_total: float
    created_at: str


class Placement(TypedDict, total=False):
    id: str
    application_id: str
    space_unit_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class NeighborRequest(TypedDict, total=False):
    id: str
    convention_id: str
    requester_exhibitor_id: str
    target_exhibitor_id: str
    kind: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict, total=False):
    id: str
    exhibitor_id: str
    convention_id: str
    full_name: str
    role_label: Optional[str]
    badge_status: str
    created_at: str
    updated_at: str
    version: int


class LoadSlot(TypedDict, total=False):
    id: str
    convention_id: str
    direction: str
    starts_at: str
    ends_at: str
    pallet_capacity: int
    reserved_pallets: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DockDoor(TypedDict, total=False):
    """Immutable door row: only id + created_at plus its fields (PRD Section 2.4)."""
    id: str
    convention_id: str
    door_code: str
    created_at: str


class FreightBooking(TypedDict, total=False):
    id: str
    application_id: str
    exhibitor_id: str
    load_slot_id: str
    dock_door_id: str
    door_starts_at: str
    door_ends_at: str
    pallet_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IssueTicket(TypedDict, total=False):
    id: str
    convention_id: str
    exhibitor_id: str
    reporter_user_id: str
    category: str
    severity: str
    description: str
    status: str
    outcome: Optional[str]
    strike_points_applied: int
    created_at: str
    updated_at: str
    version: int


class SalesReportLine(TypedDict):
    sale_date: str
    gross_cents: int


class SalesReport(TypedDict, total=False):
    id: str
    application_id: str
    exhibitor_id: str
    lines: List[SalesReportLine]
    status: str
    tax_settlement_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
