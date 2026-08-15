"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.7, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    PLATFORM_ADMIN = "PlatformAdmin"
    SALES_DIRECTOR = "SalesDirector"
    SALES_AGENT = "SalesAgent"
    BUYER = "Buyer"
    CONSTRUCTION_MANAGER = "ConstructionManager"


class CommunityStatus(str, Enum):
    SETUP = "SETUP"
    SELLING = "SELLING"


class PricePhaseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class LotStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    CLOSED = "CLOSED"


class LotType(str, Enum):
    STANDARD = "STANDARD"
    CORNER = "CORNER"
    VIEW = "VIEW"
    CUL_DE_SAC = "CUL_DE_SAC"


class OptionCategory(str, Enum):
    STRUCTURAL = "STRUCTURAL"
    KITCHEN = "KITCHEN"
    BATH = "BATH"
    FLOORING = "FLOORING"
    ELECTRICAL = "ELECTRICAL"
    OUTDOOR = "OUTDOOR"


class BuildStage(str, Enum):
    """The five build stages plus the agreement-level bookend values (PRD §2.7)."""

    NOT_STARTED = "NOT_STARTED"
    PRE_CONSTRUCTION = "PRE_CONSTRUCTION"
    FOUNDATION = "FOUNDATION"
    FRAMING = "FRAMING"
    DRYWALL = "DRYWALL"
    FINAL_WALKTHROUGH = "FINAL_WALKTHROUGH"
    COMPLETE = "COMPLETE"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_CONTINGENCIES = "PENDING_CONTINGENCIES"
    CONTINGENCIES_CLEARED = "CONTINGENCIES_CLEARED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ContingencyStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    WAIVED = "WAIVED"


class SelectionStatus(str, Enum):
    SELECTED = "SELECTED"
    CONFIRMED = "CONFIRMED"
    INSTALLED = "INSTALLED"
    CANCELLED = "CANCELLED"


class SelectionCancelReason(str, Enum):
    BUYER_REQUEST = "BUYER_REQUEST"
    CUTOFF_EXPIRED = "CUTOFF_EXPIRED"
    AGREEMENT_CANCELLED = "AGREEMENT_CANCELLED"


class MilestoneStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    COMPLETE = "COMPLETE"


class IncentiveType(str, Enum):
    RATE_BUYDOWN = "RATE_BUYDOWN"
    CLOSING_COST_CREDIT = "CLOSING_COST_CREDIT"
    PRICE_REDUCTION = "PRICE_REDUCTION"


class IncentiveStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class AgreementCancelReason(str, Enum):
    BUYER_DEFAULT = "BUYER_DEFAULT"
    BUILDER_DEFAULT = "BUILDER_DEFAULT"
    CONTINGENCY_EXPIRED = "CONTINGENCY_EXPIRED"


class WarrantyStatus(str, Enum):
    NONE = "NONE"
    ENROLLED = "ENROLLED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


# All resources share the four system-managed properties of PRD §2.4:
# id, created_at, updated_at, version.


class Community(TypedDict, total=False):
    id: str
    name: str
    incentive_budget_total_cents: int
    incentive_budget_remaining_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PricePhase(TypedDict, total=False):
    id: str
    community_id: str
    phase_name: str
    uplift_pct: float
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict, total=False):
    id: str
    community_id: str
    lot_number: str
    base_price_cents: int
    lot_type: str
    view_adjustment_cents: int
    release_price_cents: Optional[int]
    release_count: int
    reserved_buyer_id: Optional[str]
    hold_expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Elevation(TypedDict):
    name: str
    price_cents: int


class HomePlan(TypedDict, total=False):
    id: str
    community_id: str
    plan_name: str
    base_price_cents: int
    elevations: List[Elevation]
    created_at: str
    updated_at: str
    version: int


class OptionCatalogItem(TypedDict, total=False):
    id: str
    community_id: str
    option_name: str
    category: str
    price_cents: int
    cutoff_stage: str
    install_stage: str
    created_at: str
    updated_at: str
    version: int


class Buyer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class PurchaseAgreement(TypedDict, total=False):
    id: str
    buyer_id: str
    lot_id: str
    plan_id: str
    community_id: str
    elevation_name: str
    earnest_money_deposited_cents: int
    contingency_deadline: str
    outside_close_date: str
    has_sale_of_home_contingency: bool
    status: str
    financing_contingency_status: str
    appraisal_contingency_status: str
    sale_of_home_contingency_status: str
    current_stage: str
    lot_price_snapshot_cents: Optional[int]
    plan_price_snapshot_cents: Optional[int]
    elevation_price_snapshot_cents: Optional[int]
    provisional_total_cents: Optional[int]
    options_total_cents: int
    change_fees_total_cents: int
    incentives_total_cents: int
    final_total_cents: Optional[int]
    estimated_close_standard: Optional[str]
    estimated_close_padded: Optional[str]
    slippage_flag: bool
    cancel_reason: Optional[str]
    refund_amount_cents: Optional[int]
    forfeited_amount_cents: Optional[int]
    warranty_status: str
    warranty_term_months: int
    warranty_enrolled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OptionSelection(TypedDict, total=False):
    id: str
    agreement_id: str
    option_item_id: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int
    change_fee_cents: int
    selected_at_stage: str
    confirmed_at_stage: Optional[str]
    status: str
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConstructionMilestone(TypedDict, total=False):
    id: str
    agreement_id: str
    stage: str
    sequence_no: int
    planned_duration_days: int
    status: str
    completed_at: Optional[str]
    buyer_notified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncentiveRequest(TypedDict, total=False):
    id: str
    agreement_id: str
    incentive_type: str
    amount_cents: int
    status: str
    auto_approved: bool
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
