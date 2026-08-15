"""Domain types: entity TypedDicts, status enums, role enum.

Every primary resource carries id + created_at + updated_at + version,
except FeedCall, which is an immutable event record and carries only
id and created_at (no updated_at, no version).
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class OwnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PenStatus(str, Enum):
    EMPTY = "EMPTY"
    OCCUPIED = "OCCUPIED"
    MAINTENANCE = "MAINTENANCE"


class LotStatus(str, Enum):
    OPEN = "OPEN"
    MARKETED = "MARKETED"
    SHIPPED = "SHIPPED"
    CLOSED_OUT = "CLOSED_OUT"
    SETTLED = "SETTLED"


class SexClass(str, Enum):
    STEER = "STEER"
    HEIFER = "HEIFER"


class PenAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class RationAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class HealthEventStatus(str, Enum):
    WITHDRAWAL_ACTIVE = "WITHDRAWAL_ACTIVE"
    CLEARED = "CLEARED"


class DeathLossStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class InsuranceClaimStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class HedgeSide(str, Enum):
    SHORT = "SHORT"
    LONG = "LONG"


class HedgeStatus(str, Enum):
    OPEN = "OPEN"
    OFFSET = "OFFSET"
    EXPIRED = "EXPIRED"


class PricingBasis(str, Enum):
    PER_CARCASS = "PER_CARCASS"
    LOT_AVERAGE = "LOT_AVERAGE"


class QualityGrade(str, Enum):
    PRIME = "PRIME"
    CHOICE = "CHOICE"
    SELECT = "SELECT"
    STANDARD = "STANDARD"


class CloseOutStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    SUPERSEDED = "SUPERSEDED"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    VOID = "VOID"


class UserRole(str, Enum):
    FEEDYARD_MANAGER = "FeedyardManager"
    FEED_MANAGER = "FeedManager"
    CATTLE_HEALTH_TECH = "CattleHealthTech"
    RISK_MANAGER = "RiskManager"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    CLAIMS_TREASURER = "ClaimsTreasurer"
    BILLING_CLERK = "BillingClerk"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all common_fields entities unless noted)
# ---------------------------------------------------------------------------

class Owner(TypedDict):
    id: str
    owner_name: str
    billing_email: str
    status: str
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Pen(TypedDict):
    id: str
    pen_code: str
    capacity_head: int
    status: str
    current_occupancy_head: int
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict):
    id: str
    owner_id: str
    lot_number: str
    sex_class: str
    head_count_in: int
    in_weight_total_lbs: int
    purchase_cost_cents: int
    arrival_date: str
    commingle_allowed: bool
    status: str
    head_count_current: int
    head_shipped: int
    total_deaths: int
    out_weight_total_lbs: Optional[int]
    total_feed_cost_cents: int
    total_health_cost_cents: int
    total_death_loss_cents: int
    total_hedge_pnl_cents: int
    insurance_credit_pending_cents: int
    withdrawal_clear_date: Optional[str]
    provisional_cog_cents_per_cwt: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Ration(TypedDict):
    id: str
    ration_name: str
    step_level: int
    cost_per_ton_cents: int
    created_at: str
    updated_at: str
    version: int


class PenAssignment(TypedDict):
    id: str
    pen_id: str
    lot_id: str
    head_count: int
    start_date: str
    end_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RationAssignment(TypedDict):
    id: str
    lot_id: str
    ration_id: str
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FeedCall(TypedDict, total=False):
    # Immutable event record: carries ONLY id + created_at as common fields.
    id: str
    created_at: str
    pen_id: str
    call_date: str
    bunk_score: Optional[int]
    base_qty_lbs_per_head: Optional[float]
    ration_id: str
    qty_lbs_per_head: float
    total_qty_lbs: int
    total_cost_cents: int


class HealthEvent(TypedDict):
    id: str
    lot_id: str
    treatment_date: str
    drug_product: str
    withdrawal_days: int
    head_treated: int
    treatment_cost_cents: int
    withdrawal_end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DeathLossAllocation(TypedDict):
    assignment_id: str
    head_count: int


class DeathLoss(TypedDict):
    id: str
    lot_id: str
    loss_date: str
    head_count: int
    cause: str
    insured: bool
    loss_value_cents: int
    allocations: List[DeathLossAllocation]
    status: str
    created_at: str
    updated_at: str
    version: int


class InsuranceClaim(TypedDict):
    id: str
    death_loss_id: str
    claimed_amount_cents: int
    approved_amount_cents: Optional[int]
    status: str
    appeal_count: int
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HedgePosition(TypedDict):
    id: str
    lot_id: str
    contract_month: str
    side: str
    quantity_contracts: int
    entry_price_cents_per_cwt: int
    exit_price_cents_per_cwt: Optional[int]
    realized_pnl_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CarcassRecord(TypedDict):
    hot_carcass_weight_lbs: int
    quality_grade: str
    yield_grade: int


class CloseOut(TypedDict):
    id: str
    lot_id: str
    pricing_basis: str
    grid_base_price_cents_per_cwt: int
    carcass_records: Optional[List[CarcassRecord]]
    total_grid_value_cents: Optional[float]
    total_cost_cents: Optional[int]
    final_cog_cents_per_cwt: Optional[float]
    hedge_pnl_cents: Optional[int]
    net_result_cents: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    lot_id: str
    owner_id: str
    feed_cents: int
    yardage_cents: int
    yardage_head_days: int
    health_cents: int
    death_loss_cents: int
    insurance_credit_cents: int
    total_cents: int
    amount_paid_cents: int
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
