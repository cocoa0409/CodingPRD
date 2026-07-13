"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD entity model. Every entity in this system carries the full
set of common fields (id, created_at, updated_at, version) per PRD 2.4.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Roles ---
class UserRole(str, Enum):
    PRODUCTION_MANAGER = "ProductionManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SALES_MANAGER = "SalesManager"
    TASTING_ROOM_STAFF = "TastingRoomStaff"
    CUSTOMER = "Customer"


# --- Status enums ---
class MashBatchStatus(str, Enum):
    FERMENTING = "FERMENTING"
    DISTILLED = "DISTILLED"
    ARCHIVED = "ARCHIVED"
    DUMPED = "DUMPED"


class DistillationRunStatus(str, Enum):
    DISTILLING = "DISTILLING"
    GAUGED = "GAUGED"
    CLOSED = "CLOSED"


class BarrelStatus(str, Enum):
    AGING = "AGING"
    EMPTIED = "EMPTIED"
    DESTROYED = "DESTROYED"


class LabelApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    NEEDS_CORRECTION = "NEEDS_CORRECTION"
    APPROVED = "APPROVED"


class BottlingRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    BOTTLING = "BOTTLING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TaxStatus(str, Enum):
    IN_BOND = "IN_BOND"
    TAX_DETERMINED = "TAX_DETERMINED"


class InventoryStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    SOLD_OUT = "SOLD_OUT"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class TourBookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class ExciseReportStatus(str, Enum):
    FILED = "FILED"
    SUPERSEDED = "SUPERSEDED"


class CbmaRateTier(str, Enum):
    REDUCED = "REDUCED"
    STANDARD = "STANDARD"


class ClubTier(str, Enum):
    NONE = "NONE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    RESERVE = "RESERVE"


# --- Entity TypedDicts (all carry the full common-field set) ---
class Distillery(TypedDict):
    id: str
    name: str
    dsp_permit_number: str
    state_code: str
    total_gauged_pg: float
    production_account_pg: float
    storage_account_pg: float
    processing_account_pg: float
    removed_pg: float
    angel_share_losses_pg: float
    bottling_losses_pg: float
    destroyed_losses_pg: float
    bonded_total_pg: float
    cbma_pg_removed_ytd: float
    cbma_rate_tier: str
    club_release_active: bool
    created_at: str
    updated_at: str
    version: int


class MashBatch(TypedDict):
    id: str
    distillery_id: str
    grain_bill: str
    volume_gallons: float
    status: str
    created_at: str
    updated_at: str
    version: int


class DistillationRun(TypedDict):
    id: str
    distillery_id: str
    mash_batch_id: str
    spirit_type: str
    gauge_method: str
    collected_wine_gallons: float
    collected_proof: float
    collected_weight_lbs: Optional[float]
    proof_gallons: float
    remaining_proof_gallons: float
    open_barrel_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Barrel(TypedDict):
    id: str
    distillation_run_id: str
    distillery_id: str
    char_level: str
    rickhouse_position: str
    fill_proof_gallons: float
    fill_date: str
    angel_share_pg: float
    current_proof_gallons: float
    status: str
    created_at: str
    updated_at: str
    version: int


class LabelApplication(TypedDict):
    id: str
    distillery_id: str
    brand_name: str
    spirit_type: str
    label_proof: float
    net_contents_ml: float
    ttb_id: Optional[str]
    correction_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BottlingRun(TypedDict):
    id: str
    barrel_id: str
    label_application_id: str
    distillery_id: str
    line_id: str
    scheduled_start: str
    scheduled_end: str
    bottle_size_ml: float
    bottles_per_case: int
    planned_cases: int
    draw_proof_gallons: float
    bottled_proof_gallons: float
    bottling_loss_pg: float
    cases_bottled: int
    cases_available: int
    cases_reserved: int
    cases_shipped: int
    cases_removed: int
    tax_status: str
    inventory_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxRemoval(TypedDict):
    id: str
    bottling_run_id: str
    distillery_id: str
    removal_reason: str
    removed_cases: int
    removed_proof_gallons: float
    reduced_rate_pg: float
    standard_rate_pg: float
    excise_tax_due_cents: int
    removal_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ExciseReport(TypedDict):
    id: str
    distillery_id: str
    period_month: str
    expected_distillery_version: int
    total_removed_pg: float
    total_excise_due_cents: int
    supersedes_report_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    name: str
    email: str
    state_code: str
    club_tier: str
    age_verified: bool
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict):
    id: str
    customer_id: str
    bottling_run_id: str
    distillery_id: str
    channel: str
    cases: int
    unit_price_cents: int
    includes_cocktail: bool
    subtotal_cents: int
    total_cents: int
    payment_status: str
    fulfillment_status: str
    created_at: str
    updated_at: str
    version: int


class TourBooking(TypedDict):
    id: str
    customer_id: str
    distillery_id: str
    start_time: str
    end_time: str
    party_size: int
    includes_tasting: bool
    status: str
    created_at: str
    updated_at: str
    version: int
