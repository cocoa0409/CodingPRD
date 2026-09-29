"""Domain types: entity TypedDicts, status enums, role enum.

Field names match the PRD exactly.
"""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CLAIMANT = "Claimant"
    WATER_RIGHTS_ANALYST = "WaterRightsAnalyst"
    HEARING_OFFICER = "HearingOfficer"
    DECISION_AUTHORITY = "DecisionAuthority"
    BASIN_ADJUDICATOR = "BasinAdjudicator"


ALL_ROLES = [r.value for r in UserRole]


# ---------------------------------------------------------------------------
# Input enums
# ---------------------------------------------------------------------------
class EntityType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    IRRIGATION_DISTRICT = "IRRIGATION_DISTRICT"
    MUNICIPALITY = "MUNICIPALITY"
    TRIBE = "TRIBE"


class StandingStatus(str, Enum):
    IN_GOOD_STANDING = "IN_GOOD_STANDING"
    DELINQUENT = "DELINQUENT"
    BARRED = "BARRED"


class PurposeOfUse(str, Enum):
    IRRIGATION = "IRRIGATION"
    MUNICIPAL = "MUNICIPAL"
    STOCKWATER = "STOCKWATER"
    INDUSTRIAL = "INDUSTRIAL"
    INSTREAM_FLOW = "INSTREAM_FLOW"


class VerificationSource(str, Enum):
    METER = "METER"
    AERIAL_IMAGERY = "AERIAL_IMAGERY"
    AFFIDAVIT = "AFFIDAVIT"
    NONE = "NONE"


class HcuMethod(str, Enum):
    DIVERSION_BASED = "DIVERSION_BASED"
    CIR_BASED = "CIR_BASED"


class ApplicationType(str, Enum):
    CHANGE_OF_USE = "CHANGE_OF_USE"
    POINT_OF_DIVERSION_CHANGE = "POINT_OF_DIVERSION_CHANGE"
    PLACE_OF_USE_CHANGE = "PLACE_OF_USE_CHANGE"
    COMBINED = "COMBINED"


class InjuryMethod(str, Enum):
    INSTANTANEOUS_DEPLETION = "INSTANTANEOUS_DEPLETION"
    SEASONAL_AVERAGE = "SEASONAL_AVERAGE"


class ProtestBasis(str, Enum):
    INJURY_TO_SENIOR_RIGHT = "INJURY_TO_SENIOR_RIGHT"
    PUBLIC_INTEREST = "PUBLIC_INTEREST"
    ENLARGEMENT = "ENLARGEMENT"
    NO_BENEFICIAL_USE = "NO_BENEFICIAL_USE"


class ProtestTrack(str, Enum):
    NEGOTIATION = "NEGOTIATION"
    HEARING = "HEARING"


class ProtestOutcome(str, Enum):
    STIPULATE = "STIPULATE"
    DISMISS = "DISMISS"


class Disposition(str, Enum):
    APPROVE = "APPROVE"
    APPROVE_WITH_CONDITIONS = "APPROVE_WITH_CONDITIONS"
    DENY = "DENY"


class ConditionType(str, Enum):
    DRY_YEAR_FORBEARANCE = "DRY_YEAR_FORBEARANCE"
    MEASUREMENT_DEVICE = "MEASUREMENT_DEVICE"
    RETURN_FLOW_MAINTENANCE = "RETURN_FLOW_MAINTENANCE"
    MITIGATION_PAYMENT = "MITIGATION_PAYMENT"


class ConditionSource(str, Enum):
    DECISION = "DECISION"
    HEARING_RESOLUTION = "HEARING_RESOLUTION"


class ValuationMethod(str, Enum):
    PRO_RATA_DAILY = "PRO_RATA_DAILY"
    SEASON_BLOCK = "SEASON_BLOCK"


class VerificationOutcome(str, Enum):
    FIELD_VERIFIED = "FIELD_VERIFIED"
    DISPUTED = "DISPUTED"


# ---------------------------------------------------------------------------
# Derived / lifecycle enums
# ---------------------------------------------------------------------------
class WaterRightStatus(str, Enum):
    UNADJUDICATED = "UNADJUDICATED"
    ACTIVE = "ACTIVE"
    ENCUMBERED = "ENCUMBERED"
    PARTIALLY_TRANSFERRED = "PARTIALLY_TRANSFERRED"
    SUSPENDED = "SUSPENDED"
    FORFEITED = "FORFEITED"


class ForfeitureRiskBand(str, Enum):
    LOW = "LOW"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"


class PointOfDiversionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    AUTHORIZED = "AUTHORIZED"
    RETIRED = "RETIRED"


class HcuStudyStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    SUPERSEDED = "SUPERSEDED"


class TransferApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PROTEST_PERIOD = "PROTEST_PERIOD"
    UNDER_PROTEST = "UNDER_PROTEST"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    READY_FOR_DECISION = "READY_FOR_DECISION"
    APPROVED = "APPROVED"
    APPROVED_WITH_CONDITIONS = "APPROVED_WITH_CONDITIONS"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class InjuryAnalysisStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class ProtestStatus(str, Enum):
    FILED = "FILED"
    IN_NEGOTIATION = "IN_NEGOTIATION"
    IN_HEARING = "IN_HEARING"
    RESOLVED_STIPULATED = "RESOLVED_STIPULATED"
    DISMISSED = "DISMISSED"
    WITHDRAWN = "WITHDRAWN"


class ApprovalConditionStatus(str, Enum):
    IMPOSED = "IMPOSED"
    SATISFIED = "SATISFIED"
    VIOLATED = "VIOLATED"
    RELEASED = "RELEASED"


class PaymentStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    OUTSTANDING = "OUTSTANDING"
    PAID = "PAID"
    REVERSED = "REVERSED"


class AccountPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class LeaseStatus(str, Enum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DocketPhase(str, Enum):
    OPEN_FOR_CLAIMS = "OPEN_FOR_CLAIMS"
    EXAMINATION = "EXAMINATION"
    OBJECTION_PERIOD = "OBJECTION_PERIOD"
    DECREE_ENTERED = "DECREE_ENTERED"
    CLOSED = "CLOSED"


class ClaimFilingStatus(str, Enum):
    FILED = "FILED"
    EXAMINED = "EXAMINED"
    OBJECTED = "OBJECTED"
    DECREED = "DECREED"


class ClaimVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    FIELD_VERIFIED = "FIELD_VERIFIED"
    DISPUTED = "DISPUTED"


# ---------------------------------------------------------------------------
# Entity shapes
#
# PRD §2.5: every persisted resource carries `id` and `created_at`; almost
# every resource additionally carries `updated_at` and `version`.
# `BeneficialUseRecord` is the single exception and carries neither.
# ---------------------------------------------------------------------------
class Claimant(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    entity_type: str
    standing_status: str
    outstanding_fee_balance_usd: float
    open_application_count: int
    created_at: str
    updated_at: str
    version: int


class WaterRight(TypedDict):
    id: str
    claimant_id: str
    right_number: str
    priority_date: str
    source_stream_code: str
    purpose_of_use: str
    place_of_use_acres: float
    authorized_diversion_af: float
    authorized_rate_cfs: float
    bank_enrolled: bool
    status: str
    certified_hcu_af: float
    encumbered_af: float
    transferred_away_af: float
    transferable_af: float
    forfeiture_risk_score: float
    forfeiture_risk_band: str
    consecutive_nonuse_years: int
    pending_review_count: int
    created_at: str
    updated_at: str
    version: int


class PointOfDiversion(TypedDict):
    id: str
    water_right_id: str
    legal_description: str
    stream_reach_code: str
    max_rate_cfs: float
    stream_miles_from_headwater: float
    status: str
    created_at: str
    updated_at: str
    version: int


class BeneficialUseRecord(TypedDict):
    """PRD §2.5 — append-only evidence: no `updated_at`, no `version`."""

    id: str
    water_right_id: str
    use_year: int
    reported_diversion_af: float
    irrigated_acres: float
    verification_source: str
    reported_by_user_id: str
    created_at: str


class HcuStudy(TypedDict):
    id: str
    water_right_id: str
    method: str
    study_period_start_year: int
    study_period_end_year: int
    qualifying_year_count: int
    average_annual_cu_af: float
    short_history_haircut_applied: bool
    transferable_cu_af: float
    status: str
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferApplication(TypedDict):
    id: str
    water_right_id: str
    hcu_study_id: str
    proposed_point_of_diversion_id: Optional[str]
    application_type: str
    requested_af: float
    proposed_purpose_of_use: Optional[str]
    proposed_place_of_use_acres: Optional[float]
    status: str
    revision_round: int
    protest_deadline: Optional[str]
    unresolved_protest_count: int
    escrowed_af: float
    mitigation_fee_total_usd: float
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InjuryAnalysis(TypedDict):
    id: str
    transfer_application_id: str
    method: str
    pod_move_miles: float
    return_flow_credit_af: float
    offset_af: float
    gross_depletion_af: float
    net_injury_af: float
    status: str
    prepared_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Protest(TypedDict):
    id: str
    transfer_application_id: str
    protestant_claimant_id: str
    claimed_injury_af: float
    basis: str
    track: Optional[str]
    status: str
    stipulated_offset_af: float
    resolution_note: Optional[str]
    resolved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ApprovalCondition(TypedDict):
    id: str
    transfer_application_id: str
    condition_type: str
    required_af: float
    compliance_due_date: Optional[str]
    source: str
    status: str
    payment_status: str
    base_fee_usd: float
    surcharge_pct: float
    admin_surcharge_usd: float
    total_fee_usd: float
    imposed_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class WaterBankAccount(TypedDict):
    id: str
    claimant_id: str
    basin_code: str
    deposited_credit_af: float
    committed_credit_af: float
    leased_out_af: float
    available_credit_af: float
    suspended_lease_count: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class LeaseAssignment(TypedDict):
    id: str
    water_bank_account_id: str
    water_right_id: str
    point_of_diversion_id: str
    lessee_name: str
    lease_start_date: str
    lease_end_date: str
    requested_af: float
    diversion_rate_cfs: float
    rental_rate_usd_per_af: float
    valuation_method: str
    status: str
    used_af: float
    settlement_credit_af: float
    suspension_count: int
    created_at: str
    updated_at: str
    version: int


class DecreeDocket(TypedDict):
    id: str
    basin_code: str
    docket_number: str
    claim_filing_deadline: str
    phase: str
    claim_count: int
    decreed_claim_count: int
    total_decreed_af: float
    created_at: str
    updated_at: str
    version: int


class AdjudicationClaim(TypedDict):
    id: str
    decree_docket_id: str
    water_right_id: str
    claimed_priority_date: str
    claimed_af: float
    filing_status: str
    verification_status: str
    examiner_recommended_af: Optional[float]
    decreed_af: Optional[float]
    objection_count: int
    priority_rank: Optional[int]
    created_at: str
    updated_at: str
    version: int
