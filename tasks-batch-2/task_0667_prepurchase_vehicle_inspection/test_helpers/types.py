"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's resource model. Entities that carry the four common
system fields (id, created_at, updated_at, version) are distinguished from the
three immutable lightweight records (Vehicle, ReportPhoto, VinHistoryRecord)
that carry only id and created_at.
"""
from enum import Enum
from typing import TypedDict, List


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    OPS_ADMIN = "OpsAdmin"
    ACCOUNT_HOLDER = "AccountHolder"
    INSPECTOR = "Inspector"


# ---------------------------------------------------------------------------
# Status / value enums
# ---------------------------------------------------------------------------
class AccountType(str, Enum):
    DEALER = "DEALER"
    AUCTION = "AUCTION"
    INDIVIDUAL = "INDIVIDUAL"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TierCode(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    HEAVY_DUTY = "HEAVY_DUTY"


class InspectorStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFFLINE = "OFFLINE"


class RushTier(str, Enum):
    NONE = "NONE"
    EXPRESS = "EXPRESS"
    SAME_DAY = "SAME_DAY"


class WorkflowStatus(str, Enum):
    DRAFT = "DRAFT"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    REPORTED = "REPORTED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    INVOICED = "INVOICED"
    REFUNDED = "REFUNDED"


class AssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    RELEASED = "RELEASED"


class ReportOutcome(str, Enum):
    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    AMENDED = "AMENDED"


class RecordType(str, Enum):
    TITLE = "TITLE"
    ODOMETER = "ODOMETER"
    BRANDING = "BRANDING"


class BrandingCode(str, Enum):
    NONE = "NONE"
    SALVAGE = "SALVAGE"
    FLOOD = "FLOOD"
    LEMON = "LEMON"
    REBUILT = "REBUILT"


class VinReportStatus(str, Enum):
    COMPILED = "COMPILED"


class RecallSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RecallStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class DisputeReason(str, Enum):
    MISSED_DEFECT = "MISSED_DEFECT"
    LATE_DELIVERY = "LATE_DELIVERY"
    WRONG_VEHICLE = "WRONG_VEHICLE"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common-fields entities (id + created_at + updated_at + version)
# ---------------------------------------------------------------------------
class Account(TypedDict):
    id: str
    account_type: str
    legal_name: str
    email: str
    net_terms_days: int
    rush_discount_pct: float
    status: str
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class FeeSchedule(TypedDict):
    id: str
    tier_code: str
    base_fee_cents: int
    vin_history_fee_cents: int
    per_mile_dispatch_cents: int
    effective: bool
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict):
    id: str
    full_name: str
    base_lat: float
    base_lng: float
    certified_tiers: List[str]
    max_daily_jobs: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InspectionOrder(TypedDict):
    id: str
    account_id: str
    vehicle_id: str
    fee_schedule_id: str
    location_lat: float
    location_lng: float
    dispatch_miles: float
    include_vin_history: bool
    rush_tier: str
    ordered_at: str
    sla_deadline: str
    workflow_status: str
    payment_status: str
    estimated_fee_cents: int
    fee_total_cents: int
    late_delivery: bool
    refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class DispatchAssignment(TypedDict):
    id: str
    order_id: str
    inspector_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InspectionReport(TypedDict):
    id: str
    order_id: str
    assignment_id: str
    odometer_reading: int
    points_total: int
    points_failed: int
    road_test_done: bool
    condition_score: float
    outcome: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VinReport(TypedDict):
    id: str
    order_id: str
    vehicle_id: str
    odometer_rollback: bool
    worst_branding: str
    title_count: int
    open_recall_count: int
    risk_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RecallRecord(TypedDict):
    id: str
    campaign_id: str
    year: int
    make: str
    model: str
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    order_id: str
    report_id: str
    account_id: str
    reason: str
    claimed_cents: int
    approved_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Immutable lightweight records — carry ONLY id + created_at
# ---------------------------------------------------------------------------
class Vehicle(TypedDict):
    id: str
    vin: str
    year: int
    make: str
    model: str
    created_at: str


class ReportPhoto(TypedDict):
    id: str
    report_id: str
    caption: str
    is_critical: bool
    url: str
    created_at: str


class VinHistoryRecord(TypedDict):
    id: str
    vehicle_id: str
    record_type: str
    event_date: str
    odometer_value: int
    branding_code: str
    title_state: str
    created_at: str
