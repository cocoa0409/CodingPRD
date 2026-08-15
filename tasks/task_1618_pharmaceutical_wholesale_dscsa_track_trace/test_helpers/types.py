"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4: every primary resource carries id, created_at, updated_at, version.
The EpcisEvent ledger entry is the sole exception — it carries only id and
created_at; updated_at and version are absent from it entirely.
"""
from enum import Enum
from typing import TypedDict, Optional


class PartnerKind(str, Enum):
    CUSTOMER = "CUSTOMER"
    SUPPLIER = "SUPPLIER"


class LicenseScope(str, Enum):
    RX_ONLY = "RX_ONLY"
    RX_AND_CONTROLLED = "RX_AND_CONTROLLED"
    RX_AND_COLD_CHAIN = "RX_AND_COLD_CHAIN"
    FULL = "FULL"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class ShortageStatus(str, Enum):
    NORMAL = "NORMAL"
    SHORTAGE = "SHORTAGE"


class PolicyMode(str, Enum):
    PRO_RATA = "PRO_RATA"
    EQUAL_SHARE = "EQUAL_SHARE"


class PolicyStatus(str, Enum):
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"


class CaseStatus(str, Enum):
    COMMISSIONED = "COMMISSIONED"
    SHIPPED = "SHIPPED"
    RECEIVED = "RECEIVED"
    QUARANTINED = "QUARANTINED"
    DECOMMISSIONED = "DECOMMISSIONED"


class UnitStatus(str, Enum):
    COMMISSIONED = "COMMISSIONED"
    SHIPPED = "SHIPPED"
    RECEIVED = "RECEIVED"
    QUARANTINED = "QUARANTINED"
    DECOMMISSIONED = "DECOMMISSIONED"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class FinancialStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    CREDITED = "CREDITED"


class LineStatus(str, Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    PARTIALLY_ALLOCATED = "PARTIALLY_ALLOCATED"
    UNFULFILLABLE = "UNFULFILLABLE"


class EpcisEventType(str, Enum):
    COMMISSION = "COMMISSION"
    AGGREGATE = "AGGREGATE"
    SHIP = "SHIP"
    RECEIVE = "RECEIVE"
    QUARANTINE = "QUARANTINE"
    RELEASE = "RELEASE"
    DECOMMISSION = "DECOMMISSION"


class InvestigationStatus(str, Enum):
    OPEN = "OPEN"
    QUARANTINED = "QUARANTINED"
    CLEARED = "CLEARED"
    CONFIRMED_ILLEGITIMATE = "CONFIRMED_ILLEGITIMATE"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VALIDATED = "VALIDATED"
    SETTLED = "SETTLED"
    DENIED = "DENIED"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RECEIVED = "RECEIVED"
    CREDITED = "CREDITED"
    REJECTED = "REJECTED"


class SegregationMode(str, Enum):
    STANDARD = "STANDARD"
    CONTROLLED = "CONTROLLED"
    COLD_CHAIN = "COLD_CHAIN"
    SEGREGATED_COMBINED = "SEGREGATED_COMBINED"


class UserRole(str, Enum):
    ORDER_MANAGER = "OrderManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    WAREHOUSE_OPERATOR = "WarehouseOperator"
    QUALITY_ASSURANCE_LEAD = "QualityAssuranceLead"
    BILLING_CLERK = "BillingClerk"
    CONTRACT_ADMINISTRATOR = "ContractAdministrator"


class TradingPartner(TypedDict, total=False):
    id: str
    partner_name: str
    partner_kind: str
    dea_number: str
    credit_limit_cents: int
    open_receivable_cents: int
    allocation_watermark_units: int
    created_at: str
    updated_at: str
    version: int


class PartnerStateLicense(TypedDict, total=False):
    id: str
    partner_id: str
    state_code: str
    license_number: str
    license_scope: str
    valid_from: str
    valid_to: str
    license_status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    ndc: str
    product_name: str
    is_controlled: bool
    is_cold_chain: bool
    wholesale_acquisition_cost_cents: int
    is_340b_contracted: bool
    contract_340b_price_cents: Optional[int]
    shortage_status: str
    created_at: str
    updated_at: str
    version: int


class AllocationPolicy(TypedDict, total=False):
    id: str
    product_id: str
    pool_units: int
    remaining_units: int
    policy_mode: str
    min_guarantee_units: int
    policy_status: str
    created_at: str
    updated_at: str
    version: int


class SerializedCase(TypedDict, total=False):
    id: str
    sscc: str
    product_id: str
    lot_number: str
    expiry_date: str
    case_status: str
    quarantine_link_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SerializedUnit(TypedDict, total=False):
    id: str
    sni: str
    case_id: str
    unit_status: str
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict, total=False):
    id: str
    customer_id: str
    ship_to_state: str
    fulfillment_status: str
    financial_status: str
    invoice_total_cents: int
    invoice_balance_cents: int
    is_340b_order: bool
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    product_id: str
    quantity_requested: int
    quantity_allocated: int
    unit_price_cents: int
    extended_price_cents: int
    line_status: str
    created_at: str
    updated_at: str
    version: int


class EpcisEvent(TypedDict, total=False):
    # Append-only ledger entry (PRD §2.4): carries ONLY id + created_at.
    # No updated_at, no version.
    id: str
    event_type: str
    subject_case_id: str
    order_id: Optional[str]
    event_time: str
    recorded_at: str
    sender_partner_id: str
    recipient_partner_id: str
    txn_history_hash: str
    created_at: str


class SuspectInvestigation(TypedDict, total=False):
    id: str
    case_id: str
    opened_reason: str
    investigation_status: str
    reopen_count: int
    quarantined_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChargebackClaim(TypedDict, total=False):
    id: str
    order_id: str
    claimed_amount_cents: int
    computed_amount_cents: int
    claim_status: str
    created_at: str
    updated_at: str
    version: int


class ReturnAuthorization(TypedDict, total=False):
    id: str
    order_id: str
    product_id: str
    quantity_returned: int
    return_status: str
    credit_amount_cents: int
    created_at: str
    updated_at: str
    version: int
