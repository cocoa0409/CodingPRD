"""Domain types for the Domestic Service Dispatch API.

Status enums and entity TypedDicts derived from PRD §3 (workflows) and PRD §2.4
(common resource properties).

Per PRD §2.4: ServiceExecution, AbnormalEvent, OrderRating, SettlementLedgerEntry,
and AuditLogEntry are append-only and carry only `id` and `created_at` —
no `updated_at` and no `version` field.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─────────────────────────────────────────────────────────────
# Roles (PRD §2.1)
# ─────────────────────────────────────────────────────────────


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    SERVICE_PERSONNEL = "ServicePersonnel"
    PLATFORM_OPERATOR = "PlatformOperator"
    SYSTEM = "system"


# ─────────────────────────────────────────────────────────────
# ServicePersonnel enums (PRD §3.1)
# ─────────────────────────────────────────────────────────────


class PersonnelStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISQUALIFIED = "DISQUALIFIED"


class PersonnelTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class Gender(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"


# ─────────────────────────────────────────────────────────────
# SkillCertification enums (PRD §3.2)
# ─────────────────────────────────────────────────────────────


class SkillTag(str, Enum):
    CLEANING = "CLEANING"
    COOKING = "COOKING"
    CHILDCARE = "CHILDCARE"
    ELDERCARE = "ELDERCARE"


class CertificationStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


# ─────────────────────────────────────────────────────────────
# Order enums (PRD §3.4-§3.8)
# ─────────────────────────────────────────────────────────────


class OrderMode(str, Enum):
    SINGLE = "SINGLE"
    RECURRING = "RECURRING"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_DISPATCH = "PENDING_DISPATCH"
    DISPATCHED = "DISPATCHED"
    ACCEPTED = "ACCEPTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ACCEPTED_BY_CUSTOMER = "ACCEPTED_BY_CUSTOMER"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class RecurringOrderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    TERMINATED = "TERMINATED"


# ─────────────────────────────────────────────────────────────
# AbnormalEvent / InsuranceClaim enums (PRD §3.7)
# ─────────────────────────────────────────────────────────────


class ReporterRole(str, Enum):
    PERSONNEL = "PERSONNEL"
    CUSTOMER = "CUSTOMER"
    OPERATOR = "OPERATOR"


class AbnormalCategory(str, Enum):
    INJURY = "INJURY"
    PROPERTY_DAMAGE = "PROPERTY_DAMAGE"
    NO_SHOW = "NO_SHOW"
    OTHER = "OTHER"


class ClaimType(str, Enum):
    ON_JOB_INJURY = "ON_JOB_INJURY"
    PROPERTY_DAMAGE = "PROPERTY_DAMAGE"


class ClaimStatus(str, Enum):
    REPORTED = "REPORTED"
    EVIDENCE_PENDING = "EVIDENCE_PENDING"
    FILED = "FILED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"
    ARCHIVED = "ARCHIVED"


class InsuranceDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# ─────────────────────────────────────────────────────────────
# OrderRating enums (PRD §3.9)
# ─────────────────────────────────────────────────────────────


class InvestigationStatus(str, Enum):
    NONE = "NONE"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


# ─────────────────────────────────────────────────────────────
# Settlement / Audit enums (PRD §3.10, §2.11)
# ─────────────────────────────────────────────────────────────


class LedgerKind(str, Enum):
    COMMISSION = "COMMISSION"
    BONUS = "BONUS"
    REVERSAL = "REVERSAL"
    TAX = "TAX"
    PAYOUT = "PAYOUT"


class AuditActionType(str, Enum):
    DISPATCH = "DISPATCH"
    REASSIGN = "REASSIGN"
    DISPATCH_EXPIRED = "DISPATCH_EXPIRED"
    CLAIM_REPORTED = "CLAIM_REPORTED"
    CLAIM_FILED = "CLAIM_FILED"
    CLAIM_APPROVED = "CLAIM_APPROVED"
    CLAIM_REJECTED = "CLAIM_REJECTED"
    CLAIM_PAID = "CLAIM_PAID"


class AuditSubjectType(str, Enum):
    ORDER = "Order"
    INSURANCE_CLAIM = "InsuranceClaim"


# ─────────────────────────────────────────────────────────────
# Entity TypedDicts — common_fields=true carry id/created_at/updated_at/version
# ─────────────────────────────────────────────────────────────


class ServicePersonnel(TypedDict, total=False):
    id: str
    full_name: str
    gender: str
    age: int
    languages: List[str]
    skill_tags: List[str]
    service_lat: float
    service_lng: float
    service_radius_km: float
    identity_verified: bool
    health_cert_expires_at: str
    status: str
    rating_score: float
    rating_count: int
    workload_active_orders: int
    tier: str
    last_recert_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SkillCertification(TypedDict, total=False):
    id: str
    personnel_id: str
    skill_tag: str
    training_hours: float
    certified_at: Optional[str]
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceItem(TypedDict, total=False):
    id: str
    name: str
    required_skill_tag: str
    base_price_cents: int
    min_duration_hours: float
    service_areas: List[str]
    active: bool
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    area_code: str
    address_lat: float
    address_lng: float
    pref_gender: Optional[str]
    pref_min_age: Optional[int]
    pref_max_age: Optional[int]
    pref_language: Optional[str]
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    customer_id: str
    service_item_id: str
    mode: str
    recurring_order_id: Optional[str]
    scheduled_start_at: str
    duration_hours: float
    gross_price_cents: int
    status: str
    assigned_personnel_id: Optional[str]
    dispatch_round: int
    dispatch_deadline_at: Optional[str]
    completed_at: Optional[str]
    accepted_at: Optional[str]
    refunded_at: Optional[str]
    rated: bool
    created_at: str
    updated_at: str
    version: int


class RecurringOrder(TypedDict, total=False):
    id: str
    customer_id: str
    service_item_id: str
    cadence_days: int
    first_start_at: str
    duration_hours: float
    occurrences_generated: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InsuranceClaim(TypedDict, total=False):
    id: str
    order_id: str
    abnormal_event_id: str
    claim_type: str
    status: str
    claimed_amount_cents: int
    paid_amount_cents: int
    evidence_count: int
    created_at: str
    updated_at: str
    version: int


# ─────────────────────────────────────────────────────────────
# Append-only entities (PRD §2.4) — only id + created_at, NO updated_at, NO version
# ─────────────────────────────────────────────────────────────


class ServiceExecution(TypedDict, total=False):
    id: str
    order_id: str
    checkin_lat: float
    checkin_lng: float
    checkin_face_passed: bool
    checkin_at: str
    procedure_checklist: List[bool]
    before_photo_url: Optional[str]
    after_photo_url: Optional[str]
    abnormal_reported: bool
    completion_submitted_at: Optional[str]
    created_at: str


class AbnormalEvent(TypedDict, total=False):
    id: str
    order_id: str
    reporter_role: str
    category: str
    description: str
    triggers_claim: bool
    created_at: str


class OrderRating(TypedDict, total=False):
    id: str
    order_id: str
    quality_score: int
    punctuality_score: int
    attitude_score: int
    text_review: str
    anonymous: bool
    composite_score: float
    investigation_status: str
    created_at: str


class SettlementLedgerEntry(TypedDict, total=False):
    id: str
    personnel_id: str
    order_id: Optional[str]
    kind: str
    amount_cents: int
    posted_at: str
    cycle_id: str
    withheld_until: Optional[str]
    created_at: str


class AuditLogEntry(TypedDict, total=False):
    id: str
    action_type: str
    subject_type: str
    subject_id: str
    actor_role: str
    actor_id: str
    payload: dict
    created_at: str
