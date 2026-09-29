"""
Typed shapes and enumerations for the Lender Appraisal Review Desk API.

The TypedDicts mirror the response bodies described by the PRD; they are used for
editor support and to document which keys a test may read. Enumerations are plain
string classes so that a test can write ``ReviewStatus.RULES_FLAGGED`` and still
compare directly against the JSON string the API returns.
"""

from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
class Role:
    LOAN_OFFICER = "LoanOfficer"
    AMC_COORDINATOR = "AMCCoordinator"
    APPRAISAL_DESK_REVIEWER = "AppraisalDeskReviewer"
    CHIEF_APPRAISER = "ChiefAppraiser"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    APPRAISER = "Appraiser"
    BORROWER = "Borrower"


ALL_ROLES = [
    Role.LOAN_OFFICER,
    Role.AMC_COORDINATOR,
    Role.APPRAISAL_DESK_REVIEWER,
    Role.CHIEF_APPRAISER,
    Role.COMPLIANCE_OFFICER,
    Role.APPRAISER,
    Role.BORROWER,
]


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class LoanPurpose:
    PURCHASE = "PURCHASE"
    REFINANCE = "REFINANCE"


class MarketType:
    URBAN = "URBAN"
    SUBURBAN = "SUBURBAN"
    RURAL = "RURAL"


class RiskTier:
    LOW = "LOW"
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"


class UnderwritingStatus:
    SUBMITTED = "SUBMITTED"
    CONDITIONALLY_APPROVED = "CONDITIONALLY_APPROVED"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class CollateralStatus:
    PENDING_APPRAISAL = "PENDING_APPRAISAL"
    UNDER_REVIEW = "UNDER_REVIEW"
    VALUE_ACCEPTED = "VALUE_ACCEPTED"
    VALUE_CONTESTED = "VALUE_CONTESTED"
    VALUE_REVISED = "VALUE_REVISED"
    QUARANTINED = "QUARANTINED"


class DecisionImpact:
    NO_IMPACT = "NO_IMPACT"
    PRICING_ADJUSTMENT = "PRICING_ADJUSTMENT"
    CONDITION_REQUIRED = "CONDITION_REQUIRED"
    DENIAL_RECOMMENDED = "DENIAL_RECOMMENDED"


class PanelStatus:
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    REMOVED = "REMOVED"


class MembershipStatus:
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class MembershipTier:
    GENERAL = "GENERAL"
    COMPLEX = "COMPLEX"
    REVIEW_SPECIALIST = "REVIEW_SPECIALIST"


class ReportFormType:
    FORM_1004 = "FORM_1004"
    FORM_1073 = "FORM_1073"
    FORM_2055 = "FORM_2055"


class ReviewStatus:
    RECEIVED = "RECEIVED"
    RULES_CLEARED = "RULES_CLEARED"
    RULES_FLAGGED = "RULES_FLAGGED"
    IN_DESK_REVIEW = "IN_DESK_REVIEW"
    VALUE_ACCEPTED = "VALUE_ACCEPTED"
    ESCALATED = "ESCALATED"
    RETURNED_TO_AMC = "RETURNED_TO_AMC"
    VALUE_CONTESTED = "VALUE_CONTESTED"
    VALUE_REVISED = "VALUE_REVISED"
    QUARANTINED = "QUARANTINED"
    SUPERSEDED = "SUPERSEDED"


class BiasScreenStatus:
    NOT_SCREENED = "NOT_SCREENED"
    CLEAR = "CLEAR"
    INDICATED = "INDICATED"
    SUBSTANTIATED = "SUBSTANTIATED"
    CLEARED_ON_REVIEW = "CLEARED_ON_REVIEW"


class SaleStatus:
    CLOSED = "CLOSED"
    PENDING = "PENDING"
    ACTIVE_LISTING = "ACTIVE_LISTING"


