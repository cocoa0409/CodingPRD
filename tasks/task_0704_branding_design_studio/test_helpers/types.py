"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this API are mutable resources carrying id, created_at,
updated_at, and version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    STUDIO_OPS = "StudioOps"
    DESIGNER = "Designer"
    CLIENT = "Client"
    BILLING_OPS = "BillingOps"


# --- Status enums ---
class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    DISCOVERY = "DISCOVERY"
    CONCEPT = "CONCEPT"
    DELIVERY = "DELIVERY"
    HANDOFF = "HANDOFF"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ServiceType(str, Enum):
    LOGO = "LOGO"
    IDENTITY = "IDENTITY"
    WEB = "WEB"


class MoodboardStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ConceptStatus(str, Enum):
    DRAFT = "DRAFT"
    PRESENTED = "PRESENTED"
    IN_REVISION = "IN_REVISION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    INVOICED = "INVOICED"
    PAID = "PAID"
    WAIVED = "WAIVED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    OVERDUE = "OVERDUE"
    PAID = "PAID"
    VOID = "VOID"


class DeliverableStatus(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    ACCEPTED = "ACCEPTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"


class AssetType(str, Enum):
    LOGO_PRIMARY = "LOGO_PRIMARY"
    LOGO_MARK = "LOGO_MARK"
    COLOR_TOKENS = "COLOR_TOKENS"
    TYPOGRAPHY = "TYPOGRAPHY"
    BRAND_GUIDE = "BRAND_GUIDE"
    WEB_KIT = "WEB_KIT"


class LicenseStatus(str, Enum):
    RESERVED = "RESERVED"
    CLEARED = "CLEARED"
    BILLED = "BILLED"
    VOIDED = "VOIDED"


class LicenseKind(str, Enum):
    STOCK = "STOCK"
    FONT = "FONT"


class ChangeOrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ChangeOrderReason(str, Enum):
    SCOPE_ADD = "SCOPE_ADD"
    EXTRA_REVISION = "EXTRA_REVISION"
    RUSH = "RUSH"


class RetainerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class CareCycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    BILLED = "BILLED"


# --- Entity TypedDicts (all carry id/created_at/updated_at/version per PRD §2.4) ---
class Studio(TypedDict):
    id: str
    name: str
    tax_rate: float
    license_markup_pct: float
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    studio_id: str
    company_name: str
    contact_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict):
    id: str
    studio_id: str
    client_id: str
    title: str
    service_type: str
    deposit_pct: float
    status: str
    base_scope_cents: int
    contract_value_cents: int
    provisional_deposit_cents: int
    final_deposit_cents: int
    deposit_collected_cents: int
    created_at: str
    updated_at: str
    version: int


class Moodboard(TypedDict):
    id: str
    project_id: str
    title: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Concept(TypedDict):
    id: str
    project_id: str
    label: str
    revision_limit: int
    rounds_used: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Milestone(TypedDict):
    id: str
    project_id: str
    name: str
    amount_cents: int
    sequence_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    project_id: str
    milestone_id: str
    gross_cents: int
    deposit_credit_cents: int
    tax_cents: int
    late_fee_cents: int
    net_due_cents: int
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Deliverable(TypedDict):
    id: str
    project_id: str
    asset_type: str
    is_required_for_handoff: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class License(TypedDict):
    id: str
    project_id: str
    kind: str
    cost_cents: int
    billable_cents: int
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    project_id: str
    reason: str
    concept_id: Optional[str]
    extra_revisions: int
    delta_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Retainer(TypedDict):
    id: str
    client_id: str
    monthly_fee_cents: int
    included_hours: int
    tier1_rate_cents: int
    tier2_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CareCycle(TypedDict):
    id: str
    retainer_id: str
    period_start: str
    period_end: str
    hours_used: int
    overage_cents: int
    billed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
