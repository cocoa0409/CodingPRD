"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    CLERY_COORDINATOR = "CleryCoordinator"
    POLICE_CHIEF = "PoliceChief"
    CAMPUS_SECURITY_AUTHORITY = "CampusSecurityAuthority"
    FEDERAL_REVIEWER = "FederalReviewer"
    ANONYMOUS = "Anonymous"


class GeographyCategory(str, Enum):
    ON_CAMPUS = "ON_CAMPUS"
    ON_CAMPUS_RESIDENTIAL = "ON_CAMPUS_RESIDENTIAL"
    NON_CAMPUS = "NON_CAMPUS"
    PUBLIC_PROPERTY = "PUBLIC_PROPERTY"


class GeographyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CSAStatus(str, Enum):
    PENDING_TRAINING = "PENDING_TRAINING"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    INACTIVE = "INACTIVE"


class CSACategory(str, Enum):
    DEAN = "DEAN"
    COACH = "COACH"
    RESIDENT_ADVISOR = "RESIDENT_ADVISOR"
    SECURITY_STAFF = "SECURITY_STAFF"
    OTHER_OFFICIAL = "OTHER_OFFICIAL"


class TrainingRecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class ReferralStatus(str, Enum):
    RECEIVED = "RECEIVED"
    FORWARDED = "FORWARDED"
    LINKED = "LINKED"
    DUPLICATE = "DUPLICATE"


class IncidentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_CLASSIFICATION = "UNDER_CLASSIFICATION"
    CLASSIFIED = "CLASSIFIED"
    UNDER_RECLASSIFICATION = "UNDER_RECLASSIFICATION"
    UNFOUNDED = "UNFOUNDED"
    WITHDRAWN = "WITHDRAWN"


class IncidentSource(str, Enum):
    POLICE_DIRECT = "POLICE_DIRECT"
    CSA_REFERRAL = "CSA_REFERRAL"
    ANONYMOUS = "ANONYMOUS"


class OffenseType(str, Enum):
    CRIMINAL_HOMICIDE = "CRIMINAL_HOMICIDE"
    SEX_OFFENSE = "SEX_OFFENSE"
    ROBBERY = "ROBBERY"
    AGGRAVATED_ASSAULT = "AGGRAVATED_ASSAULT"
    BURGLARY = "BURGLARY"
    MOTOR_VEHICLE_THEFT = "MOTOR_VEHICLE_THEFT"
    ARSON = "ARSON"
    DOMESTIC_VIOLENCE = "DOMESTIC_VIOLENCE"
    DATING_VIOLENCE = "DATING_VIOLENCE"
    STALKING = "STALKING"
    HATE_CRIME = "HATE_CRIME"
    LIQUOR_LAW_REFERRAL = "LIQUOR_LAW_REFERRAL"
    DRUG_LAW_REFERRAL = "DRUG_LAW_REFERRAL"
    WEAPONS_LAW_REFERRAL = "WEAPONS_LAW_REFERRAL"
    NON_CLERY = "NON_CLERY"


class OffenseStatus(str, Enum):
    COUNTED = "COUNTED"
    EXCLUDED_BY_HIERARCHY = "EXCLUDED_BY_HIERARCHY"
    EXCLUDED_UNFOUNDED = "EXCLUDED_UNFOUNDED"


class BiasMotivation(str, Enum):
    NONE = "NONE"
    RACE = "RACE"
    RELIGION = "RELIGION"
    SEXUAL_ORIENTATION = "SEXUAL_ORIENTATION"
    GENDER = "GENDER"
    GENDER_IDENTITY = "GENDER_IDENTITY"
    ETHNICITY = "ETHNICITY"
    NATIONAL_ORIGIN = "NATIONAL_ORIGIN"
    DISABILITY = "DISABILITY"


class AlertType(str, Enum):
    TIMELY_WARNING = "TIMELY_WARNING"
    EMERGENCY_NOTIFICATION = "EMERGENCY_NOTIFICATION"


class AlertStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    DECIDED_ISSUE = "DECIDED_ISSUE"
    DECIDED_NO_ISSUE = "DECIDED_NO_ISSUE"
    AUTHORIZED = "AUTHORIZED"
    DISSEMINATED = "DISSEMINATED"
    CLOSED = "CLOSED"


class AlertDecision(str, Enum):
    ISSUE = "ISSUE"
    NO_ISSUE = "NO_ISSUE"


class DistributionChannel(str, Enum):
    EMAIL = "EMAIL"
    SMS = "SMS"
    POSTERS = "POSTERS"
    WEBSITE = "WEBSITE"
    SIREN = "SIREN"


class Disposition(str, Enum):
    OPEN = "OPEN"
    INVESTIGATION_PENDING = "INVESTIGATION_PENDING"
    CLEARED_BY_ARREST = "CLEARED_BY_ARREST"
    CLEARED_EXCEPTIONAL = "CLEARED_EXCEPTIONAL"
    UNFOUNDED = "UNFOUNDED"


class InspectionStatus(str, Enum):
    PENDING = "PENDING"
    FULFILLED = "FULFILLED"


