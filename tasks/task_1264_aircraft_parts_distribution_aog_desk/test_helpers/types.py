"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    AOG_DESK_AGENT = "AogDeskAgent"
    CUSTOMER_CONTACT = "CustomerContact"
    WAREHOUSE_OPERATOR = "WarehouseOperator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FINANCE_CONTROLLER = "FinanceController"
    WARRANTY_ADJUSTER = "WarrantyAdjuster"
    WARRANTY_APPROVER = "WarrantyApprover"
    PLATFORM_OPS = "PlatformOps"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PriorityTier(str, Enum):
    STANDARD = "STANDARD"
    PRIORITY = "PRIORITY"
    PLATINUM = "PLATINUM"


class PartCondition(str, Enum):
    NEW = "NEW"
    OVERHAULED = "OVERHAULED"
    SERVICEABLE = "SERVICEABLE"
    AS_REMOVED = "AS_REMOVED"


class TraceDocLevel(str, Enum):
    TRACE_MISSING = "TRACE_MISSING"
    TEARDOWN_REPORT = "TEARDOWN_REPORT"
    FAA_8130 = "FAA_8130"
    EASA_FORM1 = "EASA_FORM1"
    DUAL_RELEASE = "DUAL_RELEASE"


# Trace doc rank order per PRD §2.7
TRACE_DOC_RANK = {
    "TRACE_MISSING": 0,
    "TEARDOWN_REPORT": 1,
    "FAA_8130": 2,
    "EASA_FORM1": 3,
    "DUAL_RELEASE": 4,
}


class HazmatClass(str, Enum):
    NONE = "NONE"
    CLASS_2 = "CLASS_2"
    CLASS_3 = "CLASS_3"
    CLASS_9 = "CLASS_9"


class ExportControlCode(str, Enum):
    EAR99 = "EAR99"
    EAR9X610 = "EAR9X610"
    ITAR = "ITAR"


class UnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    SOLD = "SOLD"
    ON_LOAN = "ON_LOAN"
    UNDER_INSPECTION = "UNDER_INSPECTION"
    QUARANTINED = "QUARANTINED"
    SCRAPPED = "SCRAPPED"


class AogRequestStatus(str, Enum):
    OPEN = "OPEN"
    QUOTED = "QUOTED"
    FULFILLING = "FULFILLING"
    FULFILLED = "FULFILLED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class SaleType(str, Enum):
    OUTRIGHT = "OUTRIGHT"
    EXCHANGE = "EXCHANGE"
    LOAN = "LOAN"
    LEASE = "LEASE"


class FreightMode(str, Enum):
    STANDARD = "STANDARD"
    HOT_SHOT = "HOT_SHOT"
    CHARTER = "CHARTER"


class FulfillmentStatus(str, Enum):
    PENDING_ALLOCATION = "PENDING_ALLOCATION"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"


class ComplianceStatus(str, Enum):
    PENDING_SCREENING = "PENDING_SCREENING"
    CLEARED = "CLEARED"
    EXPORT_HELD = "EXPORT_HELD"
    BLOCKED = "BLOCKED"


class PaymentStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"


