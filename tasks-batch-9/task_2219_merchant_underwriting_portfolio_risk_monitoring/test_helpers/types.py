"""Typed shapes for every entity the merchant-underwriting API exposes.

Three entity types are append-only and carry only ``id`` and ``created_at``
(no ``updated_at``, no ``version``): ProhibitedCategoryRule,
ReserveLedgerEntry and MerchantDayActivity. Every other entity carries the
full ``id`` / ``created_at`` / ``updated_at`` / ``version`` quartet.
"""

from __future__ import annotations

from typing import Any, Literal, Optional, TypedDict

# ---------------------------------------------------------------------------
# Enumerations (string literals, matching the API's wire representation)
# ---------------------------------------------------------------------------

Role = Literal[
    "Applicant",
    "MerchantUser",
    "UnderwritingOfficer",
    "RiskAnalyst",
    "RiskCommitteeApprover",
    "PortfolioController",
]

ApplicationState = Literal[
    "DRAFT",
    "SUBMITTED",
    "IN_VERIFICATION",
    "INFO_REQUESTED",
    "UNDERWRITING",
    "APPROVED",
    "DECLINED",
    "WITHDRAWN",
]

DeclineReasonCode = Literal[
    "PROHIBITED_CATEGORY",
    "INSUFFICIENT_CREDIT",
    "VERIFICATION_FAILED",
    "OWNERSHIP_UNVERIFIED",
]

McccDisposition = Literal["ALLOWED", "RESTRICTED_REVIEW", "PROHIBITED"]
RuleDisposition = Literal["PROHIBITED", "RESTRICTED_REVIEW"]

AssessmentMethod = Literal["LAG_WEIGHTED", "CHARGEBACK_WEIGHTED"]
CreditBand = Literal["A", "B", "C", "D"]
ReserveType = Literal["ROLLING", "CAPPED"]

VerificationStatus = Literal["PASSED", "FAILED"]
OwnerStatus = Literal["PENDING", "CLEARED", "FLAGGED_PEP", "ID_UNVERIFIED", "SANCTIONS_HIT"]

AccountState = Literal["ACTIVE", "RESTRICTED", "TERMINATED"]
FundingState = Literal["NORMAL", "DELAYED", "HELD"]
FundingHoldReasonCode = Literal[
    "SUSPECTED_LAUNDERING",
    "CARD_TESTING",
    "EXCESSIVE_CHARGEBACKS",
    "TERMINATION_PENDING",
]

ReserveAccountState = Literal["ACCRUING", "CAP_REACHED", "RELEASING", "CLOSED"]
LedgerEntryType = Literal["HOLD", "RELEASE", "OFFSET_LOSS"]
LedgerReasonCode = Literal[
    "SETTLEMENT_HOLD",
    "SCHEDULED_RELEASE",
    "BATCH_REVERSAL_RELEASE",
    "LOSS_OFFSET",
    "REINSTATEMENT_RELEASE",
]

PayoutState = Literal["SCHEDULED", "DELAYED", "HELD", "PAID", "REVERSED"]
ReversalReasonCode = Literal["RISK_HOLD", "FUNDING_ERROR", "TERMINATION", "APPEAL_REMEDY"]

ChargebackNetwork = Literal["VISA", "MASTERCARD", "AMEX", "DISCOVER"]

AlertType = Literal[
    "VELOCITY_SPIKE",
    "CARD_TESTING",
    "LAUNDERING_PATTERN",
    "CHARGEBACK_THRESHOLD",
]
AlertState = Literal["OPEN", "UNDER_REVIEW", "ESCALATED", "DISMISSED", "CLOSED"]
AlertDisposition = Literal["ACKNOWLEDGE", "DISMISS", "ESCALATE"]

ProgramState = Literal["DRAFT", "ACTIVE", "PASSED", "FAILED", "NETWORK_ESCALATED"]
NetworkProgramTier = Literal["STANDARD", "EXCESSIVE"]

TerminationReasonCode = Literal[
    "EXCESSIVE_CHARGEBACKS",
    "SUSPECTED_LAUNDERING",
    "PROHIBITED_ACTIVITY",
    "REMEDIATION_FAILURE",
]
TerminationState = Literal["PROPOSED", "APPROVED", "REJECTED", "EXECUTED", "REVERSED"]

