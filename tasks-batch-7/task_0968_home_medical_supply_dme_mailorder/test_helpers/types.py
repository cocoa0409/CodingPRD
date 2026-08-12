"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class PlanType(str, Enum):
    MEDICARE_DMEPOS = "MEDICARE_DMEPOS"
    COMMERCIAL = "COMMERCIAL"
    CASH_HSA = "CASH_HSA"


class Category(str, Enum):
    OSTOMY = "OSTOMY"
    INCONTINENCE = "INCONTINENCE"
    WOUND = "WOUND"


class PatientStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    INELIGIBLE = "INELIGIBLE"


class PrescriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class FitProfileStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_FULFILLMENT = "IN_FULFILLMENT"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    CLAIM_DRAFT = "CLAIM_DRAFT"
    CLAIM_SUBMITTED = "CLAIM_SUBMITTED"
    CLAIM_DENIED = "CLAIM_DENIED"
    APPEAL_PENDING = "APPEAL_PENDING"
    PAID_SETTLED = "PAID_SETTLED"
    PATIENT_BILLED = "PATIENT_BILLED"


class OrderOrigin(str, Enum):
    PROGRAM_CYCLE = "PROGRAM_CYCLE"
    MANUAL_REORDER = "MANUAL_REORDER"


class PriorAuthStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    EXPIRED = "EXPIRED"


class ShipmentStatus(str, Enum):
    CREATED = "CREATED"
    BACKORDERED = "BACKORDERED"
    READY = "READY"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class BackorderStatus(str, Enum):
    PENDING = "PENDING"
    PARTIALLY_ALLOCATED = "PARTIALLY_ALLOCATED"
    ALLOCATED = "ALLOCATED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    DENIED_FINAL = "DENIED_FINAL"


class LedgerEntryType(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"
    REVERSAL = "REVERSAL"


class SampleStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SHIPPED = "SHIPPED"
    OUTCOME_RECORDED = "OUTCOME_RECORDED"


class SampleOutcome(str, Enum):
    CONVERTED = "CONVERTED"
    NOT_CONVERTED = "NOT_CONVERTED"


class UserRole(str, Enum):
    PATIENT = "Patient"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    PRIOR_AUTH_SPECIALIST = "PriorAuthSpecialist"
    FULFILLMENT_AGENT = "FulfillmentAgent"
    BILLING_SPECIALIST = "BillingSpecialist"
    PLATFORM_ADMIN = "PlatformAdmin"


class PayerPlan(TypedDict, total=False):
    id: str
    name: str
    plan_type: str
    coinsurance_pct: float
    cycle_months: int
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class FormularyItem(TypedDict, total=False):
    id: str
    hcpcs_code: str
    name: str
    category: str
    covered_plan_ids: List[str]
    pack_fee_cents: float
    pack_size: int
    unit_allowance_cents: float
    retail_price_cents: float
    max_units_per_cycle: int
    requires_pa: bool
    size_codes: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    payer_plan_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Prescription(TypedDict, total=False):
    id: str
    patient_id: str
    hcpcs_code: str
    prescriber_npi: str
    diagnosis_codes: List[str]
    monthly_quantity: int
    effective_date: str
    expiration_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FitProfile(TypedDict, total=False):
    id: str
    patient_id: str
    category: str
    size_code: str
    measured_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ResupplyProgram(TypedDict, total=False):
    id: str
    patient_id: str
    category: str
    frequency_days: int
    start_date: str
    next_eligible_date: str
    last_delivered_date: Optional[str]
    adherence_score_provisional: float
    adherence_score_final: float
    status: str
    suspend_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupplyOrder(TypedDict, total=False):
    id: str
    patient_id: str
    resupply_program_id: Optional[str]
    origin: str
    fulfillment_status: str
    billing_status: str
    total_allowed_cents: float
    total_patient_resp_cents: float
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    formulary_item_id: str
    hcpcs_code: str
    size_code: str
    quantity: int
    unit_allowance_cents: float
    line_allowed_cents: float
    created_at: str
    updated_at: str
    version: int


class PriorAuthorization(TypedDict, total=False):
    id: str
    patient_id: str
    hcpcs_code: str
    approved_units: int
    valid_from: str
    valid_to: str
    status: str
    appeal_count: int
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    order_id: str
    status: str
    shipped_date: Optional[str]
    delivered_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StockLevel(TypedDict, total=False):
    id: str
    formulary_item_id: str
    on_hand_qty: int
    reserved_qty: int
    available_qty: int
    created_at: str
    updated_at: str
    version: int


class BackorderReservation(TypedDict, total=False):
    id: str
    order_line_id: str
    quantity_pending: int
    quantity_allocated: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    order_id: str
    status: str
    total_allowed_cents: float
    insurer_paid_cents: float
    patient_resp_cents: float
    adjudicated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HSAAccount(TypedDict, total=False):
    id: str
    patient_id: str
    initial_credit_cents: float
    balance_cents: float
    created_at: str
    updated_at: str
    version: int


# Append-only ledger entry: carries id + created_at only (no updated_at, no version)
class HSALedgerEntry(TypedDict, total=False):
    id: str
    hsa_account_id: str
    entry_type: str
    amount_cents: float
    reason: str
    related_order_id: Optional[str]
    reverses_entry_id: Optional[str]
    status: str
    created_at: str


class FittingSample(TypedDict, total=False):
    id: str
    patient_id: str
    category: str
    size_code: str
    item_name: str
    unit_price_cents: float
    status: str
    outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int
