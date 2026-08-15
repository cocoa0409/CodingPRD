"""Domain types: entity shapes, status enums, and roles for the parking API."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PARKING_ADMIN = "ParkingAdmin"
    EMPLOYEE = "Employee"
    PAYROLL_ADMIN = "PayrollAdmin"
    ENFORCEMENT_OFFICER = "EnforcementOfficer"
    APPEALS_OFFICER = "AppealsOfficer"
    SHUTTLE_DISPATCHER = "ShuttleDispatcher"


class ProgramPosture(str, Enum):
    PROGRAM_NORMAL = "PROGRAM_NORMAL"
    PROGRAM_FROZEN = "PROGRAM_FROZEN"
    PROGRAM_CLOSED = "PROGRAM_CLOSED"


class ProrationMode(str, Enum):
    CALENDAR_DAY = "CALENDAR_DAY"
    HALF_MONTH = "HALF_MONTH"


class ShiftPattern(str, Enum):
    DAY = "DAY"
    NIGHT = "NIGHT"
    ROTATING = "ROTATING"
    SPLIT = "SPLIT"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class EmployeeStanding(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    BILLING_HOLD = "BILLING_HOLD"


class LotTier(str, Enum):
    CORE = "CORE"
    REMOTE = "REMOTE"


class LotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    STANDBY = "STANDBY"
    ACTIVATED = "ACTIVATED"
    CLOSED = "CLOSED"


class PermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    WAITLISTED = "WAITLISTED"
    OFFERED = "OFFERED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class SuspensionReason(str, Enum):
    VIOLATION_THRESHOLD = "VIOLATION_THRESHOLD"
    LOT_CLOSURE = "LOT_CLOSURE"
    BILLING_HOLD = "BILLING_HOLD"
    ADMIN = "ADMIN"


class RenewalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class RouteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TripStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DEPARTED = "DEPARTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class NoticeType(str, Enum):
    LOT_CLOSURE = "LOT_CLOSURE"
    LOT_REOPEN = "LOT_REOPEN"
    ROUTE_SUSPENSION = "ROUTE_SUSPENSION"
    HEADWAY_CHANGE = "HEADWAY_CHANGE"
    GENERAL = "GENERAL"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    EFFECTIVE = "EFFECTIVE"
    CANCELLED = "CANCELLED"


class ViolationCode(str, Enum):
    EXPIRED_PERMIT = "EXPIRED_PERMIT"
    WRONG_LOT = "WRONG_LOT"
    NO_PERMIT_DISPLAY = "NO_PERMIT_DISPLAY"
    BLOCKED_LANE = "BLOCKED_LANE"
    PARKED_AFTER_REVOCATION = "PARKED_AFTER_REVOCATION"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REVERSED = "REVERSED"


class AppealStatus(str, Enum):
    NONE = "NONE"
    APPEALED = "APPEALED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class TowStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    TOWED = "TOWED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class CycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    EXPORTED = "EXPORTED"


class ChargeType(str, Enum):
    PERMIT_FEE = "PERMIT_FEE"
    VIOLATION_FINE = "VIOLATION_FINE"
    TOW_FEE = "TOW_FEE"
    ADJUSTMENT_CREDIT = "ADJUSTMENT_CREDIT"
    ADJUSTMENT_DEBIT = "ADJUSTMENT_DEBIT"


class ChargeStatus(str, Enum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    EXPORTED = "EXPORTED"
    SETTLED = "SETTLED"
    DEDUCTION_FAILED = "DEDUCTION_FAILED"
    REVERSED = "REVERSED"


class PeakWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


# All resources carry the common system fields id/created_at/updated_at/version.

class ParkingProgram(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    posture: str
    proration_mode: str
    monthly_subsidy_pool_cents: int
    waitlist_offer_ttl_hours: int
    violation_suspension_threshold: int
    tow_hold_hours: int
    ops_run_index: int


class Employee(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    badge_number: str
    full_name: str
    employer_code: str
    shift_pattern: str
    hire_date: str
    employment_status: str
    terminated_at: Optional[str]
    balance_due_cents: int
    standing: str


class ParkingLot(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    code: str
    tier: str
    capacity: int
    monthly_maintenance_cents: int
    status: str
    occupied_slots: int
    reserved_slots: int


class Permit(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    employee_id: str
    lot_id: str
    vehicle_plate: str
    queue_shift_pattern: str
    status: str
    offered_at: Optional[str]
    offer_expires_at: Optional[str]
    activated_at: Optional[str]
    suspended_at: Optional[str]
    suspension_reason: Optional[str]
    monthly_fee_cents: Optional[int]
    term_end: Optional[str]


class PermitRenewal(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    permit_id: str
    status: str
    requested_at: str
    decided_by: Optional[str]


class ShuttleRoute(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    lot_id: str
    code: str
    headway_target_minutes: int
    operating_cost_per_trip_cents: int
    status: str


class ShuttleTrip(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    route_id: str
    scheduled_departure_at: str
    actual_departure_at: Optional[str]
    status: str
    boarded_count: int


class ServiceChangeNotice(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    lot_id: Optional[str]
    route_id: Optional[str]
    notice_type: str
    headline: str
    effective_from: str
    effective_to: Optional[str]
    new_headway_minutes: Optional[int]
    status: str
    published_at: Optional[str]


class Violation(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    permit_id: str
    violation_code: str
    issued_by: str
    issued_at: str
    fine_cents: int
    payment_status: str
    appeal_status: str
    charge_entry_id: Optional[str]


class TowEvent(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    permit_id: str
    violation_id: str
    authorized_by: str
    status: str
    towed_at: Optional[str]
    released_at: Optional[str]
    impound_fee_cents: Optional[int]
    charge_entry_id: Optional[str]


class BillingCycle(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    period_start: str
    period_end: str
    status: str
    subsidy_per_capita_cap_cents: int
    total_charges_cents: int


class ChargeEntry(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    cycle_id: str
    employee_id: str
    permit_id: Optional[str]
    charge_type: str
    amount_cents: int
    subsidy_cents: int
    span_start: Optional[str]
    span_end: Optional[str]
    status: str
    description: Optional[str]


class PeakWindow(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    lot_id: str
    starts_at: str
    ends_at: str
    status: str
