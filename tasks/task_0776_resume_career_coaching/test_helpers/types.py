"""Domain types: entity TypedDicts, status enums, role enum.

All names use the PRD's terminology. Entities that the PRD describes as full,
versioned resources carry id/created_at/updated_at/version; the deliberately
lighter records (PackagePlan, Payment, AtsScan) carry only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict


# --- Role enum ---
class UserRole(str, Enum):
    CLIENT = "Client"
    COACH = "Coach"
    CAREER_ADMIN = "CareerAdmin"


# --- Status / kind enums ---
class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CoachStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CoachSpecialty(str, Enum):
    TECH = "TECH"
    FINANCE = "FINANCE"
    GENERAL = "GENERAL"
    EXECUTIVE = "EXECUTIVE"


class PlanTier(str, Enum):
    BASIC = "BASIC"
    PRO = "PRO"
    EXECUTIVE = "EXECUTIVE"


class DeliverableType(str, Enum):
    RESUME = "RESUME"
    LINKEDIN = "LINKEDIN"
    COVER_LETTER = "COVER_LETTER"


class GuaranteeType(str, Enum):
    NONE = "NONE"
    SATISFACTION = "SATISFACTION"
    INTERVIEW = "INTERVIEW"


class OrderStatus(str, Enum):
    INTAKE = "INTAKE"
    IN_PRODUCTION = "IN_PRODUCTION"
    READY = "READY"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    REFUNDED = "REFUNDED"


class DeliverableStatus(str, Enum):
    PENDING = "PENDING"
    DRAFTED = "DRAFTED"
    IN_REVISION = "IN_REVISION"
    APPROVED = "APPROVED"
    CANCELLED = "CANCELLED"


class RevisionStatus(str, Enum):
    OPEN = "OPEN"
    ADDRESSED = "ADDRESSED"
    WITHDRAWN = "WITHDRAWN"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class SessionType(str, Enum):
    COACHING = "COACHING"
    INTERVIEW_PREP = "INTERVIEW_PREP"


class AddOnType(str, Enum):
    EXTRA_REVISION = "EXTRA_REVISION"
    EXTRA_COACHING = "EXTRA_COACHING"
    EXTRA_DELIVERABLE = "EXTRA_DELIVERABLE"
    INTERVIEW_PREP = "INTERVIEW_PREP"
    RUSH = "RUSH"


class AddOnStatus(str, Enum):
    PENDING = "PENDING"
    CHARGED = "CHARGED"
    CANCELLED = "CANCELLED"


class ClaimType(str, Enum):
    SATISFACTION = "SATISFACTION"
    INTERVIEW = "INTERVIEW"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PaymentType(str, Enum):
    CHARGE = "CHARGE"
    REFUND = "REFUND"


class PaymentReason(str, Enum):
    CONFIRM = "CONFIRM"
    REVISION_OVERAGE = "REVISION_OVERAGE"
    SESSION_OVERAGE = "SESSION_OVERAGE"
    MANUAL_ADDON = "MANUAL_ADDON"
    SESSION_REFUND = "SESSION_REFUND"
    GUARANTEE_REFUND = "GUARANTEE_REFUND"


# --- Entity shapes (full, versioned) ---
class Client(TypedDict):
    id: str
    name: str
    email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Coach(TypedDict):
    id: str
    name: str
    email: str
    specialty: str
    buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    client_id: str
    plan_id: str
    target_role: str
    target_industry: str
    rush: bool
    requested_delivery_days: int
    coupon_code: Optional[str]
    status: str
    base_price_cents: int
    addons_subtotal_cents: int
    discount_cents: int
    rush_surcharge_cents: int
    provisional_total_cents: int
    final_total_cents: Optional[int]
    amount_charged_cents: int
    amount_refunded_cents: int
    net_collected_cents: int
    revision_credits_included: int
    revision_credits_purchased: int
    revision_credits_used: int
    revision_credits_remaining: int
    sessions_included: int
    sessions_purchased: int
    sessions_used: int
    deliverables_total: int
    deliverables_approved: int
    guarantee_type: str
    delivered_at: Optional[str]
    deadline_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Deliverable(TypedDict):
    id: str
    order_id: str
    type: str
    status: str
    revision_round_count: int
    draft_count: int
    current_strict_ats_score: Optional[int]
    current_semantic_ats_score: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RevisionRequest(TypedDict):
    id: str
    deliverable_id: str
    round_no: int
    reason: str
    billable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CoachingSession(TypedDict):
    id: str
    order_id: str
    coach_id: str
    client_id: str
    session_type: str
    scheduled_start: str
    scheduled_end: str
    status: str
    billable: bool
    fee_cents: int
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    order_id: str
    type: str
    price_cents: int
    status: str
    auto_generated: bool
    source_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GuaranteeClaim(TypedDict):
    id: str
    order_id: str
    claim_type: str
    status: str
    refund_amount_cents: int
    evidence: str
    created_at: str
    updated_at: str
    version: int


# --- Lightweight records (id + created_at only) ---
class PackagePlan(TypedDict):
    id: str
    tier: str
    base_price_cents: int
    included_deliverables: List[str]
    included_revision_rounds: int
    included_coaching_sessions: int
    includes_interview_prep: bool
    includes_ats: bool
    guarantee_type: str
    rush_surcharge_pct: float
    created_at: str


class Payment(TypedDict):
    id: str
    order_id: str
    type: str
    amount_cents: int
    reason: str
    created_at: str


class AtsScan(TypedDict):
    id: str
    deliverable_id: str
    sections: List[dict]
    strict_score: int
    semantic_score: int
    coverage_by_section: Dict[str, int]
    created_at: str
