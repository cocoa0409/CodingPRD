"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    DISPATCHER = "Dispatcher"
    CREW_CALLER = "CrewCaller"
    CONDUCTOR = "Conductor"
    TRACK_INSPECTOR = "TrackInspector"
    SETTLEMENT_CLERK = "SettlementClerk"
    REGULATOR_OFFICER = "RegulatorOfficer"
    CUSTOMER_REP = "CustomerRep"
    GRANT_MANAGER = "GrantManager"


class CreditStatus(str, Enum):
    GOOD = "GOOD"
    SUSPENDED = "SUSPENDED"


class SidingAgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"


class CarOrderStatus(str, Enum):
    PLACED = "PLACED"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FURNISHED = "PARTIALLY_FURNISHED"
    FURNISHED = "FURNISHED"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CarType(str, Enum):
    BOX = "BOX"
    HOPPER = "HOPPER"
    TANK = "TANK"
    FLAT = "FLAT"
    GONDOLA = "GONDOLA"


class CarOwnership(str, Enum):
    HOME = "HOME"
    FOREIGN = "FOREIGN"


class RailcarStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    LOADED = "LOADED"
    IN_TRANSIT = "IN_TRANSIT"
    INTERCHANGED_OUT = "INTERCHANGED_OUT"
    BAD_ORDER = "BAD_ORDER"
    HELD = "HELD"


class SwitchJobStatus(str, Enum):
    PLANNED = "PLANNED"
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    ANNULLED = "ANNULLED"


class TrainMovementStatus(str, Enum):
    PLANNED = "PLANNED"
    READY = "READY"
    DEPARTED = "DEPARTED"
    HELD = "HELD"
    ARRIVED = "ARRIVED"
    SETTLED = "SETTLED"
    ANNULLED = "ANNULLED"


class InterchangeDirection(str, Enum):
    RECEIVED = "RECEIVED"
    DELIVERED = "DELIVERED"


class InterchangeEventStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    DISPUTED = "DISPUTED"


class CarHireStatementStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"


class Commodity(str, Enum):
    GRAIN = "GRAIN"
    LUMBER = "LUMBER"
    CHEMICALS = "CHEMICALS"


class WaybillStatus(str, Enum):
    CREATED = "CREATED"
    RATED = "RATED"
    BILLED = "BILLED"
    SETTLED = "SETTLED"


class DivisionBasis(str, Enum):
    MILEAGE_PRORATE = "MILEAGE_PRORATE"
    AGREED_PERCENTAGE = "AGREED_PERCENTAGE"


class RevenueDivisionStatus(str, Enum):
    DRAFT = "DRAFT"
    AGREED = "AGREED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"


class FraClass(str, Enum):
    EXCEPTED = "EXCEPTED"
    CLASS_1 = "CLASS_1"
    CLASS_2 = "CLASS_2"
    CLASS_3 = "CLASS_3"
    CLASS_4 = "CLASS_4"
    CLASS_5 = "CLASS_5"


class DefectSeverity(str, Enum):
    MONITOR = "MONITOR"
    CRITICAL = "CRITICAL"


class TrackSegmentStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    RESTRICTED = "RESTRICTED"


class TrackInspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    FILED = "FILED"
    DEFECT_FILED = "DEFECT_FILED"
    REMEDIATED = "REMEDIATED"
    WAIVED = "WAIVED"


class CrewCraft(str, Enum):
    ENGINEER = "ENGINEER"
    CONDUCTOR = "CONDUCTOR"


class CrewMemberStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_DUTY = "ON_DUTY"
    RESTING = "RESTING"


class CrewCallStatus(str, Enum):
    CALLED = "CALLED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    ON_DUTY = "ON_DUTY"
    RELIEVED = "RELIEVED"
    EXPIRED = "EXPIRED"


class CrewCallResponse(str, Enum):
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class IncidentType(str, Enum):
    DERAILMENT = "DERAILMENT"
    COLLISION = "COLLISION"
    CROSSING = "CROSSING"
    HAZMAT = "HAZMAT"
    INJURY = "INJURY"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    INVESTIGATING = "INVESTIGATING"
    FRA_FILED = "FRA_FILED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class GrantProjectStatus(str, Enum):
    AWARDED = "AWARDED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"


class GrantMilestoneStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"


# --- Entity TypedDicts ---
# Per PRD §2.5 every resource carries id, created_at, updated_at, and version.


class Customer(TypedDict, total=False):
    id: str
    name: str
    billing_email: str
    demurrage_free_days: int
    credit_status: str
    created_at: str
    updated_at: str
    version: int


