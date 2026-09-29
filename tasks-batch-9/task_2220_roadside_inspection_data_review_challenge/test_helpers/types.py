"""TypedDict shapes and enum constants for the roadside inspection data review API.

Two record types (`ReportAmendment` and `ChallengeEvidence`) are append-only audit
rows: per PRD 2.5 they carry only `id` and `created_at`, so their TypedDicts omit
`updated_at` and `version`.
"""

from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
class Role:
    CARRIER_ANALYST = "CarrierAnalyst"
    CARRIER_SAFETY_MANAGER = "CarrierSafetyManager"
    STATE_INSPECTION_OFFICER = "StateInspectionOfficer"
    FMCSA_REVIEW_OFFICER = "FmcsaReviewOfficer"
    FMCSA_PROGRAM_AUDITOR = "FmcsaProgramAuditor"


ALL_ROLES = (
    Role.CARRIER_ANALYST,
    Role.CARRIER_SAFETY_MANAGER,
    Role.STATE_INSPECTION_OFFICER,
    Role.FMCSA_REVIEW_OFFICER,
    Role.FMCSA_PROGRAM_AUDITOR,
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class BasicCategory:
    UNSAFE_DRIVING = "UNSAFE_DRIVING"
    HOURS_OF_SERVICE = "HOURS_OF_SERVICE"
    VEHICLE_MAINTENANCE = "VEHICLE_MAINTENANCE"
    DRIVER_FITNESS = "DRIVER_FITNESS"


class CarrierSegment:
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class SafetyFitnessStatus:
    UNRATED = "UNRATED"
    SATISFACTORY = "SATISFACTORY"
    CONDITIONAL = "CONDITIONAL"
    UNSATISFACTORY = "UNSATISFACTORY"


class InterventionStatus:
    NONE = "NONE"
    WARNING_LETTER = "WARNING_LETTER"
    INVESTIGATION = "INVESTIGATION"


class SelectionBand:
    PASS = "PASS"
    OPTIONAL = "OPTIONAL"
    INSPECT = "INSPECT"


class EmploymentStatus:
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class SelectionSource:
    ISS_SCREENING = "ISS_SCREENING"
    RANDOM = "RANDOM"
    POST_CRASH = "POST_CRASH"
    COMPLAINT = "COMPLAINT"
    WEIGH_STATION = "WEIGH_STATION"


class ReportStatus:
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    SCORED = "SCORED"
    AMENDED = "AMENDED"
    RESCINDED = "RESCINDED"


class UnitType:
    VEHICLE = "VEHICLE"
    DRIVER = "DRIVER"


class ViolationStatus:
    ACTIVE = "ACTIVE"
    RECODED = "RECODED"
    REMOVED = "REMOVED"


class RemovalReason:
    CHALLENGE_ACCEPTED = "CHALLENGE_ACCEPTED"
    ADJUDICATION_DISMISSED = "ADJUDICATION_DISMISSED"
    DUPLICATE_RESCINDED = "DUPLICATE_RESCINDED"
    AMENDMENT_REMOVAL = "AMENDMENT_REMOVAL"


class AmendmentType:
    VIOLATION_CODE_CORRECTION = "VIOLATION_CODE_CORRECTION"
    DRIVER_ATTRIBUTION_CORRECTION = "DRIVER_ATTRIBUTION_CORRECTION"
    CARRIER_REATTRIBUTION = "CARRIER_REATTRIBUTION"
    VIOLATION_REMOVAL = "VIOLATION_REMOVAL"


class ChallengeType:
    WRONG_CARRIER = "WRONG_CARRIER"
    DUPLICATE_REPORT = "DUPLICATE_REPORT"
    INCORRECT_VIOLATION_CODE = "INCORRECT_VIOLATION_CODE"
    VIOLATION_NOT_SUPPORTED = "VIOLATION_NOT_SUPPORTED"


class ChallengeStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    RESOLVED_ACCEPTED = "RESOLVED_ACCEPTED"
    RESOLVED_REJECTED = "RESOLVED_REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ResolutionDisposition:
    REATTRIBUTED = "REATTRIBUTED"
    REPORT_RESCINDED = "REPORT_RESCINDED"
    CODE_CORRECTED = "CODE_CORRECTED"
    VIOLATION_REMOVED = "VIOLATION_REMOVED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NOT_SUBSTANTIATED = "NOT_SUBSTANTIATED"
    EXPIRED_NO_RESPONSE = "EXPIRED_NO_RESPONSE"


class ReviewAction:
    ASSIGN = "ASSIGN"
    REQUEST_INFO = "REQUEST_INFO"
    RESOLVE_ACCEPT = "RESOLVE_ACCEPT"
    RESOLVE_REJECT = "RESOLVE_REJECT"


class EvidenceType:
    BILL_OF_LADING = "BILL_OF_LADING"
    LEASE_AGREEMENT = "LEASE_AGREEMENT"
    GPS_LOG = "GPS_LOG"
    ELD_RECORD = "ELD_RECORD"
    PHOTO = "PHOTO"
    COURT_DOCUMENT = "COURT_DOCUMENT"
    OTHER = "OTHER"


class CourtStatus:
    PENDING = "PENDING"
    CONVICTED = "CONVICTED"
    DISMISSED = "DISMISSED"
    REDUCED = "REDUCED"
    NOT_GUILTY = "NOT_GUILTY"


class RecordUpdateStatus:
    NOT_APPLIED = "NOT_APPLIED"
    APPLIED = "APPLIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AlertStatus:
    CLEAR = "CLEAR"
    MONITOR = "MONITOR"
    ALERT = "ALERT"
    NOT_ENOUGH_DATA = "NOT_ENOUGH_DATA"


class CurriculumCode:
    UNSAFE_DRIVING_101 = "UNSAFE_DRIVING_101"
    HOS_ELD_REFRESH = "HOS_ELD_REFRESH"
    PRETRIP_INSPECTION = "PRETRIP_INSPECTION"
    CDL_COMPLIANCE = "CDL_COMPLIANCE"


class CoachingStatus:
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"
    WAIVED = "WAIVED"
    ESCALATED = "ESCALATED"


class WaivedReason:
    VIOLATION_REMOVED = "VIOLATION_REMOVED"
    SCORE_BELOW_TRIGGER = "SCORE_BELOW_TRIGGER"
    DRIVER_SEPARATED = "DRIVER_SEPARATED"
    ATTRIBUTION_CLEARED = "ATTRIBUTION_CLEARED"


class CapStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    PENDING_DECISION = "PENDING_DECISION"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"
    SUPERSEDED = "SUPERSEDED"


class CapReviewBranch:
    SAFETY = "SAFETY"
    DATA = "DATA"


class CapReviewOutcome:
    CLEARED = "CLEARED"
    DEFICIENT = "DEFICIENT"


class CapDecision:
    ACCEPT = "ACCEPT"
    RETURN = "RETURN"


class CapItemStatus:
    PROPOSED = "PROPOSED"
    COMMITTED = "COMMITTED"
    IMPLEMENTED = "IMPLEMENTED"
    VERIFIED = "VERIFIED"
    REJECTED_ITEM = "REJECTED_ITEM"


class CapItemAction:
    COMMIT = "COMMIT"
    IMPLEMENT = "IMPLEMENT"
    VERIFY = "VERIFY"
    REJECT = "REJECT"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------
class CommonRecord(TypedDict):
    """PRD 2.5: every record carries these four properties."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AuditRecord(TypedDict):
    """PRD 2.5: append-only audit rows carry only `id` and `created_at`."""

    id: str
    created_at: str


class Carrier(CommonRecord):
    dot_number: str
    legal_name: str
    average_power_units: int
    annual_vmt: int
    carrier_segment: str
    utilization_factor: float
    safety_fitness_status: str
    fitness_determined_at: Optional[str]
    fitness_determined_by_user_id: Optional[str]
    intervention_status: str
    open_alert_count: int
    max_percentile: Optional[float]
    oos_violation_count_24mo: int
    scored_violation_count: int
    unattributed_violation_count: int
    iss_pre_credit_value: float
    data_quality_credit_pct: float
    iss_value: float
    selection_band: str
    challenge_quota_used: int
    challenge_quota_limit: int
    accepted_challenge_count_24mo: int
    resolved_challenge_count_24mo: int
    open_coaching_count: int


class Driver(CommonRecord):
    carrier_id: str
    cdl_number: str
    full_name: str
    employment_status: str
    attributed_violation_count: int
    strict_attribution_score: float
    adjudicated_attribution_score: float
    coaching_required: bool
    open_coaching_count: int


class ViolationCode(CommonRecord):
    code: str
    description: str
    basic_category: str
    severity_weight: int
    oos_add_on: int
    driver_attributable: bool


class InterventionThreshold(CommonRecord):
    basic_category: str
    carrier_segment: str
    effective_from: str
    measure_at_p50: float
    measure_at_p65: float
    measure_at_p80: float
    intervention_percentile: float
    monitor_percentile: float
    investigation_percentile: float


class InspectionReport(CommonRecord):
    report_number: str
    inspection_state: str
    inspection_level: int
    inspection_start: str
    inspection_end: str
    vehicle_vin: str
    attributed_carrier_id: str
    original_carrier_id: Optional[str]
    driver_id: Optional[str]
    duplicate_master_report_id: Optional[str]
    selection_source: str
    iss_value_at_selection: Optional[float]
    selection_band_at_selection: Optional[str]
    status: str
    reattributed: bool
    active_violation_count: int
    total_time_weighted_severity: float
    scored_at: Optional[str]
    severity_basis_utc: Optional[str]


class Violation(CommonRecord):
    report_id: str
    violation_code_id: str
    effective_violation_code_id: str
    basic_category: str
    driver_id: Optional[str]
    attributed_carrier_id: str
    out_of_service: bool
    unit_type: str
    status: str
    removal_reason: Optional[str]
    under_challenge: bool
    code_weight_snapshot: Optional[int]
    oos_add_on_snapshot: Optional[int]
    pinned_violation_code_version: Optional[int]
    has_stale_code_pin: bool
    time_weight: int
    time_weighted_severity: float


class ReportAmendment(AuditRecord):
    """Append-only: no `updated_at`, no `version` (PRD 2.5)."""

    report_id: str
    amendment_type: str
    target_violation_id: Optional[str]
    corrected_violation_code_id: Optional[str]
    corrected_driver_id: Optional[str]
    corrected_carrier_id: Optional[str]
    source_challenge_id: Optional[str]
    rationale: str
    applied_at: str
    report_version_before: int
    report_version_after: int


class DataChallenge(CommonRecord):
    report_id: str
    carrier_id: str
    challenge_type: str
    target_violation_id: Optional[str]
    asserted_correct_carrier_id: Optional[str]
    duplicate_of_report_id: Optional[str]
    asserted_correct_violation_code_id: Optional[str]
    narrative: str
    status: str
    info_request_count: int
    info_response_deadline: Optional[str]
    submitted_at: Optional[str]
    resolved_at: Optional[str]
    resolution_disposition: Optional[str]
    resolved_by_user_id: Optional[str]
    evidence_count: int
    filing_age_days_at_submit: Optional[int]


class ChallengeEvidence(AuditRecord):
    """Append-only: no `updated_at`, no `version` (PRD 2.5)."""

    challenge_id: str
    evidence_type: str
    document_uri: str
    description: Optional[str]
    submitted_round: int


class CitationAdjudication(CommonRecord):
    violation_id: str
    citation_number: str
    court_date: str
    court_status: str
    record_update_status: str
    reduced_to_violation_code_id: Optional[str]
    severity_factor: float
    court_result_recorded_at: Optional[str]
    applied_at: Optional[str]
    applied_by_user_id: Optional[str]
    superseded: bool


class BasicScore(CommonRecord):
    carrier_id: str
    basic_category: str
    scoring_run_id: Optional[str]
    threshold_id: Optional[str]
    snapshot_utc: str
    total_time_weighted_severity: float
    challenged_time_weighted_severity: float
    included_violation_count: int
    relevant_inspection_count: int
    denominator_value: float
    provisional_measure: float
    certified_measure: float
    percentile: Optional[float]
    alert_status: str


class CoachingAssignment(CommonRecord):
    carrier_id: str
    driver_id: str
    violation_id: str
    curriculum_code: str
    session_start: str
    session_end: str
    due_at: str
    status: str
    started_at: Optional[str]
    completed_at: Optional[str]
    attestation_note: Optional[str]
    waived_reason: Optional[str]
    overdue_marked_run_id: Optional[str]


class CorrectiveActionPlan(CommonRecord):
    carrier_id: str
    superseded_cap_id: Optional[str]
    narrative: str
    status: str
    triggering_fitness_status: str
    safety_review_outcome: Optional[str]
    safety_review_user_id: Optional[str]
    data_review_outcome: Optional[str]
    data_review_user_id: Optional[str]
    item_count: int
    committed_item_count: int
    verified_item_count: int
    completion_pct: float
    decision: Optional[str]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]


class CapActionItem(CommonRecord):
    cap_id: str
    basic_category: str
    description: str
    target_completion_date: str
    status: str
    rejection_note: Optional[str]
    verified_by_user_id: Optional[str]


class ScoringRun(CommonRecord):
    snapshot_utc: str
    note: Optional[str]
    carriers_scored: int
    scores_updated: int
    challenges_expired: int
    coaching_marked_overdue: int
    coaching_waived: int
    status: str


class ScreeningRisk(TypedDict):
    """Computed read exposed by GET /carriers/{id}/screening-risk (PRD 3.5)."""

    carrier_id: str
    category_contributions: List[dict]
    oos_adder: float
    iss_pre_credit_value: float
    data_quality_credit_pct: float
    iss_value: float
    selection_band: str


class AttributionSummary(TypedDict):
    """Computed read exposed by GET /drivers/{id}/attribution-summary (PRD 3.9)."""

    driver_id: str
    attributed_violation_count: int
    strict_attribution_score: float
    adjudicated_attribution_score: float
    coaching_required: bool
    violations: List[dict]
