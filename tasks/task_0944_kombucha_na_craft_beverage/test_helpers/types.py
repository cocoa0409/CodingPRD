"""Domain types for the kombucha / non-alcoholic craft beverage API.

Status enums, role names and entity shapes exactly as the PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD section 2.1 — the seven role names, spelled exactly as shown)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PRODUCTION_OPERATOR = "ProductionOperator"
    QA_MANAGER = "QaManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SALES_REP = "SalesRep"
    TAPROOM_STAFF = "TaproomStaff"
    SUBSCRIBER = "Subscriber"
    PLATFORM_ADMIN = "PlatformAdmin"


ALL_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Enumerations carried on resources
# --------------------------------------------------------------------------
class RecipeStyle(str, Enum):
    KOMBUCHA = "KOMBUCHA"
    JUN = "JUN"
    WATER_KEFIR = "WATER_KEFIR"
    HOP_TONIC = "HOP_TONIC"
    BOTANICAL_SODA = "BOTANICAL_SODA"


class AbvClass(str, Enum):
    NON_ALCOHOLIC = "NON_ALCOHOLIC"
    ALCOHOLIC = "ALCOHOLIC"


class LabelApprovalStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    STALE = "STALE"


class ScobyCultureState(str, Enum):
    ACTIVE = "ACTIVE"
    REVERIFICATION_PENDING = "REVERIFICATION_PENDING"
    RETIRED = "RETIRED"
    CONTAMINATED = "CONTAMINATED"


class RetireReason(str, Enum):
    GENERATION_CAP = "GENERATION_CAP"
    VITALITY = "VITALITY"
    CONTAMINATION = "CONTAMINATION"
    OPERATOR = "OPERATOR"


class VesselState(str, Enum):
    DIRTY = "DIRTY"
    CIP_IN_PROGRESS = "CIP_IN_PROGRESS"
    SANITIZED = "SANITIZED"
    OCCUPIED = "OCCUPIED"


class IngredientType(str, Enum):
    TEA = "TEA"
    SUGAR = "SUGAR"
    CULTURE_NUTRIENT = "CULTURE_NUTRIENT"
    JUICE = "JUICE"
    BOTANICAL = "BOTANICAL"
    HOPS = "HOPS"


class IngredientLotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIALLY_CONSUMED = "PARTIALLY_CONSUMED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    QUARANTINED = "QUARANTINED"


class FermentStage(str, Enum):
    F1_ACTIVE = "F1_ACTIVE"
    F2_ACTIVE = "F2_ACTIVE"
    READY_TO_PACKAGE = "READY_TO_PACKAGE"
    PACKAGED = "PACKAGED"
    DUMPED = "DUMPED"


class QaDisposition(str, Enum):
    PENDING = "PENDING"
    CONFORMING = "CONFORMING"
    AT_RISK = "AT_RISK"
    NONCONFORMING = "NONCONFORMING"


class ReadingType(str, Enum):
    F1 = "F1"
    F2 = "F2"
    PACKAGING = "PACKAGING"


class FlagReason(str, Enum):
    PH_REGRESSION = "PH_REGRESSION"
    PH_HARD_FLOOR = "PH_HARD_FLOOR"
    TEMP_EXCURSION = "TEMP_EXCURSION"
    READING_GAP = "READING_GAP"


class ContainerFormat(str, Enum):
    KEG = "KEG"
    BOTTLE = "BOTTLE"
    CAN = "CAN"


class PackagingRunStatus(str, Enum):
    DRAFT = "DRAFT"
    SOURCED = "SOURCED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    RECALL_FLAGGED = "RECALL_FLAGGED"


class FinishedLotStatus(str, Enum):
    HELD = "HELD"
    RELEASED = "RELEASED"
    QUARANTINED = "QUARANTINED"
    RECALLED = "RECALLED"
    DEPLETED = "DEPLETED"


class KegStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    FILLED = "FILLED"
    ON_TAP = "ON_TAP"
    EMPTY = "EMPTY"
    ON_DEPOSIT = "ON_DEPOSIT"
    RETURNED = "RETURNED"
    SCRAPPED = "SCRAPPED"


class DepositState(str, Enum):
    NONE = "NONE"
    CHARGED = "CHARGED"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


class KegCondition(str, Enum):
    GOOD = "GOOD"
    DAMAGED = "DAMAGED"


class AccountChannel(str, Enum):
    WHOLESALE_DISTRIBUTOR = "WHOLESALE_DISTRIBUTOR"
    SELF_DISTRIBUTION = "SELF_DISTRIBUTION"


class AccountStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"


class ShipmentStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    DELIVERED = "DELIVERED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"
    RECALL_HOLD = "RECALL_HOLD"


class ShipmentLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RECALLED = "RECALLED"
    CANCELLED = "CANCELLED"


class AgingBucket(str, Enum):
    CURRENT = "CURRENT"
    B1_1_30 = "B1_1_30"
    B2_31_60 = "B2_31_60"
    B3_61_PLUS = "B3_61_PLUS"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class AllocationStatus(str, Enum):
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    REVERSED = "REVERSED"


class ReversalReason(str, Enum):
    LOT_QUARANTINED = "LOT_QUARANTINED"
    LOT_RECALLED = "LOT_RECALLED"
    SUBSCRIPTION_CANCELLED = "SUBSCRIPTION_CANCELLED"


class TaproomContainerType(str, Enum):
    HOUSE_GROWLER = "HOUSE_GROWLER"
    CUSTOMER_GROWLER = "CUSTOMER_GROWLER"
    GLASS_POUR = "GLASS_POUR"


class FillStatus(str, Enum):
    REQUESTED = "REQUESTED"
    INSPECTED = "INSPECTED"
    POURED = "POURED"


class RecallNoticeStatus(str, Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    OVERDUE = "OVERDUE"


class RecallTriggerSource(str, Enum):
    INGREDIENT_LOT_QUARANTINE = "INGREDIENT_LOT_QUARANTINE"
    LOT_QUARANTINE = "LOT_QUARANTINE"
    LOT_RECALL = "LOT_RECALL"


class LabelElement(str, Enum):
    PRODUCT_NAME = "PRODUCT_NAME"
    NET_CONTENTS = "NET_CONTENTS"
    INGREDIENTS = "INGREDIENTS"
    PRODUCER_ADDRESS = "PRODUCER_ADDRESS"
    LOT_CODE = "LOT_CODE"
    BEST_BY = "BEST_BY"
    NON_ALCOHOLIC_STATEMENT = "NON_ALCOHOLIC_STATEMENT"
    CONTAINS_LESS_THAN_HALF_PERCENT_ALCOHOL = "CONTAINS_LESS_THAN_HALF_PERCENT_ALCOHOL"
    ALCOHOL_CONTENT_STATEMENT = "ALCOHOL_CONTENT_STATEMENT"
    GOVERNMENT_WARNING = "GOVERNMENT_WARNING"
    AGE_RESTRICTED = "AGE_RESTRICTED"
    PASTEURIZED_STATEMENT = "PASTEURIZED_STATEMENT"
    KEEP_REFRIGERATED = "KEEP_REFRIGERATED"
    LIVE_CULTURES = "LIVE_CULTURES"


# --------------------------------------------------------------------------
# Entity shapes.
#
# Seventeen of the eighteen resource families carry `updated_at` and
# `version`; the QA reading is append-only and carries only `id` and
# `created_at`, so its shape deliberately omits both.
# --------------------------------------------------------------------------
class Recipe(TypedDict):
    id: str
    name: str
    style: str
    recipe_version_number: int
    target_ph_ceiling: float
    planned_f1_days: int
    planned_f2_days: int
    f2_added_sugar_g_per_l: float
    base_gravity_brix: float
    pasteurization_required: bool
    intended_abv_class: str
    active_label_approval_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LabelApproval(TypedDict):
    id: str
    recipe_id: str
    approved_recipe_version_number: Optional[int]
    abv_class: str
    pasteurized: bool
    required_elements: List[str]
    declared_elements: List[str]
    status: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    stale_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScobyCulture(TypedDict):
    id: str
    label: str
    parent_culture_id: Optional[str]
    generation_number: int
    pitch_count: int
    reverification_count: int
    last_reverified_at: Optional[str]
    vitality_score: float
    state: str
    retire_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Vessel(TypedDict):
    id: str
    code: str
    capacity_liters: float
    state: str
    cip_started_at: Optional[str]
    cip_completed_at: Optional[str]
    current_batch_id: Optional[str]
    occupancy_start_at: Optional[str]
    occupancy_end_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IngredientLot(TypedDict):
    id: str
    ingredient_type: str
    supplier_lot_code: str
    received_on_date: str
    expiry_date: str
    quantity_received: float
    quantity_consumed: float
    quantity_available: float
    status: str
    quarantine_cleared_count: int
    pre_quarantine_status: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Batch(TypedDict):
    id: str
    batch_code: str
    recipe_id: str
    recipe_version_number_at_pitch: int
    scoby_culture_id: str
    vessel_id: str
    pitched_liters: float
    remaining_liters: float
    drawn_liters: float
    loss_liters: float
    pitched_at: str
    planned_f2_days: int
    f2_added_sugar_g_per_l: float
    f1_completed_at: Optional[str]
    f2_started_at: Optional[str]
    f2_completed_at: Optional[str]
    f1_measured_abv_pct: Optional[float]
    projected_abv_pct: Optional[float]
    projected_abv_class: Optional[str]
    packaging_abv_pct: Optional[float]
    ferment_stage: str
    qa_disposition: str
    flagged_reading_count: int
    temp_excursion_count: int
    ph_target_hit_day_index: Optional[int]
    qa_signoff_count: int
    last_flagged_reading_by_user_id: Optional[str]
    occupancy_end_at: str
    created_at: str
    updated_at: str
    version: int


class BatchIngredientUse(TypedDict):
    id: str
    batch_id: str
    ingredient_lot_id: str
    quantity_used: float
    voided: bool
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QaReading(TypedDict):
    """Append-only observation: id and created_at only, no updated_at, no version."""

    id: str
    batch_id: str
    reading_type: str
    reading_at: str
    day_index: int
    ph: float
    temperature_c: float
    brix: float
    abv_pct: float
    flagged: bool
    flag_reasons: List[str]
    recorded_by_user_id: str
    created_at: str


class PackagingRun(TypedDict):
    id: str
    run_code: str
    recipe_id: str
    label_approval_id: str
    format: str
    pasteurized: bool
    max_units_requested: int
    source_draws: List[dict]
    source_batch_count: int
    gross_liters: float
    net_liters: float
    units_produced: int
    status: str
    created_by_user_id: str
    started_by_user_id: Optional[str]
    finished_lot_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FinishedLot(TypedDict):
    id: str
    lot_code: str
    packaging_run_id: str
    recipe_id: str
    format: str
    pasteurized: bool
    container_liters: float
    units_produced: int
    on_hand_units: int
    reserved_units: int
    shipped_units: int
    poured_units: int
    destroyed_units: int
    measured_abv_pct: float
    abv_class: str
    packaged_at: str
    best_by_date: str
    cold_chain_max_c: float
    status: str
    pre_quarantine_status: Optional[str]
    quarantine_clearance_count: int
    released_by_user_id: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Keg(TypedDict):
    id: str
    asset_code: str
    capacity_liters: float
    finished_lot_id: Optional[str]
    account_id: Optional[str]
    status: str
    fill_liters: float
    remaining_liters: float
    deposit_state: str
    deposit_amount: float
    deposit_refund_amount: float
    deposit_forfeit_amount: float
    issued_at: Optional[str]
    returned_at: Optional[str]
    tapped_at: Optional[str]
    last_untapped_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    account_name: str
    channel: str
    credit_terms_days: int
    credit_limit: float
    outstanding_balance: float
    keg_deposit_balance: float
    deposit_refunded_total: float
    deposit_forfeited_total: float
    kegs_charged_lifetime: int
    ytd_self_dist_liters: float
    alcoholic_license_on_file: bool
    status: str
    open_recall_notice_count: int
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    account_id: str
    status: str
    total_units: int
    total_liters: float
    subtotal: float
    late_fee: float
    aging_bucket: str
    days_past_due: int
    confirmed_at: Optional[str]
    delivered_on_date: Optional[str]
    due_date: Optional[str]
    paid_at: Optional[str]
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class ShipmentLine(TypedDict):
    id: str
    shipment_id: str
    finished_lot_id: str
    units: int
    unit_price: float
    extended_price: float
    line_liters: float
    line_status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    subscriber_email: str
    subscriber_birth_date: str
    preferred_recipe_id: str
    status: str
    completed_cycles: int
    skips_used_this_year: int
    pause_windows: List[dict]
    current_pause_start_date: Optional[str]
    current_pause_end_date: Optional[str]
    cycle_start_date: str
    cycle_index: int
    next_cycle_charge: float
    credit_balance: float
    age_verified: bool
    created_at: str
    updated_at: str
    version: int


class SubscriptionAllocation(TypedDict):
    id: str
    subscription_id: str
    finished_lot_id: str
    cycle_index: int
    units: int
    status: str
    reversal_reason: Optional[str]
    reallocation_attempt_count: int
    charge_amount: float
    created_at: str
    updated_at: str
    version: int


class TaproomFill(TypedDict):
    id: str
    keg_id: str
    container_type: str
    requested_liters: float
    fill_status: str
    inspected_at: Optional[str]
    inspected_by_user_id: Optional[str]
    customer_birth_date: Optional[str]
    age_verified: bool
    poured_liters: float
    charge_amount: float
    poured_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecallNotice(TypedDict):
    id: str
    account_id: str
    finished_lot_id: str
    trigger_source: str
    status: str
    issued_at: str
    ack_deadline_at: str
    acknowledged_at: Optional[str]
    acknowledged_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
