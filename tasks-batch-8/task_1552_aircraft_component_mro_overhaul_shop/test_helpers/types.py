"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4: every primary resource carries id, created_at, updated_at, version.
Three resource families are immutable ledgers and carry only id and created_at:
DirectiveRecord, ReleaseCertificate, and TraceabilityRecord.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class PenaltyDelayRule(str, Enum):
    ADJUSTED = "ADJUSTED"
    CALENDAR = "CALENDAR"


class DirectiveType(str, Enum):
    AD = "AD"
    SB = "SB"


class Ownership(str, Enum):
    SHOP = "SHOP"
    CUSTOMER = "CUSTOMER"


class ConditionStatus(str, Enum):
    SERVICEABLE = "SERVICEABLE"
    UNSERVICEABLE = "UNSERVICEABLE"
    SCRAPPED = "SCRAPPED"


class CustodyStatus(str, Enum):
    OFF_SITE = "OFF_SITE"
    IN_SHOP = "IN_SHOP"
    AWAITING_SHIPMENT = "AWAITING_SHIPMENT"
    SHIPPED = "SHIPPED"
    IN_POOL = "IN_POOL"
    ON_LEASE = "ON_LEASE"


class WorkScope(str, Enum):
    REPAIR = "REPAIR"
    OVERHAUL = "OVERHAUL"
    WARRANTY_REWORK = "WARRANTY_REWORK"


class WorkOrderStatus(str, Enum):
    TEARDOWN_IN_PROGRESS = "TEARDOWN_IN_PROGRESS"
    AWAITING_QUOTE = "AWAITING_QUOTE"
    QUOTE_SUBMITTED = "QUOTE_SUBMITTED"
    REPAIR_IN_PROGRESS = "REPAIR_IN_PROGRESS"
    AWAITING_PARTS = "AWAITING_PARTS"
    READY_FOR_TEST = "READY_FOR_TEST"
    TEST_PASSED = "TEST_PASSED"
    RELEASED = "RELEASED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    BER_SCRAPPED = "BER_SCRAPPED"


class DiscrepancySeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class DiscrepancyStatus(str, Enum):
    OPEN = "OPEN"
    DISPOSITIONED = "DISPOSITIONED"
    CLOSED = "CLOSED"


class DirectiveComplianceStatus(str, Enum):
    PENDING = "PENDING"
    COMPLIED = "COMPLIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class PartsSource(str, Enum):
    OEM = "OEM"
    PMA = "PMA"


class PartsRequisitionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PMA_PENDING_CUSTOMER = "PMA_PENDING_CUSTOMER"
    APPROVED = "APPROVED"
    SOURCE_REJECTED = "SOURCE_REJECTED"
    PMA_REJECTED = "PMA_REJECTED"
    RECEIVED = "RECEIVED"
    ISSUED = "ISSUED"


class TestCellBookingStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ExchangeAgreementStatus(str, Enum):
    OPEN = "OPEN"
    FULFILLED = "FULFILLED"
    CLOSED = "CLOSED"
    DEFAULTED = "DEFAULTED"


class LeaseAgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"


class CreditVariant(str, Enum):
    FULL = "FULL"
    PRORATED = "PRORATED"


class InvoiceSourceType(str, Enum):
    WORK_ORDER = "WORK_ORDER"
    EXCHANGE = "EXCHANGE"
    LEASE = "LEASE"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"


class PenaltyVariant(str, Enum):
    ADJUSTED = "ADJUSTED"
    CALENDAR = "CALENDAR"
    NONE = "NONE"


class TraceabilityEventType(str, Enum):
    BIRTH = "BIRTH"
    INDUCT = "INDUCT"
    DISPOSITION = "DISPOSITION"
    RELEASE_OVERHAUL = "RELEASE_OVERHAUL"
    RELEASE_REPAIR = "RELEASE_REPAIR"
    SCRAP = "SCRAP"
    EXCHANGE_OUT = "EXCHANGE_OUT"
    CORE_IN = "CORE_IN"
    LEASE_OUT = "LEASE_OUT"
    LEASE_RETURN = "LEASE_RETURN"
    WARRANTY_INDUCT = "WARRANTY_INDUCT"


class UserRole(str, Enum):
    ShopManager = "ShopManager"
    CustomerServiceRep = "CustomerServiceRep"
    Technician = "Technician"
    Inspector = "Inspector"
    PartsBuyer = "PartsBuyer"
    Customer = "Customer"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields: true (id + created_at + updated_at + version)
# ---------------------------------------------------------------------------

