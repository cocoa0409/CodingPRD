"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CARRIER_REP = "CarrierRep"
    DISPATCHER = "Dispatcher"
    ESCORT_OPERATOR = "EscortOperator"
    ROUTE_SURVEYOR = "RouteSurveyor"
    SAFETY_MANAGER = "SafetyManager"
    BILLING_CLERK = "BillingClerk"
    FINANCE_MANAGER = "FinanceManager"


class JobStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    BOOKED = "BOOKED"
    CLEARED = "CLEARED"
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    ON_HOLD = "ON_HOLD"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class LegStatus(str, Enum):
    PENDING = "PENDING"
    DETERMINED = "DETERMINED"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PermitStatus(str, Enum):
    APPLIED = "APPLIED"
    ISSUED = "ISSUED"
    EXPIRED = "EXPIRED"


class SurveyStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class AssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"


class DelayStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    ASSESSED = "ASSESSED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class EscortStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CancelFeeTier(str, Enum):
    NONE = "NONE"
    TIER_10 = "TIER_10"
    TIER_25 = "TIER_25"
    TIER_50 = "TIER_50"


class ClearanceVerdict(str, Enum):
    UNKNOWN = "UNKNOWN"
    PASS = "PASS"
    FAIL = "FAIL"


class ReleaseCause(str, Enum):
    DISPATCHER = "DISPATCHER"
    JOB_CANCELLED = "JOB_CANCELLED"
    ESCORT_SUSPENDED = "ESCORT_SUSPENDED"


class DelayCause(str, Enum):
    CARRIER_DELAY = "CARRIER_DELAY"
    MECHANICAL_BREAKDOWN = "MECHANICAL_BREAKDOWN"
    DOCUMENTATION_ISSUE = "DOCUMENTATION_ISSUE"
    WEATHER = "WEATHER"
    CURFEW_HOLD = "CURFEW_HOLD"
    POLICE_DIRECTED = "POLICE_DIRECTED"
    ROAD_CLOSURE = "ROAD_CLOSURE"


class IncidentType(str, Enum):
    CARGO_DAMAGE = "CARGO_DAMAGE"
    PROPERTY_DAMAGE = "PROPERTY_DAMAGE"
    TRAFFIC_VIOLATION = "TRAFFIC_VIOLATION"
    INJURY = "INJURY"
    EQUIPMENT_DAMAGE = "EQUIPMENT_DAMAGE"


class ObstructionType(str, Enum):
    BRIDGE = "BRIDGE"
    WIRE = "WIRE"
    SIGN = "SIGN"
    OTHER = "OTHER"


class Disposition(str, Enum):
    PASSABLE = "PASSABLE"
    PASSABLE_WITH_POLE = "PASSABLE_WITH_POLE"
    REQUIRES_REROUTE = "REQUIRES_REROUTE"


class Position(str, Enum):
    FRONT = "FRONT"
    REAR = "REAR"


class SurveyOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


# --- Entity TypedDicts (common_fields: true unless noted) ---


class Carrier(TypedDict, total=False):
    id: str
    carrier_name: str
    credit_limit_cents: int
    ytd_billed_cents: int
    credit_available_cents: int
    created_at: str
    updated_at: str
    version: int


class Escort(TypedDict, total=False):
    id: str
    operator_name: str
    certified_state_codes: List[str]
    has_height_pole: bool
    height_pole_max_inches: int
    reliability_score: int
    escort_status: str
    active_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class Job(TypedDict, total=False):
    id: str
    carrier_id: str
    load_description: str
    width_inches: int
    height_inches: int
    length_inches: int
    gross_weight_lbs: int
    window_start_at: str
    window_end_at: str
    job_status: str
    quoted_cents: Optional[int]
    quoted_at: Optional[str]
    quote_expires_at: Optional[str]
    booked_at: Optional[str]
    departed_at: Optional[str]
    delivered_at: Optional[str]
    cancelled_at: Optional[str]
    cancel_fee_cents: int
    cancel_fee_tier: Optional[str]
    total_escort_positions: int
    created_at: str
    updated_at: str
    version: int


class RouteLeg(TypedDict, total=False):
    id: str
    job_id: str
    state_code: str
    sequence_index: int
    distance_miles: int
    planned_entry_at: str
    planned_exit_at: str
    map_min_clearance_inches: int
    leg_status: str
    required_front_escorts: int
    required_rear_escorts: int
    requires_height_pole: bool
    requires_police_escort: bool
    requires_route_survey: bool
    police_confirmed: bool
    clearance_verdict: str
    survey_min_clearance_inches: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    leg_id: str
    permit_number: str
    valid_from: str
    valid_until: str
    holiday_closure_dates: List[str]
    permit_status: str
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RouteSurvey(TypedDict, total=False):
    id: str
    leg_id: str
    survey_status: str
    surveyed_min_clearance_inches: Optional[int]
    submitted_at: Optional[str]
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only (common_fields: false): carries ONLY id + created_at, no
# updated_at / version.
class Obstruction(TypedDict, total=False):
    id: str
    survey_id: str
    milepost: float
    obstruction_type: str
    measured_clearance_inches: int
    disposition: str
    created_at: str


class EscortAssignment(TypedDict, total=False):
    id: str
    leg_id: str
    escort_id: str
    position: str
    assignment_status: str
    offered_at: str
    accepted_at: Optional[str]
    activated_at: Optional[str]
    completed_at: Optional[str]
    released_at: Optional[str]
    release_cause: Optional[str]
    billable_hours: Optional[float]
    assignment_fee_cents: Optional[int]
    last_checkin_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DelayEvent(TypedDict, total=False):
    id: str
    job_id: str
    cause: str
    started_at: str
    ended_at: Optional[str]
    delay_status: str
    raw_minutes: Optional[int]
    billable_minutes: Optional[int]
    standby_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    job_id: str
    assignment_id: Optional[str]
    incident_type: str
    description: str
    claimed_amount_cents: int
    reporter_role: str
    reporter_user_id: str
    incident_status: str
    escort_fault_share_pct: Optional[int]
    assessed_amount_cents: Optional[int]
    escort_share_cents: Optional[int]
    assessed_by_user_id: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    job_id: str
    invoice_status: str
    base_charges_cents: int
    equipment_charges_cents: int
    standby_total_cents: int
    subtotal_cents: int
    volume_discount_cents: int
    fuel_surcharge_cents: int
    cancellation_fee_cents: int
    incident_chargebacks_cents: int
    adjustment_delta_cents: int
    total_cents: int
    generated_by_user_id: str
    finalized_at: Optional[str]
    dispute_reason: Optional[str]
    adjustment_note: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
