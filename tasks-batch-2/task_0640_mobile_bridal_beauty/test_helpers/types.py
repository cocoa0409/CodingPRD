"""Domain types: entity TypedDicts, status enums, role enum for the Bridal Beauty API."""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    COORDINATOR = "Coordinator"
    ARTIST = "Artist"
    CLIENT = "Client"


# ─── Status enums ─────────────────────────────────────
class ArtistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class SkillTier(str, Enum):
    LEAD = "LEAD"
    SENIOR = "SENIOR"
    JUNIOR = "JUNIOR"


class PortfolioItemStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class ServiceCategory(str, Enum):
    HAIR = "HAIR"
    MAKEUP = "MAKEUP"
    BOTH = "BOTH"


class BridalEventStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    CONTRACTED = "CONTRACTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BookingFaceStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REMOVED = "REMOVED"
    SERVICED = "SERVICED"


class TrialSessionStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    VOIDED = "VOIDED"


class ServiceAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AddOnType(str, Enum):
    TOUCH_UP = "TOUCH_UP"
    EXTENDED_STAY = "EXTENDED_STAY"


class AddOnStatus(str, Enum):
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class DepositStatus(str, Enum):
    DUE = "DUE"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


class BalanceStatus(str, Enum):
    NOT_DUE = "NOT_DUE"
    DUE = "DUE"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class PaymentInstallment(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"


class PaymentOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"


class CancellationReason(str, Enum):
    CLIENT_CHOICE = "CLIENT_CHOICE"
    WEATHER = "WEATHER"
    ARTIST_UNAVAILABLE = "ARTIST_UNAVAILABLE"


class RefundTier(str, Enum):
    FULL_REFUND = "FULL_REFUND"
    DEPOSIT_FORFEIT = "DEPOSIT_FORFEIT"
    FULL_FORFEIT = "FULL_FORFEIT"


# ─── Entity TypedDicts ────────────────────────────────
# All entities except Payment carry id/created_at/updated_at/version.
class Artist(TypedDict):
    id: str
    display_name: str
    skill_tier: str
    hair_rate_per_face_cents: int
    makeup_rate_per_face_cents: int
    travel_rate_per_km_cents: int
    max_faces_per_hour: int
    can_assist: bool
    status: str
    portfolio_published: bool
    created_at: str
    updated_at: str
    version: int


class PortfolioItem(TypedDict):
    id: str
    artist_id: str
    look_name: str
    category: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BridalEvent(TypedDict):
    id: str
    client_id: str
    event_date_utc: str
    ready_by_utc: str
    venue_distance_km: float
    party_size: int
    status: str
    quote_revision: int
    estimated_total_cents: int
    trial_required: bool
    created_at: str
    updated_at: str
    version: int


class BookingFace(TypedDict):
    id: str
    event_id: str
    person_label: str
    service_type: str
    is_bride: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TrialSession(TypedDict):
    id: str
    event_id: str
    artist_id: str
    start_utc: str
    end_utc: str
    status: str
    trial_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    event_id: str
    lead_artist_id: str
    pinned_hair_rate_cents: int
    pinned_makeup_rate_cents: int
    pinned_travel_rate_per_km_cents: int
    contracted_total_cents: int
    deposit_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceAssignment(TypedDict):
    id: str
    event_id: str
    artist_id: str
    assistant_artist_id: Optional[str]
    window_start_utc: str
    window_end_utc: str
    faces_committed: int
    status: str
    extended_until_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    assignment_id: str
    addon_type: str
    quantity: int
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    event_id: str
    contract_id: str
    deposit_amount_cents: int
    balance_amount_cents: int
    amount_paid_cents: int
    deposit_status: str
    balance_status: str
    created_at: str
    updated_at: str
    version: int


class CancellationRecord(TypedDict):
    id: str
    event_id: str
    reason: str
    hours_before_event: float
    refund_tier: str
    deposit_refund_cents: int
    balance_relief_cents: int
    created_at: str
    updated_at: str
    version: int


# Payment is immutable: ONLY id + created_at (no updated_at, no version).
class Payment(TypedDict):
    id: str
    invoice_id: str
    applies_to: str
    amount_cents: int
    outcome: str
    created_at: str
