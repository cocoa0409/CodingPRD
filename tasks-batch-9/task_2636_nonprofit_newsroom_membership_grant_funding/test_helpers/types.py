"""Domain types for the Nonprofit Newsroom Funding API.

Status enums, entity TypedDicts and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    DEVELOPMENT_OFFICER = "DevelopmentOfficer"
    EDITORIAL_DIRECTOR = "EditorialDirector"
    FINANCE_CONTROLLER = "FinanceController"
    BOARD_OVERSIGHT = "BoardOversight"
    MEMBER = "Member"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------

class FiscalPeriodStatus(str, Enum):
    OPEN = "OPEN"
    REVIEW_LOCKED = "REVIEW_LOCKED"
    CLOSED = "CLOSED"


class SustainabilityPosture(str, Enum):
    HEALTHY = "HEALTHY"
    WATCH = "WATCH"
    CONSTRAINED = "CONSTRAINED"
    CRITICAL = "CRITICAL"


class SustainabilityBasis(str, Enum):
    RECOGNIZED = "RECOGNIZED"
    PIPELINE = "PIPELINE"


class MembershipTierStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class RenewalCadence(str, Enum):
    MONTHLY = "MONTHLY"
    ANNUAL = "ANNUAL"


class FulfillmentType(str, Enum):
    TOTE_BAG = "TOTE_BAG"
    EVENT_ACCESS = "EVENT_ACCESS"
    NEWSLETTER = "NEWSLETTER"
    BOOK = "BOOK"
    MERCH_DISCOUNT = "MERCH_DISCOUNT"


class MemberStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class MemberLifecycleAction(str, Enum):
    RENEW = "RENEW"
    REINSTATE = "REINSTATE"
    CANCEL = "CANCEL"


class CoverageAreaDisclosureStatus(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"


class PublicationGate(str, Enum):
    OPEN = "OPEN"
    BLOCKED = "BLOCKED"


class FunderType(str, Enum):
    FOUNDATION = "FOUNDATION"
    INDIVIDUAL = "INDIVIDUAL"
    CORPORATE = "CORPORATE"
    GOVERNMENT = "GOVERNMENT"


class FunderStatus(str, Enum):
    PROSPECT = "PROSPECT"
    CLEARED = "CLEARED"
    RESTRICTED = "RESTRICTED"


class RiskBasis(str, Enum):
    SELF_ATTESTED = "SELF_ATTESTED"
    AUDITED = "AUDITED"


class ClearanceDecision(str, Enum):
    CLEAR = "CLEAR"
    RESTRICT = "RESTRICT"


class FirewallDisclosureStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REATTESTATION_REQUIRED = "REATTESTATION_REQUIRED"
    SUPERSEDED = "SUPERSEDED"
    VOID = "VOID"


class ReattestationReason(str, Enum):
    FUNDER_RESTRICTED = "FUNDER_RESTRICTED"
    INFLUENCE_CONTACT = "INFLUENCE_CONTACT"


class ContactType(str, Enum):
    ROUTINE_STEWARDSHIP = "ROUTINE_STEWARDSHIP"
    COVERAGE_INQUIRY = "COVERAGE_INQUIRY"
    CONDITION_ATTEMPT = "CONDITION_ATTEMPT"
    EDITORIAL_DIRECTION_REQUEST = "EDITORIAL_DIRECTION_REQUEST"


class GiftOfferStatus(str, Enum):
    PROPOSED = "PROPOSED"
    INDEPENDENCE_REVIEW = "INDEPENDENCE_REVIEW"
    CONDITIONS_REQUESTED = "CONDITIONS_REQUESTED"
    CLEARED = "CLEARED"
    DECLINED = "DECLINED"
    ACCEPTED = "ACCEPTED"


class Designation(str, Enum):
    UNRESTRICTED = "UNRESTRICTED"
    PROGRAM_RESTRICTED = "PROGRAM_RESTRICTED"
    PROJECT_RESTRICTED = "PROJECT_RESTRICTED"


class GiftReviewDecision(str, Enum):
    CLEAR = "CLEAR"
    REQUEST_CONDITIONS = "REQUEST_CONDITIONS"
    DECLINE = "DECLINE"


class GrantProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    INDEPENDENCE_REVIEW = "INDEPENDENCE_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    CLEARED = "CLEARED"
    SUBMITTED = "SUBMITTED"
    AWARDED = "AWARDED"
    SUSPENDED = "SUSPENDED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    CLOSED = "CLOSED"


class RestrictionType(str, Enum):
    UNRESTRICTED = "UNRESTRICTED"
    PROGRAM_RESTRICTED = "PROGRAM_RESTRICTED"
    PROJECT_RESTRICTED = "PROJECT_RESTRICTED"


class ReportingCadence(str, Enum):
    NONE = "NONE"
    SEMIANNUAL = "SEMIANNUAL"
    ANNUAL = "ANNUAL"


class ComplianceFlag(str, Enum):
    COMPLIANT = "COMPLIANT"
    DELINQUENT = "DELINQUENT"


class SuspendedReason(str, Enum):
    FIREWALL_BREACH = "FIREWALL_BREACH"
    REPORT_DELINQUENCY = "REPORT_DELINQUENCY"


class PipelineAction(str, Enum):
    SUBMIT_FOR_REVIEW = "SUBMIT_FOR_REVIEW"
    REVISE = "REVISE"
    SUBMIT = "SUBMIT"
    WITHDRAW = "WITHDRAW"


class InternalReviewDecision(str, Enum):
    CLEAR = "CLEAR"
    REQUEST_REVISION = "REQUEST_REVISION"


class GrantOutcome(str, Enum):
    AWARDED = "AWARDED"
    DECLINED = "DECLINED"


class GrantReportStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"
    OVERDUE = "OVERDUE"
    WAIVED = "WAIVED"


class ReportReviewDecision(str, Enum):
    ACCEPT = "ACCEPT"
    RETURN = "RETURN"


class RevenueStream(str, Enum):
    MEMBERSHIP = "MEMBERSHIP"
    MAJOR_GIFT = "MAJOR_GIFT"
    GRANTS = "GRANTS"
    EVENTS = "EVENTS"
    SYNDICATION = "SYNDICATION"


class SettlementStatus(str, Enum):
    INITIATED = "INITIATED"
    SETTLED = "SETTLED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class AcknowledgmentStatus(str, Enum):
    UNACKNOWLEDGED = "UNACKNOWLEDGED"
    RECEIPTED = "RECEIPTED"
    DISCLOSED = "DISCLOSED"


class SettlementOutcome(str, Enum):
    SETTLED = "SETTLED"
    FAILED = "FAILED"


class CollaborationStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"
    DISSOLVED = "DISSOLVED"


class CollaborationAction(str, Enum):
    ACTIVATE = "ACTIVATE"
    SETTLE = "SETTLE"
    DISSOLVE = "DISSOLVE"


class CollaborationPartnerStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    WITHDRAWN = "WITHDRAWN"


class FiscalPeriodAction(str, Enum):
    LOCK = "LOCK"
    UNLOCK = "UNLOCK"
    CLOSE = "CLOSE"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------

class FiscalPeriod(TypedDict):
    id: str
    label: str
    start_date: str
    end_date: str
    status: str
    monthly_expense_base_cents: int
    reserve_balance_cents: int
    recognized_revenue_cents: int
    stream_shares_bps: Dict[str, int]
    concentration_hhi: int
    top_source_share_bps: int
    reserve_months_target: int
    operating_reserve_target_cents: int
    reserve_months_ratio_bps: int
    sustainability_posture: str
    restricted_release_cap_pct_bps: int
    board_override_active: bool
    board_override_justification: Optional[str]
    locked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MembershipTier(TypedDict):
    id: str
    tier_code: str
    name: str
    renewal_cadence: str
    contribution_amount_cents: int
    grace_period_days: int
    benefits: List[Dict[str, Any]]
    benefit_count: int
    insubstantial_benefit_codes: List[str]
    quid_pro_quo_per_period_cents: int
    insubstantial_threshold_cents: int
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    tier_id: str
    email: str
    full_name: str
    employer: Optional[str]
    linked_funder_id: Optional[str]
    status: str
    cycle_start_date: Optional[str]
    next_renewal_date: Optional[str]
    grace_expires_at: Optional[str]
    lifetime_giving_cents: int
    consecutive_renewals: int
    is_major_donor: bool
    cultivation_locked: bool
    created_at: str
    updated_at: str
    version: int


class CoverageArea(TypedDict):
    id: str
    area_code: str
    name: str
    editorial_lead_user_id: str
    disclosure_status: str
    publication_gate: str
    restricted_grant_count: int
    disclosed_funder_count: int
    created_at: str
    updated_at: str
    version: int


class Funder(TypedDict):
    id: str
    legal_name: str
    funder_type: str
    affiliated_coverage_area_id: Optional[str]
    self_attested_advocacy: bool
    audited_advocacy_index: Optional[int]
    risk_basis: str
    prior_editorial_requests_count: int
    reporting_reliability_bps: int
    independence_risk_score: int
    status: str
    cultivated_by_user_id: str
    cleared_by_user_id: Optional[str]
    lifetime_committed_cents: int
    restricted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GiftOffer(TypedDict):
    id: str
    funder_id: str
    coverage_area_id: Optional[str]
    fiscal_period_id: str
    offered_amount_cents: int
    designation: str
    donor_conditions: Optional[str]
    status: str
    stewardship_fee_cents: int
    net_acceptable_amount_cents: int
    board_ratification_required: bool
    acceptance_gate_score: int
    solicited_by_user_id: str
    cleared_by_user_id: Optional[str]
    board_ratified_by_user_id: Optional[str]
    conditions_round_count: int
    created_at: str
    updated_at: str
    version: int


class GrantProposal(TypedDict):
    id: str
    funder_id: str
    coverage_area_id: Optional[str]
    fiscal_period_id: str
    title: str
    requested_amount_cents: int
    restriction_type: str
    restriction_start_date: Optional[str]
    restriction_end_date: Optional[str]
    reporting_cadence: str
    award_probability_bps: int
    status: str
    revision_round_count: int
    awarded_amount_cents: int
    released_cents: int
    unreleased_cents: int
    returned_cents: int
    compliance_flag: str
    award_date: Optional[str]
    report_count: int
    drafted_by_user_id: str
    cleared_by_user_id: Optional[str]
    suspended_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GrantReport(TypedDict):
    id: str
    grant_proposal_id: str
    sequence_no: int
    period_start: str
    period_end: str
    due_date: str
    status: str
    allocated_release_cents: int
    consumed_release_cents: int
    spend_reported_cents: Optional[int]
    variance_bps: Optional[int]
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Contribution(TypedDict):
    id: str
    fiscal_period_id: str
    member_id: Optional[str]
    funder_id: Optional[str]
    gift_offer_id: Optional[str]
    collaboration_id: Optional[str]
    revenue_stream: str
    amount_cents: int
    received_date: str
    source_label: Optional[str]
    settlement_status: str
    acknowledgment_status: str
    quid_pro_quo_cents: int
    deductible_cents: int
    receipt_number: Optional[str]
    refunded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FirewallDisclosure(TypedDict):
    id: str
    funder_id: str
    coverage_area_id: str
    supersedes_disclosure_id: Optional[str]
    disclosure_text: str
    status: str
    attested_by_user_id: str
    attested_at: str
    reattestation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InfluenceContact(TypedDict):
    """An influence contact is immutable and append-only: it carries only
    id and created_at from the common properties -- no updated_at, no version."""

    id: str
    funder_id: str
    coverage_area_id: Optional[str]
    contact_type: str
    occurred_at: str
    summary: str
    logged_by_user_id: str
    severity_weight: int
    triggered_restriction: bool
    created_at: str


class Collaboration(TypedDict):
    id: str
    coverage_area_id: str
    fiscal_period_id: str
    title: str
    window_start: str
    window_end: str
    total_cost_cents: int
    lead_credit_bps: int
    lead_cost_share_bps: int
    status: str
    partner_count: int
    lead_cost_cents: int
    allocated_cost_cents: int
    syndication_revenue_cents: int
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CollaborationPartner(TypedDict):
    id: str
    collaboration_id: str
    partner_org_name: str
    credit_share_bps: int
    cost_share_bps: int
    cost_owed_cents: int
    remainder_rank: int
    status: str
    withdrawn_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
