"""Domain types: entity TypedDicts, status enums, role enum for the Eviction Diversion Portal."""
from enum import Enum
from typing import TypedDict, List, Optional


# --------------------------------------------------------------------------- #
# Roles                                                                        #
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    CLERK = "Clerk"
    LANDLORD = "Landlord"
    TENANT = "Tenant"
    MEDIATOR = "Mediator"
    JUDGE = "Judge"
    PROGRAM_ADMIN = "ProgramAdmin"
    SHERIFF = "Sheriff"


# --------------------------------------------------------------------------- #
# Status enums                                                                 #
# --------------------------------------------------------------------------- #
class CaseStatus(str, Enum):
    FILED = "FILED"
    SERVED = "SERVED"
    ANSWERED = "ANSWERED"
    DEFAULTED = "DEFAULTED"
    IN_DIVERSION = "IN_DIVERSION"
    IN_LITIGATION = "IN_LITIGATION"
    JUDGMENT_ENTERED = "JUDGMENT_ENTERED"
    ENFORCEMENT = "ENFORCEMENT"
    CLOSED_ENFORCED = "CLOSED_ENFORCED"
    DIVERSION_SATISFIED = "DIVERSION_SATISFIED"
    DISMISSED = "DISMISSED"


class CaseOutcome(str, Enum):
    PENDING = "PENDING"
    DIVERTED = "DIVERTED"
    JUDGMENT_FOR_LANDLORD = "JUDGMENT_FOR_LANDLORD"
    DISMISSED = "DISMISSED"
    ENFORCED = "ENFORCED"


class FilingType(str, Enum):
    NONPAYMENT = "NONPAYMENT"
    HOLDOVER = "HOLDOVER"
    NUISANCE = "NUISANCE"


class ReferralType(str, Enum):
    LEGAL_AID = "LEGAL_AID"
    RENTAL_ASSISTANCE = "RENTAL_ASSISTANCE"


class ReferralStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    DISBURSED = "DISBURSED"


class MediationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    AGREEMENT = "AGREEMENT"
    IMPASSE = "IMPASSE"


class PaymentPlanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"
    DEFAULTED = "DEFAULTED"


class InstallmentStatus(str, Enum):
    DUE = "DUE"
    PAID = "PAID"
    MISSED = "MISSED"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CONTINUED = "CONTINUED"
    CANCELLED = "CANCELLED"


class HearingType(str, Enum):
    INITIAL = "INITIAL"
    TRIAL = "TRIAL"
    ENFORCEMENT = "ENFORCEMENT"


class JudgmentStatus(str, Enum):
    ENTERED = "ENTERED"
    STAYED = "STAYED"
    VACATED = "VACATED"
    SATISFIED = "SATISFIED"


class JudgmentType(str, Enum):
    POSSESSION = "POSSESSION"
    DISMISSAL = "DISMISSAL"
    DIVERSION = "DIVERSION"


class LockoutStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class SealingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class ProposingParty(str, Enum):
    LANDLORD = "LANDLORD"
    TENANT = "TENANT"


# --------------------------------------------------------------------------- #
# Entity TypedDicts                                                            #
# common_fields: true  -> id, created_at, updated_at, version                 #
# common_fields: false -> id, created_at only                                 #
# --------------------------------------------------------------------------- #
class Court(TypedDict):
    id: str
    name: str
    jurisdiction_code: str
    hearing_daily_capacity: int
    hearings_scheduled_count: int
    created_at: str
    updated_at: str
    version: int


class Landlord(TypedDict):  # common_fields: false
    id: str
    name: str
    email: str
    created_at: str


class Tenant(TypedDict):  # common_fields: false
    id: str
    name: str
    email: str
    household_income_cents: int
    household_size: int
    created_at: str


class Officer(TypedDict):  # common_fields: false
    id: str
    name: str
    badge_number: str
    agency: str
    created_at: str


class Case(TypedDict):
    id: str
    court_id: str
    landlord_id: str
    tenant_id: str
    filing_type: str
    claimed_arrears_cents: int
    net_arrears_cents: int
    answer_due_at: str
    served_at: Optional[str]
    status: str
    outcome: str
    closed_at: Optional[str]
    sealed: bool
    created_at: str
    updated_at: str
    version: int


class Answer(TypedDict):  # common_fields: false
    id: str
    case_id: str
    defenses: List[str]
    rent_withheld_cents: int
    is_late: bool
    created_at: str


class Referral(TypedDict):
    id: str
    case_id: str
    referral_type: str
    provider_name: str
    requested_amount_cents: int
    disbursed_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MediationSession(TypedDict):
    id: str
    case_id: str
    mediator_user_id: str
    scheduled_at: str
    outcome_notes: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentPlan(TypedDict):
    id: str
    case_id: str
    proposed_by: str
    total_cents: int
    installment_count: int
    first_due_date: str
    current_proposer: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Installment(TypedDict):
    id: str
    payment_plan_id: str
    sequence: int
    amount_cents: int
    due_date: str
    paid_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict):
    id: str
    case_id: str
    court_id: str
    hearing_type: str
    scheduled_start: str
    scheduled_end: str
    continuance_count: int
    continued_from_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Judgment(TypedDict):
    id: str
    case_id: str
    judgment_type: str
    money_amount_cents: int
    stay_until: Optional[str]
    entered_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LockoutOrder(TypedDict):
    id: str
    case_id: str
    judgment_id: str
    officer_id: Optional[str]
    scheduled_at: Optional[str]
    executed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SealingRequest(TypedDict):
    id: str
    case_id: str
    basis: str
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
