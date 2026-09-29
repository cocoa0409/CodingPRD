"""Domain types for the builders risk course-of-construction API.

Status enums, role names and entity TypedDicts. Every name here is the exact
field or value spelling used by the PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    UNDERWRITER = "Underwriter"
    UNDERWRITING_MANAGER = "UnderwritingManager"
    RISK_ENGINEER = "RiskEngineer"
    CLAIM_ADJUSTER = "ClaimAdjuster"
    PROJECT_CONTACT = "ProjectContact"
    LOSS_PAYEE = "LossPayee"


class ProjectStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    UNDER_CONSTRUCTION = "UNDER_CONSTRUCTION"
    SUBSTANTIALLY_COMPLETE = "SUBSTANTIALLY_COMPLETE"


class PolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    REFERRED = "REFERRED"
    QUOTED = "QUOTED"
    BOUND = "BOUND"
    IN_FORCE = "IN_FORCE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"


class CoveragePartStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class AcknowledgmentStatus(str, Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class EndorsementStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RETURNED_FOR_INFO = "RETURNED_FOR_INFO"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    LAPSED = "LAPSED"
    SUPERSEDED = "SUPERSEDED"
    RESCINDED = "RESCINDED"


class ClaimAdjustmentStatus(str, Enum):
    REPORTED = "REPORTED"
    ADJUSTED = "ADJUSTED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class ClaimPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


class LossPaymentStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class NoticeStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class FacilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AssignmentStatus(str, Enum):
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"


CONSTRUCTION_TYPES = ["FRAME", "JOISTED_MASONRY", "NON_COMBUSTIBLE", "FIRE_RESISTIVE"]
PROJECT_KINDS = ["NEW_CONSTRUCTION", "RENOVATION"]
CAT_ZONES = ["INLAND", "WIND_TIER_1", "WIND_TIER_2", "SEISMIC", "FLOOD_A"]
ENGINEERING_GRADES = ["A", "B", "C", "D"]
DEDUCTIBLE_TIERS = ["STANDARD_25K", "ELEVATED_100K", "HIGH_250K"]
PART_TYPES = [
    "MATERIALS_ON_SITE", "IN_TRANSIT", "TEMPORARY_STORAGE", "EXISTING_STRUCTURE",
    "SOFT_COST", "DELAY_IN_COMPLETION", "WATER_DAMAGE", "TESTING_COMMISSIONING",
]
CONDITION_CODES = ["NONE", "APPROVED_NOTICE_REQUIRED", "MITIGATION_PLAN_REQUIRED"]
PARTY_ROLES = ["OWNER", "GENERAL_CONTRACTOR", "LENDER", "SUBCONTRACTOR"]
SLIP_REASONS = ["WEATHER", "LABOR_SHORTAGE", "MATERIAL_DELAY", "DESIGN_CHANGE", "PERMIT_DELAY"]
PERILS = ["WIND", "FLOOD", "FIRE", "THEFT", "WATER_DAMAGE", "TESTING_FAILURE", "DELAY"]
ADJUSTMENT_BASES = ["RECONSTRUCTION_COST", "ACTUAL_LOSS"]
TXN_TYPES = ["INITIAL", "EXTENSION_AP", "EXTENSION_AP_REVERSAL", "RETURN_PREMIUM"]
CANCEL_REASONS = ["INSURED_REQUEST", "CARRIER_INITIATED", "PROJECT_ABANDONED"]
RELEASE_REASONS = ["MANUAL", "POLICY_EXPIRY", "POLICY_CANCELLATION"]
SYSTEM_TYPES = ["SPRINKLER_HYDROSTATIC", "HVAC", "ELECTRICAL_ENERGIZATION",
                "BOILER_STARTUP", "ELEVATOR"]
PROTECTION_CLASSES = ["SPRINKLERED", "NON_SPRINKLERED"]

# The pinned waterfall sequence used by claim adjustment.
ALLOCATION_ORDER = [
    "EXISTING_STRUCTURE", "MATERIALS_ON_SITE", "IN_TRANSIT", "TEMPORARY_STORAGE",
    "TESTING_COMMISSIONING", "WATER_DAMAGE", "SOFT_COST", "DELAY_IN_COMPLETION",
]


# --- Entity TypedDicts ---------------------------------------------------
# Every persisted resource carries id and created_at. All of the entities below
# except PremiumTransaction additionally carry updated_at and version.

class ConstructionProject(TypedDict):
    id: str
    name: str
    site_address: str
    construction_type: str
    project_kind: str
    hard_cost_value_cents: int
    existing_structure_value_cents: int
    cat_zone: str
    planned_start_date: str
    projected_completion_date: str
    actual_substantial_completion_date: Optional[str]
    status: str
    engineering_grade: Optional[str]
    loss_control_report_ref: Optional[str]
    screened_by_user_id: Optional[str]
    submission_risk_score: Optional[int]
    audit_risk_score: Optional[int]
    in_force_policy_count: int
    created_at: str
    updated_at: str
    version: int


class BuildersRiskPolicy(TypedDict):
    id: str
    project_id: str
    term_start_date: str
    term_end_date: str
    original_term_days: int
    cumulative_extension_days: int
    adjusted_completion_date: str
    includes_existing_structure: bool
    deductible_tier: str
    occurrence_deductible_cents: int
    limit_cents: int
    daily_delay_rate_cents: int
    insured_tiv_cents: int
    quoted_premium_cents: Optional[int]
    referral_load_pct: float
    written_premium_cents: int
    eroded_total_cents: int
    return_premium_cents: Optional[int]
    status: str
    quoted_by_user_id: Optional[str]
    bound_at: Optional[str]
    cancel_reason: Optional[str]
    cancel_effective_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoveragePart(TypedDict):
    id: str
    policy_id: str
    part_type: str
    sublimit_cents: int
    condition_code: str
    eroded_cents: int
    available_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NamedInsuredInterest(TypedDict):
    id: str
    policy_id: str
    party_name: str
    party_role: str
    insurable_interest_pct: float
    loss_payee_priority: Optional[int]
    acknowledgment_status: str
    acknowledged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExtensionEndorsement(TypedDict):
    id: str
    policy_id: str
    requested_extension_days: int
    slip_reason: str
    revised_completion_date: str
    status: str
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    info_request_note: Optional[str]
    resubmission_count: int
    slip_factor: Optional[float]
    additional_premium_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    policy_id: str
    peril: str
    loss_date: str
    description: str
    reported_at: str
    adjustment_status: str
    payment_status: str
    adjustment_basis: Optional[str]
    continuing_pm_weeks: int
    allocation_lines: List[Any]
    indemnity_cents: int
    uncovered_cents: int
    delay_days_indemnified: int
    paid_cents: int
    outstanding_reserve_cents: int
    total_incurred_cents: int
    adjusted_by_user_id: Optional[str]
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class LossPayment(TypedDict):
    id: str
    claim_id: str
    payee_interest_id: str
    part_type: str
    amount_cents: int
    status: str
    created_by_user_id: str
    voided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PremiumTransaction(TypedDict):
    """Premium ledger entries are immutable: id and created_at only, no
    updated_at and no version."""
    id: str
    policy_id: str
    sequence_no: int
    txn_type: str
    amount_cents: int
    effective_date: str
    reverses_sequence_no: Optional[int]
    memo: str
    created_at: str


class TestingCommissioningNotice(TypedDict):
    id: str
    project_id: str
    system_type: str
    window_start: str
    window_end: str
    hot_work: bool
    water_charged: bool
    mitigation_plan_ref: Optional[str]
    status: str
    decided_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StorageFacility(TypedDict):
    id: str
    name: str
    site_code: str
    distance_from_site_miles: float
    aggregate_capacity_cents: int
    protection_class: str
    committed_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TemporaryStorageAssignment(TypedDict):
    id: str
    policy_id: str
    facility_id: str
    stored_value_cents: int
    window_start: str
    window_end: str
    status: str
    released_at: Optional[str]
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
