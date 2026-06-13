"""Domain types: entity TypedDicts, status enums, role enum (CSA Box API)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ────────────────────────────────────────────────────────────

class SeasonStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class BillingStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class FulfillmentStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_SEASON = "IN_SEASON"
    COMPLETED = "COMPLETED"


class SubscriptionAddOnStatus(str, Enum):
    ATTACHED = "ATTACHED"
    DETACHED = "DETACHED"


class WeeklyBoxStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    PACKED = "PACKED"
    DELIVERED = "DELIVERED"
    SKIPPED = "SKIPPED"


class VacationHoldMode(str, Enum):
    REFUND = "REFUND"
    SWAP = "SWAP"


class VacationHoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    CONSUMED = "CONSUMED"


class WaitlistStatus(str, Enum):
    WAITING = "WAITING"
    OFFERED = "OFFERED"
    CONVERTED = "CONVERTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class WorkShareStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class PickupSiteKind(str, Enum):
    PICKUP = "PICKUP"
    HOME_DELIVERY = "HOME_DELIVERY"


class ShareSize(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class AddOnKind(str, Enum):
    EGGS = "EGGS"
    FLOWERS = "FLOWERS"


class SlidingScaleTier(str, Enum):
    SOLIDARITY = "SOLIDARITY"
    BASELINE = "BASELINE"
    SUSTAINER = "SUSTAINER"


class LedgerEntryType(str, Enum):
    CHARGE_SEASON = "CHARGE_SEASON"
    CHARGE_ADDON = "CHARGE_ADDON"
    CHARGE_SURCHARGE = "CHARGE_SURCHARGE"
    CREDIT_WORKSHARE = "CREDIT_WORKSHARE"
    CREDIT_HOLD_REFUND = "CREDIT_HOLD_REFUND"
    PAYMENT = "PAYMENT"


class UserRole(str, Enum):
    FARM_MANAGER = "FarmManager"
    DELIVERY_COORDINATOR = "DeliveryCoordinator"
    MEMBER = "Member"
    PLATFORM_ADMIN = "PlatformAdmin"
    ANONYMOUS = "Anonymous"


# ─── Entity TypedDicts ───────────────────────────────────────────────────────
# Entities below carry the full id/created_at/updated_at/version set, except
# LedgerEntry, which is append-only and carries only id + created_at.

class Season(TypedDict):
    id: str
    name: str
    week_count: int
    first_delivery_date: str
    signup_close_date: str
    status: str
    total_share_capacity: int
    confirmed_share_count: int
    created_at: str
    updated_at: str
    version: int


class PickupSite(TypedDict):
    id: str
    season_id: str
    name: str
    kind: str
    weekly_capacity: int
    delivery_surcharge_cents: int
    active_subscription_count: int
    created_at: str
    updated_at: str
    version: int


class ShareType(TypedDict):
    id: str
    season_id: str
    size: str
    base_price_cents: int
    items_per_box: int
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    season_id: str
    kind: str
    weekly_price_cents: int
    weekly_supply_cap: int
    committed_count: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    email: str
    full_name: str
    sliding_scale_tier: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    season_id: str
    member_id: str
    share_type_id: str
    current_site_id: str
    working_share_opt_in: bool
    billing_status: str
    fulfillment_status: str
    season_price_cents: int
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class SubscriptionAddOn(TypedDict):
    id: str
    subscription_id: str
    add_on_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WeeklyBox(TypedDict):
    id: str
    subscription_id: str
    week_index: int
    site_id: str
    status: str
    item_count: int
    created_at: str
    updated_at: str
    version: int


class VacationHold(TypedDict):
    id: str
    subscription_id: str
    held_box_id: str
    swap_target_box_id: Optional[str]
    mode: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict):
    id: str
    season_id: str
    member_id: str
    share_type_id: str
    requested_site_id: str
    status: str
    offer_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkShareShift(TypedDict):
    id: str
    subscription_id: str
    scheduled_date: str
    hours: float
    status: str
    credit_earned_cents: int
    created_at: str
    updated_at: str
    version: int


# LedgerEntry is append-only (common_fields: false): id + created_at only,
# NO updated_at, NO version.
class LedgerEntry(TypedDict):
    id: str
    subscription_id: str
    entry_type: str
    amount_cents: int
    memo: str
    created_at: str
