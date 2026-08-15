"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Vendors, reps, rooms, sterilizer
units, cases, requests, trays, turns, escalations, passes, pickups, claims,
and penalties carry the four system-managed fields (id, created_at,
updated_at, version). CaseDelayEvent and CheckInEvent are event records and
carry only id + created_at — both updated_at and version are absent.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class CredentialStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class OrAccessLevel(str, Enum):
    NONE = "NONE"
    OBSERVER = "OBSERVER"
    SCRUB_ASSIST = "SCRUB_ASSIST"


class CaseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DelayCause(str, Enum):
    VENDOR_LATE_DELIVERY = "VENDOR_LATE_DELIVERY"
    STERILIZATION_TURNAROUND = "STERILIZATION_TURNAROUND"
    REP_ACCESS_ISSUE = "REP_ACCESS_ISSUE"
    PATIENT = "PATIENT"
    STAFFING = "STAFFING"
    OTHER = "OTHER"


class PriorityClass(str, Enum):
    STANDARD = "STANDARD"
    URGENT = "URGENT"
    EMERGENT = "EMERGENT"


class RequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    CLOSED = "CLOSED"


class Readiness(str, Enum):
    NOT_READY = "NOT_READY"
    AT_RISK = "AT_RISK"
    READY = "READY"


class TrayStatus(str, Enum):
    EXPECTED = "EXPECTED"
    DELIVERY_PENDING = "DELIVERY_PENDING"
    CHECKED_IN = "CHECKED_IN"
    PROCESSING = "PROCESSING"
    QUARANTINED = "QUARANTINED"
    STERILE_READY = "STERILE_READY"
    STAGED = "STAGED"
    IN_USE = "IN_USE"
    USED = "USED"
    AWAITING_PICKUP = "AWAITING_PICKUP"
    PICKED_UP = "PICKED_UP"
    RECONCILED = "RECONCILED"
    MISSING = "MISSING"
    CANCELLED = "CANCELLED"


class CheckInStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"


class TurnStatus(str, Enum):
    DECONTAMINATING = "DECONTAMINATING"
    STERILIZING = "STERILIZING"
    COOLDOWN = "COOLDOWN"
    RELEASED = "RELEASED"
    FAILED_QA = "FAILED_QA"


class EscalationType(str, Enum):
    MISSING_TRAY = "MISSING_TRAY"
    INCOMPLETE_COUNT = "INCOMPLETE_COUNT"
    DOCUMENTATION = "DOCUMENTATION"
    STERILIZATION_DELAY = "STERILIZATION_DELAY"
    LATE_DELIVERY = "LATE_DELIVERY"


class EscalationStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class ResolutionType(str, Enum):
    BACKFILL_DELIVERY = "BACKFILL_DELIVERY"
    SUBSTITUTE_APPROVED = "SUBSTITUTE_APPROVED"
    CASE_RESCHEDULED = "CASE_RESCHEDULED"
    CASE_CANCELLED = "CASE_CANCELLED"
    WAIVED = "WAIVED"


class PassStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    ADMITTED = "ADMITTED"
    EXITED = "EXITED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class PickupStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"


class DamageType(str, Enum):
    LOSS = "LOSS"
    DAMAGE = "DAMAGE"
    CONTAMINATION = "CONTAMINATION"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    APPORTIONED = "APPORTIONED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"


class PenaltyStatus(str, Enum):
    ACCRUING = "ACCRUING"
    ASSESSED = "ASSESSED"
    SETTLED = "SETTLED"
    WAIVED_CLOSED = "WAIVED_CLOSED"
    VOID = "VOID"


class UserRole(str, Enum):
    VENDOR_COORDINATOR = "VendorCoordinator"
    OR_SCHEDULER = "ORScheduler"
    STERILE_PROCESSING_TECH = "SterileProcessingTech"
    OR_CIRCULATOR_NURSE = "ORCirculatorNurse"
    VENDOR_REP = "VendorRep"


# ---------------------------------------------------------------------------
# Entity TypedDicts (system-managed fields included per PRD common fields)
# ---------------------------------------------------------------------------

