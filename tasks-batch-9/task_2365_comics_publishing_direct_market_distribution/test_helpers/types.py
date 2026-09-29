"""Domain types for the Comics Direct Market Publishing API.

Status enums, role enum and entity TypedDicts, all named exactly as the PRD
names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────

class UserRole(str, Enum):
    EDITOR_IN_CHIEF = "EditorInChief"
    MANAGING_EDITOR = "ManagingEditor"
    SALES_DIRECTOR = "SalesDirector"
    ROYALTY_ACCOUNTANT = "RoyaltyAccountant"
    CREATOR = "Creator"
    RETAILER = "Retailer"


# ─── Vocabularies ─────────────────────────────────────

class Craft(str, Enum):
    SCRIPT = "SCRIPT"
    PENCILS = "PENCILS"
    INKS = "INKS"
    COLORS = "COLORS"
    LETTERS = "LETTERS"
    COVER = "COVER"


class TitleStatus(str, Enum):
    PITCHED = "PITCHED"
    GREENLIT = "GREENLIT"
    IN_PRODUCTION = "IN_PRODUCTION"
    PUBLISHING = "PUBLISHING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CreativeAssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class IssueProductionStatus(str, Enum):
    PLANNED = "PLANNED"
    SCRIPTING = "SCRIPTING"
    ART = "ART"
    PREPRESS = "PREPRESS"
    CAMERA_READY = "CAMERA_READY"
    CANCELLED = "CANCELLED"


class IssueCommercialStatus(str, Enum):
    UNSOLICITED = "UNSOLICITED"
    SOLICITED = "SOLICITED"
    FOC_LOCKED = "FOC_LOCKED"
    PRINTED = "PRINTED"
    ON_SALE = "ON_SALE"
    CANCELLED = "CANCELLED"


class ScheduleHealth(str, Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    SLIPPED = "SLIPPED"


class ProductionStageStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    DELIVERED = "DELIVERED"
    KICKED_BACK = "KICKED_BACK"
    APPROVED = "APPROVED"
    CANCELLED = "CANCELLED"


class CatalogStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    PUBLISHED = "PUBLISHED"


class SolicitationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    WITHDRAWN = "WITHDRAWN"


class VariantCoverKind(str, Enum):
    STANDARD = "STANDARD"
    RATIO_INCENTIVE = "RATIO_INCENTIVE"
    RETAILER_EXCLUSIVE = "RETAILER_EXCLUSIVE"


class RetailerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DiscountTier(str, Enum):
    ENTRY = "ENTRY"
    BASIC = "BASIC"
    CORE = "CORE"
    PREMIER = "PREMIER"


class RetailerOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FOC_LOCKED = "FOC_LOCKED"
    INVOICED = "INVOICED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class PrintRunBasis(str, Enum):
    ORDER_DRIVEN = "ORDER_DRIVEN"
    DEMAND_FORECAST = "DEMAND_FORECAST"


class PrintRunStatus(str, Enum):
    PLANNED = "PLANNED"
    PRINTED = "PRINTED"
    CANCELLED = "CANCELLED"


class ReleaseWindowChannel(str, Enum):
    DIGITAL = "DIGITAL"
    COLLECTED = "COLLECTED"


class RevenueChannel(str, Enum):
    PRINT_DM = "PRINT_DM"
    DIGITAL = "DIGITAL"
    COLLECTED = "COLLECTED"
    SUBSIDIARY = "SUBSIDIARY"


class RevenueBasisStatus(str, Enum):
    ESTIMATED = "ESTIMATED"
    ACTUAL = "ACTUAL"


class RevenueSource(str, Enum):
    MANUAL = "MANUAL"
    SHIPMENT = "SHIPMENT"


class RoyaltyStatementBasis(str, Enum):
    ESTIMATED = "ESTIMATED"
    SETTLED = "SETTLED"


class RoyaltyStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    REVERSED = "REVERSED"


# ─── Entities carrying id + created_at + updated_at + version ─────────

class Creator(TypedDict):
    id: str
    full_name: str
    crafts: List[str]
    default_page_rate_cents: int
    active_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class Title(TypedDict):
    id: str
    name: str
    planned_issue_count: int
    royalty_pool_bps: int
    cover_participation_bps: int
    status: str
    greenlit_at: Optional[str]
    committed_share_bps: int
    production_cost_cents: int
    royalty_accrued_cents: int
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreativeAssignment(TypedDict):
    id: str
    title_id: str
    creator_id: str
    craft: str
    page_rate_cents: int
    royalty_share_bps: int
    booking_start_date: str
    booking_end_date: str
    advance_cents: int
    unrecouped_advance_cents: int
    status: str
    negotiation_round: int
    counter_page_rate_cents: Optional[int]
    counter_royalty_share_bps: Optional[int]
    terminated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Issue(TypedDict):
    id: str
    title_id: str
    issue_number: int
    page_count: int
    cover_price_cents: int
    target_on_sale_date: str
    foc_date: str
    production_status: str
    commercial_status: str
    schedule_health: str
    total_slip_days: int
    total_ordered_units: int
    printed_units: int
    shipped_units: int
    on_sale_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductionStage(TypedDict):
    id: str
    issue_id: str
    assignment_id: str
    craft: str
    planned_start_date: str
    planned_due_date: str
    actual_delivered_at: Optional[str]
    delivered_pages: Optional[int]
    slip_days: int
    page_fee_cents: int
    kickback_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Catalog(TypedDict):
    id: str
    solicitation_month: str
    submission_deadline: str
    on_sale_month: str
    max_slots: int
    status: str
    accepted_slot_count: int
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Solicitation(TypedDict):
    id: str
    catalog_id: str
    issue_id: str
    cover_image_url: str
    copy_text: str
    variant_cover_ids: List[str]
    status: str
    submitted_at: Optional[str]
    withdrawn_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Retailer(TypedDict):
    id: str
    account_no: str
    name: str
    credit_limit_cents: int
    non_returnable_ack: bool
    opening_units_ytd: int
    cumulative_units_ytd: int
    open_balance_cents: int
    discount_tier: str
    status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetailerOrder(TypedDict):
    id: str
    retailer_id: str
    issue_id: str
    standard_qty: int
    exclusive_variant_qty: int
    earned_variant_allocations: List[dict]
    total_units: int
    is_reorder: bool
    discount_tier_applied: Optional[str]
    merchandise_net_cents: int
    handling_fee_cents: int
    invoice_total_cents: int
    status: str
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrintRun(TypedDict):
    id: str
    issue_id: str
    printing_number: int
    basis: str
    quantity: int
    order_base_units: int
    overprint_units: int
    status: str
    printed_at: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoyaltyStatement(TypedDict):
    id: str
    title_id: str
    creator_id: str
    period: str
    basis: str
    lines: List[dict]
    gross_royalty_cents: int
    recoupment_applied_cents: int
    payable_cents: int
    status: str
    issued_by_user_id: Optional[str]
    paid_by_user_id: Optional[str]
    payment_reference: Optional[str]
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── Immutable records: only id + created_at (no updated_at, no version) ───

class VariantCover(TypedDict):
    id: str
    issue_id: str
    code: str
    kind: str
    incentive_ratio: Optional[int]
    cover_price_cents: int
    allocation_cap: Optional[int]
    created_at: str


class ReleaseWindow(TypedDict):
    id: str
    issue_id: str
    channel: str
    release_date: str
    expected_net_receipts_cents: int
    created_at: str


class RevenueEvent(TypedDict):
    id: str
    issue_id: str
    channel: str
    basis_status: str
    gross_receipts_cents: int
    net_receipts_cents: int
    units: int
    period: str
    source: str
    created_at: str


IMMUTABLE_RECORD_TYPES = ("VariantCover", "ReleaseWindow", "RevenueEvent")
