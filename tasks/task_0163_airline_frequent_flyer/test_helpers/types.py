"""Domain types — entity TypedDicts, status enums, role enum.

Field names mirror the PRD verbatim. Two entities carry only id +
created_at because the PRD §2.4 declares them immutable append-only:
PointsTransaction (ledger entries) and MembershipYear (annual snapshots).
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    MEMBER = "Member"
    BOOKING_AGENT = "BookingAgent"
    PROGRAM_ADMIN = "ProgramAdmin"


# ---------------------------------------------------------------------------
# Status enums — PRD §3.1, §3.2, §3.3, §3.4, §3.5, §3.7
# ---------------------------------------------------------------------------
class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class MemberTier(str, Enum):
    BASIC = "BASIC"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class TierSource(str, Enum):
    EARNED = "EARNED"
    STATUS_MATCH = "STATUS_MATCH"


class HomeRegion(str, Enum):
    DOMESTIC = "DOMESTIC"
    INTERNATIONAL = "INTERNATIONAL"


class FlightStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DEPARTED = "DEPARTED"
    CANCELLED = "CANCELLED"


class Cabin(str, Enum):
    ECONOMY = "ECONOMY"
    BUSINESS = "BUSINESS"
    FIRST = "FIRST"


class FlightSegmentStatus(str, Enum):
    BOOKED = "BOOKED"
    FLOWN = "FLOWN"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class PointsTransactionKind(str, Enum):
    ACCRUAL = "ACCRUAL"
    REDEMPTION = "REDEMPTION"
    REDEMPTION_REFUND = "REDEMPTION_REFUND"
    GIFT_OUT = "GIFT_OUT"
    GIFT_IN = "GIFT_IN"
    GIFT_FEE = "GIFT_FEE"
    EXPIRATION = "EXPIRATION"
    STATUS_MATCH_BONUS = "STATUS_MATCH_BONUS"
    ADMIN_ADJUSTMENT = "ADMIN_ADJUSTMENT"


class StatusMatchRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class UpgradeRequestStatus(str, Enum):
    WAITLISTED = "WAITLISTED"
    CONFIRMED = "CONFIRMED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class AwardBookingStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"
    EXPIRED = "EXPIRED"


class AwardBookingPricingMode(str, Enum):
    DYNAMIC = "DYNAMIC"
    FIXED = "FIXED"


class CompanionCertificateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESERVED = "RESERVED"
    USED = "USED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class CompanionCertificateIssuedReason(str, Enum):
    TIER_REACHED_PLATINUM = "TIER_REACHED_PLATINUM"
    ADMIN_GRANT = "ADMIN_GRANT"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true) — carry id + created_at + updated_at + version.
# ---------------------------------------------------------------------------
class Member(TypedDict, total=False):
    id: str
    email: str
    display_name: str
    home_region: str
    status: str
    tier: str
    tier_source: str
    tier_valid_through_year: int
    points_balance: int
    current_year_qualifying_segments: int
    current_year_qualifying_points: int
    current_membership_year: int
    last_activity_at: Optional[str]
    projected_tier_eoy: str
    created_at: str
    updated_at: str
    version: int


class Flight(TypedDict, total=False):
    id: str
    flight_number: str
    origin: str
    destination: str
    distance_miles: int
    route_region: str
    departure_at: str
    status: str
    base_fare_cents: int
    capacity_economy: int
    capacity_business: int
    capacity_first: int
    upgrade_inventory_business: int
    upgrade_inventory_first: int
    load_factor: float
    created_at: str
    updated_at: str
    version: int


class FlightSegment(TypedDict, total=False):
    id: str
    member_id: str
    flight_id: str
    booked_cabin: str
    flown_cabin: Optional[str]
    status: str
    flown_year: Optional[int]
    qualifying_points_earned: Optional[int]
    created_at: str
    updated_at: str
    version: int


class StatusMatchRequest(TypedDict, total=False):
    id: str
    member_id: str
    competitor_program: str
    competitor_tier: str
    evidence_url: str
    status: str
    granted_tier: Optional[str]
    granted_at: Optional[str]
    activated_at: Optional[str]
    expires_at: Optional[str]
    cooling_off_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UpgradeRequest(TypedDict, total=False):
    id: str
    member_id: str
    flight_segment_id: str
    flight_id: str
    target_cabin: str
    points_offered: int
    status: str
    waitlist_join_seq: int
    priority_score: int
    held_points: int
    created_at: str
    updated_at: str
    version: int


class AwardBooking(TypedDict, total=False):
    id: str
    member_id: str
    flight_id: str
    cabin: str
    pricing_mode: str
    points_cost: int
    cash_taxes_cents: int
    status: str
    held_until: str
    companion_certificate_id: Optional[str]
    linked_segment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CompanionCertificate(TypedDict, total=False):
    id: str
    member_id: str
    status: str
    issued_at: str
    expires_at: str
    reserved_for_booking_id: Optional[str]
    used_on_booking_id: Optional[str]
    issued_reason: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Immutable append-only entities (common_fields: false) — carry ONLY id +
# created_at. PRD §2.4: "a PointsTransaction is an immutable append-only
# ledger entry that carries only id and created_at, with no updated_at and
# no version; a MembershipYear is an immutable annual snapshot that
# likewise carries only id and created_at, with no updated_at and no
# version."
# ---------------------------------------------------------------------------
class PointsTransaction(TypedDict, total=False):
    id: str
    member_id: str
    created_at: str
    kind: str
    points_delta: int
    qualifying_points: int
    posted_at: str
    expires_at: Optional[str]
    remaining_unredeemed: Optional[int]
    related_segment_id: Optional[str]
    related_booking_id: Optional[str]
    related_certificate_id: Optional[str]
    counterparty_member_id: Optional[str]
    idempotency_key: Optional[str]


class MembershipYear(TypedDict, total=False):
    id: str
    member_id: str
    created_at: str
    year: int
    qualifying_segments_final: int
    qualifying_points_final: int
    starting_tier: str
    awarded_tier: str


__all__ = [
    "AwardBooking",
    "AwardBookingPricingMode",
    "AwardBookingStatus",
    "Cabin",
    "CompanionCertificate",
    "CompanionCertificateIssuedReason",
    "CompanionCertificateStatus",
    "Flight",
    "FlightSegment",
    "FlightSegmentStatus",
    "FlightStatus",
    "HomeRegion",
    "Member",
    "MemberStatus",
    "MemberTier",
    "MembershipYear",
    "PointsTransaction",
    "PointsTransactionKind",
    "StatusMatchRequest",
    "StatusMatchRequestStatus",
    "TierSource",
    "UpgradeRequest",
    "UpgradeRequestStatus",
    "UserRole",
]
