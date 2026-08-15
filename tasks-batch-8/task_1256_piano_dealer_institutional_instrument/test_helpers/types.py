"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    STORE_MANAGER = "StoreManager"
    SALES_ASSOCIATE = "SalesAssociate"
    INSTITUTIONAL_BID_OFFICER = "InstitutionalBidOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SERVICE_COORDINATOR = "ServiceCoordinator"
    FINANCE_OFFICER = "FinanceOfficer"
    CUSTOMER = "Customer"
    CONSIGNOR = "Consignor"


class InstrumentStatus(str, Enum):
    IN_PREP = "IN_PREP"
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    DELIVERED = "DELIVERED"
    RESTORATION_HOLD = "RESTORATION_HOLD"
    REPOSSESSION_HOLD = "REPOSSESSION_HOLD"
    RETURNED_TO_CONSIGNOR = "RETURNED_TO_CONSIGNOR"


class AppraisalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class BidStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    AWARDED = "AWARDED"
    LOST = "LOST"
    WITHDRAWN = "WITHDRAWN"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    FINANCED_ACTIVE = "FINANCED_ACTIVE"
    COLLECTIONS = "COLLECTIONS"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    AWAITING_SCHEDULING = "AWAITING_SCHEDULING"
    DELIVERY_SCHEDULED = "DELIVERY_SCHEDULED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    INSTALLED = "INSTALLED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class DeliveryJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXHAUSTED = "EXHAUSTED"
    CANCELLED = "CANCELLED"


class VisitStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AgreementStatus(str, Enum):
    APPLIED = "APPLIED"
    ACTIVE = "ACTIVE"
    PAID_OFF = "PAID_OFF"
    DEFAULTED = "DEFAULTED"
    CONVERTED_TO_PURCHASE = "CONVERTED_TO_PURCHASE"
    CANCELLED = "CANCELLED"


class WarrantyStatus(str, Enum):
    PENDING = "PENDING"
    REGISTERED = "REGISTERED"
    VOID = "VOID"
    EXPIRED = "EXPIRED"


class ReferralStatus(str, Enum):
    REFERRED = "REFERRED"
    ASSESSED = "ASSESSED"
    QUOTED = "QUOTED"
    COMMISSIONED = "COMMISSIONED"
    DECLINED = "DECLINED"


class EventStatus(str, Enum):
    PLANNED = "PLANNED"
    RSVP_OPEN = "RSVP_OPEN"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class Consignor(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    commission_pct: float
    split_mode: str
    payout_method: str
    outstanding_payout_cents: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    customer_type: str
    institution_type: Optional[str]
    tax_exempt: bool
    state_contract_ceiling_cents: Optional[int]
    credit_limit_cents: int
    risk_score: int
    created_at: str
    updated_at: str
    version: int


class Instrument(TypedDict, total=False):
    id: str
    serial_number: str
    category: str
    manufacturer: str
    model: str
    year_built: int
    condition_grade: str
    acquisition_type: str
    consignor_id: Optional[str]
    list_price_cents: int
    floor_price_cents: int
    recoverable_costs_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TradeInAppraisal(TypedDict, total=False):
    id: str
    customer_id: str
    category: str
    manufacturer: str
    model: str
    year_built: int
    condition_grade: str
    provisional_value_cents: int
    reconditioning_cost_cents: Optional[int]
    market_adjustment_pct: Optional[float]
    final_value_cents: Optional[int]
    counter_value_cents: Optional[int]
    offered_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BidPackage(TypedDict, total=False):
    id: str
    customer_id: str
    prepared_by_user_id: str
    lines: list
    quantity: int
    subtotal_cents: int
    tier_discount_pct: float
    institution_multiplier: float
    ceiling_cents: Optional[int]
    total_cents: int
    revision_number: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict, total=False):
    id: str
    customer_id: str
    items: list
    trade_in_appraisal_id: Optional[str]
    bid_package_id: Optional[str]
    tax_rate: float
    distance_miles: int
    stairs_count: int
    climate_controlled_required: bool
    subtotal_cents: int
    trade_in_credit_cents: int
    delivery_fee_cents: int
    tax_cents: int
    total_cents: int
    amount_paid_cents: int
    balance_cents: int
    payment_status: str
    fulfillment_status: str
    delivered_at: Optional[str]
    installed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeliveryCrew(TypedDict, total=False):
    id: str
    crew_name: str
    climate_certified: bool
    created_at: str
    updated_at: str
    version: int


class DeliveryJob(TypedDict, total=False):
    id: str
    order_id: str
    crew_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    full_name: str
    certification_level: str
    created_at: str
    updated_at: str
    version: int


class ServicePlan(TypedDict, total=False):
    id: str
    order_id: str
    tier: str
    price_cents: int
    visits_total: int
    visits_used: int
    visits_booked: int
    visits_available: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceVisit(TypedDict, total=False):
    id: str
    plan_id: str
    technician_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancingAgreement(TypedDict, total=False):
    id: str
    order_id: str
    program: str
    principal_cents: int
    apr: Optional[float]
    term_months: int
    monthly_amount_cents: int
    payments_made: int
    missed_payments: int
    purchase_credit_cents: int
    activated_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyRegistration(TypedDict, total=False):
    id: str
    order_id: str
    instrument_id: str
    term_months: int
    registered_at: Optional[str]
    coverage_end: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RestorationReferral(TypedDict, total=False):
    id: str
    instrument_id: str
    shop_name: str
    condition_score: Optional[int]
    estimate_low_cents: Optional[int]
    estimate_high_cents: Optional[int]
    final_quote_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ShowroomEvent(TypedDict, total=False):
    id: str
    room: str
    title: str
    start_at: str
    end_at: str
    capacity: int
    artist_guarantee_cents: int
    split_pct: float
    rsvp_count: int
    gross_cents: Optional[int]
    payout_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
