"""Domain types for the Mine Reclamation Bonding API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them. Every stored resource in this API carries the same four common
properties (``id``, ``created_at``, ``updated_at``, ``version``), so every
TypedDict below lists all four.
"""
from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    OPERATOR = "Operator"
    PERMIT_REVIEWER = "PermitReviewer"
    BOND_SPECIALIST = "BondSpecialist"
    INSPECTOR = "Inspector"
    PROGRAM_DIRECTOR = "ProgramDirector"
    PUBLIC_PARTICIPANT = "PublicParticipant"


# --------------------------------------------------------------------------
# Operator dimensions (PRD §3.1, §3.7)
# --------------------------------------------------------------------------
class RegistryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISQUALIFIED = "DISQUALIFIED"


class SelfBondStatus(str, Enum):
    UNTESTED = "UNTESTED"
    QUALIFIED = "QUALIFIED"
    FAILED = "FAILED"
    DISQUALIFIED = "DISQUALIFIED"


class ElectedFinancialTest(str, Enum):
    NET_WORTH_TEST = "NET_WORTH_TEST"
    FIXED_ASSET_TEST = "FIXED_ASSET_TEST"


# --------------------------------------------------------------------------
# MineSite dimensions (PRD §3.1, §3.8)
# --------------------------------------------------------------------------
class SiteClass(str, Enum):
    ACTIVE_PERMITTED = "ACTIVE_PERMITTED"
    ABANDONED_LEGACY = "ABANDONED_LEGACY"


class HazardClass(str, Enum):
    H1_EXTREME = "H1_EXTREME"
    H2_HIGH = "H2_HIGH"
    H3_MODERATE = "H3_MODERATE"


class FundingStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOMINATED = "NOMINATED"
    FUNDED = "FUNDED"


class CertificationLevel(str, Enum):
    CERT_I = "CERT_I"
    CERT_II = "CERT_II"
    CERT_III = "CERT_III"


# --------------------------------------------------------------------------
# Permit dimensions (PRD §3.2, §2.8)
# --------------------------------------------------------------------------
class PermitStatus(str, Enum):
    APPLICATION_SUBMITTED = "APPLICATION_SUBMITTED"
    ISSUED = "ISSUED"
    DENIED = "DENIED"
    RECLAMATION_PHASE = "RECLAMATION_PHASE"
    TERMINATED = "TERMINATED"
    FORFEITED = "FORFEITED"


class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    NOTICE_ACTIVE = "NOTICE_ACTIVE"
    BOND_DEFICIENT = "BOND_DEFICIENT"
    CESSATION = "CESSATION"
    FORFEITURE_PENDING = "FORFEITURE_PENDING"


class BondBasis(str, Enum):
    FULL_PLAN = "FULL_PLAN"
    INCREMENTAL = "INCREMENTAL"


class PostMiningLandUse(str, Enum):
    CROPLAND = "CROPLAND"
    FORESTLAND = "FORESTLAND"
    RANGELAND = "RANGELAND"
    INDUSTRIAL = "INDUSTRIAL"
    WATER_IMPOUNDMENT = "WATER_IMPOUNDMENT"
    WILDLIFE_HABITAT = "WILDLIFE_HABITAT"


# --------------------------------------------------------------------------
# ReclamationCostEstimate / BondInstrument (PRD §3.2, §3.3)
# --------------------------------------------------------------------------
class EstimateStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class InstrumentType(str, Enum):
    SURETY = "SURETY"
    CASH = "CASH"
    COLLATERAL = "COLLATERAL"
    SELF_BOND = "SELF_BOND"


class InstrumentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REPLACED = "REPLACED"
    RELEASED = "RELEASED"
    FORFEITED = "FORFEITED"
    SUBSTITUTION_REQUIRED = "SUBSTITUTION_REQUIRED"


class SuretyNaicRating(str, Enum):
    A_PLUS_PLUS = "A_PLUS_PLUS"
    A_PLUS = "A_PLUS"
    A = "A"
    B_PLUS_PLUS = "B_PLUS_PLUS"
    B = "B"


class CollateralType(str, Enum):
    US_TREASURY = "US_TREASURY"
    MUNICIPAL_BOND = "MUNICIPAL_BOND"
    IRREVOCABLE_LOC = "IRREVOCABLE_LOC"
    REAL_PROPERTY = "REAL_PROPERTY"


# --------------------------------------------------------------------------
# BondReleaseApplication (PRD §3.5)
# --------------------------------------------------------------------------
class ReleaseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PUBLIC_NOTICE = "PUBLIC_NOTICE"
    SUSPENDED = "SUSPENDED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RESCINDED = "RESCINDED"


class ReleasePhase(str, Enum):
    PHASE_I = "PHASE_I"
    PHASE_II = "PHASE_II"
    PHASE_III = "PHASE_III"


# --------------------------------------------------------------------------
# Inspection (PRD §3.6)
# --------------------------------------------------------------------------
class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InspectionType(str, Enum):
    ROUTINE = "ROUTINE"
    RELEASE = "RELEASE"
    COMPLAINT = "COMPLAINT"
    ABATEMENT_FOLLOWUP = "ABATEMENT_FOLLOWUP"


class InspectionResult(str, Enum):
    PASS = "PASS"
    VIOLATIONS_FOUND = "VIOLATIONS_FOUND"


# --------------------------------------------------------------------------
# ViolationNotice (PRD §3.6)
# --------------------------------------------------------------------------
class NoticeStatus(str, Enum):
    ISSUED = "ISSUED"
    CESSATION_ORDERED = "CESSATION_ORDERED"
    ABATED = "ABATED"
    VACATED = "VACATED"


