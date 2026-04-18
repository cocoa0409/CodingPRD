"""Domain types for the Shared Office API.

Entity TypedDicts, status enums, role enum — derived strictly from PRD.md.

Per PRD §2.4:
  - Tenant, Member, Lease, Resource, Reservation, AccessBadge, Bill carry id +
    created_at + updated_at + version.
  - Visitor carries only id + created_at (no updated_at, no version).
  - BillLine carries only id + created_at (append-only artefacts).
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ──────────────────────────────────────────────────────────
# Status enums (one per state-machined entity)
# ──────────────────────────────────────────────────────────


class TenantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATING = "TERMINATING"
    CLOSED = "CLOSED"


class AccessPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class MemberRoleInTenant(str, Enum):
    ADMIN = "ADMIN"
    STAFF = "STAFF"


class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATION_REQUESTED = "TERMINATION_REQUESTED"
    TERMINATION_REVIEWING = "TERMINATION_REVIEWING"
    TERMINATED = "TERMINATED"
    REJECTED = "REJECTED"


class BillingPlan(str, Enum):
    HOURLY = "HOURLY"
    DAILY = "DAILY"
    MONTHLY = "MONTHLY"


class ResourceKind(str, Enum):
    WORKSTATION = "WORKSTATION"
    MEETING_ROOM = "MEETING_ROOM"
    EVENT_AREA = "EVENT_AREA"


class ResourceStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class ReservationStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    IN_USE = "IN_USE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class VisitorStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    NO_SHOW = "NO_SHOW"
    REVOKED = "REVOKED"


class AccessBadgeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class BillStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    OVERDUE = "OVERDUE"
    PAID = "PAID"
    VOIDED = "VOIDED"


class BillLineKind(str, Enum):
    WORKSTATION_FEE = "WORKSTATION_FEE"
    MEETING_ROOM_FEE = "MEETING_ROOM_FEE"
    EVENT_AREA_FEE = "EVENT_AREA_FEE"
    VISITOR_OVERSTAY = "VISITOR_OVERSTAY"
    TERMINATION_PENALTY = "TERMINATION_PENALTY"
    MONTHLY_COMMITMENT = "MONTHLY_COMMITMENT"


class AccessEventKind(str, Enum):
    CHECK_IN = "CHECK_IN"
    CHECK_OUT = "CHECK_OUT"
    VISITOR_CHECK_IN = "VISITOR_CHECK_IN"
    VISITOR_CHECK_OUT = "VISITOR_CHECK_OUT"


class UserRole(str, Enum):
    PlatformAdmin = "PlatformAdmin"
    TenantAdmin = "TenantAdmin"
    TenantMember = "TenantMember"
    Receptionist = "Receptionist"
    BillingOfficer = "BillingOfficer"
    PaymentClerk = "PaymentClerk"


# ──────────────────────────────────────────────────────────
# Entity TypedDicts
# ──────────────────────────────────────────────────────────


class Tenant(TypedDict, total=False):
    id: str
    legal_name: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    access_posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    tenant_id: str
    email: str
    full_name: str
    role_in_tenant: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict, total=False):
    id: str
    tenant_id: str
    billing_plan: str
    monthly_rate_cents: int
    term_start_date: str
    term_end_date: str
    status: str
    termination_effective_date: Optional[str]
    termination_penalty_cents: int
    created_at: str
    updated_at: str
    version: int


class Resource(TypedDict, total=False):
    id: str
    kind: str
    code: str
    capacity: int
    hourly_rate_cents: int
    daily_rate_cents: int
    block_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict, total=False):
    id: str
    tenant_id: str
    member_id: str
    resource_id: str
    start_at: str
    end_at: str
    status: str
    provisional_fee_cents: int
    final_fee_cents: int
    actual_start_at: Optional[str]
    actual_end_at: Optional[str]
    bill_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Visitor — PRD §2.4: only id + created_at; no updated_at, no version.
class Visitor(TypedDict, total=False):
    id: str
    host_member_id: str
    tenant_id: str
    visitor_name: str
    expected_arrival_at: str
    expected_departure_at: str
    actual_arrival_at: Optional[str]
    actual_departure_at: Optional[str]
    status: str
    overstay_fee_cents: int
    bill_id: Optional[str]
    created_at: str


class AccessBadge(TypedDict, total=False):
    id: str
    member_id: str
    badge_serial: str
    status: str
    last_used_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# BillLine — PRD §2.4: append-only; only id + created_at.
class BillLine(TypedDict, total=False):
    id: str
    bill_id: str
    line_kind: str
    source_entity_id: str
    amount_cents: int
    created_at: str


class Bill(TypedDict, total=False):
    id: str
    tenant_id: str
    period_start_date: str
    period_end_date: str
    subtotal_cents: int
    tax_cents: int
    late_fee_cents: int
    total_due_cents: int
    status: str
    issued_at: Optional[str]
    due_at: Optional[str]
    paid_at: Optional[str]
    lines: List[BillLine]
    created_at: str
    updated_at: str
    version: int
