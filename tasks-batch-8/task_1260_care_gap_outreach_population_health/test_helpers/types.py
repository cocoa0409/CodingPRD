"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    PANEL_MANAGER = "PanelManager"
    QUALITY_REVIEWER = "QualityReviewer"
    TRANSPORTATION_COORDINATOR = "TransportationCoordinator"
    DATA_RECONCILIATION_BOT = "DataReconciliationBot"


class RegistryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class MeasureStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class MeasureDomain(str, Enum):
    SCREENING = "SCREENING"
    MED_ADHERENCE = "MED_ADHERENCE"


class CohortStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RiskTierFilter(str, Enum):
    ANY = "ANY"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    DISENROLLED = "DISENROLLED"
    DECEASED = "DECEASED"


class PanelStatus(str, Enum):
    BUILDING = "BUILDING"
    ACTIVE = "ACTIVE"
    REBUILDING = "REBUILDING"
    RETIRED = "RETIRED"


class CareGapStatus(str, Enum):
    OPEN = "OPEN"
    OUTREACH_IN_PROGRESS = "OUTREACH_IN_PROGRESS"
    AWAITING_APPOINTMENT = "AWAITING_APPOINTMENT"
    PENDING_EVIDENCE = "PENDING_EVIDENCE"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    EXCLUDED = "EXCLUDED"
    EXPIRED = "EXPIRED"


class PriorityBand(str, Enum):
    P1_URGENT = "P1_URGENT"
    P2_HIGH = "P2_HIGH"
    P3_ROUTINE = "P3_ROUTINE"
    P4_LOW = "P4_LOW"


class ClosureSource(str, Enum):
    EVIDENCE = "EVIDENCE"
    APPOINTMENT_COMPLETED = "APPOINTMENT_COMPLETED"
    CLAIMS_FEED = "CLAIMS_FEED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Channel(str, Enum):
    CALL = "CALL"
    TEXT = "TEXT"
    MAIL = "MAIL"


class AttemptOutcome(str, Enum):
    CONTACTED = "CONTACTED"
    LEFT_MESSAGE = "LEFT_MESSAGE"
    NO_ANSWER = "NO_ANSWER"
    BAD_ADDRESS = "BAD_ADDRESS"
    REFUSED = "REFUSED"
    REVERSED = "REVERSED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class TransportStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ARRANGED = "ARRANGED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EvidenceType(str, Enum):
    CHART_REVIEW = "CHART_REVIEW"
    CLAIMS_FEED = "CLAIMS_FEED"
    MEMBER_ATTESTATION = "MEMBER_ATTESTATION"
    LAB_RESULT = "LAB_RESULT"


class EvidenceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ExclusionKind(str, Enum):
    MEDICAL_CONTRAINDICATION = "MEDICAL_CONTRAINDICATION"
    MEMBER_REFUSAL = "MEMBER_REFUSAL"
    HOSPICE = "HOSPICE"
    DECEASED = "DECEASED"


class ExclusionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class PayoutStatus(str, Enum):
    PROJECTED = "PROJECTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    VOID = "VOID"


class ReportVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


# --- Entity TypedDicts (common_fields: true -> id, created_at, updated_at, version) ---


class PopulationRegistry(TypedDict, total=False):
    id: str
    name: str
    description: Optional[str]
    program_year: int
    current_business_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MeasureDefinition(TypedDict, total=False):
    id: str
    registry_id: str
    measure_code: str
    measure_domain: str
    lookback_days: int
    exclusion_window_days: int
    reporting_lag_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CohortDefinition(TypedDict, total=False):
    id: str
    registry_id: str
    cohort_code: str
    min_age: int
    max_age: int
    risk_tier_filter: str
    requires_active_enrollment: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    registry_id: str
    mrn: str
    date_of_birth: str
    risk_tier: str
    phone_ok: bool
    mail_ok: bool
    enrollment_status: str
    open_gap_count: int
    created_at: str
    updated_at: str
    version: int


class RegistryPanel(TypedDict, total=False):
    id: str
    registry_id: str
    cohort_id: str
    measure_id: str
    panel_manager_id: str
    member_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CareGap(TypedDict, total=False):
    id: str
    panel_id: str
    member_id: str
    measure_id: str
    last_qualifying_event_at: Optional[str]
    due_date: str
    days_overdue: int
    priority_score: int
    priority_band: str
    attempt_count: int
    next_eligible_attempt_at: Optional[str]
    status: str
    closure_source: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutreachCampaign(TypedDict, total=False):
    id: str
    registry_id: str
    panel_id: str
    measure_id: str
    name: str
    channel: str
    quiet_hours_start_min: int
    quiet_hours_end_min: int
    min_attempt_interval_hours: int
    max_attempts_per_member: int
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only ledger entry: id + created_at only (PRD §2.4)
class OutreachAttempt(TypedDict, total=False):
    id: str
    care_gap_id: str
    campaign_id: str
    member_id: str
    channel: str
    attempted_at: str
    outcome: str
    notes: Optional[str]
    reversal_reason: Optional[str]
    created_at: str


class Appointment(TypedDict, total=False):
    id: str
    care_gap_id: str
    member_id: str
    provider_id: str
    slot_start_at: str
    slot_end_at: str
    provider_capacity_per_slot: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TransportationAssist(TypedDict, total=False):
    id: str
    appointment_id: str
    member_id: str
    vendor: str
    pickup_at: str
    cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GapClosureEvidence(TypedDict, total=False):
    id: str
    care_gap_id: str
    member_id: str
    evidence_type: str
    service_date: str
    document_uri: str
    submitted_by_role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ExclusionRequest(TypedDict, total=False):
    id: str
    member_id: str
    measure_id: Optional[str]
    exclusion_kind: str
    justification: str
    effective_from: str
    effective_until: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PanelManagerWorkload(TypedDict, total=False):
    id: str
    registry_id: str
    panel_manager_id: str
    assigned_member_count: int
    closed_gap_count_period: int
    utilization_ratio: float
    period_key: str
    created_at: str
    updated_at: str
    version: int


class IncentivePayout(TypedDict, total=False):
    id: str
    workload_id: str
    panel_manager_id: str
    period_key: str
    base_amount_cents: int
    tier_multiplier_bps: int
    quality_bonus_cents: int
    total_payout_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MeasurePerformanceReport(TypedDict, total=False):
    id: str
    measure_id: str
    registry_id: str
    period_key: str
    denominator_count: int
    numerator_count: int
    closure_rate_bps: Optional[int]
    variant: str
    reconciled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