class PenaltyStatus(str, Enum):
    NONE = "NONE"
    ASSESSED = "ASSESSED"
    PAID = "PAID"
    VACATED = "VACATED"


class ViolationClass(str, Enum):
    NON_COMPLIANCE = "NON_COMPLIANCE"
    IMMINENT_HARM = "IMMINENT_HARM"
    PERMIT_DEFECT = "PERMIT_DEFECT"


class GoodFaithLevel(str, Enum):
    RAPID = "RAPID"
    PARTIAL = "PARTIAL"
    NONE = "NONE"


# --------------------------------------------------------------------------
# PermitRevision (PRD §3.4)
# --------------------------------------------------------------------------
class RevisionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class RevisionType(str, Enum):
    EXPANSION = "EXPANSION"
    SEQUENCE_CHANGE = "SEQUENCE_CHANGE"
    PMLU_CHANGE = "PMLU_CHANGE"


# --------------------------------------------------------------------------
# ForfeitureProceeding (PRD §3.7)
# --------------------------------------------------------------------------
class ProceedingStatus(str, Enum):
    INITIATED = "INITIATED"
    CONTESTED = "CONTESTED"
    FINAL = "FINAL"
    COMPLETED = "COMPLETED"


class InitiationReason(str, Enum):
    UNABATED_CESSATION = "UNABATED_CESSATION"
    BOND_DEFICIENCY_UNCURED = "BOND_DEFICIENCY_UNCURED"
    OPERATOR_DISQUALIFIED = "OPERATOR_DISQUALIFIED"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class Operator(TypedDict):
    id: str
    legal_name: str
    tangible_net_worth: float
    fixed_assets_in_state: float
    total_liabilities: float
    net_income_prior_year: float
    elected_financial_test: str
    registry_status: str
    self_bond_status: str
    self_bond_capacity_amount: float
    self_bond_exposure_amount: float
    violation_points_total: int
    outstanding_penalty_balance: float
    forfeiture_count: int
    refund_due_amount: float
    created_at: str
    updated_at: str
    version: int


class MineSite(TypedDict):
    id: str
    name: str
    county: str
    total_acres: float
    site_class: str
    hazard_class: str
    public_safety_score: int
    water_quality_score: int
    acres_affected: float
    legacy_priority_score: float
    funding_status: str
    awarded_funding_amount: float
    unfunded_reclamation_need: float
    created_at: str
    updated_at: str
    version: int


class InspectorProfile(TypedDict):
    id: str
    full_name: str
    certification_level: str
    region: str
    scheduled_inspection_count: int
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    mine_site_id: str
    operator_id: str
    mining_plan_acres: float
    post_mining_land_use: str
    proposed_start_date: str
    status: str
    compliance_posture: str
    bond_basis: str
    bond_required_amount: float
    bond_held_amount: float
    bond_released_to_date: float
    bond_deficiency_amount: float
    disturbed_acres: float
    reclaimed_acres_credited: float
    phase1_released_acres: float
    phase2_released_acres: float
    phase3_released_acres: float
    last_notice_end_date: Optional[str]
    issued_at: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReclamationCostEstimate(TypedDict):
    id: str
    permit_id: str
    estimator_firm: str
    estimator_license_no: str
    estimate_effective_date: str
    direct_cost_per_acre: float
    status: str
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BondInstrument(TypedDict):
    id: str
    permit_id: str
    instrument_type: str
    face_amount: float
    surety_company_name: Optional[str]
    surety_naic_rating: Optional[str]
    collateral_type: Optional[str]
    collateral_market_value: Optional[float]
    replaces_instrument_id: Optional[str]
    credited_amount: float
    status: str
    accepted_by_user_id: Optional[str]
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BondReleaseApplication(TypedDict):
    id: str
    permit_id: str
    phase: str
    acres_requested: float
    requested_amount: float
    approved_amount: float
    status: str
    notice_start_date: Optional[str]
    notice_end_date: Optional[str]
    comment_count: int
    objection_count: int
    objections_resolved: bool
    inspection_id: Optional[str]
    decided_by_user_id: Optional[str]
    approved_at: Optional[str]
    denial_reason: Optional[str]
    rescission_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    permit_id: str
    inspector_id: str
    inspection_type: str
    scheduled_start: str
    duration_hours: float
    scheduled_end: str
    status: str
    result: Optional[str]
    findings_note: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ViolationNotice(TypedDict):
    id: str
    inspection_id: str
    permit_id: str
    violation_class: str
    severity_points: int
    negligence_points: int
    duration_points: int
    history_points: int
    total_points: int
    abatement_days: int
    abatement_deadline: str
    notice_status: str
    penalty_status: str
    good_faith_level: Optional[str]
    penalty_amount: float
    penalty_paid_amount: float
    issued_at: str
    cessation_ordered_at: Optional[str]
    abated_at: Optional[str]
    vacated_at: Optional[str]
    cessation_reason: Optional[str]
    abatement_note: Optional[str]
    vacate_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PermitRevision(TypedDict):
    id: str
    permit_id: str
    revision_type: str
    acreage_delta: Optional[float]
    new_post_mining_land_use: Optional[str]
    sequence_note: Optional[str]
    status: str
    round_count: int
    info_request_note: Optional[str]
    response_note: Optional[str]
    denial_reason: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ForfeitureProceeding(TypedDict):
    id: str
    permit_id: str
    initiation_reason: str
    status: str
    contest_note: Optional[str]
    contest_deadline: str
    forfeited_bond_amount: float
    state_reclamation_cost_estimate: float
    actual_cost_incurred: float
    completion_pct: float
    deficiency_amount: float
    surplus_amount: float
    finalized_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
