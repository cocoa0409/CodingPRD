"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums (PRD §3 state machines)
# ---------------------------------------------------------------------------

class CampaignStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SETTLING = "SETTLING"
    SETTLED = "SETTLED"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    IN_USE = "IN_USE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TicketStatus(str, Enum):
    CREATED = "CREATED"
    WEIGHED = "WEIGHED"
    REWEIGHING = "REWEIGHING"
    SAMPLED = "SAMPLED"
    ACCEPTED = "ACCEPTED"
    CREDITED = "CREDITED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class SampleType(str, Enum):
    STATION_QUICK = "STATION_QUICK"
    LAB_VERIFY = "LAB_VERIFY"


class SampleStatus(str, Enum):
    COLLECTED = "COLLECTED"
    RESULT_RECORDED = "RESULT_RECORDED"
    VERIFIED = "VERIFIED"


class PileFillStatus(str, Enum):
    FILLING = "FILLING"
    SEALED = "SEALED"
    RECLAIMING = "RECLAIMING"
    EMPTY = "EMPTY"


class PileConditionStatus(str, Enum):
    SOUND = "SOUND"
    DETERIORATING = "DETERIORATING"
    LOSS_DECLARED = "LOSS_DECLARED"


class AllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"


class LossMethod(str, Enum):
    TABLE_RATE = "TABLE_RATE"
    RESURVEY = "RESURVEY"


class LossEventStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    ALLOCATED = "ALLOCATED"


class PoolStatus(str, Enum):
    OPEN = "OPEN"
    ACCRUING = "ACCRUING"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ISSUED = "ISSUED"


class LedgerKind(str, Enum):
    ADVANCE_CREDIT = "ADVANCE_CREDIT"
    FINAL_SETTLEMENT = "FINAL_SETTLEMENT"
    TRANSPORT_CREDIT = "TRANSPORT_CREDIT"
    REVERSAL = "REVERSAL"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PAID = "PAID"


class UserRole(str, Enum):
    COOP_ADMIN = "COOP_ADMIN"
    SCHEDULER = "SCHEDULER"
    MEMBER = "MEMBER"
    STATION_OPERATOR = "STATION_OPERATOR"
    QUALITY_TECH = "QUALITY_TECH"
    POOL_ACCOUNTANT = "POOL_ACCOUNTANT"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4 common fields: id, created_at, updated_at, version)
# ---------------------------------------------------------------------------

class Campaign(TypedDict):
    id: str
    name: str
    window_start: str
    window_end: str
    base_price_cents_per_ton: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    name: str
    member_code: str
    haul_distance_miles: float
    status: str
    net_ledger_cents: int
    deterioration_loss_lbs: float
    created_at: str
    updated_at: str
    version: int


class ReceivingStation(TypedDict):
    id: str
    name: str
    booking_capacity_tons: float
    booked_tons: float
    received_tons: float
    stored_tons: float
    created_at: str
    updated_at: str
    version: int


class StoragePile(TypedDict):
    id: str
    station_id: str
    capacity_tons: float
    fill_status: str
    condition_status: str
    stored_lbs: float
    sealed_stored_lbs: float
    sealed_at: Optional[str]
    reclaim_started_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HarvestBooking(TypedDict):
    id: str
    member_id: str
    station_id: str
    campaign_id: str
    slot_start: str
    slot_end: str
    estimated_tons: float
    status: str
    created_at: str
    updated_at: str
    version: int


class LoadTicket(TypedDict):
    id: str
    booking_id: str
    member_id: str
    station_id: str
    gross_weight_lbs: Optional[float]
    tare_weight_lbs: Optional[float]
    net_weight_lbs: Optional[float]
    status: str
    provisional_trash_pct: Optional[float]
    provisional_sugar_pct: Optional[float]
    provisional_factor: Optional[float]
    provisional_adjusted_net_tons: Optional[float]
    provisional_value_cents: Optional[int]
    final_trash_pct: Optional[float]
    final_sugar_pct: Optional[float]
    final_factor: Optional[float]
    adjusted_net_tons_final: Optional[float]
    adjusted_net_lbs_final: Optional[float]
    created_at: str
    updated_at: str
    version: int


class QualitySample(TypedDict):
    id: str
    ticket_id: str
    sample_type: str
    sugar_pct: Optional[float]
    trash_pct: Optional[float]
    recorded_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PileAllocation(TypedDict):
    id: str
    ticket_id: str
    pile_id: str
    member_id: str
    allocated_lbs: float
    remaining_lbs: float
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageLossEvent(TypedDict):
    id: str
    pile_id: str
    method: str
    survey_at: str
    window_start: str
    window_end: str
    measured_remaining_lbs: Optional[float]
    loss_lbs: Optional[float]
    unallocated_lbs: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentPool(TypedDict):
    id: str
    campaign_id: str
    status: str
    estimated_pool_value_cents: Optional[int]
    gross_pool_value_cents: Optional[int]
    accrued_provisional_cents: int
    final_price_cents_per_lb: Optional[float]
    created_at: str
    updated_at: str
    version: int


class PoolInstallment(TypedDict):
    id: str
    pool_id: str
    pct_of_estimated: float
    target_amount_cents: int
    distributed_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentLedgerEntry(TypedDict):
    """Append-only event log (PRD §2.4): carries ONLY id + created_at as common
    fields. updated_at and version are deliberately absent."""
    id: str
    created_at: str
    member_id: str
    pool_id: str
    installment_id: Optional[str]
    settlement_id: Optional[str]
    kind: str
    amount_cents: int
    reversal_of_id: Optional[str]


class SettlementStatement(TypedDict):
    id: str
    member_id: str
    campaign_id: str
    pool_id: str
    sugar_lbs: float
    price_cents_per_lb: float
    gross_entitlement_cents: int
    advances_posted_cents: int
    transport_credit_cents: int
    final_payment_cents: int
    total_payment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
