"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    SCHEDULING_ADMIN = "SchedulingAdmin"
    SURGEON = "Surgeon"
    CIRCULATOR_NURSE = "CirculatorNurse"
    ANESTHESIA_COORDINATOR = "AnesthesiaCoordinator"
    COMMITTEE_MEMBER = "CommitteeMember"
    BLOCK_COMMITTEE_CHAIR = "BlockCommitteeChair"


class BlockStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    REDUCED = "REDUCED"
    CANCELLED = "CANCELLED"


class CaseStatus(str, Enum):
    POSTED = "POSTED"
    SCHEDULED = "SCHEDULED"
    BUMPED = "BUMPED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ProcedureClass(str, Enum):
    MINOR = "MINOR"
    STANDARD = "STANDARD"
    COMPLEX = "COMPLEX"


class CasePriority(str, Enum):
    ELECTIVE = "ELECTIVE"
    ADD_ON = "ADD_ON"
    EMERGENT = "EMERGENT"


class CoverageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class SlotStatus(str, Enum):
    OPEN = "OPEN"
    CLAIMED = "CLAIMED"
    EXPIRED = "EXPIRED"


class RequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    DECIDED = "DECIDED"


class ReviewDecision(str, Enum):
    NONE = "NONE"
    REDUCE = "REDUCE"
    MAINTAIN = "MAINTAIN"


class VoteValue(str, Enum):
    REDUCE = "REDUCE"
    MAINTAIN = "MAINTAIN"
    ABSTAIN = "ABSTAIN"


class ServiceLine(TypedDict, total=False):
    id: str
    name: str
    target_utilization_pct: float
    release_deadline_hours: int
    created_at: str
    updated_at: str
    version: int


class Surgeon(TypedDict, total=False):
    id: str
    service_line_id: str
    full_name: str
    duration_bias_factor: float
    completed_cases_count: int
    on_time_rate_pct: float
    created_at: str
    updated_at: str
    version: int


class OperatingRoom(TypedDict, total=False):
    id: str
    room_name: str
    is_hybrid: bool
    created_at: str
    updated_at: str
    version: int


class BlockAllocation(TypedDict, total=False):
    id: str
    service_line_id: str
    surgeon_id: Optional[str]
    or_id: str
    date: str
    start_minute: int
    end_minute: int
    original_minutes: int
    reserved_minutes: int
    forfeited_minutes: int
    occupied_minutes: int
    release_deadline_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CasePosting(TypedDict, total=False):
    id: str
    surgeon_id: str
    block_id: Optional[str]
    or_id: Optional[str]
    date: Optional[str]
    patient_ref: Optional[str]
    procedure_class: str
    priority: str
    benchmark_duration_minutes: int
    predicted_duration_minutes: int
    turnover_minutes: Optional[int]
    scheduled_start_minute: Optional[int]
    scheduled_end_minute: Optional[int]
    actual_start_minute: Optional[int]
    actual_end_minute: Optional[int]
    is_first_case_of_day: bool
    first_case_delay_minutes: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class AnesthesiaCoverage(TypedDict, total=False):
    id: str
    or_id: str
    date: str
    start_minute: int
    end_minute: int
    provider_ref: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OpenTimeSlot(TypedDict, total=False):
    id: str
    block_id: str
    or_id: str
    date: str
    start_minute: int
    original_minutes: int
    remaining_minutes: int
    forfeited_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReallocationRequest(TypedDict, total=False):
    id: str
    slot_id: str
    surgeon_id: str
    case_id: str
    needed_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable snapshot: id + created_at only (no updated_at, no version).
class UtilizationReport(TypedDict, total=False):
    id: str
    service_line_id: str
    period_start: str
    period_end: str
    allocated_prime_minutes: int
    occupied_prime_minutes: int
    prime_time_utilization_pct: float
    raw_utilization_pct: float
    created_at: str


class CommitteeReview(TypedDict, total=False):
    id: str
    service_line_id: str
    utilization_report_id: str
    period_end: str
    status: str
    decision: str
    tally_reduce: int
    tally_maintain: int
    tally_abstain: int
    created_at: str
    updated_at: str
    version: int


# Append-only: id + created_at only (no updated_at, no version).
class CommitteeVote(TypedDict, total=False):
    id: str
    review_id: str
    member_ref: str
    vote: str
    created_at: str
