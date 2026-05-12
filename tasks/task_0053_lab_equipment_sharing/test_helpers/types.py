"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror PRD prose exactly. Per PRD §2.4:

- Versioned entities (id + created_at + updated_at + version):
  Lab, User, Equipment, MaintenanceWindow, Authorization, Reservation.

- Append-only entities (id + created_at ONLY; NO updated_at, NO version):
  BillingRule, UsageLog, AuditEvent.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    LAB_OWNER = "LabOwner"
    USER = "User"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class EquipmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class BillingRuleStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class MaintenanceWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_ACCEPTANCE = "AWAITING_ACCEPTANCE"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AuthorizationStatus(str, Enum):
    PENDING_OWNER = "PENDING_OWNER"
    PENDING_PLATFORM = "PENDING_PLATFORM"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ReservationStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


# ---------------------------------------------------------------------------
# Other enums
# ---------------------------------------------------------------------------
class Affiliation(str, Enum):
    WITHIN_SCHOOL = "WITHIN_SCHOOL"
    INTER_SCHOOL = "INTER_SCHOOL"
    EXTERNAL = "EXTERNAL"


class ValueTier(str, Enum):
    STANDARD = "STANDARD"
    HIGH_VALUE = "HIGH_VALUE"


class SharingScope(str, Enum):
    WITHIN_SCHOOL = "WITHIN_SCHOOL"
    INTER_SCHOOL = "INTER_SCHOOL"
    EXTERNAL = "EXTERNAL"


class SlotGranularity(str, Enum):
    HOUR = "HOUR"
    HALF_DAY = "HALF_DAY"
    DAY = "DAY"


class BillingMode(str, Enum):
    BY_TIME = "BY_TIME"
    BY_SAMPLE = "BY_SAMPLE"
    HYBRID = "HYBRID"


class Urgency(str, Enum):
    NORMAL = "NORMAL"
    URGENT = "URGENT"


class MaintenanceKind(str, Enum):
    PERIODIC = "PERIODIC"
    AD_HOC = "AD_HOC"


class PriorityTier(str, Enum):
    PEAK = "PEAK"
    OFF_PEAK = "OFF_PEAK"


class StatusHandover(str, Enum):
    NORMAL = "NORMAL"
    ABNORMAL = "ABNORMAL"


class AuditSubjectType(str, Enum):
    RESERVATION = "RESERVATION"
    AUTHORIZATION = "AUTHORIZATION"


# ---------------------------------------------------------------------------
# Entity TypedDicts — versioned (PRD §2.4)
# ---------------------------------------------------------------------------
class Lab(TypedDict, total=False):
    id: str
    name: str
    institution: str
    department: str
    contact_user_id: str
    revenue_share_bps: int
    settlement_balance_cents: int
    lifetime_settled_cents: int
    created_at: str
    updated_at: str
    version: int


class User(TypedDict, total=False):
    id: str
    external_user_id: str
    full_name: str
    department: str
    affiliation: str
    training_certificates: List[str]
    identity_verified: bool
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict, total=False):
    id: str
    lab_id: str
    model: str
    specification: str
    value_tier: str
    sharing_scope: str
    slot_granularity: str
    lead_time_hours: int
    single_user_duration_limit_hours: int
    peak_window_start_hour: int
    peak_window_end_hour: int
    status: str
    calibration_cert_id: str
    calibration_expires_at: str
    safety_inspection_cert_id: str
    safety_inspection_expires_at: str
    photo_uri: str
    operation_manual_uri: str
    active_billing_rule_id: Optional[str]
    required_training_codes: List[str]
    allowed_sample_types: List[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceWindow(TypedDict, total=False):
    id: str
    equipment_id: str
    kind: str
    start_at: str
    end_at: str
    status: str
    maintenance_notes: Optional[str]
    acceptance_notes: Optional[str]
    archived_record_uri: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Authorization(TypedDict, total=False):
    id: str
    equipment_id: str
    user_id: str
    sample_type: str
    urgency: str
    status: str
    approved_at: Optional[str]
    expires_at: Optional[str]
    owner_decision_user_id: Optional[str]
    platform_decision_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict, total=False):
    id: str
    equipment_id: str
    user_id: str
    authorization_id: str
    start_at: str
    end_at: str
    requested_sample_count: int
    priority_tier: str
    status: str
    billing_rule_id_pinned: Optional[str]
    estimated_fee_cents: int
    final_fee_cents: int
    estimated_platform_fee_cents: int
    final_platform_fee_cents: int
    estimated_owner_share_cents: int
    final_owner_share_cents: int
    cancelled_at: Optional[str]
    cancellation_refund_bps: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Entity TypedDicts — append-only (PRD §2.4)
# ---------------------------------------------------------------------------
class BillingRule(TypedDict, total=False):
    id: str
    equipment_id: str
    rule_version: Optional[int]
    mode: str
    internal_rate_per_hour_cents: int
    external_rate_per_hour_cents: int
    inter_school_rate_per_hour_cents: int
    internal_rate_per_sample_cents: int
    external_rate_per_sample_cents: int
    inter_school_rate_per_sample_cents: int
    peak_multiplier_bps: int
    consumables_flat_cents: int
    platform_fee_bps: int
    status: str
    published_at: Optional[str]
    created_at: str


class UsageLog(TypedDict, total=False):
    id: str
    reservation_id: str
    check_in_at: str
    check_out_at: Optional[str]
    actual_duration_minutes: int
    actual_sample_count: Optional[int]
    abnormal_event_code: Optional[str]
    status_handover: Optional[str]
    created_at: str


class AuditEvent(TypedDict, total=False):
    id: str
    subject_type: str
    subject_id: str
    actor_role: str
    actor_user_id: str
    action: str
    from_state: Optional[str]
    to_state: str
    payload_json: Dict[str, Any]
    created_at: str


__all__ = [
    "UserRole",
    "EquipmentStatus",
    "BillingRuleStatus",
    "MaintenanceWindowStatus",
    "AuthorizationStatus",
    "ReservationStatus",
    "Affiliation",
    "ValueTier",
    "SharingScope",
    "SlotGranularity",
    "BillingMode",
    "Urgency",
    "MaintenanceKind",
    "PriorityTier",
    "StatusHandover",
    "AuditSubjectType",
    "Lab",
    "User",
    "Equipment",
    "MaintenanceWindow",
    "Authorization",
    "Reservation",
    "BillingRule",
    "UsageLog",
    "AuditEvent",
]
