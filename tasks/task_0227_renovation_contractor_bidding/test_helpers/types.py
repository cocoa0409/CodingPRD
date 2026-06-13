"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Renovation Contractor Bidding PRD. Every resource in this
domain is mutable, so every entity carries id, created_at, updated_at, version.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum ────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    HOMEOWNER = "Homeowner"
    CONTRACTOR = "Contractor"
    ESCROW_AGENT = "EscrowAgent"
    PLATFORM_ADMIN = "PlatformAdmin"
    ANONYMOUS = "Anonymous"


# ─── Status enums ─────────────────────────────────────────────────────────
class ContractorStatus(str, Enum):
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN_FOR_BIDS = "OPEN_FOR_BIDS"
    AWARDED = "AWARDED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    DISPUTED = "DISPUTED"
    CANCELLED = "CANCELLED"


class BidStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISING = "REVISING"
    AWARDED = "AWARDED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    DRAW_REQUESTED = "DRAW_REQUESTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"


class EscrowStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    FUNDED = "FUNDED"
    CLOSED = "CLOSED"


class DrawStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REJECTED = "REJECTED"
    DISPUTED = "DISPUTED"


class WaiverType(str, Enum):
    CONDITIONAL = "CONDITIONAL"
    UNCONDITIONAL = "UNCONDITIONAL"


class WaiverStatus(str, Enum):
    COLLECTED = "COLLECTED"
    VOIDED = "VOIDED"


class ChangeOrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class DisputeResolution(str, Enum):
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class Trade(str, Enum):
    GENERAL = "GENERAL"
    ELECTRICAL = "ELECTRICAL"
    PLUMBING = "PLUMBING"
    HVAC = "HVAC"
    ROOFING = "ROOFING"


class ScopeUnit(str, Enum):
    SQFT = "SQFT"
    UNIT = "UNIT"
    HOUR = "HOUR"
    LUMP = "LUMP"


# ─── Entity TypedDicts (all carry id/created_at/updated_at/version) ────────
class Contractor(TypedDict):
    id: str
    legal_name: str
    trade: str
    license_number: str
    license_expiry: str
    insurance_coverage_cents: int
    qualification_status: str
    rating_sum: int
    rating_count: int
    average_rating: float
    created_at: str
    updated_at: str
    version: int


class Homeowner(TypedDict):
    id: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict):
    id: str
    homeowner_id: str
    title: str
    budget_cap_cents: int
    bid_deadline: str
    required_trade: str
    min_rating: float
    status: str
    awarded_bid_id: Optional[str]
    contract_value_cents: int
    scope_locked: bool
    created_at: str
    updated_at: str
    version: int


class ScopeLineItem(TypedDict):
    id: str
    project_id: str
    description: str
    quantity: float
    unit: str
    estimated_unit_cost_cents: int
    estimated_total_cents: int
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict):
    id: str
    project_id: str
    contractor_id: str
    total_cents: int
    duration_days: int
    status: str
    rank_score: float
    created_at: str
    updated_at: str
    version: int


class BidLineItem(TypedDict):
    id: str
    bid_id: str
    scope_line_item_id: str
    quantity: float
    unit_price_cents: int
    line_total_cents: int
    created_at: str
    updated_at: str
    version: int


class Milestone(TypedDict):
    id: str
    project_id: str
    sequence: int
    title: str
    release_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Escrow(TypedDict):
    id: str
    project_id: str
    funded_cents: int
    released_cents: int
    retained_cents: int
    available_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Draw(TypedDict):
    id: str
    project_id: str
    milestone_id: str
    contractor_id: str
    gross_amount_cents: int
    retainage_cents: int
    net_release_cents: int
    lien_waiver_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LienWaiver(TypedDict):
    id: str
    project_id: str
    contractor_id: str
    draw_id: str
    waiver_type: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    project_id: str
    bid_id: str
    description: str
    delta_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    project_id: str
    subject_type: str
    subject_id: str
    raised_by: str
    reason: str
    resolution: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
