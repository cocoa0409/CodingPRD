"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the entities and state machines described in the Local Classifieds
Marketplace PRD (Sections 2-3). Entities that the PRD declares to carry only
id + created_at (Category, Message, SafeTradeSpot, Alert) omit updated_at and
version from their TypedDicts.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Status enums ---

class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BANNED = "BANNED"


class RoleKind(str, Enum):
    SELLER = "SELLER"
    BUYER = "BUYER"
    BOTH = "BOTH"


class PublicationStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REMOVED = "REMOVED"


class SaleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    SOLD = "SOLD"


class ConversationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class OfferStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class ActorSide(str, Enum):
    BUYER = "BUYER"
    SELLER = "SELLER"


class MeetupStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class FlagTargetType(str, Enum):
    LISTING = "LISTING"
    MEMBER = "MEMBER"


class FlagReason(str, Enum):
    SPAM = "SPAM"
    PROHIBITED = "PROHIBITED"
    SCAM = "SCAM"
    MISCATEGORIZED = "MISCATEGORIZED"
    OTHER = "OTHER"


class FlagStatus(str, Enum):
    OPEN = "OPEN"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    SELLER = "Seller"
    BUYER = "Buyer"
    MEMBER = "Member"
    MODERATOR = "Moderator"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Entity TypedDicts ---

# common_fields: true -> id + created_at + updated_at + version
class Member(TypedDict, total=False):
    id: str
    email: str
    display_name: str
    role_kind: str
    status: str
    phone_verified: bool
    verification_code: Optional[str]
    trust_score: int
    upheld_flag_count: int
    active_listing_count: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> id + created_at only
class Category(TypedDict, total=False):
    id: str
    slug: str
    name: str
    requires_phone_verified_seller: bool
    max_price_cents: int
    created_at: str


# common_fields: true
class Listing(TypedDict, total=False):
    id: str
    seller_id: str
    category_slug: str
    title: str
    description: str
    ask_price_cents: int
    min_acceptable_price_cents: int
    publication_status: str
    sale_status: str
    expires_at: Optional[str]
    renewal_count: int
    open_offer_count: int
    active_flag_count: int
    accepted_offer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Conversation(TypedDict, total=False):
    id: str
    listing_id: str
    buyer_id: str
    seller_id: str
    status: str
    message_count: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false
class Message(TypedDict, total=False):
    id: str
    conversation_id: str
    sender_id: str
    body: str
    created_at: str


# common_fields: true
class Offer(TypedDict, total=False):
    id: str
    conversation_id: str
    listing_id: str
    buyer_id: str
    seller_id: str
    amount_cents: int
    last_actor_side: str
    round_count: int
    status: str
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false
class SafeTradeSpot(TypedDict, total=False):
    id: str
    name: str
    is_police_verified: bool
    open_minute_of_day: int
    close_minute_of_day: int
    created_at: str


# common_fields: true
class Meetup(TypedDict, total=False):
    id: str
    offer_id: str
    listing_id: str
    spot_id: str
    buyer_id: str
    seller_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Flag(TypedDict, total=False):
    id: str
    reporter_id: str
    target_type: str
    target_listing_id: Optional[str]
    target_member_id: Optional[str]
    reason: str
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class SavedSearch(TypedDict, total=False):
    id: str
    owner_id: str
    category_slug: str
    keyword: Optional[str]
    max_price_cents: int
    alert_count: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false
class Alert(TypedDict, total=False):
    id: str
    saved_search_id: str
    listing_id: str
    matched_at: str
    created_at: str
