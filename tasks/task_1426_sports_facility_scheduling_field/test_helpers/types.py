"""Domain types: entity TypedDicts, status enums, role enum.

All primary resources carry the standard system-managed fields (id,
created_at, updated_at, version) described in PRD section 2.5. StrikeRecord
is the sole exception: an immutable ledger entry carrying only id and
created_at.
"""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    ATHLETICS_ADMIN = "AthleticsAdmin"
    FIELD_SUPERVISOR = "FieldSupervisor"
    ORG_COORDINATOR = "OrgCoordinator"
    FINANCE_CLERK = "FinanceClerk"


class Classification(str, Enum):
    RESIDENT = "RESIDENT"
    NONRESIDENT = "NONRESIDENT"
    COMMERCIAL = "COMMERCIAL"


class OrgType(str, Enum):
    YOUTH_LEAGUE = "YOUTH_LEAGUE"
    ADULT_LEAGUE = "ADULT_LEAGUE"
    SCHOOL = "SCHOOL"
    TOURNAMENT_OPERATOR = "TOURNAMENT_OPERATOR"
    CORPORATE = "CORPORATE"


class OrgStanding(str, Enum):
    GOOD = "GOOD"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class FacilityClass(str, Enum):
    DIAMOND = "DIAMOND"
    RECTANGLE = "RECTANGLE"
    MULTIPURPOSE = "MULTIPURPOSE"


class ConditionStatus(str, Enum):
    OPEN = "OPEN"
    LIMITED = "LIMITED"
    CLOSED = "CLOSED"


class FeeScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class WindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ALLOCATED = "ALLOCATED"


class EventType(str, Enum):
    LEAGUE_GAME = "LEAGUE_GAME"
    LEAGUE_PRACTICE = "LEAGUE_PRACTICE"
    TOURNAMENT = "TOURNAMENT"
    SPECIAL_EVENT = "SPECIAL_EVENT"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    AWARDED = "AWARDED"
    WAITLISTED = "WAITLISTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class PermitStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    RAINED_OUT = "RAINED_OUT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    REVOKED = "REVOKED"


class ClosureReason(str, Enum):
    RAIN = "RAIN"
    TURF_REST = "TURF_REST"
    MAINTENANCE = "MAINTENANCE"
    SAFETY = "SAFETY"


class ClosureStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"
    REFUNDED = "REFUNDED"


class PaymentKind(str, Enum):
    PAYMENT = "PAYMENT"
    REFUND = "REFUND"


class PaymentMethod(str, Enum):
    CHECK = "CHECK"
    CARD = "CARD"
    CASH = "CASH"
    CREDIT = "CREDIT"


class PaymentStatus(str, Enum):
    CLEARED = "CLEARED"
    PENDING_APPROVAL = "PENDING_APPROVAL"


class StrikeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESCINDED = "RESCINDED"


class RevokeFault(str, Enum):
    ORG_FAULT = "ORG_FAULT"
    ADMIN_DISCRETION = "ADMIN_DISCRETION"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Organization(TypedDict, total=False):
    id: str
    name: str
    classification: str
    org_type: str
    prior_seasons_active: int
    standing: str
    no_show_strikes_active: int
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict, total=False):
    id: str
    name: str
    facility_class: str
    has_lights: bool
    capacity: int
    weekly_prime_hour_cap: int
    nightly_light_block_cap: int
    condition_status: str
    condition_reason: str
    weekly_prime_hours_used: int
    created_at: str
    updated_at: str
    version: int


class FeeSchedule(TypedDict, total=False):
    id: str
    name: str
    effective_from: str
    status: str
    hourly_resident_cents: int
    hourly_nonresident_cents: int
    hourly_commercial_cents: int
    lights_block_cents: int
    nonresident_surcharge_pct: int
    commercial_surcharge_pct: int
    tournament_day_cents: int
    tournament_day_min_minutes: int
    deposit_pct: int
    min_deposit_cents: int
    created_at: str
    updated_at: str
    version: int


class AllocationWindow(TypedDict, total=False):
    id: str
    season_code: str
    opens_at: str
    closes_at: str
    status: str
    prime_cap_hours_per_org: int
    max_tournament_days_per_org: int
    created_at: str
    updated_at: str
    version: int


class PermitApplication(TypedDict, total=False):
    id: str
    window_id: str
    organization_id: str
    facility_id: str
    event_date: str
    start_minute: int
    end_minute: int
    event_type: str
    wants_lights: bool
    headcount: int
    status: str
    provisional_score: int
    final_score: Optional[int]
    decision_note: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    application_id: str
    organization_id: str
    facility_id: str
    fee_schedule_id: str
    original_permit_id: Optional[str]
    permit_date: str
    start_minute: int
    end_minute: int
    event_type: str
    lights_approved: bool
    lights_minutes_quoted: int
    status: str
    quoted_field_fee_cents: int
    quoted_lights_fee_cents: int
    quoted_surcharge_cents: int
    quoted_total_cents: int
    deposit_required_cents: int
    final_total_cents: Optional[int]
    attendance_minutes: Optional[int]
    rain_reschedule_count: int
    created_at: str
    updated_at: str
    version: int


class FieldClosure(TypedDict, total=False):
    id: str
    facility_id: str
    closure_date: str
    start_minute: Optional[int]
    end_minute: Optional[int]
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    permit_id: str
    organization_id: str
    status: str
    field_fee_cents: int
    lights_fee_cents: int
    surcharge_cents: int
    credit_cents: int
    adjustment_cents: int
    penalty_cents: int
    total_cents: int
    deposit_cents: int
    paid_cents: int
    refunded_cents: int
    balance_due_cents: int
    deposit_penalty_applied_cents: int
    deposit_balance_applied_cents: int
    deposit_refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    invoice_id: str
    organization_id: str
    kind: str
    amount_cents: int
    method: str
    status: str
    initiated_by: str
    approved_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only ledger entry: carries ONLY id + created_at (no updated_at, no
# version) per PRD section 2.5.
class StrikeRecord(TypedDict, total=False):
    id: str
    organization_id: str
    permit_id: str
    strike_points: int
    status: str
    created_at: str


class UsageLedger(TypedDict, total=False):
    id: str
    organization_id: str
    season_code: str
    awarded_prime_hours: int
    awarded_nonprime_hours: int
    attended_hours: int
    no_show_count: int
    created_at: str
    updated_at: str
    version: int
