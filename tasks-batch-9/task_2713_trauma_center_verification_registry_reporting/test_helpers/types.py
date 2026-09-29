"""Entity shapes, enumerations and computed-read shapes for the Trauma Verification Registry API.

Every TypedDict below mirrors the resource the API returns in the ``data`` envelope
field, and every enumeration below lists exactly the members the contract declares.
"""

from typing import List, Optional, TypedDict

# ─── Roles ────────────────────────────────────────────────


class Role:
    """The seven recognised values of the ``X-User-Role`` header."""

    SYSTEM_ADMIN = "SystemAdmin"
    TRAUMA_PROGRAM_MANAGER = "TraumaProgramManager"
    REGISTRY_ABSTRACTOR = "RegistryAbstractor"
    REGISTRY_VALIDATOR = "RegistryValidator"
    TRAUMA_MEDICAL_DIRECTOR = "TraumaMedicalDirector"
    VERIFICATION_REVIEWER = "VerificationReviewer"
    STATE_DESIGNATION_OFFICER = "StateDesignationOfficer"


ALL_ROLES = [
    Role.SYSTEM_ADMIN,
    Role.TRAUMA_PROGRAM_MANAGER,
    Role.REGISTRY_ABSTRACTOR,
    Role.REGISTRY_VALIDATOR,
    Role.TRAUMA_MEDICAL_DIRECTOR,
    Role.VERIFICATION_REVIEWER,
    Role.STATE_DESIGNATION_OFFICER,
]


# ─── Center-level enumerations ────────────────────────────


class ReadinessPosture:
    READY = "READY"
    CONDITIONAL = "CONDITIONAL"
    AT_RISK = "AT_RISK"
    SUSPENDED = "SUSPENDED"


class NationalVerificationStatus:
    NOT_VERIFIED = "NOT_VERIFIED"
    VERIFIED = "VERIFIED"
    CONTINGENCY = "CONTINGENCY"
    SUSPENDED = "SUSPENDED"


class StateDesignationStatus:
    NOT_DESIGNATED = "NOT_DESIGNATED"
    DESIGNATED = "DESIGNATED"
    PROVISIONAL = "PROVISIONAL"
    WITHDRAWN = "WITHDRAWN"


class DesignationLevel:
    LEVEL_I = "LEVEL_I"
    LEVEL_II = "LEVEL_II"
    LEVEL_III = "LEVEL_III"


# ─── Activation tier and data dictionary enumerations ─────


class TierCode:
    TIER_1_FULL = "TIER_1_FULL"
    TIER_2_MODIFIED = "TIER_2_MODIFIED"
    TIER_3_CONSULT = "TIER_3_CONSULT"


class DictionaryFieldName:
    ISS_ABSTRACTED = "iss_abstracted"
    GCS_ARRIVAL = "gcs_arrival"
    MECHANISM_CODE = "mechanism_code"
    ED_DEPARTURE_AT = "ed_departure_at"


class RuleKind:
    REQUIRED = "REQUIRED"
    RANGE = "RANGE"
    CONFORMANCE = "CONFORMANCE"


class RuleSeverity:
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


# ─── Registry case enumerations ───────────────────────────


class AbstractionStatus:
    """The case's abstraction dimension."""

    PENDING = "PENDING"
    ABSTRACTED = "ABSTRACTED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    LOCKED = "LOCKED"


class TriageReviewStatus:
    """The case's triage dimension."""

    UNREVIEWED = "UNREVIEWED"
    UNDER_TRIAGE_CONFIRMED = "UNDER_TRIAGE_CONFIRMED"
    OVER_TRIAGE_CONFIRMED = "OVER_TRIAGE_CONFIRMED"
    APPROPRIATE = "APPROPRIATE"


class EdDisposition:
    ADMIT = "ADMIT"
    TRANSFER_OUT = "TRANSFER_OUT"
    DISCHARGE = "DISCHARGE"
    MORGUE = "MORGUE"


class InclusionStatus:
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"


class InclusionReason:
    MEETS_INCLUSION_CRITERIA = "MEETS_INCLUSION_CRITERIA"
    TRANSFER_OUT_MINOR_UNDER_24H = "TRANSFER_OUT_MINOR_UNDER_24H"
    BELOW_INJURY_THRESHOLD = "BELOW_INJURY_THRESHOLD"


class ValidationStatus:
    """The abstraction record's adjudication dimension."""

    SUBMITTED = "SUBMITTED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


