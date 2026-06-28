"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the entities and lifecycles described in the Musical Instrument Store PRD.
PaymentRecord and LayawayPayment are append-only ledger events and therefore
carry only ``id`` and ``created_at`` (no ``updated_at`` / ``version``).
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Roles -------------------------------------------------------------------
class UserRole(str, Enum):
    SALES_ASSOCIATE = "SalesAssociate"
    LUTHIER = "Luthier"
    STORE_MANAGER = "StoreManager"
    CUSTOMER = "Customer"


# --- Status enums ------------------------------------------------------------
class InventoryUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    ON_RENT = "ON_RENT"
    ON_LAYAWAY = "ON_LAYAWAY"
    SOLD = "SOLD"
    IN_REPAIR = "IN_REPAIR"
    CONSIGNED = "CONSIGNED"
    RETIRED = "RETIRED"


class InventoryCondition(str, Enum):
    NEW = "NEW"
    USED = "USED"
    VINTAGE = "VINTAGE"


class InventoryCategory(str, Enum):
    BAND = "BAND"
    ORCHESTRA = "ORCHESTRA"
    GUITAR = "GUITAR"
    KEYBOARD = "KEYBOARD"
    OTHER = "OTHER"


class SourceKind(str, Enum):
    STORE_PURCHASE = "STORE_PURCHASE"
    TRADE_IN = "TRADE_IN"
    CONSIGNMENT = "CONSIGNMENT"


class RentalPlan(str, Enum):
    RENTAL = "RENTAL"
    RENT_TO_OWN = "RENT_TO_OWN"


class RentalAgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BOUGHT_OUT = "BOUGHT_OUT"
    RETURNED = "RETURNED"
    DEFAULTED = "DEFAULTED"
    REPOSSESSED = "REPOSSESSED"


class PaymentKind(str, Enum):
    RENT = "RENT"
    LATE_FEE = "LATE_FEE"
    BUYOUT = "BUYOUT"
    REFUND = "REFUND"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    WAIVED = "WAIVED"


class LayawayPlanStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RepairTicketStatus(str, Enum):
    INTAKE = "INTAKE"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_PARTS = "AWAITING_PARTS"
    READY = "READY"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ConsignmentListingStatus(str, Enum):
    LISTED = "LISTED"
    SOLD = "SOLD"
    WITHDRAWN = "WITHDRAWN"


class TradeInStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class FinancingApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class SpecialOrderStatus(str, Enum):
    QUOTED = "QUOTED"
    DEPOSITED = "DEPOSITED"
    ORDERED = "ORDERED"
    ARRIVED = "ARRIVED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class LessonEnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ENDED = "ENDED"


# --- Entity TypedDicts (common_fields: true -> id/created_at/updated_at/version)
class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    credit_score: int
    store_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class InventoryUnit(TypedDict):
    id: str
    model_name: str
    category: str
    condition: str
    serial_number: str
    acquisition_cost_cents: int
    list_price_cents: int
    monthly_rent_cents: int
    status: str
    source_kind: str
    consignment_listing_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RentalAgreement(TypedDict):
    id: str
    customer_id: str
    inventory_unit_id: str
    plan: str
    monthly_rate_cents: int
    purchase_price_cents: int
    equity_rate_pct: float
    equity_cap_pct: float
    months_paid: int
    accrued_equity_cents: int
    payoff_quote_cents: int
    late_fee_balance_cents: int
    missed_streak: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only ledger event
class PaymentRecord(TypedDict):
    id: str
    agreement_id: str
    kind: str
    amount_cents: int
    billing_cycle_index: Optional[int]
    status: str
    created_at: str


class LayawayPlan(TypedDict):
    id: str
    customer_id: str
    inventory_unit_id: str
    total_price_cents: int
    deposit_cents: int
    paid_cents: int
    remaining_cents: int
    restock_fee_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only ledger event
class LayawayPayment(TypedDict):
    id: str
    layaway_plan_id: str
    amount_cents: int
    created_at: str


class RepairTicket(TypedDict):
    id: str
    customer_id: str
    inventory_unit_id: Optional[str]
    assigned_luthier_id: Optional[str]
    labor_hours: float
    labor_rate_cents: int
    parts_cost_cents: int
    rush: bool
    quoted_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsignmentListing(TypedDict):
    id: str
    consignor_id: str
    model_name: str
    ask_price_cents: int
    commission_pct: float
    consignor_payout_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TradeIn(TypedDict):
    id: str
    customer_id: str
    model_name: str
    condition: str
    appraised_value_cents: int
    offer_cents: int
    resulting_unit_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancingApplication(TypedDict):
    id: str
    customer_id: str
    special_order_id: Optional[str]
    principal_cents: int
    term_months: int
    apr_pct: float
    monthly_payment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    customer_id: str
    model_name: str
    quoted_price_cents: int
    deposit_pct: float
    required_deposit_cents: int
    deposit_paid_cents: int
    fulfilled_unit_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LessonEnrollment(TypedDict):
    id: str
    student_id: str
    rental_agreement_id: Optional[str]
    instrument_family: str
    sessions_per_month: int
    base_rate_cents: int
    monthly_tuition_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
