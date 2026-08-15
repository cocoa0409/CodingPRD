"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this PRD carries the common system-managed field set
(id, created_at, updated_at, version).
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    DEALER_ADMIN = "DealerAdmin"
    ACCOUNT_EXECUTIVE = "AccountExecutive"
    CONTRACTS_OFFICER = "ContractsOfficer"
    DESIGNER = "Designer"
    CLIENT_APPROVER = "ClientApprover"
    PROJECT_MANAGER = "ProjectManager"
    WAREHOUSE_LEAD = "WarehouseLead"
    CLAIMS_COORDINATOR = "ClaimsCoordinator"
    MANUFACTURER_REP = "ManufacturerRep"
    LIQUIDATION_APPRAISER = "LiquidationAppraiser"
    FINANCE_MANAGER = "FinanceManager"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"
    CLOSED = "CLOSED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class ContractType(str, Enum):
    STATE = "STATE"
    COOP = "COOP"
    NEGOTIATED = "NEGOTIATED"


class SpacePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    IN_REVISION = "IN_REVISION"
    SUPERSEDED = "SUPERSEDED"


class Manufacturer(str, Enum):
    STEELCASE = "STEELCASE"
    MILLERKNOLL = "MILLERKNOLL"


class SeriesCategory(str, Enum):
    SEATING = "SEATING"
    SYSTEMS = "SYSTEMS"
    CASEGOODS = "CASEGOODS"
    TABLES = "TABLES"
    STORAGE = "STORAGE"


class SeriesStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DELIVERED = "DELIVERED"
    INSTALLED = "INSTALLED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class InstallPosture(str, Enum):
    NOT_SCHEDULED = "NOT_SCHEDULED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"


class OrderLineStatus(str, Enum):
    OPEN = "OPEN"
    PLACED = "PLACED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RECEIVED = "RECEIVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CrewStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class EventKind(str, Enum):
    NEW_INSTALL = "NEW_INSTALL"
    RECONFIGURATION = "RECONFIGURATION"


class InstallEventStatus(str, Enum):
    TENTATIVE = "TENTATIVE"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class PunchSeverity(str, Enum):
    STANDARD = "STANDARD"
    CRITICAL = "CRITICAL"


class PunchSource(str, Enum):
    INSTALL = "INSTALL"
    WAREHOUSE = "WAREHOUSE"


class PunchStatus(str, Enum):
    OPEN = "OPEN"
    READY_FOR_VERIFY = "READY_FOR_VERIFY"
    VERIFIED = "VERIFIED"
    CLOSED = "CLOSED"


class ClaimType(str, Enum):
    DEFECT = "DEFECT"
    FREIGHT_DAMAGE = "FREIGHT_DAMAGE"
    SHORTAGE = "SHORTAGE"


class Remedy(str, Enum):
    REPAIR = "REPAIR"
    REPLACE = "REPLACE"
    CREDIT = "CREDIT"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    SETTLEMENT_OFFERED = "SETTLEMENT_OFFERED"
    SETTLED = "SETTLED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class ClaimOrigin(str, Enum):
    MANUAL = "MANUAL"
    AUTO_CRITICAL_PUNCH = "AUTO_CRITICAL_PUNCH"


class AssetCondition(str, Enum):
    NEW = "NEW"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"


class AssetSource(str, Enum):
    PURCHASED = "PURCHASED"
    TRADED_IN = "TRADED_IN"


class AssetStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    IN_STORAGE = "IN_STORAGE"
    DISPOSED = "DISPOSED"


class LotStatus(str, Enum):
    OFFERED = "OFFERED"
    APPRAISED = "APPRAISED"
    CREDIT_ISSUED = "CREDIT_ISSUED"
    REDEEMED = "REDEEMED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry id/created_at/updated_at/version)
# ---------------------------------------------------------------------------