class DwellingType:
    SFR = "SFR"
    CONDO = "CONDO"
    TOWNHOUSE = "TOWNHOUSE"
    MULTI_2_4 = "MULTI_2_4"


class CensusTractBand:
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class CheckCode:
    CHK_COMPLETENESS = "CHK_COMPLETENESS"
    CHK_COMP_COUNT = "CHK_COMP_COUNT"
    CHK_COMP_DISTANCE = "CHK_COMP_DISTANCE"
    CHK_COMP_AGE = "CHK_COMP_AGE"
    CHK_GROSS_ADJUSTMENT = "CHK_GROSS_ADJUSTMENT"
    CHK_NET_ADJUSTMENT = "CHK_NET_ADJUSTMENT"
    CHK_VALUE_RECONCILIATION = "CHK_VALUE_RECONCILIATION"
    CHK_FORM_TYPE = "CHK_FORM_TYPE"


class CheckOutcome:
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class BiasFlagSource:
    NARRATIVE = "NARRATIVE"
    COMP_SELECTION = "COMP_SELECTION"


class BiasFlagStatus:
    OPEN = "OPEN"
    CLEARED = "CLEARED"
    SUBSTANTIATED = "SUBSTANTIATED"


class BiasDisposition:
    SUBSTANTIATE = "SUBSTANTIATE"
    CLEAR = "CLEAR"


class CommunicationRecipient:
    APPRAISER = "APPRAISER"
    AMC = "AMC"
    LENDER_DESK = "LENDER_DESK"


class CommunicationIntent:
    ORDER_STATUS = "ORDER_STATUS"
    DELIVERY_LOGISTICS = "DELIVERY_LOGISTICS"
    REPORT_CLARIFICATION = "REPORT_CLARIFICATION"
    COMPARABLE_SUGGESTION = "COMPARABLE_SUGGESTION"
    VALUE_INFLUENCE = "VALUE_INFLUENCE"
    DEADLINE_PRESSURE = "DEADLINE_PRESSURE"


class DeskReviewStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    ESCALATED = "ESCALATED"
    RETURNED = "RETURNED"
    CLOSED = "CLOSED"


class DecisionAction:
    ACCEPT = "ACCEPT"
    ESCALATE = "ESCALATE"
    RETURN = "RETURN"


class EscalationType:
    NONE = "NONE"
    FIELD_REVIEW = "FIELD_REVIEW"
    SECOND_APPRAISAL = "SECOND_APPRAISAL"


class EscalationStatus:
    PENDING_ASSIGNMENT = "PENDING_ASSIGNMENT"
    ASSIGNED = "ASSIGNED"
    REASSIGNMENT_REQUIRED = "REASSIGNMENT_REQUIRED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ROVStatus:
    INTAKE = "INTAKE"
    AWAITING_APPRAISER = "AWAITING_APPRAISER"
    RESPONDED = "RESPONDED"
    CLOSED_AFFIRMED = "CLOSED_AFFIRMED"
    CLOSED_REVISED = "CLOSED_REVISED"


class ROVOutcome:
    VALUE_AFFIRMED = "VALUE_AFFIRMED"
    VALUE_REVISED = "VALUE_REVISED"


class EvidenceType:
    CLOSED_SALE = "CLOSED_SALE"
    ACTIVE_LISTING_WITH_CONTRACT = "ACTIVE_LISTING_WITH_CONTRACT"
    DATA_ERROR_CITATION = "DATA_ERROR_CITATION"
    OPINION_STATEMENT = "OPINION_STATEMENT"


class InadmissibleReason:
    TYPE_NOT_ADMISSIBLE = "TYPE_NOT_ADMISSIBLE"
    MISSING_REQUIRED_ATTRIBUTE = "MISSING_REQUIRED_ATTRIBUTE"
    STALE_SALE_DATE = "STALE_SALE_DATE"
    DISTANCE_EXCEEDED = "DISTANCE_EXCEEDED"
    DUPLICATE_OF_GRID_COMP = "DUPLICATE_OF_GRID_COMP"


