"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    DEALERSHIP_ADMIN = "DealershipAdmin"
    SALES_CONSULTANT = "SalesConsultant"
    CUSTOMER = "Customer"
    SITE_EVALUATOR = "SiteEvaluator"
    INSTALLATION_MANAGER = "InstallationManager"
    TRANSPORT_COORDINATOR = "TransportCoordinator"
    LENDER_AGENT = "LenderAgent"
    SERVICE_MANAGER = "ServiceManager"
    APPRAISER = "Appraiser"


class HomeModelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class FloorPlanType(str, Enum):
    SINGLE_WIDE = "SINGLE_WIDE"
    DOUBLE_WIDE = "DOUBLE_WIDE"
    TRIPLE_WIDE = "TRIPLE_WIDE"
    MODULAR = "MODULAR"


class CommunityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    LEASED = "LEASED"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CreditTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"


class UnitKind(str, Enum):
    STOCK = "STOCK"
    FACTORY_ORDER = "FACTORY_ORDER"
    TRADE_IN = "TRADE_IN"


class ConditionGrade(str, Enum):
    NEW = "NEW"
    A = "A"
    B = "B"
    C = "C"


class HomeUnitStatus(str, Enum):
    AT_FACTORY = "AT_FACTORY"
    AT_DEALER = "AT_DEALER"
    RESERVED = "RESERVED"
    IN_TRANSIT = "IN_TRANSIT"
    ON_SITE = "ON_SITE"
    INSTALLED = "INSTALLED"
    RECONDITIONING = "RECONDITIONING"
    RETAIL_READY = "RETAIL_READY"


class DealStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_SITE_EVAL = "PENDING_SITE_EVAL"
    SITE_APPROVED = "SITE_APPROVED"
    PENDING_FINANCING = "PENDING_FINANCING"
    FINANCING_APPROVED = "FINANCING_APPROVED"
    AWAITING_DELIVERY = "AWAITING_DELIVERY"
    DELIVERED = "DELIVERED"
    SET_COMPLETE = "SET_COMPLETE"
    TITLED = "TITLED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    FINANCED = "FINANCED"
    REFUNDED = "REFUNDED"


class PlacementType(str, Enum):
    COMMUNITY_LOT = "COMMUNITY_LOT"
    PRIVATE_LAND = "PRIVATE_LAND"


class FinancingType(str, Enum):
    CHATTEL = "CHATTEL"
    REAL_PROPERTY = "REAL_PROPERTY"


class OrderOptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class SiteEvaluationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    FINDINGS_RECORDED = "FINDINGS_RECORDED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class FoundationType(str, Enum):
    SLAB = "SLAB"
    CRAWL_SPACE = "CRAWL_SPACE"
    PIERS = "PIERS"
    BASEMENT = "BASEMENT"


class FindingsResult(str, Enum):
    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"


class FinancingApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CONDITIONALLY_APPROVED = "CONDITIONALLY_APPROVED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    FUNDED = "FUNDED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class TransportJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELAYED = "DELAYED"
    EN_ROUTE = "EN_ROUTE"
    DELIVERED = "DELIVERED"
    SET_COMPLETE = "SET_COMPLETE"
    CANCELLED = "CANCELLED"


class TransportOrigin(str, Enum):
    FACTORY = "FACTORY"
    DEALER_LOT = "DEALER_LOT"


class TitleType(str, Enum):
    MANUFACTURED_CERTIFICATE = "MANUFACTURED_CERTIFICATE"
    REAL_PROPERTY_AFFIXED = "REAL_PROPERTY_AFFIXED"


class TitleRecordStatus(str, Enum):
    APPLIED = "APPLIED"
    ISSUED = "ISSUED"
    CONVERTED = "CONVERTED"
    SURRENDERED = "SURRENDERED"


class ClaimType(str, Enum):
    FACTORY_DEFECT = "FACTORY_DEFECT"
    TRANSPORT_DAMAGE = "TRANSPORT_DAMAGE"
    INSTALLATION_DAMAGE = "INSTALLATION_DAMAGE"


class WarrantyClaimStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RESOLVED = "RESOLVED"


class TradeInStatus(str, Enum):
    DRAFT = "DRAFT"
    INSPECTED = "INSPECTED"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"
    RECONDITIONING = "RECONDITIONING"
    RETAIL_READY = "RETAIL_READY"


