"""Domain types: entity TypedDicts, status enums, role enum for the stewardship API."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    STEWARDSHIP_ADMIN = "StewardshipAdmin"
    STEWARDSHIP_DIRECTOR = "StewardshipDirector"
    ID_PHARMACIST = "IDPharmacist"
    ATTENDING_PHYSICIAN = "AttendingPhysician"
    MICROBIOLOGIST = "Microbiologist"
    INFECTION_PREVENTIONIST = "InfectionPreventionist"


class Discipline(str, Enum):
    PHYSICIAN = "PHYSICIAN"
    PHARMACIST = "PHARMACIST"
    MICROBIOLOGIST = "MICROBIOLOGIST"
    INFECTION_PREVENTIONIST = "INFECTION_PREVENTIONIST"


class StewardshipStanding(str, Enum):
    GOOD = "GOOD"
    WATCH = "WATCH"
    SUSPENDED = "SUSPENDED"


class PatientCaseStatus(str, Enum):
    ADMITTED = "ADMITTED"
    DISCHARGED = "DISCHARGED"


class FormularyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AllergyAssessmentStatus(str, Enum):
    SUSPECTED = "SUSPECTED"
    TESTING_SCHEDULED = "TESTING_SCHEDULED"
    TESTED = "TESTED"
    DELABELED = "DELABELED"
    CONFIRMED = "CONFIRMED"
    WITHDRAWN = "WITHDRAWN"


class ReactionSeverity(str, Enum):
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class TestResult(str, Enum):
    NULL = "NULL"
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"
    INDETERMINATE = "INDETERMINATE"


class CultureReportStatus(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    FINAL = "FINAL"
    AMENDED = "AMENDED"


class Interpretation(str, Enum):
    S = "S"
    I = "I"
    R = "R"


class Route(str, Enum):
    IV = "IV"
    PO = "PO"
    IM = "IM"


class Indication(str, Enum):
    EMPIRIC = "EMPIRIC"
    CULTURE_DIRECTED = "CULTURE_DIRECTED"
    PROPHYLAXIS = "PROPHYLAXIS"


class ApprovalStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class TherapyStatus(str, Enum):
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    ACTIVE = "ACTIVE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    DEESCALATED = "DEESCALATED"
    CONVERTED = "CONVERTED"
    COMPLETED = "COMPLETED"
    DISCONTINUED = "DISCONTINUED"


class ApprovalRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ESCALATED = "ESCALATED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class InterventionType(str, Enum):
    DOSE_OPTIMIZATION = "DOSE_OPTIMIZATION"
    DEESCALATION = "DEESCALATION"
    IV_TO_PO = "IV_TO_PO"
    DURATION_REDUCTION = "DURATION_REDUCTION"
    STOP = "STOP"


class RecommendationStatus(str, Enum):
    DOCUMENTED = "DOCUMENTED"
    RECOMMENDED = "RECOMMENDED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    APPEALED = "APPEALED"
    REJECTED_FINAL = "REJECTED_FINAL"
    SUPERSEDED = "SUPERSEDED"


class OpportunityKind(str, Enum):
    IV_TO_PO = "IV_TO_PO"
    DEESCALATION = "DEESCALATION"


class OpportunityStatus(str, Enum):
    DETECTED = "DETECTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class AntibiogramStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class GuidelineStatus(str, Enum):
    DRAFT = "DRAFT"
    ADOPTED = "ADOPTED"
    STALE = "STALE"
    RETIRED = "RETIRED"


class SnapshotStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class ReportType(str, Enum):
    NHSN_AUR = "NHSN_AUR"
    STATE_MANDATE = "STATE_MANDATE"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class Hospital(TypedDict, total=False):
    id: str
    name: str
    nhsn_facility_id: str
    current_utc: str
    dot_review_threshold: int
    iv_to_po_min_iv_hours: int
    antibiogram_min_isolates: int
    restricted_auto_expire_hours: int
    created_at: str
    updated_at: str
    version: int


class Practitioner(TypedDict, total=False):
    id: str
    hospital_id: str
    full_name: str
    license_no: str
    discipline: str
    is_stewardship_member: bool
    is_active: bool
    stewardship_standing: str
    unresolved_noncompliance_count: int
    created_at: str
    updated_at: str
    version: int


class PatientCase(TypedDict, total=False):
    id: str
    hospital_id: str
    mrn: str
    admitted_at: str
    ward: str
    is_immunocompromised: bool
    weight_kg: float
    renal_function_crcl: int
    has_enteral_access: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Antimicrobial(TypedDict, total=False):
    id: str
    hospital_id: str
    drug_name: str
    drug_class: str
    is_restricted: bool
    has_po_form: bool
    is_penicillin_class: bool
    formulary_status: str
    created_at: str
    updated_at: str
    version: int


class AllergyAssessment(TypedDict, total=False):
    id: str
    patient_case_id: str
    reported_reaction: str
    reaction_severity: str
    years_since_reaction: int
    risk_score: float
    delabel_eligible: bool
    status: str
    test_result: str
    created_at: str
    updated_at: str
    version: int


class CultureReport(TypedDict, total=False):
    id: str
    patient_case_id: str
    specimen_source: str
    collected_at: str
    organism: str
    is_first_isolate: bool
    resulted_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SusceptibilityResult(TypedDict, total=False):
    id: str
    culture_report_id: str
    antimicrobial_id: str
    interpretation: str
    mic_value: float
    created_at: str
    updated_at: str
    version: int


class AntibioticOrder(TypedDict, total=False):
    id: str
    patient_case_id: str
    antimicrobial_id: str
    prescriber_id: str
    route: str
    dose_mg: int
    frequency_per_day: int
    started_at: str
    stopped_at: str
    cumulative_iv_hours: int
    administered_doses: int
    dot_calendar: int
    dot_dose: float
    indication: str
    approval_status: str
    therapy_status: str
    created_at: str
    updated_at: str
    version: int


class ApprovalRequest(TypedDict, total=False):
    id: str
    antibiotic_order_id: str
    requester_id: str
    justification: str
    submitted_at: str
    decided_at: Optional[str]
    decided_by_id: Optional[str]
    escalation_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditIntervention(TypedDict, total=False):
    id: str
    antibiotic_order_id: str
    auditor_id: str
    intervention_type: str
    recommendation_text: str
    recommendation_status: str
    responded_by_id: Optional[str]
    appeal_adjudicator_id: Optional[str]
    due_at: str
    created_at: str
    updated_at: str
    version: int


class ConversionOpportunity(TypedDict, total=False):
    id: str
    antibiotic_order_id: str
    opportunity_kind: str
    eligibility_score: float
    detected_at: str
    suggested_antimicrobial_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Antibiogram(TypedDict, total=False):
    id: str
    hospital_id: str
    period_start: str
    period_end: str
    generated_at: str
    row_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AntibiogramRow(TypedDict, total=False):
    id: str
    antibiogram_id: str
    organism: str
    antimicrobial_id: str
    isolate_count: int
    susceptible_count: int
    pct_susceptible: float
    is_reportable: bool
    created_at: str
    updated_at: str
    version: int


class EmpiricGuideline(TypedDict, total=False):
    id: str
    hospital_id: str
    syndrome: str
    first_line_antimicrobial_id: str
    source_antibiogram_id: str
    supersedes_guideline_id: Optional[str]
    pct_susceptible_at_adoption: float
    status: str
    created_at: str
    updated_at: str
    version: int


class DOTMetricSnapshot(TypedDict, total=False):
    id: str
    hospital_id: str
    period_label: str
    total_dot_calendar: int
    total_dot_dose: float
    patient_days: int
    dot_per_1000_pd_calendar: float
    dot_per_1000_pd_dose: float
    benchmark_percentile: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RegulatoryReport(TypedDict, total=False):
    id: str
    hospital_id: str
    report_type: str
    period_label: str
    dot_snapshot_id: str
    payload_json: str
    checksum: str
    submitted_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
