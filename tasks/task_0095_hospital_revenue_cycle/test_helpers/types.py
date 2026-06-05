"""Domain types: entity TypedDicts, status enums, role enum.

All names and fields follow the Hospital Revenue Cycle PRD exactly.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1 — exactly four roles)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    REGISTRAR = "Registrar"
    CODER = "Coder"
    BILLING_SPECIALIST = "BillingSpecialist"
    FINANCE_MANAGER = "FinanceManager"


# ---------------------------------------------------------------------------
# Status / enum value sets
# ---------------------------------------------------------------------------
class PayerType(str, Enum):
    COMMERCIAL = "COMMERCIAL"
    MEDICARE = "MEDICARE"
    MEDICAID = "MEDICAID"
    SELF_PAY = "SELF_PAY"


class FinancialClass(str, Enum):
    INSURED = "INSURED"
    SELF_PAY = "SELF_PAY"
    CHARITY = "CHARITY"


class PolicyStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class EncounterStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ELIGIBILITY_VERIFIED = "ELIGIBILITY_VERIFIED"
    CHARGES_CAPTURED = "CHARGES_CAPTURED"
    CODED = "CODED"
    BILLED = "BILLED"
    CLOSED = "CLOSED"


class EligibilityResult(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class ChargeStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class CodingStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    AUDIT_HOLD = "AUDIT_HOLD"
    CLEARED = "CLEARED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    DENIED = "DENIED"
    CORRECTED = "CORRECTED"
    APPEALED = "APPEALED"
    VOID = "VOID"


class DenialReason(str, Enum):
    CODING_ERROR = "CODING_ERROR"
    NOT_COVERED = "NOT_COVERED"
    TIMELY_FILING = "TIMELY_FILING"
    DUPLICATE = "DUPLICATE"


class StatementStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    IN_COLLECTIONS = "IN_COLLECTIONS"
    WRITTEN_OFF = "WRITTEN_OFF"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    CASH = "CASH"
    CHECK = "CHECK"
    EFT = "EFT"


class WriteOffReason(str, Enum):
    BAD_DEBT = "BAD_DEBT"
    CHARITY = "CHARITY"
    SMALL_BALANCE = "SMALL_BALANCE"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Mutable accounts carry id + created_at + updated_at + version (PRD §2.4).
# Immutable ledger entries (Payment, WriteOff) carry ONLY id + created_at.
# ---------------------------------------------------------------------------
class Payer(TypedDict):
    id: str
    name: str
    payer_type: str
    timely_filing_days: int
    appeal_window_days: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    financial_class: str
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict):
    id: str
    patient_id: str
    payer_id: str
    member_number: str
    plan_year: int
    deductible_cents: int
    coinsurance_pct: float
    oop_max_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BenefitAccumulator(TypedDict):
    id: str
    policy_id: str
    plan_year: int
    deductible_met_cents: int
    oop_met_cents: int
    created_at: str
    updated_at: str
    version: int


class Encounter(TypedDict):
    id: str
    patient_id: str
    policy_id: Optional[str]
    admission_at: str
    discharge_at: Optional[str]
    status: str
    total_charges_cents: int
    patient_responsibility_cents: int
    account_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class EligibilityCheck(TypedDict):
    id: str
    encounter_id: str
    policy_id: str
    result: str
    estimated_patient_responsibility_cents: int
    checked_at: str
    created_at: str
    updated_at: str
    version: int


class Charge(TypedDict):
    id: str
    encounter_id: str
    cpt_code: str
    units: int
    unit_price_cents: int
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CodingAssignment(TypedDict):
    id: str
    encounter_id: str
    principal_icd10: str
    secondary_icd10: List[str]
    status: str
    finalized_by_user_id: Optional[str]
    compliance_risk_score: int
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    encounter_id: str
    policy_id: str
    payer_id: str
    billed_amount_cents: int
    allowed_amount_cents: Optional[int]
    status: str
    denial_reason: Optional[str]
    submitted_at: str
    patient_responsibility_cents: int
    created_at: str
    updated_at: str
    version: int


class ClaimLine(TypedDict):
    id: str
    claim_id: str
    cpt_code: str
    line_allowed_cents: int
    line_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class PatientStatement(TypedDict):
    id: str
    encounter_id: str
    amount_due_cents: int
    amount_paid_cents: int
    written_off_cents: int
    status: str
    issued_at: str
    created_at: str
    updated_at: str
    version: int


# Immutable ledger entries — NO updated_at, NO version (PRD §2.4).
class Payment(TypedDict):
    id: str
    statement_id: str
    amount_cents: int
    method: str
    posted_at: str
    created_at: str


class WriteOff(TypedDict):
    id: str
    statement_id: str
    amount_cents: int
    reason: str
    approved_by_user_id: str
    approved_at: str
    created_at: str
