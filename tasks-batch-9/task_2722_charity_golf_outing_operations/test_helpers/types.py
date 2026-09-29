"""Typed shapes and enum-like string sets for the Charity Golf Outing API."""

from typing import Any, Dict, List, Optional, TypedDict

# ---------------------------------------------------------------- enums ---

# Outing (PRD 3.1)
OUTING_FORMATS = ["SCRAMBLE", "BEST_BALL", "STROKE_PLAY"]
START_FORMATS = ["SHOTGUN", "WAVE_SPLIT", "TEE_TIME"]
PLAY_STATUSES = ["DRAFT", "OPEN", "FIELD_LOCKED", "IN_PLAY", "SCORED", "POSTPONED", "CANCELLED"]
FINANCE_STATUSES = ["COLLECTING", "RECONCILED", "DISBURSED"]
PLAY_ACTIONS = [
    "OPEN_REGISTRATION",
    "LOCK_FIELD",
    "START_PLAY",
    "FINALIZE_SCORING",
    "POSTPONE",
    "RESUME",
    "CANCEL_OUTING",
]
FINANCE_ACTIONS = ["RECONCILE", "REOPEN", "REMIT"]
PROCEEDS_VARIANTS = ["PROVISIONAL", "FINAL"]

# CourseContract (PRD 3.1)
CONTRACT_STATUSES = ["DRAFT", "SIGNED", "AMENDED", "VOIDED", "SETTLED"]
CONTRACT_ACTIONS = ["SIGN", "AMEND", "VOID"]
RAIN_DATE_TERMS = ["NONE", "FULL_CREDIT", "PARTIAL_CREDIT"]

# PackageTier (PRD 3.2)
TIER_KINDS = ["TEAM", "INDIVIDUAL", "SPONSOR"]
ENTITLED_ASSET_TYPES = ["HOLE_SIGN", "CONTEST", "CART", "BEVERAGE_STATION", "NONE"]

# Registration (PRD 3.2)
REGISTRATION_STATUSES = [
    "PENDING_PAYMENT",
    "CONFIRMED",
    "AMENDED",
    "CHECKED_IN",
    "WAITLISTED",
    "CANCELLED",
    "REFUNDED",
]
REGISTRATION_ACTIONS = ["CHECK_IN", "RECONFIRM", "CANCEL"]
REVENUE_RECOGNIZED_REGISTRATION_STATUSES = ["CONFIRMED", "AMENDED", "CHECKED_IN"]

# Player (PRD 3.3)
AMATEUR_STATUSES = ["AMATEUR", "PROFESSIONAL"]

# Team (PRD 3.3, 3.5)
WAVES = ["A", "B"]
HANDICAP_VARIANTS = ["PROVISIONAL", "LOCKED"]

# SponsorshipAsset (PRD 3.4)
ASSET_TYPES = ["HOLE_SIGN", "CONTEST", "CART", "BEVERAGE_STATION"]
ASSET_POSTURES = ["AVAILABLE", "RESERVED", "COMMITTED", "FULFILLED", "WITHDRAWN"]
INVENTORY_ACTIONS = ["WITHDRAW", "RESTORE"]

# SponsorAllocation (PRD 3.4)
ALLOCATION_SOURCES = ["PACKAGE_ENTITLEMENT", "UPSELL"]
ALLOCATION_STATUSES = [
    "RESERVED",
    "COMMITTED",
    "ARTWORK_APPROVED",
    "INSTALLED",
    "VERIFIED",
    "WAIVED",
    "RELEASED",
]
FULFILLMENT_ACTIONS = ["COMMIT", "APPROVE_ARTWORK", "INSTALL", "VERIFY", "WAIVE", "RELEASE"]
ALLOCATION_RESERVED_STATUSES = ["RESERVED"]
ALLOCATION_COMMITTED_STATUSES = ["COMMITTED", "ARTWORK_APPROVED", "INSTALLED"]
ALLOCATION_FULFILLED_STATUSES = ["VERIFIED", "WAIVED"]

# Contest (PRD 3.6)
CONTEST_TYPES = ["HOLE_IN_ONE", "LONGEST_DRIVE", "CLOSEST_TO_PIN", "PUTTING"]
CONTEST_STATUSES = ["PLANNED", "OPEN", "CLOSED", "AWARDED", "VOID"]
CONTEST_ACTIONS = ["OPEN", "CLOSE", "VOID"]
INSURANCE_STATUSES = ["NONE", "BOUND", "CLAIM_PAID", "CLAIM_DENIED", "EXPIRED"]
PRIZE_FORMS = ["CASH", "MERCHANDISE_CREDIT"]
AWARD_FORMS = ["CASH", "MERCHANDISE_CREDIT"]
CLAIM_DENIAL_REASONS = [
    "NONE",
    "YARDAGE_BELOW_MINIMUM",
    "INSUFFICIENT_WITNESSES",
    "COVERAGE_CAP_EXCEEDED",
    "NO_POLICY",
]

# FundraisingItem (PRD 3.7)
ITEM_TYPES = ["AUCTION", "RAFFLE", "DONATION"]
ITEM_STATUSES = ["LISTED", "SOLD", "PAID", "RECEIPTED", "VOID"]
ITEM_ACTIONS = ["VOID", "RELIST"]

# CharitableReceipt (PRD 3.7)
RECEIPT_KINDS = ["REGISTRATION", "FUNDRAISING_ITEM", "REVERSAL"]

# --------------------------------------------------------- entity shapes ---

# Ten of the eleven families carry id / created_at / updated_at / version.
COMMON_FIELDS = ["id", "created_at", "updated_at", "version"]
# CharitableReceipt is append-only: it carries only id and created_at (PRD 2.4).
RECEIPT_COMMON_FIELDS = ["id", "created_at"]


