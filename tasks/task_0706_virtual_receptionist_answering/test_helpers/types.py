"""Domain types: entity TypedDicts, status enums, role enum.

All names mirror the Virtual Receptionist PRD exactly.
"""
from enum import Enum
from typing import TypedDict, List


# --- Roles -------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ACCOUNT_OWNER = "AccountOwner"
    RECEPTIONIST = "Receptionist"


# --- Enums (status / model axes) --------------------------------------------
class BillingModel(str, Enum):
    PER_MINUTE = "PER_MINUTE"
    PER_CALL = "PER_CALL"


class MinuteRounding(str, Enum):
    CEIL_MINUTE = "CEIL_MINUTE"


class Language(str, Enum):
    EN = "EN"
    ES = "ES"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    SUSPENDED = "SUSPENDED"


class ScriptStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class AfterHoursAction(str, Enum):
    VOICEMAIL = "VOICEMAIL"
    OVERFLOW = "OVERFLOW"


class OverflowAction(str, Enum):
    QUEUE = "QUEUE"
    VOICEMAIL = "VOICEMAIL"


class SpamRuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class ReceptionistStatus(str, Enum):
    OFFLINE = "OFFLINE"
    AVAILABLE = "AVAILABLE"
    BUSY = "BUSY"


class WindowStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class SlotStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CallHandlingStatus(str, Enum):
    RINGING = "RINGING"
    ANSWERED = "ANSWERED"
    IN_PROGRESS = "IN_PROGRESS"
    WRAP_UP = "WRAP_UP"
    COMPLETED = "COMPLETED"
    OVERFLOW = "OVERFLOW"
    SCREENED_OUT = "SCREENED_OUT"
    ABANDONED = "ABANDONED"


class CallBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    BILLED = "BILLED"
    DISPUTED = "DISPUTED"
    ADJUSTED = "ADJUSTED"


class MessageStatus(str, Enum):
    NEW = "NEW"
    HANDED_OFF = "HANDED_OFF"


class EscalationReason(str, Enum):
    LONG_RUNNING = "LONG_RUNNING"
    CALLER_REQUEST = "CALLER_REQUEST"
    LANGUAGE = "LANGUAGE"


class EscalationStatus(str, Enum):
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    RESOLVED = "RESOLVED"


class CrmTarget(str, Enum):
    SALESFORCE = "SALESFORCE"
    HUBSPOT = "HUBSPOT"
    ZOHO = "ZOHO"


class CrmHandoffStatus(str, Enum):
    PUSHED = "PUSHED"
    FAILED = "FAILED"


class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    RESCHEDULE_REQUESTED = "RESCHEDULE_REQUESTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class BillingPeriodStatus(str, Enum):
    OPEN = "OPEN"
    PENDING_CLOSE = "PENDING_CLOSE"
    CLOSED = "CLOSED"


# --- Entity TypedDicts -------------------------------------------------------
# ServicePlan: immutable price card. Carries ONLY id + created_at
# (no updated_at, no version).
class ServicePlan(TypedDict):
    id: str
    name: str
    billing_model: str
    included_minutes: int
    included_calls: int
    base_fee_cents: int
    overage_rate_cents: int
    overage_tier2_threshold: int
    overage_tier2_rate_cents: int
    hard_cap_overage_cents: int
    minute_rounding: str
    created_at: str


class ClientAccount(TypedDict):
    id: str
    business_name: str
    plan_id: str
    default_language: str
    status: str
    current_period_id: str
    open_call_count: int
    lifetime_calls_answered: int
    created_at: str
    updated_at: str
    version: int


class CallScript(TypedDict):
    id: str
    account_id: str
    greeting_en: str
    greeting_es: str
    business_open_minute: int
    business_close_minute: int
    after_hours_action: str
    overflow_action: str
    escalation_threshold_seconds: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SpamRule(TypedDict):
    id: str
    account_id: str
    blocked_area_codes: List[str]
    spam_score_threshold: int
    anonymous_penalty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Receptionist(TypedDict):
    id: str
    display_name: str
    languages: List[str]
    max_concurrent_calls: int
    status: str
    active_call_count: int
    created_at: str
    updated_at: str
    version: int


class AvailabilityWindow(TypedDict):
    id: str
    receptionist_id: str
    start_minute: int
    end_minute: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CalendarSlot(TypedDict):
    id: str
    account_id: str
    window_start: str
    window_end: str
    buffer_minutes: int
    capacity: int
    booked_count: int
    available_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Call(TypedDict):
    id: str
    account_id: str
    script_id: str
    caller_id: str
    requested_language: str
    received_minute: int
    is_after_hours: bool
    spam_score: int
    answered_by_receptionist_id: str
    handling_status: str
    billing_status: str
    start_second: int
    end_second: int
    duration_seconds: int
    billed_units: int
    charge_cents: int
    created_at: str
    updated_at: str
    version: int


class Message(TypedDict):
    id: str
    call_id: str
    caller_name: str
    callback_number: str
    body: str
    is_lead: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Escalation(TypedDict):
    id: str
    call_id: str
    reason: str
    escalated_to_receptionist_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CrmHandoff(TypedDict):
    id: str
    call_id: str
    crm_target: str
    messages_pushed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    account_id: str
    slot_id: str
    origin_call_id: str
    start_at: str
    end_at: str
    status: str
    reschedule_count: int
    created_at: str
    updated_at: str
    version: int


class BillingPeriod(TypedDict):
    id: str
    account_id: str
    plan_id: str
    period_index: int
    included_units: int
    consumed_units: int
    overage_units: int
    overage_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
