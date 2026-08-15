"""Domain types: entity TypedDicts, status enums, and role enum for the
Sales Tax Exemption Certificates API (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    TENANT_ADMIN = "TenantAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    AUDITOR = "Auditor"
    ORDER_CLERK = "OrderClerk"
    FULFILLMENT_CLERK = "FulfillmentClerk"
    BILLING_CLERK = "BillingClerk"


class FormType(str, Enum):
    RESALE = "RESALE"
    EXEMPT_ORG = "EXEMPT_ORG"
    AGRICULTURAL = "AGRICULTURAL"
    MANUFACTURING = "MANUFACTURING"
    DIRECT_PAY = "DIRECT_PAY"
    MULTI_JURISDICTION = "MULTI_JURISDICTION"


class AnchorRule(str, Enum):
    EFFECTIVE_DATE = "EFFECTIVE_DATE"
    SIGNED_DATE = "SIGNED_DATE"


class AuditPosture(str, Enum):
    CLEAR = "CLEAR"
    UNDER_SAMPLING = "UNDER_SAMPLING"
    IN_REMEDIATION = "IN_REMEDIATION"
    DEFENSE_ASSEMBLY = "DEFENSE_ASSEMBLY"


class CertStanding(str, Enum):
    MISSING = "MISSING"
    PARTIAL = "PARTIAL"
    COMPLIANT = "COMPLIANT"


class AuditStanding(str, Enum):
    NOT_UNDER_AUDIT = "NOT_UNDER_AUDIT"
    SAMPLED = "SAMPLED"
    FAILED_SAMPLING = "FAILED_SAMPLING"
    REMEDIATED = "REMEDIATED"


class CollectionStanding(str, Enum):
    CURRENT = "CURRENT"
    RENEWAL_DUE = "RENEWAL_DUE"
    LAPSED = "LAPSED"


class CertificateStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    HELD_FOR_CERT = "HELD_FOR_CERT"
    READY_TO_SHIP = "READY_TO_SHIP"
    SHIPPED = "SHIPPED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


class DropShipLinkStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class AuditCampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    SAMPLING = "SAMPLING"
    FIELDWORK = "FIELDWORK"
    REMEDIATION = "REMEDIATION"
    DEFENSE_ASSEMBLY = "DEFENSE_ASSEMBLY"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class SamplingMethod(str, Enum):
    STATISTICAL = "STATISTICAL"
    FIXED_FLOOR = "FIXED_FLOOR"


class SampleOutcome(str, Enum):
    PENDING = "PENDING"
    DOC_REQUESTED = "DOC_REQUESTED"
    DOC_RECEIVED = "DOC_RECEIVED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    WAIVED = "WAIVED"
    EXPIRED_NO_RESPONSE = "EXPIRED_NO_RESPONSE"


class RemediationActionType(str, Enum):
    COLLECT_NEW_CERT = "COLLECT_NEW_CERT"
    OBTAIN_LETTER = "OBTAIN_LETTER"
    ASSESS_TAX = "ASSESS_TAX"
    WAIVE_SAMPLE = "WAIVE_SAMPLE"


class RemediationActionStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class OutreachCampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    SENDING = "SENDING"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class DefensePacketStatus(str, Enum):
    DRAFT = "DRAFT"
    ASSEMBLED = "ASSEMBLED"
    DELIVERED = "DELIVERED"


# --- Entity shapes (PRD §2.5 common fields: id, created_at, updated_at, version) ---

class Tenant(TypedDict, total=False):
    id: str
    legal_name: str
    home_state_code: str
    audit_clock_day_index: int
    audit_posture: str
    open_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class JurisdictionRule(TypedDict, total=False):
    id: str
    tenant_id: str
    state_code: str
    accepted_form_types: List[str]
    validity_window_days: int
    anchor_rule: str
    allows_drop_ship_resale: bool
    requires_state_registration_number: bool
    blanket_cert_allowed: bool
    created_at: str
    updated_at: str
    version: int


class ExemptionReason(TypedDict, total=False):
    id: str
    tenant_id: str
    code: str
    description: str
    tax_engine_code: str
    requires_certificate: bool
    allowed_form_types: List[str]
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    tenant_id: str
    external_ref: str
    legal_name: str
    primary_ship_to_state: str
    exemption_reason_code: str
    cert_standing: str
    audit_standing: str
    collection_standing: str
    onboarding_completed_at: Optional[str]
    blocked_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class ExemptionCertificate(TypedDict, total=False):
    id: str
    tenant_id: str
    customer_id: str
    ship_to_state: str
    form_type: str
    exemption_reason_code: str
    state_registration_number: str
    signed_date: str
    effective_date: str
    expiration_date: Optional[str]
    current_version_id: Optional[str]
    superseded_by_certificate_id: Optional[str]
    status: str
    reviewed_by_user_id: Optional[str]
    review_decision_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CertificateVersion(TypedDict, total=False):
    id: str
    certificate_id: str
    tenant_id: str
    version_index: int
    file_uri: str
    form_type: str
    signed_date: str
    effective_date: str
    uploaded_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    tenant_id: str
    customer_id: str
    order_ref: str
    ship_to_state: str
    exemption_reason_code: str
    subtotal_cents: int
    exempt_amount_cents: int
    covered_amount_cents: int
    uncovered_amount_cents: int
    applied_tax_engine_code: Optional[str]
    drop_ship_link_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    tenant_id: str
    sku: str
    quantity: int
    unit_price_cents: int
    extended_cents: int
    is_exempt_claimed: bool
    created_at: str
    updated_at: str
    version: int


class DropShipLink(TypedDict, total=False):
    id: str
    tenant_id: str
    retailer_customer_id: str
    ship_to_state: str
    resale_certificate_id: str
    is_out_of_state_resale_accepted: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditCampaign(TypedDict, total=False):
    id: str
    tenant_id: str
    name: str
    population_state_filter: List[str]
    sampling_method: str
    target_confidence_pct: Optional[int]
    floor_sample_size: Optional[int]
    planned_sample_size: int
    opened_by_user_id: Optional[str]
    closed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditSample(TypedDict, total=False):
    id: str
    tenant_id: str
    campaign_id: str
    certificate_id: str
    customer_id: str
    sampled_at_day_index: int
    doc_due_day_index: Optional[int]
    outcome: str
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemediationAction(TypedDict, total=False):
    id: str
    tenant_id: str
    sample_id: str
    customer_id: str
    action_type: str
    assigned_to_user_id: str
    resolved_by_user_id: Optional[str]
    assessment_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class OutreachCampaign(TypedDict, total=False):
    id: str
    tenant_id: str
    name: str
    target_state_filter: List[str]
    days_before_expiration: int
    scheduled_send_day_index: int
    sent_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OutreachNotice(TypedDict, total=False):
    """Immutable emission record (PRD §2.5): carries ONLY id + created_at from
    the common set — no updated_at, no version."""
    id: str
    campaign_id: str
    tenant_id: str
    customer_id: str
    certificate_id: str
    scheduled_send_day_index: int
    sent_at_day_index: int
    created_at: str


class AuditDefensePacket(TypedDict, total=False):
    id: str
    tenant_id: str
    campaign_id: str
    included_certificate_ids: List[str]
    missing_certificate_ids: List[str]
    completeness_score_pct: int
    assembled_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
