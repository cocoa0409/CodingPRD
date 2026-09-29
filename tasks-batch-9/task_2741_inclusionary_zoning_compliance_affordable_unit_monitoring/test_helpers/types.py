"""Domain enumerations and row shapes of the inclusionary-zoning program."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    HOUSING_COMPLIANCE_OFFICER = "HousingComplianceOfficer"
    DEVELOPER = "Developer"
    RESIDENT = "Resident"
    FUND_AUDITOR = "FundAuditor"


class VintageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ProjectState(str, Enum):
    DRAFT = "DRAFT"
    SCREENED_SUBJECT = "SCREENED_SUBJECT"
    SCREENED_EXEMPT = "SCREENED_EXEMPT"
    PATH_ELECTED = "PATH_ELECTED"
    AGREEMENT_RECORDED = "AGREEMENT_RECORDED"
    MONITORING = "MONITORING"
    CLOSED_OUT = "CLOSED_OUT"


class Applicability(str, Enum):
    PENDING = "PENDING"
    SUBJECT = "SUBJECT"
    EXEMPT = "EXEMPT"


class CompliancePosture(str, Enum):
    PENDING = "PENDING"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    COMPLIANT_ONSITE = "COMPLIANT_ONSITE"
    COMPLIANT_BY_FEE = "COMPLIANT_BY_FEE"
    DEFICIENT = "DEFICIENT"
    UNDER_ENFORCEMENT = "UNDER_ENFORCEMENT"


class CompliancePath(str, Enum):
    ONSITE = "ONSITE"
    OFFSITE = "OFFSITE"
    IN_LIEU_FEE = "IN_LIEU_FEE"
    LAND_DEDICATION = "LAND_DEDICATION"


class Tenure(str, Enum):
    RENTAL = "RENTAL"
    OWNERSHIP = "OWNERSHIP"


class OccupancyStatus(str, Enum):
    PLANNED = "PLANNED"
    MARKETING = "MARKETING"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    VACANT = "VACANT"
    WITHDRAWN = "WITHDRAWN"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    FINDING_OPEN = "FINDING_OPEN"
    CURE_PENDING = "CURE_PENDING"
    OUT_OF_COMPLIANCE = "OUT_OF_COMPLIANCE"


class RestrictionState(str, Enum):
    NOT_RECORDED = "NOT_RECORDED"
    RECORDED = "RECORDED"
    RELEASED = "RELEASED"


class AgreementState(str, Enum):
    DRAFT = "DRAFT"
    RECORDED = "RECORDED"
    RELEASED = "RELEASED"


class ResaleFormula(str, Enum):
    AMI_INDEXED = "AMI_INDEXED"
    SHARED_APPRECIATION = "SHARED_APPRECIATION"


class MarketingPlanState(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    CLOSED = "CLOSED"


class LotteryEventState(str, Enum):
    PENDING = "PENDING"
    DRAWN = "DRAWN"
    COMPLETED = "COMPLETED"


class HouseholdState(str, Enum):
    REGISTERED = "REGISTERED"
    APPLIED = "APPLIED"
    SELECTED = "SELECTED"
    WAITLISTED = "WAITLISTED"
    CERTIFIED = "CERTIFIED"


class CertificationState(str, Enum):
    CERTIFIED = "CERTIFIED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class MonitoringReviewState(str, Enum):
    RECORDED = "RECORDED"
    COMPLIANT = "COMPLIANT"
    FINDING_ISSUED = "FINDING_ISSUED"
    CURE_SUBMITTED = "CURE_SUBMITTED"
    CURED = "CURED"
    ESCALATED = "ESCALATED"


class FindingType(str, Enum):
    RENT_OVERCHARGE = "RENT_OVERCHARGE"
    INCOME_OVER_LIMIT = "INCOME_OVER_LIMIT"
    OCCUPANCY_UNVERIFIED = "OCCUPANCY_UNVERIFIED"


class ResaleTransactionState(str, Enum):
    SUBMITTED = "SUBMITTED"
    PRICE_APPROVED = "PRICE_APPROVED"
    ROFR_WAIVED = "ROFR_WAIVED"
    ROFR_EXERCISED = "ROFR_EXERCISED"
    BUYER_CERTIFIED = "BUYER_CERTIFIED"
    CLOSED = "CLOSED"
    CITY_PURCHASE_CLOSED = "CITY_PURCHASE_CLOSED"
    SUPERSEDED = "SUPERSEDED"


class RofrDecision(str, Enum):
    EXERCISE = "EXERCISE"
    WAIVE = "WAIVE"


class FeeBasis(str, Enum):
    FULL = "FULL"
    FRACTIONAL = "FRACTIONAL"
    SUBSTITUTION = "SUBSTITUTION"


class FeeState(str, Enum):
    ASSESSED = "ASSESSED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DELINQUENT = "DELINQUENT"
    SUPERSEDED = "SUPERSEDED"


class DisbursementState(str, Enum):
    REQUESTED = "REQUESTED"
    DISBURSED = "DISBURSED"
    VOIDED = "VOIDED"


class EligibleUse(str, Enum):
    AFFORDABLE_HOUSING_PRODUCTION = "AFFORDABLE_HOUSING_PRODUCTION"
    RENTAL_SUBSIDY = "RENTAL_SUBSIDY"
    HOMEBUYER_ASSISTANCE = "HOMEBUYER_ASSISTANCE"
    ADMIN = "ADMIN"


class MarketingReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_REVISION = "REQUEST_REVISION"


class FunderReportBasis(str, Enum):
    ENTITLEMENT = "ENTITLEMENT"
    OCCUPANCY = "OCCUPANCY"


# --- row shapes --------------------------------------------------------------
# Every one of the thirteen resource families carries id, created_at,
# updated_at and version; no family is exempt.
COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


class Ordinance(TypedDict):
    id: str
    code: str
    effective_date: str
    min_project_units_threshold: int
    set_aside_bps_by_district: dict
    gap_basis_cents_by_level: dict
    fee_gap_level_bps: int
    surcharge_bps: int
    surcharge_cap_cents: int
    discount_tiers: list
    fee_due_days: int
    alternative_paths_allowed: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AmiSchedule(TypedDict):
    id: str
    effective_year: int
    median_income_cents_by_size: dict
    utility_allowance_cents_by_bedrooms: dict
    status: str
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict):
    id: str
    name: str
    developer_user_id: str
    zoning_district: str
    total_units: int
    approval_date: str
    ordinance_id: Optional[str]
    state: str
    applicability: str
    required_affordable_units: int
    fractional_obligation_bps: int
    compliance_path: Optional[str]
    onsite_unit_equivalents_bps: int
    fee_covered_equivalents_bps: int
    total_obligation_bps: int
    compliance_posture: str
    screened_at: Optional[str]
    screen_count: int
    created_at: str
    updated_at: str
    version: int


class AffordableUnit(TypedDict):
    id: str
    project_id: str
    agreement_id: str
    unit_number: str
    bedrooms: int
    sqft: int
    tenure: str
    affordability_level_bps: int
    market_comparable_sqft: int
    occupancy_status: str
    compliance_status: str
    restriction_state: str
    occupant_household_id: Optional[str]
    current_rent_cents: int
    max_allowed_rent_cents: int
    original_purchase_price_cents: int
    ami_income_at_purchase_cents: int
    restriction_recorded_at: Optional[str]
    last_refinance_balance_cents: int
    approved_refinance_cap_cents: int
    withdrawn_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MarketingPlan(TypedDict):
    id: str
    project_id: str
    lottery_open_at: str
    lottery_close_at: str
    preference_categories: List[str]
    state: str
    revision_round: int
    reviewed_by_user_id: Optional[str]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LotteryEvent(TypedDict):
    id: str
    marketing_plan_id: str
    units_offered: int
    eligibility_level_bps: int
    state: str
    round_seq: int
    drawn_at: Optional[str]
    drawn_by_user_id: Optional[str]
    selected_household_ids: List[str]
    waitlisted_household_ids: List[str]
    redraw_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Household(TypedDict):
    id: str
    applicant_name: str
    household_size: int
    gross_annual_income_cents: int
    preference_claims: List[str]
    lottery_event_id: Optional[str]
    state: str
    preference_score: int
    rank_position: Optional[int]
    created_at: str
    updated_at: str
    version: int


class IncomeCertification(TypedDict):
    id: str
    household_id: str
    unit_id: str
    ami_schedule_year: int
    certified_income_cents: int
    contract_rent_cents: int
    income_limit_cents: int
    max_rent_cents: int
    ami_pct_bps: int
    effective_date: str
    expires_at: Optional[str]
    state: str
    certified_by_user_id: str
    is_recertification: bool
    created_at: str
    updated_at: str
    version: int


class RegulatoryAgreement(TypedDict):
    id: str
    project_id: str
    term_years: int
    resale_formula: str
    owner_appreciation_share_bps: int
    max_refinance_ltv_bps: int
    doc_number: Optional[str]
    recorded_at: Optional[str]
    state: str
    created_at: str
    updated_at: str
    version: int


class MonitoringReview(TypedDict):
    id: str
    unit_id: str
    review_year: int
    reported_rent_cents: int
    reported_income_cents: int
    occupancy_verified: bool
    state: str
    finding_types: List[str]
    overcharge_monthly_cents: int
    penalty_at_base_cents: int
    cure_extension_days: int
    cure_deadline: Optional[str]
    penalty_final_cents: Optional[int]
    finding_issued_at: Optional[str]
    issued_by_user_id: str
    cure_submitted_at: Optional[str]
    cleared_by_user_id: Optional[str]
    corrected_rent_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ResaleTransaction(TypedDict):
    id: str
    unit_id: str
    prior_transaction_id: Optional[str]
    seller_household_id: Optional[str]
    buyer_household_id: Optional[str]
    buyer_certification_id: Optional[str]
    proposed_price_cents: int
    appraised_value_cents: int
    capital_improvements_cents: int
    deferred_maintenance_cents: int
    broker_fee_cents: int
    resale_formula_applied: str
    indexed_base_cents: int
    improvement_credit_cents: int
    max_resale_price_cents: int
    net_proceeds_cents: int
    seller_equity_cents: int
    seller_improvement_credit_cents: int
    seller_appreciation_share_cents: int
    city_recapture_cents: int
    state: str
    price_approved_at: Optional[str]
    price_approved_by_user_id: Optional[str]
    rofr_deadline: Optional[str]
    rofr_auto_waived: bool
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InLieuFee(TypedDict):
    id: str
    project_id: str
    ordinance_id: str
    superseded_by_fee_id: Optional[str]
    basis: str
    unit_equivalent_bps: int
    base_amount_cents: int
    surcharge_cents: int
    pre_discount_total_cents: int
    discount_bps_applied: int
    discount_cents: int
    assessed_amount_cents: int
    paid_amount_cents: int
    due_date: str
    state: str
    last_payment_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrustFundDisbursement(TypedDict):
    id: str
    source_fee_id: str
    eligible_use: str
    amount_cents: int
    state: str
    requested_by_user_id: str
    disbursed_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrustFundSummary(TypedDict):
    total_paid_fees_cents: int
    total_recapture_cents: int
    total_inflow_cents: int
    encumbered_cents: int
    disbursed_cents: int
    unencumbered_balance_cents: int
    admin_cap_cents: int
    admin_committed_cents: int


class FunderReport(TypedDict):
    project_id: str
    basis: str
    total_obligation_bps: int
    delivered_equivalents_bps: int
    occupied_equivalents_bps: int
    compliance_ratio_bps: int
    open_findings_count: int
    total_fees_assessed_cents: int
    total_fees_paid_cents: int


class ClockResult(TypedDict):
    current_utc: str
    certifications_expired: int
    fees_marked_delinquent: int
    rofr_windows_auto_waived: int
