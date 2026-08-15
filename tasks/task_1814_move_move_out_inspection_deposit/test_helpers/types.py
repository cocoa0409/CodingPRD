"""Domain types: entity TypedDicts, status enums, role enum.

Field names and enum values follow the PRD exactly (PRD §2.4 common fields,
§3 domain sections for entity-specific fields).
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    MANAGER_ADMIN = "ManagerAdmin"
    PROPERTY_MANAGER = "PropertyManager"
    INSPECTOR = "Inspector"
    TENANT = "Tenant"


class InterestBasis(str, Enum):
    ACTUAL_DAYS = "ACTUAL_DAYS"
    WHOLE_YEARS = "WHOLE_YEARS"


class OccupancyStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    RESERVED = "RESERVED"


class TenancyStatus(str, Enum):
    PENDING_MOVE_IN = "PENDING_MOVE_IN"
    OCCUPIED = "OCCUPIED"
    NOTICE_GIVEN = "NOTICE_GIVEN"
    VACATED = "VACATED"
    SETTLED = "SETTLED"
    ESCHEATED = "ESCHEATED"


class InspectionKind(str, Enum):
    MOVE_IN = "MOVE_IN"
    MOVE_OUT = "MOVE_OUT"


class InspectionStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPLETED = "COMPLETED"


class ItemCategory(str, Enum):
    CARPET = "CARPET"
    PAINT = "PAINT"
    OTHER = "OTHER"


class ItemCondition(str, Enum):
    NEW = "NEW"
    GOOD = "GOOD"
    FAIR = "FAIR"
    WORN = "WORN"
    DAMAGED = "DAMAGED"
    MISSING = "MISSING"


class Determination(str, Enum):
    UNASSESSED = "UNASSESSED"
    NORMAL_WEAR = "NORMAL_WEAR"
    TENANT_DAMAGE = "TENANT_DAMAGE"


class DeductionSource(str, Enum):
    MOVE_OUT_DAMAGE = "MOVE_OUT_DAMAGE"
    KEY_NOT_RETURNED = "KEY_NOT_RETURNED"
    FOB_NOT_RETURNED = "FOB_NOT_RETURNED"
    LOCK_CHANGE = "LOCK_CHANGE"
    UNPAID_RENT = "UNPAID_RENT"
    CLEANING = "CLEANING"
    OTHER = "OTHER"


class DeductionStatus(str, Enum):
    DRAFT = "DRAFT"
    BILLED = "BILLED"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"
    SETTLED = "SETTLED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    MANAGER_COUNTERED = "MANAGER_COUNTERED"
    CLOSED_AGREED = "CLOSED_AGREED"
    ESCALATED_SMALL_CLAIMS = "ESCALATED_SMALL_CLAIMS"
    COURT_RESOLVED = "COURT_RESOLVED"
    WITHDRAWN = "WITHDRAWN"


class DisbursementKind(str, Enum):
    REFUND = "REFUND"
    PENALTY = "PENALTY"


class DisbursementStatus(str, Enum):
    SENT = "SENT"
    CASHED = "CASHED"
    REVERSED = "REVERSED"
    STALE_DATED = "STALE_DATED"
    ESCHEATED = "ESCHEATED"


class JurisdictionProfile(TypedDict):
    id: str
    code: str
    deposit_return_deadline_days: int
    dispute_window_days: int
    interest_required: bool
    annual_interest_rate_bp: int
    interest_basis: str
    stale_check_days: int
    small_claims_cap_cents: int
    bad_faith_multiplier: int
    lock_change_allowed: bool
    allow_actual_cost_charge: bool
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    name: str
    address: str
    jurisdiction_profile_id: str
    key_charge_cents: int
    fob_charge_cents: int
    lock_change_cents: int
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    property_id: str
    unit_number: str
    carpet_installed_on: str
    carpet_life_years: int
    paint_applied_on: str
    paint_life_years: int
    occupancy_status: str
    created_at: str
    updated_at: str
    version: int


class Tenancy(TypedDict):
    id: str
    unit_id: str
    tenant_display_name: str
    forwarding_address: Optional[str]
    lease_start_on: str
    lease_end_on: str
    monthly_rent_cents: int
    deposit_cents: int
    keys_issued: int
    fobs_issued: int
    keys_returned: int
    fobs_returned: int
    move_in_on: Optional[str]
    notice_given_on: Optional[str]
    move_out_on: Optional[str]
    interest_accrued_cents: int
    pending_deductions_cents: int
    total_deductions_cents: int
    refund_paid_cents: int
    penalty_paid_cents: int
    escheated_cents: int
    balance_remaining_cents: int
    released_cents: int
    reserved_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    tenancy_id: str
    kind: str
    inspector_user_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InspectionItem(TypedDict):
    id: str
    inspection_id: str
    area_name: str
    category: str
    condition: str
    photo_count: int
    determination: str
    linked_move_in_item_id: Optional[str]
    replacement_cost_cents: Optional[int]
    actual_repair_cents: Optional[int]
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeductionItem(TypedDict):
    id: str
    tenancy_id: str
    inspection_item_id: Optional[str]
    statement_id: Optional[str]
    source: str
    description: str
    quantity: int
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DepositStatement(TypedDict):
    id: str
    tenancy_id: str
    statement_seq: int
    issued_at: Optional[str]
    deadline_on: Optional[str]
    late: Optional[bool]
    interest_cents: int
    deduction_total_cents: int
    released_cents: int
    refund_due_cents: int
    projected_deductions_cents: int
    projected_refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    statement_id: str
    tenancy_id: str
    disputed_amount_cents: int
    reason: str
    counter_amount_cents: Optional[int]
    exposure_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict):
    id: str
    tenancy_id: str
    statement_id: str
    kind: str
    amount_cents: int
    payee_name: str
    sent_at: str
    cashed_at: Optional[str]
    escheatment_reference: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