class Vendor(TypedDict, total=False):
    id: str
    vendor_name: str
    vendor_code: str
    status: str
    late_grace_minutes: int
    late_rate_per_hour_cents: int
    late_penalty_cap_cents: int
    delay_surcharge_per_minute_cents: int
    outstanding_penalty_cents: int
    outstanding_liability_cents: int
    created_at: str
    updated_at: str
    version: int


class VendorRep(TypedDict, total=False):
    id: str
    vendor_id: str
    full_name: str
    rep_email: str
    credential_doc_ref: str
    credential_status: str
    credential_expires_at: Optional[str]
    or_access_level: str
    created_at: str
    updated_at: str
    version: int


class ORRoom(TypedDict, total=False):
    id: str
    room_name: str
    turnover_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class SterilizerUnit(TypedDict, total=False):
    id: str
    unit_name: str
    slot_capacity: int
    cycle_minutes: int
    cooldown_minutes: int
    created_at: str
    updated_at: str
    version: int


class SurgicalCase(TypedDict, total=False):
    id: str
    case_number: str
    or_room_id: str
    procedure_type: str
    surgeon_name: str
    scheduled_start_at: str
    scheduled_end_at: str
    actual_start_at: Optional[str]
    actual_end_at: Optional[str]
    status: str
    delay_minutes_provisional: int
    vendor_delay_minutes_provisional: int
    vendor_delay_minutes_final: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CaseDelayEvent(TypedDict, total=False):
    # Event record: id + created_at only — NO updated_at, NO version.
    id: str
    case_id: str
    cause: str
    minutes: int
    attributable_request_id: Optional[str]
    recorded_by_role: str
    created_at: str


class LoanerRequest(TypedDict, total=False):
    id: str
    case_id: str
    vendor_id: str
    priority_class: str
    status: str
    readiness: str
    required_delivery_by: Optional[str]
    penalty_exposure_cents: int
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LoanerTray(TypedDict, total=False):
    id: str
    request_id: str
    tray_code: str
    declared_instrument_count: int
    implant_flag: bool
    replacement_value_cents: int
    status: str
    delivered_instrument_count: Optional[int]
    returned_instrument_count: Optional[int]
    shortage_count: int
    rework_count: int
    required_sterile_ready_by: Optional[str]
    projected_sterile_ready_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CheckInEvent(TypedDict, total=False):
    # Event record: id + created_at only — NO updated_at, NO version.
    id: str
    request_id: str
    rep_id: str
    delivered_at: str
    lines: List[dict]
    ifu_provided: bool
    implant_log_provided: bool
    loaner_agreement_ref: str
    status: str
    verified_by_user_id: Optional[str]
    late_minutes: int
    created_at: str


class SterilizationTurn(TypedDict, total=False):
    id: str
    tray_id: str
    sterilizer_unit_id: Optional[str]
    attempt_number: int
    status: str
    decon_started_at: str
    cycle_started_at: Optional[str]
    cycle_completed_at: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Escalation(TypedDict, total=False):
    id: str
    request_id: str
    type: str
    linked_tray_id: Optional[str]
    status: str
    resolution_type: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ORAccessPass(TypedDict, total=False):
    id: str
    rep_id: str
    case_id: str
    window_start_at: Optional[str]
    window_end_at: Optional[str]
    status: str
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PickupRecord(TypedDict, total=False):
    id: str
    request_id: str
    rep_id: str
    picked_up_at: str
    lines: List[dict]
    status: str
    reconciled_by_user_id: Optional[str]
    discrepancy_count: int
    created_at: str
    updated_at: str
    version: int


class DamageLossClaim(TypedDict, total=False):
    id: str
    tray_id: str
    request_id: str
    pickup_id: Optional[str]
    claim_seq: int
    damage_type: str
    shortage_count: int
    claimed_amount_cents: int
    provisional_vendor_share_cents: int
    final_vendor_share_cents: Optional[int]
    final_hospital_share_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class PenaltyAssessment(TypedDict, total=False):
    id: str
    request_id: str
    check_in_id: str
    late_minutes: int
    billable_minutes: int
    time_charge_cents: int
    delay_surcharge_cents: int
    assessed_cents: int
    waived_cents: int
    settled_cents: int
    outstanding_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
