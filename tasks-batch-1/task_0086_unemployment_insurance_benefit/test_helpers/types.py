"""Domain types: entity TypedDicts, status enums, role enum for the
Unemployment Insurance Benefit API."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ──────────────────────────────────────────────────────────

class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    MONETARY_PENDING = "MONETARY_PENDING"
    MONETARILY_ELIGIBLE = "MONETARILY_ELIGIBLE"
    MONETARILY_INELIGIBLE = "MONETARILY_INELIGIBLE"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"


class BasePeriodMethod(str, Enum):
    STANDARD = "STANDARD"
    ALTERNATE = "ALTERNATE"
    NONE = "NONE"


class DeterminationType(str, Enum):
    MONETARY = "MONETARY"
    NONMONETARY = "NONMONETARY"


class DeterminationOutcome(str, Enum):
    PENDING = "PENDING"
    ALLOWED = "ALLOWED"
    DENIED = "DENIED"
    REVERSED = "REVERSED"


class AdjudicationStatus(str, Enum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    HELD = "HELD"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    OFFSET = "OFFSET"
    DENIED = "DENIED"


class ContactType(str, Enum):
    EMPLOYER_APPLICATION = "EMPLOYER_APPLICATION"
    INTERVIEW = "INTERVIEW"
    JOB_FAIR = "JOB_FAIR"
    REEMPLOYMENT_WORKSHOP = "REEMPLOYMENT_WORKSHOP"


class EmployerChargeStatus(str, Enum):
    POSTED = "POSTED"
    PROTESTED = "PROTESTED"
    RELIEVED = "RELIEVED"


class ReliefReason(str, Enum):
    QUIT_WITHOUT_CAUSE = "QUIT_WITHOUT_CAUSE"
    MISCONDUCT_DISCHARGE = "MISCONDUCT_DISCHARGE"
    CONTINUING_WORK = "CONTINUING_WORK"


class OverpaymentCause(str, Enum):
    FRAUD = "FRAUD"
    NONFRAUD = "NONFRAUD"


class OverpaymentStatus(str, Enum):
    ESTABLISHED = "ESTABLISHED"
    RECOVERING = "RECOVERING"
    SATISFIED = "SATISFIED"
    WAIVED = "WAIVED"


class RecoveryMethod(str, Enum):
    OFFSET = "OFFSET"
    CASH = "CASH"


class RecoveryStatus(str, Enum):
    APPLIED = "APPLIED"


class AppealFiledBy(str, Enum):
    CLAIMANT = "CLAIMANT"
    EMPLOYER = "EMPLOYER"


class AppealStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REMANDED = "REMANDED"
    DECIDED_AFFIRMED = "DECIDED_AFFIRMED"
    DECIDED_REVERSED = "DECIDED_REVERSED"
    WITHDRAWN = "WITHDRAWN"
    DISMISSED = "DISMISSED"


class AppealRuling(str, Enum):
    AFFIRM = "AFFIRM"
    REVERSE = "REVERSE"


class UserRole(str, Enum):
    Anonymous = "Anonymous"
    ProgramAdmin = "ProgramAdmin"
    Claimant = "Claimant"
    Adjudicator = "Adjudicator"
    BenefitPaymentOfficer = "BenefitPaymentOfficer"
    Employer = "Employer"
    AppealsClerk = "AppealsClerk"
    Referee = "Referee"


# ─── Entity TypedDicts ─────────────────────────────────────────────────────
# Entities carrying the uniform audit fields (id, created_at, updated_at, version).

class Employer(TypedDict):
    id: str
    legal_name: str
    state_account_number: str
    experience_rate: float
    reserve_account_balance_cents: int
    reserve_opening_balance_cents: int
    charge_protest_count: int
    created_at: str
    updated_at: str
    version: int


class Claimant(TypedDict):
    id: str
    full_name: str
    ssn_last4: str
    date_of_birth: str
    is_able_and_available: bool
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    claimant_id: str
    filed_date: str
    base_period_method: str
    status: str
    weekly_benefit_amount_cents: int
    maximum_benefit_amount_cents: int
    remaining_balance_cents: int
    emergency_extension_id: Optional[str]
    extension_weeks_granted: int
    created_at: str
    updated_at: str
    version: int


class Determination(TypedDict):
    id: str
    claim_id: str
    determination_type: str
    outcome: str
    issuing_adjudicator_id: str
    base_period_total_wages_cents: int
    high_quarter_wages_cents: int
    appeal_deadline_date: str
    is_appealable: bool
    created_at: str
    updated_at: str
    version: int


class WeeklyCertification(TypedDict):
    id: str
    claim_id: str
    week_ending_date: str
    reported_earnings_cents: int
    adjudication_status: str
    payment_status: str
    work_search_required: bool
    payable_amount_cents: int
    work_search_waived: bool
    created_at: str
    updated_at: str
    version: int


class EmployerCharge(TypedDict):
    id: str
    employer_id: str
    weekly_certification_id: str
    charge_amount_cents: int
    status: str
    relief_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Overpayment(TypedDict):
    id: str
    claim_id: str
    cause: str
    principal_cents: int
    penalty_cents: int
    total_assessed_cents: int
    recovered_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OverpaymentRecovery(TypedDict):
    id: str
    overpayment_id: str
    weekly_certification_id: Optional[str]
    recovery_method: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    determination_id: str
    filed_by: str
    filed_date: str
    status: str
    assigned_referee_id: Optional[str]
    remand_count: int
    created_at: str
    updated_at: str
    version: int


class EmergencyExtensionProgram(TypedDict):
    id: str
    program_code: str
    extra_weeks: int
    trigger_start_date: str
    trigger_end_date: str
    waives_work_search: bool
    is_active: bool
    created_at: str
    updated_at: str
    version: int


# ─── Append-only ledger lines: id + created_at ONLY (no updated_at, no version) ─

class WageRecord(TypedDict):
    id: str
    claimant_id: str
    employer_id: str
    calendar_quarter: str
    gross_wages_cents: int
    is_disputed: bool
    created_at: str


class WorkSearchContact(TypedDict):
    id: str
    weekly_certification_id: str
    employer_id: Optional[str]
    contact_type: str
    contact_date: str
    created_at: str
