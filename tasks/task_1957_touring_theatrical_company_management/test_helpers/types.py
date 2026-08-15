"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§4)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PRODUCER = "Producer"
    TOUR_MANAGER = "TourManager"
    COMPANY_MANAGER = "CompanyManager"
    TREASURER = "Treasurer"


class TourStatus(str, Enum):
    PLANNING = "PLANNING"
    ON_TOUR = "ON_TOUR"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"


class StopBookingStatus(str, Enum):
    TENTATIVE = "TENTATIVE"
    CONTRACTED = "CONTRACTED"
    ADVANCED = "ADVANCED"
    READY = "READY"
    PLAYING = "PLAYING"
    CLOSED = "CLOSED"
    WRAPPED = "WRAPPED"
    CANCELLED = "CANCELLED"


class ComplianceStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    NON_COMPLIANT = "NON_COMPLIANT"
    COMPLIANT = "COMPLIANT"


class PerformanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PLAYED = "PLAYED"
    CANCELLED = "CANCELLED"


class TechCheckItem(str, Enum):
    STAGE_WIDTH_FT = "STAGE_WIDTH_FT"
    FLY_LINES = "FLY_LINES"
    POWER_AMPS = "POWER_AMPS"
    CREW_MINIMUM = "CREW_MINIMUM"


class TechCheckStatus(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"
    WAIVED = "WAIVED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DISPUTED = "DISPUTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    VOID = "VOID"


class ContractType(str, Enum):
    PRINCIPAL = "PRINCIPAL"
    UNDERSTUDY = "UNDERSTUDY"
    SWING = "SWING"
    ENSEMBLE = "ENSEMBLE"


class CastStatus(str, Enum):
    OFFERED = "OFFERED"
    CONTRACTED = "CONTRACTED"
    ON_LEAVE = "ON_LEAVE"
    REPLACED = "REPLACED"
    RELEASED = "RELEASED"


class CoverageKind(str, Enum):
    UNDERSTUDY = "UNDERSTUDY"
    SWING = "SWING"


class CoverageStatus(str, Enum):
    STANDBY = "STANDBY"
    ACTIVATED = "ACTIVATED"
    SUSPENDED = "SUSPENDED"
    RELEASED = "RELEASED"


class InjuryStatus(str, Enum):
    COVERED = "COVERED"
    RESOLVED = "RESOLVED"
    REPLACED = "REPLACED"


class PerDiemPolicy(str, Enum):
    FULL_WEEK = "FULL_WEEK"
    ACTUAL_DAYS = "ACTUAL_DAYS"


class PerDiemStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"


class CrewCallType(str, Enum):
    LOAD_IN = "LOAD_IN"
    LOAD_OUT = "LOAD_OUT"
    SHOW_RUN = "SHOW_RUN"


class CrewCallStatus(str, Enum):
    POSTED = "POSTED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


# All resources carry the standard system-managed fields id, created_at,
# updated_at, version (PRD §2.4), so every TypedDict includes them.


class Tour(TypedDict, total=False):
    id: str
    name: str
    budget_total_cents: int
    capitalization_cents: int
    per_diem_policy: str
    per_diem_daily_cents: int
    royalty_tier_threshold_cents: int
    status: str
    budget_committed_cents: int
    budget_spent_cents: int
    budget_available_cents: int
    cumulative_producer_net_cents: int
    recouped: bool
    royalty_accrued_cents: int
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict, total=False):
    id: str
    name: str
    city: str
    stage_width_ft: int
    fly_capacity_lines: int
    power_amps: int
    crew_available: int
    created_at: str
    updated_at: str
    version: int


class Stop(TypedDict, total=False):
    id: str
    tour_id: str
    venue_id: str
    play_week_start: str
    play_week_end: str
    load_in_date: str
    travel_in_days: int
    guarantee_cents: int
    split_pct: float
    advance_sales_cents: int
    booking_status: str
    compliance_status: str
    estimated_venue_payment_cents: Optional[int]
    cancellation_penalty_cents: int
    wrapped_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Performance(TypedDict, total=False):
    id: str
    stop_id: str
    perf_date: str
    curtain_time: str
    duration_minutes: int
    gross_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TechRiderCheck(TypedDict, total=False):
    id: str
    stop_id: str
    item: str
    required_value: int
    actual_value: Optional[int]
    status: str
    waiver_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    stop_id: str
    status: str
    system_gross_cents: int
    audited_gross_cents: Optional[int]
    taxes_cents: Optional[int]
    levies_cents: Optional[int]
    adjusted_gross_cents: Optional[int]
    venue_payment_cents: Optional[int]
    producer_share_cents: Optional[int]
    royalty_cents: Optional[int]
    submitted_by: Optional[str]
    approved_by: Optional[str]
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CastMember(TypedDict, total=False):
    id: str
    tour_id: str
    name: str
    contract_type: str
    weekly_salary_cents: int
    status: str
    bump_shows_accrued: int
    bump_pay_cents: int
    created_at: str
    updated_at: str
    version: int


class CharacterTrack(TypedDict, total=False):
    id: str
    tour_id: str
    track_name: str
    required_covers: int
    principal_member_id: Optional[str]
    available_covers: int
    exposed: bool
    created_at: str
    updated_at: str
    version: int


class CoverageAssignment(TypedDict, total=False):
    id: str
    track_id: str
    cast_member_id: str
    kind: str
    priority_rank: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InjuryEvent(TypedDict, total=False):
    id: str
    cast_member_id: str
    notes: str
    status: str
    covered_by_coverage_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerDiemStatement(TypedDict, total=False):
    id: str
    stop_id: str
    cast_member_id: str
    days_present: int
    travel_days: int
    policy_snapshot: str
    daily_rate_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewLine(TypedDict, total=False):
    position: str
    rate_cents_per_hour: int


class CrewActualLine(TypedDict, total=False):
    position: str
    hours_worked: float


class CrewCall(TypedDict, total=False):
    id: str
    stop_id: str
    call_type: str
    scheduled_start: str
    lines: List[Dict[str, Any]]
    actual_lines: Optional[List[Dict[str, Any]]]
    total_pay_cents: Optional[int]
    cancellation_penalty_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
