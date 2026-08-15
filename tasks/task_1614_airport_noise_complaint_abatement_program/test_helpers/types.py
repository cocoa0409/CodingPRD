"""Domain types: entity TypedDicts, status enums, role enum (PRD 2.1, 2.5, 3.x)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    NOISE_OFFICE_ADMIN = "NoiseOfficeAdmin"
    NOISE_ANALYST = "NoiseAnalyst"
    COMMUNITY_LIAISON = "CommunityLiaison"
    STUDY_COORDINATOR = "StudyCoordinator"
    BOARD_MEMBER = "BoardMember"
    OPERATOR_REP = "OperatorRep"
    COMPLAINANT = "Complainant"


class ComplainantStanding(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    REPEAT = "REPEAT"
    RESTRICTED = "RESTRICTED"


class ComplaintStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    AWAITING_COMPLAINANT = "AWAITING_COMPLAINANT"
    CORRELATED = "CORRELATED"
    CLOSED_SUBSTANTIATED = "CLOSED_SUBSTANTIATED"
    CLOSED_UNSUBSTANTIATED = "CLOSED_UNSUBSTANTIATED"
    REOPENED = "REOPENED"
    WITHDRAWN = "WITHDRAWN"


class FlightStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPERATED = "OPERATED"
    CANCELLED = "CANCELLED"
    DIVERTED = "DIVERTED"


class OperatorStanding(str, Enum):
    GOOD = "GOOD"
    WATCH = "WATCH"
    PROBATION = "PROBATION"


class MonitorStatus(str, Enum):
    ONLINE = "ONLINE"
    DECOMMISSIONED = "DECOMMISSIONED"


class EventStatus(str, Enum):
    CAPTURED = "CAPTURED"
    SCREENING = "SCREENING"
    CLASSIFIED_AIRCRAFT = "CLASSIFIED_AIRCRAFT"
    CLASSIFIED_COMMUNITY = "CLASSIFIED_COMMUNITY"
    CLASSIFIED_MIXED = "CLASSIFIED_MIXED"
    VERIFIED = "VERIFIED"
    DISCARDED = "DISCARDED"


class CurfewRuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class NotificationStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESPONSE_RECEIVED = "RESPONSE_RECEIVED"
    CLOSED = "CLOSED"
    ESCALATED = "ESCALATED"
    AUTO_CLOSED = "AUTO_CLOSED"


class StudyStatus(str, Enum):
    SCOPING = "SCOPING"
    DATA_COLLECTION = "DATA_COLLECTION"
    DRAFTED = "DRAFTED"
    PUBLIC_REVIEW = "PUBLIC_REVIEW"
    ADOPTED = "ADOPTED"
    SUPERSEDED = "SUPERSEDED"


class ApplicationEligibility(str, Enum):
    NEW = "NEW"
    SUBMITTED = "SUBMITTED"
    SCREENING = "SCREENING"
    ELIGIBLE_TIER1 = "ELIGIBLE_TIER1"
    ELIGIBLE_TIER2 = "ELIGIBLE_TIER2"
    INELIGIBLE = "INELIGIBLE"
    APPEALED = "APPEALED"
    WITHDRAWN = "WITHDRAWN"


class ApplicationFunding(str, Enum):
    UNFUNDED = "UNFUNDED"
    OFFER_ISSUED = "OFFER_ISSUED"
    OFFER_DECLINED = "OFFER_DECLINED"
    GRANT_COMMITTED = "GRANT_COMMITTED"
    REIMBURSED = "REIMBURSED"


class FundStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class OutreachStatus(str, Enum):
    OPEN = "OPEN"
    CONTACT_ATTEMPTED = "CONTACT_ATTEMPTED"
    ENGAGED = "ENGAGED"
    RESOLVED = "RESOLVED"
    DORMANT = "DORMANT"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"


class Complainant(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    phone: Optional[str]
    address_line: str
    zone_code: str
    outreach_opt_in: bool
    standing: str
    complaints_90d: int
    filed_total: int
    open_count: int
    closed_count: int
    withdrawn_count: int
    substantiated_count: int
    repeat_baseline_at: Optional[str]
    low_priority_flag: bool
    created_at: str
    updated_at: str
    version: int


class NoiseComplaint(TypedDict, total=False):
    id: str
    complainant_id: str
    occurred_at: str
    channel: str
    disturbance_type: str
    narrative: Optional[str]
    status: str
    correlated_flight_id: Optional[str]
    correlated_event_id: Optional[str]
    correlation_confidence: float
    correlation_variant_used: str
    substantiation_eligible: bool
    closure_outcome: Optional[str]
    closed_at: Optional[str]
    reopen_count: int
    info_request_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FlightOperation(TypedDict, total=False):
    id: str
    flight_number: str
    operator_id: str
    aircraft_type: str
    engine_class: str
    operation_type: str
    runway_code: str
    scheduled_at: str
    actual_at: Optional[str]
    status: str
    exemption_code: str
    zone_code: str
    linked_complaint_count: int
    linked_event_count: int
    curfew_movement: bool
    curfew_violation: bool
    created_at: str
    updated_at: str
    version: int


class Operator(TypedDict, total=False):
    id: str
    name: str
    iata_code: str
    contact_email: str
    compliance_standing: str
    curfew_grace_minutes: int
    compliance_score_latest: Optional[float]
    on_time_responses_90d: int
    notifications_sent_total: int
    notifications_open: int
    notifications_closed: int
    notifications_draft: int
    created_at: str
    updated_at: str
    version: int


class NoiseMonitor(TypedDict, total=False):
    id: str
    station_code: str
    zone_code: str
    latitude: float
    longitude: float
    commissioned_at: str
    status: str
    uptime_pct_30d: float
    events_captured_total: int
    created_at: str
    updated_at: str
    version: int


class NoiseEvent(TypedDict, total=False):
    id: str
    monitor_id: str
    started_at: str
    duration_seconds: int
    lmax_db: float
    sel_db: float
    status: str
    flight_id: Optional[str]
    classification_basis: Optional[str]
    classification_confidence: float
    reclassify_count: int
    exceeds_threshold: bool
    quarter_key: str
    created_at: str
    updated_at: str
    version: int


class MonitorOutage(TypedDict, total=False):
    # Append-only record: carries ONLY id + created_at (PRD 2.5), no updated_at/version.
    id: str
    monitor_id: str
    start_at: str
    end_at: str
    outage_type: str
    reason: Optional[str]
    created_at: str


class CurfewRule(TypedDict, total=False):
    id: str
    runway_code: str
    season: str
    window_start_minute: int
    window_end_minute: int
    applies_to: str
    grace_minutes: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OperatorNotification(TypedDict, total=False):
    id: str
    operator_id: str
    complaint_id: Optional[str]
    noise_event_id: Optional[str]
    severity: str
    subject: str
    body: str
    status: str
    sent_at: Optional[str]
    due_at: Optional[str]
    acknowledged_at: Optional[str]
    responded_at: Optional[str]
    closed_at: Optional[str]
    response_text: Optional[str]
    escalation_reason: Optional[str]
    closed_outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NoiseStudy(TypedDict, total=False):
    id: str
    title: str
    baseline_year: int
    description: Optional[str]
    supersedes_study_id: Optional[str]
    status: str
    adopted_at: Optional[str]
    revision_count: int
    parcels_assessed_count: int
    created_at: str
    updated_at: str
    version: int


class LandUseParcel(TypedDict, total=False):
    id: str
    study_id: str
    parcel_ref: str
    land_use: str
    dnl_db_measured: float
    dnl_db_modeled: float
    zone_code: str
    dnl_db_effective: float
    dnl_band: int
    compatibility_status: str
    insulation_eligible: bool
    reassessed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SoundInsulationApplication(TypedDict, total=False):
    id: str
    parcel_id: str
    complainant_id: Optional[str]
    dwelling_type: str
    rooms_count: int
    est_cost_cents: int
    actual_cost_cents: Optional[int]
    eligibility_status: str
    funding_status: str
    fund_id: Optional[str]
    priority_score: int
    tier_cap_cents: int
    offered_amount_cents: Optional[int]
    offer_issued_at: Optional[str]
    offer_expires_at: Optional[str]
    last_offer_expired_at: Optional[str]
    disbursed_cents: Optional[int]
    appeal_count: int
    submitted_at: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InsulationFund(TypedDict, total=False):
    id: str
    fiscal_year: str
    total_allocation_cents: int
    intake_opens_at: str
    intake_closes_at: str
    status: str
    available_cents: int
    reserved_cents: int
    disbursed_cents: int
    projected_pipeline_cents: int
    created_at: str
    updated_at: str
    version: int


class OutreachCase(TypedDict, total=False):
    id: str
    complainant_id: str
    trigger_reason: str
    status: str
    contact_attempts: int
    opened_at: str
    resolved_at: Optional[str]
    resolution_summary: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QuarterlyReport(TypedDict, total=False):
    id: str
    quarter_label: str
    period_start: str
    period_end: str
    status: str
    notes: Optional[str]
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    published_at: Optional[str]
    revision_round_count: int
    complaints_received_count: int
    complaints_substantiated_count: int
    distinct_complainants_count: int
    events_aircraft_count: int
    events_community_count: int
    events_mixed_count: int
    curfew_movements_count: int
    curfew_violations_count: int
    avg_operator_compliance_score: float
    created_at: str
    updated_at: str
    version: int
