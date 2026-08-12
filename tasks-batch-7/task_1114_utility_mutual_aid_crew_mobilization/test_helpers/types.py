"""Domain types: entity TypedDicts, status enums, role enum.

Every resource in this API carries id, created_at, updated_at, and version
(PRD: "Common Resource Properties").
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    HOST_COORDINATOR = "HostCoordinator"
    RESPONDING_COORDINATOR = "RespondingCoordinator"
    CREW_SUPERVISOR = "CrewSupervisor"
    HOST_SAFETY_OFFICER = "HostSafetyOfficer"
    HOST_FINANCE = "HostFinance"
    RESPONDING_FINANCE = "RespondingFinance"


class RoleCapability(str, Enum):
    HOST = "HOST"
    RESPONDING = "RESPONDING"
    BOTH = "BOTH"


class EventType(str, Enum):
    STORM = "STORM"
    WILDFIRE = "WILDFIRE"
    ICE = "ICE"
    FLOOD = "FLOOD"


class EventStatus(str, Enum):
    OPEN = "OPEN"
    ACTIVE = "ACTIVE"
    DEMOBILIZING = "DEMOBILIZING"
    CLOSED = "CLOSED"


class IntakePosture(str, Enum):
    ACCEPTING = "ACCEPTING"
    RESTRICTED = "RESTRICTED"
    SEALED = "SEALED"


class ScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class PerDiemMethod(str, Enum):
    STANDARD = "STANDARD"
    ACTUAL = "ACTUAL"


class RequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"
    IN_PROGRESS = "IN_PROGRESS"
    FULFILLED = "FULFILLED"
    RELEASED = "RELEASED"
    CLOSED = "CLOSED"


class CrewType(str, Enum):
    LINE = "LINE"
    TREE = "TREE"
    DAMAGE_ASSESS = "DAMAGE_ASSESS"
    SUBSTATION = "SUBSTATION"
    SUPPORT = "SUPPORT"


class MobilityStatus(str, Enum):
    COMMITTED = "COMMITTED"
    ARRIVED = "ARRIVED"
    DEMOBILIZING = "DEMOBILIZING"
    RETURNED = "RETURNED"
    WITHDRAWN = "WITHDRAWN"


class ReadinessStatus(str, Enum):
    AWAITING_BRIEFING = "AWAITING_BRIEFING"
    BRIEFED = "BRIEFED"
    CLEARED_TO_WORK = "CLEARED_TO_WORK"
    SAFETY_HOLD = "SAFETY_HOLD"
    RELEASED = "RELEASED"


class BriefingStatus(str, Enum):
    CONDUCTED = "CONDUCTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class DayClassification(str, Enum):
    TRAVEL = "TRAVEL"
    WORK = "WORK"
    STANDBY = "STANDBY"
    REST = "REST"


class TimeSheetStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"
    HELD = "HELD"


class LodgingAssignmentStatus(str, Enum):
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"


class DayFactorType(str, Enum):
    FULL = "FULL"
    TRAVEL = "TRAVEL"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    HELD = "HELD"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    VOID = "VOID"
    DISPUTED = "DISPUTED"
    CREDIT_PROPOSED = "CREDIT_PROPOSED"
    ESCALATED = "ESCALATED"


class DisputeReason(str, Enum):
    RATE_MISMATCH = "RATE_MISMATCH"
    HOURS_MISMATCH = "HOURS_MISMATCH"
    PER_DIEM_MISMATCH = "PER_DIEM_MISMATCH"
    DUPLICATE = "DUPLICATE"
    OTHER = "OTHER"


class ReportStatus(str, Enum):
    DRAFTING = "DRAFTING"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"


class UtilityCompany(TypedDict, total=False):
    id: str
    name: str
    company_code: str
    role_capability: str
    home_region: str
    created_at: str
    updated_at: str
    version: int


class MutualAidEvent(TypedDict, total=False):
    id: str
    event_name: str
    host_utility_id: str
    event_type: str
    declared_start_date: str
    premium_window_start: str
    premium_window_end: str
    mobilization_deadline: str
    status: str
    demobilized_at: Optional[str]
    open_request_count: int
    total_certified_direct_cents: int
    total_invoiced_cents: int
    total_paid_cents: int
    intake_posture: str
    created_at: str
    updated_at: str
    version: int


class BillingRateSchedule(TypedDict, total=False):
    id: str
    event_id: str
    responding_utility_id: str
    supersedes_schedule_id: Optional[str]
    effective_start_date: str
    effective_end_date: str
    rate_lines: List[dict]
    ot_multiplier_bps: int
    dt_multiplier_bps: int
    ot_threshold_minutes: int
    dt_threshold_minutes: int
    storm_premium_bps: int
    per_diem_rate_cents: int
    per_diem_method: str
    mobilization_fee_tiers: List[dict]
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssistanceRequest(TypedDict, total=False):
    id: str
    event_id: str
    responding_utility_id: str
    requested_crews: List[dict]
    required_minimum_crews: int
    earliest_start_date: str
    latest_end_date: str
    status: str
    amendment_round: int
    counter_terms: Optional[dict]
    committed_crew_count: int
    deployable_crew_count: int
    certified_direct_cents: int
    invoiced_total_cents: int
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict, total=False):
    id: str
    request_id: str
    owning_utility_id: str
    crew_type: str
    home_base: str
    roster: List[dict]
    roster_size: int
    equipment_units: List[dict]
    equipment_daily_total_cents: int
    mobility_status: str
    readiness_status: str
    last_suspended_at: Optional[str]
    arrived_at: Optional[str]
    released_at: Optional[str]
    returned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SafetyBriefing(TypedDict, total=False):
    id: str
    crew_id: str
    event_id: str
    conductor_operator_ref: str
    host_rules_version: str
    topics: List[str]
    conducted_at: str
    supervisor_operator_ref: Optional[str]
    acknowledged_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TimeSheet(TypedDict, total=False):
    id: str
    crew_id: str
    work_date: str
    day_classification: str
    reported_work_minutes: int
    reported_travel_minutes: int
    submitted_by_operator_ref: Optional[str]
    certified_by_operator_ref: Optional[str]
    certified_schedule_id: Optional[str]
    certified_amount_cents: Optional[int]
    billed_invoice_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LodgingBlock(TypedDict, total=False):
    id: str
    event_id: str
    hotel_name: str
    block_code: str
    total_rooms: int
    nightly_rate_cents: int
    assigned_rooms: int
    created_at: str
    updated_at: str
    version: int


class LodgingAssignment(TypedDict, total=False):
    id: str
    block_id: str
    crew_id: str
    room_count: int
    check_in_date: str
    check_out_date: str
    actual_check_out_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PerDiemClaim(TypedDict, total=False):
    id: str
    crew_id: str
    claim_date: str
    member_count: int
    meals_provided_count: int
    day_factor_type: str
    receipts_total_cents: Optional[int]
    method_applied: str
    lodging_covered: bool
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    request_id: str
    rate_schedule_id: str
    billing_period_start: str
    billing_period_end: str
    provisional_subtotal_cents: int
    provisional_fee_cents: int
    provisional_total_cents: int
    labor_subtotal_cents: Optional[int]
    per_diem_subtotal_cents: Optional[int]
    mobilization_fee_cents: Optional[int]
    final_total_cents: Optional[int]
    dispute_reason: Optional[str]
    disputed_amount_cents: Optional[int]
    proposed_credit_cents: Optional[int]
    applied_credit_total_cents: int
    amount_paid_cents: int
    outstanding_cents: int
    approved_by_operator_ref: Optional[str]
    status: str
    submitted_at: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AfterActionReport(TypedDict, total=False):
    id: str
    event_id: str
    summary: str
    lessons_learned: Optional[str]
    total_crew_days: int
    as_certified_total_cents: int
    as_billed_total_cents: int
    variance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
