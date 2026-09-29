"""Domain types for the Used Furniture Consignment Gallery API.

Entity TypedDicts, status enums and the operator role enum, all named exactly
as the PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CONSIGNOR = "Consignor"
    BUYER = "Buyer"
    INTAKE_APPRAISER = "IntakeAppraiser"
    FLOOR_OPERATOR = "FloorOperator"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    GALLERY_MANAGER = "GalleryManager"
    SYSTEM_OPERATOR = "SystemOperator"


class ConsignorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class EscheatState(str, Enum):
    NONE = "NONE"
    DORMANT = "DORMANT"
    ESCHEATED = "ESCHEATED"


class PayoutMethod(str, Enum):
    ACH = "ACH"
    CHECK = "CHECK"
    STORE_CREDIT = "STORE_CREDIT"


class BuyerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


class PriceScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class ItemCategory(str, Enum):
    SOFA = "SOFA"
    DINING = "DINING"
    CASEGOOD = "CASEGOOD"
    RUG = "RUG"
    ART = "ART"
    OUTDOOR = "OUTDOOR"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    REJECTED = "REJECTED"


class ItemLifecycleState(str, Enum):
    INTAKE_SUBMITTED = "INTAKE_SUBMITTED"
    SCREEN_ACCEPTED = "SCREEN_ACCEPTED"
    SCREEN_REJECTED = "SCREEN_REJECTED"
    SCHEDULED_PICKUP = "SCHEDULED_PICKUP"
    RECEIVED = "RECEIVED"
    RECEIVING_DISPUTE = "RECEIVING_DISPUTE"
    AWAITING_PLACEMENT = "AWAITING_PLACEMENT"
    ON_FLOOR = "ON_FLOOR"
    MARKED_DOWN = "MARKED_DOWN"
    UNSOLD_PENDING_ELECTION = "UNSOLD_PENDING_ELECTION"
    DONATION_SCHEDULED = "DONATION_SCHEDULED"
    RETURN_SCHEDULED = "RETURN_SCHEDULED"
    DONATED = "DONATED"
    RETURNED = "RETURNED"
    WRITTEN_OFF = "WRITTEN_OFF"
    SOLD = "SOLD"
    SETTLED = "SETTLED"


class ItemInventoryState(str, Enum):
    PENDING_CUSTODY = "PENDING_CUSTODY"
    IN_CUSTODY = "IN_CUSTODY"
    SHRINKAGE_MISSING = "SHRINKAGE_MISSING"
    WRITTEN_OFF_INV = "WRITTEN_OFF_INV"
    RELEASED = "RELEASED"


class DispositionElection(str, Enum):
    NONE = "NONE"
    DISCOUNT = "DISCOUNT"
    DONATE = "DONATE"
    RETURN = "RETURN"


class TruckStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"


class CrewStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFF_DUTY = "OFF_DUTY"


class ZoneType(str, Enum):
    SHOWROOM_FRONT = "SHOWROOM_FRONT"
    SHOWROOM_REAR = "SHOWROOM_REAR"
    WAREHOUSE = "WAREHOUSE"
    CLEARANCE = "CLEARANCE"


class ZoneStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class UtilizationState(str, Enum):
    NORMAL = "NORMAL"
    TIGHT = "TIGHT"
    FULL = "FULL"


class PickupJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class SaleStatus(str, Enum):
    COMPLETED = "COMPLETED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class DeliveryOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    REFUSED = "REFUSED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class FaultParty(str, Enum):
    GALLERY = "GALLERY"
    CONSIGNOR = "CONSIGNOR"
    BUYER = "BUYER"
    UNDETERMINED = "UNDETERMINED"


class ShrinkageAuditStatus(str, Enum):
    COUNTED = "COUNTED"
    RECONCILED = "RECONCILED"
    ABANDONED = "ABANDONED"


class LedgerEntryType(str, Enum):
    SALE_CREDIT = "SALE_CREDIT"
    SALE_REVERSAL_DEBIT = "SALE_REVERSAL_DEBIT"
    SHRINKAGE_CREDIT = "SHRINKAGE_CREDIT"
    SHRINKAGE_RECOVERY_DEBIT = "SHRINKAGE_RECOVERY_DEBIT"
    PICKUP_SURCHARGE_DEBIT = "PICKUP_SURCHARGE_DEBIT"
    DAMAGE_ALLOCATION_DEBIT = "DAMAGE_ALLOCATION_DEBIT"
    DISPOSAL_FEE_DEBIT = "DISPOSAL_FEE_DEBIT"
    PAYOUT_DISBURSEMENT_DEBIT = "PAYOUT_DISBURSEMENT_DEBIT"
    ESCHEATMENT_DEBIT = "ESCHEATMENT_DEBIT"


# --- Entity TypedDicts -------------------------------------------------------
# Resources that carry updated_at + version alongside id + created_at.

class Consignor(TypedDict):
    id: str
    display_name: str
    email: str
    address_line: str
    floor_number: int
    has_elevator: bool
    payout_method: str
    status: str
    unclaimed_balance_cents: int
    lifetime_credits_cents: int
    last_activity_at: str
    escheat_state: str
    created_at: str
    updated_at: str
    version: int


class Buyer(TypedDict):
    id: str
    display_name: str
    email: str
    address_line: str
    floor_number: int
    has_elevator: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PriceSchedule(TypedDict):
    id: str
    name: str
    unsold_trigger_day: int
    election_window_days: int
    step_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsignmentAgreement(TypedDict):
    id: str
    consignor_id: str
    price_schedule_id: str
    term_days: int
    status: str
    effective_at: Optional[str]
    expires_at: Optional[str]
    approved_by_user_id: Optional[str]
    item_count: int
    created_at: str
    updated_at: str
    version: int


class ConsignmentItem(TypedDict):
    id: str
    consignor_id: str
    agreement_id: str
    parent_lot_item_id: Optional[str]
    pickup_job_id: Optional[str]
    placement_zone_id: Optional[str]
    title: str
    category: str
    declared_value_cents: int
    photo_count: int
    volume_cuft: int
    footprint_sqft: int
    photo_score: Optional[float]
    provisional_condition_grade: Optional[str]
    provisional_list_price_cents: Optional[int]
    condition_grade: Optional[str]
    list_price_cents: Optional[int]
    current_price_cents: Optional[int]
    markdown_sequence: int
    lifecycle_state: str
    inventory_state: str
    tag_code: Optional[str]
    listed_at: Optional[str]
    days_on_floor: int
    election_round: int
    election_deadline_at: Optional[str]
    disposition_election: Optional[str]
    unsold_trigger_day_effective: int
    clearance_relocation_pending: bool
    lot_component_count: int
    lot_ready: bool
    screened_by_user_id: Optional[str]
    received_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Truck(TypedDict):
    id: str
    name: str
    capacity_volume_cuft: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WhiteGloveCrew(TypedDict):
    id: str
    name: str
    max_concurrent_jobs: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FloorZone(TypedDict):
    id: str
    name: str
    zone_type: str
    capacity_sqft: int
    occupied_sqft: int
    utilization_state: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PickupJob(TypedDict):
    id: str
    consignor_id: str
    truck_id: str
    window_start: str
    window_end: str
    crew_size: int
    item_count: int
    total_volume_cuft: int
    declared_stair_flights: int
    declared_elevator: bool
    quoted_surcharge_cents: int
    actual_stair_flights: Optional[int]
    actual_elevator_used: Optional[bool]
    actual_crew_size: Optional[int]
    final_surcharge_cents: Optional[int]
    surcharge_variance_cents: Optional[int]
    status: str
    scheduled_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Sale(TypedDict):
    id: str
    item_id: str
    buyer_id: str
    sale_price_cents: int
    markdown_sequence_at_sale: int
    split_pct_applied: float
    consignor_share_cents: int
    gallery_share_cents: int
    refund_cents: int
    status: str
    sold_at: str
    reversed_at: Optional[str]
    sold_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class DeliveryOrder(TypedDict):
    id: str
    sale_id: str
    crew_id: str
    window_start: str
    window_end: str
    stair_flights: int
    elevator_used: bool
    delivery_fee_cents: int
    status: str
    outcome_recorded_at: Optional[str]
    claim_window_ends_at: Optional[str]
    scheduled_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict):
    id: str
    delivery_order_id: str
    claim_amount_cents: int
    description: str
    status: str
    resubmission_count: int
    fault_party: Optional[str]
    adjudicated_amount_cents: Optional[int]
    gallery_absorbed_cents: Optional[int]
    consignor_debited_cents: Optional[int]
    info_request_note: Optional[str]
    adjudicated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShrinkageAudit(TypedDict):
    id: str
    floor_zone_id: str
    counted_item_ids: List[str]
    expected_item_count: int
    counted_item_count: int
    variance_count: int
    missing_item_ids: List[str]
    write_off_total_cents: int
    status: str
    counted_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Deliberately immutable once written: appended/minted and never edited, so
# these two carry only id and created_at -- no updated_at, no version.

class PriceScheduleStep(TypedDict):
    id: str
    schedule_id: str
    sequence: int
    start_day_offset: int
    markdown_pct: float
    min_price_cents: int
    created_at: str


class PayoutLedgerEntry(TypedDict):
    id: str
    consignor_id: str
    item_id: Optional[str]
    entry_type: str
    amount_cents: int
    withholding_cents: Optional[int]
    processing_fee_cents: Optional[int]
    net_payout_cents: Optional[int]
    balance_after_cents: int
    memo: str
    effective_at: str
    created_at: str
