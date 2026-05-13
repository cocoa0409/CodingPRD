"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror PRD prose exactly. Per PRD §2.4:

- Versioned entities (id + created_at + updated_at + version):
  Tenant, Subscription, Invoice.

- Append-only / immutable-config entities (id + created_at ONLY;
  NO updated_at, NO version):
  PackageVersion, SubscriptionChange, UsageRecord, Payment, CreditNote,
  Jurisdiction, SyncEvent, AuditLog.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BILLING_OPERATOR = "BillingOperator"
    TENANT_ADMIN = "TenantAdmin"


# ---------------------------------------------------------------------------
# Tenant status enums (PRD §3.2, §3.12)
# ---------------------------------------------------------------------------
class TenantStatus(str, Enum):
    TRIAL = "TRIAL"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class RestrictionLevel(str, Enum):
    NONE = "NONE"
    READ_ONLY = "READ_ONLY"
    FEATURE_RESTRICTED = "FEATURE_RESTRICTED"


class BillingEntityType(str, Enum):
    INDEPENDENT = "INDEPENDENT"
    PARENT = "PARENT"
    SUBSIDIARY = "SUBSIDIARY"


# ---------------------------------------------------------------------------
# PackageVersion enums (PRD §3.1)
# ---------------------------------------------------------------------------
class PackageType(str, Enum):
    TIERED = "TIERED"
    USAGE_BASED = "USAGE_BASED"
    HYBRID = "HYBRID"


