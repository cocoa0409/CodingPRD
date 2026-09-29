"""Domain types for the Flood Zone Determination API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.  Every entity in this API carries the full common-field set
(``id``, ``created_at``, ``updated_at``, ``version``) because PRD 2.4 states
that all eleven entity types carry it.
"""
from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------
# Role enum (PRD 2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PROVIDER_ANALYST = "ProviderAnalyst"
    PROVIDER_REVIEWER = "ProviderReviewer"
    AGENCY_OFFICER = "AgencyOfficer"
    LENDER = "Lender"
    BORROWER = "Borrower"


ALL_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class ParticipationStatus(str, Enum):
    REGULAR = "REGULAR"
    EMERGENCY = "EMERGENCY"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    NON_PARTICIPATING = "NON_PARTICIPATING"
    WITHDRAWN = "WITHDRAWN"


class CoverageAvailability(str, Enum):
    FULL = "FULL"
    FULL_WITH_SURCHARGE = "FULL_WITH_SURCHARGE"
    EMERGENCY_LIMITS_ONLY = "EMERGENCY_LIMITS_ONLY"
    UNAVAILABLE = "UNAVAILABLE"


class PanelRevisionStatus(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    APPEAL_OPEN = "APPEAL_OPEN"
    LFD_ISSUED = "LFD_ISSUED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class PanelZoneCode(str, Enum):
    A = "A"
    AE = "AE"
    AO = "AO"
    AH = "AH"
    VE = "VE"


class DeterminationZoneCode(str, Enum):
    A = "A"
    AE = "AE"
    AO = "AO"
    AH = "AH"
    VE = "VE"
    X = "X"


class GeocodeMethod(str, Enum):
    ROOFTOP = "ROOFTOP"
    PARCEL_CENTROID = "PARCEL_CENTROID"
    ZIP_CENTROID = "ZIP_CENTROID"
    FAILED = "FAILED"


class GeocodeStatus(str, Enum):
    GEOCODED = "GEOCODED"
    UNRESOLVED = "UNRESOLVED"


class OccupancyType(str, Enum):
    SINGLE_FAMILY = "SINGLE_FAMILY"
    TWO_TO_FOUR_FAMILY = "TWO_TO_FOUR_FAMILY"
    OTHER_RESIDENTIAL = "OTHER_RESIDENTIAL"
    NON_RESIDENTIAL = "NON_RESIDENTIAL"


class FoundationType(str, Enum):
    SLAB = "SLAB"
    CRAWLSPACE = "CRAWLSPACE"
    BASEMENT = "BASEMENT"
    PIER_PILE = "PIER_PILE"


class MonitoringStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class InsuranceStatus(str, Enum):
    NONE = "NONE"
    NOT_REQUIRED = "NOT_REQUIRED"
    BORROWER_PROVIDED = "BORROWER_PROVIDED"
    FORCE_PLACED = "FORCE_PLACED"


class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    NOTICE_DUE = "NOTICE_DUE"
    NOTICE_PENDING = "NOTICE_PENDING"
    FORCE_PLACE_ELIGIBLE = "FORCE_PLACE_ELIGIBLE"
    FORCE_PLACED = "FORCE_PLACED"
    REVIEW_PENDING = "REVIEW_PENDING"
    COVERAGE_UNAVAILABLE = "COVERAGE_UNAVAILABLE"


class DeterminationType(str, Enum):
    ORIGINATION = "ORIGINATION"
    LIFE_OF_LOAN_REVIEW = "LIFE_OF_LOAN_REVIEW"
    DISPUTE_REVISION = "DISPUTE_REVISION"


class DeterminationStatus(str, Enum):
    ISSUED = "ISSUED"
    FLAGGED_FOR_REVIEW = "FLAGGED_FOR_REVIEW"
    UNDER_DISPUTE = "UNDER_DISPUTE"
    SUPERSEDED = "SUPERSEDED"


class PositionClass(str, Enum):
    INSIDE = "INSIDE"
    OUTSIDE = "OUTSIDE"
    INDETERMINATE = "INDETERMINATE"


class FlaggedReason(str, Enum):
    MAP_REVISION = "MAP_REVISION"
    GEOCODE_CORRECTION = "GEOCODE_CORRECTION"


class DisputeStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    JOINT_AGENCY_REVIEW = "JOINT_AGENCY_REVIEW"
    SUSTAINED = "SUSTAINED"
    DENIED = "DENIED"


class DisputeBasis(str, Enum):
    ELEVATION_ABOVE_BFE = "ELEVATION_ABOVE_BFE"
    MAP_PANEL_STALE = "MAP_PANEL_STALE"
    GEOCODE_ERROR = "GEOCODE_ERROR"
    STRUCTURE_LOCATION = "STRUCTURE_LOCATION"


class ProviderRecommendation(str, Enum):
    UPHOLD = "UPHOLD"
    REVISE = "REVISE"


class AgencyConcurrence(str, Enum):
    CONCUR = "CONCUR"
    NON_CONCUR = "NON_CONCUR"


class DisputeResolution(str, Enum):
    REVISED_BY_CONCURRENCE = "REVISED_BY_CONCURRENCE"
    REVISED_BY_AGENCY_OVERRIDE = "REVISED_BY_AGENCY_OVERRIDE"
    UPHELD_BY_CONCURRENCE = "UPHELD_BY_CONCURRENCE"
    UPHELD_BY_AGENCY_OVERRIDE = "UPHELD_BY_AGENCY_OVERRIDE"


class CertificateStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class CertificateRejectionReason(str, Enum):
    DATUM_MISMATCH = "DATUM_MISMATCH"
    SURVEY_STALE = "SURVEY_STALE"
    MISSING_MACHINERY_ELEVATION = "MISSING_MACHINERY_ELEVATION"


class Datum(str, Enum):
    NAVD88 = "NAVD88"
    NGVD29 = "NGVD29"


class AmendmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED_TO_AGENCY = "SUBMITTED_TO_AGENCY"
    ADDITIONAL_DATA_REQUESTED = "ADDITIONAL_DATA_REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class AmendmentRequestType(str, Enum):
    LOMA = "LOMA"
    LOMR_F = "LOMR_F"


class FeeTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class NoticeType(str, Enum):
    MANDATORY_PURCHASE = "MANDATORY_PURCHASE"
    FORCE_PLACEMENT_WARNING = "FORCE_PLACEMENT_WARNING"
    COVERAGE_UNAVAILABLE = "COVERAGE_UNAVAILABLE"
    RE_DETERMINATION = "RE_DETERMINATION"


class NoticeStatus(str, Enum):
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


# --------------------------------------------------------------------------
# Entity TypedDicts — every entity carries id/created_at/updated_at/version
# --------------------------------------------------------------------------
class Community(TypedDict):
    id: str
    community_id_code: str
    name: str
    state_code: str
    participation_status: str
    cbrs_flag: bool
    probation_surcharge_cents: int
    coverage_availability: str
    last_participation_change_at: str
    active_folio_count: int
    created_at: str
    updated_at: str
    version: int


class Lender(TypedDict):
    id: str
    name: str
    contact_email: str
    force_placement_authorized_flag: bool
    escrow_servicing_flag: bool
    open_force_placement_count: int
    created_at: str
    updated_at: str
    version: int


class MapPanel(TypedDict):
    id: str
    community_id: str
    map_panel_number: str
    revision_sequence: int
    supersedes_panel_id: Optional[str]
    revision_status: str
    zone_code: str
    base_flood_elevation_ft: Optional[float]
    sfha_boundary_shift_ft: float
    horizontal_uncertainty_ft: float
    effective_date: str
    appeal_period_end_date: Optional[str]
    lfd_issued_at: Optional[str]
    superseded_at: Optional[str]
    revision_round: int
    study_case_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    community_id: str
    street_address: str
    city: str
    postal_code: str
    map_panel_number: str
    latitude: float
    longitude: float
    geocode_method: str
    geocode_confidence_score: float
    geocode_status: str
    geocode_buffer_ft: float
    geocode_corrected_count: int
    structure_count: int
    created_at: str
    updated_at: str
    version: int


class Structure(TypedDict):
    id: str
    property_id: str
    structure_label: str
    occupancy_type: str
    foundation_type: str
    replacement_cost_cents: int
    sfha_offset_ft: float
    post_firm_flag: bool
    fill_placed_flag: bool
    lowest_floor_elevation_ft: Optional[float]
    lowest_adjacent_grade_ft: Optional[float]
    elevation_source_certificate_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LoanFolio(TypedDict):
    id: str
    lender_id: str
    property_id: str
    loan_number: str
    borrower_user_id: str
    principal_balance_cents: int
    escrow_balance_cents: int
    initial_escrow_balance_cents: int
    policy_anniversary_date: str
    monitoring_status: str
    insurance_status: str
    current_determination_id: Optional[str]
    required_coverage_cents: int
    reported_coverage_cents: int
    uninsured_exposure_cents: int
    force_placed_premium_cents: int
    force_placed_at: Optional[str]
    force_placed_coverage_days: int
    cumulative_earned_premium_cents: int
    open_notice_count: int
    pending_redetermination_count: int
    compliance_posture: str
    created_at: str
    updated_at: str
    version: int


class Determination(TypedDict):
    id: str
    loan_folio_id: str
    structure_id: str
    map_panel_id: str
    determination_type: str
    status: str
    position_class: str
    zone_code: str
    sfha_flag: bool
    base_flood_elevation_ft: Optional[float]
    freeboard_ft: Optional[float]
    mandatory_purchase_flag: bool
    issued_by_user_id: str
    supersedes_determination_id: Optional[str]
    superseded_at: Optional[str]
    flagged_reason: Optional[str]
    issued_at: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    determination_id: str
    basis: str
    borrower_statement: str
    asserted_sfha_offset_ft: float
    status: str
    round_number: int
    provider_recommendation: Optional[str]
    provider_reviewed_by_user_id: Optional[str]
    agency_concurrence: Optional[str]
    agency_reviewed_by_user_id: Optional[str]
    resolution: Optional[str]
    revised_determination_id: Optional[str]
    filed_at: str
    decision_due_at: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ElevationCertificate(TypedDict):
    id: str
    structure_id: str
    dispute_id: Optional[str]
    reference_panel_id: str
    surveyor_license_number: str
    survey_date: str
    datum: str
    raw_lowest_floor_elevation_ft: float
    raw_lowest_adjacent_grade_ft: float
    machinery_elevation_ft: Optional[float]
    converted_lowest_floor_ft: float
    converted_lag_ft: float
    freeboard_ft: Optional[float]
    lag_freeboard_ft: Optional[float]
    status: str
    rejection_reason: Optional[str]
    submitted_by_user_id: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MapAmendmentRequest(TypedDict):
    id: str
    determination_id: str
    elevation_certificate_id: str
    request_type: str
    expedite_flag: bool
    status: str
    resubmission_count: int
    base_review_fee_cents: int
    fee_tier: str
    expedite_surcharge_cents: int
    total_fee_cents: int
    agency_case_number: Optional[str]
    additional_data_note: Optional[str]
    prepared_by_user_id: str
    submitted_at: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceNotice(TypedDict):
    id: str
    loan_folio_id: str
    determination_id: str
    notice_type: str
    annual_premium_rate_cents: int
    status: str
    sent_at: str
    response_deadline_at: str
    required_coverage_snapshot_cents: int
    estimated_force_place_premium_cents: int
    acknowledged_at: Optional[str]
    acknowledged_by_role: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
