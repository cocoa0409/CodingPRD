"""Domain types for the whole-home leak-detection API.

Role enum, every status enum and one TypedDict per entity, all named exactly as
the PRD names them.  Every entity except `TelemetryReading` carries `id`,
`created_at`, `updated_at` and `version`; a telemetry reading is immutable and
carries only `id` and `created_at` (PRD §2.4).
"""

from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    HOMEOWNER = "Homeowner"
    INSTALLER_TECH = "InstallerTech"
    DEVICE_GATEWAY = "DeviceGateway"
    INSURER_ANALYST = "InsurerAnalyst"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    PROGRAM_ADMIN = "ProgramAdmin"


# --------------------------------------------------------------------------
# Account and property
# --------------------------------------------------------------------------
class NotificationChannel(str, Enum):
    SMS = "SMS"
    EMAIL = "EMAIL"
    PUSH = "PUSH"


class AccountState(str, Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class VerificationState(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"


class ContactStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class PropertyState(str, Enum):
    ACTIVE = "ACTIVE"
    TRANSFER_PENDING = "TRANSFER_PENDING"
    ARCHIVED = "ARCHIVED"


# --------------------------------------------------------------------------
# Device: three independent dimensions
# --------------------------------------------------------------------------
class ModelCode(str, Enum):
    FLO_SMART_3_4 = "FLO_SMART_3_4"
    FLO_SMART_1_0 = "FLO_SMART_1_0"


class LifecycleState(str, Enum):
    REGISTERED = "REGISTERED"
    INSTALL_VERIFIED = "INSTALL_VERIFIED"
    LEARNING = "LEARNING"
    ARMED = "ARMED"
    TRANSFER_PENDING = "TRANSFER_PENDING"
    DECOMMISSIONED = "DECOMMISSIONED"


class ValveState(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class MonitorMode(str, Enum):
    NORMAL = "NORMAL"
    VACATION = "VACATION"
    SNOOZE = "SNOOZE"


class ValveCommand(str, Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"


# --------------------------------------------------------------------------
# Baseline profile and telemetry
# --------------------------------------------------------------------------
class LearningState(str, Enum):
    COLLECTING = "COLLECTING"
    COMPLETE = "COMPLETE"
    INVALIDATED = "INVALIDATED"


class InvalidatedReason(str, Enum):
    FIRMWARE_UPDATE = "FIRMWARE_UPDATE"
    OWNERSHIP_TRANSFER = "OWNERSHIP_TRANSFER"
    FALSE_POSITIVE_THRESHOLD = "FALSE_POSITIVE_THRESHOLD"


class ReadingSource(str, Enum):
    DEVICE = "DEVICE"
    MANUAL_TEST = "MANUAL_TEST"


class Classification(str, Enum):
    NONE = "NONE"
    DRIP = "DRIP"
    RUNNING_FIXTURE = "RUNNING_FIXTURE"
    CATASTROPHIC_BURST = "CATASTROPHIC_BURST"


class AnomalyClassification(str, Enum):
    DRIP = "DRIP"
    RUNNING_FIXTURE = "RUNNING_FIXTURE"
    CATASTROPHIC_BURST = "CATASTROPHIC_BURST"


# --------------------------------------------------------------------------
# Alerting
# --------------------------------------------------------------------------
class EventState(str, Enum):
    DETECTED = "DETECTED"
    SUPPRESSED = "SUPPRESSED"
    ALERTED = "ALERTED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    FALSE_POSITIVE = "FALSE_POSITIVE"


class SuppressionReason(str, Enum):
    DEVICE_NOT_ARMED = "DEVICE_NOT_ARMED"
    SNOOZE_ACTIVE = "SNOOZE_ACTIVE"
    DUPLICATE_WITHIN_COOLDOWN = "DUPLICATE_WITHIN_COOLDOWN"


class FeedbackLabel(str, Enum):
    TRUE_POSITIVE = "TRUE_POSITIVE"
    FALSE_POSITIVE = "FALSE_POSITIVE"


class TicketStage(str, Enum):
    PENDING_HOMEOWNER = "PENDING_HOMEOWNER"
    PENDING_EMERGENCY_CONTACT = "PENDING_EMERGENCY_CONTACT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    EXPIRED = "EXPIRED"


class TicketExpiryReason(str, Enum):
    CONTACT_SLA_BREACH = "CONTACT_SLA_BREACH"
    NO_ELIGIBLE_CONTACT = "NO_ELIGIBLE_CONTACT"
    ACCOUNT_DEACTIVATED = "ACCOUNT_DEACTIVATED"
    EVENT_CLOSED = "EVENT_CLOSED"


class IrrigationWindowStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED_BY_SHUTOFF = "SUSPENDED_BY_SHUTOFF"
    CANCELLED = "CANCELLED"


# --------------------------------------------------------------------------
# Insurer credit program
# --------------------------------------------------------------------------
class CreditState(str, Enum):
    PENDING_ENROLLMENT = "PENDING_ENROLLMENT"
    CREDIT_ACTIVE = "CREDIT_ACTIVE"
    CREDIT_SUSPENDED = "CREDIT_SUSPENDED"
    TERMINATED = "TERMINATED"


class SuspendedReason(str, Enum):
    DEVICE_NOT_ARMED = "DEVICE_NOT_ARMED"
    UPTIME_BELOW_FLOOR = "UPTIME_BELOW_FLOOR"
    OWNERSHIP_TRANSFER = "OWNERSHIP_TRANSFER"


class AttestationStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED_AWARDED = "FINALIZED_AWARDED"
    FINALIZED_DENIED = "FINALIZED_DENIED"


class AttestationDenialReason(str, Enum):
    UPTIME_BELOW_FLOOR = "UPTIME_BELOW_FLOOR"
    DEVICE_NOT_ARMED = "DEVICE_NOT_ARMED"
    NO_ENROLLED_DEVICE = "NO_ENROLLED_DEVICE"


# --------------------------------------------------------------------------
# Claims
# --------------------------------------------------------------------------
class ClaimType(str, Enum):
    WARRANTY_DEVICE = "WARRANTY_DEVICE"
    WATER_DAMAGE = "WATER_DAMAGE"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class ClaimDecision(str, Enum):
    BEGIN_REVIEW = "BEGIN_REVIEW"
    REQUEST_INFO = "REQUEST_INFO"
    SUPPLY_INFO = "SUPPLY_INFO"
    APPROVE = "APPROVE"
    DENY = "DENY"
    PAY = "PAY"


class PayoutVariant(str, Enum):
    MITIGATED = "MITIGATED"
    UNMITIGATED = "UNMITIGATED"
    WARRANTY_FLAT = "WARRANTY_FLAT"


class ClaimDenialReason(str, Enum):
    NO_QUALIFYING_EVENT = "NO_QUALIFYING_EVENT"
    OVERRIDE_DEFEATED_MITIGATION = "OVERRIDE_DEFEATED_MITIGATION"
    INSUFFICIENT_DOCUMENTATION = "INSUFFICIENT_DOCUMENTATION"
    ACCOUNT_CLOSED = "ACCOUNT_CLOSED"


# --------------------------------------------------------------------------
# Transfers
# --------------------------------------------------------------------------
class TransferStatus(str, Enum):
    INITIATED = "INITIATED"
    ACCEPTED = "ACCEPTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class TransferCancelReason(str, Enum):
    SUPERSEDED = "SUPERSEDED"
    ACCOUNT_DEACTIVATED = "ACCOUNT_DEACTIVATED"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class CommonRecord(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Homeowner(CommonRecord):
    full_name: str
    email: str
    phone_e164: str
    notification_channel: str
    account_state: str
    deactivated_at: Optional[str]
    owned_property_count: int


class EmergencyContact(CommonRecord):
    homeowner_id: str
    full_name: str
    phone_e164: str
    priority_rank: int
    verification_state: str
    status: str
    last_notified_at: Optional[str]


class Property(CommonRecord):
    homeowner_id: str
    address_line1: str
    city: str
    state_code: str
    postal_code: str
    year_built: int
    irrigation_present: bool
    property_state: str
    archived_at: Optional[str]


class Device(CommonRecord):
    property_id: str
    serial_number: str
    model_code: str
    firmware_version: str
    lifecycle_state: str
    valve_state: str
    monitor_mode: str
    install_verified_by_user_id: Optional[str]
    install_verified_at: Optional[str]
    installed_static_pressure_psi: Optional[float]
    close_count: int
    reopen_count: int
    last_shutoff_at: Optional[str]
    last_reading_at: Optional[str]
    vacation_started_at: Optional[str]
    vacation_ends_at: Optional[str]
    snooze_window_start_at: Optional[str]
    snooze_window_end_at: Optional[str]
    monitor_mode_updated_at: str
    baseline_ready: bool
    decommissioned_at: Optional[str]


class BaselineProfile(CommonRecord):
    device_id: str
    learning_state: str
    learning_started_at: str
    learning_cycle_no: int
    sample_count: int
    baseline_static_pressure_psi: Optional[float]
    baseline_peak_flow_gpm: Optional[float]
    drip_threshold_gpm: Optional[float]
    baseline_version: int
    false_positive_count: int
    last_false_positive_at: Optional[str]
    invalidated_reason: Optional[str]
    completed_at: Optional[str]


class TelemetryReading(TypedDict):
    """Immutable: only `id` and `created_at`, with no `version` (PRD §2.4)."""

    id: str
    created_at: str
    device_id: str
    reading_at: str
    static_pressure_psi: float
    flow_gpm: float
    duration_minutes: float
    total_gallons: float
    reading_source: str
    classification_at_ingest: str
    suppressed_by_irrigation: bool
    baseline_eligible: bool
    coverage_minutes: float
    anomaly_event_created: bool


class AnomalyEvent(CommonRecord):
    device_id: str
    telemetry_reading_id: str
    classification: str
    severity_score: float
    event_state: str
    detected_at: str
    suppression_reason: Optional[str]
    auto_shutoff_executed: bool
    shutoff_latency_minutes: Optional[float]
    override_reopen_at: Optional[str]
    mitigation_credited: bool
    observed_flow_gpm: float
    observed_duration_minutes: float
    observed_gallons: float
    baseline_version_used: int
    resolved_at: Optional[str]
    resolution_note: Optional[str]
    feedback_label: Optional[str]


class EscalationTicket(CommonRecord):
    anomaly_event_id: str
    notified_contact_id: Optional[str]
    stage: str
    homeowner_deadline_at: str
    contact_deadline_at: Optional[str]
    escalated_at: Optional[str]
    acknowledged_at: Optional[str]
    acknowledged_by_user_id: Optional[str]
    expiry_reason: Optional[str]
    notification_attempt_count: int


class IrrigationWindow(CommonRecord):
    property_id: str
    label: str
    start_at: str
    end_at: str
    expected_max_flow_gpm: float
    status: str
    suspended_at: Optional[str]


class InsurancePolicy(CommonRecord):
    property_id: str
    insurer_code: str
    policy_number: str
    annual_premium_cents: int
    deductible_cents: int
    policy_year_start_at: str
    credit_state: str
    current_credit_tier_pct: float
    credited_cents_total: int
    clawback_cents_total: int
    true_up_cents: int
    paid_payout_cents_total: int
    finalized_period_count: int
    avg_uptime_pct: Optional[float]
    last_attestation_end_at: Optional[str]
    suspended_reason: Optional[str]


class CreditAttestation(CommonRecord):
    policy_id: str
    period_start_at: str
    period_end_at: str
    status: str
    period_minutes: float
    covered_minutes: Optional[float]
    uptime_pct: Optional[float]
    offline_gap_count: Optional[int]
    tier_pct: Optional[float]
    credit_cents_awarded: int
    true_up_cents: int
    is_policy_year_close: bool
    device_snapshot_lifecycle_state: Optional[str]
    denial_reason: Optional[str]
    finalized_at: Optional[str]


class ReimbursementClaim(CommonRecord):
    policy_id: str
    device_id: str
    anomaly_event_id: Optional[str]
    claim_type: str
    documented_loss_cents: int
    submitted_by_user_id: str
    status: str
    payout_variant: Optional[str]
    approved_payout_cents: int
    deductible_applied_cents: int
    info_request_count: int
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    denial_reason: Optional[str]
    paid_at: Optional[str]


class DeviceTransfer(CommonRecord):
    device_id: str
    from_homeowner_id: str
    to_homeowner_id: str
    status: str
    initiated_at: str
    expires_at: str
    accepted_at: Optional[str]
    accepted_by_user_id: Optional[str]
    cancel_reason: Optional[str]
    transfer_note: Optional[str]
