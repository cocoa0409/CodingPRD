"""Domain types: status enums, role enum and entity TypedDicts from the PRD."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    GROWER_RELATIONS_MANAGER = "GrowerRelationsManager"
    GROWER = "Grower"
    HARVEST_COORDINATOR = "HarvestCoordinator"
    SCALE_OPERATOR = "ScaleOperator"
    QUALITY_LAB_TECH = "QualityLabTech"
    ACCOUNTS_PAYABLE_CLERK = "AccountsPayableClerk"


class GrowerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BlockStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ContractBasis(str, Enum):
    TONNAGE = "TONNAGE"
    ACREAGE = "ACREAGE"
    BLOCK = "BLOCK"


class OverDeliveryPolicy(str, Enum):
    ACCEPT_AT_CONTRACT = "ACCEPT_AT_CONTRACT"
    ACCEPT_AT_SPOT = "ACCEPT_AT_SPOT"
    REJECT = "REJECT"


class SettlementBasis(str, Enum):
    LOAD_BY_LOAD = "LOAD_BY_LOAD"
    WEIGHTED_BLEND = "WEIGHTED_BLEND"


class CapScope(str, Enum):
    PER_CONTRACT = "PER_CONTRACT"
    PER_BLOCK = "PER_BLOCK"


class ContractLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"
    TERMINATION_PENDING = "TERMINATION_PENDING"
    TERMINATED = "TERMINATED"
    WITHDRAWN = "WITHDRAWN"


class ContractRenewalStatus(str, Enum):
    NOT_DUE = "NOT_DUE"
    RENEWAL_WINDOW_OPEN = "RENEWAL_WINDOW_OPEN"
    RENEWED = "RENEWED"
    EVERGREEN_ROLLED = "EVERGREEN_ROLLED"
    NOT_RENEWING = "NOT_RENEWING"


class TonnageStatus(str, Enum):
    OPEN = "OPEN"
    CAP_REACHED = "CAP_REACHED"
    HARD_CAP_REACHED = "HARD_CAP_REACHED"


class LaneStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class SamplingVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MaturityFlag(str, Enum):
    PICK_READY = "PICK_READY"
    IMMATURE = "IMMATURE"


class PickCallStatus(str, Enum):
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    SUSPENDED_CAP = "SUSPENDED_CAP"
    FULFILLED = "FULFILLED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ARRIVED = "ARRIVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class WeighStatus(str, Enum):
    GROSS_CAPTURED = "GROSS_CAPTURED"
    NET_FINAL = "NET_FINAL"


class Disposition(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_ACCEPTED = "PARTIALLY_ACCEPTED"
    REJECTED_QUALITY = "REJECTED_QUALITY"
    REJECTED_OVER_CAP = "REJECTED_OVER_CAP"
    DISPUTED = "DISPUTED"


class RecommendedDisposition(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT_QUALITY = "REJECT_QUALITY"


class SettlementLineBucket(str, Enum):
    CONTRACT = "CONTRACT"
    OVER_DELIVERY = "OVER_DELIVERY"


class SettlementLineStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    VOID = "VOID"


class InstallmentStatus(str, Enum):
    PENDING_SETTLEMENT = "PENDING_SETTLEMENT"
    SCHEDULED = "SCHEDULED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DELINQUENT = "DELINQUENT"


# --- Entity shapes -------------------------------------------------------------
# Every entity below carries id + created_at + updated_at + version, except the
# grading row, which is append-only and carries id + created_at only.


class Grower(TypedDict):
    id: str
    name: str
    license_number: str
    region_code: str
    status: str
    rejected_load_count_vintage: int
    expired_pick_call_count_vintage: int
    no_show_appointment_count_vintage: int
    prior_vintage_penalty_units: int
    reliability_score_vintage: float
    reliability_score_lifetime: float
    outstanding_lien_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class VineyardBlock(TypedDict):
    id: str
    grower_id: str
    block_code: str
    varietal: str
    acres: float
    expected_yield_tons_per_acre: float
    ava_code: str
    status: str
    latest_sampling_brix: Optional[float]
    latest_sampling_rot_pct: Optional[float]
    delivered_net_tons_vintage: float
    created_at: str
    updated_at: str
    version: int


class QualitySpec(TypedDict):
    id: str
    spec_code: str
    min_brix_pick_call: float
    min_brix_accept: float
    brix_bonus_start: float
    brix_penalty_start: float
    brix_step: float
    brix_bonus_pct_per_step: float
    brix_penalty_pct_per_step: float
    ta_min_gl: float
    ta_max_gl: float
    acid_out_of_spec_penalty_pct: float
    rot_free_pct: float
    rot_penalty_pct_per_point: float
    rot_rejection_pct: float
    mog_max_pct: float
    mog_penalty_pct: float
    max_total_bonus_pct: float
    max_total_penalty_pct: float
    created_at: str
    updated_at: str
    version: int


class GrapeContract(TypedDict):
    id: str
    grower_id: str
    quality_spec_id: str
    contract_code: str
    contract_basis: str
    committed_tons: Optional[float]
    contracted_yield_tons_per_acre: Optional[float]
    base_price_per_ton_cents: int
    countered_price_per_ton_cents: Optional[int]
    over_delivery_policy: str
    spot_price_pct: float
    over_delivery_tolerance_pct: float
    settlement_basis: str
    provisional_payment_pct: float
    lien_holdback_pct: float
    min_pick_notice_hours: int
    pick_call_ack_window_hours: int
    term_start_vintage: int
    term_end_vintage: int
    evergreen_flag: bool
    evergreen_term_years: int
    termination_notice_days: int
    installment_plan: List[dict]
    lifecycle_status: str
    renewal_status: str
    tonnage_status: str
    offer_round: int
    cap_scope: Optional[str]
    contract_cap_tons: Optional[float]
    hard_cap_tons: Optional[float]
    delivered_contract_tons: float
    delivered_over_tons: float
    rejected_tons: float
    provisional_settlement_cents: int
    final_settlement_cents: int
    prompt_pay_credit_cents: int
    lien_holdback_cents: int
    net_payable_cents: int
    settlement_closed_at: Optional[str]
    renewal_window_opens_at: Optional[str]
    renewal_window_closes_at: Optional[str]
    termination_effective_at: Optional[str]
    lien_released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContractBlockAllocation(TypedDict):
    id: str
    contract_id: str
    block_id: str
    allocated_acres: Optional[float]
    block_cap_tons: Optional[float]
    block_hard_cap_tons: Optional[float]
    delivered_net_tons: float
    created_at: str
    updated_at: str
    version: int


class CrushPadLane(TypedDict):
    id: str
    lane_code: str
    daily_capacity_tons: float
    turnaround_buffer_minutes: int
    max_load_tons: float
    status: str
    committed_tons: float
    scheduled_appointment_count: int
    created_at: str
    updated_at: str
    version: int


class SamplingCrew(TypedDict):
    id: str
    crew_code: str
    region_code: str
    max_concurrent_visits: int
    scheduled_visit_count: int
    created_at: str
    updated_at: str
    version: int


class SamplingVisit(TypedDict):
    id: str
    contract_id: str
    block_id: str
    crew_id: str
    window_start: str
    window_end: str
    status: str
    measured_brix: Optional[float]
    measured_ta_gl: Optional[float]
    measured_ph: Optional[float]
    measured_rot_pct: Optional[float]
    maturity_flag: Optional[str]
    sampled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PickCall(TypedDict):
    id: str
    contract_id: str
    block_id: str
    target_pick_at: str
    estimated_tons: float
    status: str
    issued_at: Optional[str]
    notice_hours: Optional[int]
    ack_deadline_at: Optional[str]
    acknowledged_at: Optional[str]
    revision_count: int
    appointed_tons: float
    delivered_net_tons: float
    fulfillment_pct: float
    created_at: str
    updated_at: str
    version: int


class DeliveryAppointment(TypedDict):
    id: str
    pick_call_id: str
    lane_id: str
    window_start: str
    window_end: str
    planned_tons: float
    status: str
    captured_net_tons: float
    weigh_tag_count: int
    created_at: str
    updated_at: str
    version: int


class WeighTag(TypedDict):
    id: str
    appointment_id: str
    block_id: str
    gross_weight_lbs: int
    tare_weight_lbs: Optional[int]
    net_weight_lbs: Optional[int]
    net_tons: Optional[float]
    weigh_status: str
    disposition: str
    captured_by_user_id: str
    grade_count: int
    active_adjustment_pct: Optional[float]
    contract_slice_tons: float
    over_slice_tons: float
    over_rejected_tons: float
    excess_rejected_tons: float
    dispute_deadline_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QualityGrade(TypedDict):
    """Append-only lab record: id and created_at only, no updated_at, no version."""

    id: str
    weigh_tag_id: str
    brix: float
    ta_gl: float
    ph: float
    rot_pct: float
    mog_pct: float
    brix_component_pct: float
    acid_component_pct: float
    rot_component_pct: float
    mog_component_pct: float
    raw_adjustment_pct: float
    adjustment_pct: float
    recommended_disposition: str
    graded_by_user_id: str
    superseded_at: Optional[str]
    created_at: str


class SettlementLine(TypedDict):
    id: str
    weigh_tag_id: str
    contract_id: str
    bucket: str
    tons: float
    adjustment_pct_applied: float
    price_per_ton_cents: int
    gross_amount_cents: int
    provisional_amount_cents: int
    final_amount_cents: Optional[int]
    status: str
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaymentInstallment(TypedDict):
    id: str
    contract_id: str
    installment_no: int
    pct_of_settlement: float
    due_offset_days: int
    lien_protected: bool
    planned_amount_cents: int
    paid_amount_cents: int
    due_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
