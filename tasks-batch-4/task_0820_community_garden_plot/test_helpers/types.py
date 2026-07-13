"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    GARDENER = "Gardener"
    GARDEN_MANAGER = "GardenManager"
    TREASURER = "Treasurer"


class PlotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    ASSIGNED = "ASSIGNED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    WAITLISTED = "WAITLISTED"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class OccupancyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    RENEWED = "RENEWED"
    ENDED = "ENDED"
    FORFEITED = "FORFEITED"


class FeeStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    WAIVED = "WAIVED"
    REFUNDED = "REFUNDED"


class ComplianceStatus(str, Enum):
    OPEN = "OPEN"
    WARNED = "WARNED"
    CURED = "CURED"
    ESCALATED = "ESCALATED"


class GardenerStanding(str, Enum):
    GOOD = "GOOD"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class ToolLoanStatus(str, Enum):
    CHECKED_OUT = "CHECKED_OUT"
    RETURNED = "RETURNED"
    RETURNED_LATE = "RETURNED_LATE"


class PlotSize(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


# --- Entity TypedDicts ---
# common_fields: true -> id + created_at + updated_at + version

class Garden(TypedDict):
    id: str
    name: str
    season_label: str
    season_start: str
    season_end: str
    offer_window_days: int
    total_plots: int
    available_plot_count: int
    created_at: str
    updated_at: str
    version: int


class Plot(TypedDict):
    id: str
    garden_id: str
    label: str
    size: str
    status: str
    current_assignment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Gardener(TypedDict):
    id: str
    full_name: str
    email: str
    tenure_seasons: int
    standing: str
    strike_count: int
    balance_owed_cents: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    gardener_id: str
    garden_id: str
    requested_size: str
    status: str
    priority_score_at_submission: int
    offered_plot_id: Optional[str]
    offer_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    plot_id: str
    gardener_id: str
    garden_id: str
    application_id: Optional[str]
    renewed_from_assignment_id: Optional[str]
    season_start: str
    season_end: str
    size: str
    occupancy_status: str
    fee_status: str
    provisional_fee_cents: int
    final_fee_cents: Optional[int]
    required_work_hours: int
    logged_work_hours: float
    created_at: str
    updated_at: str
    version: int


class ComplianceCase(TypedDict):
    id: str
    assignment_id: str
    gardener_id: str
    violation_type: str
    status: str
    cure_deadline: Optional[str]
    opened_on: str
    created_at: str
    updated_at: str
    version: int


class Tool(TypedDict):
    id: str
    garden_id: str
    name: str
    category: str
    cleaning_buffer_hours: int
    created_at: str
    updated_at: str
    version: int


class ToolLoan(TypedDict):
    id: str
    tool_id: str
    gardener_id: str
    checked_out_at: str
    due_at: str
    returned_at: Optional[str]
    status: str
    late_fine_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> ONLY id + created_at (no updated_at, no version)

class WorkLog(TypedDict):
    id: str
    assignment_id: str
    hours: float
    logged_on: str
    note: Optional[str]
    created_at: str


class WaterReading(TypedDict):
    id: str
    assignment_id: str
    period_index: int
    gallons_used: float
    recorded_on: str
    created_at: str


class ShedBooking(TypedDict):
    id: str
    garden_id: str
    gardener_id: str
    starts_at: str
    ends_at: str
    purpose: str
    created_at: str
