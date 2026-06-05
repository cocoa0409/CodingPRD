"""Domain types: entity TypedDicts, status enums, role enum.

All field names mirror the PRD verbatim. PredictabilityLedgerEntry is an
append-only event record carrying only id + created_at (no updated_at, no version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles ---
class UserRole(str, Enum):
    MANAGER = "Manager"
    WORKER = "Worker"


# --- Status enums ---
class LocationStatus(str, Enum):
    ACTIVE = "ACTIVE"


class WorkerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AvailabilityKind(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class TimeOffStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class ShiftStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    FULLY_STAFFED = "FULLY_STAFFED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class AssignmentSource(str, Enum):
    DIRECT = "DIRECT"
    BID = "BID"
    SWAP = "SWAP"


class BidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    AWARDED = "AWARDED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class SwapStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    MANAGER_APPROVED = "MANAGER_APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class PredictabilityReason(str, Enum):
    CLOPENING = "CLOPENING"
    SHORT_NOTICE_POST = "SHORT_NOTICE_POST"
    SHORT_NOTICE_CANCEL = "SHORT_NOTICE_CANCEL"


class PayPeriodStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"


# --- Entity TypedDicts (common_fields: true → id/created_at/updated_at/version) ---
class Location(TypedDict):
    id: str
    name: str
    time_zone: str
    predictability_pay_enabled: bool
    advance_notice_days: int
    min_rest_hours_between_shifts: int
    overtime_weekly_threshold_hours: float
    overtime_multiplier: float
    overtime_cost_guardrail_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Worker(TypedDict):
    id: str
    location_id: str
    full_name: str
    email: str
    is_minor: bool
    minor_daily_cap_hours: float
    minor_weekly_cap_hours: float
    base_hourly_rate_cents: int
    no_show_strikes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Availability(TypedDict):
    id: str
    worker_id: str
    kind: str
    start_utc: str
    end_utc: str
    created_at: str
    updated_at: str
    version: int


class TimeOffRequest(TypedDict):
    id: str
    worker_id: str
    start_utc: str
    end_utc: str
    reason: str
    status: str
    decided_by_manager_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShiftTemplate(TypedDict):
    id: str
    location_id: str
    role_name: str
    weekday: int
    local_start_minute: int
    duration_minutes: int
    forecast_headcount: int
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict):
    id: str
    location_id: str
    template_id: Optional[str]
    role_name: str
    start_utc: str
    end_utc: str
    headcount_required: int
    headcount_filled: int
    posted_utc: Optional[str]
    status: str
    duration_hours: float
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    shift_id: str
    worker_id: str
    pay_period_id: str
    status: str
    source: str
    clopening_flag: bool
    provisional_cost_cents: int
    finalized_cost_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class OpenShiftBid(TypedDict):
    id: str
    shift_id: str
    worker_id: str
    seniority_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SwapRequest(TypedDict):
    id: str
    from_assignment_id: str
    to_worker_id: str
    counter_assignment_id: Optional[str]
    status: str
    decided_by_manager_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayPeriod(TypedDict):
    id: str
    location_id: str
    start_utc: str
    end_utc: str
    status: str
    projected_labor_cost_cents: int
    finalized_labor_cost_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only event, ONLY id + created_at
class PredictabilityLedgerEntry(TypedDict):
    id: str
    worker_id: str
    shift_id: str
    pay_period_id: str
    reason: str
    amount_cents: int
    created_at: str
