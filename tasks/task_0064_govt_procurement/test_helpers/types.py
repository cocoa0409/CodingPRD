"""Domain types: entity TypedDicts, status enums, role enum.

Field-name fidelity follows PRD §2.4 / §2.11 / §3 exactly. Entities that
carry only id + created_at per PRD §2.4 ("EvaluationCommittee,
ContractAmendment, AuditLog, and ClockState carry only id and created_at
— neither updated_at nor version is exposed on these resources") omit
updated_at and version from their TypedDicts.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1 — exact spellings)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PROCUREMENT_OFFICER = "ProcurementOfficer"
    SUPPLIER = "Supplier"
    EVALUATION_EXPERT = "EvaluationExpert"
    REGULATOR = "Regulator"


# ---------------------------------------------------------------------------
# Enumerated state and category values (PRD §2.11)
# ---------------------------------------------------------------------------
class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    PUBLISHED = "PUBLISHED"
    AMENDING = "AMENDING"
    ARCHIVED = "ARCHIVED"
    REJECTED = "REJECTED"


class PlanItemStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PUBLISHED = "PUBLISHED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class PlanItemCategory(str, Enum):
    GOODS = "GOODS"
    SERVICES = "SERVICES"
    WORKS = "WORKS"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    PRESCREEN_OPEN = "PRESCREEN_OPEN"
    BIDDING_OPEN = "BIDDING_OPEN"
    BIDDING_CLOSED = "BIDDING_CLOSED"
    EVALUATING = "EVALUATING"
    AWARDED = "AWARDED"
    CONTRACT_SIGNED = "CONTRACT_SIGNED"
    CANCELLED = "CANCELLED"
    FROZEN = "FROZEN"


class EvaluationMethod(str, Enum):
    LOWEST_PRICE = "LOWEST_PRICE"
    COMPREHENSIVE_SCORING = "COMPREHENSIVE_SCORING"


class FrozenReason(str, Enum):
    COMPLAINT_UPHELD = "COMPLAINT_UPHELD"
    REGULATORY_HOLD = "REGULATORY_HOLD"


class TenderDocStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CLARIFYING = "CLARIFYING"
    AMENDING = "AMENDING"
    SUPERSEDED = "SUPERSEDED"


class BidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    WITHDRAWN = "WITHDRAWN"
    OPENED = "OPENED"
    EVALUATED = "EVALUATED"
    AWARDED = "AWARDED"
    LOST = "LOST"
    DISQUALIFIED = "DISQUALIFIED"


class CommitteeStatus(str, Enum):
    FORMED = "FORMED"
    EVALUATING = "EVALUATING"
    FINALIZED = "FINALIZED"
    DISSOLVED = "DISSOLVED"


class AwardStatus(str, Enum):
    DECIDED = "DECIDED"
    PUBLISHED = "PUBLISHED"
    REVOKED = "REVOKED"


class ContractStatus(str, Enum):
    PENDING_SIGNATURE = "PENDING_SIGNATURE"
    ACTIVE = "ACTIVE"
    AMENDING = "AMENDING"
    EXECUTED = "EXECUTED"
    TERMINATED = "TERMINATED"


class QueryStatus(str, Enum):
    OPEN = "OPEN"
    ANSWERED = "ANSWERED"
    EXPIRED = "EXPIRED"


class ComplaintStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"
    WITHDRAWN = "WITHDRAWN"


class ComplaintSubject(str, Enum):
    PRESCREEN_RESULT = "PRESCREEN_RESULT"
    EVALUATION = "EVALUATION"
    AWARD = "AWARD"
    CONTRACT = "CONTRACT"


class CorrectiveAction(str, Enum):
    REOPEN_PRESCREEN = "REOPEN_PRESCREEN"
    REOPEN_EVALUATION = "REOPEN_EVALUATION"
    REVOKE_AWARD = "REVOKE_AWARD"
    FREEZE_PROJECT = "FREEZE_PROJECT"


class SupplierRegistrationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    BLACKLISTED = "BLACKLISTED"
    REVOKED = "REVOKED"


class AuditTargetType(str, Enum):
    EVALUATION = "EVALUATION"
    COMPLAINT = "COMPLAINT"
    CONTRACT = "CONTRACT"
    TENDER = "TENDER"
    AWARD = "AWARD"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# Common-versioned entities carry id + created_at + updated_at + version.
class Supplier(TypedDict, total=False):
    id: str
    legal_name: str
    tax_id: str
    registration_status: str
    blacklist_until: Optional[str]
    credit_score: int
    qualifications: List[str]
    created_at: str
    updated_at: str
    version: int


class ProcurementPlan(TypedDict, total=False):
    id: str
    agency_id: str
    fiscal_year: int
    status: str
    total_budget_cents: int
    published_at: Optional[str]
    amendment_round: int
    created_at: str
    updated_at: str
    version: int


class PlanItem(TypedDict, total=False):
    id: str
    plan_id: str
    title: str
    category: str
    budget_cents: int
    item_status: str
    executed_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict, total=False):
    id: str
    plan_item_id: str
    title: str
    project_status: str
    evaluation_method: str
    bid_submission_deadline: str
    query_window_close_at: str
    bid_opening_at: str
    estimated_value_cents: int
    required_qualifications: List[str]
    frozen_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TenderDocument(TypedDict, total=False):
    id: str
    project_id: str
    template_id: str
    version: int  # NOTE: domain version (overrides common version semantics)
    doc_status: str
    technical_spec: str
    commercial_spec: str
    qualification_requirements: List[str]
    evaluation_criteria: Dict[str, Any]
    pinned_at: Optional[str]
    created_at: str
    updated_at: str


class Bid(TypedDict, total=False):
    id: str
    project_id: str
    supplier_id: str
    tender_document_version: int
    bid_price_cents: int
    technical_score_raw: int
    bid_status: str
    prescreen_passed: bool
    final_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


# PRD §2.4: EvaluationCommittee, ContractAmendment, AuditLog, ClockState
# carry only id + created_at — no updated_at, no version.
class EvaluationCommittee(TypedDict, total=False):
    id: str
    project_id: str
    members: List[Dict[str, Any]]
    selection_seed: str
    committee_status: str
    created_at: str


class Award(TypedDict, total=False):
    id: str
    project_id: str
    winning_bid_id: str
    award_status: str
    published_at: Optional[str]
    award_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    project_id: str
    award_id: str
    supplier_id: str
    contract_amount_cents: int
    payment_terms: str
    signature_ref: Optional[str]
    contract_status: str
    paid_amount_cents: int
    created_at: str
    updated_at: str
    version: int


# PRD §2.4: ContractAmendment is append-only.
class ContractAmendment(TypedDict, total=False):
    id: str
    contract_id: str
    delta_amount_cents: int
    reason: str
    filed_at: str
    created_at: str


class Query(TypedDict, total=False):
    id: str
    project_id: str
    supplier_id: str
    question: str
    response: Optional[str]
    query_status: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict, total=False):
    id: str
    project_id: str
    complainant_supplier_id: str
    subject: str
    narrative: str
    complaint_status: str
    decision_at: Optional[str]
    corrective_action: Optional[str]
    created_at: str
    updated_at: str
    version: int


# PRD §2.4: AuditLog is append-only.
class AuditLog(TypedDict, total=False):
    id: str
    target_type: str
    target_id: str
    actor_role: str
    actor_id: str
    action: str
    payload: Dict[str, Any]
    created_at: str


# PRD §2.4: ClockState carries only id + created_at + current_time.
class ClockState(TypedDict, total=False):
    id: str
    current_time: str
    created_at: str


__all__ = [
    "UserRole",
    "PlanStatus",
    "PlanItemStatus",
    "PlanItemCategory",
    "ProjectStatus",
    "EvaluationMethod",
    "FrozenReason",
    "TenderDocStatus",
    "BidStatus",
    "CommitteeStatus",
    "AwardStatus",
    "ContractStatus",
    "QueryStatus",
    "ComplaintStatus",
    "ComplaintSubject",
    "CorrectiveAction",
    "SupplierRegistrationStatus",
    "AuditTargetType",
    "Supplier",
    "ProcurementPlan",
    "PlanItem",
    "Project",
    "TenderDocument",
    "Bid",
    "EvaluationCommittee",
    "Award",
    "Contract",
    "ContractAmendment",
    "Query",
    "Complaint",
    "AuditLog",
    "ClockState",
]
