"""Type definitions for the project-based rental assistance contract renewal API.

Enum members and field names are taken verbatim from the PRD.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    OWNER_AGENT = "OwnerAgent"
    CONTRACT_ADMINISTRATOR = "ContractAdministrator"
    HUD_FIELD_OFFICE = "HudFieldOffice"
    PHA_ADMINISTRATOR = "PhaAdministrator"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class ComplianceFlag(str, Enum):
    OK = "OK"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class StateCode(str, Enum):
    IL = "IL"
    TX = "TX"


class ContractType(str, Enum):
    NEW_CONSTRUCTION = "NEW_CONSTRUCTION"
    STATE_AGENCY_FINANCED = "STATE_AGENCY_FINANCED"
    LOAN_MANAGEMENT_SET_ASIDE = "LOAN_MANAGEMENT_SET_ASIDE"
    PROPERTY_DISPOSITION = "PROPERTY_DISPOSITION"


class ContractLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    RENEWED = "RENEWED"
    OPT_OUT_PENDING = "OPT_OUT_PENDING"
    EXPIRED_OPT_OUT = "EXPIRED_OPT_OUT"


class RenewalOption(str, Enum):
    OPTION_1_MARK_UP_TO_MARKET = "OPTION_1_MARK_UP_TO_MARKET"
    OPTION_2_OCAF = "OPTION_2_OCAF"
    OPTION_3_MARK_TO_MARKET = "OPTION_3_MARK_TO_MARKET"
    OPTION_4_PORTFOLIO_REENGINEERING = "OPTION_4_PORTFOLIO_REENGINEERING"


class AdjustmentMethod(str, Enum):
    OCAF = "OCAF"
    BUDGET_BASED = "BUDGET_BASED"


class RentTrackStatus(str, Enum):
    TERMS_PENDING = "TERMS_PENDING"
    OPTION_SELECTED = "OPTION_SELECTED"
    RCS_IN_PROGRESS = "RCS_IN_PROGRESS"
    RENTS_APPROVED = "RENTS_APPROVED"
    EXECUTED = "EXECUTED"


class NoticeTrackStatus(str, Enum):
    NOTICES_PENDING = "NOTICES_PENDING"
    RENEWAL_NOTICED = "RENEWAL_NOTICED"
    OPT_OUT_NOTICED = "OPT_OUT_NOTICED"
    OPT_OUT_FINALIZED = "OPT_OUT_FINALIZED"


class StudyState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHALLENGED = "CHALLENGED"
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class ComparableStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    STRUCK = "STRUCK"


class StudyDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class UaMethod(str, Enum):
    FACTOR_BASED = "FACTOR_BASED"
    ENGINEERING_BASED = "ENGINEERING_BASED"


class UaState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"


class UaDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class HouseholdStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OPT_OUT_NOTICED = "OPT_OUT_NOTICED"
    EV_ISSUED = "EV_ISSUED"
    MOVED_OUT = "MOVED_OUT"


class CertType(str, Enum):
    INITIAL = "INITIAL"
    ANNUAL = "ANNUAL"
    INTERIM = "INTERIM"
    UA_ADJUSTMENT = "UA_ADJUSTMENT"


class CertStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class NoticeType(str, Enum):
    RENEWAL_INTENT = "RENEWAL_INTENT"
    OPT_OUT_ONE_YEAR = "OPT_OUT_ONE_YEAR"
    TERMINATION_120_DAY = "TERMINATION_120_DAY"
    RENT_CHANGE = "RENT_CHANGE"


class NoticeStatus(str, Enum):
    ISSUED = "ISSUED"
    RESCINDED = "RESCINDED"


class DeterminationState(str, Enum):
    DRAFT = "DRAFT"
    MUTM_ELIGIBLE = "MUTM_ELIGIBLE"
    M2M_REFERRED = "M2M_REFERRED"
    INELIGIBLE = "INELIGIBLE"
    APPROVED = "APPROVED"


class EligibilityReasonCode(str, Enum):
    CONTRACT_TYPE_EXCLUDED = "CONTRACT_TYPE_EXCLUDED"
    MARKET_ABOVE_CONTRACT_AND_FMR = "MARKET_ABOVE_CONTRACT_AND_FMR"
    MARKET_BELOW_FMR_FLOOR = "MARKET_BELOW_FMR_FLOOR"
    CONTRACT_ABOVE_MARKET_FHA_INSURED = "CONTRACT_ABOVE_MARKET_FHA_INSURED"
    MARKET_NOT_ABOVE_CONTRACT = "MARKET_NOT_ABOVE_CONTRACT"


class EnhancedVoucherState(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    RESCINDED = "RESCINDED"


class VoucherState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    REVERSED = "REVERSED"


class ClaimType(str, Enum):
    VACANCY = "VACANCY"
    UNPAID_RENT = "UNPAID_RENT"
    TENANT_DAMAGES = "TENANT_DAMAGES"


class ValuationVariant(str, Enum):
    ACTUAL_CHRONOLOGICAL = "ACTUAL_CHRONOLOGICAL"
    PROJECTED_ESTIMATE = "PROJECTED_ESTIMATE"
    DIRECT_LEDGER = "DIRECT_LEDGER"


class ClaimState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class ClaimDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


# --------------------------------------------------------------------------
# Common properties carried by every one of the fourteen resource kinds
# --------------------------------------------------------------------------
class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class Owner(CommonFields):
    legal_name: str
    tin: str
    contact_email: str
    portfolio_property_count: int
    compliance_flag: str


class Property(CommonFields):
    owner_id: str
    project_name: str
    state_code: str
    total_units: int
    assisted_unit_count: int
    published_fmr_cents: int
    baseline_utility_allowance_cents: int
    current_utility_allowance_cents: int
    has_fha_insured_mortgage: bool
    units_under_hap_count: int
    enhanced_voucher_unit_count: int
    released_unit_count: int
    last_applied_ua_effective_date: Optional[str]


class HapContract(CommonFields):
    property_id: str
    contract_type: str
    expiration_date: str
    term_months: int
    contract_rent_per_unit_cents: int
    monthly_debt_service_per_unit_cents: int
    operating_expense_per_unit_cents: int
    reserve_deposit_per_unit_cents: int
    authorized_hap_budget_cents: int
    paid_hap_total_cents: int
    paid_claims_total_cents: int
    hap_ledger_balance_cents: int
    lifecycle_status: str
    renewed_rent_per_unit_cents: Optional[int]
    renewed_expiration_date: Optional[str]
    renewed_option: Optional[str]


class RenewalCase(CommonFields):
    contract_id: str
    rent_track_status: str
    notice_track_status: str
    renewal_option: Optional[str]
    adjustment_method: Optional[str]
    opened_on_date: str
    days_to_expiration_at_open: int
    rcs_required: bool
    comparable_market_rent_cents: Optional[int]
    ocaf_rent_per_unit_cents: Optional[int]
    budget_rent_per_unit_cents: Optional[int]
    approved_rent_per_unit_cents: Optional[int]
    challenge_reviewer_user_id: Optional[str]
    rents_approver_user_id: Optional[str]
    opt_out_notice_id: Optional[str]


class RentComparabilityStudy(CommonFields):
    renewal_case_id: str
    supersedes_study_id: Optional[str]
    state: str
    appraiser_name: str
    challenge_round: int
    estimated_market_rent_cents: Optional[int]
    accepted_comparable_count: int
    last_challenge_reason: Optional[str]
    submitted_on_date: Optional[str]


class Comparable(CommonFields):
    study_id: str
    address_label: str
    raw_rent_cents: int
    adjustment_total_cents: int
    utility_adjustment_cents: int
    weight: int
    adjusted_rent_cents: int
    status: str


class UtilityAllowanceAnalysis(CommonFields):
    property_id: str
    method: str
    baseline_allowance_cents: int
    utility_rate_change_pct: Optional[float]
    engineering_estimate_cents: Optional[int]
    proposed_allowance_cents: int
    change_pct: float
    requires_field_office_approval: bool
    effective_date: str
    state: str
    approver_user_id: Optional[str]
    applied_on_date: Optional[str]
    recertified_tenant_count: int


class TenantHousehold(CommonFields):
    property_id: str
    unit_number: str
    household_name: str
    annual_adjusted_income_cents: int
    annual_gross_income_cents: int
    family_size: int
    status: str
    move_out_date: Optional[str]
    current_ttp_cents: Optional[int]
    current_hap_cents: Optional[int]
    ev_eligible: bool


class TenantCertification(CommonFields):
    tenant_id: str
    cert_type: str
    effective_date: str
    utility_allowance_cents: int
    contract_rent_per_unit_cents: int
    gross_rent_cents: int
    ttp_cents: int
    tenant_rent_cents: int
    utility_reimbursement_cents: int
    hap_cents: int
    status: str


class TenantNotice(CommonFields):
    renewal_case_id: str
    tenant_id: Optional[str]
    notice_type: str
    issued_date: str
    effective_date: str
    lead_days: int
    required_lead_days: int
    status: str
    rescind_reason: Optional[str]


class RestructuringDetermination(CommonFields):
    renewal_case_id: str
    determination_state: str
    market_rent_per_unit_cents: Optional[int]
    current_rent_per_unit_cents: int
    fmr_per_unit_cents: int
    eligibility_reason_code: Optional[str]
    post_restructure_rent_per_unit_cents: Optional[int]
    approved_by_user_id: Optional[str]


class EnhancedVoucher(CommonFields):
    tenant_id: str
    renewal_case_id: str
    state: str
    payment_standard_cents: int
    ttp_snapshot_cents: int
    entitlement_cents: int
    issuing_pha_user_id: Optional[str]
    issued_on_date: Optional[str]


class VoucherSubmission(CommonFields):
    contract_id: str
    period_month: str
    state: str
    requested_hap_cents: int
    included_certification_count: int
    paid_amount_cents: Optional[int]
    paid_on_date: Optional[str]
    reversal_reason: Optional[str]


class SpecialClaim(CommonFields):
    contract_id: str
    claim_type: str
    unit_number: str
    claim_period_month: str
    vacancy_start_date: Optional[str]
    vacancy_end_date: Optional[str]
    estimated_vacancy_days: Optional[int]
    claimed_amount_cents: Optional[int]
    security_deposit_balance_cents: int
    vacancy_days_claimed: int
    valuation_variant: Optional[str]
    computed_amount_cents: Optional[int]
    state: str
    decision_reason: Optional[str]
    paid_amount_cents: Optional[int]


class ReconciliationProjection(TypedDict):
    requested_total_cents: int
    paid_hap_total_cents: int
    reversed_total_cents: int
    paid_claims_total_cents: int
    authorized_hap_budget_cents: int
    variance_cents: int
    hap_ledger_balance_cents: int
    paid_period_count: int


JsonDict = dict[str, Any]
