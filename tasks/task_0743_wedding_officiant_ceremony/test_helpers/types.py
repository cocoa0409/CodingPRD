"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's resource model (Section 2.4 common properties and the
per-entity workflows in Section 3). Every entity in this system carries the four
system-managed fields id, created_at, updated_at, and version (PRD Section 2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles (PRD Section 2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    COORDINATOR = "Coordinator"
    COUPLE = "Couple"
    OFFICIANT = "Officiant"


# ---------------------------------------------------------------------------
# Status enums (PRD Section 3 state machines)
# ---------------------------------------------------------------------------
class OfficiantStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BookingStatus(str, Enum):
    INQUIRY = "INQUIRY"
    HOLD = "HOLD"
    CONFIRMED = "CONFIRMED"
    BACKUP_PENDING = "BACKUP_PENDING"
    BACKUP_CONFIRMED = "BACKUP_CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class DateHoldStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class CeremonyScriptStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


class RehearsalStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class MarriageLicenseStatus(str, Enum):
    NOT_FILED = "NOT_FILED"
    FILED = "FILED"
    SIGNED = "SIGNED"
    RECORDED = "RECORDED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class ReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PUBLISHED = "PUBLISHED"
    REMOVED = "REMOVED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class Officiant(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    styles: List[str]
    denomination: str
    certified_jurisdictions: List[str]
    travel_buffer_minutes: int
    max_active_holds: int
    status: str
    active_hold_count: int
    escrow_balance_cents: int
    displayed_rating: Optional[float]
    internal_rating: Optional[float]
    published_review_count: int
    created_at: str
    updated_at: str
    version: int


class Couple(TypedDict, total=False):
    id: str
    partner_one_name: str
    partner_two_name: str
    email: str
    phone: str
    paid_total_cents: int
    refund_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Package(TypedDict, total=False):
    id: str
    name: str
    tier: str
    base_price_cents: int
    deposit_pct: float
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict, total=False):
    id: str
    name: str
    jurisdiction: str
    address: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    officiant_id: str
    couple_id: str
    package_id: str
    venue_id: str
    backup_officiant_id: Optional[str]
    ceremony_start: str
    ceremony_end: str
    travel_distance_km: float
    required_style: str
    addon_codes: List[str]
    status: str
    quoted_subtotal_cents: int
    quoted_travel_cents: int
    quoted_rush_cents: int
    quoted_interfaith_cents: int
    quoted_addons_cents: int
    quoted_gratuity_cents: int
    quoted_total_cents: int
    deposit_due_cents: int
    deposit_captured_cents: int
    refund_issued_cents: int
    forfeit_retained_cents: int
    cancel_initiator: Optional[str]
    cancel_reason: Optional[str]
    days_until_ceremony_at_quote: int
    created_at: str
    updated_at: str
    version: int


class DateHold(TypedDict, total=False):
    id: str
    booking_id: str
    officiant_id: str
    hold_start: str
    hold_end: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CeremonyScript(TypedDict, total=False):
    id: str
    booking_id: str
    opening_remarks: str
    vow_format: str
    readings: List[str]
    ritual_elements: List[str]
    closing_blessing: str
    officiant_notes: Optional[str]
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Rehearsal(TypedDict, total=False):
    id: str
    booking_id: str
    venue_id: str
    rehearsal_start: str
    rehearsal_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MarriageLicense(TypedDict, total=False):
    id: str
    booking_id: str
    jurisdiction: str
    license_number: str
    issued_date: str
    expiry_date: str
    signed_at: Optional[str]
    return_deadline: Optional[str]
    recorded_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Review(TypedDict, total=False):
    id: str
    booking_id: str
    officiant_id: str
    rating: int
    text: str
    status: str
    created_at: str
    updated_at: str
    version: int
