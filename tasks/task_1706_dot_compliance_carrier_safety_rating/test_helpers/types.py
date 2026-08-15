"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    SAFETY_ADMIN = "SafetyAdmin"
    SAFETY_DIRECTOR = "SafetyDirector"
    SAFETY_MANAGER = "SafetyManager"
    COMPLIANCE_ANALYST = "ComplianceAnalyst"
    MEDICAL_REVIEW_OFFICER = "MedicalReviewOfficer"
    INSURANCE_ANALYST = "InsuranceAnalyst"


class SafetyRating(str, Enum):
    NONE = "NONE"
    SATISFACTORY = "SATISFACTORY"
    CONDITIONAL = "CONDITIONAL"
    UNSATISFACTORY = "UNSATISFACTORY"


class NewEntrantStatus(str, Enum):
    NOT_NEW_ENTRANT = "NOT_NEW_ENTRANT"
    PENDING_AUDIT = "PENDING_AUDIT"
    PASSED = "PASSED"
    FAILED = "FAILED"


class CarrierPosture(str, Enum):
    NORMAL = "NORMAL"
    INTERVENTION_WATCH = "INTERVENTION_WATCH"
    INTERVENTION_PRIORITY = "INTERVENTION_PRIORITY"
    OUT_OF_SERVICE_PROPOSED = "OUT_OF_SERVICE_PROPOSED"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ReviewStatus(str, Enum):
    IMPORTED = "IMPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    FINALIZED = "FINALIZED"


class ViolationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CHALLENGED = "CHALLENGED"
    REMOVED = "REMOVED"


class ChallengeStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REMANDED = "REMANDED"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class CoachingStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    OVERDUE = "OVERDUE"
    ESCALATED = "ESCALATED"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class TestStatus(str, Enum):
    COLLECTED = "COLLECTED"
    LAB_REPORTED = "LAB_REPORTED"
    MRO_VERIFIED = "MRO_VERIFIED"
    CANCELLED = "CANCELLED"


class LabResult(str, Enum):
    PENDING = "PENDING"
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"
    REFUSAL = "REFUSAL"
    CANCELLED_BY_LAB = "CANCELLED_BY_LAB"


class MroVerdict(str, Enum):
    NONE = "NONE"
    VERIFIED_NEGATIVE = "VERIFIED_NEGATIVE"
    VERIFIED_POSITIVE = "VERIFIED_POSITIVE"
    VERIFIED_REFUSAL = "VERIFIED_REFUSAL"
    CANCELLED = "CANCELLED"


class PreventabilityStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    PREVENTABLE = "PREVENTABLE"
    NOT_PREVENTABLE = "NOT_PREVENTABLE"


class AuditCaseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    FIELD_WORK = "FIELD_WORK"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CORRECTIVE_ACTION_PHASE = "CORRECTIVE_ACTION_PHASE"
    CLOSED_PASSED = "CLOSED_PASSED"
    CLOSED_FAILED = "CLOSED_FAILED"


class UpgradeRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class PremiumModelStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    STALE = "STALE"
    BOUND = "BOUND"


class DocumentStatus(str, Enum):
    RETAINED = "RETAINED"
    PURGE_ELIGIBLE = "PURGE_ELIGIBLE"
    PURGED = "PURGED"


class PeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_COMPLIANT = "CLOSED_COMPLIANT"
    CLOSED_DEFICIENT = "CLOSED_DEFICIENT"


# --- Entity TypedDicts (common_fields: id, created_at, updated_at, version) ---


class Carrier(TypedDict, total=False):
    id: str
    dot_number: str
    legal_name: str
    fleet_size: int
    is_new_entrant: bool
    safety_audit_due_date: Optional[str]
    safety_rating: str
    new_entrant_status: str
    rating_cooling_off_until: Optional[str]
    posture: str
    last_cycle_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict, total=False):
    id: str
    carrier_id: str
    cdl_number: str
    full_name: str
    hire_date: str
    employment_status: str
    risk_score: int
    risk_tier: str
    coaching_strikes: int
    created_at: str
    updated_at: str
    version: int


class ViolationCategory(TypedDict, total=False):
    id: str
    category_code: str
    display_name: str
    intervention_threshold: int
    benchmark_measure: float
    measure_window_months: int
    created_at: str
    updated_at: str
    version: int


class RoadsideInspection(TypedDict, total=False):
    id: str
    carrier_id: str
    driver_id: str
    report_number: str
    inspection_date: str
    inspection_level: int
    state_code: str
    review_status: str
    total_weighted_points: int
    created_at: str
    updated_at: str
    version: int


class InspectionViolation(TypedDict, total=False):
    id: str
    inspection_id: str
    category_id: str
    driver_id: str
    violation_code: str
    severity_weight: int
    occurred_at: str
    time_weight_multiplier: int
    weighted_points: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DataQsChallenge(TypedDict, total=False):
    id: str
    violation_id: str
    reason_code: str
    evidence_note: str
    filed_by_user_id: str
    remand_count: int
    decided_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CoachingAssignment(TypedDict, total=False):
    id: str
    driver_id: str
    coaching_type: str
    source_violation_id: Optional[str]
    assigned_by_user_id: str
    due_date: str
    completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DrugAlcoholTest(TypedDict, total=False):
    id: str
    driver_id: str
    test_type: str
    substance: str
    collected_at: str
    accident_id: Optional[str]
    recorded_by_user_id: str
    lab_result: str
    mro_verdict: str
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AccidentRecord(TypedDict, total=False):
    id: str
    carrier_id: str
    driver_id: str
    occurred_at: str
    fatalities: int
    injuries: int
    tow_away: bool
    hazmat_release: bool
    dot_reportable: bool
    crash_points: int
    registered_by_user_id: str
    preventability_status: str
    preventability_determined_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceAuditCase(TypedDict, total=False):
    id: str
    carrier_id: str
    audit_type: str
    scheduled_date: str
    field_work_duration_days: int
    acute_count: Optional[int]
    critical_count: Optional[int]
    proposed_outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RatingUpgradeRequest(TypedDict, total=False):
    id: str
    carrier_id: str
    requested_rating: str
    justification_note: str
    decided_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InsurancePremiumModel(TypedDict, total=False):
    id: str
    carrier_id: str
    policy_period_start: str
    policy_period_end: str
    base_rate_cents_per_unit: int
    scenario: str
    assume_rating: Optional[str]
    assume_cleared_category_codes: Optional[list]
    assume_removed_preventable_accidents: Optional[int]
    rating_factor_used: float
    score_loading_pct: float
    crash_loading_pct: float
    driver_loading_pct: float
    computed_premium_cents: int
    carrier_version_at_compute: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DocumentRecord(TypedDict, total=False):
    id: str
    carrier_id: str
    driver_id: Optional[str]
    document_type: str
    filed_at: str
    retention_months: int
    retention_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RandomTestingPeriod(TypedDict, total=False):
    id: str
    carrier_id: str
    program_year: int
    avg_driver_count: int
    required_drug_tests: int
    required_alcohol_tests: int
    completed_drug_tests: int
    completed_alcohol_tests: int
    status: str
    created_at: str
    updated_at: str
    version: int


# MeasurementSnapshot is an immutable epoch artifact (PRD §2.4): it carries
# id and created_at only — updated_at and version are absent.
class MeasurementSnapshot(TypedDict, total=False):
    id: str
    carrier_id: str
    category_id: str
    cycle_date: str
    as_of: str
    official_measure: float
    provisional_measure: float
    official_percentile: int
    provisional_percentile: int
    alerted_official: bool
    alerted_provisional: bool
    created_at: str
