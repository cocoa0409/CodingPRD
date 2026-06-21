"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resource model in the Jury Duty Management PRD (§2.4, §3). Mutable
aggregates carry the system quartet (id, created_at, updated_at, version);
append-only audit rows (qualification response, check-in, strike) carry only
id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ──────────────────────────────────────────────────────

class ServiceTermStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class JurorQualificationStatus(str, Enum):
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    INELIGIBLE = "INELIGIBLE"


class SummonsStatus(str, Enum):
    SUMMONED = "SUMMONED"
    QUALIFIED_PENDING = "QUALIFIED_PENDING"
    REPORTING = "REPORTING"
    SERVING = "SERVING"
    RELEASED = "RELEASED"
    DEFERRED = "DEFERRED"
    EXCUSED = "EXCUSED"
    EXEMPT = "EXEMPT"
    FAILED_TO_APPEAR = "FAILED_TO_APPEAR"


class EvaluatedStatus(str, Enum):
    QUALIFIED = "QUALIFIED"
    INELIGIBLE = "INELIGIBLE"


class DispositionKind(str, Enum):
    DEFER = "DEFER"
    EXCUSE = "EXCUSE"
    EXEMPT = "EXEMPT"


class DispositionDecision(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class TrialStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    READY = "READY"
    IN_TRIAL = "IN_TRIAL"
    ADJOURNED = "ADJOURNED"


class PanelStatus(str, Enum):
    FORMING = "FORMING"
    SEATED = "SEATED"
    DISMISSED = "DISMISSED"


class PanelAssignmentStatus(str, Enum):
    SEATED = "SEATED"
    EXCUSED_FROM_PANEL = "EXCUSED_FROM_PANEL"


class DayKind(str, Enum):
    FULL = "FULL"
    HALF = "HALF"


class PayVoucherVariant(str, Enum):
    ESTIMATED = "ESTIMATED"
    FINAL = "FINAL"


class UserRole(str, Enum):
    JURY_ADMINISTRATOR = "JuryAdministrator"
    COURT_CLERK = "CourtClerk"
    JUDGE = "Judge"
    JUROR = "Juror"


# ─── Mutable aggregates (id + created_at + updated_at + version) ────────

class ServiceTerm(TypedDict):
    id: str
    name: str
    report_date: str
    daily_pay_cents: int
    half_day_pay_cents: int
    full_day_hours: float
    mileage_rate_cents: int
    pay_day_cap: int
    fta_disqualify_threshold: int
    pool_size: int
    summoned_count: int
    status: str
    draw_seq: int
    created_at: str
    updated_at: str
    version: int


class Juror(TypedDict):
    id: str
    service_term_id: str
    full_name: str
    birth_year: int
    round_trip_miles: float
    qualification_status: str
    fta_strike_count: int
    disqualified: bool
    last_drawn_seq: int
    created_at: str
    updated_at: str
    version: int


class Summons(TypedDict):
    id: str
    service_term_id: str
    juror_id: str
    badge_number: int
    status: str
    deferred_to_term_id: Optional[str]
    deferral_count: int
    service_days: int
    created_at: str
    updated_at: str
    version: int


class Disposition(TypedDict):
    id: str
    summons_id: str
    kind: str
    reason_code: str
    requested_term_id: Optional[str]
    decision: str
    decided_by_role: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Trial(TypedDict):
    id: str
    service_term_id: str
    caption: str
    required_jurors: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Panel(TypedDict):
    id: str
    service_term_id: str
    trial_id: str
    target_size: int
    seated_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PanelAssignment(TypedDict):
    id: str
    panel_id: str
    summons_id: str
    seat_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PayVoucher(TypedDict):
    id: str
    summons_id: str
    variant: str
    paid_days: int
    attendance_cents: int
    mileage_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int


# ─── Append-only audit rows (id + created_at ONLY) ─────────────────────

class QualificationResponse(TypedDict):
    id: str
    summons_id: str
    is_citizen: bool
    is_resident: bool
    felony_conviction: bool
    english_proficient: bool
    evaluated_status: str
    created_at: str


class CheckIn(TypedDict):
    id: str
    summons_id: str
    service_date: str
    on_floor_hours: float
    day_kind: str
    created_at: str


class Strike(TypedDict):
    id: str
    juror_id: str
    summons_id: str
    source: str
    created_at: str