AppealState = Literal["SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "GRANTED", "UPHELD"]
AppealOutcome = Literal["GRANT", "UPHOLD"]

ForecastMethod = Literal["EXPECTED_LOSS", "STRESSED"]

DecisionVerb = Literal["APPROVE", "DECLINE"]


# ---------------------------------------------------------------------------
# Common field groups
# ---------------------------------------------------------------------------


class VersionedRecord(TypedDict):
    """id / created_at / updated_at / version - the standard mutable entity."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyRecord(TypedDict):
    """id / created_at only - the three append-only entity types."""

    id: str
    created_at: str


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


class MerchantApplication(VersionedRecord, total=False):
    legal_business_name: str
    tax_id: str
    mcc_code: str
    country_code: str
    requested_monthly_volume_cents: int
    average_ticket_cents: int
    avg_delivery_lag_days: int
    prior_processing_history_months: int
    credit_score: int
    declared_chargeback_ratio_bps: int
    supersedes_application_id: Optional[str]
    state: ApplicationState
    outstanding_info_items: list[str]
    decline_reason_code: Optional[DeclineReasonCode]
    verification_attempt_count: int
    owner_ownership_pct_total: float
    mcc_disposition: McccDisposition
    current_assessment_method: Optional[AssessmentMethod]
    current_reserve_pct_bps: Optional[int]
    current_reserve_cap_cents: Optional[int]
    current_reserve_type: Optional[ReserveType]
    decision_officer_user_id: Optional[str]
    decided_at: Optional[str]


class BusinessVerification(VersionedRecord, total=False):
    application_id: str
    registry_match: bool
    tax_id_match: bool
    bank_account_match: bool
    address_match: bool
    mismatch_count: int
    attempt_index: int
    status: VerificationStatus
    verified_by_user_id: str


class BeneficialOwner(VersionedRecord, total=False):
    application_id: str
    full_name: str
    ownership_pct: float
    date_of_birth: str
    government_id_last4: str
    country_code: str
    sanctions_hit: bool
    pep_flag: bool
    id_verified: bool
    status: OwnerStatus
    screened_at: Optional[str]


class ProhibitedCategoryRule(AppendOnlyRecord, total=False):
    mcc_code: str
    category: str
    disposition: RuleDisposition
    reserve_uplift_bps: int
    created_by_user_id: str


class CreditAssessment(VersionedRecord, total=False):
    application_id: str
    method: AssessmentMethod
    assessment_sequence: int
    credit_band: CreditBand
    base_reserve_bps: int
    lag_uplift_bps: int
    thin_file_uplift_bps: int
    mcc_uplift_bps: int
    chargeback_uplift_bps: int
    reserve_pct_bps: int
    exposure_estimate_cents: int
    reserve_cap_cents: int
    reserve_type: ReserveType
    assessed_by_user_id: str


class Merchant(VersionedRecord, total=False):
    application_id: str
    legal_business_name: str
    mcc_code: str
    monthly_volume_limit_cents: int
    account_state: AccountState
    funding_state: FundingState
    delayed_payout_days: int
    remediation_required: bool
    pinned_reserve_pct_bps: int
    pinned_reserve_cap_cents: int
    pinned_reserve_type: ReserveType
    pinned_assessment_method: AssessmentMethod
    metrics_as_of_date: Optional[str]
    trailing_30d_txn_count: int
    trailing_30d_volume_cents: int
    trailing_30d_chargeback_count: int
    trailing_30d_chargeback_amount_cents: int
    rolling_chargeback_ratio_bps: int
    amount_based_chargeback_ratio_bps: int
    reserve_balance_cents: int
    pending_payout_cents: int
    lifetime_reversed_cents: int
    open_alert_count: int
    last_monitoring_run_date: Optional[str]
    funding_hold_reason_code: Optional[FundingHoldReasonCode]
    terminated_at: Optional[str]
    reinstated_at: Optional[str]


class ReserveAccount(VersionedRecord, total=False):
    merchant_id: str
    reserve_type: ReserveType
    reserve_pct_bps: int
    reserve_cap_cents: int
    release_lag_days: int
    total_accrued_cents: int
    released_to_date_cents: int
    offset_to_date_cents: int
    held_balance_cents: int
    state: ReserveAccountState
    last_release_tranche_end_date: Optional[str]


class ReserveLedgerEntry(AppendOnlyRecord, total=False):
    reserve_account_id: str
    settlement_batch_id: Optional[str]
    entry_type: LedgerEntryType
    amount_cents: int
    effective_date: str
    tranche_start_date: Optional[str]
    tranche_end_date: Optional[str]
    reason_code: LedgerReasonCode
    recorded_by_user_id: Optional[str]


class SettlementBatch(VersionedRecord, total=False):
    merchant_id: str
    period_start_date: str
    period_end_date: str
    gross_volume_cents: int
    day_line_count: int
    reserve_hold_cents: int
    loss_offset_from_settlement_cents: int
    reserve_offset_cents: int
    uncovered_loss_cents: int
    net_payout_cents: int
    payout_state: PayoutState
    scheduled_payout_date: Optional[str]
    paid_at: Optional[str]
    reversed_at: Optional[str]
    reversal_reason_code: Optional[ReversalReasonCode]


class MerchantDayActivity(AppendOnlyRecord, total=False):
    merchant_id: str
    business_date: str
    txn_count: int
    volume_cents: int
    distinct_card_count: int
    decline_count: int
    cross_border_count: int
    refund_cents: int
    unique_bin_count: int
    chargeback_count: int
    chargeback_amount_cents: int
    chargeback_network: Optional[ChargebackNetwork]
    avg_ticket_cents: int
    ingested_by_user_id: str


class MonitoringAlert(VersionedRecord, total=False):
    merchant_id: str
    alert_type: AlertType
    severity_score: int
    observed_metric_bps: int
    state: AlertState
    detected_on_date: str
    last_detected_on_date: str
    recurrence_count: int
    reviewed_by_user_id: Optional[str]
    review_note: Optional[str]


class RemediationProgram(VersionedRecord, total=False):
    merchant_id: str
    target_ratio_bps: int
    monitoring_month_count: int
    window_start_date: str
    window_end_date: str
    state: ProgramState
    months_elapsed: int
    consecutive_compliant_months: int
    last_observed_ratio_bps: Optional[int]
    network_program_tier: Optional[NetworkProgramTier]
    opened_by_user_id: str
    activated_by_user_id: Optional[str]


class TerminationDecision(VersionedRecord, total=False):
    merchant_id: str
    reason_code: TerminationReasonCode
    match_listing_flag: bool
    state: TerminationState
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    rejection_note: Optional[str]
    executed_at: Optional[str]
    reversed_at: Optional[str]


class Appeal(VersionedRecord, total=False):
    merchant_id: str
    termination_decision_id: str
    evidence_summary: str
    state: AppealState
    filed_on_date: str
    outstanding_info_items: list[str]
    response_round_count: int
    reviewer_user_id: Optional[str]
    reinstatement_reserve_pct_bps: Optional[int]
    decided_at: Optional[str]


class PortfolioForecast(VersionedRecord, total=False):
    as_of_date: str
    method: ForecastMethod
    stress_multiplier_bps: int
    merchant_count: int
    unpaid_exposure_cents: int
    gross_expected_loss_cents: int
    net_expected_loss_cents: int
    total_reserve_held_cents: int
    reserve_adequacy_ratio_bps: int
    coverage_gap_cents: int
    required_additional_reserve_cents: int
    projected_adequacy_ratio_bps: int
    generated_by_user_id: str


class RiskSummary(TypedDict, total=False):
    """Computed projection returned by GET /merchants/{id}/risk-summary."""

    merchant_id: str
    account_state: AccountState
    funding_state: FundingState
    rolling_chargeback_ratio_bps: int
    amount_based_chargeback_ratio_bps: int
    gating_ratio_band: str
    open_alert_count: int
    reserve_account_id: str
    reserve_type: ReserveType
    reserve_held_balance_cents: int
    reserve_releasable_cents: int
    unpaid_settlement_exposure_cents: int
    remediation_required: bool


Payload = dict[str, Any]
Headers = dict[str, str]
