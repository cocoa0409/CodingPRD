"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    CAPTIVE_MANAGER = "CaptiveManager"
    DOMICILE_REGULATOR = "DomicileRegulator"
    UNDERWRITER = "Underwriter"
    ACTUARY = "Actuary"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    BOARD_DIRECTOR = "BoardDirector"
    TAX_ADVISOR = "TaxAdvisor"


class CaptiveStatus(str, Enum):
    FORMATION_PENDING = "FORMATION_PENDING"
    DOMICILE_FILED = "DOMICILE_FILED"
    CAPITALIZED = "CAPITALIZED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISSOLVED = "DISSOLVED"


class SolvencyStatus(str, Enum):
    ADEQUATE = "ADEQUATE"
    WARNING = "WARNING"
    BREACH = "BREACH"


class TaxClassification(str, Enum):
    MICRO_CAPTIVE_831B = "MICRO_CAPTIVE_831B"
    STANDARD_831A = "STANDARD_831A"
    NON_ELECTING = "NON_ELECTING"


class DomicileJurisdiction(str, Enum):
    VERMONT = "VERMONT"
    BERMUDA = "BERMUDA"
    CAYMAN = "CAYMAN"
    GUERNSEY = "GUERNSEY"
    LUXEMBOURG = "LUXEMBOURG"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    BOUND = "BOUND"
    IN_FORCE = "IN_FORCE"
    RUN_OFF = "RUN_OFF"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CoverageStatus(str, Enum):
    UNBOUND = "UNBOUND"
    BOUND = "BOUND"
    EXPIRED = "EXPIRED"


class FrontingStatus(str, Enum):
    NEGOTIATING = "NEGOTIATING"
    TERMS_AGREED = "TERMS_AGREED"
    COLLATERAL_POSTED = "COLLATERAL_POSTED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class CollateralVerificationStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class CollateralType(str, Enum):
    LETTER_OF_CREDIT = "LETTER_OF_CREDIT"
    TRUST_ACCOUNT = "TRUST_ACCOUNT"
    SURETY_BOND = "SURETY_BOND"
    CASH_ESCROW = "CASH_ESCROW"
    INVESTMENT_SECURITIES = "INVESTMENT_SECURITIES"


class OperatingUnitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DECOMMISSIONED = "DECOMMISSIONED"


class AllocationStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    AUDITED = "AUDITED"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    CANCELLED = "CANCELLED"


class AllocationMethod(str, Enum):
    EXPOSURE_PRO_RATA = "EXPOSURE_PRO_RATA"
    EQUAL_SHARE = "EQUAL_SHARE"
    MANUAL = "MANUAL"
    RISK_WEIGHTED = "RISK_WEIGHTED"


class ClaimStatus(str, Enum):
    REPORTED = "REPORTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    RESERVED = "RESERVED"
    SETTLED = "SETTLED"
    DENIED = "DENIED"
    CLOSED_WITHOUT_PAYMENT = "CLOSED_WITHOUT_PAYMENT"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    FULLY_PAID = "FULLY_PAID"


class LitigationStatus(str, Enum):
    NOT_LITIGATED = "NOT_LITIGATED"
    LITIGATED = "LITIGATED"
    SETTLED_IN_LITIGATION = "SETTLED_IN_LITIGATION"


class TPAStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REINSTATED = "REINSTATED"
    TERMINATED = "TERMINATED"


