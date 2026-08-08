"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""
from enum import Enum
from typing import TypedDict, Optional


# --- Roles (PRD §2.1) -------------------------------------------------------
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    INTAKE_COUNSELOR = "IntakeCounselor"
    ADJUDICATOR = "Adjudicator"
    FINANCE_OFFICER = "FinanceOfficer"
    RECOVERY_OFFICER = "RecoveryOfficer"
    APPEALS_OFFICER = "AppealsOfficer"


# --- Status enums -----------------------------------------------------------
class ProgramStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CaseStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    CLOSED = "CLOSED"


class EligibilityStatus(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class CaseCrimeType(str, Enum):
    ASSAULT = "ASSAULT"
    HOMICIDE = "HOMICIDE"
    DOMESTIC_VIOLENCE = "DOMESTIC_VIOLENCE"
    DUI = "DUI"
    ROBBERY = "ROBBERY"
    SEXUAL_ASSAULT = "SEXUAL_ASSAULT"
    OTHER = "OTHER"


class CooperationStatus(str, Enum):
    PENDING = "PENDING"
    COOPERATIVE = "COOPERATIVE"
    NONCOOPERATIVE = "NONCOOPERATIVE"


class ClaimCategory(str, Enum):
    MEDICAL = "MEDICAL"
    LOST_WAGE = "LOST_WAGE"
    FUNERAL = "FUNERAL"
    MENTAL_HEALTH = "MENTAL_HEALTH"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class CollateralSourceType(str, Enum):
    HEALTH_INSURANCE = "HEALTH_INSURANCE"
    AUTO_INSURANCE = "AUTO_INSURANCE"
    LIFE_INSURANCE = "LIFE_INSURANCE"
    EMPLOYER_BENEFIT = "EMPLOYER_BENEFIT"
    RESTITUTION = "RESTITUTION"
    OTHER_PUBLIC = "OTHER_PUBLIC"


class CollateralSourceStatus(str, Enum):
    DECLARED = "DECLARED"
    CONFIRMED = "CONFIRMED"
    WAIVED = "WAIVED"


class AwardApprovalStatus(str, Enum):
    CALCULATED = "CALCULATED"
    APPROVED = "APPROVED"
    FINALIZED = "FINALIZED"


class AwardPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    FULLY_PAID = "FULLY_PAID"


class PayeeType(str, Enum):
    VICTIM = "VICTIM"
    MEDICAL_PROVIDER = "MEDICAL_PROVIDER"
    FUNERAL_HOME = "FUNERAL_HOME"
    MENTAL_HEALTH_PROVIDER = "MENTAL_HEALTH_PROVIDER"


class DisbursementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    VOID = "VOID"
    CLAWED_BACK = "CLAWED_BACK"


class RecoveryStatus(str, Enum):
    ORDERED = "ORDERED"
    COLLECTING = "COLLECTING"
    SATISFIED = "SATISFIED"
    WRITTEN_OFF = "WRITTEN_OFF"


class ReceiptStatus(str, Enum):
    RECORDED = "RECORDED"
    VOID = "VOID"


class AppealStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class NotificationChannel(str, Enum):
    VINE = "VINE"
    EMAIL = "EMAIL"
    LETTER = "LETTER"


class NotificationEventType(str, Enum):
    ELIGIBILITY_DECISION = "ELIGIBILITY_DECISION"
    CLAIM_DECISION = "CLAIM_DECISION"
    PAYMENT = "PAYMENT"
    APPEAL_DECISION = "APPEAL_DECISION"
    CASE_REOPENED = "CASE_REOPENED"


# --- Entity TypedDicts ------------------------------------------------------
# All entities carry common_fields (id, created_at, updated_at, version) EXCEPT
# Notification, which is an append-only log carrying only id + created_at.

class Program(TypedDict):
    id: str
    name: str
    fiscal_year: int
    total_budget_cents: int
    overall_case_cap_cents: int
    medical_cap_cents: int
    lost_wage_cap_cents: int
    funeral_cap_cents: int
    mental_health_cap_cents: int
    status: str
    budget_committed_cents: int
    budget_disbursed_cents: int
    budget_recovered_cents: int
    budget_available_cents: int
    created_at: str
    updated_at: str
    version: int


class VictimCase(TypedDict):
    id: str
    program_id: str
    victim_name: str
    incident_date: str
    crime_type: str
    reported_to_le: bool
    le_report_date: Optional[str]
    cooperation_status: str
    filing_date: str
    status: str
    eligibility_status: str
    denied_at: Optional[str]
    denied_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    case_id: str
    category: str
    claimed_amount_cents: Optional[int]
    weekly_wage_cents: Optional[int]
    num_weeks: Optional[int]
    disability_start_date: Optional[str]
    disability_end_date: Optional[str]
    verified_amount_cents: Optional[int]
    assessed_base_cents: int
    collateral_offset_cents: int
    net_claim_cents: int
    status: str
    denied_at: Optional[str]
    denied_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CollateralSource(TypedDict):
    id: str
    claim_id: str
    source_type: str
    amount_cents: int
    coverage_start_date: Optional[str]
    coverage_end_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Award(TypedDict):
    id: str
    case_id: str
    gross_award_cents: int
    collateral_offset_cents: int
    net_award_cents: int
    amount_paid_cents: int
    approval_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict):
    id: str
    award_id: str
    payee_type: str
    amount_cents: int
    pay_run_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RestitutionRecovery(TypedDict):
    id: str
    case_id: str
    offender_name: str
    ordered_amount_cents: int
    recovered_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RecoveryReceipt(TypedDict):
    id: str
    recovery_id: str
    amount_cents: int
    received_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    case_id: str
    claim_id: Optional[str]
    appeal_reason: str
    filed_at: str
    status: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only log: id + created_at only (no updated_at / version).
class Notification(TypedDict):
    id: str
    case_id: str
    channel: str
    event_type: str
    message: str
    created_at: str
