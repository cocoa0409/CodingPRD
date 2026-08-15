"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    SALES_REP = "SalesRep"
    PERMIT_COORDINATOR = "PermitCoordinator"
    INSTALL_CREW = "InstallCrew"
    FINANCE_MANAGER = "FinanceManager"
    OPERATIONS_ADMIN = "OperationsAdmin"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SITE_REVIEW = "SITE_REVIEW"
    PERMIT_REVIEW = "PERMIT_REVIEW"
    READY_TO_SCHEDULE = "READY_TO_SCHEDULE"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class StructureState(str, Enum):
    NOT_INSTALLED = "NOT_INSTALLED"
    INSTALLED = "INSTALLED"
    REPOSSESSION_PENDING = "REPOSSESSION_PENDING"
    REPOSSESSED = "REPOSSESSED"


class DeliveryMode(str, Enum):
    PRE_BUILT = "PRE_BUILT"
    ON_SITE_BUILD = "ON_SITE_BUILD"


class FoundationType(str, Enum):
    GRAVEL_PAD = "GRAVEL_PAD"
    CONCRETE_SLAB = "CONCRETE_SLAB"
    PIERS = "PIERS"
    NONE = "NONE"


class AnchorType(str, Enum):
    AUGER_STRAP = "AUGER_STRAP"
    NONE = "NONE"


class PurchaseType(str, Enum):
    CASH = "CASH"
    RTO = "RTO"


class OrderOption(str, Enum):
    WINDOW = "WINDOW"
    LOFT = "LOFT"
    RAMP = "RAMP"
    ELECTRICAL = "ELECTRICAL"


class SiteAssessmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    REPORTED = "REPORTED"
    CANCELLED = "CANCELLED"


class Verdict(str, Enum):
    SUITABLE = "SUITABLE"
    SUITABLE_WITH_PREP = "SUITABLE_WITH_PREP"
    UNSUITABLE = "UNSUITABLE"


class PermitApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    NOT_REQUIRED = "NOT_REQUIRED"
    WITHDRAWN = "WITHDRAWN"


class RtoContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    DEFAULTED = "DEFAULTED"
    PAID_OFF = "PAID_OFF"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"
    RTO_PAYMENT = "RTO_PAYMENT"
    REFUND = "REFUND"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CARD = "CARD"
    CHECK = "CHECK"


class ServiceTicketStatus(str, Enum):
    OPEN = "OPEN"
    SCHEDULED = "SCHEDULED"
    RESOLVED = "RESOLVED"


# --- Entity payloads (common_fields: id + created_at + updated_at + version) ---

class Jurisdiction(TypedDict, total=False):
    id: str
    name: str
    state_code: str
    county_name: str
    permit_threshold_sqft: int
    setback_front_ft: float
    setback_side_ft: float
    setback_rear_ft: float
    max_building_height_ft: float
    anchoring_required: bool
    permit_base_fee_cents: int
    permit_per_sqft_cents: int
    tax_rate_bp: int
    created_at: str
    updated_at: str
    version: int


class StructureModel(TypedDict, total=False):
    id: str
    name: str
    sku: str
    min_width_ft: float
    max_width_ft: float
    min_depth_ft: float
    max_depth_ft: float
    wall_height_ft: float
    supported_delivery_modes: List[str]
    base_price_cents: int
    overage_rate_tier1_cents: int
    overage_rate_tier2_cents: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    phone: str
    street: str
    city: str
    state_code: str
    zip: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    customer_id: str
    model_id: str
    jurisdiction_id: str
    width_ft: float
    depth_ft: float
    area_sqft: float
    options: List[str]
    delivery_mode: str
    foundation_type: str
    anchor_type: str
    purchase_type: str
    rto_term_months: Optional[int]
    removal_requested: bool
    old_structure_area_sqft: Optional[float]
    trade_in_appraised_cents: Optional[int]
    site_prep_required: bool
    site_prep_fee_cents: int
    structure_price_cents: int
    quoted_total_cents: int
    final_total_cents: Optional[int]
    collected_cents: int
    refunded_cents: int
    retained_cents: int
    status: str
    scheduled_date: Optional[str]
    crew_id: Optional[str]
    completed_at: Optional[str]
    warranty_ends_at: Optional[str]
    structure_state: str
    created_at: str
    updated_at: str
    version: int


class SiteAssessment(TypedDict, total=False):
    id: str
    order_id: str
    assessor_id: str
    scheduled_date: str
    window_start_hour: int
    status: str
    measured_access_width_in: Optional[int]
    measured_slope_pct: Optional[float]
    setback_front_ft: Optional[float]
    setback_side_ft: Optional[float]
    setback_rear_ft: Optional[float]
    ground_prep_needed: Optional[bool]
    prep_cost_cents: Optional[int]
    verdict: Optional[str]
    reported_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PermitApplication(TypedDict, total=False):
    id: str
    order_id: str
    jurisdiction_id: str
    jurisdiction_version: int
    area_sqft: float
    permit_required: bool
    fee_cents: int
    status: str
    decision_note: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RtoContract(TypedDict, total=False):
    id: str
    order_id: str
    term_months: int
    total_contract_cents: int
    monthly_payment_cents: int
    final_payment_cents: int
    amount_applied_cents: int
    remaining_balance_cents: int
    accrued_late_fees_cents: int
    written_off_cents: int
    delinquency_episodes: int
    first_due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    # Recorded payments are immutable: only id + created_at, no updated_at/version (PRD §2.4).
    id: str
    order_id: str
    rto_contract_id: Optional[str]
    kind: str
    amount_cents: int
    method: str
    idempotency_key: str
    applied_to_late_fees_cents: int
    applied_to_principal_cents: int
    recorded_by: str
    created_at: str


class ServiceTicket(TypedDict, total=False):
    id: str
    order_id: str
    issue_description: str
    status: str
    crew_id: Optional[str]
    scheduled_date: Optional[str]
    in_warranty: Optional[bool]
    parts_cents: int
    charge_cents: Optional[int]
    resolved_at: Optional[str]
    reopen_count: int
    created_at: str
    updated_at: str
    version: int
