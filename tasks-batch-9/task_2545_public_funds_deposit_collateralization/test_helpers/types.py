"""Domain types for the Public Funds Collateral API: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ─────────────────────────────────


class UserRole(str, Enum):
    STATE_REGULATOR = "StateRegulator"
    BANK_COLLATERAL_OFFICER = "BankCollateralOfficer"
    BANK_COMPLIANCE_OFFICER = "BankComplianceOfficer"
    CUSTODIAN = "Custodian"
    PUBLIC_UNIT_TREASURER = "PublicUnitTreasurer"
    SYSTEM_OPERATOR = "SystemOperator"


# ─── Status / enum vocabularies ───────────────────────


class CustodianApprovalStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"


class CustodianType(str, Enum):
    FEDERAL_RESERVE = "FEDERAL_RESERVE"
    FHLB = "FHLB"
    TRUST_BANK = "TRUST_BANK"


class PoolPosture(str, Enum):
    ADEQUATE = "ADEQUATE"
    SHORTFALL = "SHORTFALL"


class UnitType(str, Enum):
    SCHOOL_DISTRICT = "SCHOOL_DISTRICT"
    COUNTY = "COUNTY"
    MUNICIPALITY = "MUNICIPALITY"
    STATE_AGENCY = "STATE_AGENCY"


class CollateralProgramPreference(str, Enum):
    DEDICATED = "DEDICATED"
    POOLED = "POOLED"


class ReportingFrequency(str, Enum):
    DAILY = "DAILY"
    MONTHLY = "MONTHLY"


class ExposureStatus(str, Enum):
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    ESCALATED = "ESCALATED"


class CharterType(str, Enum):
    STATE_CHARTERED = "STATE_CHARTERED"
    NATIONAL = "NATIONAL"


class CapitalTier(str, Enum):
    WELL_CAPITALIZED = "WELL_CAPITALIZED"
    ADEQUATELY_CAPITALIZED = "ADEQUATELY_CAPITALIZED"
    UNDERCAPITALIZED = "UNDERCAPITALIZED"


class InsuranceDeterminationBasis(str, Enum):
    AGGREGATED_BY_UNIT = "AGGREGATED_BY_UNIT"
    PER_ACCOUNT = "PER_ACCOUNT"


class DepositoryApprovalStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUSPENDED = "SUSPENDED"


class CollateralPosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    MARGIN_DEFICIENT = "MARGIN_DEFICIENT"
    FROZEN = "FROZEN"


class RiskGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class QualificationReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ATTESTED = "ATTESTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED_FOR_INFO = "RETURNED_FOR_INFO"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class QualificationDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class DepositClass(str, Enum):
    DEMAND = "DEMAND"
    TIME_AND_SAVINGS = "TIME_AND_SAVINGS"


class PledgingMode(str, Enum):
    DEDICATED = "DEDICATED"
    POOLED = "POOLED"


class FundingStatus(str, Enum):
    PENDING_FUNDING = "PENDING_FUNDING"
    FUNDED = "FUNDED"
    RESTRICTED = "RESTRICTED"


class CollateralStatus(str, Enum):
    UNSECURED = "UNSECURED"
    SECURED = "SECURED"
    DEFICIENT = "DEFICIENT"


class RestrictedReason(str, Enum):
    DEPOSITORY_SUSPENDED = "DEPOSITORY_SUSPENDED"


class BeneficiaryType(str, Enum):
    DEPOSIT_ACCOUNT = "DEPOSIT_ACCOUNT"
    POOLED_PROGRAM = "POOLED_PROGRAM"


class PledgeAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_SIGNATURES = "PENDING_SIGNATURES"
    AMENDMENT_REQUESTED = "AMENDMENT_REQUESTED"
    EXECUTED = "EXECUTED"
    TERMINATED = "TERMINATED"


class SignatureParty(str, Enum):
    DEPOSITORY = "DEPOSITORY"
    PUBLIC_UNIT = "PUBLIC_UNIT"
    CUSTODIAN = "CUSTODIAN"


class AssetType(str, Enum):
    US_TREASURY = "US_TREASURY"
    AGENCY_DEBENTURE = "AGENCY_DEBENTURE"
    AGENCY_MBS = "AGENCY_MBS"
    MUNI_GO = "MUNI_GO"
    MUNI_REVENUE = "MUNI_REVENUE"
    LETTER_OF_CREDIT = "LETTER_OF_CREDIT"


class EligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class PledgeStatus(str, Enum):
    UNPLEDGED = "UNPLEDGED"
    PARTIALLY_PLEDGED = "PARTIALLY_PLEDGED"
    FULLY_PLEDGED = "FULLY_PLEDGED"


class PledgeAllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    SUBSTITUTED = "SUBSTITUTED"


class ReleaseReason(str, Enum):
    OFFICER_RELEASE = "OFFICER_RELEASE"
    AGREEMENT_TERMINATED = "AGREEMENT_TERMINATED"
    ASSET_INELIGIBLE = "ASSET_INELIGIBLE"
    SUBSTITUTION_SETTLED = "SUBSTITUTION_SETTLED"


class SubstitutionRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    COMPLIANCE_APPROVED = "COMPLIANCE_APPROVED"
    CUSTODIAN_ACKED = "CUSTODIAN_ACKED"
    READY_TO_SETTLE = "READY_TO_SETTLE"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class MtmBasis(str, Enum):
    SUPERVISORY = "SUPERVISORY"
    INTERNAL = "INTERNAL"


class MtmOutcome(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    DEFICIENT = "DEFICIENT"


class MarginCallStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_CURED = "PARTIALLY_CURED"
    ESCALATED = "ESCALATED"
    CURED = "CURED"
    BREACHED = "BREACHED"


class ConfirmationStatus(str, Enum):
    ISSUED = "ISSUED"
    CONFIRMED = "CONFIRMED"
    EXCEPTION = "EXCEPTION"


class CycleLabel(str, Enum):
    TAX_COLLECTION = "TAX_COLLECTION"
    DISBURSEMENT = "DISBURSEMENT"
    DEBT_SERVICE = "DEBT_SERVICE"


class RunoffBasis(str, Enum):
    PEAK_WINDOW = "PEAK_WINDOW"
    PERIOD_END = "PERIOD_END"


class RunoffForecastStatus(str, Enum):
    OPEN = "OPEN"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"


# ─── Entity shapes ────────────────────────────────────
# Resources carry id + created_at + updated_at + version (PRD §2.4), except
# MarkToMarketRun, which is immutable and carries only id and created_at.


class Custodian(TypedDict, total=False):
    id: str
    name: str
    custodian_type: str
    tri_party_capable: bool
    concentration_limit_bps: int
    approval_status: str
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PooledCollateralProgram(TypedDict, total=False):
    id: str
    name: str
    administrator_state: str
    minimum_pool_pct_bps: int
    aggregate_required_collateral_cents: int
    aggregate_collateral_value_cents: int
    unallocated_collateral_cents: int
    participant_account_count: int
    pool_posture: str
    created_at: str
    updated_at: str
    version: int


class PublicUnit(TypedDict, total=False):
    id: str
    name: str
    unit_type: str
    jurisdiction_state: str
    statutory_max_deposit_cents: int
    collateral_program_preference: str
    reporting_frequency: str
    total_deposit_balance_cents: int
    total_uninsured_cents: int
    exposure_status: str
    created_at: str
    updated_at: str
    version: int


class Depository(TypedDict, total=False):
    id: str
    name: str
    charter_type: str
    home_state: str
    capital_ratio_bps: int
    capital_tier: str
    insurance_determination_basis: str
    pooled_program_id: Optional[str]
    approval_status: str
    collateral_posture: str
    risk_grade: str
    risk_score_bps: int
    consecutive_deficiency_runs: int
    open_margin_call_count: int
    approved_pledge_capacity_cents: int
    approved_at: Optional[str]
    mtm_run_index: int
    last_mtm_window_end: Optional[str]
    total_required_collateral_cents: int
    total_pledged_collateral_value_cents: int
    total_pledged_par_cents: int
    deposit_account_count: int
    created_at: str
    updated_at: str
    version: int


class QualificationReview(TypedDict, total=False):
    id: str
    depository_id: str
    requested_pledge_capacity_cents: int
    status: str
    submitted_by_user_id: str
    attested_by_user_id: Optional[str]
    attestation_note: Optional[str]
    info_request_note: Optional[str]
    decision: Optional[str]
    decision_note: Optional[str]
    decided_at: Optional[str]
    round_count: int
    created_at: str
    updated_at: str
    version: int


class DepositAccount(TypedDict, total=False):
    id: str
    depository_id: str
    public_unit_id: str
    deposit_class: str
    pledging_mode: str
    group_sequence: int
    funding_status: str
    collateral_status: str
    ledger_balance_cents: int
    insured_amount_cents: int
    uninsured_amount_cents: int
    required_collateral_pct_bps: int
    required_collateral_cents: int
    assigned_collateral_value_cents: int
    pooled_allocated_collateral_cents: int
    coverage_ratio_bps: int
    restricted_reason: Optional[str]
    pool_priority_rank: int
    created_at: str
    updated_at: str
    version: int


class PledgeAgreement(TypedDict, total=False):
    id: str
    depository_id: str
    custodian_id: str
    beneficiary_type: str
    deposit_account_id: Optional[str]
    pooled_program_id: Optional[str]
    agreement_number: str
    governing_law_state: str
    status: str
    signature_count: int
    amendment_round: int
    depository_signed_at: Optional[str]
    public_unit_signed_at: Optional[str]
    custodian_signed_at: Optional[str]
    executed_at: Optional[str]
    terminated_at: Optional[str]
    total_pledged_par_cents: int
    total_collateral_value_cents: int
    active_allocation_count: int
    created_at: str
    updated_at: str
    version: int


class CollateralAsset(TypedDict, total=False):
    id: str
    depository_id: str
    custodian_id: str
    cusip: str
    asset_type: str
    par_value_cents: int
    market_price_bps: int
    haircut_bps: int
    market_value_cents: int
    collateral_value_cents: int
    priced_at: str
    pledged_par_cents: int
    available_par_cents: int
    eligibility_status: str
    pledge_status: str
    ineligible_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PledgeAllocation(TypedDict, total=False):
    id: str
    pledge_agreement_id: str
    collateral_asset_id: str
    allocated_par_cents: int
    allocated_collateral_value_cents: int
    effective_from: str
    effective_to: str
    status: str
    released_at: Optional[str]
    release_reason: Optional[str]
    created_by_substitution_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubstitutionRequest(TypedDict, total=False):
    id: str
    pledge_agreement_id: str
    outgoing_allocation_id: str
    incoming_asset_id: str
    incoming_par_cents: int
    status: str
    submitted_by_user_id: str
    compliance_approved_at: Optional[str]
    compliance_approved_by_user_id: Optional[str]
    custodian_acked_at: Optional[str]
    settled_at: Optional[str]
    rejection_reason: Optional[str]
    value_adequacy_delta_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MarkToMarketRun(TypedDict, total=False):
    """Immutable historical record: carries only id and created_at (PRD §2.4)."""

    id: str
    depository_id: str
    window_start: str
    window_end: str
    basis: str
    as_of: str
    run_index: int
    deficiency_surcharge_bps_applied: int
    total_required_collateral_cents: int
    total_collateral_value_cents: int
    deficiency_cents: int
    deficiency_ratio_bps: int
    outcome: str
    coverage_component_bps: int
    volatility_component_bps: int
    documentation_component_bps: int
    risk_score_bps: int
    risk_grade_assigned: str
    created_at: str


class MarginCall(TypedDict, total=False):
    id: str
    depository_id: str
    mtm_run_id: str
    required_cure_cents: int
    cured_cents: int
    outstanding_cents: int
    status: str
    cure_deadline_at: str
    breach_deadline_at: str
    escalated_at: Optional[str]
    cured_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SafekeepingReceipt(TypedDict, total=False):
    id: str
    pledge_agreement_id: str
    receipt_number: str
    reported_par_cents: int
    reported_asset_count: int
    as_of: str
    ledger_par_cents: int
    ledger_asset_count: int
    discrepancy_par_cents: int
    confirmation_status: str
    confirmed_by_user_id: Optional[str]
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProjectedWindow(TypedDict, total=False):
    window_start: str
    window_end: str
    projected_balance_cents: int


class RunoffForecast(TypedDict, total=False):
    id: str
    deposit_account_id: str
    cycle_label: str
    basis: str
    horizon_start: str
    horizon_end: str
    projected_windows: List[ProjectedWindow]
    projected_peak_balance_cents: int
    projected_required_collateral_cents: int
    unpledged_capacity_cents: int
    pledge_capacity_gap_cents: int
    status: str
    requires_reforecast: bool
    superseded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