SUPERSEDED_BY_RESUBMISSION = "SUPERSEDED_BY_RESUBMISSION"


# ─── Response log enumerations ────────────────────────────


class ResponderRole:
    SURGEON = "SURGEON"
    ANESTHESIA = "ANESTHESIA"
    NEUROSURGERY = "NEUROSURGERY"
    ORTHOPEDICS = "ORTHOPEDICS"
    RADIOLOGY = "RADIOLOGY"


class ComplianceStatus:
    COMPLIANT = "COMPLIANT"
    LATE = "LATE"
    UNDOCUMENTED = "UNDOCUMENTED"


# ─── PI event and corrective action enumerations ──────────


class PiEventType:
    UNDER_TRIAGE = "UNDER_TRIAGE"
    DELAYED_SURGEON = "DELAYED_SURGEON"
    DEFICIENCY_ESCALATION = "DEFICIENCY_ESCALATION"
    MORTALITY_REVIEW = "MORTALITY_REVIEW"
    TRANSFER_DELAY = "TRANSFER_DELAY"


class PiSeverity:
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class PiOrigin:
    MANUAL = "MANUAL"
    SYSTEM_AUTO = "SYSTEM_AUTO"


class PiStatus:
    IDENTIFIED = "IDENTIFIED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACTION_PLANNED = "ACTION_PLANNED"
    LOOP_CLOSED = "LOOP_CLOSED"
    REOPENED = "REOPENED"


OPEN_PI_STATUSES = [
    PiStatus.IDENTIFIED,
    PiStatus.UNDER_REVIEW,
    PiStatus.ACTION_PLANNED,
    PiStatus.REOPENED,
]


class ActionType:
    EDUCATION = "EDUCATION"
    PROTOCOL_CHANGE = "PROTOCOL_CHANGE"
    CREDENTIAL_ACTION = "CREDENTIAL_ACTION"
    EQUIPMENT = "EQUIPMENT"


class CompletionStatus:
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"


# ─── Verification cycle enumerations ──────────────────────


class CycleType:
    NATIONAL_VERIFICATION = "NATIONAL_VERIFICATION"
    STATE_DESIGNATION = "STATE_DESIGNATION"


class CycleStatus:
    PREP = "PREP"
    PREP_BLOCKED = "PREP_BLOCKED"
    SUBMITTED = "SUBMITTED"
    SITE_VISIT_SCHEDULED = "SITE_VISIT_SCHEDULED"
    UNDER_REVIEW = "UNDER_REVIEW"
    VERIFIED = "VERIFIED"
    CONTINGENCY = "CONTINGENCY"
    DENIED = "DENIED"


class Decision:
    VERIFIED = "VERIFIED"
    CONTINGENCY = "CONTINGENCY"
    DENIED = "DENIED"


class DeficiencyClass:
    TYPE_I_CRITICAL = "TYPE_I_CRITICAL"
    TYPE_II_MAJOR = "TYPE_II_MAJOR"
    TYPE_III_MINOR = "TYPE_III_MINOR"


class DeficiencyStatus:
    OPEN = "OPEN"
    REMEDIATION_SUBMITTED = "REMEDIATION_SUBMITTED"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class ReadinessVariant:
    """The two ways the readiness score is assembled.

    The reviewer variant is the default when no selector is supplied and the one that is
    persisted, so a test normally omits the parameter rather than naming it.
    """

    REVIEWER_ASSESSMENT = "REVIEWER_ASSESSMENT"
    SELF_ASSESSMENT = "SELF_ASSESSMENT"


class TriageRateVariant:
    PROVISIONAL_MONITORING = "PROVISIONAL_MONITORING"
    VERIFICATION_AUDIT = "VERIFICATION_AUDIT"


# ─── Outreach and referral enumerations ───────────────────


class ActivityKind:
    INJURY_PREVENTION = "INJURY_PREVENTION"
    PROFESSIONAL_EDUCATION = "PROFESSIONAL_EDUCATION"
    COMMUNITY_OUTREACH = "COMMUNITY_OUTREACH"


class VerifiedStatus:
    LOGGED = "LOGGED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class AgreementStatus:
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


# ─── Entity shapes ────────────────────────────────────────


