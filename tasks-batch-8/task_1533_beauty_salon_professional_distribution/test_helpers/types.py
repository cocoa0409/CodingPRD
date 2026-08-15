"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.9)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    DISTRIBUTION_ADMIN = "DistributionAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SALES_CONSULTANT = "SalesConsultant"
    SALON_BUYER = "SalonBuyer"
    WAREHOUSE_OPERATOR = "WarehouseOperator"


class SalonAccountStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class SalonTier(str, Enum):
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class SuspensionReason(str, Enum):
    MANUAL = "MANUAL"
    LICENSE_EXPIRED = "LICENSE_EXPIRED"
    DIVERSION_STRIKES = "DIVERSION_STRIKES"


class LicenseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class LicenseType(str, Enum):
    COSMETOLOGY = "COSMETOLOGY"
    ESTHETICIAN = "ESTHETICIAN"
    BARBER = "BARBER"
    NAIL_TECH = "NAIL_TECH"
    SALON_BUSINESS = "SALON_BUSINESS"


class BrandStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class ProductLifecycle(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"
    LIQUIDATION = "LIQUIDATION"
    ARCHIVED = "ARCHIVED"


class VariantType(str, Enum):
    BACKBAR = "BACKBAR"
    RETAIL = "RETAIL"


class HazmatClass(str, Enum):
    NONE = "NONE"
    AEROSOL = "AEROSOL"
    FLAMMABLE_LIQUID = "FLAMMABLE_LIQUID"


class ConsultantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CommissionModel(str, Enum):
    STRAIGHT = "STRAIGHT"
    ACCELERATOR = "ACCELERATOR"


class RoutePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    COMPLETED = "COMPLETED"


class RouteStopStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class OrderFulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    FULFILLING = "FULFILLING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    VOIDED = "VOIDED"
    REFUNDED = "REFUNDED"


class ShipmentMethod(str, Enum):
    GROUND = "GROUND"
    AIR = "AIR"


class ShipmentStatus(str, Enum):
    PLANNED = "PLANNED"
    LABEL_CREATED = "LABEL_CREATED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"


class PromotionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ENDED = "ENDED"


class PromoType(str, Enum):
    BUNDLE = "BUNDLE"
    SAMPLE = "SAMPLE"


class RedemptionStatus(str, Enum):
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class ReversalReason(str, Enum):
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ACCOUNT_SUSPENDED = "ACCOUNT_SUSPENDED"


class CreditEntryType(str, Enum):
    PROVISIONAL_ACCRUAL = "PROVISIONAL_ACCRUAL"
    FINAL_ACCRUAL = "FINAL_ACCRUAL"
    REDEMPTION = "REDEMPTION"
    REVERSAL = "REVERSAL"
    EXPIRY = "EXPIRY"


class DiversionCaseStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class DiversionSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    SEVERE = "SEVERE"


# --- Entity TypedDicts (common_fields: true -> id/created_at/updated_at/version) ---

class SalonAccount(TypedDict):
    id: str
    legal_name: str
    territory_code: str
    assigned_consultant_id: Optional[str]
    status: str
    tier: str
    tier_override_active: bool
    education_credit_points: int
    diversion_strike_points: int
    diversion_risk_score: float
    trailing_12m_delivered_volume_cents: int
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProfessionalLicense(TypedDict):
    id: str
    salon_account_id: str
    license_number: str
    issuing_state: str
    license_type: str
    valid_until: str
    status: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Brand(TypedDict):
    id: str
    name: str
    status: str
    discontinued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BrandTerritoryExclusive(TypedDict):
    id: str
    brand_id: str
    territory_code: str
    effective_from: str
    effective_to: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    brand_id: str
    sku: str
    name: str
    variant_type: str
    hazmat_class: str
    base_price_cents: int
    weight_grams: int
    lifecycle_status: str
    discontinued_at: Optional[str]
    liquidation_started_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SalesConsultant(TypedDict):
    id: str
    full_name: str
    territory_codes: List[str]
    commission_model: str
    status: str
    commission_accrued_cents: int
    commission_month: Optional[str]
    commission_month_volume_cents: int
    created_at: str
    updated_at: str
    version: int


class RoutePlan(TypedDict):
    id: str
    sales_consultant_id: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict):
    id: str
    route_plan_id: str
    salon_account_id: str
    start_at: str
    end_at: str
    status: str
    visited_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    salon_account_id: str
    fulfillment_status: str
    payment_status: str
    merchandise_total_cents: int
    credit_applied_cents: int
    net_merch_cents: int
    shipping_total_cents: int
    grand_total_cents: int
    promo_applied_code: Optional[str]
    submitted_at: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderItem(TypedDict):
    id: str
    order_id: str
    product_id: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int
    is_promotional: bool
    pricing_snapshot: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    order_id: str
    method: str
    items: List[dict]
    status: str
    hazmat_declaration_required: bool
    hazmat_surcharge_cents: int
    shipping_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class Promotion(TypedDict):
    id: str
    code: str
    promo_type: str
    eligible_tiers: List[str]
    starts_at: str
    ends_at: str
    budget_units: int
    remaining_budget_units: Optional[int]
    per_salon_cap: int
    status: str
    required_product_id: Optional[str]
    required_qty: Optional[int]
    free_product_id: Optional[str]
    free_qty: Optional[int]
    sample_product_id: Optional[str]
    sample_units_per_redemption: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PromotionRedemption(TypedDict):
    id: str
    promotion_id: str
    order_id: str
    salon_account_id: str
    units_consumed: int
    status: str
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only ledger row: only id + created_at,
# NO updated_at, NO version (PRD §2.5 exemption).
class EducationCreditEntry(TypedDict):
    id: str
    created_at: str
    salon_account_id: str
    order_id: Optional[str]
    entry_type: str
    points: int
    consumed_points: int
    earned_at: str
    expires_at: Optional[str]


class DiversionCase(TypedDict):
    id: str
    salon_account_id: str
    product_id: str
    filed_by_consultant_id: Optional[str]
    filed_by_user_id: str
    severity: str
    evidence_note: str
    hold_shipments: bool
    status: str
    adjudicated_by_user_id: Optional[str]
    strike_points_awarded: int
    created_at: str
    updated_at: str
    version: int
