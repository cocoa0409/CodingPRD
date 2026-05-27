"""Domain types: entity TypedDicts, status enums, role enum.

Per PRD §2.4: Member, Property, Host, GamingSession, CompRoomBooking,
HostAssignment, and AnnualResetRun all carry common fields (id, created_at,
updated_at, version). SelfExclusion and VelocityAlert are append-only audit
rows — they carry only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────────────────────────

class MemberTierStatus(str, Enum):
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"
    DIAMOND = "DIAMOND"
    SEVEN_STARS = "SEVEN_STARS"


class MemberExclusionStatus(str, Enum):
    NOT_EXCLUDED = "NOT_EXCLUDED"
    EXCLUDED = "EXCLUDED"
    REINSTATED = "REINSTATED"


class MemberVelocityStatus(str, Enum):
    NORMAL = "NORMAL"
    FLAGGED = "FLAGGED"
    SUSPENDED = "SUSPENDED"


class PropertyStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class PropertyMarketSegment(str, Enum):
    VEGAS_STRIP = "VEGAS_STRIP"
    REGIONAL = "REGIONAL"
    INTERNATIONAL = "INTERNATIONAL"


class HostStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class GamingSessionStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class GameType(str, Enum):
    SLOTS = "SLOTS"
    TABLE_GAMES = "TABLE_GAMES"
    POKER = "POKER"


class CompRoomBookingStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SelfExclusionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REINSTATED = "REINSTATED"
    EXPIRED = "EXPIRED"


class HostAssignmentStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    REJECTED = "REJECTED"


class VelocityAlertSeverity(str, Enum):
    FLAGGED = "FLAGGED"
    SUSPENDED = "SUSPENDED"


class AnnualResetRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    Member = "Member"
    MemberServices = "MemberServices"
    LoyaltyManager = "LoyaltyManager"
    ComplianceOfficer = "ComplianceOfficer"


# ─── Entity TypedDicts ────────────────────────────────────────────────────

# common_fields: true — carries id + created_at + updated_at + version.

class Member(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    home_property_id: str
    tier_status: str
    tier_credits_ytd: float
    tier_credits_lifetime: float
    exclusion_status: str
    velocity_status: str
    assigned_host_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict, total=False):
    id: str
    name: str
    market_segment: str
    base_room_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Host(TypedDict, total=False):
    id: str
    employee_email: str
    home_property_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GamingSession(TypedDict, total=False):
    id: str
    member_id: str
    property_id: str
    started_at: str
    ended_at: str
    game_type: str
    theoretical_loss_cents: int
    tier_credits_earned: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CompRoomBooking(TypedDict, total=False):
    id: str
    member_id: str
    property_id: str
    check_in: str
    check_out: str
    nights: int
    provisional_rate_cents: int
    final_rate_cents: Optional[int]
    total_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HostAssignment(TypedDict, total=False):
    id: str
    member_id: str
    host_id: str
    assigned_by_user_id: str
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AnnualResetRun(TypedDict, total=False):
    id: str
    reset_year: int
    scheduled_for: str
    status: str
    members_reset_count: int
    tier_credits_lifetime_invariant_before_cents: int
    tier_credits_lifetime_invariant_after_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only audit rows. Only id + created_at.

class SelfExclusion(TypedDict, total=False):
    id: str
    member_id: str
    requested_at: str
    exclusion_until: str
    reason: str
    status: str
    created_at: str


class VelocityAlert(TypedDict, total=False):
    id: str
    member_id: str
    window_start: str
    window_end: str
    total_theoretical_loss_cents: int
    severity: str
    created_at: str
