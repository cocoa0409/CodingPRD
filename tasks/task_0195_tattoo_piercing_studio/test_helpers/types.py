"""Domain types: entity TypedDicts, status enums, and the role enum for the
Tattoo & Piercing Studio API."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    STUDIO_MANAGER = "StudioManager"
    ARTIST = "Artist"
    CLIENT = "Client"
    ANONYMOUS = "Anonymous"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class ArtistDiscipline(str, Enum):
    TATTOO = "TATTOO"
    PIERCING = "PIERCING"
    BOTH = "BOTH"


class ClientIdStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PENDING_REVIEW = "PENDING_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class IdDocumentType(str, Enum):
    DRIVERS_LICENSE = "DRIVERS_LICENSE"
    PASSPORT = "PASSPORT"
    STATE_ID = "STATE_ID"


class FlashDesignStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    RETIRED = "RETIRED"


class CustomDesignRequestStatus(str, Enum):
    PENDING = "PENDING"
    QUOTED = "QUOTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    CONVERTED = "CONVERTED"


class PricingMode(str, Enum):
    HOURLY = "HOURLY"
    PIECE = "PIECE"


class AppointmentStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class DepositStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    FORFEITED = "FORFEITED"
    APPLIED = "APPLIED"


class TouchUpStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    DENIED = "DENIED"


class PortfolioItemVisibility(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    HIDDEN = "HIDDEN"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# common_fields: true -> id + created_at + updated_at + version
class Artist(TypedDict):
    id: str
    display_name: str
    discipline: str
    hourly_rate_cents: int
    commission_pct: float
    accepting_custom: bool
    completed_session_count: int
    artist_cancel_count: int
    late_reschedule_count: int
    reliability_score: int
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    full_name: str
    email: str
    date_of_birth: str
    id_status: str
    id_document_type: Optional[str]
    verified_age_years: Optional[int]
    created_at: str
    updated_at: str
    version: int


class FlashDesign(TypedDict):
    id: str
    artist_id: str
    title: str
    piece_price_cents: int
    estimated_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomDesignRequest(TypedDict):
    id: str
    artist_id: str
    client_id: str
    brief: str
    quoted_price_cents: Optional[int]
    quoted_hourly_rate_cents: Optional[int]
    estimated_minutes: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    artist_id: str
    client_id: str
    chair_id: str
    flash_design_id: Optional[str]
    custom_request_id: Optional[str]
    pricing_mode: str
    piece_price_cents: Optional[int]
    hourly_rate_cents: Optional[int]
    estimated_minutes: int
    start_at: str
    end_at: str
    actual_minutes: Optional[int]
    required_deposit_cents: int
    deposit_paid_cents: int
    gross_cents: Optional[int]
    balance_due_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Chair(TypedDict):
    id: str
    label: str
    cleanup_buffer_minutes: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Deposit(TypedDict):
    id: str
    appointment_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TouchUp(TypedDict):
    id: str
    parent_appointment_id: str
    requested_at: str
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PortfolioItem(TypedDict):
    id: str
    artist_id: str
    appointment_id: str
    caption: str
    visibility: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> immutable record, carries ONLY id + created_at
# (plus its own fields). No updated_at, no version (PRD §2.4).
class ConsentWaiver(TypedDict):
    id: str
    appointment_id: str
    client_id: str
    medical_flags: List[str]
    aftercare_acknowledged: bool
    signed_at: str
    created_at: str
