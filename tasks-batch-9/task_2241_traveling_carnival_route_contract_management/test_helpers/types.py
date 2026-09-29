"""Domain types for the Traveling Carnival Route Ops API.

Entity TypedDicts, lifecycle status enums, input enums and the role enum, all
named exactly as the PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Caller identity ──────────────────────────────────────────────────────────

class UserRole(str, Enum):
    """The ten recognized roles of PRD §2.1."""

    PLATFORM_ADMIN = "PlatformAdmin"
    ROUTE_MANAGER = "RouteManager"
    CONTRACT_NEGOTIATOR = "ContractNegotiator"
    GENERAL_MANAGER = "GeneralManager"
    LOT_BOSS = "LotBoss"
    SAFETY_OFFICER = "SafetyOfficer"
    COMPLIANCE_CLERK = "ComplianceClerk"
    JURISDICTION_OFFICER = "JurisdictionOfficer"
    TICKETING_AUDITOR = "TicketingAuditor"
    CREW_CHIEF = "CrewChief"


# ─── Lifecycle status enums ───────────────────────────────────────────────────

class RouteStatus(str, Enum):
    DRAFT = "DRAFT"
    SEQUENCED = "SEQUENCED"
    COMMITTED = "COMMITTED"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"


class RouteStopStatus(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    SETUP = "SETUP"
    OPEN = "OPEN"
    TEARDOWN = "TEARDOWN"
    CLOSED = "CLOSED"
    DARK = "DARK"


class CompliancePosture(str, Enum):
    CLEAR = "CLEAR"
    PERMIT_HOLD = "PERMIT_HOLD"
    INSPECTION_HOLD = "INSPECTION_HOLD"
    LABOR_HOLD = "LABOR_HOLD"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    COUNTERED = "COUNTERED"
    EXECUTED = "EXECUTED"
    TERMINATED = "TERMINATED"
    VOID = "VOID"


class RideStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class RideAllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    INSPECTION_HELD = "INSPECTION_HELD"
    OPERATING = "OPERATING"
    STRUCK = "STRUCK"
    RELEASED = "RELEASED"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class CrewAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"


class SettlementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"
    FINAL = "FINAL"


class SettlementVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class WeatherClosureStatus(str, Enum):
    LOGGED = "LOGGED"
    ADJUDICATED = "ADJUDICATED"


class MakeGoodStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class WorkerComplianceStatus(str, Enum):
    CLEAR = "CLEAR"
    VISA_LAPSED = "VISA_LAPSED"
    VISA_EXPIRING = "VISA_EXPIRING"


# ─── Input enums ──────────────────────────────────────────────────────────────

class LotSurface(str, Enum):
    PAVED = "PAVED"
    GRAVEL = "GRAVEL"
    GRASS = "GRASS"


class RideClass(str, Enum):
    MAJOR = "MAJOR"
    FLAT = "FLAT"
    KIDDIE = "KIDDIE"


class Exclusivity(str, Enum):
    NONE = "NONE"
    RIDES = "RIDES"
    FOOD = "FOOD"
    FULL = "FULL"


class SettlementBasis(str, Enum):
    GREATER_OF = "GREATER_OF"
    SPLIT_ONLY = "SPLIT_ONLY"


class PermitType(str, Enum):
    EVENT = "EVENT"
    TRANSPORT = "TRANSPORT"
    ELECTRICAL = "ELECTRICAL"
    HOUSING = "HOUSING"


class PermitDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class InspectionAuthority(str, Enum):
    STATE = "STATE"
    THIRD_PARTY = "THIRD_PARTY"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class EmploymentType(str, Enum):
    PERMANENT = "PERMANENT"
    SEASONAL_DOMESTIC = "SEASONAL_DOMESTIC"
    H2B_VISA = "H2B_VISA"


class CrewRole(str, Enum):
    SETUP = "SETUP"
    RIDE_OPERATOR = "RIDE_OPERATOR"
    TEARDOWN = "TEARDOWN"
    TICKETING = "TICKETING"


class TicketChannel(str, Enum):
    WRISTBAND = "WRISTBAND"
    SINGLE = "SINGLE"
    PRESALE = "PRESALE"
    COMP = "COMP"


class ClosureCause(str, Enum):
    WIND = "WIND"
    RAIN = "RAIN"
    LIGHTNING = "LIGHTNING"
    HEAT = "HEAT"


class MakeGoodKind(str, Enum):
    CASH_REFUND = "CASH_REFUND"
    SPONSOR_CREDIT = "SPONSOR_CREDIT"
    BONUS_DAY = "BONUS_DAY"


class MakeGoodResponse(str, Enum):
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"


# ─── Entity shapes ────────────────────────────────────────────────────────────
# Fourteen of the fifteen resource kinds carry id + created_at + updated_at +
# version. The ticket-sale record is the single exception: it is an immutable
# financial fact carrying only id and created_at.


class Jurisdiction(TypedDict):
    id: str
    state_code: str
    name: str
    permit_lead_days: int
    amusement_tax_pct: float
    permit_fee_cents: int
    requires_state_ride_inspection: bool
    inspection_slot_capacity_per_day: int
    max_consecutive_work_days: int
    housing_permit_required: bool
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict):
    id: str
    jurisdiction_id: str
    name: str
    city: str
    lot_area_sqft: int
    power_amps_available: float
    expected_attendance: int
    lot_surface: str
    housing_pads_available: int
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    name: str
    season_year: int
    home_base_state: str
    status: str
    stop_count: int
    total_haul_miles: float
    total_travel_hours: float
    total_guaranteed_cents: int
    closed_stop_count: int
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict):
    id: str
    route_id: str
    venue_id: str
    load_in_start: str
    open_date: str
    close_date: str
    teardown_deadline: str
    previous_stop_id: Optional[str]
    haul_miles_from_previous: float
    sequence_index: Optional[int]
    travel_hours_from_previous: float
    operating_days: int
    scheduled_operating_hours: float
    status: str
    compliance_posture: str
    allocated_sqft_used: int
    power_amps_used: float
    labor_cost_provisional_cents: int
    operating_ride_count: int
    closure_hours_adjudicated: float
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    route_stop_id: str
    counterparty_name: str
    revenue_split_pct_operator: float
    sponsor_name: Optional[str]
    guarantee_cents: int
    ride_minimum_count: int
    exclusivity: str
    settlement_basis: str
    status: str
    negotiation_round: int
    last_sent_by_user_id: Optional[str]
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Ride(TypedDict):
    id: str
    name: str
    ride_class: str
    footprint_sqft: int
    power_amps: float
    crew_size_setup: int
    setup_hours: float
    axle_count: int
    requires_state_inspection: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RideAllocation(TypedDict):
    id: str
    ride_id: str
    route_stop_id: str
    status: str
    footprint_charged_sqft: int
    power_charged_amps: float
    occupation_start: str
    occupation_end: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PermitApplication(TypedDict):
    id: str
    route_stop_id: str
    permit_type: str
    valid_from: str
    valid_until: str
    axles_declared: int
    fee_cents: int
    status: str
    submitted_at: Optional[str]
    decided_at: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InspectionOrder(TypedDict):
    id: str
    ride_allocation_id: str
    authority: str
    scheduled_date: str
    status: str
    attempt_number: int
    defect_count: int
    result_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Worker(TypedDict):
    id: str
    full_name: str
    employment_type: str
    hourly_rate_cents: int
    visa_expires_on: Optional[str]
    certified_ride_classes: List[str]
    housing_required: bool
    compliance_status: str
    scheduled_hours_total: float
    worked_days_count: int
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict):
    id: str
    route_stop_id: str
    worker_id: str
    crew_role: str
    shift_start: str
    shift_end: str
    status: str
    shift_hours: float
    cost_cents: int
    housing_pad_assigned: bool
    created_at: str
    updated_at: str
    version: int


class TicketSale(TypedDict):
    """A sales batch is an immutable financial fact: it carries only ``id`` and
    ``created_at`` — no ``updated_at`` and no ``version``."""

    id: str
    route_stop_id: str
    channel: str
    units: int
    unit_price_cents: int
    business_date: str
    gross_cents: int
    created_at: str


class Settlement(TypedDict):
    id: str
    contract_id: str
    variant: str
    status: str
    gross_cents: int
    tax_cents: int
    taxable_net_cents: int
    effective_operator_pct: float
    split_share_cents: int
    shortfall_penalty_cents: int
    guarantee_effective_cents: int
    makegood_deduction_cents: int
    settlement_due_cents: int
    dispute_reason: Optional[str]
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WeatherClosure(TypedDict):
    id: str
    route_stop_id: str
    cause: str
    closed_from: str
    closed_to: str
    closure_hours_raw: float
    abated_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class MakeGoodArrangement(TypedDict):
    id: str
    weather_closure_id: str
    contract_id: str
    kind: str
    amount_cents: int
    status: str
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Readiness(TypedDict):
    """Shape of the computed readiness read on a lot."""

    route_stop_id: str
    compliance_posture: str
    blocking_error_id: Optional[str]
    event_permit_ok: bool
    inspections_ok: bool
    crew_coverage_ok: bool
    committed_ride_count: int
    ride_minimum_required: int
