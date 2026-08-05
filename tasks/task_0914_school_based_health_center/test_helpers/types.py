"""Domain types for the School-Based Health Center API: status enums, entity
TypedDicts and the role enum.

Every name here mirrors the PRD's own vocabulary.
"""

from enum import Enum
from typing import Optional, TypedDict


# ─── Roles (PRD §2.1) ────────────────────────────────────────────────────────

class UserRole(str, Enum):
    SBHC_ADMIN = "SbhcAdmin"
    REGISTRAR = "Registrar"
    CLINICIAN = "Clinician"
    CARE_COORDINATOR = "CareCoordinator"
    BILLING_SPECIALIST = "BillingSpecialist"
    GUARDIAN = "Guardian"
    STUDENT = "Student"


# ─── School (PRD §3.1) ───────────────────────────────────────────────────────

class SchoolProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


# ─── Clinician (PRD §3.1) ────────────────────────────────────────────────────

class ClinicianDiscipline(str, Enum):
    MEDICAL = "MEDICAL"
    BEHAVIORAL = "BEHAVIORAL"
    DENTAL = "DENTAL"


# ─── Student (PRD §3.2, §3.7) ────────────────────────────────────────────────

class PayerRoute(str, Enum):
    MEDICAID = "MEDICAID"
    PRIVATE_INSURANCE = "PRIVATE_INSURANCE"
    SELF_PAY = "SELF_PAY"


class DiscountTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"
    TIER_D = "TIER_D"
    TIER_E = "TIER_E"


class ImmunizationComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    PROVISIONAL = "PROVISIONAL"
    NON_COMPLIANT = "NON_COMPLIANT"


class ImmunizationExemptionType(str, Enum):
    NONE = "NONE"
    MEDICAL = "MEDICAL"
    RELIGIOUS = "RELIGIOUS"


# ─── Guardian (PRD §3.2) ─────────────────────────────────────────────────────

class GuardianRelationship(str, Enum):
    MOTHER = "MOTHER"
    FATHER = "FATHER"
    LEGAL_GUARDIAN = "LEGAL_GUARDIAN"
    OTHER = "OTHER"


# ─── Enrollment (PRD §3.3) ───────────────────────────────────────────────────

class EnrollmentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"
    TRANSFERRED = "TRANSFERRED"


# ─── Consent (PRD §3.4) ──────────────────────────────────────────────────────

class ConsentCategory(str, Enum):
    GENERAL_TREATMENT = "GENERAL_TREATMENT"
    BEHAVIORAL_HEALTH = "BEHAVIORAL_HEALTH"
    CONFIDENTIAL_SERVICES = "CONFIDENTIAL_SERVICES"
    DENTAL = "DENTAL"
    TELEHEALTH = "TELEHEALTH"


class ConsentGrantedBy(str, Enum):
    GUARDIAN = "GUARDIAN"
    STUDENT_SELF = "STUDENT_SELF"


class ConsentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


# ─── Visit / encounter (PRD §3.5) ────────────────────────────────────────────

class VisitType(str, Enum):
    ACUTE = "ACUTE"
    BEHAVIORAL = "BEHAVIORAL"
    DENTAL = "DENTAL"
    SPORTS_PHYSICAL = "SPORTS_PHYSICAL"


class DeliveryMode(str, Enum):
    IN_PERSON = "IN_PERSON"
    TELEHEALTH = "TELEHEALTH"


class VisitClinicalStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class VisitBillingStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING_CHARGES = "PENDING_CHARGES"
    CHARGES_POSTED = "CHARGES_POSTED"
    REVERSED = "REVERSED"


class VisitDisposition(str, Enum):
    TREATED_RETURNED_TO_CLASS = "TREATED_RETURNED_TO_CLASS"
    TREATED_SENT_HOME = "TREATED_SENT_HOME"
    REFERRED_OUT = "REFERRED_OUT"
    NO_TREATMENT_NEEDED = "NO_TREATMENT_NEEDED"


class VisitCloseOutcome(str, Enum):
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


# ─── Sports-physical clearance (PRD §3.9) ────────────────────────────────────

class ClearanceOutcome(str, Enum):
    CLEARED = "CLEARED"
    CLEARED_WITH_RESTRICTIONS = "CLEARED_WITH_RESTRICTIONS"
    NOT_CLEARED = "NOT_CLEARED"
    DEFERRED = "DEFERRED"


class ClearanceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PENDING_REEVALUATION = "PENDING_REEVALUATION"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class ClearanceVoidReason(str, Enum):
    IMMUNIZATION_COMPLIANCE_LOST = "IMMUNIZATION_COMPLIANCE_LOST"
    SCREENING_REFERRAL_RAISED = "SCREENING_REFERRAL_RAISED"


# ─── Immunization dose (PRD §3.7) ────────────────────────────────────────────

class SeriesCode(str, Enum):
    HEPB = "HEPB"
    MMR = "MMR"