class DelayReason(str, Enum):
    WEATHER = "WEATHER"
    PERMIT_HOLD = "PERMIT_HOLD"
    FACTORY_DELAY = "FACTORY_DELAY"
    SITE_NOT_READY = "SITE_NOT_READY"
    ESCORT_UNAVAILABLE = "ESCORT_UNAVAILABLE"


class HomeModel(TypedDict, total=False):
    id: str
    model_code: str
    name: str
    floor_plan_type: str
    section_count: int
    width_ft: float
    length_ft: float
    base_price_cents: int
    factory_lead_time_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Community(TypedDict, total=False):
    id: str
    name: str
    address: str
    lot_rent_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict, total=False):
    id: str
    community_id: str
    lot_number: str
    max_sections: int
    max_length_ft: float
    utilities_ready: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    phone: str
    credit_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class HomeUnit(TypedDict, total=False):
    id: str
    model_id: str
    serial_number: str
    unit_kind: str
    condition_grade: str
    status: str
    lot_id: Optional[str]
    sales_order_id: Optional[str]
    delivered_at: Optional[str]
    set_completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict, total=False):
    id: str
    customer_id: str
    home_unit_id: str
    placement_type: str
    lot_id: Optional[str]
    financing_type: str
    agreed_home_price_cents: int
    deposit_cents: int
    options_total_cents: int
    discount_cents: int
    doc_fee_cents: int
    transport_charge_cents: int
    total_price_cents: int
    trade_in_credit_cents: int
    amount_financed_cents: int
    delay_compensation_cents: int
    deal_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class OrderOption(TypedDict, total=False):
    id: str
    sales_order_id: str
    option_code: str
    description: str
    unit_price_cents: int
    quantity: int
    line_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SiteEvaluation(TypedDict, total=False):
    id: str
    sales_order_id: str
    evaluator_id: str
    scheduled_date: str
    foundation_type: Optional[str]
    utilities_verified: Optional[bool]
    permit_number: Optional[str]
    findings_result: Optional[str]
    install_estimate_cents: Optional[int]
    status: str
    evaluated_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FinancingApplication(TypedDict, total=False):
    id: str
    sales_order_id: str
    financing_type: str
    lender_name: str
    term_months: int
    down_payment_cents: int
    requested_amount_cents: int
    apr_bps: Optional[int]
    estimated_payment_cents: int
    monthly_payment_cents: Optional[int]
    rate_lock_expires_at: Optional[str]
    status: str
    decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransportCrew(TypedDict, total=False):
    id: str
    name: str
    crew_size: int
    can_set_multiwide: bool
    max_sections_per_window: int
    booked_dates: list
    created_at: str
    updated_at: str
    version: int


class TransportJob(TypedDict, total=False):
    id: str
    sales_order_id: str
    home_unit_id: str
    crew_id: str
    origin: str
    distance_miles: int
    scheduled_start_date: str
    sections_count: int
    escort_required: bool
    escort_vehicle_count: int
    quoted_cost_cents: int
    status: str
    buyer_notified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TitleRecord(TypedDict, total=False):
    id: str
    home_unit_id: str
    title_type: str
    state_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    home_unit_id: str
    sales_order_id: str
    claim_type: str
    description: str
    estimated_cost_cents: int
    approved_cost_cents: Optional[int]
    coverage_window_end: Optional[str]
    status: str
    reviewed_by: Optional[str]
    resolved_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TradeInAppraisal(TypedDict, total=False):
    id: str
    sales_order_id: str
    model_id: str
    declared_model_year: int
    declared_condition: str
    provisional_credit_cents: int
    appraised_value_cents: Optional[int]
    reconditioning_cost_cents: Optional[int]
    condition_grade: Optional[str]
    final_credit_cents: Optional[int]
    supersedes_appraisal_id: Optional[str]
    trade_in_unit_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only communication record: carries ONLY id + created_at from the
# common envelope (PRD §2.5 exemption); no updated_at, no version.
class DelayNotice(TypedDict, total=False):
    id: str
    transport_job_id: Optional[str]
    sales_order_id: Optional[str]
    reason: str
    original_date: str
    new_date: str
    buyer_notified: bool
    delay_days: int
    compensation_cents: int
    created_at: str
