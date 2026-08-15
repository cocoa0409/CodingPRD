"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PUBLISHING_DIRECTOR = "PublishingDirector"
    PRODUCTION_MANAGER = "ProductionManager"
    CIRCULATION_MANAGER = "CirculationManager"
    FULFILLMENT_MANAGER = "FulfillmentManager"
    POSTAL_COMPLIANCE_OFFICER = "PostalComplianceOfficer"


# ---------------------------------------------------------------------------
# Status / field enums (PRD §3)
# ---------------------------------------------------------------------------
class PublicationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CEASED = "CEASED"


class Frequency(str, Enum):
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


class CirculationModel(str, Enum):
    PAID = "PAID"
    CONTROLLED = "CONTROLLED"
    MIXED = "MIXED"


class DeferredRevenueMethod(str, Enum):
    PRO_RATA_ISSUE = "PRO_RATA_ISSUE"
    STRAIGHT_LINE_MONTH = "STRAIGHT_LINE_MONTH"


class IssueStatus(str, Enum):
    PLANNING = "PLANNING"
    EDITORIAL_CLOSED = "EDITORIAL_CLOSED"
    AD_CLOSED = "AD_CLOSED"
    AT_PRINTER = "AT_PRINTER"
    MAILED = "MAILED"
    FINALIZED = "FINALIZED"


class CirculationClass(str, Enum):
    PAID_QUALIFIED = "PAID_QUALIFIED"
    CONTROLLED_QUALIFIED = "CONTROLLED_QUALIFIED"
    NON_QUALIFIED = "NON_QUALIFIED"


class SubscriptionStatus(str, Enum):
    PENDING_START = "PENDING_START"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    GRACE = "GRACE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    RENEWED = "RENEWED"


class QualificationTier(str, Enum):
    PAID = "PAID"
    CONTROLLED = "CONTROLLED"
    COMPLIMENTARY = "COMPLIMENTARY"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    CHECK = "CHECK"
    INVOICE = "INVOICE"
    NONE = "NONE"


class ExpireAction(str, Enum):
    EXPIRE = "EXPIRE"
    CONVERT_TO_CONTROLLED = "CONVERT_TO_CONTROLLED"


class SubscriptionTermStatus(str, Enum):
    OPEN = "OPEN"
    FULLY_RECOGNIZED = "FULLY_RECOGNIZED"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"


class RecognitionVariant(str, Enum):
    PRO_RATA_ISSUE = "PRO_RATA_ISSUE"
    STRAIGHT_LINE_MONTH = "STRAIGHT_LINE_MONTH"


class RevenueEntryType(str, Enum):
    RECOGNITION = "RECOGNITION"
    REVERSAL = "REVERSAL"
    REFUND_LIQUIDATION = "REFUND_LIQUIDATION"


