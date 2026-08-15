"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_COORDINATOR = "ProgramCoordinator"
    INSPECTOR = "Inspector"
    PROPERTY_OWNER = "PropertyOwner"
    CONTRACTOR = "Contractor"
    FORESTRY_OFFICER = "ForestryOfficer"
    FINANCE_OFFICER = "FinanceOfficer"
    HEARING_OFFICER = "HearingOfficer"


class ProgramCycleStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class StreetClass(str, Enum):
    LOCAL = "LOCAL"
    COLLECTOR = "COLLECTOR"
    ARTERIAL = "ARTERIAL"


class HardshipTier(str, Enum):
    NONE = "NONE"
    SENIOR_65 = "SENIOR_65"
    LOW_INCOME = "LOW_INCOME"


class SegmentStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    FLAGGED = "FLAGGED"
    UNDER_NOTICE = "UNDER_NOTICE"
    REPAIR_IN_PROGRESS = "REPAIR_IN_PROGRESS"
    RESTORED = "RESTORED"


class DefectType(str, Enum):
    VERTICAL_SEPARATION = "VERTICAL_SEPARATION"
    HORIZONTAL_OPENING = "HORIZONTAL_OPENING"
    SPALLING = "SPALLING"
    SETTLEMENT = "SETTLEMENT"
    TREE_ROOT_UPHEAVAL = "TREE_ROOT_UPHEAVAL"
    CRUMBLED_JOINT = "CRUMBLED_JOINT"


class DefectStatus(str, Enum):
    OPEN = "OPEN"
    AWAITING_FORESTRY = "AWAITING_FORESTRY"
    UNDER_REPAIR = "UNDER_REPAIR"
    VERIFIED = "VERIFIED"


class SeverityClass(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    TRIP_HAZARD = "TRIP_HAZARD"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    UNDER_APPEAL = "UNDER_APPEAL"
    COMPLIANT = "COMPLIANT"
    DELINQUENT = "DELINQUENT"
    CITY_REPAIR_SCHEDULED = "CITY_REPAIR_SCHEDULED"
    CITY_REPAIR_COMPLETED = "CITY_REPAIR_COMPLETED"
    LIENED = "LIENED"
    CLOSED = "CLOSED"
    VOID = "VOID"


class AppealStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    UPHELD = "UPHELD"
    REVERSED = "REVERSED"


class ReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RETURNED = "RETURNED"
    OBLIGATED = "OBLIGATED"
    REIMBURSED = "REIMBURSED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    RESERVED = "RESERVED"
    DISBURSED = "DISBURSED"
    RELEASED = "RELEASED"


class BatchStatus(str, Enum):
    OPEN_FOR_ITEMS = "OPEN_FOR_ITEMS"
    SEALED_FOR_BIDDING = "SEALED_FOR_BIDDING"
    AWARDED = "AWARDED"
    WORK_IN_PROGRESS = "WORK_IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class WorkItemStatus(str, Enum):
    POOLED = "POOLED"
    SCHEDULED = "SCHEDULED"
    WORK_COMPLETED = "WORK_COMPLETED"
    VERIFIED = "VERIFIED"
    REMOVED = "REMOVED"


class BidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"
    AWARDED = "AWARDED"
    NOT_AWARDED = "NOT_AWARDED"


class ForestryDecision(str, Enum):
    PENDING = "PENDING"
    PRUNE_APPROVED = "PRUNE_APPROVED"
    REMOVAL_ORDERED = "REMOVAL_ORDERED"
    NO_CITY_CONFLICT = "NO_CITY_CONFLICT"


class ForestryStatus(str, Enum):
    PENDING = "PENDING"
    DECIDED = "DECIDED"
    CLEARED = "CLEARED"


class LienStatus(str, Enum):
    ASSESSED = "ASSESSED"
    RECORDED = "RECORDED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    SATISFIED = "SATISFIED"
    FORECLOSURE_REFERRED = "FORECLOSURE_REFERRED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


# --- Entity TypedDicts (all carry id + created_at + updated_at + version) ---


class ProgramCycle(TypedDict):
    id: str
    cycle_year: int
    window_start_date: str
    window_end_date: str
    appropriation_cents: int
    committed_cents: int
    disbursed_cents: int
    available_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PropertyOwner(TypedDict):
    id: str
    full_name: str
    mailing_address: str
    hardship_tier: str
    created_at: str
    updated_at: str
    version: int


class PropertyParcel(TypedDict):
    id: str
    parcel_number: str
    owner_id: str
    street_address: str
    street_class: str
    is_corner_lot: bool
    is_city_owned: bool
    owner_responsibility_pct: int
    delinquency_flag: bool
    created_at: str
    updated_at: str
    version: int


class SidewalkSegment(TypedDict):
    id: str
    segment_code: str
    parcel_id: str
    length_ft: float
    width_ft: float
    is_corner_segment: bool
    has_existing_curb_ramp: bool
    open_defect_count: int
    condition_screening: int
    condition_area_weighted: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Defect(TypedDict):
    id: str
    segment_id: str
    defect_type: str
    measured_offset_inches: Optional[float]
    area_sqft: float
    city_tree_involved: bool
    severity_class: str
    recorded_by_inspector_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairNotice(TypedDict):
    id: str
    parcel_id: str
    defect_ids: list
    base_deadline_days: int
    issued_at: Optional[str]
    compliance_deadline: Optional[str]
    prior_notice_id: Optional[str]
    issued_by_user_id: Optional[str]
    appeal_status: str
    appeal_grounds: Optional[str]
    appeal_decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CostShareApplication(TypedDict):
    id: str
    notice_id: str
    parcel_id: str
    owner_id: str
    cycle_id: str
    estimated_qty_sqft: float
    ramp_upgrade_required: bool
    share_pct: int
    provisional_award_cents: int
    final_award_cents: Optional[int]
    approved_at: Optional[str]
    approval_expires_at: Optional[str]
    review_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class BidBatch(TypedDict):
    id: str
    neighborhood_code: str
    work_window_start: str
    work_window_end: str
    bid_deadline: str
    estimated_total_cents: int
    awarded_bid_id: Optional[str]
    awarded_total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class BatchWorkItem(TypedDict):
    id: str
    batch_id: str
    notice_id: str
    scope_sqft: float
    engineer_unit_rate_cents: int
    includes_ramp_upgrade: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Contractor(TypedDict):
    id: str
    company_name: str
    license_number: str
    insurance_valid_until: str
    is_suspended: bool
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict):
    id: str
    batch_id: str
    contractor_id: str
    unit_rate_cents: int
    ramp_flat_fee_cents: int
    submitted_at: str
    evaluated_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ForestryReview(TypedDict):
    id: str
    defect_id: str
    decision: str
    decided_by_user_id: Optional[str]
    work_completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LienCase(TypedDict):
    id: str
    notice_id: str
    parcel_id: str
    actual_repair_cost_cents: int
    admin_fee_cents: int
    city_credit_cents: int
    owner_principal_cents: int
    interest_rate_bp: int
    assessed_at: str
    principal_remaining_cents: int
    accrued_interest_cents: int
    last_accrual_day: int
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only evidentiary row: carries ONLY id + created_at (no updated_at, no version)
class InspectionRecord(TypedDict):
    id: str
    notice_id: str
    inspector_id: str
    result: str
    notes: Optional[str]
    created_at: str