class Outing(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    beneficiary_name: str
    format: str
    start_format: str
    scheduled_date: str
    rain_date: Optional[str]
    postponed_from_date: Optional[str]
    wave_a_start: str
    wave_a_end: str
    wave_b_start: Optional[str]
    wave_b_end: Optional[str]
    field_capacity_teams: int
    prize_pool_cents: int
    play_status: str
    finance_status: str
    proceeds_variant: str
    reopen_count: int
    confirmed_player_slots: int
    checked_in_player_count: int
    waitlisted_registration_count: int
    reserved_asset_slot_count: int
    gross_revenue_cents: int
    refunded_cents: int
    course_charge_cents: int
    fnb_shortfall_cents: int
    insurance_cost_cents: int
    prize_cost_cents: int
    fulfillment_credit_cents: int
    direct_costs_cents: int
    net_proceeds_before_fee_cents: int
    admin_fee_pct: float
    admin_fee_cents: int
    net_proceeds_cents: int
    unclaimed_prize_cents: int
    receipted_deductible_total_cents: int
    beneficiary_remittance_cents: int
    remittance_reference: Optional[str]


class CourseContract(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    outing_id: str
    course_name: str
    rate_per_player_cents: int
    guaranteed_player_count: int
    fnb_minimum_cents: int
    fnb_per_player_cents: int
    course_rating: float
    slope_rating: float
    par: int
    tee_interval_minutes: int
    cart_allowance_count: int
    rain_date_terms: str
    rain_date_credit_pct: float
    cancellation_notice_days: int
    status: str
    signed_at: Optional[str]
    amendment_count: int
    rain_credit_cents: int
    settled_charge_cents: int
    void_reason: Optional[str]


class PackageTier(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    outing_id: str
    code: str
    kind: str
    price_cents: int
    player_slots: int
    gsv_cents: int
    inventory_cap: int
    entitled_asset_type: str
    entitled_asset_count: int
    sold_count: int


class Registration(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    outing_id: str
    package_tier_id: str
    buyer_name: str
    buyer_email: Optional[str]
    player_count: int
    status: str
    amount_paid_cents: int
    amount_refunded_cents: int
    late_cancel_fee_cents: int
    fulfillment_credit_cents: int
    entitled_asset_balance: int
    amendment_count: int
    confirmed_at: Optional[str]
    receipt_issued: bool
    recorded_by_user_id: str


class Player(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    registration_id: str
    full_name: str
    handicap_index: float
    amateur_status: str
    team_id: Optional[str]
    checked_in: bool
    handicap_index_at_confirm: Optional[float]
    effective_handicap_index: Optional[float]
    course_handicap: Optional[int]


class Team(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    outing_id: str
    team_name: str
    player_count: int
    team_playing_handicap: Optional[float]
    handicap_variant: str
    wave: Optional[str]
    starting_hole: Optional[int]
    tee_time: Optional[str]
    cart_number: Optional[int]
    slot_occupancy_start: Optional[str]
    slot_occupancy_end: Optional[str]
    tee_assignment_count: int
    gross_score: Optional[int]
    gross_back_9: Optional[int]
    gross_back_6: Optional[int]
    gross_back_3: Optional[int]
    gross_hole_18: Optional[int]
    net_score: Optional[float]
    net_back_9: Optional[float]
    net_back_6: Optional[float]
    net_back_3: Optional[float]
    net_hole_18: Optional[float]
    rank_position: Optional[int]
    prize_eligible: bool
    prize_award_cents: int
    score_posted_at: Optional[str]


class SponsorshipAsset(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    outing_id: str
    asset_type: str
    label: str
    hole_number: Optional[int]
    capacity: int
    exclusive: bool
    list_price_cents: int
    fulfillment_due_at: Optional[str]
    reserved_count: int
    committed_count: int
    fulfilled_count: int
    remaining_capacity: int
    status: str


class SponsorAllocation(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    registration_id: str
    sponsorship_asset_id: str
    source: str
    status: str
    service_window_start: Optional[str]
    service_window_end: Optional[str]
    upsell_price_cents: int
    fulfillment_credit_cents: int
    waived_reason: Optional[str]
    artwork_approved_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    committed_at: Optional[str]


class Contest(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    outing_id: str
    contest_type: str
    hole_number: int
    prize_value_cents: int
    yardage: Optional[int]
    prize_form: str
    status: str
    insurance_status: str
    requires_insurance: bool
    insurance_carrier: Optional[str]
    insurance_premium_cents: int
    insurance_coverage_cap_cents: int
    insurance_min_yardage: int
    insurance_required_witness_count: int
    insurance_bound_at: Optional[str]
    winner_player_id: Optional[str]
    witness_count: int
    award_form: Optional[str]
    awarded_value_cents: int
    insurance_recovery_cents: int
    contest_payout_cents: int
    claim_denial_reason: str


class FundraisingItem(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    outing_id: str
    item_type: str
    description: str
    fmv_cents: int
    ask_cents: int
    status: str
    buyer_registration_id: Optional[str]
    bid_cents: int
    collected_cents: int
    recorded_by_user_id: Optional[str]
    sold_at: Optional[str]
    void_count: int


class CharitableReceipt(TypedDict, total=False):
    id: str
    created_at: str
    outing_id: str
    receipt_kind: str
    registration_id: Optional[str]
    fundraising_item_id: Optional[str]
    reverses_receipt_id: Optional[str]
    receipt_number: str
    payment_cents: int
    gsv_cents: int
    deductible_amount_cents: int
    issued_by_user_id: str
    issued_at: str
    reversal_reason: Optional[str]


Json = Dict[str, Any]
JsonList = List[Json]