class DisputeBasis:
    COMP_SELECTION = "COMP_SELECTION"
    ADJUSTMENT_SUPPORT = "ADJUSTMENT_SUPPORT"
    VALUE_OPINION = "VALUE_OPINION"
    USPAP_COMPLIANCE = "USPAP_COMPLIANCE"


class DisputeStatus:
    OPEN = "OPEN"
    APPRAISER_RESPONDED = "APPRAISER_RESPONDED"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_OVERTURNED = "RESOLVED_OVERTURNED"
    RESOLVED_BY_DEFAULT = "RESOLVED_BY_DEFAULT"


class DisputeResolution:
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    BY_DEFAULT = "BY_DEFAULT"


class AppraiserPosition:
    VALUE_SUPPORTED = "VALUE_SUPPORTED"
    VALUE_AMENDED = "VALUE_AMENDED"
    NO_POSITION = "NO_POSITION"


class RevisionSourceType:
    ROV = "ROV"
    FIELD_REVIEW = "FIELD_REVIEW"
    SECOND_APPRAISAL = "SECOND_APPRAISAL"
    DISPUTE = "DISPUTE"


class PanelReviewAction:
    MONITOR = "MONITOR"
    REINSTATE = "REINSTATE"
    REMOVE = "REMOVE"


# ---------------------------------------------------------------------------
# Entity shapes
#
# Entities whose rows are append-only event records (RuleCheckResult,
# AppraiserCommunication, ValueRevision) expose only ``id`` and ``created_at``;
# they carry neither ``updated_at`` nor ``version``. Every other entity carries
# the full quartet.
# ---------------------------------------------------------------------------
class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class EventFields(TypedDict):
    id: str
    created_at: str


class LoanFile(CommonFields):
    loan_number: str
    loan_purpose: str
    market_type: str
    risk_tier: str
    loan_amount_cents: int
    contract_price_cents: Optional[int]
    borrower_display_name: str
    underwriting_status: str
    collateral_status: str
    value_of_record_appraisal_id: Optional[str]
    current_appraised_value_cents: Optional[int]
    effective_value_cents: Optional[int]
    ltv_bps: Optional[int]
    decision_impact: Optional[str]
    rov_request_count: int


class Appraiser(CommonFields):
    full_name: str
    license_number: str
    license_state: str
    panel_status: str
    probation_started_at: Optional[str]
    removal_reason: Optional[str]
    performance_score_bps: int
    lifetime_performance_score_bps: int
    revision_rate_bps: int
    total_appraisal_count: int
    substantiated_bias_count: int
    sla_miss_count: int
    open_assignment_count: int
    completed_assignment_count: int
    panel_membership_count: int


class AMC(CommonFields):
    name: str
    sla_response_hours: int
    concurrent_dispute_capacity: int
    escalation_budget_cents: int
    panel_status: str
    ytd_escalation_spend_cents: int
    sla_breach_count: int
    open_dispute_count: int


class PanelMembership(CommonFields):
    appraiser_id: str
    amc_id: str
    coverage_state: str
    tier: str
    status: str


class Appraisal(CommonFields):
    loan_file_id: str
    appraiser_id: str
    amc_id: str
    supersedes_appraisal_id: Optional[str]
    report_form_type: str
    effective_date: str
    reported_value_cents: int
    sections_present: List[str]
    exhibit_count: int
    narrative_text: str
    subject_census_tract_band: str
    review_status: str
    bias_screen_status: str
    quarantine_return_status: Optional[str]
    completeness_score_bps: Optional[int]
    eligible_comp_count: int
    closed_comp_count: int
    max_gross_adjustment_bps: Optional[int]
    max_net_adjustment_bps: Optional[int]
    indicated_value_cents: Optional[int]
    variance_vs_reported_bps: Optional[int]
    bias_risk_index: Optional[int]
    current_value_cents: Optional[int]
    rule_check_fail_count: int
    rule_check_warn_count: int


