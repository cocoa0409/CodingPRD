"""Domain types: status enums, role enum and entity TypedDicts.

Every persisted resource in this system carries id, created_at, updated_at and
version, so every TypedDict below extends CommonFields.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    OWNER = "Owner"
    ACCOUNT_MANAGER = "AccountManager"
    DISPATCHER = "Dispatcher"
    FIELD_TECH = "FieldTech"
    VENDOR = "Vendor"
    STORM_COORDINATOR = "StormCoordinator"
    AUDITOR = "Auditor"


ALL_ROLES = [r.value for r in UserRole]


class OwnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class NotificationPreference(str, Enum):
    EMAIL = "EMAIL"
    SMS = "SMS"
    BOTH = "BOTH"


class TravelZone(str, Enum):
    Z1 = "Z1"
    Z2 = "Z2"
    Z3 = "Z3"
    OUT_OF_AREA = "OUT_OF_AREA"


class SeasonalState(str, Enum):
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    WINTERIZED = "WINTERIZED"
    OPENING = "OPENING"


class OccupancyState(str, Enum):
    VACANT = "VACANT"
    OWNER_IN_RESIDENCE = "OWNER_IN_RESIDENCE"
    RENTAL_OCCUPIED = "RENTAL_OCCUPIED"
    CONTRACTOR_ONSITE = "CONTRACTOR_ONSITE"


class RiskPosture(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    CRITICAL = "CRITICAL"


class PlanTier(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class RolloverPolicy(str, Enum):
    EXPIRE = "EXPIRE"
    CARRY_CAPPED = "CARRY_CAPPED"


class SubscriptionStatus(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DELINQUENT = "DELINQUENT"
    CANCELLED = "CANCELLED"


class BillingCycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class AwayPeriodDerivedStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_EFFECT = "IN_EFFECT"
    ENDED = "ENDED"


class VisitType(str, Enum):
    ROUTINE_WATCH = "ROUTINE_WATCH"
    SEASONAL_CLOSE = "SEASONAL_CLOSE"
    SEASONAL_OPEN = "SEASONAL_OPEN"
    TURNOVER_INSPECT = "TURNOVER_INSPECT"
    STORM_SECURE = "STORM_SECURE"
    STORM_ASSESS = "STORM_ASSESS"
    ALARM_RESPONSE = "ALARM_RESPONSE"


class TriggerSource(str, Enum):
    SCHEDULED = "SCHEDULED"
    OWNER_REQUESTED = "OWNER_REQUESTED"
    ALARM_TRIGGERED = "ALARM_TRIGGERED"
    STORM = "STORM"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    DEFERRED = "DEFERRED"
    CONVERTED = "CONVERTED"
    ABORTED = "ABORTED"


class DeferReason(str, Enum):
    TURNOVER_OVERLAP = "TURNOVER_OVERLAP"
    OWNER_IN_RESIDENCE = "OWNER_IN_RESIDENCE"
    WEATHER = "WEATHER"
    ACCESS_BLOCKED = "ACCESS_BLOCKED"
    SUBSCRIPTION_PAUSED = "SUBSCRIPTION_PAUSED"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FindingCategory(str, Enum):
    PLUMBING = "PLUMBING"
    HVAC = "HVAC"
    ELECTRICAL = "ELECTRICAL"
    STRUCTURAL = "STRUCTURAL"
    SECURITY = "SECURITY"
    PEST = "PEST"
    LANDSCAPE = "LANDSCAPE"
    OTHER = "OTHER"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    MONITORING = "MONITORING"
    WORK_ORDERED = "WORK_ORDERED"
    DISMISSED = "DISMISSED"


class VendorTrade(str, Enum):
    PLUMBING = "PLUMBING"
    HVAC = "HVAC"
    ELECTRICAL = "ELECTRICAL"
    GENERAL = "GENERAL"
    SECURITY = "SECURITY"
    LOCKSMITH = "LOCKSMITH"
    LANDSCAPE = "LANDSCAPE"


class BillingMode(str, Enum):
    MANAGED = "MANAGED"
    PASS_THROUGH = "PASS_THROUGH"


class VendorStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ELIGIBLE = "ELIGIBLE"
    SUSPENDED = "SUSPENDED"
    LAPSED = "LAPSED"


class WorkType(str, Enum):
    REPAIR = "REPAIR"
    REKEY = "REKEY"
    WINTERIZE_FIX = "WINTERIZE_FIX"
    STORM_MITIGATION = "STORM_MITIGATION"
    CLEANING = "CLEANING"


class Pipeline(str, Enum):
    ROUTINE = "ROUTINE"
    STORM = "STORM"


class WorkOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    INVOICED = "INVOICED"
    VOID = "VOID"


class AssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WORKING = "WORKING"
    FINISHED = "FINISHED"
    WITHDRAWN = "WITHDRAWN"


class KeyType(str, Enum):
    PHYSICAL = "PHYSICAL"
    LOCKBOX = "LOCKBOX"


class KeyIssuanceStatus(str, Enum):
    ISSUED = "ISSUED"
    RETURNED = "RETURNED"
    OVERDUE = "OVERDUE"
    RETURNED_LATE = "RETURNED_LATE"
    LOST = "LOST"
    REKEY_ORDERED = "REKEY_ORDERED"


class AccessGrantStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class InvalidatedReason(str, Enum):
    CODE_ROTATION = "CODE_ROTATION"
    KEY_LOST = "KEY_LOST"
    ASSIGNMENT_WITHDRAWN = "ASSIGNMENT_WITHDRAWN"


class RevokeReason(str, Enum):
    OPERATOR = "OPERATOR"
    WINDOW_ELAPSED = "WINDOW_ELAPSED"


class WinterizationStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"
    REOPENED = "REOPENED"


class ReopenReason(str, Enum):
    FREEZE_ALARM = "FREEZE_ALARM"
    SPRING_OPEN = "SPRING_OPEN"
    RENTAL_TURNOVER = "RENTAL_TURNOVER"
    INSPECTION_FAIL = "INSPECTION_FAIL"


class TurnoverStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKOUT = "CHECKOUT"
    CLEANING = "CLEANING"
    INSPECTION = "INSPECTION"
    READY = "READY"
    CHECKIN = "CHECKIN"
    CANCELLED = "CANCELLED"


class MailHoldStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACTIVE = "ACTIVE"
    OVERFLOW = "OVERFLOW"
    FORWARDED = "FORWARDED"
    RELEASED = "RELEASED"


class IncidentType(str, Enum):
    ALARM_INTRUSION = "ALARM_INTRUSION"
    ALARM_SMOKE = "ALARM_SMOKE"
    FREEZE_ALARM = "FREEZE_ALARM"
    WATER_LEAK = "WATER_LEAK"
    VANDALISM = "VANDALISM"
    UNAUTHORIZED_ACCESS = "UNAUTHORIZED_ACCESS"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    INVESTIGATING = "INVESTIGATING"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    FALSE_ALARM = "FALSE_ALARM"


class StormEventStatus(str, Enum):
    FORECAST = "FORECAST"
    WATCH = "WATCH"
    WARNING = "WARNING"
    IMMINENT = "IMMINENT"
    LANDFALL = "LANDFALL"
    ALL_CLEAR = "ALL_CLEAR"
    CLOSED = "CLOSED"


class StormTier(str, Enum):
    FORECAST = "FORECAST"
    WATCH = "WATCH"
    WARNING = "WARNING"
    IMMINENT = "IMMINENT"


class StormResponseStatus(str, Enum):
    PENDING = "PENDING"
    SECURE_SWEEP_SCHEDULED = "SECURE_SWEEP_SCHEDULED"
    SECURED = "SECURED"
    SECURED_LATE = "SECURED_LATE"
    MISSED_DEADLINE = "MISSED_DEADLINE"
    AWAITING_ALL_CLEAR = "AWAITING_ALL_CLEAR"
    ASSESSMENT_DUE = "ASSESSMENT_DUE"
    ASSESSED = "ASSESSED"
    CLOSED = "CLOSED"


class DamageLevel(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    VOID = "VOID"


class LineType(str, Enum):
    SUBSCRIPTION_FEE = "SUBSCRIPTION_FEE"
    VISIT_OVERAGE = "VISIT_OVERAGE"
    TRAVEL_SURCHARGE = "TRAVEL_SURCHARGE"
    WORK_ORDER = "WORK_ORDER"
    FALSE_ALARM_FEE = "FALSE_ALARM_FEE"
    MAIL_DISPOSITION = "MAIL_DISPOSITION"
    REKEY_FEE = "REKEY_FEE"
    ENTITLEMENT_OFFSET = "ENTITLEMENT_OFFSET"
    GUARANTEE_CREDIT = "GUARANTEE_CREDIT"


class LineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOID = "VOID"


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Owner(CommonFields):
    full_name: str
    email: str
    phone: str
    primary_residence_state: str
    snowbird_flag: bool
    notification_preference: str
    approval_ceiling_override_cents: Optional[int]
    lifetime_credit_balance_cents: int
    status: str


class Property(CommonFields):
    owner_id: str
    label: str
    address_line: str
    state_code: str
    travel_distance_miles: float
    travel_zone: str
    seasonal_state: str
    occupancy_state: str
    freeze_setpoint_f: float
    last_interior_temp_f: Optional[float]
    last_temp_reading_at: Optional[str]
    freeze_risk_score: float
    risk_posture: str
    winterization_completeness_pct: float
    false_alarm_count_window: int
    open_critical_finding_count: int
    storm_hold_flag: bool
    rental_program_enrolled: bool


class ServicePlan(CommonFields):
    tier: str
    monthly_fee_cents: int
    included_visit_units: int
    entitlement_rollover_policy: str
    storm_guarantee_included: bool
    covered_visit_types: List[str]
    status: str


class Subscription(CommonFields):
    property_id: str
    service_plan_id: str
    status: str
    started_on: str
    current_cycle_id: Optional[str]
    paused_at: Optional[str]
    resumed_at: Optional[str]
    cumulative_paused_days: int
    pending_tier_change_plan_id: Optional[str]
    delinquent_since: Optional[str]
    cancelled_at: Optional[str]


class BillingCycle(CommonFields):
    subscription_id: str
    cycle_index: int
    period_start: str
    period_end: str
    status: str
    entitlement_granted_units: int
    entitlement_carried_in_units: int
    entitlement_consumed_units: int
    entitlement_remaining_units: int
    entitlement_expired_units: int
    entitlement_carried_out_units: int
    prorated_fee_cents: int
    closed_at: Optional[str]


class AwayPeriod(CommonFields):
    property_id: str
    owner_id: str
    start_at: str
    end_at: str
    cadence_days: int
    projected_visit_count: int
    scheduled_visit_count: int
    derived_status: str
    cadence_revision_count: int


class ChecklistTemplate(CommonFields):
    visit_type: str
    version_label: str
    item_codes: List[str]
    critical_item_codes: List[str]
    default_finding_category: str
    required_item_count: int
    status: str


class Visit(CommonFields):
    property_id: str
    checklist_template_id: str
    away_period_id: Optional[str]
    storm_response_id: Optional[str]
    rental_turnover_id: Optional[str]
    billing_cycle_id: Optional[str]
    visit_type: str
    trigger_source: str
    scheduled_start_at: str
    scheduled_end_at: str
    status: str
    departed_at: Optional[str]
    arrived_at: Optional[str]
    completed_at: Optional[str]
    tech_user_id: Optional[str]
    completed_item_codes: List[str]
    failed_item_codes: List[str]
    checklist_completion_pct: float
    interior_temp_f: Optional[float]
    entitlement_applied: bool
    billable_amount_cents: int
    after_hours_flag: bool
    deferral_count: int
    defer_reason: Optional[str]


class Finding(CommonFields):
    visit_id: Optional[str]
    property_id: str
    item_code: str
    severity: str
    category: str
    status: str
    escalation_score: float
    triaged_at: Optional[str]
    dismissed_at: Optional[str]
    monitor_recheck_count: int
    description: str


class Vendor(CommonFields):
    legal_name: str
    trade: str
    coi_expires_at: str
    license_expires_at: str
    hourly_rate_cents: int
    rating: float
    billing_mode: str
    status: str
    emergency_capable: bool
    outstanding_key_count: int
    last_eligibility_evaluated_at: Optional[str]


class WorkOrder(CommonFields):
    finding_id: str
    property_id: str
    storm_event_id: Optional[str]
    key_asset_id: Optional[str]
    work_type: str
    pipeline: str
    estimated_labour_hours: float
    estimated_parts_cents: int
    labour_cost_cents: int
    parts_cost_cents: int
    markup_cents: int
    surcharge_pct_applied: float
    storm_surcharge_cents: int
    total_cents: int
    approval_ceiling_cents: int
    approval_required: bool
    status: str
    dispatch_attempt_count: int
    approved_by_user_id: Optional[str]
    created_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    actual_labour_hours: Optional[float]
    actual_parts_cents: Optional[int]


class VendorAssignment(CommonFields):
    work_order_id: str
    vendor_id: str
    window_start_at: str
    window_end_at: str
    status: str
    offered_at: Optional[str]
    accepted_at: Optional[str]
    finished_at: Optional[str]
    decline_reason: Optional[str]
    coi_valid_at_offer: bool
    access_blocked_flag: bool


class KeyAsset(CommonFields):
    property_id: str
    key_type: str
    label: str
    copies_total: int
    copies_on_hand: int
    copies_issued_outstanding: int
    copies_lost: int
    current_code: Optional[str]
    code_rotation_count: int
    active_grant_count: int
    rekey_pending_flag: bool


class KeyIssuance(CommonFields):
    key_asset_id: str
    vendor_id: str
    vendor_assignment_id: Optional[str]
    issued_at: str
    return_deadline_at: str
    returned_at: Optional[str]
    status: str
    overdue_days: int
    copies_issued: int


class AccessGrant(CommonFields):
    key_asset_id: str
    vendor_id: str
    key_issuance_id: Optional[str]
    window_start_at: str
    window_end_at: str
    code_snapshot: Optional[str]
    status: str
    invalidated_reason: Optional[str]
    rotation_index_at_grant: int


class WinterizationRecord(CommonFields):
    property_id: str
    visit_id: Optional[str]
    water_shutoff_done: bool
    lines_drained_done: bool
    thermostat_set_f: Optional[float]
    valve_tagged_done: bool
    antifreeze_added_done: bool
    completed_step_count: int
    completeness_pct: float
    status: str
    completed_at: Optional[str]
    reopen_reason: Optional[str]


class RentalTurnover(CommonFields):
    property_id: str
    checkout_at: str
    checkin_at: str
    clean_started_at: Optional[str]
    inspect_started_at: Optional[str]
    ready_at: Optional[str]
    status: str
    reclean_attempt_count: int
    absorbed_visit_id: Optional[str]
    guest_reference: str


class MailHold(CommonFields):
    property_id: str
    start_on: str
    end_on: str
    hold_days: int
    extension_count: int
    package_count: int
    overflow_events: int
    status: str
    forwarding_address: Optional[str]
    disposition_fee_cents: int


class SecurityIncident(CommonFields):
    property_id: str
    visit_id: Optional[str]
    incident_type: str
    reported_at: str
    severity: str
    status: str
    escalation_count: int
    false_alarm_sequence: Optional[int]
    false_alarm_fee_cents: int
    triggered_visit_id: Optional[str]
    resolution_note: Optional[str]


class StormEvent(CommonFields):
    name: str
    region_state_code: str
    landfall_eta_at: str
    status: str
    derived_tier: str
    landfall_recorded_at: Optional[str]
    all_clear_at: Optional[str]
    downgrade_count: int
    response_count: int


class StormResponse(CommonFields):
    storm_event_id: str
    property_id: str
    subscription_id: Optional[str]
    secure_sweep_deadline_at: Optional[str]
    secure_sweep_visit_id: Optional[str]
    secured_at: Optional[str]
    sweep_on_time: bool
    guarantee_credit_cents: int
    assessment_deadline_at: Optional[str]
    assessed_at: Optional[str]
    swept_by_user_id: Optional[str]
    assessed_by_user_id: Optional[str]
    damage_level: Optional[str]
    surcharge_pct_at_dispatch: float
    status: str


class Invoice(CommonFields):
    billing_cycle_id: str
    property_id: str
    owner_id: str
    status: str
    storm_surcharge_pct: float
    gross_service_cents: int
    entitlement_offset_cents: int
    storm_surcharge_cents: int
    guarantee_credit_cents: int
    subtotal_cents: int
    tax_cents: int
    late_fee_cents: int
    total_cents: int
    amount_paid_cents: int
    balance_due_cents: int
    issued_at: Optional[str]
    paid_at: Optional[str]
    dispute_count: int


class InvoiceLine(CommonFields):
    invoice_id: str
    visit_id: Optional[str]
    work_order_id: Optional[str]
    security_incident_id: Optional[str]
    mail_hold_id: Optional[str]
    line_type: str
    description: str
    amount_cents: int
    taxable: bool
    tax_cents: int
    status: str
    sequence_index: int
