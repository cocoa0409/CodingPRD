"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes two field-shape classes:

- Resources carrying id + created_at + updated_at + version: WeddingProject,
  Milestone, Vendor, Quote, Contract, ChangeOrder, Settlement, TimelineSlot,
  Guest.

- Append-only / immutable rows carrying only id + created_at:
  ProjectTemplate (immutable library entry), AuditEntry (append-only log),
  PerformanceRating (immutable rating record). Tests MUST NOT assert
  updated_at or version on these.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLANNER = "Planner"
    VENDOR_REP = "VendorRep"
    COUPLE = "Couple"
    AUDITOR = "Auditor"


# ---------------------------------------------------------------------------
# WeddingProject status enums (PRD §3.1, §3.8)
# ---------------------------------------------------------------------------
class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    PLANNING = "PLANNING"
    EXECUTION = "EXECUTION"
    SETTLEMENT = "SETTLEMENT"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ProjectStyle(str, Enum):
    CLASSIC = "CLASSIC"
    RUSTIC = "RUSTIC"
    MODERN = "MODERN"
    DESTINATION = "DESTINATION"


class ProjectScale(str, Enum):
    INTIMATE = "INTIMATE"
    MEDIUM = "MEDIUM"
    GRAND = "GRAND"


# ---------------------------------------------------------------------------
# Milestone (PRD §3.1)
# ---------------------------------------------------------------------------
class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"


# ---------------------------------------------------------------------------
# Vendor + Quote (PRD §3.2)
# ---------------------------------------------------------------------------
class VendorCategory(str, Enum):
    VENUE = "VENUE"
    PHOTOGRAPHY = "PHOTOGRAPHY"
    FLORAL = "FLORAL"
    CATERING = "CATERING"
    MC = "MC"
    BAND = "BAND"


class QualificationStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    OFFERED = "OFFERED"
    BOUND = "BOUND"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


# ---------------------------------------------------------------------------
# Contract (PRD §3.3, §3.4)
# ---------------------------------------------------------------------------
class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    NEGOTIATING = "NEGOTIATING"
    SIGNED = "SIGNED"
    ACCEPTED = "ACCEPTED"
    TERMINATED = "TERMINATED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIAL = "PARTIAL"
    FINALIZED = "FINALIZED"
    REFUNDED = "REFUNDED"


# ---------------------------------------------------------------------------
# ChangeOrder + Settlement (PRD §3.4)
# ---------------------------------------------------------------------------
class ChangeOrderStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    VENDOR_CONFIRMED = "VENDOR_CONFIRMED"
    FINALIZED = "FINALIZED"


# ---------------------------------------------------------------------------
# TimelineSlot (PRD §3.6)
# ---------------------------------------------------------------------------
class SlotKind(str, Enum):
    PREPARATION = "PREPARATION"
    CEREMONY = "CEREMONY"
    RECEPTION = "RECEPTION"


# ---------------------------------------------------------------------------
# Guest (PRD §3.7)
# ---------------------------------------------------------------------------
class RsvpStatus(str, Enum):
    INVITED = "INVITED"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    NO_RESPONSE = "NO_RESPONSE"


# ---------------------------------------------------------------------------
# AuditEntry (PRD §2.10, §3.8)
# ---------------------------------------------------------------------------
class AuditSubjectType(str, Enum):
    BUDGET = "BUDGET"
    CONTRACT = "CONTRACT"
    SETTLEMENT = "SETTLEMENT"
    CHANGE_ORDER = "CHANGE_ORDER"


class AuditEventKind(str, Enum):
    BUDGET_REALLOCATED = "BUDGET_REALLOCATED"
    CHANGE_ORDER_APPROVED = "CHANGE_ORDER_APPROVED"
    CONTRACT_TERMINATED = "CONTRACT_TERMINATED"
    SETTLEMENT_FINALIZED = "SETTLEMENT_FINALIZED"
    OVERSPEND_WARNING_RAISED = "OVERSPEND_WARNING_RAISED"


