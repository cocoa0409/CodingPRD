"""Domain types for the Hotel Revenue Management API.

Status enums and entity TypedDicts derived from PRD §2.4 (common resource
properties and versioning) and the entity / state-machine prose in §3.

PRD §2.4 distinguishes two field-shape classes:
- Versioned entities (RoomType, Room, MaintenanceBlock, Channel, RatePlan,
  RateOverride, OverbookingPolicy, Reservation): expose `id`, `created_at`,
  `updated_at`, and `version`.
- Append-only / immutable join records (ChannelRatePlanMapping, AuditLog):
  expose only `id` and `created_at`. Tests MUST NOT assert `updated_at`
  or `version` on these.
"""
from __future__ import annotations
from enum import Enum
from typing import TypedDict, Optional, List, Any


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    REVENUE_ANALYST = "RevenueAnalyst"
    REVENUE_MANAGER = "RevenueManager"
    RESERVATIONS_AGENT = "ReservationsAgent"
    FRONT_DESK_CLERK = "FrontDeskClerk"
    HOUSEKEEPING_STAFF = "HousekeepingStaff"
    GUEST = "Guest"


# ---------------------------------------------------------------------------
# RoomType / Room / MaintenanceBlock enums (PRD §3.1)
# ---------------------------------------------------------------------------
class RoomTypeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class RoomHousekeepingStatus(str, Enum):
    VACANT_CLEAN = "VACANT_CLEAN"
    OCCUPIED = "OCCUPIED"
    DIRTY = "DIRTY"


class RoomOperationalStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_ORDER = "OUT_OF_ORDER"


class RoomLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class MaintenanceBlockStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Channel / RatePlan / Mapping enums (PRD §3.2)
# ---------------------------------------------------------------------------
class ChannelType(str, Enum):
    DIRECT = "DIRECT"
    OTA = "OTA"
    GDS = "GDS"
    WHOLESALER = "WHOLESALER"


class ChannelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RatePlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class RefundTier(str, Enum):
    FLEXIBLE = "FLEXIBLE"
    MODERATE = "MODERATE"
    STRICT = "STRICT"
    NON_REFUNDABLE = "NON_REFUNDABLE"


# ---------------------------------------------------------------------------
# RateOverride / OverbookingPolicy enums (PRD §3.3, §3.4)
# ---------------------------------------------------------------------------
class RateOverrideStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class RecommendationSource(str, Enum):
    SYSTEM_ENGINE = "SYSTEM_ENGINE"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


class OverbookingPolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


# ---------------------------------------------------------------------------
# Reservation parallel state dimensions (PRD §3.5)
# ---------------------------------------------------------------------------
class BookingStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    WALKED_OUT = "WALKED_OUT"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    REFUNDED_PARTIAL = "REFUNDED_PARTIAL"
    REFUNDED_FULL = "REFUNDED_FULL"
    CHARGEBACK = "CHARGEBACK"


class DisputeStatus(str, Enum):
    NONE = "NONE"
    OPEN = "OPEN"
    RESOLVED_GUEST = "RESOLVED_GUEST"
    RESOLVED_HOTEL = "RESOLVED_HOTEL"


# ---------------------------------------------------------------------------
# Audit (PRD §2.10)
# ---------------------------------------------------------------------------
class AuditEventType(str, Enum):
    RATE_OVERRIDE_APPROVED = "RATE_OVERRIDE_APPROVED"
    RATE_OVERRIDE_REJECTED = "RATE_OVERRIDE_REJECTED"
    OVERBOOKING_ACCEPTED = "OVERBOOKING_ACCEPTED"
    WALKOUT_EXECUTED = "WALKOUT_EXECUTED"
    RATE_PARITY_VIOLATION_DETECTED = "RATE_PARITY_VIOLATION_DETECTED"


class DisputeResolution(str, Enum):
    GUEST = "GUEST"
    HOTEL = "HOTEL"


# ===========================================================================
# Versioned entities (PRD §2.4: id, created_at, updated_at, version)
# ===========================================================================
class RoomType(TypedDict, total=False):
    id: str
    code: str
    name: str
    base_rate_cents: int
    max_occupancy: int
    total_physical_rooms: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict, total=False):
    id: str
    room_number: str
    room_type_id: str
    housekeeping_status: str
    operational_status: str
    lifecycle_status: str
    current_reservation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceBlock(TypedDict, total=False):
    id: str
    room_id: str
    start_date: str
    end_date: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Channel(TypedDict, total=False):
    id: str
    code: str
    channel_type: str
    commission_basis_points: int
    priority_rank: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RatePlan(TypedDict, total=False):
    id: str
    code: str
    room_type_id: str
    refund_tier_code: str
    modification_allowed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RateOverride(TypedDict, total=False):
    id: str
    room_type_id: str
    stay_date: str
    proposed_rate_cents: int
    recommendation_source: str
    status: str
    approved_by: Optional[str]
    applied_rate_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class OverbookingPolicy(TypedDict, total=False):
    id: str
    room_type_id: str
    stay_date: str
    overbook_ratio_basis_points: int
    estimated_no_show_probability_basis_points: int
    walkout_compensation_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict, total=False):
    id: str
    guest_name: str
    room_type_id: str
    rate_plan_id: str
    channel_id: str
    assigned_room_id: Optional[str]
    check_in_date: str
    check_out_date: str
    nights: int
    booking_status: str
    payment_status: str
    booked_total_cents: int
    refund_amount_cents: int
    no_show_charge_cents: int
    walkout_compensation_cents: int
    cancelled_at: Optional[str]
    dispute_status: str
    created_at: str
    updated_at: str
    version: int


# ===========================================================================
# Append-only / immutable join (PRD §2.4: only id + created_at)
# ===========================================================================
class ChannelRatePlanMapping(TypedDict, total=False):
    id: str
    channel_id: str
    rate_plan_id: str
    inventory_share_basis_points: int
    enabled: bool
    created_at: str


class AuditLog(TypedDict, total=False):
    id: str
    event_type: str
    actor_role: str
    actor_id: str
    subject_entity: str
    subject_id: str
    payload: Any
    occurred_at: str
    created_at: str


# ===========================================================================
# Walk-out cost estimate response shape (PRD §3.4)
# ===========================================================================
class WalkoutCostEstimate(TypedDict, total=False):
    room_type_id: str
    stay_date: str
    expected_walkouts: float
    estimated_cost_cents: int
