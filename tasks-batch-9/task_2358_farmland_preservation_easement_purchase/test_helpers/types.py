"""Domain types for the Farmland Preservation Easement Purchase API.

Entity TypedDicts, status enumerations and the role enumeration, all named
exactly as the PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    LANDOWNER = "Landowner"
    ACQUISITION_OFFICER = "AcquisitionOfficer"
    APPRAISAL_REVIEWER = "AppraisalReviewer"
    APPRAISER = "Appraiser"
    STEWARDSHIP_MONITOR = "StewardshipMonitor"


# ---------------------------------------------------------------------------
# Status enumerations
# ---------------------------------------------------------------------------


class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class AmendmentPolicy(str, Enum):
    STRICT = "STRICT"
    CONDITIONAL = "CONDITIONAL"


class RoundStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    SELECTED = "SELECTED"
    CLOSED = "CLOSED"


class ScoreBasis(str, Enum):
    RECEIPT_BASIS = "RECEIPT_BASIS"
    ROUND_CLOSE_BASIS = "ROUND_CLOSE_BASIS"


class SourceLevel(str, Enum):
    FEDERAL = "FEDERAL"
    STATE = "STATE"
    LOCAL = "LOCAL"


class SourceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FULLY_OBLIGATED = "FULLY_OBLIGATED"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"


class LandownerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ParcelStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    UNDER_APPLICATION = "UNDER_APPLICATION"
    ENCUMBERED = "ENCUMBERED"
    WITHDRAWN = "WITHDRAWN"


class ApplicationStatus(str, Enum):
    RECEIVED = "RECEIVED"
    RANKED = "RANKED"
    NOT_SELECTED = "NOT_SELECTED"
    OFFER_ISSUED = "OFFER_ISSUED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    CLOSED_RECORDED = "CLOSED_RECORDED"
    WITHDRAWN = "WITHDRAWN"
    LAPSED = "LAPSED"


class ClosingStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING_REQUIREMENTS = "PENDING_REQUIREMENTS"
    BLOCKED = "BLOCKED"
    CLEARED = "CLEARED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class FundingPlanStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    FUNDED = "FUNDED"
    UNDERFUNDED = "UNDERFUNDED"
    OBLIGATED = "OBLIGATED"
    DISBURSED = "DISBURSED"
    RELEASED = "RELEASED"


class AppraisalStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"


class AppraisalMethod(str, Enum):
    PAIRED_SALES = "PAIRED_SALES"
    INCOME_CAPITALIZATION = "INCOME_CAPITALIZATION"


class AppraisalBasis(str, Enum):
    CERTIFIED_APPRAISAL_BASIS = "CERTIFIED_APPRAISAL_BASIS"


class NegotiationKind(str, Enum):
    OFFER = "OFFER"
    COUNTER = "COUNTER"
    ACCEPTANCE = "ACCEPTANCE"
    EXPIRATION = "EXPIRATION"
    WITHDRAWAL = "WITHDRAWAL"


class OfferStructure(str, Enum):
    FULL_PURCHASE = "FULL_PURCHASE"
    BARGAIN_SALE = "BARGAIN_SALE"
    INSTALLMENT = "INSTALLMENT"


class CommitmentStatus(str, Enum):
    RESERVED = "RESERVED"
    OBLIGATED = "OBLIGATED"
    DISBURSED = "DISBURSED"
    LAPSED = "LAPSED"
    RELEASED = "RELEASED"


class LapseReason(str, Enum):
    SOURCE_FULLY_OBLIGATED = "SOURCE_FULLY_OBLIGATED"
    SOURCE_SUSPENDED = "SOURCE_SUSPENDED"
    SOURCE_EXPIRED = "SOURCE_EXPIRED"
    PLAN_SUPERSEDED = "PLAN_SUPERSEDED"
    APPLICATION_WITHDRAWN = "APPLICATION_WITHDRAWN"
    APPLICATION_LAPSED = "APPLICATION_LAPSED"
    CLOSING_CANCELLED = "CLOSING_CANCELLED"


class RequirementType(str, Enum):
    TITLE_COMMITMENT = "TITLE_COMMITMENT"
    MORTGAGE_SUBORDINATION = "MORTGAGE_SUBORDINATION"
    BOUNDARY_SURVEY = "BOUNDARY_SURVEY"


class RequirementStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    SUBMITTED = "SUBMITTED"
    SATISFIED = "SATISFIED"
    DEFICIENT = "DEFICIENT"
    WAIVED = "WAIVED"


class EasementStatus(str, Enum):
    RECORDED = "RECORDED"
    AMENDED = "AMENDED"
    TERMINATED = "TERMINATED"


class StewardshipStatus(str, Enum):
    MONITORING_CURRENT = "MONITORING_CURRENT"
    MONITORING_DUE = "MONITORING_DUE"
    MONITORING_DELINQUENT = "MONITORING_DELINQUENT"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    VIOLATION_OPEN = "VIOLATION_OPEN"
    VIOLATION_CURED = "VIOLATION_CURED"
    VIOLATION_ESCALATED = "VIOLATION_ESCALATED"


class PermittedUse(str, Enum):
    CROP_PRODUCTION = "CROP_PRODUCTION"
    LIVESTOCK = "LIVESTOCK"
    DAIRY = "DAIRY"
    ORCHARD = "ORCHARD"
    FARM_STAND = "FARM_STAND"
    AGRITOURISM = "AGRITOURISM"
    FORESTRY = "FORESTRY"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class VisitFinding(str, Enum):
    NO_ISSUE = "NO_ISSUE"
    CONFIRMED_VIOLATION = "CONFIRMED_VIOLATION"


class ViolationType(str, Enum):
    IMPERVIOUS_EXCEEDANCE = "IMPERVIOUS_EXCEEDANCE"
    UNAUTHORIZED_SUBDIVISION = "UNAUTHORIZED_SUBDIVISION"
    PROHIBITED_USE = "PROHIBITED_USE"
    EXCESS_DWELLING = "EXCESS_DWELLING"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    CURE_PLAN_ACCEPTED = "CURE_PLAN_ACCEPTED"
    CURED = "CURED"
    ESCALATED = "ESCALATED"


class ViolationSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class AmendmentType(str, Enum):
    IMPERVIOUS_INCREASE = "IMPERVIOUS_INCREASE"
    BOUNDARY_ADJUSTMENT = "BOUNDARY_ADJUSTMENT"
    RESIDENTIAL_RIGHT_RELOCATION = "RESIDENTIAL_RIGHT_RELOCATION"


class AmendmentStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUSPENDED = "SUSPENDED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RESCINDED = "RESCINDED"


class SuspendedReason(str, Enum):
    VIOLATION_OPEN = "VIOLATION_OPEN"


class RescissionReason(str, Enum):
    SUPERSEDED_BY_NEWER_DRAFT = "SUPERSEDED_BY_NEWER_DRAFT"


# ---------------------------------------------------------------------------
# Entity TypedDicts
#
# Thirteen of the fourteen resource types carry id + created_at + updated_at +
# version (PRD §2.4). NegotiationRound is append-only and carries only
# id + created_at.
# ---------------------------------------------------------------------------


class PreservationProgram(TypedDict):
    id: str
    name: str
    soil_weight: float
    size_weight: float
    contiguity_weight: float
    pressure_weight: float
    min_composite_score: float
    max_negotiation_rounds: int
    local_match_min_pct: float
    federal_max_share_pct: float
    impervious_allowance_pct: float
    amendment_policy: str
    monitoring_interval_days: int
    monitoring_grace_days: int
    appraisal_engagement_buffer_days: int
    status: str
    total_preserved_acres: float
    created_at: str
    updated_at: str
    version: int


class FundingRound(TypedDict):
    id: str
    program_id: str
    round_label: str
    opens_on: str
    closes_on: str
    pool_cents: int
    status: str
    score_basis: Optional[str]
    ranked_at: Optional[str]
    application_count: int
    selected_count: int
    created_at: str
    updated_at: str
    version: int


class FundingSource(TypedDict):
    id: str
    program_id: str
    source_name: str
    level: str
    authorized_cents: int
    obligation_window_start: str
    obligation_window_end: str
    max_share_pct: float
    priority_order: int
    requires_match: bool
    match_ratio: float
    fully_obligated_threshold_pct: float
    status: str
    committed_cents: int
    reserved_cents: int
    disbursed_cents: int
    available_cents: int
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Landowner(TypedDict):
    id: str
    legal_name: str
    mailing_state: str
    tax_id_last4: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Parcel(TypedDict):
    id: str
    landowner_id: str
    county: str
    acres: float
    prime_soil_acres: float
    statewide_important_soil_acres: float
    contiguous_preserved_acres: float
    road_frontage_feet: int
    sewer_available: bool
    zoning_min_lot_acres: float
    baseline_dwelling_rights: int
    unrestricted_value_cents: int
    restricted_value_cents: int
    mortgage_lienholder_name: Optional[str]
    status: str
    soil_quality_score: float
    development_pressure_score: float
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    funding_round_id: str
    parcel_id: str
    landowner_id: str
    requested_price_cents: int
    status: str
    closing_status: str
    funding_plan_status: str
    contiguity_acres_at_receipt: float
    preliminary_easement_value_cents: int
    certified_easement_value_cents: Optional[int]
    composite_score: Optional[float]
    rank_position: Optional[int]
    negotiation_round_count: int
    structure: Optional[str]
    donation_pct: Optional[float]
    installment_years: Optional[int]
    current_offer_cents: Optional[int]
    current_offer_expires_on: Optional[str]
    last_counter_cents: Optional[int]
    proposed_price_cents: Optional[int]
    agreed_price_cents: Optional[int]
    offer_issued_by_user_id: Optional[str]
    donation_cents: Optional[int]
    bargain_sale_price_cents: Optional[int]
    admin_fee_cents: Optional[int]
    total_program_cost_cents: Optional[int]
    first_installment_cents: Optional[int]
    final_installment_cents: Optional[int]
    installment_interest_total_cents: Optional[int]
    funded_cost_cents: Optional[int]
    requirement_total: int
    requirement_satisfied_count: int
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appraisal(TypedDict):
    id: str
    application_id: str
    appraiser_user_id: str
    appraiser_firm: str
    engagement_start: str
    engagement_end: str
    method: str
    basis: str
    status: str
    submission_count: int
    engaged_by_user_id: str
    unrestricted_value_cents: Optional[int]
    restricted_value_cents: Optional[int]
    easement_value_cents: Optional[int]
    certified_by_user_id: Optional[str]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NegotiationRound(TypedDict):
    """Append-only log entry: carries id and created_at only (PRD §2.4)."""

    id: str
    application_id: str
    round_index: int
    kind: str
    amount_cents: Optional[int]
    offer_expires_on: Optional[str]
    actor_role: str
    actor_user_id: str
    rationale: Optional[str]
    created_at: str


class FundingCommitment(TypedDict):
    id: str
    application_id: str
    funding_source_id: str
    amount_cents: int
    sweep_order: int
    absorbed_remainder_cents: int
    window_start: str
    window_end: str
    status: str
    lapse_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClosingRequirement(TypedDict):
    id: str
    application_id: str
    requirement_type: str
    status: str
    submitted_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    deficiency_note: Optional[str]
    waiver_reason: Optional[str]
    lienholder_name: Optional[str]
    surveyed_acres: Optional[float]
    exception_count: int
    created_at: str
    updated_at: str
    version: int


class Easement(TypedDict):
    id: str
    parcel_id: str
    application_id: str
    recorded_on: str
    protected_acres: float
    residential_rights_retained: int
    residential_rights_extinguished: int
    subdivision_permitted: bool
    permitted_uses: List[str]
    status: str
    stewardship_status: str
    compliance_status: str
    stewardship_hold: bool
    impervious_allowance_sqft: int
    impervious_used_sqft: int
    last_monitored_on: Optional[str]
    next_monitoring_due_on: str
    open_violation_count: int
    pending_amendment_count: int
    amendment_count: int
    created_at: str
    updated_at: str
    version: int


class MonitoringVisit(TypedDict):
    id: str
    easement_id: str
    window_start: str
    window_end: str
    status: str
    completed_at: Optional[str]
    observed_impervious_sqft: Optional[int]
    finding: Optional[str]
    cancellation_reason: Optional[str]
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict):
    id: str
    easement_id: str
    monitoring_visit_id: Optional[str]
    violation_type: str
    severity: str
    excess_sqft: int
    status: str
    opened_on: str
    cure_deadline_on: str
    cure_plan_note: Optional[str]
    cured_on: Optional[str]
    escalated_on: Optional[str]
    verification_note: Optional[str]
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Amendment(TypedDict):
    id: str
    easement_id: str
    amendment_type: str
    net_conservation_benefit_cents: int
    requested_impervious_sqft: Optional[int]
    residential_rights_delta: int
    status: str
    applied_rights_delta: int
    applied_impervious_sqft: Optional[int]
    suspended_reason: Optional[str]
    decision_reason: Optional[str]
    rescission_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
