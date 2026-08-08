"""Domain types for the Body-Art & Tattoo Establishment Permit API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import Optional, TypedDict


# ─── Role enum (PRD §2.1) ──────────────────────────────────────────────


class UserRole(str, Enum):
    HEALTH_OFFICER = "HealthOfficer"
    INSPECTOR = "Inspector"
    PLAN_REVIEWER = "PlanReviewer"
    RECORDS_CLERK = "RecordsClerk"
    ESTABLISHMENT_OPERATOR = "EstablishmentOperator"
    ARTIST = "Artist"
    PUBLIC_USER = "PublicUser"


# ─── Status enums ──────────────────────────────────────────────────────


class EstablishmentPermitStatus(str, Enum):
    PENDING_PLAN_REVIEW = "PENDING_PLAN_REVIEW"
    PENDING_INSPECTION = "PENDING_INSPECTION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class OperatingPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class EstablishmentType(str, Enum):
    TATTOO = "TATTOO"
    PIERCING = "PIERCING"
    PERMANENT_COSMETICS = "PERMANENT_COSMETICS"
    COMBINED = "COMBINED"


class SterilizationComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    DEFICIENT = "DEFICIENT"
    NONCOMPLIANT = "NONCOMPLIANT"


class ArtistPermitStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"
    REVOKED = "REVOKED"


class PlanReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CORRECTIONS_REQUIRED = "CORRECTIONS_REQUIRED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class InspectionType(str, Enum):
    PREOPENING = "PREOPENING"
    ROUTINE = "ROUTINE"
    COMPLAINT = "COMPLAINT"
    REINSPECTION = "REINSPECTION"


class ViolationStatus(str, Enum):
    ISSUED = "ISSUED"
    CORRECTION_SUBMITTED = "CORRECTION_SUBMITTED"
    VERIFIED = "VERIFIED"
    ESCALATED = "ESCALATED"


class ViolationSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    NONCRITICAL = "NONCRITICAL"


class SporeTestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    PENDING = "PENDING"


class ConsentVerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class GuardianIdDocumentType(str, Enum):
    DRIVERS_LICENSE = "DRIVERS_LICENSE"
    PASSPORT = "PASSPORT"
    STATE_ID = "STATE_ID"
    MILITARY_ID = "MILITARY_ID"


class ProcedureType(str, Enum):
    TATTOO = "TATTOO"
    PIERCING = "PIERCING"
    PERMANENT_COSMETICS = "PERMANENT_COSMETICS"


class ProcedureLogAuditStatus(str, Enum):
    RECORDED = "RECORDED"
    FLAGGED = "FLAGGED"
    CLEARED = "CLEARED"


class AuditFindingCode(str, Enum):
    CONSENT_EXPIRED = "CONSENT_EXPIRED"
    CONSENT_TYPE_MISMATCH = "CONSENT_TYPE_MISMATCH"
    AFTERCARE_MISSING = "AFTERCARE_MISSING"
    ARTIST_NOT_PERMITTED = "ARTIST_NOT_PERMITTED"


class ComplaintStatus(str, Enum):
    RECEIVED = "RECEIVED"
    TRIAGED = "TRIAGED"
    INVESTIGATING = "INVESTIGATING"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"


class ComplaintCategory(str, Enum):
    SANITATION = "SANITATION"
    UNLICENSED_ARTIST = "UNLICENSED_ARTIST"
    MINOR_PROCEDURE = "MINOR_PROCEDURE"
    INJURY = "INJURY"
    OTHER = "OTHER"


class InfectionType(str, Enum):
    BACTERIAL = "BACTERIAL"
    VIRAL_HEPATITIS = "VIRAL_HEPATITIS"
    MRSA = "MRSA"
    MYCOBACTERIAL = "MYCOBACTERIAL"
    OTHER = "OTHER"


class InvestigationStatus(str, Enum):
    RECEIVED = "RECEIVED"
    SCREENING = "SCREENING"
    CONFIRMED = "CONFIRMED"
    RULED_OUT = "RULED_OUT"


class NotificationStatus(str, Enum):
    PENDING = "PENDING"
    CDC_NOTIFIED = "CDC_NOTIFIED"
    NOT_REQUIRED = "NOT_REQUIRED"
    CLOSED = "CLOSED"


class EnforcementSubjectType(str, Enum):
    ESTABLISHMENT = "ESTABLISHMENT"
    ARTIST = "ARTIST"


class EnforcementActionType(str, Enum):
    SUSPENSION = "SUSPENSION"
    REVOCATION = "REVOCATION"


class EnforcementReasonCode(str, Enum):
    IMMINENT_HEALTH_HAZARD = "IMMINENT_HEALTH_HAZARD"
    RISK_THRESHOLD = "RISK_THRESHOLD"
    CONFIRMED_INFECTION = "CONFIRMED_INFECTION"
    UNLICENSED_PRACTICE = "UNLICENSED_PRACTICE"
    FEE_DELINQUENCY = "FEE_DELINQUENCY"


class EnforcementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class RenewalStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DEFICIENT = "DEFICIENT"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class DeficiencyCode(str, Enum):
    MISSING_BBP_ATTESTATION = "MISSING_BBP_ATTESTATION"
    MISSING_STERILIZATION_ATTESTATION = "MISSING_STERILIZATION_ATTESTATION"
    OPEN_CRITICAL_VIOLATION = "OPEN_CRITICAL_VIOLATION"
    ARTIST_ROSTER_MISMATCH = "ARTIST_ROSTER_MISMATCH"


# ─── Entity TypedDicts ─────────────────────────────────────────────────
# Every entity below carries id + created_at + updated_at + version, except
# SterilizationRecord, which the PRD declares immutable with only id and
# created_at.


class Establishment(TypedDict):
    id: str
    name: str
    street_address: str
    county_code: str
    establishment_type: str
    permit_status: str
    permit_issued_on: Optional[str]
    permit_expires_on: Optional[str]
    operating_posture: str
    risk_score: int
    open_violation_count: int
    open_critical_violation_count: int
    sterilization_compliance_status: str
    active_artist_count: int
    fees_paid_cents: int
    fees_refunded_cents: int
    plan_review_cycles_used: int
    created_at: str
    updated_at: str
    version: int


class Artist(TypedDict):
    id: str
    establishment_id: str
    legal_name: str
    permit_status: str
    bbp_training_completed_on: Optional[str]
    bbp_training_expires_on: Optional[str]
    bbp_recert_required: bool
    permit_expires_on: Optional[str]
    confirmed_infection_count: int
    suspension_count: int
    created_at: str
    updated_at: str
    version: int


class PlanReview(TypedDict):
    id: str
    establishment_id: str
    status: str
    floor_plan_reference: str
    sterilization_area_sqft: float
    procedure_station_count: int
    has_handwash_sink: bool
    cycle_count: int
    decision_notes: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    establishment_id: str
    source_complaint_id: Optional[str]
    inspection_type: str
    status: str
    scheduled_start_at: str
    scheduled_end_at: str
    inspector_user_id: Optional[str]
    score: Optional[int]
    open_violation_count_at_start: int
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict):
    id: str
    inspection_id: str
    violation_code: str
    severity: str
    narrative: str
    status: str
    issued_at: str
    abatement_due_at: str
    repeat_multiplier_applied: float
    deduction_points: int
    correction_note: Optional[str]
    correction_submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SterilizationRecord(TypedDict):
    """Immutable once filed: carries only id and created_at (PRD §2.4)."""

    id: str
    establishment_id: str
    device_serial: str
    cycle_completed_at: str
    spore_test_result: str
    supersedes_record_id: Optional[str]
    recorded_by_user_id: str
    created_at: str


class MinorConsent(TypedDict):
    id: str
    establishment_id: str
    minor_full_name: str
    minor_age_at_signing: int
    guardian_full_name: str
    guardian_id_document_type: str
    guardian_id_document_number: str
    authorized_procedure_type: str
    consent_signed_at: str
    expires_at: str
    verification_status: str
    verified_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProcedureLog(TypedDict):
    id: str
    establishment_id: str
    artist_id: str
    minor_consent_id: Optional[str]
    client_age: int
    procedure_type: str
    started_at: str
    ended_at: str
    aftercare_provided: bool
    audit_status: str
    audit_finding_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    establishment_id: str
    complainant_contact: str
    category: str
    narrative: str
    status: str
    received_at: str
    triage_due_at: str
    triage_overdue: bool
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class InfectionReport(TypedDict):
    id: str
    establishment_id: str
    artist_id: Optional[str]
    reporter_contact: str
    infection_type: str
    procedure_date: str
    symptom_onset_at: str
    investigation_status: str
    notification_status: str
    notification_due_at: str
    notification_late: bool
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class EnforcementAction(TypedDict):
    id: str
    establishment_id: Optional[str]
    artist_id: Optional[str]
    subject_type: str
    action_type: str
    reason_code: str
    status: str
    issued_by_user_id: str
    issued_at: str
    lifted_by_user_id: Optional[str]
    lifted_at: Optional[str]
    auto_generated: bool
    suspension_days: Optional[int]
    reinstatement_base_cents: Optional[int]
    reinstatement_admin_fee_cents: Optional[int]
    reinstatement_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RenewalApplication(TypedDict):
    id: str
    establishment_id: str
    status: str
    requested_term_start_on: str
    expedite_requested: bool
    attested_bbp_current: bool
    attested_sterilization_logs_complete: bool
    submitted_at: Optional[str]
    artist_count_at_submit: Optional[int]
    fee_estimate_cents: Optional[int]
    fee_final_cents: Optional[int]
    fee_balance_due_cents: int
    fee_paid_cents: int
    fee_refunded_cents: int
    payment_status: str
    late_fee_applied: bool
    deficiency_code: Optional[str]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    cycle_count: int
    created_at: str
    updated_at: str
    version: int
