"""Domain types: entity record shapes, status enums, role enum.

Primary resources carry id + created_at + updated_at + version (PRD §2.4).
Formula lines and batch adjustments are append-only sub-records that carry
only id + created_at — updated_at and version are absent from them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLANT_MANAGER = "PlantManager"
    LAB_TECHNICIAN = "LabTechnician"
    PRODUCTION_OPERATOR = "ProductionOperator"
    QC_INSPECTOR = "QCInspector"
    REGULATORY_CLERK = "RegulatoryClerk"
    DEALER = "Dealer"


class ProductCategory(str, Enum):
    FLAT = "FLAT"
    NONFLAT = "NONFLAT"
    PRIMER = "PRIMER"
    INDUSTRIAL_MAINTENANCE = "INDUSTRIAL_MAINTENANCE"
    TRAFFIC_MARKING = "TRAFFIC_MARKING"


class BaseFamily(str, Enum):
    LATEX_INTERIOR = "LATEX_INTERIOR"
    LATEX_EXTERIOR = "LATEX_EXTERIOR"
    ALKYD = "ALKYD"


class FormulaStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"


class VocRuleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class MillStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"


class BatchStatus(str, Enum):
    PLANNED = "PLANNED"
    MILLING = "MILLING"
    TINTING = "TINTING"
    QC_PENDING = "QC_PENDING"
    QC_APPROVED = "QC_APPROVED"
    FILLING = "FILLING"
    FILLED = "FILLED"
    CLOSED = "CLOSED"
    REWORK = "REWORK"
    ON_HOLD = "ON_HOLD"
    DISPOSAL_PENDING = "DISPOSAL_PENDING"
    DISPOSED = "DISPOSED"
    CANCELLED = "CANCELLED"


class AdjustmentKind(str, Enum):
    THINNER = "THINNER"
    THICKENER = "THICKENER"
    TINT_SHOT = "TINT_SHOT"
    EXEMPT_SOLVENT = "EXEMPT_SOLVENT"


class ColorMatchStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ContainerStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"
    SHIPPED = "SHIPPED"
    RETURNED = "RETURNED"
    OBSOLETE = "OBSOLETE"
    DISPOSAL_PENDING = "DISPOSAL_PENDING"
    DISPOSED = "DISPOSED"


class SizeCode(str, Enum):
    QUART = "QUART"
    GALLON = "GALLON"
    FIVE_GALLON = "FIVE_GALLON"


class OrderStatus(str, Enum):
    PLACED = "PLACED"
    RUSH_REVIEW = "RUSH_REVIEW"
    SCHEDULED = "SCHEDULED"
    IN_PRODUCTION = "IN_PRODUCTION"
    BLOCKED = "BLOCKED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class ClaimType(str, Enum):
    FREEZE_DAMAGE = "FREEZE_DAMAGE"
    SHELF_LIFE_EXPIRY = "SHELF_LIFE_EXPIRY"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class DisposalReason(str, Enum):
    OBSOLETE_STOCK = "OBSOLETE_STOCK"
    RETURNED_GOODS = "RETURNED_GOODS"
    BATCH_REJECT = "BATCH_REJECT"
    DAMAGED_STOCK = "DAMAGED_STOCK"


class HazmatClass(str, Enum):
    HAZARDOUS = "HAZARDOUS"
    NON_HAZARDOUS = "NON_HAZARDOUS"


class DisposalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    MANIFESTED = "MANIFESTED"
    DISPOSED = "DISPOSED"
    CANCELLED = "CANCELLED"


# ─── Entity records (common fields: id/created_at/updated_at/version) ───


class Customer(TypedDict, total=False):
    id: str
    name: str
    home_state_code: str
    annual_credit_cap_cents: int
    credit_balance_cents: int
    credit_used_ytd_cents: int
    created_at: str
    updated_at: str
    version: int


class TintBase(TypedDict, total=False):
    id: str
    base_code: str
    product_category: str
    base_family: str
    base_voc_gpl: float
    water_fraction_pct: float
    density_kg_per_gal: float
    base_cost_per_gal_cents: int
    unit_price_per_gal_cents: int
    shelf_life_months: int
    grind_spec_um: float
    created_at: str
    updated_at: str
    version: int


class Colorant(TypedDict, total=False):
    id: str
    colorant_code: str
    voc_g_per_unit: float
    cost_per_shot_cents: int
    is_hazmat: bool
    created_at: str
    updated_at: str
    version: int


class Formula(TypedDict, total=False):
    id: str
    formula_code: str
    color_name: str
    tint_base_id: str
    is_custom: bool
    target_delta_e: float
    min_batch_gallons: int
    formula_version_no: int
    predecessor_formula_id: Optional[str]
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FormulaLine(TypedDict, total=False):
    """Append-only sub-record: id + created_at only (no updated_at/version)."""

    id: str
    formula_id: str
    colorant_id: str
    shots_per_gallon: float
    sequence: int
    created_at: str


class VocRule(TypedDict, total=False):
    id: str
    category: str
    state_code: str
    max_voc_gpl: float
    effective_from: str
    effective_to: Optional[str]
    exempt_container_l: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Mill(TypedDict, total=False):
    id: str
    mill_code: str
    capacity_gallons: int
    status: str
    reserved_minutes: int
    created_at: str
    updated_at: str
    version: int


class Batch(TypedDict, total=False):
    id: str
    batch_code: str
    formula_id: str
    pinned_formula_version_no: int
    product_category: str
    base_family: str
    mill_id: str
    order_id: Optional[str]
    planned_gallons: float
    actual_gallons: Optional[float]
    mill_window_start: str
    mill_window_end: str
    status: str
    rework_count: int
    dispersion_cycles: int
    voc_actual_gpl: Optional[float]
    theoretical_cost_cents: int
    actual_cost_cents: Optional[int]
    filled_net_kg: float
    waste_gallons: Optional[float]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BatchAdjustment(TypedDict, total=False):
    """Append-only sub-record: id + created_at only (no updated_at/version)."""

    id: str
    batch_id: str
    kind: str
    quantity: float
    colorant_id: Optional[str]
    voc_contribution_g: float
    cycle_index: int
    created_at: str


class ColorMatch(TypedDict, total=False):
    id: str
    batch_id: str
    cycle_index: int
    measured_delta_e: float
    threshold_delta_e: float
    measured_by_user_id: str
    status: str
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    retain_sample_id: Optional[str]
    retain_until: Optional[str]
    retain_purged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Container(TypedDict, total=False):
    id: str
    batch_id: str
    size_code: str
    nominal_fill_g: int
    actual_fill_g: int
    fill_variance_g: int
    net_weight_kg: float
    volume_gal: float
    size_liters: float
    status: str
    order_id: Optional[str]
    destination_state_code: Optional[str]
    manufactured_at: str
    expiry_date: str
    freeze_exposure_count: int
    shipped_at: Optional[str]
    disposal_request_id: Optional[str]
    pre_disposal_status: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict, total=False):
    id: str
    customer_id: str
    destination_state_code: str
    rush_flag: bool
    lines: List[dict]
    is_custom_order: bool
    subtotal_cents: int
    setup_fee_cents: int
    rush_fee_cents: int
    total_cents: int
    status: str
    rush_approved_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditClaim(TypedDict, total=False):
    id: str
    customer_id: str
    container_id: str
    claim_type: str
    invoice_value_cents: int
    claimed_exposure_count: int
    verified_exposure_count: Optional[int]
    remaining_days_at_claim: int
    provisional_credit_cents: int
    final_credit_cents: Optional[int]
    reviewed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    settled_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DisposalRequest(TypedDict, total=False):
    id: str
    reason: str
    container_ids: List[str]
    batch_ids: List[str]
    hazmat_class: str
    manifest_no: Optional[str]
    expected_destroyed_kg: float
    actual_destroyed_kg: Optional[float]
    gross_cost_cents: Optional[int]
    recovery_credit_cents: Optional[int]
    net_cost_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
