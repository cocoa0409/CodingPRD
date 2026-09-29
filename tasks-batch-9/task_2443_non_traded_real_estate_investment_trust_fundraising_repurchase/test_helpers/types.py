"""Typed shapes for the Non-Traded REIT Fundraising & Repurchase API.

Field lists follow the PRD: every ``_cents`` field is an integer count of cents,
every ``_e4`` field is an integer count of ten-thousandths of a share, and every
``_bps`` field is integer basis points.

Per PRD §2.4 every persisted resource carries ``id``, ``created_at``,
``updated_at`` and ``version`` — except ``StockholderVote``, which is immutable
and carries only ``id`` and ``created_at``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


# ─── Roles (PRD §2.1, spelled precisely) ──────────────────────────────

class UserRole:
    SPONSOR_OPERATOR = "SponsorOperator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    INDEPENDENT_VALUATION_ADVISOR = "IndependentValuationAdvisor"
    TRANSFER_AGENT = "TransferAgent"
    BOARD_COMMITTEE = "BoardCommittee"
    BROKER_DEALER_REP = "BrokerDealerRep"
    INVESTOR_USER = "InvestorUser"

    ALL = (
        SPONSOR_OPERATOR,
        COMPLIANCE_OFFICER,
        INDEPENDENT_VALUATION_ADVISOR,
        TRANSFER_AGENT,
        BOARD_COMMITTEE,
        BROKER_DEALER_REP,
        INVESTOR_USER,
    )


# ─── Status vocabularies ──────────────────────────────────────────────

class RegistrationStatus:
    DRAFT = "DRAFT"
    EFFECTIVE = "EFFECTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class EscrowStatus:
    COLLECTING = "COLLECTING"
    BROKEN = "BROKEN"
    FAILED = "FAILED"


class RepurchasePlanStatus:
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class RegistrationAction:
    DECLARE_EFFECTIVE = "DECLARE_EFFECTIVE"
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"
    CLOSE = "CLOSE"


class EscrowAction:
    BREAK = "BREAK"
    FAIL = "FAIL"


class RepurchasePlanAction:
    SUSPEND = "SUSPEND"
    RESUME = "RESUME"
    TERMINATE = "TERMINATE"


class ShareClassStatus:
    ACTIVE = "ACTIVE"
    CLOSED_TO_NEW = "CLOSED_TO_NEW"


class ClassCode:
    T = "T"
    S = "S"
    D = "D"
    I = "I"


class SuitabilityStatus:
    INCOMPLETE = "INCOMPLETE"
    DOCUMENTED = "DOCUMENTED"
    FLAGGED = "FLAGGED"


class AccountStatus:
    ACTIVE = "ACTIVE"
    CLOSED_NO_POSITION = "CLOSED_NO_POSITION"


class SupervisionStatus:
    IN_GOOD_STANDING = "IN_GOOD_STANDING"
    HEIGHTENED_SUPERVISION = "HEIGHTENED_SUPERVISION"
    BARRED = "BARRED"


class SellingAgreementStatus:
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class FindingAction:
    RECORD = "RECORD"
    RESOLVE = "RESOLVE"


class FindingSeverity:
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class SubscriptionStatus:
    PENDING = "PENDING"
    ESCROWED = "ESCROWED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    REFUNDED = "REFUNDED"
    RESCINDED = "RESCINDED"


class ShareLotStatus:
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    RESCINDED = "RESCINDED"


class NavRecordStatus:
    DRAFT = "DRAFT"
    ADVISOR_REVIEW = "ADVISOR_REVIEW"
    ADVISOR_CONFIRMED = "ADVISOR_CONFIRMED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class DeclarationStatus:
    DECLARED = "DECLARED"
    SUPERSEDED = "SUPERSEDED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class DeclarationAction:
    PAY = "PAY"
    CANCEL = "CANCEL"


class RepurchasePeriodStatus:
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    PROCESSED = "PROCESSED"
    CANCELLED = "CANCELLED"


class RepurchaseRequestStatus:
    QUEUED = "QUEUED"
    HELD = "HELD"
    FULFILLED = "FULFILLED"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class HardshipType:
    NONE = "NONE"
    DEATH = "DEATH"
    DISABILITY = "DISABILITY"


class LiquidityEventStatus:
    PROPOSED = "PROPOSED"
    BOARD_APPROVED = "BOARD_APPROVED"
    VOTE_OPEN = "VOTE_OPEN"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    ABANDONED = "ABANDONED"


class LiquidityEventAction:
    BOARD_APPROVE = "BOARD_APPROVE"
    OPEN_VOTE = "OPEN_VOTE"
    CLOSE_VOTE = "CLOSE_VOTE"
    EXECUTE = "EXECUTE"
    ABANDON = "ABANDON"


class LiquidityEventType:
    LISTING = "LISTING"
    MERGER = "MERGER"
    ASSET_SALE = "ASSET_SALE"


class VoteChoice:
    FOR = "FOR"
    AGAINST = "AGAINST"
    ABSTAIN = "ABSTAIN"


# ─── Entity shapes ────────────────────────────────────────────────────

class _Versioned(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Offering(_Versioned):
    name: str
    minimum_offering_amount_cents: int
    maximum_offering_amount_cents: int
    escrow_deadline_date: str
    initial_offering_price_cents: int
    rescission_window_days: int
    registration_status: str
    escrow_status: str
    repurchase_plan_status: str
    repurchase_plan_suspension_reason: Optional[str]
    escrow_balance_cents: int
    gross_proceeds_cents: int
    aggregate_nav_cents: int


class ShareClass(_Versioned):
    offering_id: str
    class_code: str
    upfront_selling_commission_bps: int
    dealer_manager_fee_bps: int
    annual_distribution_fee_bps: int
    distribution_fee_cap_bps: int
    converts_to_class_code: Optional[str]
    status: str
    shares_outstanding_e4: int


class Investor(_Versioned):
    legal_name: str
    email: str
    state_code: str
    net_worth_cents: int
    annual_income_cents: int
    concentration_limit_cents: int
    suitability_status: str
    suitability_documentation_reference: Optional[str]
    account_status: str
    cumulative_invested_cents: int
    total_shares_e4: int
    cumulative_distributions_received_cents: int
    cumulative_early_repurchase_deduction_cents: int


class BrokerDealer(_Versioned):
    firm_name: str
    crd_number: str
    supervision_status: str
    suspended_agreement_count: int


class SellingAgreement(_Versioned):
    offering_id: str
    broker_dealer_id: str
    max_commission_bps: int
    suitability_documentation_required: bool
    status: str
    open_minor_finding_count: int
    open_major_finding_count: int


class Subscription(_Versioned):
    offering_id: str
    share_class_id: str
    investor_id: str
    selling_agreement_id: str
    gross_investment_cents: int
    transaction_price_cents: int
    upfront_selling_commission_cents: int
    dealer_manager_fee_cents: int
    net_invested_cents: int
    shares_issued_e4: int
    unapplied_cash_cents: int
    status: str
    rejection_reason: Optional[str]
    accepted_at: Optional[str]


class ShareLot(_Versioned):
    subscription_id: str
    investor_id: str
    share_class_id: str
    converted_from_share_class_id: Optional[str]
    issued_date: str
    original_shares_e4: int
    remaining_shares_e4: int
    gross_offering_price_cents: int
    distribution_fee_cap_cents: int
    cumulative_distribution_fee_cents: int
    status: str


class NavRecord(_Versioned):
    share_class_id: str
    period_start_date: str
    period_end_date: str
    gross_asset_value_cents: int
    other_liabilities_cents: int
    shares_outstanding_e4_snapshot: int
    accrued_distribution_payable_cents: int
    nav_per_share_pre_accrual_cents: int
    nav_per_share_cents: int
    variance_bps: int
    status: str
    advisor_opinion_reference: Optional[str]
    rejection_reason: Optional[str]


class DistributionDeclaration(_Versioned):
    offering_id: str
    record_date: str
    payment_date: str
    declared_per_share_cents: int
    gaap_net_income_cents: int
    adjusted_cash_flow_cents: int
    board_uncovered_acknowledgement: bool
    total_declared_cents: int
    coverage_ratio_gaap_bps: int
    coverage_ratio_cash_bps: int
    return_of_capital_bps: int
    gaap_return_of_capital_bps: int
    total_distribution_fee_accrued_cents: int
    status: str


class RepurchasePeriod(_Versioned):
    offering_id: str
    period_month: str
    quarter_key: str
    opens_at: str
    request_cutoff_at: str
    settlement_date: str
    monthly_cap_cents: int
    quarterly_remaining_cents: int
    capacity_cents: int
    settled_amount_cents: int
    prorated: bool
    status: str


class RepurchaseRequest(_Versioned):
    repurchase_period_id: str
    investor_id: str
    share_class_id: str
    shares_requested_e4: int
    hardship_type: str
    requested_value_cents: int
    approved_value_cents: int
    approved_shares_e4: int
    early_repurchase_deduction_cents: int
    net_proceeds_cents: int
    status: str


class LiquidityEvent(_Versioned):
    offering_id: str
    event_type: str
    proposed_effective_date: str
    record_date_shares_e4: int
    votes_for_e4: int
    votes_against_e4: int
    votes_abstain_e4: int
    quorum_met: bool
    status: str


class StockholderVote(TypedDict):
    """PRD §2.4: a ballot carries only ``id`` and ``created_at``."""

    id: str
    created_at: str
    liquidity_event_id: str
    investor_id: str
    choice: str
    voting_shares_e4: int


class InvestorStatement(TypedDict):
    investor_id: str
    total_shares_e4: int
    open_lot_count: int
    cumulative_invested_cents: int
    cumulative_distributions_received_cents: int
    cumulative_early_repurchase_deduction_cents: int
    estimated_value_cents: int


class ClockState(TypedDict):
    current_utc: str
    previous_utc: str


Json = Dict[str, Any]
JsonList = List[Json]
