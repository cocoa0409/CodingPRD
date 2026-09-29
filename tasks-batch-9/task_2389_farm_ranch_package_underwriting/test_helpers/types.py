"""Domain types for the Farm And Ranch Package Underwriting API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD spells them on the wire.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1) — six role names, spelled as they must appear on the wire.
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    AGENT = "Agent"
    UNDERWRITER = "Underwriter"
    SENIOR_UNDERWRITER = "SeniorUnderwriter"
    LOSS_CONTROL_SPECIALIST = "LossControlSpecialist"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------


class AppointmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class InspectorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Peril(str, Enum):
    HAIL = "HAIL"
    WIND = "WIND"
    WILDFIRE = "WILDFIRE"


class PoolStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"


class OperationType(str, Enum):
    CROP = "CROP"
    LIVESTOCK = "LIVESTOCK"
    DAIRY = "DAIRY"
    RANCH = "RANCH"
    MIXED = "MIXED"


class UwStatus(str, Enum):
    DRAFT = "DRAFT"
    RATED = "RATED"
    REFERRED = "REFERRED"
    BOUND = "BOUND"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class ComplianceStatus(str, Enum):
    NOT_INSPECTED = "NOT_INSPECTED"
    RECS_OPEN = "RECS_OPEN"
    RECS_OVERDUE = "RECS_OVERDUE"
    SUSPENDED = "SUSPENDED"
    COMPLIANT = "COMPLIANT"


class ReferralReasonCode(str, Enum):
    TIV_ABOVE_LIMIT = "TIV_ABOVE_LIMIT"
    AGRITOURISM_VISITORS = "AGRITOURISM_VISITORS"
    CAT_UTILIZATION_HIGH = "CAT_UTILIZATION_HIGH"
    HAZARD_SCORE_HIGH = "HAZARD_SCORE_HIGH"


class ItemClass(str, Enum):
    DWELLING = "DWELLING"
    FARM_STRUCTURE = "FARM_STRUCTURE"
    EQUIPMENT = "EQUIPMENT"
    STORED_CROP = "STORED_CROP"
    HAY = "HAY"
    INPUTS = "INPUTS"


class ValuationBasis(str, Enum):
    RC = "RC"
    ACV = "ACV"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class ScheduledItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class Species(str, Enum):
    CATTLE = "CATTLE"
    SWINE = "SWINE"
    POULTRY = "POULTRY"
    SHEEP = "SHEEP"
    EQUINE = "EQUINE"


class LimitBasis(str, Enum):
    PER_HEAD = "PER_HEAD"
    BLANKET = "BLANKET"


class PerilScope(str, Enum):
    FULL_PERIL = "FULL_PERIL"
    NAMED_PERIL = "NAMED_PERIL"
    CATASTROPHE_ONLY = "CATASTROPHE_ONLY"


class ExposureType(str, Enum):
    GENERAL_FARM = "GENERAL_FARM"
    CUSTOM_FARMING = "CUSTOM_FARMING"
    AGRITOURISM = "AGRITOURISM"
    ROADSIDE_STAND = "ROADSIDE_STAND"


class FormCode(str, Enum):
    POLLUTION_BUYBACK = "POLLUTION_BUYBACK"
    CHEMICAL_APPLICATION_BUYBACK = "CHEMICAL_APPLICATION_BUYBACK"
    AGRITOURISM_LIABILITY = "AGRITOURISM_LIABILITY"
    PEAK_SEASON_INCREASE = "PEAK_SEASON_INCREASE"


class EndorsementStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    RESCINDED = "RESCINDED"


class CoordinationStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_PROOF = "PENDING_PROOF"
    VERIFIED = "VERIFIED"
    LAPSED = "LAPSED"


class InspectionType(str, Enum):
    INITIAL = "INITIAL"
    RE_INSPECTION = "RE_INSPECTION"
    LOSS_TRIGGERED = "LOSS_TRIGGERED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class RecommendationStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    WAIVED = "WAIVED"
    OVERDUE = "OVERDUE"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class TxnType(str, Enum):
    BASE_PROPERTY = "BASE_PROPERTY"
    BASE_LIVESTOCK = "BASE_LIVESTOCK"
    BASE_LIABILITY = "BASE_LIABILITY"
    CAT_LOAD = "CAT_LOAD"
    ENDORSEMENT_ADD = "ENDORSEMENT_ADD"
    ENDORSEMENT_REMOVE = "ENDORSEMENT_REMOVE"
    REVERSAL = "REVERSAL"


class ReasonCode(str, Enum):
    RATING = "RATING"
    RATING_REVERT = "RATING_REVERT"
    ENDORSEMENT_APPROVAL = "ENDORSEMENT_APPROVAL"
    ENDORSEMENT_RESCISSION = "ENDORSEMENT_RESCISSION"
    COMPLIANCE_SUSPENSION = "COMPLIANCE_SUSPENSION"
    COMPLIANCE_REINSTATEMENT = "COMPLIANCE_REINSTATEMENT"
    POLICY_DECLINE = "POLICY_DECLINE"
    POLICY_CANCELLATION = "POLICY_CANCELLATION"


class EndorsementDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ReferralDecision(str, Enum):
    APPROVE = "APPROVE"
    RETURN = "RETURN"
    DECLINE = "DECLINE"


class ReviewDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    WAIVE = "WAIVE"


# ---------------------------------------------------------------------------
# Entity shapes. Rows carry id / created_at / updated_at / version (PRD §2.4);
# the premium ledger entry is the one exception and carries only id and
# created_at.
# ---------------------------------------------------------------------------


class Agent(TypedDict):
    id: str
    agency_name: str
    license_state: str
    appointment_status: str
    authority_limit_cents: int
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict):
    id: str
    full_name: str
    region_code: str
    status: str
    daily_capacity_minutes: int
    created_at: str
    updated_at: str
    version: int


class CatCapacityPool(TypedDict):
    id: str
    zone_code: str
    peril: str
    participation_pct: float
    total_capacity_cents: int
    status: str
    reserved_cents: int
    committed_cents: int
    available_cents: int
    created_at: str
    updated_at: str
    version: int


class FarmAccount(TypedDict):
    id: str
    agent_id: str
    legal_name: str
    state_code: str
    county_name: str
    cat_zone_code: str
    acreage: int
    operation_type: str
    created_at: str
    updated_at: str
    version: int


class FarmPolicy(TypedDict):
    id: str
    account_id: str
    term_start_date: str
    term_end_date: str
    deductible_cents: int
    uw_status: str
    compliance_status: str
    property_premium_cents: int
    livestock_premium_cents: int
    liability_premium_cents: int
    endorsement_premium_cents: int
    base_premium_cents: int
    cat_load_cents: int
    total_premium_cents: int
    exposed_tiv_cents: int
    rating_valuation_date: Optional[str]
    quote_expires_at: Optional[str]
    referred_at: Optional[str]
    referred_by_user_id: Optional[str]
    referral_reason_code: Optional[str]
    bound_at: Optional[str]
    bound_by_user_id: Optional[str]
    closure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScheduledItem(TypedDict):
    id: str
    policy_id: str
    item_class: str
    description: str
    valuation_basis: str
    stated_value_cents: int
    age_years: int
    condition_grade: str
    peak_season_value_cents: Optional[int]
    peak_season_start_month: Optional[int]
    peak_season_end_month: Optional[int]
    status: str
    insured_value_cents: int
    valued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LivestockGroup(TypedDict):
    id: str
    policy_id: str
    species: str
    head_count: int
    per_head_value_cents: int
    limit_basis: str
    blanket_limit_cents: Optional[int]
    peril_scope: str
    covered_limit_cents: int
    created_at: str
    updated_at: str
    version: int


class LiabilityExposure(TypedDict):
    id: str
    policy_id: str
    exposure_type: str
    annual_receipts_cents: int
    annual_visitor_count: Optional[int]
    exposure_premium_cents: int
    created_at: str
    updated_at: str
    version: int


class Endorsement(TypedDict):
    id: str
    policy_id: str
    form_code: str
    sublimit_cents: int
    requested_effective_date: str
    status: str
    premium_cents: int
    requires_inspection: bool
    decision_note: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LaborProfile(TypedDict):
    id: str
    policy_id: str
    full_time_count: int
    seasonal_count: int
    migrant_h2a_count: int
    labor_exposure_units: float
    wc_required: bool
    wc_carrier_name: Optional[str]
    wc_policy_number: Optional[str]
    wc_expiry_date: Optional[str]
    coordination_status: str
    verified_at: Optional[str]
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    policy_id: str
    inspector_id: str
    inspection_type: str
    scheduled_for: str
    duration_minutes: int
    status: str
    completed_at: Optional[str]
    findings_summary: Optional[str]
    hazard_score: int
    recommendation_count: int
    created_at: str
    updated_at: str
    version: int


class Recommendation(TypedDict):
    id: str
    inspection_id: str
    sequence_no: int
    severity: str
    description: str
    due_date: str
    status: str
    evidence_note: Optional[str]
    completed_date: Optional[str]
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CatReservation(TypedDict):
    id: str
    policy_id: str
    pool_id: str
    peril: str
    amount_cents: int
    utilization_at_rating: float
    scarcity_factor: float
    load_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PremiumTransaction(TypedDict):
    """A ledger entry is immutable, so it carries only id and created_at —
    both updated_at and version are absent from its representation."""

    id: str
    policy_id: str
    sequence_no: int
    txn_type: str
    reason_code: str
    amount_cents: int
    reverses_sequence_no: Optional[int]
    created_at: str


class ComplianceSweepResult(TypedDict):
    policies_scanned: int
    recommendations_marked_overdue: int
    policies_marked_recs_overdue: int
    policies_suspended: int
    labor_profiles_lapsed: int


__all__ = [
    "UserRole",
    "AppointmentStatus",
    "InspectorStatus",
    "Peril",
    "PoolStatus",
    "OperationType",
    "UwStatus",
    "ComplianceStatus",
    "ReferralReasonCode",
    "ItemClass",
    "ValuationBasis",
    "ConditionGrade",
    "ScheduledItemStatus",
    "Species",
    "LimitBasis",
    "PerilScope",
    "ExposureType",
    "FormCode",
    "EndorsementStatus",
    "CoordinationStatus",
    "InspectionType",
    "InspectionStatus",
    "Severity",
    "RecommendationStatus",
    "ReservationStatus",
    "TxnType",
    "ReasonCode",
    "EndorsementDecision",
    "ReferralDecision",
    "ReviewDecision",
    "Agent",
    "Inspector",
    "CatCapacityPool",
    "FarmAccount",
    "FarmPolicy",
    "ScheduledItem",
    "LivestockGroup",
    "LiabilityExposure",
    "Endorsement",
    "LaborProfile",
    "Inspection",
    "Recommendation",
    "CatReservation",
    "PremiumTransaction",
    "ComplianceSweepResult",
    "List",
]
