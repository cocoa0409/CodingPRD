"""Domain types: entity TypedDicts, status enums, role enum.

All enums and field sets follow the Survey & Market-Research Panel PRD.
Consent and AttentionCheck are immutable audit records: they carry only
id + created_at (no updated_at, no version).
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    RESEARCH_MANAGER = "ResearchManager"
    PANEL_OPS = "PanelOps"
    FIELD_COORDINATOR = "FieldCoordinator"
    PANELIST = "Panelist"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class StudyStatus(str, Enum):
    DRAFT = "DRAFT"
    FIELDING = "FIELDING"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"
    DELIVERED = "DELIVERED"


class QuotaCellFillStatus(str, Enum):
    OPEN = "OPEN"
    FILLED = "FILLED"


class PanelistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    AT_RISK = "AT_RISK"
    CHURNED = "CHURNED"
    SUSPENDED = "SUSPENDED"


class ConsentDecision(str, Enum):
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class ScreeningStatus(str, Enum):
    SCREENING = "SCREENING"
    SCREENED_IN = "SCREENED_IN"
    QUALIFIED = "QUALIFIED"
    SCREENED_OUT = "SCREENED_OUT"
    VOIDED = "VOIDED"


class CompletionStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class QualityStatus(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FLAGGED = "FLAGGED"
    FAIL = "FAIL"


class AttentionCheckKind(str, Enum):
    TRAP_QUESTION = "TRAP_QUESTION"
    INSTRUCTED_RESPONSE = "INSTRUCTED_RESPONSE"
    TIMING = "TIMING"


class AccrualKind(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    REVERSAL = "REVERSAL"


class AccrualStatus(str, Enum):
    HELD = "HELD"
    CREDITED = "CREDITED"
    VOID = "VOID"


class PayoutMethod(str, Enum):
    CASH = "CASH"
    GIFT_CARD = "GIFT_CARD"


class PayoutStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class FacilityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFFLINE = "OFFLINE"


class FocusGroupStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class FocusGroupBookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    ATTENDED = "ATTENDED"


class ReportFormat(str, Enum):
    CSV = "CSV"
    SPSS = "SPSS"
    DASHBOARD = "DASHBOARD"


class DataDeliveryStatus(str, Enum):
    BUILDING = "BUILDING"
    READY = "READY"
    DELIVERED = "DELIVERED"
    REVOKED = "REVOKED"


# --------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true -> id/created_at/updated_at/version)
# --------------------------------------------------------------------------
class Study(TypedDict):
    id: str
    title: str
    irb_protocol_number: str
    estimated_minutes: int
    base_incentive_points: int
    screener_min_age: int
    required_consent_version: int
    target_total_n: int
    committed_total_n: int
    status: str
    created_at: str
    updated_at: str
    version: int


class QuotaCell(TypedDict):
    id: str
    study_id: str
    segment_key: str
    target_n: int
    reserved_n: int
    committed_n: int
    available_n: int
    fill_status: str
    created_at: str
    updated_at: str
    version: int


class Panelist(TypedDict):
    id: str
    email: str
    full_name: str
    age: int
    segment_key: str
    points_balance: int
    lifetime_invited_n: int
    lifetime_completed_n: int
    last_activity_at: Optional[str]
    health_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Participation(TypedDict):
    id: str
    study_id: str
    panelist_id: str
    quota_cell_id: str
    screening_status: str
    completion_status: str
    completion_seconds: Optional[int]
    straightline_run: Optional[int]
    quality_score: Optional[int]
    quality_status: str
    provisional_points: int
    rescreen_count: int
    created_at: str
    updated_at: str
    version: int


class IncentiveAccrual(TypedDict):
    id: str
    panelist_id: str
    participation_id: str
    accrual_kind: str
    points: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PayoutRequest(TypedDict):
    id: str
    panelist_id: str
    payout_method: str
    points_requested: int
    cash_cents: int
    expected_panelist_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict):
    id: str
    name: str
    capacity: int
    turnaround_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FocusGroup(TypedDict):
    id: str
    study_id: str
    facility_id: str
    starts_at: str
    ends_at: str
    seats: int
    booked_n: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FocusGroupBooking(TypedDict):
    id: str
    focus_group_id: str
    panelist_id: str
    expected_focus_group_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DataDelivery(TypedDict):
    id: str
    study_id: str
    included_completes_n: int
    report_format: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Immutable audit records (common_fields: false -> id/created_at ONLY)
# --------------------------------------------------------------------------
class Consent(TypedDict):
    id: str
    panelist_id: str
    study_id: str
    consent_version: int
    decision: str
    recorded_at: str
    created_at: str


class AttentionCheck(TypedDict):
    id: str
    participation_id: str
    check_kind: str
    passed: bool
    recorded_at: str
    created_at: str