class Customer(TypedDict, total=False):
    id: str
    name: str
    certificate_number: str
    contract_tat_hours: int
    tat_penalty_rate_cents_per_hour: int
    tat_penalty_cap_pct: int
    credit_limit_cents: int
    penalty_delay_rule: str
    current_exposure_cents: int
    credit_hold: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PartCatalogEntry(TypedDict, total=False):
    id: str
    part_number: str
    ata_chapter: str
    is_rotable: bool
    cmm_reference: str
    replacement_value_cents: int
    ber_threshold_pct: int
    warranty_cycle_limit: int
    warranty_month_limit: int
    flat_overhaul_price_cents: int
    created_at: str
    updated_at: str
    version: int


class ComponentUnit(TypedDict, total=False):
    id: str
    part_id: str
    serial_number: str
    ownership: str
    owner_customer_id: Optional[str]
    condition_status: str
    custody_status: str
    total_cycles: int
    cycles_since_overhaul: int
    manufactured_at: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    customer_id: str
    unit_id: str
    work_scope: str
    status: str
    received_at: str
    quote_submitted_at: Optional[str]
    accumulated_delay_hours: float
    promised_return_at: str
    released_at: Optional[str]
    labor_estimate_cents: int
    parts_estimate_cents: int
    ber_flag: bool
    labor_charge_cents: int
    parts_charge_cents: int
    test_attempt_count: int
    open_discrepancy_count: int
    technician_user_id: Optional[str]
    inspector_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DiscrepancyCard(TypedDict, total=False):
    id: str
    work_order_id: str
    finding_text: str
    severity: str
    disposition_text: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DirectiveCompliance(TypedDict, total=False):
    id: str
    work_order_id: str
    directive_number: str
    directive_type: str
    mandatory: bool
    status: str
    compliance_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PartsRequisition(TypedDict, total=False):
    id: str
    work_order_id: str
    part_number: str
    quantity: int
    requested_source: str
    approved_source: Optional[str]
    status: str
    unit_cost_cents: Optional[int]
    extended_price_cents: int
    created_at: str
    updated_at: str
    version: int


class TestCell(TypedDict, total=False):
    id: str
    name: str
    supported_ata_chapters: List[str]
    hourly_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class TestCellBooking(TypedDict, total=False):
    id: str
    test_cell_id: str
    work_order_id: str
    start_time: str
    end_time: str
    status: str
    fee_cents: int
    created_at: str
    updated_at: str
    version: int


class ExchangeAgreement(TypedDict, total=False):
    id: str
    customer_id: str
    part_id: str
    status: str
    pool_unit_id: Optional[str]
    fulfilled_at: Optional[str]
    core_due_date: Optional[str]
    core_unit_id: Optional[str]
    core_received_at: Optional[str]
    core_ber_flag: bool
    core_charge_cents: int
    late_fee_cents: int
    admin_fee_cents: int
    settlement_total_cents: int
    created_at: str
    updated_at: str
    version: int


class LeaseAgreement(TypedDict, total=False):
    id: str
    customer_id: str
    unit_id: str
    daily_rate_cents: int
    start_date: str
    end_date: str
    returned_at: Optional[str]
    status: str
    billed_days: int
    overage_days: int
    total_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    customer_id: str
    original_work_order_id: str
    unit_id: str
    claim_cycles_used: int
    claim_months_used: int
    failure_description: str
    status: str
    credit_variant: Optional[str]
    credit_cents: int
    rework_work_order_id: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    source_type: str
    work_order_id: Optional[str]
    exchange_agreement_id: Optional[str]
    lease_agreement_id: Optional[str]
    customer_id: str
    labor_cents: int
    parts_cents: int
    test_fee_cents: int
    penalty_credit_cents: int
    other_charge_cents: int
    total_cents: int
    warranty_credit_applied_cents: int
    penalty_variant: str
    status: str
    issued_at: str
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only ledger entities (common_fields: false) — ONLY id + created_at
# ---------------------------------------------------------------------------

class DirectiveRecord(TypedDict, total=False):
    id: str
    part_id: str
    directive_type: str
    directive_number: str
    mandatory: bool
    description: str
    created_at: str


class ReleaseCertificate(TypedDict, total=False):
    id: str
    work_order_id: str
    cert_number: str
    signed_by: str
    issued_at: str
    status: str
    created_at: str


class TraceabilityRecord(TypedDict, total=False):
    id: str
    unit_id: str
    event_type: str
    event_at: str
    work_order_id: Optional[str]
    notes: Optional[str]
    created_at: str