class ReserveStatus(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    REVIEWED = "REVIEWED"
    CERTIFIED = "CERTIFIED"
    FILED = "FILED"
    SUPERSEDED = "SUPERSEDED"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTUARIAL_REVIEW = "ACTUARIAL_REVIEW"
    BOARD_APPROVED = "BOARD_APPROVED"
    FILED = "FILED"
    AMENDED = "AMENDED"


class RbcActionLevel(str, Enum):
    NONE = "NONE"
    COMPANY_ACTION = "COMPANY_ACTION"
    REGULATORY_ACTION = "REGULATORY_ACTION"
    AUTHORIZED_CONTROL = "AUTHORIZED_CONTROL"
    MANDATORY_CONTROL = "MANDATORY_CONTROL"


class MeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_SESSION = "IN_SESSION"
    MINUTES_DRAFTED = "MINUTES_DRAFTED"
    MINUTES_APPROVED = "MINUTES_APPROVED"
    FILED = "FILED"
    CANCELLED = "CANCELLED"


class TaxPositionStatus(str, Enum):
    DRAFT = "DRAFT"
    ANALYZED = "ANALYZED"
    OPINION_ISSUED = "OPINION_ISSUED"
    FILED = "FILED"
    CHALLENGED = "CHALLENGED"


class RiskDistributionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    MARGINAL = "MARGINAL"


class ReportingPosition(str, Enum):
    MORE_LIKELY_THAN_NOT = "MORE_LIKELY_THAN_NOT"
    SUBSTANTIAL_AUTHORITY = "SUBSTANTIAL_AUTHORITY"
    REASONABLE_BASIS = "REASONABLE_BASIS"
    NO_POSITION = "NO_POSITION"


class CaptiveEntity(TypedDict, total=False):
    id: str
    captive_name: str
    domicile_jurisdiction: str
    formation_date: str
    capitalization_amount: int
    capital_minimum_required: int
    solvency_ratio: float
    solvency_status: str
    admitted_assets: int
    total_reserves_held: int
    total_premium_written: int
    governance_score: float
    status: str
    tax_classification: str
    risk_distribution_score: float
    created_at: str
    updated_at: str
    version: int


class DomicileFiling(TypedDict, total=False):
    id: str
    captive_id: str
    filing_type: str
    jurisdiction: str
    filing_fee_cents: int
    supporting_documents: List[Dict[str, Any]]
    regulator_reference: Optional[str]
    review_deadline: Optional[str]
    status: str
    rejection_reason: Optional[str]
    filed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InsuranceProgram(TypedDict, total=False):
    id: str
    captive_id: str
    program_name: str
    line_of_business: str
    policy_period_start: str
    policy_period_end: str
    aggregate_limit_cents: int
    per_occurrence_limit_cents: int
    attachment_point_cents: int
    premium_budget_cents: int
    premium_allocated_cents: int
    claims_incurred_cents: int
    claims_paid_cents: int
    loss_ratio: float
    program_status: str
    coverage_status: str
    fronting_required: bool
    created_at: str
    updated_at: str
    version: int


class FrontingArrangement(TypedDict, total=False):
    id: str
    program_id: str
    captive_id: str
    fronting_carrier_name: str
    fronting_fee_pct: float
    collateral_required_cents: int
    collateral_posted_cents: int
    collateral_shortfall_cents: int
    reinsurance_ceded_pct: float
    fronting_fee_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CollateralPosting(TypedDict, total=False):
    id: str
    fronting_arrangement_id: str
    collateral_type: str
    amount_cents: int
    posted_date: str
    expiry_date: str
    issuing_institution: str
    verification_status: str
    haircut_pct: float
    effective_value_cents: int
    created_at: str
    updated_at: str
    version: int


class OperatingUnit(TypedDict, total=False):
    id: str
    captive_id: str
    unit_name: str
    unit_code: str
    exposure_basis: str
    exposure_amount: float
    total_premium_allocated_cents: int
    total_claims_incurred_cents: int
    loss_ratio: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PremiumAllocation(TypedDict, total=False):
    id: str
    program_id: str
    operating_unit_id: str
    captive_id: str
    allocation_method: str
    allocated_amount_cents: int
    provisional_amount_cents: int
    final_amount_cents: Optional[int]
    adjustment_cents: Optional[int]
    risk_weight: float
    allocation_period_start: str
    allocation_period_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    program_id: str
    operating_unit_id: str
    captive_id: str
    claim_number: str
    claimant_name: str
    loss_date: str
    reported_date: str
    claimed_amount_cents: int
    reserved_amount_cents: int
    paid_amount_cents: int
    recoverable_amount_cents: int
    net_incurred_cents: int
    tpa_assigned_id: Optional[str]
    coverage_confirmed: bool
    claim_status: str
    payment_status: str
    litigation_status: str
    created_at: str
    updated_at: str
    version: int


class TPAAssignment(TypedDict, total=False):
    id: str
    claim_id: str
    tpa_firm_name: str
    tpa_contact_email: str
    assignment_date: str
    authority_limit_cents: int
    fee_structure: str
    fee_amount_cents: int
    performance_score: float
    sla_compliance_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ActuarialReserve(TypedDict, total=False):
    id: str
    program_id: str
    captive_id: str
    reserve_type: str
    actuarial_method: str
    valuation_date: str
    central_estimate_cents: int
    low_estimate_cents: int
    high_estimate_cents: int
    carried_reserve_cents: int
    confidence_level_pct: int
    development_factor: float
    certified_by: Optional[str]
    certification_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AnnualStatement(TypedDict, total=False):
    id: str
    captive_id: str
    statement_year: int
    filing_deadline: str
    total_assets_cents: int
    total_liabilities_cents: int
    policyholder_surplus_cents: int
    net_premium_written_cents: int
    net_losses_incurred_cents: int
    combined_ratio: float
    expense_ratio: float
    underwriting_result_cents: int
    investment_income_cents: int
    rbc_ratio: float
    rbc_action_level: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BoardMeeting(TypedDict, total=False):
    id: str
    captive_id: str
    meeting_date: str
    meeting_type: str
    quorum_required: int
    directors_present: int
    quorum_met: bool
    agenda_items: List[Dict[str, Any]]
    resolutions_passed: List[Dict[str, Any]]
    minutes_document_url: Optional[str]
    annual_meeting_completed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxPosition(TypedDict, total=False):
    id: str
    captive_id: str
    tax_year: int
    position_type: str
    position_description: str
    premium_deductibility_pct: float
    risk_distribution_test_result: str
    insured_entities_count: int
    third_party_premium_pct: float
    premium_threshold_met: bool
    reporting_position: str
    disclosure_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditLog(TypedDict, total=False):
    # Append-only: carries only id + created_at, no updated_at / version (PRD §2.4).
    id: str
    captive_id: str
    action_type: str
    entity_type: str
    entity_id: str
    actor_role: str
    actor_id: str
    action_description: str
    previous_state: str
    new_state: str
    timestamp: str
    created_at: str
