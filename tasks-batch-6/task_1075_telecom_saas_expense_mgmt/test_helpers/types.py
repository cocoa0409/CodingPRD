"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    SOURCING = "Sourcing"
    ANALYST = "Analyst"
    FINANCE_APPROVER = "FinanceApprover"
    COST_CENTER_OWNER = "CostCenterOwner"
    VENDOR = "Vendor"
    SYSTEM_ADMIN = "SystemAdmin"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VendorType(str, Enum):
    TELECOM = "TELECOM"
    SAAS = "SAAS"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class ServiceType(str, Enum):
    TELECOM_LINE = "TELECOM_LINE"
    SAAS_SUBSCRIPTION = "SAAS_SUBSCRIPTION"


class LicenseType(str, Enum):
    PER_SEAT = "PER_SEAT"
    FLAT = "FLAT"
    USAGE_BASED = "USAGE_BASED"


class DiscoverySource(str, Enum):
    SANCTIONED = "SANCTIONED"
    SHADOW_IT = "SHADOW_IT"


class ServiceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RIGHTSIZED = "RIGHTSIZED"
    RETIRED = "RETIRED"


class InvoiceStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DISPUTED = "DISPUTED"
    APPROVED = "APPROVED"
    PAID = "PAID"


class LineItemStatus(str, Enum):
    BILLED = "BILLED"
    DISPUTED = "DISPUTED"
    CREDITED = "CREDITED"


class DisputeResponseType(str, Enum):
    NONE = "NONE"
    FULL_ACCEPT = "FULL_ACCEPT"
    PARTIAL = "PARTIAL"
    REJECT = "REJECT"


class DisputeStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VENDOR_RESPONDED = "VENDOR_RESPONDED"
    RESUBMITTED = "RESUBMITTED"
    ACCEPTED = "ACCEPTED"
    WITHDRAWN = "WITHDRAWN"


class CreditStatus(str, Enum):
    ISSUED = "ISSUED"


class CostCenterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"


class AllocationStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class RecommendationType(str, Enum):
    DOWNGRADE_SEATS = "DOWNGRADE_SEATS"
    TERMINATE = "TERMINATE"
    SANCTION = "SANCTION"


class RecommendationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    IMPLEMENTED = "IMPLEMENTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


# ---- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ----

class Vendor(TypedDict):
    id: str
    name: str
    vendor_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    vendor_id: str
    term_start: str
    term_end: str
    renewal_notice_days: int
    renewal_term_months: int
    auto_renew: bool
    volume_tier_enabled: bool
    status: str
    monthly_committed_cost_cents: int
    total_recovered_cents: int
    renewal_count: int
    created_at: str
    updated_at: str
    version: int


class Service(TypedDict):
    id: str
    contract_id: str
    service_type: str
    license_type: str
    unit_rate_cents: int
    contracted_quantity: int
    active_quantity: int
    discovery_source: str
    sanctioned: bool
    utilization_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    contract_id: str
    period_start: str
    period_end: str
    status: str
    billed_amount_cents: int
    expected_amount_cents: int
    variance_cents: int
    net_amount_cents: int
    balance_due_cents: int
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InvoiceLineItem(TypedDict):
    id: str
    invoice_id: str
    service_id: str
    billing_period_start: str
    billing_period_end: str
    billed_quantity: int
    billed_amount_cents: int
    expected_amount_cents: int
    variance_cents: int
    credited_amount_cents: int
    net_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    invoice_line_item_id: str
    disputed_amount_cents: int
    claimed_credit_cents: int
    offered_credit_cents: int
    recovered_credit_cents: int
    response_type: str
    round_count: int
    reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only ledger entry, ONLY id + created_at
class Credit(TypedDict):
    id: str
    dispute_id: str
    invoice_line_item_id: str
    amount_cents: int
    status: str
    created_at: str


class CostCenter(TypedDict):
    id: str
    code: str
    gl_account: str
    owner_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict):
    id: str
    invoice_line_item_id: str
    cost_center_id: str
    weight_pct: float
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Recommendation(TypedDict):
    id: str
    service_id: str
    rec_type: str
    target_quantity: int
    projected_savings_cents: int
    realized_savings_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
