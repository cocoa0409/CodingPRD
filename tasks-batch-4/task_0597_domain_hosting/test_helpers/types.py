"""Domain types for the Domain Registrar & Hosting API: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Roles (PRD §2.1) ──────────────────────────────────────────────────────

class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    REGISTRANT = "Registrant"
    SUPPORT_AGENT = "SupportAgent"
    ABUSE_ANALYST = "AbuseAnalyst"
    BILLING_ADMIN = "BillingAdmin"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Status enums ──────────────────────────────────────────────────────────

class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class DomainLifecycleStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REDEMPTION = "REDEMPTION"
    PENDING_DELETE = "PENDING_DELETE"
    DELETED = "DELETED"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"


class DomainLockStatus(str, Enum):
    LOCKED = "LOCKED"
    UNLOCKED = "UNLOCKED"


class HostingSubscriptionStatus(str, Enum):
    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    OVER_QUOTA = "OVER_QUOTA"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class AddOnStatus(str, Enum):
    PENDING_VALIDATION = "PENDING_VALIDATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    CANCELLED = "CANCELLED"


class AddOnType(str, Enum):
    SSL_CERT = "SSL_CERT"
    EMAIL_MAILBOX = "EMAIL_MAILBOX"


class TransferStatus(str, Enum):
    INITIATED = "INITIATED"
    PENDING_ACK = "PENDING_ACK"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TransferDirection(str, Enum):
    IN = "IN"
    OUT = "OUT"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class ItemType(str, Enum):
    DOMAIN_REGISTRATION = "DOMAIN_REGISTRATION"
    DOMAIN_RENEWAL = "DOMAIN_RENEWAL"
    REDEMPTION_FEE = "REDEMPTION_FEE"
    PRIVACY_FEE = "PRIVACY_FEE"
    HOSTING_PLAN = "HOSTING_PLAN"
    SSL_CERT = "SSL_CERT"
    EMAIL_MAILBOX = "EMAIL_MAILBOX"
    BANDWIDTH_OVERAGE = "BANDWIDTH_OVERAGE"


class EntryType(str, Enum):
    PAYMENT = "PAYMENT"
    REFUND = "REFUND"
    CREDIT_GRANT = "CREDIT_GRANT"
    CREDIT_APPLIED = "CREDIT_APPLIED"


class BillingPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AbuseReportStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class AbuseSeverity(str, Enum):
    LOW = "LOW"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RecordType(str, Enum):
    A = "A"
    AAAA = "AAAA"
    CNAME = "CNAME"
    MX = "MX"
    TXT = "TXT"
    NS = "NS"


# ─── Entities carrying the full audit triple (PRD §2.4) ────────────────────

class Account(TypedDict):
    id: str
    email: str
    company_name: str
    status: str
    payment_method_on_file: bool
    auto_renew_default: bool
    credit_balance_cents: int
    net_cash_cents: int
    risk_score: int
    created_at: str
    updated_at: str
    version: int


class Domain(TypedDict):
    id: str
    account_id: str
    domain_name: str
    tld: str
    fqdn: str
    lifecycle_status: str
    lock_status: str
    suspension_reason: Optional[str]
    whois_privacy_enabled: bool
    auto_renew_enabled: bool
    registrant_name: str
    registrant_email: str
    term_years: int
    registered_at: Optional[str]
    expires_at: Optional[str]
    epp_auth_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DnsRecord(TypedDict):
    id: str
    domain_id: str
    record_type: str
    name: str
    value: str
    ttl: int
    priority: Optional[int]
    serving_enabled: bool
    created_at: str
    updated_at: str
    version: int


class HostingSubscription(TypedDict):
    id: str
    account_id: str
    plan_id: str
    primary_domain_id: Optional[str]
    status: str
    storage_committed_mb: int
    bandwidth_used_mb: float
    auto_renew: bool
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    subscription_id: str
    domain_id: str
    add_on_type: str
    status: str
    validation_token: Optional[str]
    mailbox_address: Optional[str]
    storage_mb_quota: int
    term_days: int
    starts_at: str
    ends_at: str
    unit_price_cents: int
    created_at: str
    updated_at: str
    version: int


class TransferRequest(TypedDict):
    id: str
    account_id: str
    domain_id: Optional[str]
    direction: str
    domain_name: str
    tld: str
    epp_auth_code: str
    status: str
    attempt_count: int
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    account_id: str
    billing_period_id: Optional[str]
    status: str
    applied_promo_code: Optional[str]
    subtotal_cents: int
    discount_cents: int
    service_fee_cents: int
    tax_cents: int
    total_cents: int
    amount_paid_cents: int
    amount_refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class BillingPeriod(TypedDict):
    id: str
    subscription_id: str
    period_start: str
    period_end: str
    status: str
    provisional_overage_cents: int
    final_overage_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AbuseReport(TypedDict):
    id: str
    domain_id: str
    category: str
    severity: str
    status: str
    reporter_email: str
    evidence_url: Optional[str]
    reviewer_user_id: Optional[str]
    decider_user_id: Optional[str]
    decision_note: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── Write-once entities: id + created_at only (PRD §2.4) ──────────────────

class HostingPlan(TypedDict):
    id: str
    plan_code: str
    tier: str
    storage_quota_mb: int
    bandwidth_quota_mb: int
    monthly_price_cents: int
    included_mailboxes: int
    included_ssl: bool
    overage_rate_cents_per_gb: int
    created_at: str


class InvoiceLineItem(TypedDict):
    id: str
    invoice_id: str
    item_type: str
    reference_id: str
    description: str
    quantity: int
    unit_price_cents: int
    line_subtotal_cents: int
    line_discount_cents: int
    line_tax_cents: int
    line_total_cents: int
    created_at: str


class LedgerEntry(TypedDict):
    id: str
    account_id: str
    entry_type: str
    amount_cents: int
    reference_type: str
    reference_id: Optional[str]
    reason: Optional[str]
    balance_after_cents: int
    created_at: str


class UsageRecord(TypedDict):
    id: str
    subscription_id: str
    metric: str
    amount_mb: float
    recorded_at: str
    created_at: str


class PromoCode(TypedDict):
    id: str
    code: str
    discount_type: str
    discount_value: float
    applies_to_item_types: List[str]
    min_subtotal_cents: int
    max_discount_cents: int
    created_at: str
