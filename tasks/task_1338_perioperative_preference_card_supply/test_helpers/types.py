"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class SurgeonStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class SupplyItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class CardStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class Designation(str, Enum):
    OPEN = "OPEN"
    HOLD = "HOLD"


class CaseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PICKING_RELEASED = "PICKING_RELEASED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PickListStatus(str, Enum):
    GENERATED = "GENERATED"
    IN_PICKING = "IN_PICKING"
    PICKING_EXCEPTION = "PICKING_EXCEPTION"
    STAGED = "STAGED"
    DISPATCHED = "DISPATCHED"
    RETURNED = "RETURNED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PickListLineStatus(str, Enum):
    PENDING = "PENDING"
    PICKED = "PICKED"
    SHORT = "SHORT"
    SUBSTITUTED = "SUBSTITUTED"


class AuditStatus(str, Enum):
    GENERATED = "GENERATED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DISPUTED = "DISPUTED"
    ACCEPTED = "ACCEPTED"


class RequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CountStatus(str, Enum):
    RECORDED = "RECORDED"
    VERIFIED = "VERIFIED"


class ChargeStatus(str, Enum):
    PENDING = "PENDING"
    CAPTURED = "CAPTURED"
    VOIDED = "VOIDED"


class UserRole(str, Enum):
    SURGEON = "Surgeon"
    SUPPLY_CHAIN_ANALYST = "SupplyChainAnalyst"
    CART_TECHNICIAN = "CartTechnician"
    CIRCULATING_NURSE = "CirculatingNurse"
    VALUE_ANALYSIS_OFFICER = "ValueAnalysisOfficer"
    MATERIALS_MANAGER = "MaterialsManager"
    ANY = "Any"


class Surgeon(TypedDict):
    id: str
    full_name: str
    specialty: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplyItem(TypedDict):
    id: str
    sku: str
    name: str
    unit_cost_cents: int
    substitute_group: Optional[str]
    consignment_flag: bool
    on_hand_quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PreferenceCard(TypedDict):
    id: str
    surgeon_id: str
    procedure_name: str
    version_number: int
    status: str
    estimated_cost_cents: int
    flagged_audit_count: int
    rolling_line_match_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class PreferenceCardLine(TypedDict):
    id: str
    card_id: str
    supply_item_id: str
    quantity: int
    designation: str
    pick_sequence: Optional[int]
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurgicalCase(TypedDict):
    id: str
    surgeon_id: str
    card_id: str
    pinned_card_version_number: int
    procedure_name: str
    scheduled_start: str
    expected_duration_min: int
    room: str
    consignment_budget_cents: Optional[int]
    status: str
    standard_cost_cents: Optional[int]
    actual_cost_cents: Optional[int]
    waste_cost_cents: Optional[int]
    pick_exception_count: int
    created_at: str
    updated_at: str
    version: int


class PickList(TypedDict):
    id: str
    case_id: str
    card_id: str
    card_version_number: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PickListLine(TypedDict):
    id: str
    pick_list_id: str
    supply_item_id: str
    designation: str
    qty_requested: int
    qty_picked: int
    qty_returned_unopened: int
    unit_cost_cents: int
    pick_sequence: int
    status: str
    substituted_item_id: Optional[str]
    short_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UsageRecord(TypedDict):
    id: str
    case_id: str
    pick_list_line_id: str
    supply_item_id: str
    qty_opened: int
    qty_used: int
    qty_wasted: int
    unit_cost_cents: int
    waste_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class CardAccuracyAudit(TypedDict):
    id: str
    case_id: str
    card_id: str
    card_version_number: int
    matched_line_count: int
    total_line_count: int
    line_match_pct: float
    spend_match_pct: float
    waste_pct: float
    waste_flag: bool
    status: str
    dispute_comment: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductRequest(TypedDict):
    id: str
    surgeon_id: str
    proposed_item_name: str
    proposed_sku: str
    estimated_unit_cost_cents: int
    rationale: str
    substitute_group: Optional[str]
    consignment_flag: bool
    replaces_item_id: Optional[str]
    status: str
    reviewing_officer_id: Optional[str]
    endorser_ids: list
    endorsements_count: int
    rejection_reason: Optional[str]
    created_item_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsignmentCount(TypedDict):
    id: str
    supply_item_id: str
    counted_qty: int
    system_qty_at_count: int
    variance_qty: int
    variance_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsignmentCharge(TypedDict):
    id: str
    case_id: str
    usage_record_id: str
    supply_item_id: str
    qty_billed: int
    unit_cost_cents: int
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
