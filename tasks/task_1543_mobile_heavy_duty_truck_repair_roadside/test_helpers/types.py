"""Domain types: entity TypedDicts, status enums, role enum.

Field names follow the PRD exactly. CallEvent is append-only and carries only
id + created_at alongside its content fields (no updated_at, no version).
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    OPS_ADMIN = "OpsAdmin"
    DISPATCHER = "Dispatcher"
    TECHNICIAN = "Technician"
    FLEET_MANAGER = "FleetManager"
    BILLING_CLERK = "BillingClerk"
    WARRANTY_ADMINISTRATOR = "WarrantyAdministrator"
    SAFETY_OFFICER = "SafetyOfficer"


# ---------------------------------------------------------------------------
# Status / field enums
# ---------------------------------------------------------------------------

class FleetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class SuspensionReason(str, Enum):
    NONE = "NONE"
    ADMIN = "ADMIN"
    CREDIT_HOLD = "CREDIT_HOLD"


class DiscountTier(str, Enum):
    STANDARD = "STANDARD"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class Roadworthiness(str, Enum):
    ROADWORTHY = "ROADWORTHY"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class TechnicianStatus(str, Enum):
    OFF_DUTY = "OFF_DUTY"
    AVAILABLE = "AVAILABLE"
    ON_BREAK = "ON_BREAK"
    ON_DISPATCH = "ON_DISPATCH"


class LaborRateClass(str, Enum):
    STANDARD = "STANDARD"
    MASTER = "MASTER"


class Certification(str, Enum):
    ENGINE = "ENGINE"
    BRAKES = "BRAKES"
    ELECTRICAL = "ELECTRICAL"
    HVAC = "HVAC"
    TIRES = "TIRES"
    WELDING = "WELDING"
    DOT_INSPECTION = "DOT_INSPECTION"


class SymptomCategory(str, Enum):
    ENGINE_NO_START = "ENGINE_NO_START"
    OVERHEAT = "OVERHEAT"
    BRAKE_FAULT = "BRAKE_FAULT"
    AIR_LEAK = "AIR_LEAK"
    ELECTRICAL = "ELECTRICAL"
    LIGHTING = "LIGHTING"
    TIRE_BLOWOUT = "TIRE_BLOWOUT"
    HVAC_ISSUE = "HVAC_ISSUE"
    OTHER = "OTHER"


class Severity(str, Enum):
    BLOCKING = "BLOCKING"
    DRIVABLE = "DRIVABLE"
    DEFERRED = "DEFERRED"


class Priority(str, Enum):
    P1_EMERGENCY = "P1_EMERGENCY"
    P2_URGENT = "P2_URGENT"
    P3_STANDARD = "P3_STANDARD"


class RequiredPartClass(str, Enum):
    ENGINE = "ENGINE"
    COOLING = "COOLING"
    BRAKE = "BRAKE"
    AIR_SYSTEM = "AIR_SYSTEM"
    ELECTRICAL = "ELECTRICAL"
    LIGHTING = "LIGHTING"
    TIRE = "TIRE"
    HVAC = "HVAC"
    NONE = "NONE"


class ServiceCallStatus(str, Enum):
    RECEIVED = "RECEIVED"
    TRIAGED = "TRIAGED"
    DISPATCHED = "DISPATCHED"
    EN_ROUTE = "EN_ROUTE"
    ON_SITE = "ON_SITE"
    DIAGNOSED = "DIAGNOSED"
    REPAIR_IN_PROGRESS = "REPAIR_IN_PROGRESS"
    REPAIR_COMPLETED = "REPAIR_COMPLETED"
    TOW_IN_PROGRESS = "TOW_IN_PROGRESS"
    TOWED = "TOWED"
    INVOICED = "INVOICED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    CANCELLED = "CANCELLED"


class ResolutionPath(str, Enum):
    PENDING = "PENDING"
    ON_SITE_REPAIR = "ON_SITE_REPAIR"
    TOW_REQUIRED = "TOW_REQUIRED"


class HoldReason(str, Enum):
    NONE = "NONE"
    FLEET_CREDIT_HOLD = "FLEET_CREDIT_HOLD"


class DispatchStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EN_ROUTE = "EN_ROUTE"
    ON_SITE = "ON_SITE"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class PartClass(str, Enum):
    ENGINE = "ENGINE"
    COOLING = "COOLING"
    BRAKE = "BRAKE"
    AIR_SYSTEM = "AIR_SYSTEM"
    ELECTRICAL = "ELECTRICAL"
    LIGHTING = "LIGHTING"
    TIRE = "TIRE"
    HVAC = "HVAC"
    FILTERS = "FILTERS"


class EstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class ChargeType(str, Enum):
    CUSTOMER_PAY = "CUSTOMER_PAY"
    SHOP_GUARANTEE = "SHOP_GUARANTEE"


class PartUsageStatus(str, Enum):
    POSTED = "POSTED"
    RETURNED = "RETURNED"


class TowOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    HOOKED = "HOOKED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ClaimType(str, Enum):
    OEM_BASE = "OEM_BASE"
    OEM_POWERTRAIN = "OEM_POWERTRAIN"
    EXTENDED_SERVICE_CONTRACT = "EXTENDED_SERVICE_CONTRACT"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    SETTLED = "SETTLED"


class DefectSource(str, Enum):
    ROADSIDE_DOT_INSPECTION = "ROADSIDE_DOT_INSPECTION"
    ANNUAL_INSPECTION = "ANNUAL_INSPECTION"
    DRIVER_REPORT = "DRIVER_REPORT"


class DefectSeverity(str, Enum):
    OOS = "OOS"
    NON_OOS = "NON_OOS"


class DefectStatus(str, Enum):
    OPEN = "OPEN"
    REPAIR_SCHEDULED = "REPAIR_SCHEDULED"
    CORRECTED = "CORRECTED"
    VERIFIED = "VERIFIED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    ESCALATED = "ESCALATED"


class IssueStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    VOID = "VOID"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class PaymentMethod(str, Enum):
    CHECK = "CHECK"
    CARD = "CARD"
    ACH = "ACH"
    FLEET_ACCOUNT = "FLEET_ACCOUNT"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONFIRMED_COMEBACK = "CONFIRMED_COMEBACK"
    REJECTED = "REJECTED"
    RESOLVED = "RESOLVED"


class ChargePolicy(str, Enum):
    NO_CHARGE = "NO_CHARGE"
    REDUCED = "REDUCED"
    FULL = "FULL"


class RestockSource(str, Enum):
    AUTO_LOW_STOCK = "AUTO_LOW_STOCK"
    MANUAL = "MANUAL"


class RestockStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    FULFILLED = "FULFILLED"
    REJECTED = "REJECTED"


class CallEventType(str, Enum):
    CALL_RECEIVED = "CALL_RECEIVED"
    TRIAGED = "TRIAGED"
    DISPATCH_CREATED = "DISPATCH_CREATED"
    DISPATCH_ACCEPTED = "DISPATCH_ACCEPTED"
    DISPATCH_REJECTED = "DISPATCH_REJECTED"
    DISPATCH_DEPARTED = "DISPATCH_DEPARTED"
    DISPATCH_ARRIVED = "DISPATCH_ARRIVED"
    DIAGNOSED = "DIAGNOSED"
    ESTIMATE_CREATED = "ESTIMATE_CREATED"
    ESTIMATE_APPROVED = "ESTIMATE_APPROVED"
    ESTIMATE_REJECTED = "ESTIMATE_REJECTED"
    REPAIR_STARTED = "REPAIR_STARTED"
    PART_POSTED = "PART_POSTED"
    PART_RETURNED = "PART_RETURNED"
    REPAIR_COMPLETED = "REPAIR_COMPLETED"
    TOW_REQUESTED = "TOW_REQUESTED"
    TOW_HOOKED = "TOW_HOOKED"
    TOW_DELIVERED = "TOW_DELIVERED"
    INVOICE_CREATED = "INVOICE_CREATED"
    INVOICE_ISSUED = "INVOICE_ISSUED"
    INVOICE_VOIDED = "INVOICE_VOIDED"
    PAYMENT_POSTED = "PAYMENT_POSTED"
    PAYMENT_VOIDED = "PAYMENT_VOIDED"
    CALL_CLOSED = "CALL_CLOSED"
    CALL_REOPENED = "CALL_REOPENED"
    CALL_CANCELLED = "CALL_CANCELLED"
    HOLD_FLAGGED = "HOLD_FLAGGED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: id, created_at, updated_at, version)
# ---------------------------------------------------------------------------

class FleetAccount(TypedDict, total=False):
    id: str
    company_name: str
    account_number: str
    billing_email: str
    per_call_authorization_limit_cents: int
    monthly_spend_cap_cents: int
    payment_terms_days: int
    rate_card_id: Optional[str]
    month_to_date_spend_cents: int
    effective_discount_tier: str
    status: str
    suspension_reason: str
    created_at: str
    updated_at: str
    version: int


class RateCard(TypedDict, total=False):
    id: str
    name: str
    labor_rate_standard_cents: int
    labor_rate_master_cents: int
    after_hours_multiplier_bp: int
    travel_free_miles: int
    travel_per_mile_cents: int
    travel_time_per_minute_cents: int
    emergency_callout_fee_cents: int
    parts_tax_rate_bp: int
    effective_from: str
    effective_to: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    fleet_account_id: Optional[str]
    vin: str
    unit_number: str
    make: str
    model: str
    year: int
    odometer_miles: int
    oem_warranty_expires_at: Optional[str]
    oem_warranty_miles_limit: Optional[int]
    extended_warranty: bool
    roadworthiness: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    full_name: str
    employee_code: str
    certifications: List[str]
    labor_rate_class: str
    home_depot_city: str
    status: str
    current_dispatch_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceCall(TypedDict, total=False):
    id: str
    vehicle_id: str
    fleet_account_id: Optional[str]
    caller_name: str
    caller_phone: str
    breakdown_location_text: str
    distance_miles_from_depot: int
    symptom_category: str
    symptom_description: str
    severity: Optional[str]
    received_at: str
    after_hours: bool
    priority: Optional[str]
    required_certification: Optional[str]
    required_part_class: Optional[str]
    status: str
    diagnosis_summary: Optional[str]
    resolution_path: str
    labor_hours_actual: Optional[float]
    completion_odometer_miles: Optional[int]
    completed_at: Optional[str]
    is_comeback: bool
    repeat_of_call_id: Optional[str]
    linked_defect_id: Optional[str]
    hold_reason: str
    status_before_invoice: Optional[str]
    reopened_count: int
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispatch(TypedDict, total=False):
    id: str
    service_call_id: str
    technician_id: str
    window_start_at: str
    window_end_at: str
    planned_travel_miles: int
    status: str
    departed_at: Optional[str]
    arrived_at: Optional[str]
    completed_at: Optional[str]
    actual_travel_minutes: Optional[int]
    actual_travel_miles: Optional[int]
    rejection_reason: Optional[str]
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VanStockItem(TypedDict, total=False):
    id: str
    technician_id: str
    part_number: str
    description: str
    part_class: str
    qty_on_hand: int
    unit_cost_cents: int
    unit_retail_cents: int
    reorder_point: int
    restock_pending: bool
    created_at: str
    updated_at: str
    version: int


class WorkEstimate(TypedDict, total=False):
    id: str
    service_call_id: str
    revision: int
    labor_hours_est: float
    travel_miles_est: int
    parts_estimate_cents: int
    includes_tow: bool
    tow_estimate_cents: int
    total_cents: int
    requires_fleet_approval: bool
    status: str
    decided_by: Optional[str]
    decided_at: Optional[str]
    submitted_at: Optional[str]
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PartUsage(TypedDict, total=False):
    id: str
    service_call_id: str
    van_stock_item_id: str
    part_number: str
    qty: int
    charge_type: str
    unit_price_cents: int
    line_total_cents: int
    status: str
    posted_at: str
    created_at: str
    updated_at: str
    version: int


class TowOrder(TypedDict, total=False):
    id: str
    service_call_id: str
    tow_provider_name: str
    tow_unit_id: str
    pickup_location_text: str
    dropoff_location_text: str
    pickup_window_start_at: str
    pickup_window_end_at: str
    tow_fee_cents: int
    status: str
    hooked_at: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    service_call_id: str
    vehicle_id: str
    claim_type: str
    filed_by_technician_id: str
    oem_labor_hours: float
    oem_labor_rate_cents: int
    parts_at_cost_cents: int
    oem_value_cents: int
    retail_value_cents: int
    recovered_cents: int
    status: str
    denial_reason: Optional[str]
    appeal_count: int
    decided_by: Optional[str]
    settled_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class InspectionDefect(TypedDict, total=False):
    id: str
    vehicle_id: str
    source: str
    defect_code: str
    severity: str
    citation_reference: Optional[str]
    discovered_at: str
    correction_deadline_at: str
    correcting_service_call_id: Optional[str]
    status: str
    correction_note: Optional[str]
    verified_by: Optional[str]
    verified_at: Optional[str]
    escalation_count: int
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    service_call_id: str
    fleet_account_id: Optional[str]
    invoice_number: str
    issue_status: str
    payment_status: str
    labor_hours_actual: float
    labor_rate_cents: int
    after_hours: bool
    labor_amount_cents: int
    travel_miles_actual: int
    travel_miles_billable: int
    travel_amount_cents: int
    travel_minutes_actual: int
    travel_time_amount_cents: int
    callout_fee_cents: int
    parts_subtotal_cents: int
    tow_charge_cents: int
    discount_tier: str
    discount_cents: int
    tax_cents: int
    warranty_offset_cents: int
    total_cents: int
    amount_paid_cents: int
    outstanding_cents: int
    issued_at: Optional[str]
    due_at: Optional[str]
    created_by: str
    issued_by: Optional[str]
    void_reason: Optional[str]
    writeoff_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    invoice_id: str
    amount_cents: int
    method: str
    received_at: str
    allocation_json: dict
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepeatFailureCase(TypedDict, total=False):
    id: str
    vehicle_id: str
    original_service_call_id: str
    new_service_call_id: str
    symptom_category: str
    window_days: int
    miles_since_repair: int
    charge_policy: str
    status: str
    decided_by: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RestockRequest(TypedDict, total=False):
    id: str
    van_stock_item_id: str
    technician_id: str
    source: str
    qty_requested: int
    status: str
    fulfilled_qty: Optional[int]
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CallEvent(TypedDict, total=False):
    # Append-only audit row: id + created_at only, NO updated_at / version.
    id: str
    service_call_id: str
    event_type: str
    actor_role: str
    actor_id: str
    note: Optional[str]
    created_at: str
