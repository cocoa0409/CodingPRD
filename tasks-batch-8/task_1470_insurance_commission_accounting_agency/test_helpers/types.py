"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    AGENCY_ADMIN = "AgencyAdmin"
    AGENCY_ACCOUNTANT = "AgencyAccountant"
    PRODUCER = "Producer"


class ProducerTier(str, Enum):
    STANDARD = "STANDARD"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class ProducerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class LineOfBusiness(str, Enum):
    LIFE = "LIFE"
    ANNUITY = "ANNUITY"
    HEALTH = "HEALTH"
    PROPERTY_CASUALTY = "PROPERTY_CASUALTY"


class ScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class BillingType(str, Enum):
    AGENCY_BILL = "AGENCY_BILL"
    DIRECT_BILL = "DIRECT_BILL"


class PolicyStatus(str, Enum):
    QUOTED = "QUOTED"
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    CANCELLED_VOLUNTARY = "CANCELLED_VOLUNTARY"
    CANCELLED_NONPAY = "CANCELLED_NONPAY"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    DELINQUENT = "DELINQUENT"
    PAID = "PAID"


class StatementStatus(str, Enum):
    RECEIVED = "RECEIVED"
    RECONCILING = "RECONCILING"
    DISPUTED = "DISPUTED"
    RECONCILED = "RECONCILED"


class LineMatchStatus(str, Enum):
    UNMATCHED = "UNMATCHED"
    MATCHED = "MATCHED"
    VARIANCE_FLAGGED = "VARIANCE_FLAGGED"
    ORPHAN = "ORPHAN"
    WAIVED = "WAIVED"


class EntryType(str, Enum):
    BASE = "BASE"
    OVERRIDE = "OVERRIDE"
    EARNED_ADJUSTMENT = "EARNED_ADJUSTMENT"
    VARIANCE_ADJUSTMENT = "VARIANCE_ADJUSTMENT"


class EntryVariant(str, Enum):
    ANNUALIZED_FULL = "ANNUALIZED_FULL"
    ADVANCE_LIMITED = "ADVANCE_LIMITED"


class EntryStatus(str, Enum):
    EXPECTED = "EXPECTED"
    MATCHED = "MATCHED"
    VARIANCE = "VARIANCE"
    CHARGED_BACK = "CHARGED_BACK"


class ChargebackReason(str, Enum):
    CANCELLATION_UNEARNED = "CANCELLATION_UNEARNED"
    NONPAY_LAPSE = "NONPAY_LAPSE"
    OVERPAYMENT_VARIANCE = "OVERPAYMENT_VARIANCE"


class ChargebackStatus(str, Enum):
    PENDING = "PENDING"
    RECOVERED = "RECOVERED"
    WRITTEN_OFF = "WRITTEN_OFF"


class DisclosureStatus(str, Enum):
    GENERATED = "GENERATED"
    DELIVERED = "DELIVERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class PayoutStatus(str, Enum):
    INITIATED = "INITIATED"
    PAID = "PAID"


class TaxFormStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


# All resources carry the common fields of PRD §2.5: id, created_at,
# updated_at, version.


class Producer(TypedDict, total=False):
    id: str
    name: str
    license_number: str
    tier: str
    upline_producer_id: Optional[str]
    tax_form_on_file: bool
    status: str
    commission_balance_cents: int
    pending_chargebacks_cents: int
    created_at: str
    updated_at: str
    version: int


class Carrier(TypedDict, total=False):
    id: str
    name: str
    carrier_code: str
    trust_balance_cents: int
    total_remitted_cents: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    carrier_id: str
    product_code: str
    name: str
    line_of_business: str
    created_at: str
    updated_at: str
    version: int


class CommissionSchedule(TypedDict, total=False):
    id: str
    product_id: str
    tier: str
    commission_rate_bps: int
    override_rate_bps: int
    advance_months: int
    effective_from: str
    effective_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict, total=False):
    id: str
    policy_number: str
    product_id: str
    producer_id: str
    insured_name: str
    billing_type: str
    premium_annual_cents: int
    effective_date: str
    status: str
    cancel_effective_date: Optional[str]
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PremiumInvoice(TypedDict, total=False):
    id: str
    policy_id: str
    amount_cents: int
    paid_total_cents: int
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StatementLine(TypedDict, total=False):
    line_ref: str
    reported_amount_cents: int
    match_status: str
    matched_entry_id: Optional[str]


class CarrierStatement(TypedDict, total=False):
    id: str
    carrier_id: str
    period_start: str
    period_end: str
    lines: list
    total_reported_cents: int
    matched_total_cents: int
    expected_matched_total_cents: int
    variance_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CommissionEntry(TypedDict, total=False):
    id: str
    policy_id: str
    producer_id: str
    schedule_id: str
    entry_type: str
    amount_cents: int
    annualized_full_amount_cents: int
    variant: str
    status: str
    matched_statement_id: Optional[str]
    matched_at: Optional[str]
    source_entry_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Chargeback(TypedDict, total=False):
    id: str
    policy_id: str
    producer_id: str
    commission_entry_id: str
    reason: str
    amount_cents: int
    recovered_cents: int
    outstanding_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProducerDisclosure(TypedDict, total=False):
    id: str
    policy_id: str
    producer_id: str
    projected_comp_cents: int
    status: str
    disclosed_at: Optional[str]
    acknowledged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProducerPayout(TypedDict, total=False):
    id: str
    producer_id: str
    amount_cents: int
    status: str
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaxForm1099(TypedDict, total=False):
    id: str
    producer_id: str
    tax_year: int
    cash_basis_total_cents: int
    accrual_basis_total_cents: int
    status: str
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