class AllocationStatus(str, Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"


class ShipmentStatus(str, Enum):
    DRAFT = "DRAFT"
    TENDERED = "TENDERED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    EXCEPTION = "EXCEPTION"


class CharterSlotStatus(str, Enum):
    OPEN = "OPEN"
    BOOKED = "BOOKED"
    RELEASED = "RELEASED"


class CoreReturnStatus(str, Enum):
    OPEN = "OPEN"
    OVERDUE = "OVERDUE"
    RECEIVED = "RECEIVED"
    SETTLED = "SETTLED"


class CoreVerdict(str, Enum):
    ACCEPTED = "ACCEPTED"
    ACCEPTED_WITH_PENALTY = "ACCEPTED_WITH_PENALTY"
    REJECTED = "REJECTED"


class LoanType(str, Enum):
    LOAN = "LOAN"
    LEASE = "LEASE"


class LoanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OVERDUE = "OVERDUE"
    RETURNED = "RETURNED"
    DAMAGE_REVIEW = "DAMAGE_REVIEW"
    SETTLED = "SETTLED"


class FaultCategory(str, Enum):
    DOA = "DOA"
    PREMATURE_FAILURE = "PREMATURE_FAILURE"
    COSMETIC = "COSMETIC"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    CREDIT_ISSUED = "CREDIT_ISSUED"
    REJECTED = "REJECTED"


class ConditionGrade(str, Enum):
    RESALEABLE = "RESALEABLE"
    DAMAGED = "DAMAGED"


class ReturnAuthStatus(str, Enum):
    APPROVED = "APPROVED"
    RECEIVED = "RECEIVED"
    SETTLED = "SETTLED"


class LedgerEntryType(str, Enum):
    INVOICE_DEBIT = "INVOICE_DEBIT"
    CORE_DEPOSIT_DEBIT = "CORE_DEPOSIT_DEBIT"
    FREIGHT_DEBIT = "FREIGHT_DEBIT"
    LOAN_DEBIT = "LOAN_DEBIT"
    LEASE_DEBIT = "LEASE_DEBIT"
    CORE_REFUND_CREDIT = "CORE_REFUND_CREDIT"
    WARRANTY_CREDIT = "WARRANTY_CREDIT"
    RESTOCK_CREDIT = "RESTOCK_CREDIT"
    WAIVER_CREDIT = "WAIVER_CREDIT"
    PAYMENT_CREDIT = "PAYMENT_CREDIT"
    MANUAL_DEBIT = "MANUAL_DEBIT"
    MANUAL_CREDIT = "MANUAL_CREDIT"


class LedgerReferenceType(str, Enum):
    SALES_ORDER = "SALES_ORDER"
    SHIPMENT = "SHIPMENT"
    CORE_RETURN = "CORE_RETURN"
    LOAN_AGREEMENT = "LOAN_AGREEMENT"
    WARRANTY_CLAIM = "WARRANTY_CLAIM"
    RETURN_AUTH = "RETURN_AUTH"
    CUSTOMER = "CUSTOMER"


# --- Entity TypedDicts ---
# Primary business resources carry id, created_at, updated_at, version (PRD §2.4).

class Customer(TypedDict, total=False):
    id: str
    name: str
    country_code: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    priority_tier: str
    core_returns_settled_180d: int
    core_returns_on_time_180d: int
    warranty_fraud_flags: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PartMaster(TypedDict, total=False):
    id: str
    part_number: str
    description: str
    rotable: bool
    hazmat_class: str
    export_control_code: str
    list_price_cents: int
    core_value_cents: int
    warranty_months: int
    available_count: int
    reserved_count: int
    created_at: str
    updated_at: str
    version: int


class InventoryUnit(TypedDict, total=False):
    id: str
    part_id: str
    serial_number: str
    condition: str
    trace_doc_level: str
    warehouse_code: str
    status: str
    reserved_by_request_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AogRequest(TypedDict, total=False):
    id: str
    customer_id: str
    aircraft_tail: str
    airport_code: str
    part_id: str
    quantity: int
    condition_acceptable: List[str]
    min_trace_doc: str
    needed_by_utc: str
    escalated: bool
    status: str
    reserved_unit_id: Optional[str]
    last_search_candidate_count: int
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    aog_request_id: str
    customer_id: str
    lines: List[dict]
    validity_hours: int
    freight_mode: str
    distance_km: int
    chargeable_weight_kg: int
    destination_country: str
    revision_count: int
    status: str
    tier_at_issue: Optional[str]
    issued_at: Optional[str]
    expires_at: Optional[str]
    subtotal_cents: int
    handling_fee_cents: int
    tier_fee_cents: int
    freight_cost_cents: int
    total_cents: int
    max_penalty_cents: int
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict, total=False):
    id: str
    quote_id: str
    customer_id: str
    fulfillment_status: str
    compliance_status: str
    payment_status: str
    invoiced_cents: int
    freight_mode: str
    distance_km: int
    chargeable_weight_kg: int
    destination_country: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    part_id: str
    quantity: int
    sale_type: str
    condition_required: str
    unit_price_cents: int
    discount_pct: float
    line_total_cents: int
    lease_periods: Optional[int]
    allocated_unit_id: Optional[str]
    allocation_status: str
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    order_id: str
    hazmat_declaration_ref: Optional[str]
    export_license_ref: Optional[str]
    depart_at: Optional[str]
    arrive_at: Optional[str]
    charter_slot_id: Optional[str]
    freight_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CharterSlot(TypedDict, total=False):
    id: str
    tail_number: str
    home_base: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CoreReturn(TypedDict, total=False):
    id: str
    order_line_id: str
    customer_id: str
    core_value_cents: int
    due_at: str
    received_at: Optional[str]
    days_overdue: int
    penalty_cents: int
    refunded_cents: int
    penalty_retained_cents: int
    forfeited_cents: int
    penalty_waived_cents: int
    status: str
    verdict: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LoanAgreement(TypedDict, total=False):
    id: str
    customer_id: str
    unit_id: str
    order_line_id: Optional[str]
    loan_type: str
    daily_rate_cents: int
    lease_periods: Optional[int]
    start_at: str
    due_at: str
    returned_at: Optional[str]
    billed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    customer_id: str
    order_line_id: str
    fault_category: str
    description: str
    months_in_service: int
    coverage_pct: float
    credit_cents: int
    reviewed_by: Optional[str]
    reopen_count: int
    fraud_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnAuthorization(TypedDict, total=False):
    id: str
    customer_id: str
    order_line_id: str
    reason: str
    days_since_delivery: int
    restock_fee_cents: int
    credit_cents: int
    condition_grade: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only ledger entry (PRD §2.4 exception): carries ONLY id + created_at
# plus entry content — no updated_at, no version.
class AccountLedgerEntry(TypedDict, total=False):
    id: str
    created_at: str
    customer_id: str
    entry_type: str
    amount_cents: int
    reference_type: str
    reference_id: str
    memo: Optional[str]
