"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity definitions (sections 2.5 and 3).
"""
from enum import Enum
from typing import Any, List, Optional, TypedDict


class UserRole(str, Enum):
    STATE_PROGRAM_ADMIN = "StateProgramAdmin"
    STATE_INSPECTOR = "StateInspector"
    FAIR_MANAGER = "FairManager"
    RIDE_OPERATOR = "RideOperator"
    TICKET_CLERK = "TicketClerk"
    CREW_MEMBER = "CrewMember"


class FairStatus(str, Enum):
    SETUP = "SETUP"
    PERMIT_REQUESTED = "PERMIT_REQUESTED"
    PERMITTED = "PERMITTED"
    TEARDOWN = "TEARDOWN"
    ARCHIVED = "ARCHIVED"


class RideSetupStatus(str, Enum):
    INSTALLED = "INSTALLED"
    SETUP_VERIFIED = "SETUP_VERIFIED"
    DISMANTLED = "DISMANTLED"


class RideLicenseStatus(str, Enum):
    PENDING = "PENDING"
    LICENSED = "LICENSED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class RideDailyStatus(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    WEATHER_HOLD = "WEATHER_HOLD"
    INCIDENT_HOLD = "INCIDENT_HOLD"


class RideClass(str, Enum):
    KIDDIE = "KIDDIE"
    FAMILY = "FAMILY"
    THRILL = "THRILL"
    EXTREME = "EXTREME"


class AppointmentScope(str, Enum):
    FAIR_WIDE = "FAIR_WIDE"
    RIDE_AUDIT = "RIDE_AUDIT"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED_PASS = "COMPLETED_PASS"
    COMPLETED_FAIL = "COMPLETED_FAIL"
    CANCELLED = "CANCELLED"


class PermitStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class StaffStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class StaffFunction(str, Enum):
    OPERATOR = "OPERATOR"
    CLERK = "CLERK"
    CREW = "CREW"
    SUPERVISOR = "SUPERVISOR"


class CertStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class DayPosture(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKLIST_PHASE = "CHECKLIST_PHASE"
    OPEN = "OPEN"
    WEATHER_HOLD = "WEATHER_HOLD"
    CLOSED = "CLOSED"
    RECONCILED = "RECONCILED"


class ChecklistStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    COUNTERSIGNED = "COUNTERSIGNED"


class CycleStatus(str, Enum):
    LOADING = "LOADING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class RedemptionStatus(str, Enum):
    QUEUED = "QUEUED"
    REDEEMED = "REDEEMED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class ProductKind(str, Enum):
    RIDE_TICKET = "RIDE_TICKET"
    CREDIT_BUNDLE = "CREDIT_BUNDLE"
    WRISTBAND = "WRISTBAND"


class SaleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class IncidentSeverity(str, Enum):
    NEAR_MISS = "NEAR_MISS"
    MINOR = "MINOR"
    SERIOUS = "SERIOUS"
    FATAL = "FATAL"


class IncidentStatus(str, Enum):
    FILED = "FILED"
    CLEARED = "CLEARED"
    SHUTDOWN_ORDERED = "SHUTDOWN_ORDERED"


class ShiftRole(str, Enum):
    SETUP = "SETUP"
    OPERATIONS = "OPERATIONS"
    TEARDOWN = "TEARDOWN"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class Fair(TypedDict, total=False):
    id: str
    name: str
    operator_company_name: str
    location: str
    setup_start_date: str
    opening_date: str
    closing_date: str
    teardown_end_date: str
    midway_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Ride(TypedDict, total=False):
    id: str
    fair_id: str
    name: str
    manufacturer: str
    model: str
    serial_number: str
    ride_class: str
    capacity_per_cycle: int
    min_rider_height_in: int
    max_rider_height_in: int
    wind_limit_mph: int
    cycle_inspection_interval: int
    annual_cert_expires_on: str
    cycles_since_inspection: int
    minor_incidents_today: int
    setup_status: str
    license_status: str
    daily_status: str
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict, total=False):
    id: str
    full_name: str
    license_number: str
    max_daily_inspections: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class InspectionAppointment(TypedDict, total=False):
    id: str
    fair_id: str
    inspector_id: str
    ride_id: Optional[str]
    scope: str
    scheduled_date: str
    start_hour: int
    duration_hours: int
    end_hour: int
    status: str
    findings: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    fair_id: str
    status: str
    estimated_fee_cents: int
    final_fee_cents: Optional[int]
    billable_ride_count: Optional[int]
    reinspection_failure_count: Optional[int]
    approved_by_inspector_id: Optional[str]
    denial_reason: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict, total=False):
    id: str
    fair_id: str
    full_name: str
    functions: List[str]
    status: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OperatorCertification(TypedDict, total=False):
    id: str
    staff_id: str
    ride_class: str
    issued_on: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OperatingDay(TypedDict, total=False):
    id: str
    fair_id: str
    date: str
    max_attendance: int
    posture: str
    attendance_count: int
    gross_sales_cents: Optional[int]
    voided_cents: Optional[int]
    projected_revenue_cents: Optional[int]
    recognized_revenue_cents: Optional[int]
    breakage_cents: Optional[int]
    reconciliation_flagged: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class DailyChecklist(TypedDict, total=False):
    id: str
    ride_id: str
    operating_day_id: str
    performed_by_staff_id: str
    countersigned_by_staff_id: Optional[str]
    items_total: int
    items_passed: Optional[int]
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RideCycle(TypedDict, total=False):
    id: str
    ride_id: str
    operating_day_id: str
    operator_staff_id: str
    sequence_number: int
    status: str
    rider_count: int
    created_at: str
    updated_at: str
    version: int


class RideRedemption(TypedDict, total=False):
    id: str
    wristband_id: str
    ride_id: str
    operating_day_id: str
    ride_cycle_id: Optional[str]
    queue_position: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TicketProduct(TypedDict, total=False):
    id: str
    fair_id: str
    name: str
    kind: str
    base_price_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class TicketSale(TypedDict, total=False):
    id: str
    product_id: str
    operating_day_id: str
    clerk_staff_id: str
    holder_height_in: int
    quantity: int
    is_unlimited: bool
    credits_granted: Optional[int]
    credits_remaining: Optional[int]
    credits_redeemed: Optional[int]
    credits_forfeited: Optional[int]
    subtotal_cents: int
    service_fee_cents: int
    total_charged_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD section 2.5): carries ONLY id + created_at — no updated_at,
# no version.
class WeatherObservation(TypedDict, total=False):
    id: str
    operating_day_id: str
    wind_speed_mph: int
    note: Optional[str]
    created_at: str


class IncidentReport(TypedDict, total=False):
    id: str
    ride_id: str
    operating_day_id: str
    reporter_staff_id: str
    severity: str
    injury_count: int
    description: str
    status: str
    cleared_by_inspector_id: Optional[str]
    cleared_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CrewShift(TypedDict, total=False):
    id: str
    staff_id: str
    fair_id: str
    work_date: str
    start_hour: int
    end_hour: int
    shift_role: str
    status: str
    created_at: str
    updated_at: str
    version: int
