"""Domain types for the Custom Grazing & Pasture Rental API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    GRAZIER = "Grazier"
    CATTLE_OWNER = "CattleOwner"
    RANGE_CONSULTANT = "RangeConsultant"
    PLATFORM_ADMIN = "PlatformAdmin"


class CreditStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    DELINQUENT = "DELINQUENT"


class PastureOperationalStatus(str, Enum):
    DRAFT = "DRAFT"
    AVAILABLE = "AVAILABLE"
    CLOSED = "CLOSED"


class GrazingPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    DESTOCK_ORDERED = "DESTOCK_ORDERED"
    CLOSED = "CLOSED"


class ForageType(str, Enum):
    NATIVE_RANGE = "NATIVE_RANGE"
    IMPROVED_PASTURE = "IMPROVED_PASTURE"
    COOL_SEASON_MIX = "COOL_SEASON_MIX"
    WARM_SEASON_MIX = "WARM_SEASON_MIX"


class WaterSourceType(str, Enum):
    WELL = "WELL"
    CREEK = "CREEK"
    PIPELINE = "PIPELINE"
    POND = "POND"


class FenceClass(str, Enum):
    CLASS_A = "CLASS_A"
    CLASS_B = "CLASS_B"
    CLASS_C = "CLASS_C"


class CapacityMethod(str, Enum):
    DRY_MATTER = "DRY_MATTER"
    STOCKING_HISTORY = "STOCKING_HISTORY"


class BillingMode(str, Enum):
    PER_HEAD_PER_DAY = "PER_HEAD_PER_DAY"
    PER_POUND_OF_GAIN = "PER_POUND_OF_GAIN"


class ResponsibilityParty(str, Enum):
    GRAZIER = "GRAZIER"
    OWNER = "OWNER"
    SHARED = "SHARED"


class DeathLossTerms(str, Enum):
    OWNER_BEARS_ALL = "OWNER_BEARS_ALL"
    GRAZIER_SHARE_ABOVE_THRESHOLD = "GRAZIER_SHARE_ABOVE_THRESHOLD"


class ContractLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_SIGNATURE = "PENDING_SIGNATURE"
    SUSPENDED = "SUSPENDED"
    ACTIVE = "ACTIVE"
    EARLY_REMOVAL_PENDING = "EARLY_REMOVAL_PENDING"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class ContractBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    SETTLEMENT_ISSUED = "SETTLEMENT_ISSUED"
    SETTLED = "SETTLED"


class EarlyRemovalReason(str, Enum):
    DROUGHT = "DROUGHT"
    OWNER_ELECTED = "OWNER_ELECTED"
    GRAZIER_ELECTED = "GRAZIER_ELECTED"


class LotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RECEIVING_HELD = "RECEIVING_HELD"
    ON_FEED = "ON_FEED"
    REMOVAL_SCHEDULED = "REMOVAL_SCHEDULED"
    WEIGHED_OUT = "WEIGHED_OUT"
    CLOSED = "CLOSED"


class WeightEventType(str, Enum):
    IN = "IN"
    INTERIM = "INTERIM"
    OUT = "OUT"


class TreatmentClassification(str, Enum):
    ROUTINE_PROTOCOL = "ROUTINE_PROTOCOL"
    THERAPEUTIC = "THERAPEUTIC"
    PREVENTIVE_EMERGENCY = "PREVENTIVE_EMERGENCY"


class TreatmentStatus(str, Enum):
    RECORDED = "RECORDED"
    APPROVED = "APPROVED"
    DISPUTED = "DISPUTED"
    VOIDED = "VOIDED"


class DeathCause(str, Enum):
    DISEASE = "DISEASE"
    PREDATOR = "PREDATOR"
    WEATHER = "WEATHER"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"
    UNKNOWN = "UNKNOWN"


class DeathLossStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class AssetType(str, Enum):
    WATER = "WATER"
    FENCE = "FENCE"


class TicketSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class TicketCause(str, Enum):
    WEAR = "WEAR"
    STORM = "STORM"
    LIVESTOCK_DAMAGE = "LIVESTOCK_DAMAGE"
    NEGLECT = "NEGLECT"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED_GRAZIER = "ASSIGNED_GRAZIER"
    ASSIGNED_OWNER = "ASSIGNED_OWNER"
    REPAIRED = "REPAIRED"
    BILLED = "BILLED"


class GainMethod(str, Enum):
    PROVISIONAL_PRORATED = "PROVISIONAL_PRORATED"
    FINAL_ADJUDICATED = "FINAL_ADJUDICATED"
    SPLIT_MIDPOINT = "SPLIT_MIDPOINT"


class DisputedField(str, Enum):
    SHRUNK_GAIN_LBS = "SHRUNK_GAIN_LBS"
    TREATMENT_CHARGE = "TREATMENT_CHARGE"
    DEATH_LOSS_CREDIT = "DEATH_LOSS_CREDIT"


class DisputeResolution(str, Enum):
    UPHELD_GRAZIER = "UPHELD_GRAZIER"
    UPHELD_OWNER = "UPHELD_OWNER"
    SPLIT_MIDPOINT = "SPLIT_MIDPOINT"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    ADJUDICATED = "ADJUDICATED"
    FINAL = "FINAL"
    VOID = "VOID"


# --------------------------------------------------------------------------
# Living resources — id + created_at + updated_at + version
# --------------------------------------------------------------------------


class Grazier(TypedDict):
    id: str
    business_name: str
    state_code: str
    liability_carrier: str
    created_at: str
    updated_at: str
    version: int


class CattleOwner(TypedDict):
    id: str
    legal_name: str
    state_code: str
    brand_registration: str
    credit_limit_cents: int
    open_settlement_balance_cents: int
    credit_status: str
    created_at: str
    updated_at: str
    version: int


class RangeConsultant(TypedDict):
    id: str
    full_name: str
    certification_number: str
    state_code: str
    created_at: str
    updated_at: str
    version: int


class Pasture(TypedDict):
    id: str
    grazier_id: str
    name: str
    acres: float
    forage_type: str
    water_source_type: str
    fence_class: str
    prior_season_head_days: int
    operational_status: str
    effective_assessment_id: Optional[str]
    rated_aum: float
    rated_head_days: int
    committed_head_days: int
    capacity_utilization_pct: float
    stocked_head_count: int
    drought_destock_flag: bool
    open_critical_ticket_count: int
    grazing_posture: str
    created_at: str
    updated_at: str
    version: int


class GrazingContract(TypedDict):
    id: str
    grazier_id: str
    cattle_owner_id: str
    pasture_id: str
    billing_mode: str
    rate_cents: int
    shrink_pct: float
    out_shrink_pct: float
    head_count_committed: int
    head_value_cents: int
    start_date: str
    end_date: str
    min_days: int
    treatment_cost_split_pct: int
    water_responsibility: str
    fence_responsibility: str
    infrastructure_owner_cap_cents: int
    death_loss_terms: str
    death_loss_threshold_pct: float
    signature_ref: Optional[str]
    committed_head_days: int
    lifecycle_status: str
    billing_status: str
    early_removal_reason: Optional[str]
    early_removal_effective_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CattleLot(TypedDict):
    id: str
    contract_id: str
    scheduled_head_count: int
    scheduled_delivery_date: str
    head_count_received: int
    gross_weight_in_lbs: float
    shrunk_weight_in_lbs: float
    in_date: Optional[str]
    head_count_out: int
    gross_weight_out_lbs: float
    shrunk_weight_out_lbs: float
    out_date: Optional[str]
    confirmed_death_head: int
    days_on_feed: int
    scheduled_removal_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HealthTreatment(TypedDict):
    id: str
    lot_id: str
    protocol_code: str
    classification: str
    treatment_date: str
    withdrawal_days: int
    head_treated: int
    drug_cost_cents: int
    labor_cost_cents: int
    total_cost_cents: int
    owner_share_cents: int
    grazier_share_cents: int
    review_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeathLossReport(TypedDict):
    id: str
    lot_id: str
    death_date: str
    head_lost: int
    cause: str
    necropsy_performed: bool
    owner_liable_head: int
    grazier_liable_head: int
    credit_cents: int
    review_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InfrastructureTicket(TypedDict):
    id: str
    pasture_id: str
    contract_id: str
    asset_type: str
    severity: str
    description: str
    reported_at: str
    cause: Optional[str]
    repair_party: Optional[str]
    repair_cost_cents: int
    repair_completed_at: Optional[str]
    responsible_party: Optional[str]
    owner_share_cents: int
    grazier_share_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    contract_id: str
    lot_id: str
    adjudicator_id: Optional[str]
    gain_method: str
    days_on_feed: int
    billable_head_days: int
    adjusted_in_weight_lbs: float
    shrunk_gain_lbs: float
    average_daily_gain: float
    base_charge_cents: int
    treatment_charge_cents: int
    infrastructure_charge_cents: int
    death_loss_credit_cents: int
    subtotal_cents: int
    early_removal_adjustment_cents: int
    volume_rebate_cents: int
    total_due_cents: int
    dispute_round: int
    disputed_field: Optional[str]
    claimed_shrunk_gain_lbs: Optional[float]
    resolution: Optional[str]
    dispute_note: Optional[str]
    adjudication_note: Optional[str]
    void_reason: Optional[str]
    issued_at: Optional[str]
    dispute_opened_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only ledger rows — id + created_at ONLY (no updated_at, no version)
# --------------------------------------------------------------------------


class CapacityAssessment(TypedDict):
    id: str
    pasture_id: str
    assessor_id: str
    method: str
    forage_dry_matter_lbs_per_acre: float
    utilization_pct: float
    assessment_date: str
    rated_aum: float
    rated_head_days: int
    created_at: str


class DroughtReading(TypedDict):
    id: str
    pasture_id: str
    reading_date: str
    drought_index: int
    forage_remaining_pct: float
    consecutive_severe_count: int
    triggered_destock: bool
    created_at: str


class WeightEvent(TypedDict):
    id: str
    lot_id: str
    event_type: str
    gross_weight_lbs: float
    head_count: int
    scale_ticket_ref: str
    weighed_at: str
    shrink_pct_applied: float
    shrunk_weight_lbs: float
    created_at: str


APPEND_ONLY_ENTITIES: List[str] = [
    "CapacityAssessment",
    "DroughtReading",
    "WeightEvent",
]
