"""Domain types: entity TypedDicts, status enums, role enum.

Per the PRD's common-resource-properties rule, primary resources carry
id + created_at + updated_at + version, while the append-only resources
(TrainingEvent, FuelPriceEntry, RidershipReport) carry only id + created_at.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    DISTRICT_ADMIN = "DistrictAdmin"
    CONTRACTOR_OPS = "ContractorOps"
    HR_RECRUITER = "HRRecruiter"
    FLEET_MANAGER = "FleetManager"
    FINANCE_CLERK = "FinanceClerk"
    DRIVER = "Driver"


class DistrictStatus(str, Enum):
    ACTIVE = "ACTIVE"


class ContractStatus(str, Enum):
    DRAFT_BID = "DRAFT_BID"
    SUBMITTED = "SUBMITTED"
    AWARDED = "AWARDED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"
    WITHDRAWN = "WITHDRAWN"
    LOST = "LOST"


class PenaltyMode(str, Enum):
    FLAT_PER_ROUTE = "FLAT_PER_ROUTE"
    PER_STUDENT_MINUTE = "PER_STUDENT_MINUTE"


class RouteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class DriverStatus(str, Enum):
    APPLICANT = "APPLICANT"
    SCREENING = "SCREENING"
    TRAINING = "TRAINING"
    TESTING = "TESTING"
    CERTIFIED = "CERTIFIED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class SuspensionReason(str, Enum):
    DISCIPLINE = "DISCIPLINE"
    CREDENTIAL_LAPSED = "CREDENTIAL_LAPSED"


class TrainingCategory(str, Enum):
    CLASSROOM = "CLASSROOM"
    BEHIND_WHEEL = "BEHIND_WHEEL"
    SAFETY = "SAFETY"


class CredentialKind(str, Enum):
    CDL_B = "CDL_B"
    S_ENDORSEMENT = "S_ENDORSEMENT"
    FIRST_AID = "FIRST_AID"


class CredentialStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class BusStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    IN_SHOP = "IN_SHOP"
    GROUNDED = "GROUNDED"
    DECOMMISSIONED = "DECOMMISSIONED"


class FuelType(str, Enum):
    DIESEL = "DIESEL"
    GASOLINE = "GASOLINE"
    ELECTRIC = "ELECTRIC"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    DIAGNOSING = "DIAGNOSING"
    WAITING_PARTS = "WAITING_PARTS"
    IN_REPAIR = "IN_REPAIR"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class WorkOrderCategory(str, Enum):
    PM = "PM"
    REPAIR = "REPAIR"
    INSPECTION_FOLLOWUP = "INSPECTION_FOLLOWUP"


class ServiceDayStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCH_OPEN = "DISPATCH_OPEN"
    LOCKED = "LOCKED"
    RECONCILED = "RECONCILED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


class ServiceDayCancellationReason(str, Enum):
    WEATHER = "WEATHER"
    DISTRICT_CLOSURE = "DISTRICT_CLOSURE"


class AssignmentStatus(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    EN_ROUTE = "EN_ROUTE"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class AssignmentCancellationReason(str, Enum):
    BUS_GROUNDED = "BUS_GROUNDED"
    DRIVER_SUSPENDED = "DRIVER_SUSPENDED"
    CONTRACT_TERMINATED = "CONTRACT_TERMINATED"
    WEATHER = "WEATHER"
    OPS_CANCEL = "OPS_CANCEL"


class CharterTripStatus(str, Enum):
    REQUESTED = "REQUESTED"
    QUOTED = "QUOTED"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    INVOICED = "INVOICED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class IncidentCategory(str, Enum):
    ACCIDENT = "ACCIDENT"
    BEHAVIOR = "BEHAVIOR"
    MECHANICAL = "MECHANICAL"
    MEDICAL = "MEDICAL"


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RETURNED_FOR_INFO = "RETURNED_FOR_INFO"
    CLOSED = "CLOSED"


# --- Entity TypedDicts (primary resources: id + created_at + updated_at + version) ---

class District(TypedDict, total=False):
    id: str
    name: str
    region_fuel_index_code: str
    credit_limit_cents: int
    billing_dispute_window_days: int
    status: str
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    district_id: str
    bid_reference: str
    daily_rate_per_bus_cents: int
    school_days_per_year: int
    fuel_base_price_cents: int
    fuel_escalation_trigger_pct: int
    fuel_escalation_share_pct: int
    penalty_mode: str
    shortage_penalty_flat_cents: int
    shortage_penalty_per_student_minute_cents: int
    assumed_minutes_per_missed_route: int
    monthly_cap_cents: int
    charter_hourly_rate_cents: int
    charter_per_mile_cents: int
    start_date: str
    end_date: str
    status: str
    amendment_seq: int
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict, total=False):
    id: str
    contract_id: str
    route_code: str
    school_site: str
    am_start_minute: int
    am_end_minute: int
    student_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict, total=False):
    id: str
    primary_district_id: str
    full_name: str
    license_number: str
    license_class: str
    hourly_wage_cents: int
    hired_on: Optional[str]
    status: str
    suspension_reason: Optional[str]
    behind_wheel_minutes: int
    classroom_minutes: int
    test_fail_count: int
    weekly_assigned_minutes: int
    created_at: str
    updated_at: str
    version: int


class TrainingEvent(TypedDict, total=False):
    # Append-only: id + created_at only, no updated_at / version.
    id: str
    driver_id: str
    category: str
    minutes: int
    occurred_on: str
    created_at: str


class Credential(TypedDict, total=False):
    id: str
    driver_id: str
    kind: str
    issued_on: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Bus(TypedDict, total=False):
    id: str
    district_id: str
    fleet_number: str
    capacity: int
    fuel_type: str
    mpg_x10: int
    odometer_miles: int
    status: str
    next_inspection_due: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    bus_id: str
    scheduled_date: str
    inspector_ref: str
    status: str
    result: Optional[str]
    completed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    bus_id: str
    category: str
    description: str
    status: str
    labor_minutes: Optional[int]
    parts_cost_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ServiceDay(TypedDict, total=False):
    id: str
    contract_id: str
    service_date: str
    status: str
    required_routes: int
    covered_routes: int
    uncovered_routes: int
    shortage_flag: bool
    shortage_credit_cents: int
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    service_day_id: str
    route_id: str
    driver_id: Optional[str]
    bus_id: Optional[str]
    status: str
    cancellation_reason: Optional[str]
    is_doubled: bool
    doubled_after_assignment_id: Optional[str]
    planned_start_minute: int
    planned_end_minute: int
    actual_start_minute: Optional[int]
    actual_end_minute: Optional[int]
    actual_miles: Optional[int]
    billable: bool
    created_at: str
    updated_at: str
    version: int


class CharterTrip(TypedDict, total=False):
    id: str
    contract_id: str
    purpose: str
    trip_date: str
    pickup_minute: int
    return_minute: int
    estimated_hours_x10: int
    estimated_miles: int
    passenger_count: int
    assigned_bus_id: Optional[str]
    assigned_driver_id: Optional[str]
    status: str
    quote_price_cents: Optional[int]
    quote_valid_until: Optional[str]
    deposit_cents: Optional[int]
    final_price_cents: Optional[int]
    actual_hours_x10: Optional[int]
    actual_miles: Optional[int]
    cancel_fee_cents: Optional[int]
    refund_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class FuelPriceEntry(TypedDict, total=False):
    # Append-only: id + created_at only, no updated_at / version.
    id: str
    district_id: str
    effective_month: str
    avg_price_cents_per_gallon: int
    source: str
    created_at: str


class Invoice(TypedDict, total=False):
    id: str
    contract_id: str
    period_month: str
    status: str
    bus_lines_cents: int
    charter_lines_cents: int
    shortage_credit_cents: int
    fuel_adjustment_cents: int
    provisional_total_cents: Optional[int]
    final_total_cents: Optional[int]
    total_cents: int
    issued_on: Optional[str]
    dispute_count: int
    dispute_reason: Optional[str]
    paid_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    district_id: str
    route_id: Optional[str]
    driver_id: Optional[str]
    service_day_id: Optional[str]
    category: str
    severity: str
    description: str
    occurred_at: str
    student_discipline_flag: bool
    status: str
    submitted_at: Optional[str]
    district_due_by: Optional[str]
    acknowledged_at: Optional[str]
    sla_breached: bool
    created_at: str
    updated_at: str
    version: int


class RidershipReport(TypedDict, total=False):
    # Append-only: id + created_at only, no updated_at / version.
    id: str
    assignment_id: str
    service_day_id: str
    boardings: int
    alightings: int
    first_pickup_actual_minute: int
    last_dropoff_actual_minute: int
    minutes_late: int
    on_time: bool
    student_minutes_late: int
    created_at: str
