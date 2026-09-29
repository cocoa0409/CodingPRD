"""Domain types for the Short-Term Rental Turnover Coordination API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ──────────────────────────────────────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    COORDINATOR = "Coordinator"
    CLEANER = "Cleaner"
    QUALITY_AUDITOR = "QualityAuditor"
    PROPERTY_OWNER = "PropertyOwner"


# ─── Status / enum vocabularies ────────────────────────────────────────────

class PropertyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    OFFBOARDED = "OFFBOARDED"


class SizeTier(str, Enum):
    STUDIO = "STUDIO"
    ONE_BR = "ONE_BR"
    TWO_BR = "TWO_BR"
    THREE_BR_PLUS = "THREE_BR_PLUS"


class CleanerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class CleanerStatusAction(str, Enum):
    SUSPEND = "SUSPEND"
    REACTIVATE = "REACTIVATE"
    OFFBOARD = "OFFBOARD"


class BookingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"


class CheckinGate(str, Enum):
    OPEN = "OPEN"
    BLOCKED = "BLOCKED"
    RELEASED = "RELEASED"


class GuestNoticeCode(str, Enum):
    NONE = "NONE"
    LATE_CHECKOUT_GRANTED = "LATE_CHECKOUT_GRANTED"
    EARLY_CHECKIN_LIMITED = "EARLY_CHECKIN_LIMITED"
    CHECKIN_DELAYED = "CHECKIN_DELAYED"


class ScheduleChangeType(str, Enum):
    LATE_CHECKOUT = "LATE_CHECKOUT"
    EARLY_CHECKIN = "EARLY_CHECKIN"


class TurnoverStatus(str, Enum):
    PENDING_ASSIGNMENT = "PENDING_ASSIGNMENT"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_VERIFICATION = "AWAITING_VERIFICATION"
    REWORK_REQUIRED = "REWORK_REQUIRED"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    VOID = "VOID"


class TurnType(str, Enum):
    SAME_DAY = "SAME_DAY"
    OVERNIGHT = "OVERNIGHT"
    VACANT_GAP = "VACANT_GAP"


class AssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    ACTIVE = "ACTIVE"
    DECLINED = "DECLINED"
    REVOKED = "REVOKED"
    COMPLETED = "COMPLETED"


class SelectionMode(str, Enum):
    EXPLICIT = "EXPLICIT"
    SELECTOR = "SELECTOR"


class ChecklistTaskStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    WAIVED = "WAIVED"


class ChecklistTaskCategory(str, Enum):
    CLEANING = "CLEANING"
    STAGING = "STAGING"
    RESTOCK = "RESTOCK"


class ChecklistTaskCode(str, Enum):
    STRIP_LINENS = "STRIP_LINENS"
    BATHROOM_DEEP_CLEAN = "BATHROOM_DEEP_CLEAN"
    BED_STAGING = "BED_STAGING"
    SUPPLY_RESTOCK = "SUPPLY_RESTOCK"
    PATIO_STAGING = "PATIO_STAGING"


class ReviewAction(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    WAIVE = "WAIVE"


class SupplyLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class SupplyCategory(str, Enum):
    LINEN = "LINEN"
    CONSUMABLE = "CONSUMABLE"
    WELCOME = "WELCOME"


class StockMovementReason(str, Enum):
    SEED = "SEED"
    REPLENISH = "REPLENISH"
    RESTOCK_USE = "RESTOCK_USE"
    REVERSAL = "REVERSAL"


class IssueReportStatus(str, Enum):
    REPORTED = "REPORTED"
    OWNER_NOTIFIED = "OWNER_NOTIFIED"
    DISPATCHED = "DISPATCHED"
    RESOLVED = "RESOLVED"


class IssueType(str, Enum):
    DAMAGE = "DAMAGE"
    MAINTENANCE = "MAINTENANCE"
    SAFETY = "SAFETY"
    CONSUMABLE_SHORTAGE = "CONSUMABLE_SHORTAGE"


class IssueSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RepairOrderStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"


class QualityAuditStatus(str, Enum):
    SAMPLED = "SAMPLED"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class AuditVariant(str, Enum):
    BLENDED = "BLENDED"
    AUDIT_ONLY = "AUDIT_ONLY"


class PayLineStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    ADJUSTED = "ADJUSTED"
    VOIDED = "VOIDED"


class PayVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


# ─── Entities ──────────────────────────────────────────────────────────────
# Every entity below carries id + created_at + updated_at + version, except
# StockMovement, which the PRD declares append-only: it carries only id and
# created_at (PRD §2.4).

class Property(TypedDict):
    id: str
    code: str
    name: str
    zone_code: str
    size_tier: str
    owner_contact_email: str
    bedroom_count: int
    bathroom_count: int
    bed_count: int
    local_utc_offset_minutes: int
    min_clean_minutes: int
    min_skill_level: int
    owner_notify_min_cost_cents: int
    status: str
    open_issue_count: int
    last_turnover_completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Cleaner(TypedDict):
    id: str
    name: str
    home_zone_code: str
    secondary_zone_codes: List[str]
    accepts_cross_zone: bool
    skill_level: int
    max_daily_turnovers: int
    quality_score: float
    status: str
    pending_payout_cents: int
    completed_turnover_count: int
    decline_count: int
    strike_count: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    property_id: str
    external_ref: str
    guest_name: str
    checkin_at: str
    checkout_at: str
    party_size: int
    pet_stay: bool
    late_checkout_until_at: Optional[str]
    early_checkin_at: Optional[str]
    actual_checkout_at: Optional[str]
    status: str
    checkin_gate: str
    guest_notice_code: str
    cleanliness_rating: Optional[int]
    cleanliness_rated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Turnover(TypedDict):
    id: str
    property_id: str
    outgoing_booking_id: str
    incoming_booking_id: Optional[str]
    window_start_at: str
    window_end_at: str
    window_minutes: int
    required_minutes: int
    slack_minutes: int
    turn_type: str
    is_tight: bool
    escalation_required: bool
    status: str
    pre_hold_status: Optional[str]
    blocking_repair_order_id: Optional[str]
    checklist_task_count: int
    rejected_review_count: int
    rework_round: int
    started_at: Optional[str]
    finished_at: Optional[str]
    late_minutes: int
    restock_chargeback_cents: int
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    turnover_id: str
    cleaner_id: str
    sequence_no: int
    selection_mode: str
    match_score: float
    zone_match_factor: float
    assigned_by_user_id: str
    status: str
    accepted_at: Optional[str]
    declined_at: Optional[str]
    revoked_at: Optional[str]
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChecklistTask(TypedDict):
    id: str
    turnover_id: str
    task_code: str
    category: str
    sequence_no: int
    requires_photo: bool
    status: str
    photo_uri: Optional[str]
    note: Optional[str]
    submitted_at: Optional[str]
    reviewed_by_user_id: Optional[str]
    reject_reason: Optional[str]
    reject_count: int
    restock_line_count: int
    restock_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class SupplyLine(TypedDict):
    id: str
    property_id: str
    sku: str
    name: str
    category: str
    unit: str
    unit_cost_cents: int
    par_qty: int
    reorder_point: int
    on_hand_qty: int
    below_par: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class StockMovement(TypedDict):
    """Append-only evidence row: id and created_at only, no updated_at, no version."""
    id: str
    supply_line_id: str
    turnover_id: Optional[str]
    checklist_task_id: Optional[str]
    sequence_no: int
    reason: str
    delta_qty: int
    unit_cost_cents_at_time: int
    charge_cents: int
    note: Optional[str]
    created_at: str


class IssueReport(TypedDict):
    id: str
    turnover_id: str
    property_id: str
    reported_by_cleaner_id: Optional[str]
    issue_type: str
    severity: str
    description: str
    estimated_cost_cents: int
    guest_chargeable: bool
    status: str
    owner_notified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict):
    id: str
    issue_report_id: str
    property_id: str
    vendor_name: str
    scheduled_at: str
    blocks_checkin: bool
    actual_cost_cents: Optional[int]
    completion_note: Optional[str]
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QualityAudit(TypedDict):
    id: str
    turnover_id: str
    cleaner_id: str
    auditor_user_id: str
    score: int
    findings: Optional[str]
    variant_applied: Optional[str]
    guest_rating_at_audit: Optional[int]
    observed_score: Optional[float]
    resulting_quality_score: Optional[float]
    pay_adjustment_cents: int
    status: str
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayLine(TypedDict):
    id: str
    assignment_id: str
    cleaner_id: str
    turnover_id: str
    variant: str
    size_base_cents: int
    rush_premium_cents: int
    tight_window_premium_cents: int
    cross_zone_premium_cents: int
    linen_units: int
    linen_adder_cents: int
    gross_cents: int
    late_minutes: int
    late_penalty_cents: int
    photo_penalty_cents: int
    penalty_cents: int
    on_time_bonus_cents: int
    photo_pass_bonus_cents: int
    bonus_cents: int
    audit_adjustment_cents: int
    net_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