class ASRStatus(str, Enum):
    COLLECTING = "COLLECTING"
    UNDER_REVIEW = "UNDER_REVIEW"
    PUBLISHED = "PUBLISHED"
    UNDER_AMENDMENT = "UNDER_AMENDMENT"
    REPUBLISHED = "REPUBLISHED"


class CompilationVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class StatisticLineStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class FireCauseCategory(str, Enum):
    COOKING = "COOKING"
    ELECTRICAL = "ELECTRICAL"
    HEATING = "HEATING"
    SMOKING_MATERIALS = "SMOKING_MATERIALS"
    OPEN_FLAME = "OPEN_FLAME"
    INTENTIONAL = "INTENTIONAL"
    UNDETERMINED = "UNDETERMINED"


class FireIncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    FINALIZED = "FINALIZED"
    UNDER_ADJUSTMENT = "UNDER_ADJUSTMENT"


class FireReportStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPILED = "COMPILED"
    PUBLISHED = "PUBLISHED"
    UNDER_AMENDMENT = "UNDER_AMENDMENT"
    REPUBLISHED = "REPUBLISHED"


class ReviewStatus(str, Enum):
    OPENED = "OPENED"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CORRECTIVE_ACTION = "CORRECTIVE_ACTION"
    UNDER_VERIFICATION = "UNDER_VERIFICATION"
    CLOSED = "CLOSED"


class ActionStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class CleryGeography(TypedDict, total=False):
    id: str
    name: str
    category: str
    is_residential_facility: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CampusSecurityAuthority(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    department: str
    csa_category: str
    status: str
    certification_expires_at: Optional[str]
    active_training_record_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CSATrainingRecord(TypedDict, total=False):
    id: str
    csa_id: str
    completed_at: str
    score: int
    passed: bool
    training_year: int
    valid_from: str
    valid_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CSAReferralReport(TypedDict, total=False):
    id: str
    csa_id: str
    geography_id: str
    occurred_at: str
    occurred_end_at: Optional[str]
    offense_suspicion: str
    narrative: str
    received_at: str
    forwarded_at: Optional[str]
    forward_overdue: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict, total=False):
    id: str
    report_number: str
    reported_at: str
    occurred_at: str
    occurred_end_at: Optional[str]
    geography_id: str
    source: str
    referral_id: Optional[str]
    narrative: str
    is_clery_reportable: bool
    classified_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OffenseCount(TypedDict, total=False):
    id: str
    incident_id: str
    offense_type: str
    victim_count: int
    referred_persons: int
    bias_motivation: str
    hierarchy_rank: int
    is_exempt_from_hierarchy: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SafetyAlert(TypedDict, total=False):
    id: str
    incident_id: str
    alert_type: str
    decision: Optional[str]
    decision_rationale: Optional[str]
    decided_by: Optional[str]
    decided_at: Optional[str]
    decision_deadline_at: str
    decision_overdue: bool
    authorized_by: Optional[str]
    authorized_at: Optional[str]
    dissemination_deadline_at: Optional[str]
    dissemination_overdue: bool
    distribution_channels: Optional[List[str]]
    disseminated_at: Optional[str]
    closed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DailyCrimeLogEntry(TypedDict, total=False):
    id: str
    entry_number: str
    incident_id: str
    nature: str
    date_reported: str
    date_occurred: str
    general_location: Optional[str]
    disposition: str
    last_disposition_change_at: Optional[str]
    entry_overdue: bool
    disposition_update_overdue: bool
    is_public: bool
    created_at: str
    updated_at: str
    version: int


class LogInspectionRequest(TypedDict, total=False):
    id: str
    requester_name: str
    requester_contact: str
    from_date: str
    to_date: str
    requested_at: str
    due_at: str
    provisional_due_at: str
    fulfilled_at: Optional[str]
    is_overdue: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class AnnualSecurityReport(TypedDict, total=False):
    id: str
    report_year: int
    statistics_version: int
    compiled_at: Optional[str]
    final_compile_done: bool
    statistics_stale: bool
    amendment_started_at: Optional[str]
    published_at: Optional[str]
    is_late: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class StatisticLine(TypedDict, total=False):
    id: str
    report_id: str
    statistics_version: int
    compilation_variant: str
    offense_type: str
    geography_column: str
    count: int
    referred_persons_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FireIncident(TypedDict, total=False):
    id: str
    geography_id: str
    occurred_at: str
    cause_category: str
    injuries: int
    deaths: int
    estimated_damage_dollars: float
    adjudicated_damage_dollars: Optional[float]
    final_damage_dollars: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class FireSafetyReport(TypedDict, total=False):
    id: str
    report_year: int
    total_fires: int
    total_injuries: int
    total_deaths: int
    total_damage_dollars: int
    provisional_total_damage_dollars: float
    totals_stale: bool
    published_at: Optional[str]
    is_late: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgramReview(TypedDict, total=False):
    id: str
    scope_year_start: int
    scope_year_end: int
    opened_at: str
    penalty_score: int
    escalated: bool
    open_action_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CorrectiveAction(TypedDict, total=False):
    id: str
    review_id: str
    finding_code: str
    severity: str
    description: str
    due_date: str
    is_repeat_finding: bool
    weight: int
    resolution_summary: Optional[str]
    rejection_count: int
    verification_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
