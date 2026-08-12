"""Domain types: entity TypedDicts, status enums and the role enum.

Naming follows the PRD exactly. Two entities — SubscriptionPlan and
DeviceCatalogEntry — are configuration rows that carry only ``id`` and
``created_at``; their TypedDicts deliberately omit ``updated_at`` and
``version`` because the PRD says neither exists on those rows nor is
returned in their payloads.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    OWNER = "Owner"
    MEMBER = "Member"
    BILLING_ADMIN = "BillingAdmin"
    SUPPORT_AGENT = "SupportAgent"
    TECHNICIAN = "Technician"
    PLATFORM_ADMIN = "PlatformAdmin"


class MemberRole(str, Enum):
    OWNER = "OWNER"
    MEMBER = "MEMBER"
    BILLING_ADMIN = "BILLING_ADMIN"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class PlanTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    PRO = "PRO"


class CoverageMode(str, Enum):
    BUSINESS_HOURS = "BUSINESS_HOURS"
    TWENTY_FOUR_SEVEN = "TWENTY_FOUR_SEVEN"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    SUSPENDED = "SUSPENDED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"


class PaymentOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class DeviceClass(str, Enum):
    HUB = "HUB"
    CAMERA = "CAMERA"
    SENSOR = "SENSOR"
    THERMOSTAT = "THERMOSTAT"
    LOCK = "LOCK"


class DeviceLifecycleStatus(str, Enum):
    CLAIMED = "CLAIMED"
    ACTIVE = "ACTIVE"
    RECLAIMABLE = "RECLAIMABLE"
    SERVICE_HOLD = "SERVICE_HOLD"
    SUSPENDED_RMA = "SUSPENDED_RMA"
    TRANSFER_PENDING = "TRANSFER_PENDING"
    DECOMMISSIONED = "DECOMMISSIONED"


class DeviceFirmwareStatus(str, Enum):
    CURRENT = "CURRENT"
    UPDATE_PENDING = "UPDATE_PENDING"
    ROLLED_BACK = "ROLLED_BACK"
    DEFERRED = "DEFERRED"
    BLOCKED = "BLOCKED"


class WarrantyBasis(str, Enum):
    BASE_ONLY = "BASE_ONLY"
    TIER_EXTENDED = "TIER_EXTENDED"


class TicketSeverity(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class TicketWorkflowStatus(str, Enum):
    NEW = "NEW"
    TRIAGED = "TRIAGED"
    REMOTE_DIAG = "REMOTE_DIAG"
    AWAITING_CUSTOMER = "AWAITING_CUSTOMER"
    DISPATCH_PENDING = "DISPATCH_PENDING"
    ONSITE = "ONSITE"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"


class TicketSlaStatus(str, Enum):
    WITHIN = "WITHIN"
    AT_RISK = "AT_RISK"
    PAUSED = "PAUSED"
    BREACHED_FIRST_RESPONSE = "BREACHED_FIRST_RESPONSE"
    BREACHED_ONSITE = "BREACHED_ONSITE"
    MET = "MET"
    CREDITED = "CREDITED"


class TicketDispatchStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED = "REQUIRED"
    SCHEDULED = "SCHEDULED"
    RESCHEDULING = "RESCHEDULING"
    NO_SHOW = "NO_SHOW"
    COMPLETED = "COMPLETED"


class EscalationReason(str, Enum):
    FAILURE_THRESHOLD = "FAILURE_THRESHOLD"
    HARDWARE_FAULT = "HARDWARE_FAULT"


class RemoteSessionStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class RemoteSessionOutcome(str, Enum):
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"
    HARDWARE_FAULT = "HARDWARE_FAULT"


class VisitSlotStatus(str, Enum):
    OPEN = "OPEN"
    BOOKED = "BOOKED"
    BLOCKED = "BLOCKED"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class VisitFeeKind(str, Enum):
    NONE = "NONE"
    LATE_CANCEL = "LATE_CANCEL"
    NO_SHOW = "NO_SHOW"


class CampaignKind(str, Enum):
    SECURITY_MANDATORY = "SECURITY_MANDATORY"
    FEATURE_OPTIONAL = "FEATURE_OPTIONAL"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    RING_ACTIVE = "RING_ACTIVE"
    HALTED = "HALTED"
    COMPLETED = "COMPLETED"


class RolloutStatus(str, Enum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    ROLLED_BACK = "ROLLED_BACK"
    DEFERRED = "DEFERRED"
    BLOCKED_BY_HALT = "BLOCKED_BY_HALT"
    BLOCKED_BY_SERVICE = "BLOCKED_BY_SERVICE"


class RolloutResult(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class AddOnOrderStatus(str, Enum):
    PLACED = "PLACED"
    FULFILLED = "FULFILLED"


class ProrationMode(str, Enum):
    MID_CYCLE_PRORATED = "MID_CYCLE_PRORATED"
    NEXT_CYCLE_FULL = "NEXT_CYCLE_FULL"


class WarrantyState(str, Enum):
    IN_WARRANTY = "IN_WARRANTY"
    EXPIRED = "EXPIRED"


class RoutingTarget(str, Enum):
    MANUFACTURER = "MANUFACTURER"
    IN_HOUSE_DEPOT = "IN_HOUSE_DEPOT"
    ADVANCE_REPLACEMENT = "ADVANCE_REPLACEMENT"
    CUSTOMER_PAID_DEPOT = "CUSTOMER_PAID_DEPOT"


class RmaStatus(str, Enum):
    OPEN = "OPEN"
    ROUTED = "ROUTED"
    ADVANCE_SHIPPED = "ADVANCE_SHIPPED"
    AWAITING_RETURN = "AWAITING_RETURN"
    RETURN_RECEIVED = "RETURN_RECEIVED"
    RETURN_WINDOW_EXPIRED = "RETURN_WINDOW_EXPIRED"
    CHARGED = "CHARGED"
    CLOSED = "CLOSED"
    SUPERSEDED = "SUPERSEDED"


class HoldState(str, Enum):
    NONE = "NONE"
    HELD = "HELD"
    RELEASED = "RELEASED"
    CHARGED = "CHARGED"


class CreditVariant(str, Enum):
    NONE = "NONE"
    BREACH_COMPOUNDED = "BREACH_COMPOUNDED"
    GOODWILL = "GOODWILL"


class CreditReason(str, Enum):
    SLA_FIRST_RESPONSE_BREACH = "SLA_FIRST_RESPONSE_BREACH"
    SLA_ONSITE_BREACH = "SLA_ONSITE_BREACH"
    CSAT_BREACH_COMPOUNDED = "CSAT_BREACH_COMPOUNDED"
    CSAT_GOODWILL = "CSAT_GOODWILL"


class BreachTier(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    SEVERE = "SEVERE"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------
class Household(TypedDict):
    id: str
    name: str
    region_code: str
    billing_email: str
    account_status: str
    suspended_at: Optional[str]
    entitled_device_count: int
    active_device_count: int
    created_at: str
    updated_at: str
    version: int


class HouseholdMember(TypedDict):
    id: str
    household_id: str
    full_name: str
    email: str
    member_role: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


# Configuration entity — id + created_at only.
class SubscriptionPlan(TypedDict):
    id: str
    tier: str
    monthly_fee_cents: int
    included_device_count: int
    overage_fee_cents_per_device: int
    coverage_mode: str
    first_response_minutes_p1: int
    first_response_minutes_p2: int
    first_response_minutes_p3: int
    onsite_resolution_hours_p1: int
    onsite_resolution_hours_p2: int
    onsite_resolution_hours_p3: int
    warranty_extension_months: int
    included_install_credits: int
    advance_replacement_eligible: bool
    created_at: str


class Subscription(TypedDict):
    id: str
    household_id: str
    plan_id: str
    pending_tier_plan_id: Optional[str]
    status: str
    allow_overage: bool
    cycle_index: int
    cycle_start_at: str
    cycle_end_at: str
    monthly_fee_cents: int
    install_credits_granted: int
    install_credits_consumed: int
    install_credits_remaining: int
    overage_device_count: int
    overage_charges_cents_this_cycle: int
    credits_issued_cents_this_cycle: int
    next_invoice_credit_cents: int
    next_invoice_adjustment_cents: int
    created_at: str
    updated_at: str
    version: int


# Configuration entity — id + created_at only.
class DeviceCatalogEntry(TypedDict):
    id: str
    model_code: str
    display_name: str
    device_class: str
    serial_prefix: str
    base_warranty_months: int
    requires_install: bool
    manufacturer_service_only: bool
    msrp_cents: int
    current_firmware_version: str
    created_at: str


class Device(TypedDict):
    id: str
    household_id: str
    catalog_entry_id: str
    transfer_target_household_id: Optional[str]
    serial_number: str
    purchase_date: str
    lifecycle_status: str
    firmware_status: str
    firmware_version: Optional[str]
    activation_token: Optional[str]
    activation_expires_at: Optional[str]
    activation_attempts: int
    activated_at: Optional[str]
    warranty_expires_at: str
    warranty_basis: str
    is_overage: bool
    created_at: str
    updated_at: str
    version: int


class Ticket(TypedDict):
    id: str
    household_id: str
    device_id: Optional[str]
    opened_by_member_id: Optional[str]
    severity: str
    summary: str
    workflow_status: str
    sla_status: str
    dispatch_status: str
    first_response_at: Optional[str]
    resolved_at: Optional[str]
    closed_at: Optional[str]
    pause_started_at: Optional[str]
    sla_paused_minutes: int
    sla_uncovered_minutes: int
    sla_counted_minutes: int
    first_response_target_minutes: int
    onsite_resolution_target_minutes: int
    remote_session_failure_count: int
    escalation_reason: Optional[str]
    survey_solicited_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemoteSession(TypedDict):
    id: str
    ticket_id: str
    agent_user_id: str
    session_index: int
    started_at: str
    ended_at: Optional[str]
    status: str
    outcome: Optional[str]
    diagnostic_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    full_name: str
    region_code: str
    skills: List[str]
    total_slot_count: int
    open_slot_count: int
    booked_slot_count: int
    blocked_slot_count: int
    created_at: str
    updated_at: str
    version: int


class VisitSlot(TypedDict):
    id: str
    technician_id: str
    region_code: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict):
    id: str
    ticket_id: str
    slot_id: str
    status: str
    scheduled_start_at: str
    scheduled_end_at: str
    cancelled_at: Optional[str]
    fee_kind: str
    fee_cents: int
    fee_waived: bool
    completion_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FirmwareCampaign(TypedDict):
    id: str
    catalog_entry_id: str
    kind: str
    target_firmware_version: str
    halt_failure_rate_pct: float
    status: str
    current_ring_index: int
    ring_window_start_at: Optional[str]
    ring_window_end_at: Optional[str]
    ring_device_count: int
    ring_failed_count: int
    ring_failure_rate: float
    created_at: str
    updated_at: str
    version: int


class FirmwareRollout(TypedDict):
    id: str
    campaign_id: str
    device_id: str
    ring_index: int
    window_start_at: str
    window_end_at: str
    status: str
    last_result: Optional[str]
    retry_count: int
    deferred_until: Optional[str]
    result_reported_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AddOnOrder(TypedDict):
    id: str
    household_id: str
    subscription_id: str
    lines: List[dict]
    status: str
    subtotal_cents: int
    bundle_discount_pct: float
    bundle_discount_cents: int
    discounted_subtotal_cents: int
    install_credits_applied: int
    install_charge_cents: int
    monthly_delta_cents: int
    proration_mode: str
    proration_cents: int
    order_total_cents: int
    fulfilled_device_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class RmaCase(TypedDict):
    id: str
    device_id: str
    ticket_id: Optional[str]
    supersedes_rma_id: Optional[str]
    warranty_state: str
    routing_target: str
    status: str
    hold_amount_cents: int
    hold_state: str
    shipped_at: Optional[str]
    return_deadline_at: Optional[str]
    returned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SatisfactionSurvey(TypedDict):
    id: str
    ticket_id: str
    score: int
    comment: Optional[str]
    submitted_at: str
    window_closes_at: str
    credit_variant: str
    credit_cents: int
    created_at: str
    updated_at: str
    version: int


class ServiceCredit(TypedDict):
    id: str
    household_id: str
    subscription_id: str
    ticket_id: str
    reason: str
    breach_tier: Optional[str]
    uncapped_amount_cents: int
    amount_cents: int
    cycle_index: int
    applied_to_cycle_index: int
    created_at: str
    updated_at: str
    version: int
