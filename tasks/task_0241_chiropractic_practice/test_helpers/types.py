"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror the PRD's wire contract exactly. Entities that carry the
standard system-managed set (id, created_at, updated_at, version) are modeled
with all four; LedgerEntry and PracticeClock are append-only/singleton and
carry only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PROVIDER = "Provider"
    FRONT_DESK = "FrontDesk"
    BILLING_CLERK = "BillingClerk"
    PRACTICE_ADMIN = "PracticeAdmin"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class ProviderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TreatmentRoomStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RoomType(str, Enum):
    ADJUSTMENT = "ADJUSTMENT"
    IMAGING = "IMAGING"


class FeeScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class VisitType(str, Enum):
    ADJUSTMENT = "ADJUSTMENT"
    EXAM = "EXAM"
    RE_EXAM = "RE_EXAM"
    X_RAY = "X_RAY"
    THERAPY = "THERAPY"


class WellnessPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"


class PayerMode(str, Enum):
    INSURANCE = "INSURANCE"
    CASH = "CASH"
    WELLNESS = "WELLNESS"


class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISMISSED = "DISMISSED"


class InsurancePolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class ExamType(str, Enum):
    INITIAL = "INITIAL"
    RE_EXAM = "RE_EXAM"


class ExamStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class PhaseType(str, Enum):
    ACUTE = "ACUTE"
    CORRECTIVE = "CORRECTIVE"
    MAINTENANCE = "MAINTENANCE"


class TreatmentPlanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    DISCONTINUED = "DISCONTINUED"


class PlanPhaseStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AppointmentSeriesStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    REGENERATED = "REGENERATED"
    CANCELLED = "CANCELLED"


class AttendanceStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"
    LATE_CANCEL = "LATE_CANCEL"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    POSTED = "POSTED"
    ADJUDICATED = "ADJUDICATED"
    WRITTEN_OFF = "WRITTEN_OFF"


class SoapNoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"


class LedgerEntryType(str, Enum):
    CHARGE = "CHARGE"
    INSURANCE_PAYMENT = "INSURANCE_PAYMENT"
    PATIENT_PAYMENT = "PATIENT_PAYMENT"
    NO_SHOW_FEE = "NO_SHOW_FEE"
    WRITE_OFF = "WRITE_OFF"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields: true (id + created_at + updated_at + version)
# ---------------------------------------------------------------------------
class Provider(TypedDict):
    id: str
    full_name: str
    npi: str
    license_state: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TreatmentRoom(TypedDict):
    id: str
    name: str
    room_type: str
    turnover_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeSchedule(TypedDict):
    id: str
    visit_type: str
    cash_rate_cents: int
    billed_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WellnessPlan(TypedDict):
    id: str
    name: str
    monthly_fee_cents: int
    included_adjustments_per_month: int
    overage_discount_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    payer_mode: str
    wellness_plan_id: Optional[str]
    no_show_strike_count: int
    ledger_balance_cents: int
    is_dismissed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict):
    id: str
    patient_id: str
    carrier_name: str
    annual_visit_cap: int
    visits_reserved: int
    visits_committed: int
    deductible_total_cents: int
    deductible_met_cents: int
    coinsurance_pct: float
    allowed_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExamRecord(TypedDict):
    id: str
    patient_id: str
    provider_id: str
    exam_type: str
    imaging_ordered: bool
    severity_score: int
    findings: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TreatmentPlan(TypedDict):
    id: str
    patient_id: str
    exam_record_id: str
    current_phase: str
    total_planned_visits: int
    visits_delivered: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PlanPhase(TypedDict):
    id: str
    treatment_plan_id: str
    phase_type: str
    sequence_index: int
    visits_per_week: int
    planned_visit_count: int
    visits_completed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AppointmentSeries(TypedDict):
    id: str
    treatment_plan_id: str
    plan_phase_id: str
    provider_id: str
    treatment_room_id: str
    start_date: str
    weekday_pattern: List[int]
    start_time_minutes: int
    duration_minutes: int
    generated_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    patient_id: str
    appointment_series_id: Optional[str]
    plan_phase_id: Optional[str]
    provider_id: str
    treatment_room_id: str
    insurance_policy_id: Optional[str]
    visit_type: str
    replaces_appointment_id: Optional[str]
    scheduled_start: str
    scheduled_end: str
    duration_minutes: int
    counts_against_cap: bool
    patient_responsibility_cents: int
    insurance_paid_cents: int
    no_show_fee_cents: int
    attendance_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class SoapNote(TypedDict):
    id: str
    appointment_id: str
    provider_id: str
    subjective: str
    objective: str
    assessment: str
    plan: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields: false (id + created_at only)
# ---------------------------------------------------------------------------
class LedgerEntry(TypedDict):
    id: str
    patient_id: str
    appointment_id: Optional[str]
    entry_type: str
    amount_cents: int
    memo: Optional[str]
    created_at: str


class PracticeClock(TypedDict):
    id: str
    current_utc: str
    created_at: str
