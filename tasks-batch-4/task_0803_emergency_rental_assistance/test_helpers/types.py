"""Domain types: entity TypedDicts, status enums, role enum for the ERAP API."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    TENANT = "Tenant"
    LANDLORD = "Landlord"
    CASE_WORKER = "CaseWorker"
    PROGRAM_ADMIN = "ProgramAdmin"
    FRAUD_INVESTIGATOR = "FraudInvestigator"


class ProgramStatus(str, Enum):
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"


class W9Status(str, Enum):
    MISSING = "MISSING"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DISBURSED = "DISBURSED"
    DENIED = "DENIED"
    CLOSED = "CLOSED"


class SectionStatus(str, Enum):
    INCOMPLETE = "INCOMPLETE"
    COMPLETE = "COMPLETE"


class HardshipType(str, Enum):
    JOB_LOSS = "JOB_LOSS"
    REDUCED_INCOME = "REDUCED_INCOME"
    MEDICAL = "MEDICAL"
    OTHER = "OTHER"


class IncomeSourceType(str, Enum):
    WAGES = "WAGES"
    SELF_EMPLOYMENT = "SELF_EMPLOYMENT"
    UNEMPLOYMENT = "UNEMPLOYMENT"
    SSI = "SSI"
    TANF = "TANF"
    CHILD_SUPPORT = "CHILD_SUPPORT"


class LedgerStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class LineType(str, Enum):
    CHARGE = "CHARGE"
    PAYMENT = "PAYMENT"
    ADJUSTMENT = "ADJUSTMENT"


class DisbursementStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    CLEARED = "CLEARED"
    FAILED = "FAILED"
    RECAPTURED = "RECAPTURED"


class CoverageKind(str, Enum):
    ARREARS = "ARREARS"
    PROSPECTIVE = "PROSPECTIVE"
    COMBINED = "COMBINED"


class RecertStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class RecaptureReason(str, Enum):
    DUPLICATE_BENEFIT = "DUPLICATE_BENEFIT"
    INCOME_MISREPRESENTATION = "INCOME_MISREPRESENTATION"
    VACATED_UNIT = "VACATED_UNIT"
    OTHER = "OTHER"


class RecaptureStatus(str, Enum):
    OPEN = "OPEN"
    SUBSTANTIATED = "SUBSTANTIATED"
    RECOVERED = "RECOVERED"
    DISMISSED = "DISMISSED"


# ---- Entity TypedDicts (all entities carry id/created_at/updated_at/version) ----

class Program(TypedDict, total=False):
    id: str
    name: str
    status: str
    funding_pool_total_cents: int
    funding_pool_remaining_cents: int
    months_cap: int
    per_month_max_cents: int
    monthly_income_limit_by_size: dict
    eligibility_ami_pct: float
    created_at: str
    updated_at: str
    version: int


class Tenant(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    household_size: int
    months_used: int
    created_at: str
    updated_at: str
    version: int


class Landlord(TypedDict, total=False):
    id: str
    legal_name: str
    email: str
    w9_status: str
    tin: str
    banking_last4: str
    mailing_address: str
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict, total=False):
    id: str
    landlord_id: str
    address: str
    monthly_rent_cents: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    program_id: str
    tenant_id: str
    landlord_id: str
    unit_id: str
    status: str
    tenant_section_status: str
    landlord_section_status: str
    hardship_type: str
    hardship_attested: bool
    monthly_rent_cents: int
    arrears_start_month: Optional[str]
    arrears_end_month: Optional[str]
    arrears_covered_months: int
    requested_prospective_months: int
    prospective_start_date: Optional[str]
    prospective_end_date: Optional[str]
    countable_monthly_income_cents: int
    ami_pct: float
    income_eligible: bool
    arrears_owed_cents: int
    arrears_award_cents: int
    prospective_award_cents: int
    total_award_cents: int
    months_awarded: int
    total_disbursed_cents: int
    approved_by_cw_id: str
    decision_reason: str
    created_at: str
    updated_at: str
    version: int


class IncomeSource(TypedDict, total=False):
    id: str
    application_id: str
    source_type: str
    monthly_amount_cents: int
    countable: bool
    created_at: str
    updated_at: str
    version: int


class RentLedger(TypedDict, total=False):
    id: str
    application_id: str
    status: str
    verified_by_id: str
    created_at: str
    updated_at: str
    version: int


class LedgerLine(TypedDict, total=False):
    id: str
    ledger_id: str
    month: str
    line_type: str
    charge_cents: int
    payment_cents: int
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict, total=False):
    id: str
    application_id: str
    amount_cents: int
    months_covered: int
    coverage_kind: str
    status: str
    issued_by_cw_id: str
    payment_reference: str
    created_at: str
    updated_at: str
    version: int


class Recertification(TypedDict, total=False):
    id: str
    application_id: str
    requested_additional_months: int
    new_prospective_start_date: Optional[str]
    new_prospective_end_date: Optional[str]
    status: str
    decision_reason: str
    created_at: str
    updated_at: str
    version: int


class RecaptureCase(TypedDict, total=False):
    id: str
    application_id: str
    disbursement_id: str
    reason: str
    status: str
    recovered_amount_cents: int
    created_at: str
    updated_at: str
    version: int
