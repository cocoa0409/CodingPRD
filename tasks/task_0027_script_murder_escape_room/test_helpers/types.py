"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the PRD entity model. Entities other than AuditLogEntry carry the four
common fields (id, created_at, updated_at, version) per PRD §2.4. AuditLogEntry
is append-only and carries only id and created_at.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ─── User / Role ──────────────────────────────────────────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    VENUE_OPERATOR = "VenueOperator"
    SCRIPT_AUTHOR = "ScriptAuthor"
    HOST = "Host"
    NPC = "NPC"
    PLAYER = "Player"
    CONTENT_MODERATOR = "ContentModerator"
    PAYMENT_GATEWAY = "PaymentGateway"


# ─── Status enums (PRD §3) ────────────────────────────────────────────────

class VenueStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class RoomStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ThemeStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class ThemeGenre(str, Enum):
    MYSTERY = "MYSTERY"
    HORROR = "HORROR"
    EMOTIONAL = "EMOTIONAL"
    SCIFI = "SCIFI"
    COMEDY = "COMEDY"
    PUZZLE = "PUZZLE"


class ThemeDifficulty(str, Enum):
    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"
    EXPERT = "EXPERT"


class MaintenanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class SlotScheduleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SlotMatchStatus(str, Enum):
    OPEN = "OPEN"
    MATCHED = "MATCHED"
    MATCH_FAILED = "MATCH_FAILED"


class SlotVisibility(str, Enum):
    PRIVATE_ONLY = "PRIVATE_ONLY"
    PUBLIC_TEAMUP = "PUBLIC_TEAMUP"


class BookingStatus(str, Enum):
    PENDING_DEPOSIT = "PENDING_DEPOSIT"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class CancellationInitiator(str, Enum):
    PLAYER = "PLAYER"
    VENUE = "VENUE"
    SYSTEM_MATCH_FAIL = "SYSTEM_MATCH_FAIL"
    NO_SHOW = "NO_SHOW"


class WaitlistStatus(str, Enum):
    QUEUED = "QUEUED"
    PROMOTED = "PROMOTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class WaitlistPriorityClass(str, Enum):
    VIP = "VIP"
    STANDARD = "STANDARD"


class PlayerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BANNED = "BANNED"


class PlayerGender(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    UNDISCLOSED = "UNDISCLOSED"


class PlayerExperience(str, Enum):
    NOVICE = "NOVICE"
    INTERMEDIATE = "INTERMEDIATE"
    VETERAN = "VETERAN"


class PlayerTier(str, Enum):
    STANDARD = "STANDARD"
    VIP = "VIP"


class StaffStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    TERMINATED = "TERMINATED"


class StaffRole(str, Enum):
    HOST = "HOST"
    NPC = "NPC"


class StaffAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HANDED_OFF = "HANDED_OFF"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReviewStatus(str, Enum):
    PENDING_MODERATION = "PENDING_MODERATION"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"
    REVISED = "REVISED"
    HIDDEN = "HIDDEN"


class ModerationDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    HIDE = "HIDE"


class SettlementRunStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    REVERSED = "REVERSED"


class AuditAction(str, Enum):
    BOOKING_CREATED = "BOOKING_CREATED"
    BOOKING_CANCELLED = "BOOKING_CANCELLED"
    BOOKING_NO_SHOW_MARKED = "BOOKING_NO_SHOW_MARKED"
    BOOKING_REFUNDED = "BOOKING_REFUNDED"
    REVIEW_SUBMITTED = "REVIEW_SUBMITTED"
    REVIEW_PUBLISHED = "REVIEW_PUBLISHED"
    REVIEW_REJECTED = "REVIEW_REJECTED"
    REVIEW_HIDDEN = "REVIEW_HIDDEN"
    SETTLEMENT_FINALIZED = "SETTLEMENT_FINALIZED"
    SETTLEMENT_REVERSED = "SETTLEMENT_REVERSED"


class AuditSubjectType(str, Enum):
    BOOKING = "Booking"
    REVIEW = "Review"
    SETTLEMENT_RUN = "SettlementRun"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# Common-fields entities carry id, created_at, updated_at, version per PRD §2.4.

class Venue(TypedDict, total=False):
    id: str
    chain_id: str
    name: str
    timezone: str
    business_hours: dict
    deposit_policy_cents: int
    revenue_share_bps: int
    author_royalty_bps: int
    host_commission_bps: int
    platform_fee_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict, total=False):
    id: str
    venue_id: str
    name: str
    capacity_min: int
    capacity_max: int
    turnover_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Theme(TypedDict, total=False):
    id: str
    chain_id: str
    title: str
    genre: str
    difficulty: str
    duration_minutes: int
    min_players: int
    max_players: int
    required_host_qualifications: List[str]
    required_npc_count: int
    compatible_room_ids: List[str]
    base_price_cents: int
    author_royalty_bps_override: Optional[int]
    current_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceWindow(TypedDict, total=False):
    id: str
    room_id: str
    starts_at: str
    ends_at: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SessionSlot(TypedDict, total=False):
    id: str
    venue_id: str
    room_id: str
    theme_id: str
    theme_version_pinned: int
    starts_at: str
    ends_at: str
    price_cents: int
    visibility: str
    required_seats_for_launch: int
    schedule_status: str
    match_status: str
    confirmed_seat_count: int
    match_deadline_at: str
    gross_revenue_cents: int
    net_revenue_cents: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    slot_id: str
    lead_player_id: str
    team_player_ids: List[str]
    seat_count: int
    paid_amount_cents: int
    deposit_held_cents: int
    refund_total_cents: int
    cancellation_initiator: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict, total=False):
    id: str
    slot_id: str
    lead_player_id: str
    requested_seat_count: int
    priority_class: str
    enqueued_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Player(TypedDict, total=False):
    id: str
    display_name: str
    gender: str
    age: int
    experience_level: str
    tier: str
    no_show_strikes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict, total=False):
    id: str
    chain_id: str
    display_name: str
    roles_held: List[str]
    qualifications: List[str]
    max_weekly_minutes: int
    commission_bps_override: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class StaffAssignment(TypedDict, total=False):
    id: str
    slot_id: str
    staff_member_id: str
    role_type: str
    assignment_minutes: int
    substitute_of_assignment_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Review(TypedDict, total=False):
    id: str
    booking_id: str
    author_player_id: str
    theme_score: int
    host_score: Optional[int]
    venue_score: int
    comment: str
    spam_signal_count: int
    moderation_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SettlementRun(TypedDict, total=False):
    id: str
    chain_id: str
    period_starts_at: str
    period_ends_at: str
    included_session_ids: List[str]
    gross_total_cents: int
    venue_payout_cents: int
    author_payout_cents: int
    host_payout_cents: int
    platform_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# AuditLogEntry — append-only: PRD §2.4 explicitly says it has neither updated_at
# nor version. Keep id + created_at only plus action-specific fields.
class AuditLogEntry(TypedDict, total=False):
    id: str
    created_at: str
    actor_user_id: str
    actor_role: str
    subject_entity_type: str
    subject_entity_id: str
    action: str
    payload_snapshot: dict