class DoseStatus(str, Enum):
    VALID = "VALID"
    INVALID_TOO_EARLY = "INVALID_TOO_EARLY"
    VOIDED = "VOIDED"


class DoseInvalidReason(str, Enum):
    MIN_AGE_NOT_MET = "MIN_AGE_NOT_MET"
    MIN_INTERVAL_NOT_MET = "MIN_INTERVAL_NOT_MET"
    PREDECESSOR_VOIDED = "PREDECESSOR_VOIDED"


# ─── Screening (PRD §3.8) ────────────────────────────────────────────────────

class ScreeningInstrument(str, Enum):
    VISION = "VISION"
    HEARING = "HEARING"
    DENTAL = "DENTAL"
    BMI = "BMI"
    BEHAVIORAL = "BEHAVIORAL"


class ScreeningOutcome(str, Enum):
    PASS = "PASS"
    REFER = "REFER"


class ScreeningBandLabel(str, Enum):
    NORMAL = "NORMAL"
    ABNORMAL = "ABNORMAL"


class ScreeningStatus(str, Enum):
    RECORDED = "RECORDED"
    CLOSED_PASS = "CLOSED_PASS"
    REFERRED = "REFERRED"


# ─── Referral (PRD §3.8) ─────────────────────────────────────────────────────

class ReferralSpecialty(str, Enum):
    OPHTHALMOLOGY = "OPHTHALMOLOGY"
    AUDIOLOGY = "AUDIOLOGY"
    DENTISTRY = "DENTISTRY"
    BEHAVIORAL_HEALTH = "BEHAVIORAL_HEALTH"
    PRIMARY_CARE = "PRIMARY_CARE"
    NUTRITION = "NUTRITION"


class ReferralStatus(str, Enum):
    OPEN = "OPEN"
    OUTREACH_IN_PROGRESS = "OUTREACH_IN_PROGRESS"
    SCHEDULED = "SCHEDULED"
    REPORT_RECEIVED = "REPORT_RECEIVED"
    CLOSED = "CLOSED"
    LOST_TO_FOLLOW_UP = "LOST_TO_FOLLOW_UP"


class OutreachOutcome(str, Enum):
    REACHED = "REACHED"
    NO_ANSWER = "NO_ANSWER"


# ─── Billable charge (PRD §3.10) ─────────────────────────────────────────────

class ServiceCategory(str, Enum):
    ACUTE_OFFICE_VISIT = "ACUTE_OFFICE_VISIT"
    BEHAVIORAL_THERAPY = "BEHAVIORAL_THERAPY"
    DENTAL_PREVENTIVE = "DENTAL_PREVENTIVE"
    SPORTS_PHYSICAL_EXAM = "SPORTS_PHYSICAL_EXAM"
    IMMUNIZATION_ADMIN = "IMMUNIZATION_ADMIN"
    TELEHEALTH_ENCOUNTER = "TELEHEALTH_ENCOUNTER"


class ChargeStatus(str, Enum):
    PENDING = "PENDING"
    CLAIM_SUBMITTED = "CLAIM_SUBMITTED"
    CLAIM_DENIED = "CLAIM_DENIED"
    CLAIM_APPEALED = "CLAIM_APPEALED"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"
    NO_CHARGE = "NO_CHARGE"
    REVERSED = "REVERSED"


class AdjudicationOutcome(str, Enum):
    PAID = "PAID"
    DENIED = "DENIED"


# ─── Parent notification (PRD §3.11) ─────────────────────────────────────────

class NotificationEventType(str, Enum):
    VISIT_COMPLETED = "VISIT_COMPLETED"
    CLEARANCE_DETERMINED = "CLEARANCE_DETERMINED"
    CLEARANCE_VOIDED = "CLEARANCE_VOIDED"
    REFERRAL_CREATED = "REFERRAL_CREATED"
    IMMUNIZATION_NON_COMPLIANT = "IMMUNIZATION_NON_COMPLIANT"


class NotificationStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    FAILED = "FAILED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    UNDELIVERABLE = "UNDELIVERABLE"
    SUPPRESSED_CONFIDENTIAL = "SUPPRESSED_CONFIDENTIAL"
    SUPPRESSED_OPT_OUT = "SUPPRESSED_OPT_OUT"


class NotificationSuppressionReason(str, Enum):
    NO_GUARDIAN_ON_FILE = "NO_GUARDIAN_ON_FILE"
    CONFIDENTIAL_SERVICE = "CONFIDENTIAL_SERVICE"
    GUARDIAN_OPT_OUT = "GUARDIAN_OPT_OUT"


class DeliveryOutcome(str, Enum):
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


# ─── Telehealth session (PRD §3.6) ───────────────────────────────────────────

class TelehealthSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class SessionCloseOutcome(str, Enum):
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


# ─── Entity shapes ───────────────────────────────────────────────────────────
# Every entity except the aggregate report carries id + created_at +
# updated_at + version (PRD §2.4). The report snapshot is immutable and
# carries id and created_at only.


