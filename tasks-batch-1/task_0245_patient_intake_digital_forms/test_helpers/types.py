"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Patient Intake & Digital Forms PRD (§2.4, §3).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    CLINIC_ADMIN = "ClinicAdmin"
    FRONT_DESK_STAFF = "FrontDeskStaff"
    PATIENT = "Patient"
    BILLING_CLERK = "BillingClerk"


# --- Status enums ---
class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    INTAKE_OPENED = "INTAKE_OPENED"
    CANCELLED = "CANCELLED"


class WorkflowStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_PROGRESS = "IN_PROGRESS"
    READY_FOR_VISIT = "READY_FOR_VISIT"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class FinancialStatus(str, Enum):
    PENDING_ELIGIBILITY = "PENDING_ELIGIBILITY"
    INSURED = "INSURED"
    SELF_PAY = "SELF_PAY"
    COPAY_DUE = "COPAY_DUE"
    COPAY_SETTLED = "COPAY_SETTLED"
    WAIVED = "WAIVED"


class EligibilityStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFYING = "VERIFYING"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class EligibilityOutcome(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class ConsentStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED = "SIGNED"
    REVOKED = "REVOKED"


class QuestionnaireStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    FLAGGED = "FLAGGED"


class CopayStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    VOIDED = "VOIDED"
    REFUNDED = "REFUNDED"


class QueueStatus(str, Enum):
    WAITING = "WAITING"
    CALLED = "CALLED"
    IN_ROOM = "IN_ROOM"
    DONE = "DONE"
    NO_SHOW = "NO_SHOW"


class ReminderKind(str, Enum):
    CONSENT = "CONSENT"
    QUESTIONNAIRE = "QUESTIONNAIRE"
    COPAY = "COPAY"
    GENERIC = "GENERIC"


class ReminderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SENT = "SENT"
    CANCELLED = "CANCELLED"
    SUPPRESSED = "SUPPRESSED"


class CopayRounding(str, Enum):
    PER_LINE_THEN_SUM = "PER_LINE_THEN_SUM"
    SUM_THEN_ROUND = "SUM_THEN_ROUND"


class SyncJobStatus(str, Enum):
    QUEUED = "QUEUED"
    COMMITTED = "COMMITTED"
    SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"


# --- Entity TypedDicts (common_fields: true unless noted) ---
class Clinic(TypedDict):
    id: str
    name: str
    timezone: str
    form_expiration_hours: int
    reminder_quiet_start_min: int
    reminder_quiet_end_min: int
    reminder_min_gap_minutes: int
    copay_rounding: str
    facility_fee_cents: int
    current_utc: str
    collected_copay_cents: int
    active_queue_count: int
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    clinic_id: str
    full_name: str
    cleanup_buffer_minutes: int
    required_consent_codes: List[str]
    questionnaire_required_sections: List[str]
    created_at: str
    updated_at: str
    version: int


class ExamRoom(TypedDict):
    id: str
    clinic_id: str
    label: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    clinic_id: str
    legal_name: str
    date_of_birth: str
    phone: str
    demographics_revision: int
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    clinic_id: str
    provider_id: str
    patient_id: str
    start_utc: str
    end_utc: str
    plan_default_copay_cents: int
    provisional_copay_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IntakeSession(TypedDict):
    id: str
    appointment_id: str
    clinic_id: str
    provider_id: str
    patient_id: str
    expires_at: str
    workflow_status: str
    financial_status: str
    forms_complete: bool
    final_patient_responsibility_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class InsuranceCard(TypedDict):
    id: str
    intake_session_id: str
    payer_name: str
    member_id: str
    plan_copay_cents: int
    plan_coinsurance_pct: int
    facility_coinsurance_pct: int
    remaining_deductible_cents: int
    visit_allowed_amount_cents: int
    eligibility_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only event, only id + created_at
class EligibilityCheck(TypedDict):
    id: str
    insurance_card_id: str
    intake_session_id: str
    outcome: str
    provisional_responsibility_cents: int
    created_at: str


class ConsentDocument(TypedDict):
    id: str
    intake_session_id: str
    consent_code: str
    signer_name: Optional[str]
    signed_at: Optional[str]
    revision: int
    status: str
    created_at: str
    updated_at: str
    version: int


class QuestionnaireResponse(TypedDict):
    id: str
    intake_session_id: str
    answered_sections: list
    provisional_risk_score: int
    final_risk_score: Optional[int]
    high_risk_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CopayPayment(TypedDict):
    id: str
    intake_session_id: str
    amount_cents: int
    refunded_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class KioskQueueEntry(TypedDict):
    id: str
    intake_session_id: str
    clinic_id: str
    exam_room_id: Optional[str]
    enqueued_seq: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RoomBooking(TypedDict):
    id: str
    exam_room_id: str
    queue_entry_id: str
    start_utc: str
    end_utc: str
    created_at: str
    updated_at: str
    version: int


class Reminder(TypedDict):
    id: str
    intake_session_id: str
    target_kind: str
    scheduled_utc: str
    scheduled_local_min: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DemographicsSyncJob(TypedDict):
    id: str
    intake_session_id: str
    idempotency_key: str
    synced_legal_name: str
    synced_phone: str
    status: str
    created_at: str
    updated_at: str
    version: int