class ComparableSale(CommonFields):
    appraisal_id: str
    street_address: str
    sale_price_cents: int
    gross_adjustment_cents: int
    net_adjustment_cents: int
    distance_miles: float
    sale_date: str
    sale_status: str
    dwelling_type: str
    census_tract_band: str
    included_in_grid: bool
    adjusted_price_cents: int
    gross_adjustment_bps: int
    net_adjustment_bps: int


class RuleCheckResult(EventFields):
    appraisal_id: str
    sequence_no: int
    check_code: str
    outcome: str
    observed_value: Optional[str]
    detail: Optional[str]


class BiasIndicatorFlag(CommonFields):
    appraisal_id: str
    source: str
    indicator_code: str
    matched_text: Optional[str]
    severity_weight: int
    status: str
    adjudicated_by_user_id: Optional[str]
    rationale: Optional[str]


class AppraiserCommunication(EventFields):
    appraisal_id: str
    sender_role: str
    sender_user_id: str
    recipient: str
    intent: str
    body: str
    sent_at: str


class DeskReview(CommonFields):
    appraisal_id: str
    status: str
    created_by_user_id: str
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    risk_tier_at_review: str
    preliminary_quality_score_bps: int
    final_quality_score_bps: Optional[int]
    required_escalation: Optional[str]
    decision_action: Optional[str]
    reviewer_note: Optional[str]
    findings_note: Optional[str]
    decision_note: Optional[str]


class EscalationOrder(CommonFields):
    desk_review_id: str
    amc_id: str
    assigned_appraiser_id: Optional[str]
    escalation_type: str
    status: str
    due_at: str
    inspection_window_start: Optional[str]
    inspection_window_end: Optional[str]
    base_fee_cents: Optional[int]
    rush_surcharge_cents: Optional[int]
    discount_pct_bps: Optional[int]
    total_cost_cents: Optional[int]
    resulting_value_cents: Optional[int]
    documentation_note: Optional[str]
    cancel_reason: Optional[str]


class ROVRequest(CommonFields):
    loan_file_id: str
    appraisal_id: str
    borrower_statement: str
    requested_value_cents: int
    round_number: int
    status: str
    admissible_evidence_count: int
    response_deadline_at: Optional[str]
    appraiser_responded_at: Optional[str]
    responded_late: bool
    outcome: Optional[str]
    revised_value_cents: Optional[int]
    intake_note: Optional[str]
    response_note: Optional[str]
    next_round_reason: Optional[str]
    closure_note: Optional[str]


class ROVEvidenceItem(CommonFields):
    rov_request_id: str
    evidence_type: str
    street_address: Optional[str]
    sale_price_cents: Optional[int]
    sale_date: Optional[str]
    distance_miles: Optional[float]
    citation_note: Optional[str]
    admissible: bool
    inadmissible_reason: Optional[str]
    round_number: int


class DisputeCase(CommonFields):
    appraisal_id: str
    amc_id: str
    appraiser_id: str
    dispute_basis: str
    review_slot_start: str
    review_slot_end: str
    response_deadline_at: str
    appraiser_position: Optional[str]
    response_summary: Optional[str]
    appraiser_responded_at: Optional[str]
    responded_late: bool
    status: str
    resolution: Optional[str]
    resolved_value_cents: Optional[int]
    resolution_note: Optional[str]


class ValueRevision(EventFields):
    appraisal_id: str
    source_type: str
    source_ref_id: str
    prior_value_cents: int
    new_value_cents: int
    delta_cents: int
    delta_bps: int
    is_compensating: bool
    ltv_bps_before: Optional[int]
    ltv_bps_after: Optional[int]
    decision_impact_before: Optional[str]
    decision_impact_after: Optional[str]
    documentation_note: Optional[str]


JsonDict = Dict[str, Any]