class Dealership(TypedDict, total=False):
    id: str
    name: str
    staging_capacity_units: int
    standard_labor_rate_cents_per_hour: int
    after_hours_start_minute: int
    after_hours_multiplier_bp: int
    turnover_buffer_minutes: int
    credit_cap_pct: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    dealership_id: str
    name: str
    external_ref: str
    status: str
    liquidation_credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class PricingContract(TypedDict, total=False):
    id: str
    customer_id: str
    contract_type: str
    pricing_tiers: List[Dict[str, Any]]
    default_discount_pct: int
    labor_rate_cents_per_hour: Optional[int]
    after_hours_multiplier_bp: Optional[int]
    effective_from: str
    effective_to: str
    supersedes_contract_id: Optional[str]
    created_by_user_id: str
    activated_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SpacePlan(TypedDict, total=False):
    id: str
    customer_id: str
    name: str
    revision_no: int
    supersedes_plan_id: Optional[str]
    approved_version: Optional[int]
    budget_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Typical(TypedDict, total=False):
    id: str
    space_plan_id: str
    code: str
    quantity: int
    target_budget_cents_per_instance: int
    extended_budget_cents: int
    created_at: str
    updated_at: str
    version: int


class ProductSeries(TypedDict, total=False):
    id: str
    dealership_id: str
    manufacturer: str
    category: str
    series_code: str
    base_list_price_cents: int
    base_lead_time_days: int
    option_catalog: List[Dict[str, Any]]
    quality_hold: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ProjectOrder(TypedDict, total=False):
    id: str
    customer_id: str
    contract_id: str
    space_plan_id: str
    pinned_contract_version: Optional[int]
    pinned_plan_version: Optional[int]
    total_list_cents: int
    total_net_cents: int
    install_fee_cents: int
    credit_applied_cents: int
    grand_total_cents: int
    promised_date: Optional[str]
    cancel_fee_cents: int
    status: str
    install_posture: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    series_id: str
    typical_id: Optional[str]
    quantity: int
    selected_options: List[str]
    is_replacement: bool
    unit_list_price_cents: int
    unit_net_price_cents: int
    line_total_cents: int
    provisional_lead_time_days: int
    provisional_promise_date: Optional[str]
    confirmed_lead_time_days: Optional[int]
    confirmed_promise_date: Optional[str]
    received_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict, total=False):
    id: str
    dealership_id: str
    name: str
    size: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InstallEvent(TypedDict, total=False):
    id: str
    order_id: str
    crew_id: str
    kind: str
    scheduled_date: str
    start_minute: int
    end_minute: int
    after_hours: bool
    labor_hours_estimated: Optional[float]
    labor_hours_actual: Optional[float]
    labor_cost_cents: Optional[int]
    asset_moves: Optional[List[Dict[str, Any]]]
    status: str
    created_at: str
    updated_at: str
    version: int


class StagingReservation(TypedDict, total=False):
    id: str
    order_line_id: str
    units: int
    start_date: str
    end_date: str
    received_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PunchItem(TypedDict, total=False):
    id: str
    order_id: str
    order_line_id: Optional[str]
    install_event_id: Optional[str]
    severity: str
    description: str
    source: str
    affected_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ManufacturerClaim(TypedDict, total=False):
    id: str
    punch_item_id: str
    series_id: str
    claim_type: str
    remedy_requested: str
    claimed_amount_cents: int
    settlement_amount_cents: Optional[int]
    settled_amount_cents: Optional[int]
    replacement_order_line_id: Optional[str]
    origin: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AssetTag(TypedDict, total=False):
    id: str
    customer_id: str
    series_id: Optional[str]
    description: str
    condition: str
    current_location: str
    source: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LiquidationLot(TypedDict, total=False):
    id: str
    customer_id: str
    description: str
    item_count: int
    condition_grade: Optional[str]
    estimated_credit_cents: int
    appraised_value_cents: Optional[int]
    appraised_at: Optional[str]
    appraised_by_user_id: Optional[str]
    issued_by_user_id: Optional[str]
    final_credit_cents: Optional[int]
    redeemed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
