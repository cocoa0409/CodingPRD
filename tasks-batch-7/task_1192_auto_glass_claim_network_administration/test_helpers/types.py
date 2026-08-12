"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    POLICYHOLDER = "Policyholder"
    SHOP_OPERATOR = "ShopOperator"
    CLAIM_ADJUSTER = "ClaimAdjuster"
    NETWORK_AUDITOR = "NetworkAuditor"
    FRAUD_INVESTIGATOR = "FraudInvestigator"
    NETWORK_ADMIN = "NetworkAdmin"


class PolicyholderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class CoverageType(str, Enum):
    COMPREHENSIVE = "COMPREHENSIVE"
    LIABILITY = "LIABILITY"


class AgreementTier(str, Enum):
    PLATINUM = "PLATINUM"
    PREFERRED = "PREFERRED"
    STANDARD = "STANDARD"


class ShopNetworkStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PartCategory(str, Enum):
    WINDSHIELD = "WINDSHIELD"
    SIDE_GLASS = "SIDE_GLASS"
    REAR_GLASS = "REAR_GLASS"
    MOLDING_KIT = "MOLDING_KIT"
    CALIBRATION = "CALIBRATION"


class PartOrigin(str, Enum):
    OEM = "OEM"
    AFTERMARKET = "AFTERMARKET"


class PartStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DISCONTINUED = "DISCONTINUED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    FRAUD_HOLD = "FRAUD_HOLD"
    COVERAGE_VERIFIED = "COVERAGE_VERIFIED"
    WORK_AUTHORIZED = "WORK_AUTHORIZED"
    WORK_COMPLETED = "WORK_COMPLETED"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class DisclosureChannel(str, Enum):
    PHONE = "PHONE"
    PORTAL = "PORTAL"
    IN_PERSON = "IN_PERSON"


class WorkOrderStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    SCHEDULED = "SCHEDULED"
    NO_SHOW = "NO_SHOW"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class ServiceMode(str, Enum):
    MOBILE = "MOBILE"
    IN_SHOP = "IN_SHOP"


class CalibrationType(str, Enum):
    STATIC = "STATIC"
    DYNAMIC = "DYNAMIC"


class CalibrationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    WAIVED = "WAIVED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DISPUTED = "DISPUTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REJECTED = "REJECTED"


class LineType(str, Enum):
    PART = "PART"
    CALIBRATION = "CALIBRATION"
    MOBILE_FEE = "MOBILE_FEE"
    MATERIALS = "MATERIALS"


class AlertType(str, Enum):
    REPEAT_WINDOW = "REPEAT_WINDOW"
    SOLICITATION = "SOLICITATION"
    RAPID_COMPLETION = "RAPID_COMPLETION"
    SCORE_THRESHOLD = "SCORE_THRESHOLD"


class FraudAlertStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class WarrantyStatus(str, Enum):
    FILED = "FILED"
    APPROVED_REWORK = "APPROVED_REWORK"
    DENIED = "DENIED"
    REWORK_COMPLETED = "REWORK_COMPLETED"


# --- Entity TypedDicts ---
# Primary resources carry id + created_at + updated_at + version (PRD §2.5).


class Policyholder(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    phone: str
    state_code: str
    fraud_score: int
    no_show_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StateRegulation(TypedDict, total=False):
    id: str
    state_code: str
    zero_deductible_windshield: bool
    max_deductible_cents: Optional[int]
    glass_sales_tax_rate_bp: int
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict, total=False):
    id: str
    policyholder_id: str
    policy_number: str
    state_code: str
    coverage_type: str
    deductible_cents: int
    oem_endorsement: bool
    effective_start_date: str
    effective_end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GlassShop(TypedDict, total=False):
    id: str
    shop_name: str
    state_code: str
    service_zip_prefixes: List[str]
    mobile_capable: bool
    adas_certified: bool
    oem_certified: bool
    agreement_tier: str
    bay_count: int
    mobile_unit_count: int
    operating_minutes_per_day: int
    network_status: str
    warranty_strike_count: int
    rolling_audit_score: float
    period_close_audit_score: float
    created_at: str
    updated_at: str
    version: int


class PartCatalogEntry(TypedDict, total=False):
    id: str
    part_number: str
    part_description: str
    part_category: str
    part_origin: str
    nags_list_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    policyholder_id: str
    policy_id: str
    assigned_shop_id: Optional[str]
    incident_state_code: str
    service_zip_code: str
    part_category: str
    loss_date: str
    description: str
    requires_adas_calibration: bool
    estimated_repair_cost_cents: int
    provisional_customer_responsibility_cents: Optional[int]
    deductible_applied_cents: Optional[int]
    oem_upcharge_cents: Optional[int]
    customer_responsibility_cents: Optional[int]
    insurer_payment_cents: Optional[int]
    coverage_verified_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only audit record (PRD §2.5): carries ONLY id + created_at;
# no updated_at, no version.
class ChoiceDisclosureRecord(TypedDict, total=False):
    id: str
    claim_id: str
    disclosure_channel: str
    shop_solicited: bool
    customer_selected_shop_name: Optional[str]
    informed_of_network_options: bool
    created_at: str


class WorkOrder(TypedDict, total=False):
    id: str
    claim_id: str
    shop_id: str
    warranty_claim_id: Optional[str]
    service_mode: Optional[str]
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CalibrationEvent(TypedDict, total=False):
    id: str
    work_order_id: str
    calibration_type: str
    scheduled_start: str
    scheduled_end: str
    report_reference: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    work_order_id: str
    status: str
    submitted_total_cents: int
    tax_amount_cents: int
    approved_total_cents: int
    adjustment_total_cents: int
    audited_by_user_id: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InvoiceLineItem(TypedDict, total=False):
    id: str
    invoice_id: str
    part_catalog_entry_id: Optional[str]
    line_type: str
    quantity: int
    origin_claimed: Optional[str]
    unit_price_cents: int
    agreement_unit_price_cents: int
    line_total_cents: int
    approved_amount_cents: Optional[int]
    approved_origin: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FraudAlert(TypedDict, total=False):
    id: str
    policyholder_id: str
    claim_id: str
    alert_type: str
    score_contribution: int
    resolution_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    original_work_order_id: str
    issue_description: str
    filed_at: str
    decision_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
