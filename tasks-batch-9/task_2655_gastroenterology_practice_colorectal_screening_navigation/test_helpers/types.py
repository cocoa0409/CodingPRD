"""Domain types for the Colorectal Screening Navigation API.

Status enums, role enum and entity TypedDicts. Every one of the thirteen
resource types this API persists carries `id`, `created_at`, `updated_at` and
`version` (PRD §2.4), so every TypedDict below lists all four.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────

class UserRole(str, Enum):
    PRACTICE_ADMIN = "PracticeAdmin"
    REFERRAL_COORDINATOR = "ReferralCoordinator"
    PATIENT_NAVIGATOR = "PatientNavigator"
    ENDOSCOPIST = "Endoscopist"
    PATHOLOGIST = "Pathologist"
    BILLING_SPECIALIST = "BillingSpecialist"
    QUALITY_OFFICER = "QualityOfficer"
    PATIENT = "Patient"


# ─── Reference data enums ─────────────────────────────

class PolypectomyCarveout(str, Enum):
    PREVENTIVE_RETAINED = "PREVENTIVE_RETAINED"
    DIAGNOSTIC_CONVERTED = "DIAGNOSTIC_CONVERTED"


class ClinicianType(str, Enum):
    ENDOSCOPIST = "ENDOSCOPIST"
    ANESTHESIA = "ANESTHESIA"


class CredentialStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RiskTier(str, Enum):
    AVERAGE = "AVERAGE"
    INCREASED = "INCREASED"
    HIGH = "HIGH"


class NavigationPriority(str, Enum):
    ROUTINE = "ROUTINE"
    HIGH = "HIGH"


# ─── Referral enums ───────────────────────────────────

class ReferralStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_TRIAGE = "UNDER_TRIAGE"
    INFO_REQUESTED = "INFO_REQUESTED"
    ACCEPTED_OPEN_ACCESS = "ACCEPTED_OPEN_ACCESS"
    ACCEPTED_OFFICE_VISIT = "ACCEPTED_OFFICE_VISIT"
    DECLINED = "DECLINED"


class ReferralReason(str, Enum):
    AVERAGE_RISK_SCREENING = "AVERAGE_RISK_SCREENING"
    FAMILY_HISTORY = "FAMILY_HISTORY"
    POSITIVE_FIT = "POSITIVE_FIT"
    SURVEILLANCE = "SURVEILLANCE"
    SYMPTOMATIC_BLEEDING = "SYMPTOMATIC_BLEEDING"


class RiskScreenResult(str, Enum):
    PENDING = "PENDING"
    CLEARED_OPEN_ACCESS = "CLEARED_OPEN_ACCESS"
    OFFICE_VISIT_REQUIRED = "OFFICE_VISIT_REQUIRED"


class TriageAction(str, Enum):
    BEGIN_TRIAGE = "BEGIN_TRIAGE"
    REQUEST_INFO = "REQUEST_INFO"
    RESPOND_INFO = "RESPOND_INFO"
    ACCEPT_OPEN_ACCESS = "ACCEPT_OPEN_ACCESS"
    ACCEPT_OFFICE_VISIT = "ACCEPT_OFFICE_VISIT"
    DECLINE = "DECLINE"


# ─── Episode enums ────────────────────────────────────

class EpisodeIndication(str, Enum):
    SCREENING_AVERAGE_RISK = "SCREENING_AVERAGE_RISK"
    SCREENING_HIGH_RISK = "SCREENING_HIGH_RISK"
    SURVEILLANCE = "SURVEILLANCE"
    DIAGNOSTIC_FOLLOWUP = "DIAGNOSTIC_FOLLOWUP"


class EpisodeOrigin(str, Enum):
    DIRECT = "DIRECT"
    REFERRAL = "REFERRAL"
    NONINVASIVE_POSITIVE = "NONINVASIVE_POSITIVE"
    SURVEILLANCE_RECALL = "SURVEILLANCE_RECALL"


class EligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE_AGE = "INELIGIBLE_AGE"
    INELIGIBLE_PRIOR_CRC = "INELIGIBLE_PRIOR_CRC"
    INELIGIBLE_RISK_MISMATCH = "INELIGIBLE_RISK_MISMATCH"


class ClinicalStatus(str, Enum):
    OPEN = "OPEN"
    PROCEDURE_SCHEDULED = "PROCEDURE_SCHEDULED"
    PATHOLOGY_PENDING = "PATHOLOGY_PENDING"
    CLOSED_SURVEILLANCE_SET = "CLOSED_SURVEILLANCE_SET"
    CLOSED_DECLINED = "CLOSED_DECLINED"
    CLOSED_SUPERSEDED = "CLOSED_SUPERSEDED"


class NavigationStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    OUTREACH_ACTIVE = "OUTREACH_ACTIVE"
    PREP_AT_RISK = "PREP_AT_RISK"
    PREP_CONFIRMED = "PREP_CONFIRMED"
    NAVIGATION_COMPLETE = "NAVIGATION_COMPLETE"


class PrepAttestation(str, Enum):
    NONE = "NONE"
    COMPLETED = "COMPLETED"
    NOT_COMPLETED = "NOT_COMPLETED"


class ClosureReason(str, Enum):
    PATIENT_DECLINED = "PATIENT_DECLINED"
    LOST_TO_FOLLOW_UP = "LOST_TO_FOLLOW_UP"
    SUPERSEDED_BY_OTHER_PATHWAY = "SUPERSEDED_BY_OTHER_PATHWAY"


class OutreachChannel(str, Enum):
    PHONE = "PHONE"
    SMS = "SMS"
    PORTAL = "PORTAL"
    MAIL = "MAIL"


# ─── Non-invasive test enums ──────────────────────────

class TestType(str, Enum):
    FIT = "FIT"
    MT_SDNA = "MT_SDNA"


class TestResult(str, Enum):
    PENDING = "PENDING"
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"
    INSUFFICIENT_SPECIMEN = "INSUFFICIENT_SPECIMEN"


# ─── Suite enums ──────────────────────────────────────

class SessionStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    COVERAGE_CONFIRMED = "COVERAGE_CONFIRMED"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class SessionAction(str, Enum):
    PUBLISH = "PUBLISH"
    SUSPEND = "SUSPEND"
    RESUME = "RESUME"
    CLOSE = "CLOSE"


class AnesthesiaMode(str, Enum):
    MODERATE_SEDATION = "MODERATE_SEDATION"
    MAC = "MAC"


class CoverageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED_INADEQUATE_PREP = "ABORTED_INADEQUATE_PREP"
    CANCELLED = "CANCELLED"


# ─── Pathology enums ──────────────────────────────────

class PathologyStatus(str, Enum):
    RECEIVED = "RECEIVED"
    FINALIZED = "FINALIZED"
    AMENDED = "AMENDED"


class Histology(str, Enum):
    TUBULAR_ADENOMA = "TUBULAR_ADENOMA"
    TUBULOVILLOUS_ADENOMA = "TUBULOVILLOUS_ADENOMA"
    SESSILE_SERRATED_LESION = "SESSILE_SERRATED_LESION"
    HYPERPLASTIC = "HYPERPLASTIC"
    ADENOCARCINOMA = "ADENOCARCINOMA"
    NORMAL_MUCOSA = "NORMAL_MUCOSA"


class RecommendationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class RecommendationBasis(str, Enum):
    GUIDELINE = "GUIDELINE"
    OVERRIDE_ATTESTED = "OVERRIDE_ATTESTED"


# ─── Billing enums ────────────────────────────────────

class ClaimStatus(str, Enum):
    PROVISIONAL_PRICED = "PROVISIONAL_PRICED"
    REPRICED = "REPRICED"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    VOIDED = "VOIDED"


class ClaimVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ClaimClassification(str, Enum):
    SCREENING_PREVENTIVE = "SCREENING_PREVENTIVE"
    DIAGNOSTIC = "DIAGNOSTIC"


class ComplexityTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class LineItemCode(str, Enum):
    FACILITY = "FACILITY"
    PROFESSIONAL = "PROFESSIONAL"
    ANESTHESIA = "ANESTHESIA"
    ABORTED_TECHNICAL = "ABORTED_TECHNICAL"


# ─── Quality enums ────────────────────────────────────

class QualityPeriodStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    ATTESTED = "ATTESTED"


class AttributionBasis(str, Enum):
    PROCEDURE_DATE = "PROCEDURE_DATE"
    PATHOLOGY_FINALIZATION_DATE = "PATHOLOGY_FINALIZATION_DATE"


class BenchmarkResult(str, Enum):
    INSUFFICIENT_VOLUME = "INSUFFICIENT_VOLUME"
    MET = "MET"
    MISSED = "MISSED"


# ─── Entity TypedDicts ────────────────────────────────

class InsurancePlan(TypedDict):
    id: str
    plan_code: str
    payer_name: str
    preventive_coverage_pct: float
    diagnostic_coinsurance_pct: float
    deductible_cents: int
    out_of_pocket_max_cents: int
    polypectomy_carveout: str
    modifier_33_honored: bool
    anesthesia_bundled: bool
    created_at: str
    updated_at: str
    version: int


class Clinician(TypedDict):
    id: str
    npi: str
    full_name: str
    clinician_type: str
    max_overlapping_rooms: int
    adr_benchmark_pct: float
    credential_status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    mrn: str
    birth_date: str
    insurance_plan_id: str
    family_history_crc: bool
    ibd_diagnosis: bool
    prior_crc_history: bool
    anticoagulant_therapy: bool
    asa_class: int
    risk_tier: str
    deductible_applied_cents: int
    oop_applied_cents: int
    open_episode_count: int
    navigation_priority: str
    created_at: str
    updated_at: str
    version: int


class EndoscopySession(TypedDict):
    id: str
    room_code: str
    session_date: str
    window_start_utc: str
    window_end_utc: str
    lead_endoscopist_id: str
    anesthesia_mode: str
    turnover_minutes: int
    max_procedures: int
    status: str
    suspension_reason: Optional[str]
    capacity_minutes: int
    booked_minutes: int
    remaining_minutes: int
    created_at: str
    updated_at: str
    version: int


class AnesthesiaCoverage(TypedDict):
    id: str
    session_id: str
    anesthesia_clinician_id: str
    coverage_start_utc: str
    coverage_end_utc: str
    covers_full_window: bool
    overlap_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    patient_id: str
    referring_provider_npi: str
    reason: str
    asa_class_reported: int
    anticoagulant_reported: bool
    status: str
    risk_screen_result: str
    info_request_rounds: int
    triage_decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutreachLogEntry(TypedDict):
    channel: str
    occurred_at: str
    acknowledged: bool


class ScreeningEpisode(TypedDict):
    id: str
    patient_id: str
    indication: str
    referral_id: Optional[str]
    preceding_episode_id: Optional[str]
    origin: str
    index_date: str
    due_date: str
    eligibility_status: str
    risk_tier_snapshot: str
    clinical_status: str
    navigation_status: str
    prep_adherence_score: float
    prep_attestation: str
    outreach_log: List[OutreachLogEntry]
    assigned_interval_months: Optional[int]
    closure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NoninvasiveTest(TypedDict):
    id: str
    episode_id: str
    test_type: str
    collected_date: str
    result: str
    resulted_at: Optional[str]
    follow_up_episode_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProcedureBooking(TypedDict):
    id: str
    session_id: str
    episode_id: str
    performing_endoscopist_id: str
    slot_start_utc: str
    slot_end_utc: str
    occupancy_end_utc: str
    duration_minutes: int
    status: str
    released_minutes: int
    prep_quality_bbps: Optional[int]
    polyps_removed_count: Optional[int]
    largest_polyp_mm: Optional[int]
    specimen_count: Optional[int]
    planned_classification: Optional[str]
    final_classification: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Specimen(TypedDict):
    label: str
    histology: str
    size_mm: int


class PathologyReport(TypedDict):
    id: str
    booking_id: str
    accession_number: str
    specimens: List[Specimen]
    high_grade_dysplasia: bool
    adenoma_count: int
    sessile_serrated_count: int
    largest_adenoma_mm: int
    villous_component: bool
    adenocarcinoma_present: bool
    status: str
    amendment_count: int
    amendment_reason: Optional[str]
    finalized_at: Optional[str]
    routed_to_endoscopist_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurveillanceRecommendation(TypedDict):
    id: str
    episode_id: str
    pathology_report_id: Optional[str]
    computed_interval_months: int
    assigned_interval_months: int
    override_interval_months: Optional[int]
    override_reason: Optional[str]
    basis: str
    attesting_endoscopist_id: Optional[str]
    next_due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LineItem(TypedDict):
    code: str
    allowed_cents: int


class BillingClaim(TypedDict):
    id: str
    booking_id: str
    insurance_plan_id: str
    status: str
    variant: str
    classification: str
    complexity_tier: str
    line_items: List[LineItem]
    base_allowed_cents: int
    allowed_amount_cents: int
    deductible_applied_cents: int
    coinsurance_cents: int
    patient_responsibility_cents: int
    plan_paid_cents: int
    reprice_count: int
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QualityPeriod(TypedDict):
    id: str
    endoscopist_id: str
    period_start_date: str
    period_end_date: str
    attribution_basis: str
    status: str
    screening_colonoscopy_count: int
    adenoma_positive_count: int
    adr_pct: Optional[float]
    benchmark_pct: Optional[float]
    benchmark_result: Optional[str]
    remediation_required: bool
    remediation_plan: Optional[str]
    attesting_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
