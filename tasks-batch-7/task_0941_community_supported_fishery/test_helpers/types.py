"""Domain types for the Community-Supported Fishery API: status enums and entity shapes."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CSF_ADMIN = "CsfAdmin"
    MEMBER = "Member"
    VENDOR = "Vendor"
    HUB_OPERATOR = "HubOperator"
    QUALITY_OFFICER = "QualityOfficer"


class Species(str, Enum):
    COD = "COD"
    HADDOCK = "HADDOCK"
    POLLOCK = "POLLOCK"
    HALIBUT = "HALIBUT"
    SALMON = "SALMON"
    TUNA = "TUNA"
    LOBSTER = "LOBSTER"
    SCALLOP = "SCALLOP"
    OYSTER = "OYSTER"


class SpeciesTier(str, Enum):
    WHITEFISH = "WHITEFISH"
    PREMIUM_FINFISH = "PREMIUM_FINFISH"
    SHELLFISH = "SHELLFISH"


class GearType(str, Enum):
    HOOK_AND_LINE = "HOOK_AND_LINE"
    TRAP = "TRAP"
    DIVE = "DIVE"
    GILLNET = "GILLNET"
    TRAWL = "TRAWL"


class SustainabilityBand(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    ORANGE = "ORANGE"
    RED = "RED"


class CustodyLeg(str, Enum):
    DOCK_TO_HUB = "DOCK_TO_HUB"
    HUB_HOLD = "HUB_HOLD"
    HUB_TO_DOOR = "HUB_TO_DOOR"


class BreachType(str, Enum):
    NONE = "NONE"
    SINGLE_EXCURSION = "SINGLE_EXCURSION"
    CUMULATIVE = "CUMULATIVE"
    BOTH = "BOTH"


class DestinationType(str, Enum):
    HUB = "HUB"
    ROUTE = "ROUTE"


class RecallReason(str, Enum):
    PATHOGEN = "PATHOGEN"
    MISLABEL = "MISLABEL"
    COLD_CHAIN = "COLD_CHAIN"
    REGULATORY = "REGULATORY"


class AmbientBand(str, Enum):
    COOL = "COOL"
    MILD = "MILD"
    HOT = "HOT"


class FeeTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class ShareSize(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class PackSize(str, Enum):
    NONE = "NONE"
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class DeliveryFrequency(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"


class FulfillmentMode(str, Enum):
    HUB_PICKUP = "HUB_PICKUP"
    HOME_DELIVERY = "HOME_DELIVERY"


class PaymentBasis(str, Enum):
    PREPAID_FULL_SEASON = "PREPAID_FULL_SEASON"
    INSTALLMENT = "INSTALLMENT"


class SeasonStatus(str, Enum):
    PLANNING = "PLANNING"
    OPEN = "OPEN"
    LANDINGS_CLOSED = "LANDINGS_CLOSED"
    TRUE_UP = "TRUE_UP"
    CLOSED = "CLOSED"


class SubscriptionLifecycleStatus(str, Enum):
    PENDING = "PENDING"
    WAITLISTED = "WAITLISTED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    PAST_DUE = "PAST_DUE"
    TRANSFERRED = "TRANSFERRED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class SubscriptionBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    CURRENT = "CURRENT"
    DUNNING = "DUNNING"
    PREPAID_SETTLED = "PREPAID_SETTLED"
    REFUND_PENDING = "REFUND_PENDING"
    SETTLED = "SETTLED"


class TrueUpStatus(str, Enum):
    NOT_DUE = "NOT_DUE"
    SHORTFALL_FLAGGED = "SHORTFALL_FLAGGED"
    REFUNDED = "REFUNDED"
    CREDITED = "CREDITED"


class MemberStanding(str, Enum):
    GOOD = "GOOD"
    WARNED = "WARNED"
    RESTRICTED = "RESTRICTED"


class VesselComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class QuotaLedgerStatus(str, Enum):
    OPEN = "OPEN"
    WARNING = "WARNING"
    EXHAUSTED = "EXHAUSTED"
    SUSPENDED = "SUSPENDED"


class TripStatus(str, Enum):
    PLANNED = "PLANNED"
    LANDED = "LANDED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class LandingLotStatus(str, Enum):
    RECORDED = "RECORDED"
    ALLOCATED = "ALLOCATED"
    SPLIT = "SPLIT"
    DISPATCHED = "DISPATCHED"
    CLOSED = "CLOSED"
    RECALLED = "RECALLED"


class QualityStatus(str, Enum):
    CLEAR = "CLEAR"
    HOLD = "HOLD"
    RELEASED = "RELEASED"
    DISCOUNTED = "DISCOUNTED"
    DISCARDED = "DISCARDED"


class AllocationVariant(str, Enum):
    NONE = "NONE"
    NORMAL_FILL = "NORMAL_FILL"
    SHORT_FILL = "SHORT_FILL"


class SubLotStatus(str, Enum):
    IN_TRANSIT = "IN_TRANSIT"
    ARRIVED = "ARRIVED"
    CONSUMED = "CONSUMED"
    RETURNED = "RETURNED"
    DESTROYED = "DESTROYED"


class PickupWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    GRACE = "GRACE"
    CLOSED = "CLOSED"
    RECONCILED = "RECONCILED"


class FulfillmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SKIPPED = "SKIPPED"
    ALLOCATED = "ALLOCATED"
    PACKED = "PACKED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    AT_HUB = "AT_HUB"
    PICKED_UP = "PICKED_UP"
    NO_SHOW = "NO_SHOW"
    DONATED = "DONATED"
    VOIDED = "VOIDED"


class FillStatus(str, Enum):
    PENDING = "PENDING"
    FULL_FILL = "FULL_FILL"
    UNDER_FILLED = "UNDER_FILLED"
    SUBSTITUTED = "SUBSTITUTED"
    VOID = "VOID"


class DeliveryBillingStatus(str, Enum):
    PENDING = "PENDING"
    CHARGED = "CHARGED"
    PARTIALLY_CREDITED = "PARTIALLY_CREDITED"
    CREDITED = "CREDITED"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


class SubstitutionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CREDIT_ISSUED = "CREDIT_ISSUED"


class SubstitutionSettlementVariant(str, Enum):
    EQUAL_OR_GREATER = "EQUAL_OR_GREATER"
    BELOW_VALUE = "BELOW_VALUE"


class SkipStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CREDITED = "CREDITED"
    FORFEITED = "FORFEITED"
    REVOKED = "REVOKED"


class SkipSettlementVariant(str, Enum):
    CREDIT = "CREDIT"
    FORFEIT = "FORFEIT"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    PROVISIONAL = "PROVISIONAL"
    HELD = "HELD"
    FINAL = "FINAL"
    PAID = "PAID"
    VOID = "VOID"


class SettlementVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class TransferStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class TransferSettlementVariant(str, Enum):
    PREPAID = "PREPAID"
    INSTALLMENT = "INSTALLMENT"


class RecallStatus(str, Enum):
    INITIATED = "INITIATED"
    SCOPED = "SCOPED"
    REMEDIATED = "REMEDIATED"
    CLOSED = "CLOSED"


# ─── Entity shapes ────────────────────────────────────────────────────────────
# Every entity below carries id, created_at, updated_at and version, with the one
# exception of ColdChainEvent, which is an append-only observation carrying only
# id and created_at.


class Season(TypedDict):
    id: str
    season_code: str
    start_date: str
    end_date: str
    total_weeks: int
    ambient_band: str
    offered_species: List[str]
    landing_commit_lead_hours: int
    status: str
    shortfall_flag_count: int
    true_up_run_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SharePlan(TypedDict):
    id: str
    season_id: str
    plan_code: str
    share_size: str
    delivery_frequency: str
    species_tier: str
    price_per_delivery_cents: int
    weight_units: int
    target_pounds_per_delivery: float
    min_floor_pounds: float
    scheduled_delivery_count: int
    created_at: str
    updated_at: str
    version: int


class DeliveryZone(TypedDict):
    id: str
    zone_code: str
    fee_tier: str
    transit_hours: float
    is_serviceable: bool
    created_at: str
    updated_at: str
    version: int


class PickupHub(TypedDict):
    id: str
    hub_code: str
    cooler_slots_default: int
    grace_minutes: int
    created_at: str
    updated_at: str
    version: int


class PickupWindow(TypedDict):
    id: str
    pickup_hub_id: str
    season_id: str
    week_index: int
    opens_at: str
    closes_at: str
    cooler_slots_total: int
    grace_minutes: int
    slots_free: int
    slots_reserved: int
    slots_occupied: int
    slots_forfeited: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    full_name: str
    email: str
    allergy_exclusions: List[str]
    dislikes: List[str]
    never_substitute: bool
    standing: str
    season_no_show_count: int
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    member_id: str
    share_plan_id: str
    season_id: str
    pickup_hub_id: Optional[str]
    delivery_zone_id: Optional[str]
    renewed_from_subscription_id: Optional[str]
    fulfillment_mode: str
    payment_basis: str
    join_week_index: int
    lifecycle_status: str
    billing_status: str
    commitment_cents: int
    price_per_delivery_cents: int
    promised_delivery_count: int
    delivered_count: int
    credited_count: int
    skip_credited_count: int
    undelivered_count: int
    member_fault_count: int
    skip_count: int
    skip_credit_balance_cents: int
    paid_cents: int
    rollover_credit_cents: int
    expired_credit_cents: int
    true_up_status: str
    true_up_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Vessel(TypedDict):
    id: str
    vessel_name: str
    permit_number: str
    home_port: str
    gear_types: List[str]
    compliance_status: str
    violation_count: int
    created_at: str
    updated_at: str
    version: int


class QuotaLedger(TypedDict):
    id: str
    vessel_id: str
    season_id: str
    species: str
    management_area: str
    entitlement_pounds: float
    committed_pounds: float
    remaining_pounds: float
    area_closed: bool
    species_open_date: str
    species_close_date: str
    permitted_gears: List[str]
    area_sensitivity_penalty: int
    species_stock_adjustment: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Trip(TypedDict):
    id: str
    vessel_id: str
    season_id: str
    quota_ledger_id: str
    gear_type: str
    management_area: str
    landed_at: Optional[str]
    offload_minutes: int
    sustainability_score: int
    sustainability_band: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LandingLot(TypedDict):
    id: str
    trip_id: str
    species: str
    landed_pounds_gross: float
    landed_pounds_net: float
    discarded_over_quota_pounds: float
    ex_vessel_price_cents_per_lb: int
    retail_value_cents_per_lb: int
    allocation_week_index: Optional[int]
    allocated_pounds_total: float
    surplus_secondary_pounds: float
    surplus_donated_pounds: float
    split_pounds_total: float
    cold_chain_cumulative_minutes: int
    cold_chain_max_single_minutes: int
    peak_temp_c: float
    allocation_variant: str
    status: str
    quality_status: str
    created_at: str
    updated_at: str
    version: int


class SubLot(TypedDict):
    id: str
    landing_lot_id: str
    pickup_hub_id: Optional[str]
    delivery_zone_id: Optional[str]
    destination_type: str
    pounds: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ShareDelivery(TypedDict):
    id: str
    subscription_id: str
    season_id: str
    landing_lot_id: Optional[str]
    sub_lot_id: Optional[str]
    pickup_window_id: Optional[str]
    week_index: int
    scheduled_at: str
    allocated_pounds: float
    substituted_pounds: float
    box_pounds: float
    pack_size: str
    gel_pack_count: int
    subtotal_cents: int
    surcharge_cents: int
    delivery_fee_cents: int
    invoice_total_cents: int
    charged_cents: int
    credit_cents: int
    fill_status: str
    fulfillment_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class SubstitutionEvent(TypedDict):
    id: str
    share_delivery_id: str
    substitute_landing_lot_id: str
    substitute_species: str
    substitute_pounds: float
    shortfall_pounds: float
    owed_value_cents: int
    substitute_value_cents: int
    settlement_variant: str
    member_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ColdChainEvent(TypedDict):
    """Append-only observation: carries id and created_at, and neither updated_at nor version."""

    id: str
    landing_lot_id: str
    sub_lot_id: Optional[str]
    custody_leg: str
    minutes_above_threshold: int
    peak_temp_c: float
    breach_type: str
    recorded_at: str
    recorded_by_user_id: str
    created_at: str


class SkipRequest(TypedDict):
    id: str
    subscription_id: str
    share_delivery_id: str
    requested_at: str
    cutoff_at: str
    settlement_variant: str
    credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SettlementStatement(TypedDict):
    id: str
    trip_id: str
    landing_lot_id: str
    vessel_id: str
    ex_vessel_cents: int
    premium_cents: int
    gross_cents: int
    dock_fee_cents: int
    ice_handling_cents: int
    offload_labor_cents: int
    handling_levy_cents: int
    deductions_cents: int
    holdback_cents: int
    holdback_released_cents: int
    holdback_forfeited_cents: int
    offset_cents: int
    net_payable_cents: int
    net_paid_cents: int
    variant: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ShareTransfer(TypedDict):
    id: str
    from_subscription_id: str
    to_subscription_id: str
    season_id: str
    effective_week_index: int
    remaining_delivery_count: int
    transfer_fee_cents: int
    transferee_charge_cents: int
    transferor_refund_cents: int
    settlement_variant: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RecallNotice(TypedDict):
    id: str
    landing_lot_id: str
    season_id: str
    reason: str
    impacted_sub_lot_count: int
    impacted_delivery_count: int
    impacted_member_count: int
    total_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
