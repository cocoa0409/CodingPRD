"""Domain types: entity TypedDicts, status enums, role enum.

Per PRD §2.4, every resource carries (id, created_at, updated_at, version) — the
PRD explicitly states "All nine entities in this system maintain the full quartet".
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ──────────────────────────────────────────────────────────

class WeddingStatus(str, Enum):
    DRAFT = "DRAFT"
    RSVP_OPEN = "RSVP_OPEN"
    RSVP_CLOSED = "RSVP_CLOSED"
    SEATED = "SEATED"
    ARCHIVED = "ARCHIVED"


class GuestRsvpStatus(str, Enum):
    INVITED = "INVITED"
    ATTENDING = "ATTENDING"
    DECLINED = "DECLINED"


class PlusOneRsvpStatus(str, Enum):
    ATTENDING = "ATTENDING"
    DECLINED = "DECLINED"


class AssigneeType(str, Enum):
    GUEST = "GUEST"
    PLUS_ONE = "PLUS_ONE"


class RegistryItemStatus(str, Enum):
    OPEN = "OPEN"
    FULFILLED = "FULFILLED"
    ARCHIVED = "ARCHIVED"


class PurchaseStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    PENDING_REVIEW = "PENDING_REVIEW"
    CANCELLED = "CANCELLED"


class ThankYouStatus(str, Enum):
    PENDING = "PENDING"
    DRAFTED = "DRAFTED"
    SENT = "SENT"


class UserRole(str, Enum):
    COUPLE = "Couple"
    GUEST_SELF = "GuestSelf"
    PLATFORM_INTEGRATION = "PlatformIntegration"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Entity TypedDicts (all carry the full id+created_at+updated_at+version quartet
#     per PRD §2.4) ───────────────────────────────────────────────────────────

class Wedding(TypedDict):
    id: str
    couple_user_id: str
    title: str
    ceremony_at: str
    rsvp_deadline_at: str
    status: str
    seating_dirty: bool
    total_capacity: int
    created_at: str
    updated_at: str
    version: int


class MealOption(TypedDict):
    id: str
    wedding_id: str
    code: str
    label: str
    is_kids: bool
    max_servings: int
    created_at: str
    updated_at: str
    version: int


class Table(TypedDict):
    id: str
    wedding_id: str
    table_number: int
    capacity: int
    kids_only: bool
    created_at: str
    updated_at: str
    version: int


class Guest(TypedDict):
    id: str
    wedding_id: str
    full_name: str
    email: str
    is_child: bool
    plus_one_allowed: bool
    rsvp_status: str
    meal_option_id: Optional[str]
    invitation_token: str
    created_at: str
    updated_at: str
    version: int


class PlusOne(TypedDict):
    id: str
    guest_id: str
    wedding_id: str
    full_name: str
    is_child: bool
    rsvp_status: str
    meal_option_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SeatingAssignment(TypedDict):
    id: str
    wedding_id: str
    table_id: str
    assignee_type: str
    assignee_id: str
    created_at: str
    updated_at: str
    version: int


class RegistryItem(TypedDict):
    id: str
    wedding_id: str
    sku: str
    title: str
    target_quantity: int
    unit_price_cents: int
    status: str
    fulfilled_quantity: int
    pending_quantity: int
    created_at: str
    updated_at: str
    version: int


class Purchase(TypedDict):
    id: str
    registry_item_id: str
    platform_code: str
    external_purchase_id: str
    purchaser_name: str
    quantity: int
    occurred_at: str
    status: str
    dup_of_purchase_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ThankYouNote(TypedDict):
    id: str
    purchase_id: str
    wedding_id: str
    status: str
    drafted_body: Optional[str]
    sent_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
