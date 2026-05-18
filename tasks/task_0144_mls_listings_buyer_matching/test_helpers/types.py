"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.11 fixes the state vocabulary for every mutable entity. PRD §2.4
distinguishes mutable resources (id + created_at + updated_at + version)
from immutable resources (Counter, CommissionSplit: id + created_at only).
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    LISTING_AGENT = "ListingAgent"
    BUYER_AGENT = "BuyerAgent"
    MLS_ADMIN = "MlsAdmin"


# ---------------------------------------------------------------------------
# Status enums — PRD §2.11
# ---------------------------------------------------------------------------
class AgentRole(str, Enum):
    LISTING_AGENT = "LISTING_AGENT"
    BUYER_AGENT = "BUYER_AGENT"
    DUAL_AGENT = "DUAL_AGENT"


class AgentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ListingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    SOLD = "SOLD"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class BuyerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SOLD = "SOLD"
    WITHDRAWN = "WITHDRAWN"


class LockboxStatus(str, Enum):
    ARMED = "ARMED"
    DISARMED = "DISARMED"
    RETIRED = "RETIRED"


class ShowingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class OfferStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class CounterStatus(str, Enum):
    OPEN = "OPEN"
    REBOUND = "REBOUND"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class ContingencyStatus(str, Enum):
    PENDING = "PENDING"
    SATISFIED = "SATISFIED"
    WAIVED = "WAIVED"
    FAILED = "FAILED"


class ContingencyKind(str, Enum):
    INSPECTION = "INSPECTION"
    APPRAISAL = "APPRAISAL"
    FINANCING = "FINANCING"


class CommissionSplitVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


# ---------------------------------------------------------------------------
# Mutable entities — PRD §2.4: id + created_at + updated_at + version.
# ---------------------------------------------------------------------------
class Agent(TypedDict, total=False):
    id: str
    full_name: str
    brokerage_name: str
    agent_role: str
    license_number: str
    brokerage_split_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict, total=False):
    id: str
    listing_agent_id: str
    address_line: str
    zip_code: str
    list_price_cents: int
    bedrooms: int
    bathrooms: float
    features: List[str]
    co_op_pct: float
    total_commission_pct: float
    status: str
    accepted_offer_id: Optional[str]
    showing_count: int
    created_at: str
    updated_at: str
    version: int


class Buyer(TypedDict, total=False):
    id: str
    buyer_agent_id: str
    full_name: str
    max_price_cents: int
    min_price_cents: int
    min_bedrooms: int
    min_bathrooms: float
    desired_zips: List[str]
    desired_features: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Lockbox(TypedDict, total=False):
    id: str
    listing_id: str
    serial_number: str
    access_code: str
    code_rotated_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ShowingAppointment(TypedDict, total=False):
    id: str
    listing_id: str
    buyer_agent_id: str
    buyer_id: str
    start_at: str
    end_at: str
    status: str
    lockbox_access_granted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict, total=False):
    id: str
    listing_id: str
    buyer_id: str
    offer_price_cents: int
    earnest_money_cents: int
    estimated_seller_concessions_cents: int
    round_no: int
    parent_counter_id: Optional[str]
    status: str
    expires_at: str
    provisional_net_to_seller_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Contingency(TypedDict, total=False):
    id: str
    offer_id: str
    kind: str
    deadline_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Immutable entities — PRD §2.4: id + created_at only.
# Counter and CommissionSplit carry neither updated_at nor version because
# their content does not change after the row is emitted.
# ---------------------------------------------------------------------------
class Counter(TypedDict, total=False):
    id: str
    offer_id: str
    counter_price_cents: int
    counter_concessions_cents: int
    counter_expires_at: str
    status: str
    created_at: str


class CommissionSplit(TypedDict, total=False):
    id: str
    listing_id: str
    offer_id: str
    sale_price_cents: int
    gross_commission_cents: int
    listing_side_cents: int
    buyer_side_cents: int
    listing_agent_cents: int
    listing_brokerage_cents: int
    buyer_agent_cents: int
    buyer_brokerage_cents: int
    variant: str
    created_at: str


__all__ = [
    "UserRole",
    "AgentRole",
    "AgentStatus",
    "ListingStatus",
    "BuyerStatus",
    "LockboxStatus",
    "ShowingStatus",
    "OfferStatus",
    "CounterStatus",
    "ContingencyStatus",
    "ContingencyKind",
    "CommissionSplitVariant",
    "Agent",
    "Listing",
    "Buyer",
    "Lockbox",
    "ShowingAppointment",
    "Offer",
    "Contingency",
    "Counter",
    "CommissionSplit",
]
