"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entities, lifecycle states, and roles. All persisted
resources carry id/created_at/updated_at/version per the PRD's audit-field
convention (§2.4: "There are no resources in this system that omit updated_at
or version").
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ────────────────────────────────────────────────────────

class CaseStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    MEETING_HELD = "MEETING_HELD"
    CONFIRMED = "CONFIRMED"
    DISCHARGED = "DISCHARGED"
    DISMISSED = "DISMISSED"


class StayPosture(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    LIFTED_PARTIAL = "LIFTED_PARTIAL"
    TERMINATED = "TERMINATED"


class MeansTestResult(str, Enum):
    NOT_RUN = "NOT_RUN"
    PRESUMPTION_OK = "PRESUMPTION_OK"
    PRESUMPTION_ABUSE = "PRESUMPTION_ABUSE"


class FiledChapter(str, Enum):
    CHAPTER_7 = "CHAPTER_7"
    CHAPTER_13 = "CHAPTER_13"


class ScheduleLetter(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"
    G = "G"
    H = "H"
    I = "I"
    J = "J"


class DebtClass(str, Enum):
    SECURED = "SECURED"
    PRIORITY = "PRIORITY"
    UNSECURED = "UNSECURED"


class MeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    ALLOWED = "ALLOWED"
    DISALLOWED = "DISALLOWED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    CONFIRMED = "CONFIRMED"
    DENIED = "DENIED"
    COMPLETED = "COMPLETED"


class MotionStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class UserRole(str, Enum):
    DEBTOR = "Debtor"
    TRUSTEE = "Trustee"
    CREDITOR = "Creditor"
    BANKRUPTCY_ADMIN = "BankruptcyAdmin"


# ─── Entity TypedDicts (all carry full audit fields) ─────────────────────

class Case(TypedDict):
    id: str
    debtor_id: str
    filed_chapter: str
    status: str
    stay_posture: str
    petition_date: Optional[str]
    state_code: str
    household_size: int
    means_test_result: str
    total_exempt_value_cents: int
    nonexempt_estate_cents: int
    created_at: str
    updated_at: str
    version: int


class Debtor(TypedDict):
    id: str
    full_name: str
    email: str
    prior_discharge_within_8y: bool
    created_at: str
    updated_at: str
    version: int


class MeansTest(TypedDict):
    id: str
    case_id: str
    cmi_monthly_cents: int
    monthly_expenses_cents: int
    median_annual_income_cents: int
    annualized_cmi_cents: int
    disposable_monthly_cents: int
    result: str
    created_at: str
    updated_at: str
    version: int


class Schedule(TypedDict):
    id: str
    case_id: str
    schedule_letter: str
    description: str
    asset_value_cents: int
    claimed_exempt_value_cents: int
    created_at: str
    updated_at: str
    version: int


class Debt(TypedDict):
    id: str
    case_id: str
    creditor_id: str
    debt_class: str
    scheduled_amount_cents: int
    allowed_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Creditor(TypedDict):
    id: str
    name: str
    created_at: str
    updated_at: str
    version: int


class Trustee(TypedDict):
    id: str
    name: str
    created_at: str
    updated_at: str
    version: int


class Meeting341(TypedDict):
    id: str
    case_id: str
    trustee_id: str
    room_code: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimRecord(TypedDict):
    id: str
    case_id: str
    debt_id: str
    filed_by_creditor_id: str
    claimed_amount_cents: int
    status: str
    allowed_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Plan(TypedDict):
    id: str
    case_id: str
    monthly_payment_cents: int
    plan_duration_months: int
    status: str
    is_active: bool
    total_committed_cents: int
    paid_to_date_cents: int
    created_at: str
    updated_at: str
    version: int


class PlanPayment(TypedDict):
    id: str
    plan_id: str
    amount_cents: int
    applied_at: str
    created_at: str
    updated_at: str
    version: int


class StayReliefMotion(TypedDict):
    id: str
    case_id: str
    movant_creditor_id: str
    target_debt_id: str
    status: str
    created_at: str
    updated_at: str
    version: int
