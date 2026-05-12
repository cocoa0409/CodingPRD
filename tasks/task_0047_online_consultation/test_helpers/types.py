"""Domain types for the Online Consultation API.

Status enums and entity TypedDicts derived from PRD §2 and §3.

Per PRD §2.4 'Common Resource Properties': every primary resource carries
the system-managed fields `id`, `created_at`, `updated_at`, and `version`,
EXCEPT for DepartmentMapping and AuditLog. Those two carry only `id` and
`created_at`; their TypedDicts therefore omit `updated_at` and `version`.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, List, Optional, TypedDict


# ============================================================================
# Roles (PRD §2.1)
# ============================================================================
class UserRole(str, Enum):
    PATIENT = "Patient"
    DOCTOR = "Doctor"
    PHARMACIST = "Pharmacist"
    PLATFORM_ADMIN = "PlatformAdmin"


# ============================================================================
# Status enums (PRD §3)
# ============================================================================
class PatientInsuranceStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    SUSPENDED = "SUSPENDED"


class DoctorStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    BUSY = "BUSY"
    OFF_DUTY = "OFF_DUTY"
    SUSPENDED = "SUSPENDED"


class PharmacistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TriageStatus(str, Enum):
    COLLECTING = "COLLECTING"
    ASSESSED = "ASSESSED"
    EMERGENCY_ROUTED = "EMERGENCY_ROUTED"
    MATCHED = "MATCHED"
    CLOSED = "CLOSED"


class SeverityBand(str, Enum):
    LOW = "LOW"
    MID = "MID"
    HIGH = "HIGH"
    EMERGENCY = "EMERGENCY"


class ConsultationMode(str, Enum):
    REAL_TIME = "REAL_TIME"
    APPOINTMENT = "APPOINTMENT"


class MediaType(str, Enum):
    TEXT_IMAGE = "TEXT_IMAGE"
    VIDEO = "VIDEO"


class SessionStatus(str, Enum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    ACCEPTED = "ACCEPTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    TRANSFERRED = "TRANSFERRED"
    CANCELLED = "CANCELLED"


class QualityStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    OK = "OK"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


class PrescriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DISPATCHED = "DISPATCHED"
    DISPENSED = "DISPENSED"
    FAILED = "FAILED"


class EligibilityFlag(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class DispatchTargetKind(str, Enum):
    PHARMACY = "PHARMACY"
    ECOMMERCE = "ECOMMERCE"


class DispensingStatus(str, Enum):
    NONE = "NONE"
    RECEIVED = "RECEIVED"
    PREPARING = "PREPARING"
    READY = "READY"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class InsuranceClaimStatus(str, Enum):
    ELIGIBILITY_PENDING = "ELIGIBILITY_PENDING"
    VERIFIED = "VERIFIED"
    INELIGIBLE = "INELIGIBLE"
    SETTLING = "SETTLING"
    SETTLED = "SETTLED"
    REJECTED_BY_BUREAU = "REJECTED_BY_BUREAU"


class FollowUpStatus(str, Enum):
    PLANNED = "PLANNED"
    REMINDED = "REMINDED"
    SUBMITTED = "SUBMITTED"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class ReminderChannel(str, Enum):
    SMS = "SMS"
    EMAIL = "EMAIL"
    APP_PUSH = "APP_PUSH"


class QualityReportTier(str, Enum):
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


# ============================================================================
# Entity TypedDicts
# ============================================================================
class Patient(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    region_code: str
    insurance_policy_no: Optional[str]
    insurance_status: str
    preferred_hospital_id: Optional[str]
    preferred_doctor_id: Optional[str]
    chronic_condition_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class Doctor(TypedDict, total=False):
    id: str
    full_name: str
    hospital_id: str
    department_code: str
    specialty_codes: List[str]
    licensed_region_codes: List[str]
    status: str
    max_concurrent_sessions: int
    rating_score: float
    base_fee: float
    created_at: str
    updated_at: str
    version: int


class Pharmacist(TypedDict, total=False):
    id: str
    full_name: str
    license_number: str
    status: str
    created_at: str
    updated_at: str
    version: int


# DepartmentMapping is configuration; per PRD §2.4 it has only id + created_at.
class DepartmentMapping(TypedDict, total=False):
    id: str
    department_code: str
    disease_codes: List[str]
    triage_priority: int
    created_at: str


class TriageSession(TypedDict, total=False):
    id: str
    patient_id: str
    questionnaire_responses: List[Any]
    chief_complaint_score: int
    vital_anomaly_score: int
    risk_factor_score: int
    severity_score: int
    severity_band: str
    recommended_department_code: Optional[str]
    status: str
    emergency_routing_ticket: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Consultation(TypedDict, total=False):
    id: str
    triage_session_id: str
    patient_id: str
    doctor_id: str
    mode: str
    scheduled_start_at: Optional[str]
    queue_position: Optional[int]
    media_type: str
    session_status: str
    quality_status: str
    started_at: Optional[str]
    ended_at: Optional[str]
    duration_minutes: float
    image_attachment_ids: List[str]
    transcript_archive_id: Optional[str]
    base_fee: float
    total_fee: float
    transfer_to_doctor_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrescriptionItem(TypedDict, total=False):
    drug_code: str
    quantity: int
    unit_price_cents: int
    dosage_text: str


class Prescription(TypedDict, total=False):
    id: str
    consultation_id: str
    patient_id: str
    drafting_doctor_id: str
    reviewing_pharmacist_id: Optional[str]
    disease_codes: List[str]
    items: List[PrescriptionItem]
    gross_amount_cents: int
    eligibility_flag: str
    status: str
    rejection_reason: Optional[str]
    dispatch_target_kind: str
    dispatch_target_id: Optional[str]
    dispensing_status: str
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class InsuranceClaim(TypedDict, total=False):
    id: str
    consultation_id: str
    prescription_id: Optional[str]
    patient_id: str
    claim_amount_cents: int
    deductible_cents: int
    reimbursed_cents: int
    self_pay_cents: int
    self_pay_collected_cents: int
    status: str
    bureau_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FollowUpTask(TypedDict, total=False):
    id: str
    consultation_id: str
    patient_id: str
    plan_template_code: str
    scheduled_reminder_at: str
    reminder_channels: List[str]
    form_payload: Optional[dict]
    abnormal_flag: bool
    status: str
    escalation_consultation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# AuditLog is append-only per PRD §3.9; carries only id + created_at.
class AuditLog(TypedDict, total=False):
    id: str
    actor_role: str
    actor_user_id: str
    action_code: str
    target_entity: str
    target_id: str
    occurred_at: str
    payload_digest: str
    created_at: str
