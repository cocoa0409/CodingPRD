"""Domain types: entity TypedDicts, status enums, role enum (PRD 2.1, 2.5, 2.6, 3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    MONITORING_AGENT = "MonitoringAgent"
    CAREGIVER = "Caregiver"
    SENIOR = "Senior"
    INSTALLER = "Installer"
    DEVICE_HUB = "DeviceHub"


class MonitoringPosture(str, Enum):
    INACTIVE = "INACTIVE"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"


class RiskTier(str, Enum):
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"


class PlanTier(str, Enum):
    ESSENTIAL = "ESSENTIAL"
    PLUS = "PLUS"
    PREMIUM = "PREMIUM"


class WellnessReportCadence(str, Enum):
    NONE = "NONE"
    MONTHLY = "MONTHLY"
    WEEKLY = "WEEKLY"


class ServiceStatus(str, Enum):
    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    DELINQUENT = "DELINQUENT"


class PaymentOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ProrationMode(str, Enum):
    DAILY_PRORATE = "DAILY_PRORATE"
    FULL_CYCLE_SWAP = "FULL_CYCLE_SWAP"


class KitStatus(str, Enum):
    ORDERED = "ORDERED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    INSTALLED = "INSTALLED"
    ACTIVE = "ACTIVE"


class DeviceType(str, Enum):
    GATEWAY = "GATEWAY"
    WEARABLE = "WEARABLE"
    MOTION = "MOTION"


class DeviceStatus(str, Enum):
    PROVISIONED = "PROVISIONED"
    INSTALLED = "INSTALLED"
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    DECOMMISSIONED = "DECOMMISSIONED"


class SensorEventType(str, Enum):
    HEARTBEAT = "HEARTBEAT"
    MOTION = "MOTION"
    DOOR_OPEN = "DOOR_OPEN"
    DOOR_CLOSE = "DOOR_CLOSE"
    FALL_DETECTED = "FALL_DETECTED"
    PILL_DISPENSED = "PILL_DISPENSED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ContactEntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class AlertType(str, Enum):
    FALL = "FALL"
    INACTIVITY = "INACTIVITY"
    MISSED_MEDICATION = "MISSED_MEDICATION"
    MISSED_CHECKIN = "MISSED_CHECKIN"
    DEVICE_OFFLINE = "DEVICE_OFFLINE"
    LOW_BATTERY = "LOW_BATTERY"
    MANUAL = "MANUAL"


class AlertStatus(str, Enum):
    RAISED = "RAISED"
    NOTIFYING = "NOTIFYING"
    ESCALATED = "ESCALATED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    FALSE_ALARM = "FALSE_ALARM"


class NotificationStatus(str, Enum):
    SENT = "SENT"
    ACKED = "ACKED"
    TIMED_OUT = "TIMED_OUT"
    SUPERSEDED = "SUPERSEDED"


class MedicationCriticality(str, Enum):
    ROUTINE = "ROUTINE"
    CRITICAL = "CRITICAL"


class ScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class DoseStatus(str, Enum):
    PENDING = "PENDING"
    TAKEN = "TAKEN"
    MISSED = "MISSED"
    SKIPPED = "SKIPPED"


class CheckInKind(str, Enum):
    SELF_CONFIRM = "SELF_CONFIRM"
    APP_CONFIRM = "APP_CONFIRM"
    CALL = "CALL"
    VISIT = "VISIT"


class ReportMode(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ReportStatus(str, Enum):
    READY = "READY"
    DELIVERED = "DELIVERED"


# --- Entity TypedDicts -------------------------------------------------------
# Common-field resources carry id + created_at + updated_at + version (PRD 2.5).


class Senior(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    address: str
    monitoring_posture: str
    open_alert_count: int
    risk_tier: str
    created_at: str
    updated_at: str
    version: int


class SubscriptionPlan(TypedDict, total=False):
    id: str
    tier: str
    monthly_fee_cents: int
    included_motion_sensors: int
    extra_sensor_fee_cents: int
    max_contacts: int
    checkin_interval_hours: int
    medication_reminders_enabled: bool
    wellness_report_enabled: bool
    wellness_report_cadence: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    senior_id: str
    plan_id: str
    service_status: str
    billing_status: str
    current_period_end: Optional[str]
    billing_credit_cents: int
    lifetime_charged_cents: int
    lifetime_credited_cents: int
    consecutive_failed_payments: int
    last_change_plan_credit_cents: Optional[int]
    last_change_sensor_credit_cents: Optional[int]
    last_change_total_credit_cents: Optional[int]
    last_change_total_charge_cents: Optional[int]
    last_change_net_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SensorKit(TypedDict, total=False):
    id: str
    senior_id: str
    motion_sensor_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict, total=False):
    id: str
    kit_id: str
    senior_id: str
    device_type: str
    serial: str
    status: str
    battery_percent: int
    last_seen_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Installer(TypedDict, total=False):
    id: str
    full_name: str
    region: str
    created_at: str
    updated_at: str
    version: int


class InstallAppointment(TypedDict, total=False):
    id: str
    senior_id: str
    kit_id: str
    installer_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Caregiver(TypedDict, total=False):
    id: str
    senior_id: str
    full_name: str
    phone: str
    created_at: str
    updated_at: str
    version: int


class ContactTreeEntry(TypedDict, total=False):
    id: str
    senior_id: str
    caregiver_id: str
    priority_rank: int
    min_severity: str
    response_timeout_seconds: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Alert(TypedDict, total=False):
    id: str
    senior_id: str
    device_id: Optional[str]
    alert_type: str
    severity: str
    status: str
    escalation_level: int
    escalation_exhausted: bool
    reopen_count: int
    acknowledged_by_caregiver_id: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MedicationSchedule(TypedDict, total=False):
    id: str
    senior_id: str
    medication_name: str
    times_of_day: List[str]
    window_minutes: int
    criticality: str
    start_date: str
    missed_streak: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WellnessReport(TypedDict, total=False):
    id: str
    senior_id: str
    period_start: str
    period_end: str
    mode: str
    status: str
    activity_score: float
    adherence_pct: float
    device_health_pct: float
    wellness_index: float
    fall_cap_applied: bool
    alert_count: int
    created_at: str
    updated_at: str
    version: int


# --- Append-only resources: only id + created_at (PRD 2.5) --------------------


class SensorEvent(TypedDict, total=False):
    id: str
    device_id: str
    senior_id: str
    event_type: str
    observed_at: str
    battery_percent: Optional[int]
    note: Optional[str]
    created_at: str


class AlertNotification(TypedDict, total=False):
    id: str
    alert_id: str
    contact_entry_id: str
    caregiver_id: str
    level: int
    status: str
    sent_at: str
    created_at: str


class DoseEvent(TypedDict, total=False):
    id: str
    schedule_id: str
    senior_id: str
    scheduled_at: str
    status: str
    confirmed_at: Optional[str]
    punctual: Optional[bool]
    created_at: str


class CheckIn(TypedDict, total=False):
    id: str
    senior_id: str
    caregiver_id: Optional[str]
    kind: str
    note: Optional[str]
    occurred_at: str
    created_at: str


class Dashboard(TypedDict, total=False):
    monitoring_posture: str
    open_alert_count: int
    risk_tier: str
    adherence_today_pct: float
    devices_online: int
    devices_total: int
    last_checkin_at: Optional[str]
    next_dose_scheduled_at: Optional[str]
