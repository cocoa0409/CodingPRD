"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SITE_CLERK = "SiteClerk"
    DRIVER = "Driver"
    TECHNICIAN = "Technician"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    HOST_SITE_MANAGER = "HostSiteManager"


class HostSiteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DECOMMISSIONED = "DECOMMISSIONED"


class SalesPosture(str, Enum):
    SALES_OPEN = "SALES_OPEN"
    SALES_BLOCKED = "SALES_BLOCKED"


class CommissionBasis(str, Enum):
    GROSS = "GROSS"
    NET = "NET"


class ReconBasis(str, Enum):
    BOOK = "BOOK"
    PHYSICAL = "PHYSICAL"


class OwnerKind(str, Enum):
    FLEET = "FLEET"
    CUSTOMER = "CUSTOMER"


class FillStatus(str, Enum):
    FULL = "FULL"
    EMPTY = "EMPTY"
    QUARANTINED = "QUARANTINED"


class CertStatus(str, Enum):
    CERTIFIED = "CERTIFIED"
    RECERT_DUE = "RECERT_DUE"
    CONDEMNED = "CONDEMNED"


class CertMethod(str, Enum):
    INITIAL = "INITIAL"
    VISUAL = "VISUAL"
    HYDROSTATIC = "HYDROSTATIC"


class ExchangeOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"
    REFUNDED = "REFUNDED"


class VoidReason(str, Enum):
    MANUAL = "MANUAL"
    SAFETY = "SAFETY"


class RefillTicketStatus(str, Enum):
    OPEN = "OPEN"
    WEIGHED = "WEIGHED"
    FILLED = "FILLED"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class CertificationRecordStatus(str, Enum):
    RECORDED = "RECORDED"
    PENDING_SECOND = "PENDING_SECOND"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class CertOutcome(str, Enum):
    PASS = "PASS"
    CONDEMN = "CONDEMN"


class LeakSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class LeakReportStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    RESOLVED = "RESOLVED"
    FALSE_ALARM = "FALSE_ALARM"


class RestockRunStatus(str, Enum):
    DRAFT = "DRAFT"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"
    CANCELLED = "CANCELLED"


class CommissionStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"


class ReconciliationSessionStatus(str, Enum):
    OPEN = "OPEN"
    BALANCED = "BALANCED"
    VARIANCE_FLAGGED = "VARIANCE_FLAGGED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class StaffStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CertLevel(str, Enum):
    VISUAL_ONLY = "VISUAL_ONLY"
    FULL = "FULL"


class HostSite(TypedDict, total=False):
    id: str
    name: str
    address: str
    status: str
    cage_capacity_cylinders: int
    par_level_full: int
    reorder_floor_full: int
    opening_float_cents: int
    commission_rate_bps: int
    commission_tier_threshold_cents: int
    commission_tier2_bonus_bps: int
    commission_basis: str
    recon_basis: str
    hazmat_fee_cents: int
    promo_waives_hazmat: bool
    full_on_hand: int
    empty_on_hand: int
    quarantined_on_hand: int
    sales_posture: str
    restock_alert: bool
    created_at: str
    updated_at: str
    version: int


class PricingPolicy(TypedDict, total=False):
    id: str
    site_id: str
    swap_price_cents: int
    core_deposit_cents: int
    tax_rate_bps: int
    refill_tier1_cents_per_lb: int
    refill_tier1_max_lbs: float
    refill_tier2_cents_per_lb: int
    effective_from: str
    effective_to: Optional[str]
    is_current: bool
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict, total=False):
    id: str
    name: str
    license_number: str
    dot_medical_expires_on: str
    vehicle_max_payload_lbs: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    name: str
    cert_level: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Cylinder(TypedDict, total=False):
    id: str
    serial_number: str
    owner_kind: str
    water_capacity_lbs: float
    tare_weight_lbs: float
    manufacture_date: str
    certified_on: str
    certification_expires_on: str
    cert_method_last: str
    cert_status: str
    fill_status: str
    current_site_id: Optional[str]
    in_transit_run_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExchangeOrder(TypedDict, total=False):
    id: str
    site_id: str
    clerk_id: str
    returned_cylinder_id: Optional[str]
    issued_cylinder_id: Optional[str]
    unit_price_cents: int
    core_deposit_cents: int
    tax_cents: int
    total_cents: int
    payment_cash_cents: Optional[int]
    change_due_cents: Optional[int]
    business_date: Optional[str]
    sale_seq: Optional[int]
    refunded_on: Optional[str]
    void_reason: Optional[str]
    idempotency_key: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RefillTicket(TypedDict, total=False):
    id: str
    site_id: str
    cylinder_id: str
    clerk_id: str
    pre_weight_lbs: float
    measured_tare_lbs: Optional[float]
    post_weight_lbs: Optional[float]
    propane_lbs: Optional[float]
    max_fill_lbs: float
    tier1_cents_per_lb: Optional[int]
    tier2_cents_per_lb: Optional[int]
    tier1_max_lbs: Optional[float]
    propane_charge_cents: Optional[int]
    hazmat_fee_cents: Optional[int]
    total_cents: Optional[int]
    payment_cash_cents: Optional[int]
    change_due_cents: Optional[int]
    business_date: Optional[str]
    sale_seq: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CertificationRecord(TypedDict, total=False):
    id: str
    cylinder_id: str
    technician_id: str
    method: str
    outcome: str
    performed_on: str
    previous_expires_on: str
    new_expires_on: Optional[str]
    confirmer_technician_id: Optional[str]
    note: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LeakReport(TypedDict, total=False):
    id: str
    site_id: str
    cylinder_id: Optional[str]
    severity: str
    quarantine_cage: bool
    reporter_clerk_id: str
    note: str
    confirmed_by: Optional[str]
    confirmed_on: Optional[str]
    resolved_by: Optional[str]
    resolution_note: Optional[str]
    false_alarm_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RestockRun(TypedDict, total=False):
    id: str
    site_id: str
    driver_id: str
    planned_date: str
    planned_full_count: int
    planned_empty_pickup_count: int
    assigned_cylinder_count: int
    delivered_full_count: Optional[int]
    picked_up_empty_count: Optional[int]
    variance_full_count: Optional[int]
    verified_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CommissionStatement(TypedDict, total=False):
    id: str
    site_id: str
    period_start: str
    period_end: str
    basis_used: str
    gross_sales_cents: int
    refunds_cents: int
    base_cents: int
    commission_cents: int
    leak_count: int
    leak_deduction_cents: int
    net_payable_cents: int
    finalized_on: Optional[str]
    paid_on: Optional[str]
    dispute_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReconciliationSession(TypedDict, total=False):
    id: str
    site_id: str
    business_date: str
    clerk_id: str
    basis: str
    opening_baseline_cents: int
    expected_cash_cents: int
    expected_full_cylinders: int
    expected_empty_cylinders: int
    counted_cash_cents: Optional[int]
    counted_full_cylinders: Optional[int]
    counted_empty_cylinders: Optional[int]
    cash_variance_cents: Optional[int]
    full_variance: Optional[int]
    empty_variance: Optional[int]
    escalated_by: Optional[str]
    resolved_by: Optional[str]
    resolution_note: Optional[str]
    idempotency_key: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
