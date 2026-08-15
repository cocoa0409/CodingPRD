"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§4)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ─────────────────────────────────

class UserRole(str, Enum):
    DEALER_ADMIN = "DealerAdmin"
    SALES_REP = "SalesRep"
    AGRONOMIST = "Agronomist"
    GROWER = "Grower"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"


# ─── Status enums (PRD §3) ────────────────────────────

class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    SALES_CLOSED = "SALES_CLOSED"
    SETTLED = "SETTLED"


class GrowerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"
    INACTIVE = "INACTIVE"


class FieldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class TraitPackageStatus(str, Enum):
    LISTED = "LISTED"
    RETIRED = "RETIRED"


class VarietyStatus(str, Enum):
    LISTED = "LISTED"
    DELISTED = "DELISTED"


class AgreementStatus(str, Enum):
    PENDING_SIGNATURE = "PENDING_SIGNATURE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class SuspensionReason(str, Enum):
    STEWARDSHIP_VIOLATION = "STEWARDSHIP_VIOLATION"
    PAPERWORK = "PAPERWORK"


class RecommendationStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    COMPLIANCE_HOLD = "COMPLIANCE_HOLD"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PREPAID = "PREPAID"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"


class FulfillmentStatus(str, Enum):
    NONE = "NONE"
    PARTIAL = "PARTIAL"
    DELIVERED = "DELIVERED"
    RETURNED_PARTIAL = "RETURNED_PARTIAL"
    RETURNED_FULL = "RETURNED_FULL"


class TreatmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DISCONTINUED = "DISCONTINUED"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"


class TicketStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TicketType(str, Enum):
    DELIVERY = "DELIVERY"
    PICKUP = "PICKUP"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    RECEIVED = "RECEIVED"
    CREDITED = "CREDITED"
    REJECTED = "REJECTED"


class ReturnReason(str, Enum):
    OVERSTOCK = "OVERSTOCK"
    WRONG_HYBRID = "WRONG_HYBRID"
    DAMAGED = "DAMAGED"
    OTHER = "OTHER"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class EventType(str, Enum):
    FROST = "FROST"
    FLOOD = "FLOOD"
    HAIL = "HAIL"
    DROUGHT = "DROUGHT"
    PEST = "PEST"


class PlotStatus(str, Enum):
    PLANNED = "PLANNED"
    PLANTED = "PLANTED"
    HARVESTED = "HARVESTED"
    PUBLISHED = "PUBLISHED"
    DISCARDED = "DISCARDED"


class StatementStatus(str, Enum):
    ACCRUING = "ACCRUING"
    FINALIZED = "FINALIZED"
    PAID = "PAID"


class SoilType(str, Enum):
    CLAY = "CLAY"
    LOAM = "LOAM"
    SAND = "SAND"
    SILT = "SILT"


class Drainage(str, Enum):
    POOR = "POOR"
    MODERATE = "MODERATE"
    WELL = "WELL"


class Crop(str, Enum):
    CORN = "CORN"
    SOYBEAN = "SOYBEAN"


class PrevCrop(str, Enum):
    CORN = "CORN"
    SOYBEAN = "SOYBEAN"
    WHEAT = "WHEAT"
    FALLOW = "FALLOW"
    OTHER = "OTHER"


# ─── Entity TypedDicts (PRD §2.5 common properties on all) ──

