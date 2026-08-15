"""Domain types: entity TypedDicts, status enums, role enum.

All roles in this PRD have opaque identities (PRD section 2.1). Every entity
carries the full common set: id, created_at, updated_at, version (PRD 2.5).
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    TITLE_AGENT = "TitleAgent"
    RESEARCH_ANALYST = "ResearchAnalyst"
    QA_REVIEWER = "QAReviewer"
    PROVIDER_ADMIN = "ProviderAdmin"


class JurisdictionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class DepartmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class DeptType(str, Enum):
    UTILITY = "UTILITY"
    CODE_ENFORCEMENT = "CODE_ENFORCEMENT"
    PERMIT = "PERMIT"
    TAX_COLLECTOR = "TAX_COLLECTOR"


class OrderClass(str, Enum):
    STANDARD = "STANDARD"
    RUSH = "RUSH"


class SearchOrderStatus(str, Enum):
    INTAKE = "INTAKE"
    RESEARCH_IN_PROGRESS = "RESEARCH_IN_PROGRESS"
    VERIFICATION = "VERIFICATION"
    READY_FOR_DELIVERY = "READY_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ResearchTaskStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    UNABLE_TO_REACH = "UNABLE_TO_REACH"
    CANCELLED = "CANCELLED"


class FindingKind(str, Enum):
    UNPAID_UTILITY = "UNPAID_UTILITY"
    CODE_VIOLATION = "CODE_VIOLATION"
    OPEN_PERMIT = "OPEN_PERMIT"
    TAX_LIEN = "TAX_LIEN"


class EstoppelOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ORDERED = "ORDERED"
    OVERDUE = "OVERDUE"
    RECEIVED = "RECEIVED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class DiscrepancyStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"


class SubjectType(str, Enum):
    SEARCH_ORDER = "SEARCH_ORDER"
    RESEARCH_TASK = "RESEARCH_TASK"
    ESTOPPEL_ORDER = "ESTOPPEL_ORDER"


class DiscrepancyType(str, Enum):
    MISSED_ITEM = "MISSED_ITEM"
    BALANCE_MISMATCH = "BALANCE_MISMATCH"
    PAYOFF_MISMATCH = "PAYOFF_MISMATCH"
    STALE_ESTOPPEL = "STALE_ESTOPPEL"


class ResolutionOutcome(str, Enum):
    CONFIRMED_CORRECTION = "CONFIRMED_CORRECTION"
    REJECTED_INVALID = "REJECTED_INVALID"
    VOID_ORDER_CANCELLED = "VOID_ORDER_CANCELLED"


class DeliveryStatus(str, Enum):
    READY = "READY"
    DELIVERED = "DELIVERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class Jurisdiction(TypedDict, total=False):
    id: str
    code: str
    name: str
    state_code: str
    rush_daily_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class JurisdictionStatute(TypedDict, total=False):
    id: str
    jurisdiction_id: str
    effective_from: str
    effective_to: Optional[str]
    estoppel_response_days: int
    estoppel_fee_cap_cents: int
    estoppel_validity_days: int
    created_at: str
    updated_at: str
    version: int


class Department(TypedDict, total=False):
    id: str
    jurisdiction_id: str
    dept_type: str
    name: str
    research_fee_cents: int
    rush_surcharge_cents: int
    supports_rush: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Association(TypedDict, total=False):
    id: str
    jurisdiction_id: str
    name: str
    management_company: str
    estoppel_fee_cents: int
    estoppel_validity_days: int
    created_at: str
    updated_at: str
    version: int


class SearchOrder(TypedDict, total=False):
    id: str
    title_agent_id: str
    property_address: str
    parcel_number: str
    association_id: Optional[str]
    jurisdiction_id: Optional[str]
    rush_candidate_jurisdiction_id: Optional[str]
    statute_id: Optional[str]
    order_class: str
    service_date: Optional[str]
    closing_date: str
    extended_coverage: bool
    status: str
    research_completed_by_user_id: Optional[str]
    payoff_verified_by_user_id: Optional[str]
    payoff_verified_at: Optional[str]
    total_payoff_cents: int
    total_fees_cents: int
    pending_claims_cents: int
    total_liability_cents: int
    created_at: str
    updated_at: str
    version: int


class ResearchTask(TypedDict, total=False):
    id: str
    search_order_id: str
    department_id: str
    dept_type: str
    status: str
    findings: List[Dict[str, Any]]
    findings_recorded: bool
    unpaid_balance_cents: int
    open_violation_count: int
    fee_base_cents: int
    fee_rush_surcharge_cents: int
    fee_charged_cents: int
    completed_by_user_id: Optional[str]
    unreachable_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EstoppelOrder(TypedDict, total=False):
    id: str
    search_order_id: str
    association_id: str
    status: str
    fee_quoted_cents: int
    ordered_at: Optional[str]
    statutory_due_at: Optional[str]
    received_at: Optional[str]
    late_delivery: bool
    current_fee_cents: int
    lifetime_fees_cents: int
    payoff_amount_cents: Optional[int]
    valid_through: Optional[str]
    renewal_count: int
    created_at: str
    updated_at: str
    version: int


class Discrepancy(TypedDict, total=False):
    id: str
    search_order_id: str
    subject_type: str
    subject_id: str
    discrepancy_type: str
    claimed_amount_cents: int
    description: str
    filed_by_user_id: str
    post_delivery: bool
    status: str
    resolution_outcome: Optional[str]
    confirmed_amount_cents: Optional[int]
    confirmed_liability_cents: int
    resolved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Delivery(TypedDict, total=False):
    id: str
    search_order_id: str
    status: str
    snapshot_payoff_cents: int
    snapshot_fees_cents: int
    coverage_fee_cents: int
    liability_cap_cents: int
    delivered_at: Optional[str]
    delivered_to_agent_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
