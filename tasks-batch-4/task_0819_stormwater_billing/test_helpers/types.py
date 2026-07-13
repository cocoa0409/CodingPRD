"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PROPERTY_OWNER = "PropertyOwner"
    ASSESSOR = "Assessor"
    BILLING_CLERK = "BillingClerk"
    CREDIT_INSPECTOR = "CreditInspector"
    STORMWATER_ADMIN = "StormwaterAdmin"


class AccountBillingMethod(str, Enum):
    TAX_ROLL = "TAX_ROLL"
    UTILITY_BILL = "UTILITY_BILL"


class DelinquencyStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    DELINQUENT = "DELINQUENT"


class ParcelStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"


class MeasurementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ExemptionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class BMPCreditStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class BillStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DELINQUENT = "DELINQUENT"
    ADJUSTED = "ADJUSTED"
    VOID = "VOID"


class FeeVariant(str, Enum):
    MARGINAL = "MARGINAL"
    FLAT = "FLAT"


class AppealStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_REMEASURE = "NEEDS_REMEASURE"
    UPHELD = "UPHELD"
    DENIED = "DENIED"


class PaymentStatus(str, Enum):
    APPLIED = "APPLIED"
    REFUNDED = "REFUNDED"


class Fund(str, Enum):
    CAPITAL = "CAPITAL"
    OPERATING = "OPERATING"


class FundEntryType(str, Enum):
    ALLOCATION = "ALLOCATION"
    REVERSAL = "REVERSAL"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---

class Account(TypedDict):
    id: str
    owner_name: str
    contact_email: str
    billing_method: str
    mailing_address: Optional[str]
    outstanding_balance_cents: int
    delinquency_status: str
    created_at: str
    updated_at: str
    version: int


class Parcel(TypedDict):
    id: str
    account_id: str
    parcel_number: str
    land_use: str
    status: str
    active_measurement_id: Optional[str]
    impervious_area_sqft: int
    exempt_pct: float
    billable_eru: float
    current_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class ImperviousMeasurement(TypedDict):
    id: str
    parcel_id: str
    measured_sqft: int
    method: str
    source: str
    status: str
    recorded_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Exemption(TypedDict):
    id: str
    parcel_id: str
    category: str
    requested_pct: float
    granted_pct: float
    status: str
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BMPCredit(TypedDict):
    id: str
    parcel_id: str
    bmp_type: str
    self_reported_score: float
    inspected_score: Optional[float]
    credit_pct: float
    status: str
    effective_date: str
    expiry_date: str
    next_inspection_due: str
    created_at: str
    updated_at: str
    version: int


class CreditInspection(TypedDict):
    id: str
    bmp_credit_id: str
    scheduled_date: str
    observed_score: Optional[float]
    result: Optional[str]
    status: str
    inspector_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StormwaterBill(TypedDict):
    id: str
    parcel_id: str
    account_id: str
    period_start: str
    period_end: str
    due_date: str
    fee_variant: str
    eru_snapshot: float
    base_fee_cents: int
    fixed_charge_cents: int
    credit_amount_cents: int
    penalty_cents: int
    assessed_fee_cents: int
    net_fee_cents: int
    amount_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    parcel_id: str
    bill_id: Optional[str]
    account_id: str
    grounds: str
    narrative: str
    status: str
    resolution_note: Optional[str]
    filed_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    bill_id: str
    account_id: str
    amount_cents: int
    applied_amount_cents: int
    method: str
    status: str
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable audit record, ONLY id + created_at.
class FundLedgerEntry(TypedDict):
    id: str
    source_payment_id: str
    fund: str
    amount_cents: int
    entry_type: str
    created_at: str
