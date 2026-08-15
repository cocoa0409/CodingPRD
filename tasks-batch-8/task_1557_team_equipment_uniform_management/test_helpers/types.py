"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Every resource carries the four
system-managed fields id + created_at + updated_at + version (PRD section
on common resource properties).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    EQUIPMENT_MANAGER = "EquipmentManager"
    TEAM_ADMIN = "TeamAdmin"
    LAUNDRY_VENDOR = "LaundryVendor"


class PositionGroup(str, Enum):
    OFFENSE = "OFFENSE"
    DEFENSE = "DEFENSE"
    SPECIAL_TEAMS = "SPECIAL_TEAMS"


class PlayerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RELEASED = "RELEASED"


class GarmentType(str, Enum):
    GAME_JERSEY = "GAME_JERSEY"
    GAME_PANTS = "GAME_PANTS"
    PRACTICE_JERSEY = "PRACTICE_JERSEY"
    PRACTICE_PANTS = "PRACTICE_PANTS"
    SOCKS = "SOCKS"


class PoolStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class KitOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class KitOrderSource(str, Enum):
    MANUAL = "MANUAL"
    AUTO_REORDER = "AUTO_REORDER"


class KitAssignmentStatus(str, Enum):
    RESERVED = "RESERVED"
    ISSUED = "ISSUED"
    RETURNED = "RETURNED"
    RELEASED = "RELEASED"
    LOST = "LOST"


class GearItemType(str, Enum):
    HELMET = "HELMET"
    SHOULDER_PADS = "SHOULDER_PADS"
    GIRDLE_PADS = "GIRDLE_PADS"
    KNEE_BRACE = "KNEE_BRACE"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    F = "F"


class GearItemStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    ISSUED = "ISSUED"
    OUT_FOR_RECONDITIONING = "OUT_FOR_RECONDITIONING"
    RETIRED = "RETIRED"


class ReconditioningJobStatus(str, Enum):
    OUT = "OUT"
    PASSED = "PASSED"
    FAILED = "FAILED"


class DesignatedKit(str, Enum):
    HOME = "HOME"
    AWAY = "AWAY"
    ALTERNATE = "ALTERNATE"


class GameEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    KIT_LOCKED = "KIT_LOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LaundryStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    COLLECTING = "COLLECTING"
    IN_WASH = "IN_WASH"
    READY = "READY"
    CLOSED = "CLOSED"


class ClaimType(str, Enum):
    LOST = "LOST"
    DAMAGED = "DAMAGED"


class DamageClaimStatus(str, Enum):
    REPORTED = "REPORTED"
    ASSESSED = "ASSESSED"
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"


class DispositionMethod(str, Enum):
    RETURN_TO_STOCK = "RETURN_TO_STOCK"
    DONATE = "DONATE"
    MEMORABILIA_SALE = "MEMORABILIA_SALE"
    DISCARD = "DISCARD"


class DispositionCaseStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"


class Player(TypedDict, total=False):
    id: str
    full_name: str
    position_group: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryPool(TypedDict, total=False):
    id: str
    season_label: str
    garment_type: str
    size_code: str
    stock_on_hand: int
    reserved_quantity: int
    in_laundry_quantity: int
    available_quantity: int
    reorder_point: int
    reorder_batch_size: int
    reorder_blocked: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplierContract(TypedDict, total=False):
    id: str
    vendor_name: str
    season_label: str
    status: str
    start_on: str
    end_on: str
    allocation_caps: List[dict]
    units_committed: List[dict]
    default_lead_time_days: int
    contract_rebate_pct: float
    created_at: str
    updated_at: str
    version: int


class KitOrder(TypedDict, total=False):
    id: str
    supplier_contract_id: str
    source: str
    status: str
    lines: List[dict]
    received_lines: List[dict]
    expected_delivery_on: str
    subtotal_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int


class KitAssignment(TypedDict, total=False):
    id: str
    player_id: str
    season_label: str
    jersey_number: int
    jersey_pool_id: str
    pants_pool_id: str
    status: str
    issued_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GearItem(TypedDict, total=False):
    id: str
    asset_tag: str
    item_type: str
    size_spec: str
    condition_grade: str
    certification_expires_on: Optional[str]
    acquired_on: str
    status: str
    current_holder_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReconditioningJob(TypedDict, total=False):
    id: str
    item_id: str
    provider_name: str
    sent_on: str
    due_back_on: str
    status: str
    result_grade: Optional[str]
    result_recorded_on: Optional[str]
    certification_valid_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GameEvent(TypedDict, total=False):
    id: str
    season_label: str
    opponent_name: str
    kickoff_at: str
    designated_kit: str
    status: str
    checklist: List[dict]
    laundry_status: str
    laundry_load: List[dict]
    laundry_due_at: Optional[str]
    laundry_overdue: bool
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict, total=False):
    id: str
    player_id: str
    claim_type: str
    kit_assignment_id: Optional[str]
    gear_item_id: Optional[str]
    base_value_cents: int
    description: Optional[str]
    status: str
    condition_grade: Optional[str]
    provisional_fee_cents: int
    assessed_fee_cents: Optional[int]
    final_fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DispositionCase(TypedDict, total=False):
    id: str
    season_label: str
    garment_type: str
    size_code: Optional[str]
    method: str
    unit_price_cents: Optional[int]
    status: str
    affected_pool_ids: List[str]
    units_disposed: int
    proceeds_cents: int
    created_at: str
    updated_at: str
    version: int