class RenewalEventResponse(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class MailingBatchStatus(str, Enum):
    DRAFT = "DRAFT"
    LABELS_GENERATED = "LABELS_GENERATED"
    POSTAL_VERIFIED = "POSTAL_VERIFIED"
    TENDERED = "TENDERED"
    CONFIRMED = "CONFIRMED"


class PostalClass(str, Enum):
    PERIODICAL = "PERIODICAL"
    STANDARD = "STANDARD"
    FIRST_CLASS = "FIRST_CLASS"


class EntryPoint(str, Enum):
    ORIGIN = "ORIGIN"
    DDU = "DDU"
    DSCF = "DSCF"
    SCF = "SCF"


class PostalFormNumber(str, Enum):
    PS_3541 = "PS_3541"
    PS_3541_A = "PS_3541_A"
    PS_3602_R = "PS_3602_R"


class BackIssueOrderStatus(str, Enum):
    PENDING = "PENDING"
    FULFILLED = "FULFILLED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class AccessLevel(str, Enum):
    FULL = "FULL"
    PREVIEW = "PREVIEW"
    NONE = "NONE"


class RevocationReason(str, Enum):
    REFUND = "REFUND"
    CHARGEBACK = "CHARGEBACK"
    MANUAL = "MANUAL"


class QualificationResult(str, Enum):
    QUALIFIED = "QUALIFIED"
    NON_QUALIFIED = "NON_QUALIFIED"
    PENDING = "PENDING"


class CirculationAuditStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    AUDIT_PASSED = "AUDIT_PASSED"
    AUDIT_FAILED = "AUDIT_FAILED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.5: primary resources carry id, created_at,
# updated_at, version; MailingLabel, PostalStatement and DeferredRevenueEntry
# are immutable ledger snapshots carrying only id and created_at)
# ---------------------------------------------------------------------------
class Publication(TypedDict, total=False):
    id: str
    title: str
    issn: str
    frequency: str
    circulation_model: str
    issues_per_year: int
    base_cover_price_cents: int
    deferred_revenue_method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Issue(TypedDict, total=False):
    id: str
    publication_id: str
    issue_number: int
    volume_number: int
    cover_date: str
    editorial_close_date: str
    ad_close_date: str
    ship_to_printer_date: str
    mail_date: str
    ad_pages_sold: int
    print_run_override: Optional[int]
    print_run: int
    qualified_subscriber_count: int
    newsstand_buffer_copies: int
    revenue_recognized_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscriber(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    address_line1: str
    address_line2: Optional[str]
    city: str
    state_code: str
    postal_code: str
    country_code: str
    is_deliverable: bool
    circulation_class: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    subscriber_id: str
    publication_id: str
    start_issue_id: str
    term_issues: int
    price_paid_cents: int
    qualification_tier: str
    payment_method: str
    is_gift: bool
    donor_subscriber_id: Optional[str]
    renewal_series_code: str
    renewal_effort_number: int
    issues_served: int
    issues_remaining: int
    issues_suspended_count: int
    auto_renew: bool
    expire_action: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SubscriptionTerm(TypedDict, total=False):
    id: str
    subscription_id: str
    term_index: int
    term_start_issue_id: str
    term_end_issue_id: str
    issues_in_term: int
    gross_amount_cents: int
    deferred_balance_cents: int
    recognized_balance_cents: int
    recognition_variant: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RenewalSeries(TypedDict, total=False):
    id: str
    publication_id: str
    series_code: str
    effort_offsets_days: List[int]
    effort_pricing_cents: List[int]
    max_efforts: int
    is_default: bool
    created_at: str
    updated_at: str
    version: int


class RenewalEvent(TypedDict, total=False):
    id: str
    subscription_id: str
    series_code: str
    effort_number: int
    sent_at: str
    offered_price_cents: int
    response: str
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MailingBatch(TypedDict, total=False):
    id: str
    issue_id: str
    batch_label: str
    postal_class: str
    entry_point: str
    expected_piece_count: int
    total_postage_cents: int
    permit_number: str
    is_controlled_copy_included: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class MailingLabel(TypedDict, total=False):
    # Immutable ledger snapshot: id + created_at only (no updated_at, no version)
    id: str
    batch_id: str
    subscription_id: str
    subscriber_id: str
    address_block: str
    postal_code: str
    is_controlled_copy: bool
    piece_weight_oz: float
    postage_cents: int
    created_at: str


class PostalStatement(TypedDict, total=False):
    # Immutable ledger snapshot: id + created_at only (no updated_at, no version)
    id: str
    batch_id: str
    form_number: str
    paid_piece_count: int
    controlled_piece_count: int
    paid_percentage_bps: int
    advertising_percentage_bps: int
    total_postage_cents: int
    filed_at: str
    created_at: str


class BackIssueOrder(TypedDict, total=False):
    id: str
    subscriber_id: str
    issue_id: str
    quantity: int
    unit_price_cents: int
    shipping_cents: int
    total_charged_cents: int
    is_recognized_revenue: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class DigitalEntitlement(TypedDict, total=False):
    id: str
    subscription_id: str
    issue_id: str
    access_level: str
    granted_at: str
    revoked_at: Optional[str]
    revocation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeferredRevenueEntry(TypedDict, total=False):
    # Immutable ledger snapshot: id + created_at only (no updated_at, no version)
    id: str
    subscription_term_id: str
    issue_id: str
    recognized_at: str
    amount_cents: int
    variant: str
    entry_type: str
    created_at: str


class CirculationAuditRecord(TypedDict, total=False):
    id: str
    publication_id: str
    audit_period_start: str
    audit_period_end: str
    total_distribution: int
    paid_distribution: int
    controlled_distribution: int
    paid_percentage_bps: int
    qualification_result: str
    status: str
    created_at: str
    updated_at: str
    version: int
