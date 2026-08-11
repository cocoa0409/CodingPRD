"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    MEMBER = "Member"
    CARE_COORDINATOR = "CareCoordinator"
    INSURANCE_SPECIALIST = "InsuranceSpecialist"
    BILLING_SPECIALIST = "BillingSpecialist"
    WAREHOUSE_OPERATOR = "WarehouseOperator"
    PLATFORM_ADMIN = "PlatformAdmin"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class PlanType(str, Enum):
    COMMERCIAL_PPO = "COMMERCIAL_PPO"
    MEDICAID = "MEDICAID"
    MEDICARE_ADVANTAGE = "MEDICARE_ADVANTAGE"


class ScheduleMode(str, Enum):
    ROLLING = "ROLLING"
    CALENDAR_ANCHORED = "CALENDAR_ANCHORED"


class PrescriptionStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


class PumpType(str, Enum):
    SINGLE_ELECTRIC = "SINGLE_ELECTRIC"
    DOUBLE_ELECTRIC = "DOUBLE_ELECTRIC"
    HOSPITAL_GRADE = "HOSPITAL_GRADE"


class ItemType(str, Enum):
    PUMP = "PUMP"
    PART = "PART"
    COMPRESSION_GARMENT = "COMPRESSION_GARMENT"


class InsuranceTier(str, Enum):
    STANDARD = "STANDARD"
    UPGRADE = "UPGRADE"


class FulfillmentStatus(str, Enum):
    PENDING_QUALIFICATION = "PENDING_QUALIFICATION"
    QUALIFIED = "QUALIFIED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    AUTH_PENDING = "AUTH_PENDING"
    AUTH_APPROVED = "AUTH_APPROVED"
    CLAIM_FILED = "CLAIM_FILED"
    ADJUDICATED = "ADJUDICATED"
    DENIED = "DENIED"


class LineType(str, Enum):
    PUMP_PRIMARY = "PUMP_PRIMARY"
    ADDON_GARMENT = "ADDON_GARMENT"


class PriorAuthStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PENDED = "PENDED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    DENIED_FINAL = "DENIED_FINAL"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class ShipmentStatus(str, Enum):
    LABEL_CREATED = "LABEL_CREATED"
    IN_TRANSIT = "IN_TRANSIT"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"
    LOST = "LOST"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    VOID = "VOID"


class ResupplyScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ENDED = "ENDED"


class ResupplyOrderStatus(str, Enum):
    APPROVED = "APPROVED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class WarrantyClaimStatus(str, Enum):
    OPENED = "OPENED"
    APPROVED_REPAIR = "APPROVED_REPAIR"
    APPROVED_REPLACE = "APPROVED_REPLACE"
    DENIED = "DENIED"
    RESOLVED = "RESOLVED"


class IssueType(str, Enum):
    MOTOR_FAILURE = "MOTOR_FAILURE"
    BATTERY_FAILURE = "BATTERY_FAILURE"
    SUCTION_LOSS = "SUCTION_LOSS"
    PHYSICAL_DAMAGE = "PHYSICAL_DAMAGE"
    OTHER = "OTHER"


# All entities carry common fields: id, created_at, updated_at, version (PRD §2.4).

class Member(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    date_of_birth: str
    shipping_address: str
    out_of_pocket_balance_cents: int
    oop_accumulated_cents: int
    next_resupply_date: Optional[str]
    active_schedule_count: int
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict, total=False):
    id: str
    member_id: str
    payer_name: str
    plan_type: str
    benefit_period_start: str
    benefit_period_end: str
    requires_prior_auth: bool
    prior_auth_threshold_cents: int
    pump_allowance_per_period: int
    pumps_consumed_count: int
    garment_allowance_per_period: int
    garments_consumed_count: int
    resupply_frequency_days: int
    schedule_mode: str
    deductible_cents: int
    deductible_met_cents: int
    coinsurance_pct: float
    oop_max_cents: int
    upgrade_coverage: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Prescription(TypedDict, total=False):
    id: str
    member_id: str
    diagnosis_code: str
    pump_type: str
    issued_date: str
    expiration_date: str
    status: str
    rejection_reason: Optional[str]
    verified_by_user_id: Optional[str]
    consumed_by_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CatalogItem(TypedDict, total=False):
    id: str
    item_type: str
    name: str
    sku: str
    unit_price_cents: int
    insurance_tier: str
    upgrade_fee_cents: int
    covered_under_resupply: bool
    max_qty_per_frequency: int
    warranty_months: int
    pump_type: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PumpOrder(TypedDict, total=False):
    id: str
    member_id: str
    policy_id: str
    prescription_id: str
    pump_item_id: str
    shipping_address: str
    fulfillment_status: str
    billing_status: str
    prior_auth_required: bool
    provisional_allowed_cents: int
    provisional_patient_cents: int
    upgrade_fee_cents: int
    merchandise_subtotal_cents: int
    discount_total_cents: int
    order_total_cents: int
    delivery_date: Optional[str]
    replacement_count: int
    warranty_blocked: bool
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    catalog_item_id: str
    line_type: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int
    discount_cents: int
    created_at: str
    updated_at: str
    version: int


class PriorAuthorization(TypedDict, total=False):
    id: str
    pump_order_id: str
    member_id: str
    policy_id: str
    requested_item_tier: str
    status: str
    auth_number: Optional[str]
    approved_until: Optional[str]
    submission_count: int
    submitted_by_user_id: str
    decided_by_user_id: Optional[str]
    payer_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    pump_order_id: Optional[str]
    resupply_order_id: Optional[str]
    carrier: str
    tracking_number: str
    status: str
    is_warranty_replacement: bool
    shipped_at: str
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    pump_order_id: Optional[str]
    resupply_order_id: Optional[str]
    member_id: str
    policy_id: str
    claim_number: str
    status: str
    provisional_allowed_cents: int
    adjudicated_allowed_cents: Optional[int]
    deductible_applied_cents: int
    patient_responsibility_cents: Optional[int]
    insurance_paid_cents: Optional[int]
    submitted_by_user_id: str
    remitted_by_user_id: Optional[str]
    remittance_reference: Optional[str]
    remitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ResupplySchedule(TypedDict, total=False):
    id: str
    member_id: str
    pump_order_id: str
    catalog_item_id: str
    frequency_days: int
    schedule_mode: str
    anchor_date: str
    last_fulfilled_date: Optional[str]
    next_eligible_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ResupplyOrder(TypedDict, total=False):
    id: str
    schedule_id: str
    member_id: str
    quantity: int
    unit_price_cents: int
    total_cents: int
    status: str
    fulfilled_date: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    pump_order_id: str
    member_id: str
    serial_number: str
    issue_type: str
    description: Optional[str]
    status: str
    reopen_count: int
    resolution_notes: Optional[str]
    replacement_shipment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