class TraumaCenter(TypedDict):
    id: str
    name: str
    state_code: str
    designation_level: str
    verification_cycle_start_date: str
    readiness_posture: str
    national_verification_status: str
    state_designation_status: str
    registry_compliance_score: float
    outreach_credit_hours_ytd: float
    under_triage_rate_pct: float
    over_triage_rate_pct: float
    open_critical_deficiency_count: int
    escalated_critical_deficiency_count: int
    open_pi_event_count: int
    closed_pi_event_count: int
    registry_included_case_count: int
    registry_excluded_case_count: int
    created_at: str
    updated_at: str
    version: int


class ActivationCriteriaTier(TypedDict):
    id: str
    center_id: str
    tier_code: str
    surgeon_response_limit_minutes: int
    specialty_response_limit_minutes: int
    iss_threshold: int
    created_at: str
    updated_at: str
    version: int


class DataDictionaryRule(TypedDict):
    """Immutable configuration: it carries only ``id`` and ``created_at``.

    There is deliberately no ``updated_at`` and no ``version`` on this shape.
    """

    id: str
    field_name: str
    rule_kind: str
    severity: str
    min_value: Optional[int]
    max_value: Optional[int]
    allowed_codes: Optional[List[str]]
    error_weight: int
    created_at: str


class RegistryCase(TypedDict):
    id: str
    center_id: str
    activation_tier_id: str
    mrn: str
    arrival_at: str
    injury_severity_score: int
    los_hours: float
    ed_disposition: str
    transfer_in_from_center_id: Optional[str]
    transfer_out_to_center_id: Optional[str]
    abstraction_status: str
    triage_review_status: str
    effective_iss: int
    inclusion_status: str
    inclusion_reason: str
    locked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AbstractionRecord(TypedDict):
    id: str
    case_id: str
    iss_abstracted: Optional[int]
    gcs_arrival: Optional[int]
    mechanism_code: Optional[str]
    ed_departure_at: Optional[str]
    submitted_by_user_id: str
    validation_status: str
    validated_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    dictionary_error_count: int
    band_multiplier_used: float
    applied_penalty_points: float
    created_at: str
    updated_at: str
    version: int


class ResponseLog(TypedDict):
    id: str
    case_id: str
    responder_role: str
    responder_user_id: str
    notified_at: str
    arrived_at: Optional[str]
    response_minutes: Optional[float]
    applicable_limit_minutes: int
    compliance_status: str
    created_at: str
    updated_at: str
    version: int


class PIEvent(TypedDict):
    id: str
    center_id: str
    case_id: Optional[str]
    source_deficiency_id: Optional[str]
    event_type: str
    severity: str
    origin: str
    status: str
    opened_at: str
    loop_closure_due_at: str
    closed_at: Optional[str]
    review_round: int
    corrective_action_count: int
    verified_action_count: int
    created_at: str
    updated_at: str
    version: int


class CorrectiveAction(TypedDict):
    id: str
    pi_event_id: str
    action_type: str
    owner_user_id: str
    due_at: str
    completion_status: str
    completed_at: Optional[str]
    verified_at: Optional[str]
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VerificationCycle(TypedDict):
    id: str
    center_id: str
    cycle_type: str
    site_visit_date: str
    status: str
    readiness_score: float
    open_type_i_count: int
    open_type_ii_count: int
    open_type_iii_count: int
    decided_at: Optional[str]
    decision_effective_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CriteriaDeficiency(TypedDict):
    id: str
    verification_cycle_id: str
    criterion_code: str
    deficiency_class: str
    status: str
    remediation_due_at: str
    remediation_note: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutreachActivity(TypedDict):
    id: str
    center_id: str
    activity_kind: str
    event_date: str
    credit_hours: float
    audience_count: int
    weighted_credit_hours: float
    verified_status: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReferralAgreement(TypedDict):
    id: str
    referring_center_id: str
    receiving_center_id: str
    effective_from: str
    effective_to: str
    guaranteed_acceptance_minutes: int
    agreement_status: str
    activated_at: Optional[str]
    terminated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurveyorBooking(TypedDict):
    id: str
    verification_cycle_id: str
    surveyor_user_id: str
    window_start: str
    window_end: str
    travel_buffer_hours: int
    created_at: str
    updated_at: str
    version: int


# ─── Computed read shapes ─────────────────────────────────


class TriageRatesRead(TypedDict):
    variant: str
    denominator_case_count: int
    under_triage_numerator: int
    over_triage_numerator: int
    under_triage_rate_pct: float
    over_triage_rate_pct: float


class ReadinessRead(TypedDict):
    variant: str
    base_score: float
    deficiency_penalty: float
    outreach_penalty: float
    pi_penalty: float
    readiness_score: float
    submit_eligible: bool
