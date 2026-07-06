"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the Gift-Basket & Corporate-Gifting PRD's resources. Mutable resources
carry id/created_at/updated_at/version. AssemblyStation and ShippingZone are
configuration-only records (common_fields: false) — they carry only id and
created_at, never updated_at or version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Roles ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ACCOUNT_MANAGER = "AccountManager"
    FINANCE_APPROVER = "FinanceApprover"
    PROOF_APPROVER = "ProofApprover"
    WAREHOUSE_OPS = "WarehouseOps"
    SHIPPING_OPS = "ShippingOps"


# ─── Status / enum vocabularies ───────────────────────────────────────────

class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TemplateCategory(str, Enum):
    HOLIDAY = "HOLIDAY"
    CORPORATE_WELCOME = "CORPORATE_WELCOME"
    CLIENT_APPRECIATION = "CLIENT_APPRECIATION"
    CUSTOM = "CUSTOM"


class CardStock(str, Enum):
    MATTE = "MATTE"
    GLOSS = "GLOSS"
    RECYCLED = "RECYCLED"


class Occasion(str, Enum):
    HOLIDAY = "HOLIDAY"
    ANNIVERSARY = "ANNIVERSARY"
    ONBOARDING = "ONBOARDING"
    THANK_YOU = "THANK_YOU"
    CUSTOM = "CUSTOM"


class ApprovalStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ProductionStatus(str, Enum):
    DRAFT = "DRAFT"
    ASSEMBLING = "ASSEMBLING"
    READY_TO_SHIP = "READY_TO_SHIP"
    SHIPPED = "SHIPPED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ImportRowStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ProofStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"


class InventoryReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    ALLOCATED = "ALLOCATED"
    ASSEMBLED = "ASSEMBLED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class AssemblyTaskStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class ShipmentStatus(str, Enum):
    CREATED = "CREATED"
    LABEL_GENERATED = "LABEL_GENERATED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    EXCEPTION = "EXCEPTION"
    RETURNED = "RETURNED"


class BudgetApprovalDecision(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# ─── Entity TypedDicts ─────────────────────────────────────────────────────
# common_fields: true — id + created_at + updated_at + version

class CorporateAccount(TypedDict):
    id: str
    name: str
    billing_email: str
    monthly_budget_cents: int
    approval_threshold_cents: int
    ytd_spend_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GiftBasketTemplate(TypedDict):
    id: str
    name: str
    category: str
    base_price_cents: int
    is_perishable: bool
    shelf_life_days: Optional[int]
    components: list
    active: bool
    created_at: str
    updated_at: str
    version: int


class ComponentSKU(TypedDict):
    id: str
    name: str
    unit_cost_cents: int
    is_perishable: bool
    shelf_life_days: Optional[int]
    on_hand_qty: int
    created_at: str
    updated_at: str
    version: int


class BrandingProfile(TypedDict):
    id: str
    corporate_account_id: str
    name: str
    logo_url: str
    accent_color: str
    card_stock: str
    approved: bool
    created_at: str
    updated_at: str
    version: int


class CorporateOrder(TypedDict):
    id: str
    corporate_account_id: str
    template_id: str
    branding_profile_id: Optional[str]
    occasion: str
    scheduled_send_date: Optional[str]
    approval_status: str
    production_status: str
    locked_template_version: Optional[int]
    locked_branding_version: Optional[int]
    subtotal_cents: int
    total_cost_cents: int
    requires_approval: bool
    created_at: str
    updated_at: str
    version: int


class Recipient(TypedDict):
    id: str
    corporate_order_id: str
    full_name: str
    email: str
    shipping_address_line1: str
    city: str
    state_code: str
    postal_code: str
    country_code: str
    quantity: int
    import_row_status: str
    created_at: str
    updated_at: str
    version: int


class MessageProof(TypedDict):
    id: str
    recipient_id: str
    message_text: str
    proof_status: str
    revision_count: int
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InventoryReservation(TypedDict):
    id: str
    recipient_id: str
    sku_id: str
    reserved_qty: int
    status: str
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — only id + created_at
class AssemblyStation(TypedDict):
    id: str
    name: str
    daily_capacity: int
    created_at: str


class AssemblyTask(TypedDict):
    id: str
    recipient_id: str
    station_id: str
    scheduled_date: str
    quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — only id + created_at
class ShippingZone(TypedDict):
    id: str
    zone_code: str
    country_codes: list
    carrier: str
    base_rate_cents: int
    per_kg_rate_cents: int
    transit_days_min: int
    transit_days_max: int
    blackout_dates: list
    created_at: str


class Shipment(TypedDict):
    id: str
    recipient_id: str
    zone_id: str
    ship_date: str
    tracking_number: Optional[str]
    status: str
    shipping_cost_cents: int
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BudgetApproval(TypedDict):
    id: str
    corporate_order_id: str
    requested_by_user_id: str
    approver_user_id: Optional[str]
    decision: str
    decision_reason: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecurringOrderSeries(TypedDict):
    id: str
    corporate_account_id: str
    source_order_id: str
    interval_days: int
    next_run_date: str
    active: bool
    last_generated_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