# ---------------------------------------------------------------------------
# External event hooks (PRD §3.8)
# ---------------------------------------------------------------------------
class ExternalEventKind(str, Enum):
    ESIGN_COMPLETED = "ESIGN_COMPLETED"
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED"
    IM_DELIVERED = "IM_DELIVERED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (mostly for documentation / IDE help; runtime checks live
# in assertions.py).
# ---------------------------------------------------------------------------
class WeddingProject(TypedDict, total=False):
    id: str
    couple_name: str
    ceremony_date: int
    style: str
    scale: str
    planner_user_id: str
    auditor_user_id: str
    template_id: Optional[str]
    status: str
    total_budget_cents: int
    provisional_committed_cents: int
    finalized_settled_cents: int
    budget_balance_cents: int
    rehearsal_version: int
    created_at: str
    updated_at: str
    version: int


class ProjectTemplate(TypedDict, total=False):
    # Append-only / immutable: PRD §2.4 says only id + created_at.
    id: str
    name: str
    scale: str
    default_milestones: List[Any]
    created_at: str


class Milestone(TypedDict, total=False):
    id: str
    project_id: str
    label: str
    due_at: int
    percent_of_budget: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    name: str
    category: str
    qualification_status: str
    avg_performance_rating: Optional[float]
    rating_count: int
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    vendor_id: str
    category: str
    amount_cents: int
    scope_description: str
    valid_until: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    project_id: str
    vendor_id: str
    quote_id: str
    pinned_quote_version: Optional[int]
    pinned_amount_cents: Optional[int]
    contract_status: str
    payment_status: str
    e_sign_envelope_id: Optional[str]
    negotiation_round: int
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict, total=False):
    id: str
    contract_id: str
    delta_amount_cents: int
    reason: str
    requested_by_user_id: str
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    contract_id: str
    provisional_total_cents: int
    breach_deduction_cents: int
    refund_cents: int
    final_amount_cents: int
    status: str
    confirmed_by_vendor_at: Optional[int]
    confirmed_by_user_id: str
    finalized_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TimelineSlot(TypedDict, total=False):
    id: str
    project_id: str
    vendor_id: Optional[str]
    start_at: int
    end_at: int
    setup_buffer_seconds: int
    kind: str
    label: str
    created_at: str
    updated_at: str
    version: int


class Guest(TypedDict, total=False):
    id: str
    project_id: str
    full_name: str
    party_size: int
    rsvp_status: str
    dietary_requirements: List[str]
    accessibility_requirements: List[str]
    table_number: Optional[int]
    gift_amount_cents: int
    thank_you_sent_at: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AuditEntry(TypedDict, total=False):
    # Append-only: PRD §2.4 says only id + created_at.
    id: str
    project_id: str
    subject_type: str
    subject_id: str
    actor_user_id: str
    actor_role: str
    event_kind: str
    payload: Any
    created_at: str


class PerformanceRating(TypedDict, total=False):
    # Embedded immutable record: PRD §2.4 says only id + created_at + payload.
    id: str
    settlement_id: str
    vendor_id: str
    score: int
    comment: Optional[str]
    created_at: str


__all__ = [
    "UserRole",
    "ProjectStatus",
    "ProjectStyle",
    "ProjectScale",
    "MilestoneStatus",
    "VendorCategory",
    "QualificationStatus",
    "QuoteStatus",
    "ContractStatus",
    "PaymentStatus",
    "ChangeOrderStatus",
    "SettlementStatus",
    "SlotKind",
    "RsvpStatus",
    "AuditSubjectType",
    "AuditEventKind",
    "ExternalEventKind",
    "WeddingProject",
    "ProjectTemplate",
    "Milestone",
    "Vendor",
    "Quote",
    "Contract",
    "ChangeOrder",
    "Settlement",
    "TimelineSlot",
    "Guest",
    "AuditEntry",
    "PerformanceRating",
]