class School(TypedDict):
    id: str
    name: str
    site_code: str
    sponsor_hospital_name: str
    program_status: str
    telehealth_concurrent_capacity: int
    telehealth_booked_minutes_total: int
    suspended_count: int
    created_at: str
    updated_at: str
    version: int


class Clinician(TypedDict):
    id: str
    full_name: str
    discipline: str
    license_number: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    first_name: str
    last_name: str
    date_of_birth: str
    household_income_annual_cents: int
    household_size: int
    payer_route: str
    insurance_member_id: Optional[str]
    fpl_percent: float
    discount_tier: str
    immunization_compliance_status: str
    immunization_exemption_type: str
    valid_dose_count: int
    invalid_dose_count: int
    voided_dose_count: int
    total_dose_count: int
    created_at: str
    updated_at: str
    version: int


class Guardian(TypedDict):
    id: str
    student_id: str
    full_name: str
    relationship: str
    contact_email: str
    is_primary: bool
    notification_opt_out: bool
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    student_id: str
    school_id: str
    school_year: str
    status: str
    activated_at: Optional[str]
    withdrawn_at: Optional[str]
    withdrawal_reason: Optional[str]
    reinstated_count: int
    created_at: str
    updated_at: str
    version: int


class Consent(TypedDict):
    id: str
    student_id: str
    category: str
    school_year: str
    granted_by: str
    granted_by_user_id: str
    status: str
    effective_at: str
    expires_at: str
    revoked_at: Optional[str]
    revocation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict):
    id: str
    student_id: str
    school_id: str
    clinician_id: str
    enrollment_id: str
    consent_id: str
    visit_type: str
    delivery_mode: str
    confidential_service_requested: bool
    confidential: bool
    scheduled_start_at: str
    completed_at: Optional[str]
    disposition: Optional[str]
    clinical_status: str
    billing_status: str
    gross_charge_total_cents: int
    no_charge_total_cents: int
    patient_responsibility_total_cents: int
    write_off_total_cents: int
    payer_billed_total_cents: int
    created_at: str
    updated_at: str
    version: int


class SportsPhysicalClearance(TypedDict):
    id: str
    visit_id: str
    student_id: str
    school_year: str
    outcome: str
    restrictions: Optional[str]
    determination_date: str
    unrestricted_valid_until: Optional[str]
    valid_until: Optional[str]
    reevaluation_count: int
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ImmunizationDose(TypedDict):
    id: str
    student_id: str
    visit_id: Optional[str]
    series_code: str
    dose_number: int
    administered_date: str
    earliest_valid_date: Optional[str]
    strict_earliest_valid_date: Optional[str]
    status: str
    invalid_reason: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Screening(TypedDict):
    id: str
    visit_id: str
    student_id: str
    instrument: str
    numeric_result: float
    outcome: str
    band_label: str
    generated_referral_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    student_id: str
    source_screening_id: Optional[str]
    source_visit_id: Optional[str]
    requested_by_user_id: str
    specialty: str
    reason: Optional[str]
    outreach_attempt_count: int
    status: str
    report_received_date: Optional[str]
    report_summary: Optional[str]
    closed_by_user_id: Optional[str]
    closure_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BillableCharge(TypedDict):
    id: str
    visit_id: str
    student_id: str
    service_category: str
    gross_amount_cents: int
    payer_route: str
    discount_tier_snapshot: str
    provisional_patient_responsibility_cents: int
    final_patient_responsibility_cents: Optional[int]
    floor_adjustment_cents: int
    patient_responsibility_cents: int
    payer_paid_amount_cents: int
    patient_paid_amount_cents: int
    write_off_amount_cents: int
    appeal_count: int
    denial_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ParentNotification(TypedDict):
    id: str
    student_id: str
    guardian_id: Optional[str]
    visit_id: Optional[str]
    event_type: str
    status: str
    delivery_attempt_count: int
    sent_at: Optional[str]
    acknowledged_at: Optional[str]
    suppression_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TelehealthSession(TypedDict):
    id: str
    visit_id: str
    clinician_id: str
    school_id: str
    start_at: str
    end_at: str
    duration_minutes: int
    reschedule_count: int
    closure_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AggregateReport(TypedDict):
    """Immutable snapshot — carries id and created_at only, no updated_at and
    no version (PRD §2.4)."""

    id: str
    school_id: Optional[str]
    visit_type_filter: Optional[str]
    period_start_date: str
    period_end_date: str
    generated_at: str
    total_visits: int
    scheduled_visit_count: int
    in_progress_visit_count: int
    completed_visit_count: int
    cancelled_visit_count: int
    no_show_visit_count: int
    gross_charge_total_cents: int
    no_charge_total_cents: int
    patient_responsibility_total_cents: int
    write_off_total_cents: int
    payer_billed_total_cents: int
    referral_total_count: int
    referral_closed_count: int
    referral_lost_count: int
    referral_closure_rate_all: float
    referral_closure_rate_excluding_lost: float
    grace_compliance_count: int
    strict_compliance_count: int
    created_at: str