class SeedProgram(TypedDict, total=False):
    id: str
    name: str
    crop_year: int
    status: str
    early_order_tiers: List[dict]
    prepay_tiers: List[dict]
    volume_rebate_tiers: List[dict]
    return_window_end: str
    return_restocking_bps: int
    returns_untreated_only: bool
    replant_claim_window_days: int
    replant_replacement_discount_bps: int
    daily_delivery_capacity_units: int
    delivery_window_start: str
    delivery_window_end: str
    sales_close_at: str
    commission_base_bps: int
    commission_volume_tiers: List[dict]
    min_plot_replications: int
    opened_at: Optional[str]
    sales_closed_at: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GrowerAccount(TypedDict, total=False):
    id: str
    account_name: str
    external_ref: str
    credit_limit_cents: int
    status: str
    outstanding_balance_cents: int
    prepay_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Field(TypedDict, total=False):
    id: str
    grower_id: str
    name: str
    acres: float
    soil_type: str
    drainage: str
    irrigated: bool
    prev_crop: str
    maturity_zone: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TraitPackage(TypedDict, total=False):
    id: str
    code: str
    description: str
    requires_stewardship_agreement: bool
    refuge_required_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Variety(TypedDict, total=False):
    id: str
    sku: str
    crop: str
    relative_maturity_days: int
    trait_package_id: Optional[str]
    base_price_cents_per_unit: int
    seeds_per_unit: int
    preferred_soils: List[str]
    min_drainage: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TraitAgreement(TypedDict, total=False):
    id: str
    grower_id: str
    trait_package_id: str
    effective_from: str
    effective_to: str
    status: str
    supersedes_agreement_id: Optional[str]
    suspension_reason: Optional[str]
    signed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlacementRecommendation(TypedDict, total=False):
    id: str
    field_id: str
    variety_id: str
    program_id: str
    grower_id: str
    seeding_rate_seeds_per_acre: int
    expected_yield_index: float
    placement_score: float
    status: str
    supersedes_recommendation_id: Optional[str]
    published_at: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SeedOrder(TypedDict, total=False):
    id: str
    grower_id: str
    program_id: str
    recommendation_id: Optional[str]
    is_replacement: bool
    status: str
    payment_status: str
    fulfillment_status: str
    confirmed_at: Optional[str]
    locked_discount_bps: int
    total_units: int
    gross_amount_cents: int
    rebate_bps_applied: int
    rebate_amount_cents: int
    prepay_discount_cents: int
    net_amount_cents: int
    prepaid_amount_cents: int
    paid_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    variety_id: str
    treatment_option_id: Optional[str]
    units: int
    unit_price_cents: int
    discounted_unit_price_cents: Optional[int]
    line_total_cents: int
    inventory_lot_id: Optional[str]
    reserved_units: int
    delivered_units: int
    returned_units: int
    created_at: str
    updated_at: str
    version: int


class TreatmentOption(TypedDict, total=False):
    id: str
    code: str
    crop: str
    adder_cents_per_unit: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict, total=False):
    id: str
    variety_id: str
    treatment_option_id: Optional[str]
    warehouse_code: str
    received_units: int
    expiry_date: str
    on_hand_units: int
    reserved_units: int
    delivered_units: int
    returned_units: int
    written_off_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryTicket(TypedDict, total=False):
    id: str
    order_id: str
    order_line_id: str
    lot_id: str
    type: str
    scheduled_date: str
    units: int
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SeedReturn(TypedDict, total=False):
    id: str
    order_id: str
    order_line_id: str
    delivery_ticket_id: Optional[str]
    units: int
    reason: str
    status: str
    requested_at: str
    restocking_fee_cents: Optional[int]
    credit_estimate_cents: Optional[int]
    credit_cents: Optional[int]
    reject_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReplantClaim(TypedDict, total=False):
    id: str
    order_id: str
    order_line_id: str
    field_id: str
    event_date: str
    event_type: str
    acres_affected: float
    filed_by_user_id: str
    status: str
    replacement_order_id: Optional[str]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlotTrial(TypedDict, total=False):
    id: str
    program_id: str
    variety_id: str
    field_id: str
    planting_date: str
    expected_harvest_date: str
    replication_index: int
    yield_bu_per_acre: Optional[float]
    moisture_pct: Optional[float]
    actual_harvest_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CommissionStatement(TypedDict, total=False):
    id: str
    program_id: str
    status: str
    gross_sales_cents: int
    return_credits_cents: int
    net_sales_cents: int
    volume_units: int
    base_commission_cents: int
    volume_bonus_bps: int
    volume_bonus_cents: int
    total_commission_cents: int
    finalized_at: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
