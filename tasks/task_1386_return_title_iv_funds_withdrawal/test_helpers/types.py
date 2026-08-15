"""Domain types: entity TypedDicts, status enums, role enum.

Entities carrying the full audit set expose id, created_at, updated_at and
version (PRD section 2.4). Scheduled breaks and student account entries are
immutable records: they carry only id and created_at, and both updated_at
and version are absent from them.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    REGISTRAR_CLERK = "RegistrarClerk"
    FINANCIAL_AID_OFFICER = "FinancialAidOfficer"
    BURSAR_CLERK = "BursarClerk"
    STUDENT = "Student"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"


class WithdrawalCaseStatus(str, Enum):
    OPEN = "OPEN"
    CALCULATED = "CALCULATED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class AidAwardStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    CANCELLED = "CANCELLED"


class AidDisbursementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISBURSED = "DISBURSED"
    CANCELLED = "CANCELLED"


class ReturnObligationStatus(str, Enum):
    PENDING = "PENDING"
    OVERDUE = "OVERDUE"
    RETURNED = "RETURNED"
    VOIDED = "VOIDED"


class PostWithdrawalOfferStatus(str, Enum):
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class AidProgram(str, Enum):
    PELL_GRANT = "PELL_GRANT"
    SUBSIDIZED_LOAN = "SUBSIDIZED_LOAN"
    UNSUBSIDIZED_LOAN = "UNSUBSIDIZED_LOAN"
    PLUS_LOAN = "PLUS_LOAN"


class WithdrawalType(str, Enum):
    OFFICIAL = "OFFICIAL"
    UNOFFICIAL = "UNOFFICIAL"


class RefundMethod(str, Enum):
    TIERED = "TIERED"
    PRO_RATA = "PRO_RATA"


class ObligationParty(str, Enum):
    SCHOOL = "SCHOOL"
    STUDENT = "STUDENT"


class AccountEntryType(str, Enum):
    CHARGE = "CHARGE"
    REFUND_CREDIT = "REFUND_CREDIT"
    R2T4_CHARGEBACK = "R2T4_CHARGEBACK"
    AID_CREDIT = "AID_CREDIT"
    PAYMENT = "PAYMENT"
    REVERSAL = "REVERSAL"


class AcademicTerm(TypedDict, total=False):
    id: str
    name: str
    start_date: str
    end_date: str
    attendance_taking_required: bool
    refund_method: str
    refund_schedule: List[Dict[str, Any]]
    calendar_days: int
    deductible_break_days: int
    total_days: int
    created_at: str
    updated_at: str
    version: int


class ScheduledBreak(TypedDict, total=False):
    # Immutable record: only id + created_at audit fields (no updated_at, no version).
    id: str
    term_id: str
    start_date: str
    end_date: str
    length_days: int
    deductible_days: int
    created_at: str


class Student(TypedDict, total=False):
    id: str
    external_ref: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    student_id: str
    term_id: str
    institutional_charges_cents: int
    status: str
    balance_cents: int
    balance_notification_sent: bool
    balance_notified_at: Optional[str]
    current_withdrawal_case_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AidAward(TypedDict, total=False):
    id: str
    enrollment_id: str
    program: str
    amount_cents: int
    is_grant: bool
    status: str
    disbursed_amount_cents: int
    scheduled_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class AidDisbursement(TypedDict, total=False):
    id: str
    award_id: str
    pwd_offer_id: Optional[str]
    amount_cents: int
    status: str
    disbursed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WithdrawalCase(TypedDict, total=False):
    id: str
    enrollment_id: str
    withdrawal_type: str
    notification_date: Optional[str]
    last_attendance_date: Optional[str]
    withdrawal_date: str
    determination_date: str
    total_days: int
    completed_days: int
    percentage_completed: float
    earned_pct: float
    aid_disbursable_cents: Optional[int]
    aid_disbursed_cents: Optional[int]
    aid_earned_cents: Optional[int]
    aid_unearned_cents: Optional[int]
    return_amount_cents: Optional[int]
    school_return_cents: Optional[int]
    student_grant_return_cents: Optional[int]
    student_loan_deferred_cents: Optional[int]
    pwd_grant_cents: Optional[int]
    pwd_loan_cents: Optional[int]
    status: str
    calculated_by_user_id: Optional[str]
    calculated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReturnObligation(TypedDict, total=False):
    id: str
    withdrawal_case_id: str
    party: str
    amount_cents: int
    due_date: str
    status: str
    returned_at: Optional[str]
    returned_amount_cents: Optional[int]
    recorded_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PostWithdrawalOffer(TypedDict, total=False):
    id: str
    withdrawal_case_id: str
    award_id: str
    amount_cents: int
    offered_at: str
    response_deadline: str
    late_offer: bool
    status: str
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StudentAccountEntry(TypedDict, total=False):
    # Immutable record: only id + created_at audit fields (no updated_at, no version).
    id: str
    enrollment_id: str
    entry_type: str
    amount_cents: int
    reversal_of_entry_id: Optional[str]
    source_ref: str
    posted_at: str
    created_at: str
