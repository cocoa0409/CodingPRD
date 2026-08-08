"""Domain types: status enums, role enum and entity shapes."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    CARE_NAVIGATOR = "CareNavigator"
    CLINICIAN = "Clinician"
    BILLING_SPECIALIST = "BillingSpecialist"


ALL_ROLES = [r.value for r in UserRole]


class ReferralStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class EpisodeStatus(str, Enum):
    INTAKE = "INTAKE"
    ACTIVE = "ACTIVE"
    SERVICE_PERIOD_CLOSED = "SERVICE_PERIOD_CLOSED"
    BILLED = "BILLED"
    CLOSED_READMITTED = "CLOSED_READMITTED"
    ADMIN_CLOSED = "ADMIN_CLOSED"


class RecordPosture(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"


class ContactStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCESSFUL = "SUCCESSFUL"
    REFUSED = "REFUSED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    SEVERE = "SEVERE"


class ContactAttemptStatus(str, Enum):
    LOGGED = "LOGGED"
    CONNECTED = "CONNECTED"
    NO_ANSWER = "NO_ANSWER"
    VOICEMAIL = "VOICEMAIL"
    REFUSED = "REFUSED"


class EncounterStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class DocumentationStatus(str, Enum):
    DRAFT = "DRAFT"
    ATTESTED = "ATTESTED"
    AMENDED = "AMENDED"


class ConfirmationStatus(str, Enum):
    UNCONFIRMED = "UNCONFIRMED"
    CONFIRMED = "CONFIRMED"


class DeadlineStatus(str, Enum):
    SCHEDULED_IN_WINDOW = "SCHEDULED_IN_WINDOW"
    SCHEDULED_LATE = "SCHEDULED_LATE"
    MET = "MET"
    MISSED = "MISSED"


class MedReconciliationStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    COMPLETED = "COMPLETED"


class DiscrepancyStatus(str, Enum):
    UNRESOLVED = "UNRESOLVED"
    RESOLVED = "RESOLVED"
    DEFERRED = "DEFERRED"


class BarrierStatus(str, Enum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"
    CLOSED_ADMINISTRATIVE = "CLOSED_ADMINISTRATIVE"


class RedFlagStatus(str, Enum):
    RAISED = "RAISED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    BREACHED = "BREACHED"
    CLOSED_ADMINISTRATIVE = "CLOSED_ADMINISTRATIVE"


class RedFlagTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class ReadmissionStatus(str, Enum):
    RECORDED = "RECORDED"
    RETRACTED = "RETRACTED"


class ClaimStatus(str, Enum):
    PREPARED = "PREPARED"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    DENIED_FINAL = "DENIED_FINAL"
    VOIDED = "VOIDED"


class HandoffStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class Patient(TypedDict):
    id: str
    external_mrn: str
    full_name: str
    date_of_birth: str
    primary_language: str
    open_episode_count: int
    lifetime_episode_count: int
    lifetime_readmission_count: int
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict):
    id: str
    name: str
    facility_type: str
    network_status: str
    created_at: str
    updated_at: str
    version: int


class Payer(TypedDict):
    id: str
    name: str
    tcm_covered: bool
    tcm_rate_multiplier: float
    coinsurance_rate: float
    contact_deadline_basis: str
    created_at: str
    updated_at: str
    version: int


class Navigator(TypedDict):
    id: str
    full_name: str
    active_episode_cap: int
    cap_policy: str
    active_episode_count: int
    workload_score: float
    availability_status: str
    created_at: str
    updated_at: str
    version: int


class DischargeReferral(TypedDict):
    id: str
    patient_id: str
    facility_id: str
    payer_id: str
    discharge_date: str
    discharge_datetime: str
    discharge_disposition: str
    stay_type: str
    length_of_stay_days: Optional[int]
    length_of_stay_hours: Optional[int]
    admission_acuity: str
    comorbidity_count: int
    prior_ed_visits_6mo: int
    prior_admissions_6mo: int
    social_risk_flags_count: int
    referred_at: str
    status: str
    closure_reason_code: Optional[str]
    created_episode_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CareEpisode(TypedDict):
    id: str
    referral_id: str
    patient_id: str
    payer_id: str
    facility_id: str
    navigator_id: str
    discharge_date: str
    discharge_datetime: str
    status: str
    record_posture: str
    pre_readmission_status: Optional[str]
    risk_score: int
    risk_tier: str
    current_risk_assessment_id: str
    contact_sla_business_days: int
    contact_deadline_at: str
    contact_status: str
    contact_attempt_count: int
    successful_contact_at: Optional[str]
    contact_timely: bool
    required_visit_complexity: str
    visit_due_date: str
    visit_completed_at: Optional[str]
    visit_timely: bool
    medrec_complete: bool
    service_period_end_date: str
    readmission_window_end_date: str
    readmission_event_count: int
    counted_readmission_count: int
    excluded_readmission_count: int
    retracted_readmission_count: int
    open_red_flag_count: int
    escalation_state: str
    billing_eligible: bool
    recoupment_required: bool
    claim_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RiskAssessment(TypedDict):
    id: str
    episode_id: str
    supersedes_id: Optional[str]
    stay_type: str
    length_of_stay_days: Optional[int]
    length_of_stay_hours: Optional[int]
    admission_acuity: str
    comorbidity_count: int
    prior_ed_visits_6mo: int
    prior_admissions_6mo: int
    social_risk_flags_count: int
    los_variant: str
    los_points: int
    acuity_points: int
    comorbidity_points: int
    utilization_points: int
    social_modifier_points: int
    risk_score: int
    risk_tier: str
    is_current: bool
    assessed_at: str
    created_at: str
    updated_at: str
    version: int


class ContactAttempt(TypedDict):
    id: str
    episode_id: str
    attempt_number: int
    modality: str
    attempt_status: str
    attempted_at: str
    disposition_at: Optional[str]
    notes: str
    created_at: str
    updated_at: str
    version: int


class TcmVisit(TypedDict):
    id: str
    episode_id: str
    navigator_id: str
    scheduled_start: str
    scheduled_end: str
    encounter_status: str
    documentation_status: str
    confirmation_status: str
    required_complexity: str
    achieved_complexity: Optional[str]
    visit_due_date: str
    deadline_status: str
    completed_at: Optional[str]
    documented_elements: List[str]
    attested_by_user_id: Optional[str]
    attested_at: Optional[str]
    amendment_count: int
    created_at: str
    updated_at: str
    version: int


class MedReconciliation(TypedDict):
    id: str
    episode_id: str
    status: str
    discrepancy_count: int
    resolved_count: int
    unresolved_count: int
    deferred_count: int
    blocking_unresolved_count: int
    completed_at: Optional[str]
    reopen_count: int
    performed_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class MedDiscrepancy(TypedDict):
    id: str
    med_reconciliation_id: str
    medication_name: str
    discrepancy_type: str
    severity: str
    status: str
    resolution_note: Optional[str]
    disposition_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Barrier(TypedDict):
    id: str
    episode_id: str
    barrier_type: str
    blocking_class: bool
    owner_role: str
    sla_hours: int
    opened_at: str
    sla_due_at: str
    status: str
    closed_at: Optional[str]
    description: str
    escalated_red_flag_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RedFlag(TypedDict):
    id: str
    episode_id: str
    source_barrier_id: Optional[str]
    category: str
    initial_tier: str
    tier: str
    promotion_count: int
    status: str
    raised_by_user_id: str
    raised_at: str
    ack_due_at: str
    acknowledged_by_user_id: Optional[str]
    acknowledged_at: Optional[str]
    resolution_outcome: Optional[str]
    spawned_readmission_id: Optional[str]
    ed_event_suppressed: bool
    created_at: str
    updated_at: str
    version: int


class ReadmissionEvent(TypedDict):
    id: str
    episode_id: str
    source_red_flag_id: Optional[str]
    readmission_date: str
    day_index: int
    classification: str
    counts_toward_rate: bool
    status: str
    retraction_reason: Optional[str]
    recorded_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class TcmClaim(TypedDict):
    id: str
    episode_id: str
    patient_id: str
    visit_id: str
    payer_id: str
    service_period_start_date: str
    service_period_end_date: str
    payable_code: str
    payable_variant: str
    base_rate_cents: int
    allowed_cents: int
    coinsurance_cents: int
    net_before_withhold_cents: int
    withhold_pct: float
    withhold_cents: int
    net_payable_cents: int
    status: str
    appeal_count: int
    denial_reason_code: Optional[str]
    prepared_by_user_id: str
    submitted_by_user_id: Optional[str]
    readmission_flagged: bool
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HandoffRequest(TypedDict):
    id: str
    episode_id: str
    from_navigator_id: str
    to_navigator_id: str
    handoff_type: str
    status: str
    proposed_at: str
    expires_at: str
    responded_at: Optional[str]
    decline_reason: Optional[str]
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