class BillingCycle(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    ANNUAL = "ANNUAL"


class PricingModel(str, Enum):
    PREPAID = "PREPAID"
    POSTPAID = "POSTPAID"


# ---------------------------------------------------------------------------
# Subscription enums (PRD §3.3, §3.4, §3.12)
# ---------------------------------------------------------------------------
class SubscriptionStatus(str, Enum):
    PENDING = "PENDING"
    TRIAL = "TRIAL"
    ACTIVE = "ACTIVE"
    PENDING_DOWNGRADE = "PENDING_DOWNGRADE"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    CURRENT = "CURRENT"
    DUE = "DUE"
    OVERDUE_TIER1 = "OVERDUE_TIER1"
    OVERDUE_TIER2 = "OVERDUE_TIER2"
    OVERDUE_TIER3 = "OVERDUE_TIER3"


# ---------------------------------------------------------------------------
# SubscriptionChange (PRD §3.4)
# ---------------------------------------------------------------------------
class SubscriptionChangeType(str, Enum):
    UPGRADE = "UPGRADE"
    DOWNGRADE_IMMEDIATE_REFUND = "DOWNGRADE_IMMEDIATE_REFUND"
    DOWNGRADE_END_OF_CYCLE = "DOWNGRADE_END_OF_CYCLE"
    TRIAL_CONVERSION = "TRIAL_CONVERSION"
    ADDON_ADD = "ADDON_ADD"
    ADDON_REMOVE = "ADDON_REMOVE"
    CANCEL = "CANCEL"


# ---------------------------------------------------------------------------
# UsageRecord (PRD §3.7)
# ---------------------------------------------------------------------------
class UsageMetric(str, Enum):
    API_CALL = "API_CALL"
    STORAGE_GB = "STORAGE_GB"
    BANDWIDTH_GB = "BANDWIDTH_GB"
    ACTIVE_USER = "ACTIVE_USER"


class IngestionMode(str, Enum):
    REALTIME = "REALTIME"
    BATCH = "BATCH"


# ---------------------------------------------------------------------------
# Invoice (PRD §3.9)
# ---------------------------------------------------------------------------
class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    WRITTEN_OFF = "WRITTEN_OFF"


# ---------------------------------------------------------------------------
# Payment / CreditNote (PRD §3.11)
# ---------------------------------------------------------------------------
class PaymentRecordStatus(str, Enum):
    RECEIVED = "RECEIVED"
    REVERSED = "REVERSED"


class CreditNoteOrigin(str, Enum):
    REFUND_DOWNGRADE = "REFUND_DOWNGRADE"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"
    TAX_CORRECTION = "TAX_CORRECTION"


# ---------------------------------------------------------------------------
# Jurisdiction (PRD §3.13)
# ---------------------------------------------------------------------------
class RoundingMode(str, Enum):
    PER_LINE = "PER_LINE"
    TOTAL = "TOTAL"


# ---------------------------------------------------------------------------
# SyncEvent (PRD §2.13)
# ---------------------------------------------------------------------------
class TargetSystem(str, Enum):
    PAYMENT_PAY = "PAYMENT_PAY"
    ACCOUNTING = "ACCOUNTING"
    CRM = "CRM"
    TAX_COMPLIANCE = "TAX_COMPLIANCE"


class SyncEventType(str, Enum):
    SUBSCRIPTION_CREATED = "SUBSCRIPTION_CREATED"
    SUBSCRIPTION_CHANGED = "SUBSCRIPTION_CHANGED"
    INVOICE_ISSUED = "INVOICE_ISSUED"
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED"
    TENANT_SUSPENDED = "TENANT_SUSPENDED"
    TENANT_REACTIVATED = "TENANT_REACTIVATED"


class DeliveryStatus(str, Enum):
    QUEUED = "QUEUED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# AuditLog (PRD §2.13)
# ---------------------------------------------------------------------------
class AuditAction(str, Enum):
    SUBSCRIPTION_CREATE = "SUBSCRIPTION_CREATE"
    SUBSCRIPTION_UPGRADE = "SUBSCRIPTION_UPGRADE"
    SUBSCRIPTION_DOWNGRADE = "SUBSCRIPTION_DOWNGRADE"
    INVOICE_ADJUSTMENT = "INVOICE_ADJUSTMENT"
    CREDIT_ISSUE = "CREDIT_ISSUE"
    TENANT_STATUS_CHANGE = "TENANT_STATUS_CHANGE"


# ---------------------------------------------------------------------------
# Versioned entity TypedDicts (id + created_at + updated_at + version)
# ---------------------------------------------------------------------------
class Tenant(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    contact_phone: str
    billing_entity_type: str
    parent_tenant_id: Optional[str]
    currency: str
    jurisdiction_code: str
    tenant_status: str
    restriction_level: str
    trial_expires_at: Optional[str]
    outstanding_balance_cents: int
    active_subscription_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    tenant_id: str
    package_code: str
    package_version_id: str
    selected_addons: List[str]
    subscription_status: str
    payment_status: str
    cycle_start: str
    cycle_end: str
    pending_change_package_version_id: Optional[str]
    quota_consumed: Dict[str, int]
    quota_carry_forward: Dict[str, int]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    tenant_id: str
    subscription_id: str
    cycle_start: str
    cycle_end: str
    invoice_status: str
    currency: str
    subtotal_cents: int
    discount_cents: int
    credit_applied_cents: int
    tax_cents: int
    late_fee_cents: int
    total_cents: int
    amount_paid_cents: int
    amount_due_cents: int
    due_at: str
    line_items: List[Dict[str, Any]]
    pricing_model: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities (PRD §2.4: id + created_at ONLY)
# ---------------------------------------------------------------------------
class PackageVersion(TypedDict, total=False):
    id: str
    package_code: str
    version_number: int
    package_type: str
    effective_from: str
    base_price_cents: int
    currency: str
    billing_cycle: str
    pricing_model: str
    included_quotas: Dict[str, int]
    tiered_brackets: List[Dict[str, Any]]
    overage_rates: Dict[str, int]
    addons: List[Dict[str, Any]]
    created_at: str


class SubscriptionChange(TypedDict, total=False):
    id: str
    subscription_id: str
    tenant_id: str
    change_type: str
    from_package_version_id: Optional[str]
    to_package_version_id: Optional[str]
    effective_at: str
    prorated_charge_cents: int
    created_at: str


class UsageRecord(TypedDict, total=False):
    id: str
    subscription_id: str
    tenant_id: str
    idempotency_key: str
    metric: str
    quantity: int
    event_timestamp: str
    ingestion_mode: str
    attributed_cycle_start: str
    archived: bool
    created_at: str


class Payment(TypedDict, total=False):
    id: str
    tenant_id: str
    invoice_id: str
    amount_cents: int
    currency: str
    external_reference: str
    payment_status: str
    created_at: str


class CreditNote(TypedDict, total=False):
    id: str
    tenant_id: str
    origin: str
    amount_cents: int
    applied_to_invoice_id: Optional[str]
    applied_cents: int
    created_at: str


class Jurisdiction(TypedDict, total=False):
    id: str
    jurisdiction_code: str
    tax_rate_bps: int
    rounding_mode: str
    created_at: str


class SyncEvent(TypedDict, total=False):
    id: str
    tenant_id: str
    target_system: str
    event_type: str
    payload: Dict[str, Any]
    delivery_status: str
    created_at: str


class AuditLog(TypedDict, total=False):
    id: str
    tenant_id: str
    actor_role: str
    actor_id: str
    action: str
    target_entity_type: str
    target_entity_id: str
    before_snapshot: Dict[str, Any]
    after_snapshot: Dict[str, Any]
    created_at: str


__all__ = [
    "UserRole",
    "TenantStatus", "RestrictionLevel", "BillingEntityType",
    "PackageType", "BillingCycle", "PricingModel",
    "SubscriptionStatus", "PaymentStatus",
    "SubscriptionChangeType",
    "UsageMetric", "IngestionMode",
    "InvoiceStatus",
    "PaymentRecordStatus", "CreditNoteOrigin",
    "RoundingMode",
    "TargetSystem", "SyncEventType", "DeliveryStatus",
    "AuditAction",
    "Tenant", "Subscription", "Invoice",
    "PackageVersion", "SubscriptionChange", "UsageRecord",
    "Payment", "CreditNote", "Jurisdiction",
    "SyncEvent", "AuditLog",
]
