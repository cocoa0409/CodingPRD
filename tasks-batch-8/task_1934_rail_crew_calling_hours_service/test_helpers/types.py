"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class Craft(str, Enum):
    CONDUCTOR = "CONDUCTOR"
    ENGINEER = "ENGINEER"
    BRAKEMAN = "BRAKEMAN"
    YARDMASTER = "YARDMASTER"


class AvailabilityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MARKED_OFF = "MARKED_OFF"
    ON_LEAVE = "ON_LEAVE"
    ON_ASSIGNMENT = "ON_ASSIGNMENT"
    ON_REST = "ON_REST"
    SUSPENDED = "SUSPENDED"


class SlotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    VACATED = "VACATED"


class JobStatus(str, Enum):
    BULLETINED = "BULLETINED"
    CALLING = "CALLING"
    FILLED = "FILLED"


class CallStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    NO_ANSWER = "NO_ANSWER"
    EXPIRED = "EXPIRED"
    RESCINDED = "RESCINDED"


class AssignmentStatus(str, Enum):
    MARKED_UP = "MARKED_UP"
    ON_DUTY = "ON_DUTY"
    TIE_UP_PENDING = "TIE_UP_PENDING"
    COMPLETED = "COMPLETED"
    LAID_OFF = "LAID_OFF"
    RECREWED = "RECREWED"


class RestStatus(str, Enum):
    OPEN = "OPEN"
    SATISFIED = "SATISFIED"
    DISTURBED = "DISTURBED"


class LeaveType(str, Enum):
    VACATION = "VACATION"
    PERSONAL_DAY = "PERSONAL_DAY"


class BidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    AWARDED = "AWARDED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class DeadheadMode(str, Enum):
    NONE = "NONE"
    TAXI = "TAXI"
    COMPANY_VEHICLE = "COMPANY_VEHICLE"
    TRAIN = "TRAIN"


class RecordStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DISPUTED = "DISPUTED"
    FINALIZED = "FINALIZED"


class ShortageStatus(str, Enum):
    OPEN = "OPEN"
    RECREWING = "RECREWING"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class UserRole(str, Enum):
    EMPLOYEE = "Employee"
    CREW_CALLER = "CrewCaller"
    CREW_MANAGER = "CrewManager"


# --- Entities carrying id + created_at + updated_at + version (PRD §2.4) ---


class Employee(TypedDict, total=False):
    id: str
    employee_number: str
    full_name: str
    craft: str
    seniority_date: str
    availability_status: str
    cumulative_duty_minutes_month: int
    fatigue_score: float
    home_terminal: str
    created_at: str
    updated_at: str
    version: int


class ExtraBoard(TypedDict, total=False):
    id: str
    board_code: str
    craft: str
    terminal: str
    guaranteed_slots: int
    created_at: str
    updated_at: str
    version: int


class ExtraBoardSlot(TypedDict, total=False):
    id: str
    board_id: str
    employee_id: str
    standing_position: int
    slot_status: str
    created_at: str
    updated_at: str
    version: int


class Job(TypedDict, total=False):
    id: str
    job_symbol: str
    craft: str
    origin_terminal: str
    report_time: str
    crew_required: int
    filled_count: int
    job_status: str
    created_at: str
    updated_at: str
    version: int


class Call(TypedDict, total=False):
    id: str
    job_id: str
    employee_id: str
    call_status: str
    offered_at: str
    expires_at: str
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    job_id: str
    employee_id: str
    call_id: str
    assignment_status: str
    on_duty_at: Optional[str]
    off_duty_at: Optional[str]
    deadhead_minutes: int
    deadhead_mode: str
    created_at: str
    updated_at: str
    version: int


# Append-only entity (PRD §2.4): carries ONLY id + created_at — no updated_at,
# no version.
class RestPeriod(TypedDict, total=False):
    id: str
    employee_id: str
    rest_start: str
    rest_end: Optional[str]
    rest_status: str
    undisturbed_minutes: int
    created_at: str


class LeaveBid(TypedDict, total=False):
    id: str
    employee_id: str
    leave_type: str
    start_date: str
    end_date: str
    bid_status: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayRecord(TypedDict, total=False):
    id: str
    employee_id: str
    assignment_id: str
    claimed_minutes: int
    claimed_deadhead_minutes: int
    gross_pay_cents: int
    record_status: str
    created_at: str
    updated_at: str
    version: int


class CrewShortage(TypedDict, total=False):
    id: str
    job_id: str
    craft: str
    shortage_status: str
    opened_at: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
