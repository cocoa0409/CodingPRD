"""Domain types for the Mobile Dentistry API: status enums, role enum, entity TypedDicts.

Every field name here is the exact name used by the PRD.
All fifteen entity types carry ``id``, ``created_at``, ``updated_at`` and ``version``.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    SITE_COORDINATOR = "SiteCoordinator"
    FIELD_DENTIST = "FieldDentist"
    FIELD_HYGIENIST = "FieldHygienist"
    DENTAL_ASSISTANT = "DentalAssistant"
    BILLING_SPECIALIST = "BillingSpecialist"
    GUARDIAN = "Guardian"


# ─── Status enums ─────────────────────────────────────────────────────────────

class ProgramPeriodStatus(str, Enum):
    OPEN = "OPEN"
    REPORTING = "REPORTING"
    SUBMITTED = "SUBMITTED"
    CLOSED = "CLOSED"


class SiteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SiteType(str, Enum):
    SCHOOL = "SCHOOL"
    SNF = "SNF"


class RosterDisclosureLevel(str, Enum):
    SUMMARY_ONLY = "SUMMARY_ONLY"
    CLINICAL_DETAIL = "CLINICAL_DETAIL"


class HoldType(str, Enum):
    WEATHER_CLOSURE = "WEATHER_CLOSURE"
    OUTBREAK_LOCKDOWN = "OUTBREAK_LOCKDOWN"
    ADMINISTRATIVE = "ADMINISTRATIVE"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class PatientType(str, Enum):
    STUDENT = "STUDENT"
    RESIDENT = "RESIDENT"


class CapacityDetermination(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    HAS_CAPACITY = "HAS_CAPACITY"
    LACKS_CAPACITY = "LACKS_CAPACITY"


class ConsentRegime(str, Enum):
    SCHOOL_GUARDIAN = "SCHOOL_GUARDIAN"
    SNF_RESPONSIBLE_PARTY = "SNF_RESPONSIBLE_PARTY"


class ScopeTier(str, Enum):
    SCREENING_ONLY = "SCREENING_ONLY"
    SCREENING_FLUORIDE = "SCREENING_FLUORIDE"
    SCREENING_FLUORIDE_SEALANT = "SCREENING_FLUORIDE_SEALANT"
    FULL_WITH_RADIOGRAPHS = "FULL_WITH_RADIOGRAPHS"


class ResponsiblePartyAuthority(str, Enum):
    DURABLE_POA = "DURABLE_POA"
    HEALTHCARE_PROXY = "HEALTHCARE_PROXY"
    COURT_GUARDIAN = "COURT_GUARDIAN"
    SELF = "SELF"


class ConsentStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class PortableUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_SERVICE = "IN_SERVICE"
    QUARANTINED = "QUARANTINED"


class CalibrationStatus(str, Enum):
    CURRENT = "CURRENT"
    DUE = "DUE"
    EXPIRED = "EXPIRED"


class SporeResult(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class StaffRole(str, Enum):
    DENTIST = "DENTIST"
    HYGIENIST = "HYGIENIST"
    PUBLIC_HEALTH_HYGIENIST = "PUBLIC_HEALTH_HYGIENIST"
    DENTAL_ASSISTANT = "DENTAL_ASSISTANT"


class SupervisionLevel(str, Enum):
    DIRECT = "DIRECT"
    INDIRECT = "INDIRECT"
    GENERAL = "GENERAL"
    SELF = "SELF"


class CredentialStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    INACTIVE = "INACTIVE"


class SiteVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HOLD_BLOCKED = "HOLD_BLOCKED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PayerType(str, Enum):
    MEDICAID_MCO = "MEDICAID_MCO"
    COMMERCIAL_FFS = "COMMERCIAL_FFS"
    UNINSURED = "UNINSURED"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"


class SlidingFeeBand(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


class ClinicalStatus(str, Enum):
    REGISTERED = "REGISTERED"
    SCREENED = "SCREENED"
    EXAMINED = "EXAMINED"
    TREATED = "TREATED"
    CLOSED = "CLOSED"
    DEFERRED = "DEFERRED"
    NO_SHOW = "NO_SHOW"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    PRICED = "PRICED"
    CLAIMED = "CLAIMED"
    PAID = "PAID"
    DENIED = "DENIED"


class TriageBand(str, Enum):
    URGENT = "URGENT"
    EARLY_CARE_NEEDED = "EARLY_CARE_NEEDED"
    NO_OBVIOUS_PROBLEM = "NO_OBVIOUS_PROBLEM"


class ExamModality(str, Enum):
    ONSITE = "ONSITE"
    TELEDENTISTRY = "TELEDENTISTRY"


class PricingRegime(str, Enum):
    MEDICAID_ENCOUNTER_RATE = "MEDICAID_ENCOUNTER_RATE"
    COMMERCIAL_FEE_SCHEDULE = "COMMERCIAL_FEE_SCHEDULE"
    UNINSURED_SLIDING_FEE = "UNINSURED_SLIDING_FEE"


class ProcedureCode(str, Enum):
    D0190 = "D0190"
    D0150 = "D0150"
    D1206 = "D1206"
    D1351 = "D1351"
    D0272 = "D0272"


class Surface(str, Enum):
    O = "O"
    B = "B"
    L = "L"
    M = "M"
    D = "D"


class ProcedureStatus(str, Enum):
    PLANNED = "PLANNED"
    PERFORMED = "PERFORMED"
    INELIGIBLE = "INELIGIBLE"
    VOIDED = "VOIDED"
    TAINTED = "TAINTED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class FollowUpStatus(str, Enum):
    NOT_DUE = "NOT_DUE"
    DUE = "DUE"
    OVERDUE = "OVERDUE"
    CONTACTED = "CONTACTED"


class ReferralStatus(str, Enum):
    OPEN = "OPEN"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    NO_RESPONSE = "NO_RESPONSE"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class ReportType(str, Enum):
    PARENT = "PARENT"
    FACILITY_ROSTER = "FACILITY_ROSTER"
    PROGRAM_PERIOD = "PROGRAM_PERIOD"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    GENERATED = "GENERATED"
    STALE = "STALE"
    SUBMITTED = "SUBMITTED"


# ─── Entity shapes ────────────────────────────────────────────────────────────
# Every entity carries id / created_at / updated_at / version.

class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class ProgramPeriod(CommonFields):
    name: str
    starts_on: str
    ends_on: str
    status: str
    frozen_at: Optional[str]
    state_submission_ref: Optional[str]


class Site(CommonFields):
    name: str
    site_type: str
    state_code: str
    status: str
    roster_disclosure_level: str
    facility_contact_name: Optional[str]
    active_hold_count: int


class SiteHold(CommonFields):
    site_id: str
    hold_type: str
    starts_at: str
    ends_at: str
    hold_status: str
    reason: Optional[str]
    released_at: Optional[str]
    blocked_visit_count: int


class Patient(CommonFields):
    site_id: str
    patient_type: str
    external_ref: str
    first_name: str
    last_name: str
    date_of_birth: str
    grade_level: Optional[str]
    room_number: Optional[str]
    household_size: int
    annual_household_income_cents: Optional[int]
    capacity_determination: str
    capacity_determined_at: Optional[str]
    varnish_applications_in_period: int
    last_varnish_date: Optional[str]


class Consent(CommonFields):
    patient_id: str
    site_id: str
    program_period_id: str
    regime: str
    scope_tier: str
    status: str
    guardian_name: Optional[str]
    guardian_relationship: Optional[str]
    responsible_party_name: Optional[str]
    responsible_party_authority: Optional[str]
    poa_document_ref: Optional[str]
    signed_at: str
    expires_at: Optional[str]
    reaffirmation_due_at: Optional[str]
    superseded_by_consent_id: Optional[str]
    revoked_at: Optional[str]
    revoke_reason: Optional[str]
    expired_at: Optional[str]
    invalidated_procedure_count: int


class PortableUnit(CommonFields):
    unit_code: str
    status: str
    last_calibrated_on: Optional[str]
    calibration_due_on: Optional[str]
    calibration_status: str
    last_passed_load_at: Optional[str]
    quarantined_at: Optional[str]


class SterilizationLoad(CommonFields):
    portable_unit_id: str
    site_visit_id: Optional[str]
    loaded_by_staff_id: str
    result_recorded_by_staff_id: Optional[str]
    load_number: str
    cycle_completed_at: str
    incubation_ends_at: str
    spore_result: str
    result_recorded_at: Optional[str]
    auto_failed: bool
    tainted_procedure_count: int


class StaffMember(CommonFields):
    full_name: str
    staff_role: str
    license_number: str
    license_state: str
    supervision_level: str
    credential_status: str
    credential_expires_on: Optional[str]


class SiteVisit(CommonFields):
    site_id: str
    program_period_id: str
    portable_unit_id: str
    lead_staff_id: str
    onsite_dentist_staff_id: Optional[str]
    remote_dentist_staff_id: Optional[str]
    scheduled_start_at: str
    scheduled_end_at: str
    chair_count: int
    capacity_chair_minutes: int
    booked_chair_minutes: int
    status: str
    reschedule_count: int
    started_at: Optional[str]
    completed_at: Optional[str]
    cancelled_at: Optional[str]


class Coverage(CommonFields):
    patient_id: str
    payer_type: str
    payer_name: Optional[str]
    member_id: Optional[str]
    verification_status: str
    verified_through_date: Optional[str]
    verified_at: Optional[str]
    fpl_percent: Optional[float]
    sliding_fee_band: Optional[str]
    determination_date: Optional[str]


class Encounter(CommonFields):
    site_visit_id: str
    patient_id: str
    consent_id: str
    coverage_id: Optional[str]
    clinical_status: str
    billing_status: str
    triage_band: Optional[str]
    cavitated_lesion_count: Optional[int]
    pain_reported: Optional[bool]
    abscess_or_swelling: Optional[bool]
    untreated_decay_present: Optional[bool]
    denture_problem: Optional[bool]
    oral_hygiene_score: Optional[int]
    medical_complexity_count: Optional[int]
    exam_modality: Optional[str]
    teledentistry_reviewed_at: Optional[str]
    subtotal_cents: int
    supply_surcharge_cents: int
    total_charge_cents: int
    allowed_amount_cents: int
    patient_responsibility_cents: int
    plan_paid_cents: int
    write_off_cents: int
    pricing_regime: Optional[str]
    tainted_procedure_count: int
    deferred_reason: Optional[str]
    denial_reason: Optional[str]


class Procedure(CommonFields):
    encounter_id: str
    treatment_plan_id: Optional[str]
    sterilization_load_id: Optional[str]
    performing_staff_id: Optional[str]
    procedure_code: str
    tooth_number: Optional[int]
    surface: Optional[str]
    required_tier: str
    chair_minutes: int
    charge_cents: int
    status: str
    performed_at: Optional[str]
    taint_reason: Optional[str]
    void_reason: Optional[str]


class TreatmentPlan(CommonFields):
    encounter_id: str
    patient_id: str
    authoring_staff_id: str
    plan_status: str
    urgency_band: str
    planned_procedure_codes: List[str]
    activated_on: Optional[str]
    follow_up_due_date: Optional[str]
    follow_up_status: str
    last_contact_at: Optional[str]
    contact_attempt_count: int
    superseded_reason: Optional[str]


class Referral(CommonFields):
    treatment_plan_id: str
    patient_id: str
    dental_home_name: str
    status: str
    attempt_count: int
    due_at: Optional[str]
    last_sent_at: Optional[str]
    next_eligible_send_at: Optional[str]
    abandoned_at: Optional[str]
    abandon_reason: Optional[str]
    case_management_opened_at: Optional[str]


class Report(CommonFields):
    program_period_id: str
    site_id: Optional[str]
    patient_id: Optional[str]
    report_type: str
    recipient_user_id: Optional[str]
    status: str
    payload: Optional[Dict[str, Any]]
    generated_at: Optional[str]
    submitted_at: Optional[str]
    stale_reason: Optional[str]