class IndustrySiding(TypedDict, total=False):
    id: str
    customer_id: str
    name: str
    capacity_cars: int
    serving_track_segment_id: str
    agreement_expires_on: str
    maintenance_agreement_status: str
    created_at: str
    updated_at: str
    version: int


class CarOrder(TypedDict, total=False):
    id: str
    customer_id: str
    siding_id: str
    car_type: str
    quantity: int
    needed_by_date: str
    status: str
    cars_furnished_count: int
    furnished_at: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Railcar(TypedDict, total=False):
    id: str
    reporting_mark: str
    car_type: str
    ownership: str
    home_road_mark: Optional[str]
    status: str
    current_location_segment_id: Optional[str]
    assigned_order_id: Optional[str]
    hire_rate_per_hour_cents: int
    hire_rate_per_mile_cents: int
    created_at: str
    updated_at: str
    version: int


class SwitchJob(TypedDict, total=False):
    id: str
    car_order_id: Optional[str]
    scheduled_date: str
    notes: Optional[str]
    crew_call_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainMovement(TypedDict, total=False):
    id: str
    symbol: str
    route_segment_ids: List[str]
    origin_interchange_id: Optional[str]
    status: str
    max_speed_mph: int
    departed_at: Optional[str]
    arrived_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InterchangeEvent(TypedDict, total=False):
    id: str
    class_i_partner: str
    direction: str
    railcar_id: str
    waybill_id: Optional[str]
    occurred_at: str
    miles_traveled_on_line: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CarHireStatement(TypedDict, total=False):
    id: str
    railcar_id: str
    period_month: str
    hire_accrual_start: str
    hire_accrual_end: Optional[str]
    accrued_hours: int
    accrued_miles: int
    provisional_amount_cents: int
    final_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Waybill(TypedDict, total=False):
    id: str
    railcar_id: str
    origin_customer_id: str
    car_order_id: Optional[str]
    movement_id: Optional[str]
    destination: str
    commodity: str
    weight_tons: int
    through_route: bool
    our_miles: Optional[int]
    total_miles: Optional[int]
    total_freight_charge_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RevenueDivision(TypedDict, total=False):
    id: str
    waybill_id: str
    basis: str
    agreed_pct: Optional[float]
    our_miles: Optional[int]
    total_miles: Optional[int]
    total_charge_cents: int
    our_share_cents: int
    connecting_share_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TrackSegment(TypedDict, total=False):
    id: str
    name: str
    milepost_start: float
    milepost_end: float
    fra_class: str
    effective_speed_mph: int
    defect_open: bool
    open_defect_severity: Optional[str]
    is_overdue: bool
    status: str
    last_inspection_at: str
    created_at: str
    updated_at: str
    version: int


class TrackInspection(TypedDict, total=False):
    id: str
    segment_id: str
    scheduled_date: str
    status: str
    defect_found: Optional[bool]
    defect_severity: Optional[str]
    findings: Optional[str]
    filed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict, total=False):
    id: str
    name: str
    craft: str
    status: str
    on_duty_minutes_rolling_24h: int
    on_duty_minutes_month: int
    rest_minutes_completed: Optional[int]
    rest_start_at: Optional[str]
    hos_available_minutes: int
    created_at: str
    updated_at: str
    version: int


class CrewCall(TypedDict, total=False):
    id: str
    crew_member_id: str
    movement_id: Optional[str]
    switch_job_id: Optional[str]
    scheduled_start_at: str
    scheduled_end_at: str
    status: str
    on_duty_at: Optional[str]
    off_duty_at: Optional[str]
    actual_on_duty_minutes: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    incident_type: str
    segment_id: str
    movement_id: Optional[str]
    occurred_at: str
    estimated_damage_cents: int
    injuries_count: int
    status: str
    fra_reportable: bool
    fra_report_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GrantProject(TypedDict, total=False):
    id: str
    title: str
    grantor: str
    award_amount_cents: int
    required_match_pct: float
    status: str
    committed_cents: int
    drawn_cents: int
    remaining_cents: int
    percent_complete: float
    created_at: str
    updated_at: str
    version: int


class GrantMilestone(TypedDict, total=False):
    id: str
    project_id: str
    name: str
    milestone_value_cents: int
    actual_cost_cents: Optional[int]
    status: str
    drawdown_cents: Optional[int]
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DemurrageRead(TypedDict, total=False):
    billable_days: int
    cars_held: int
    free_days: int
    charge_cents: int
