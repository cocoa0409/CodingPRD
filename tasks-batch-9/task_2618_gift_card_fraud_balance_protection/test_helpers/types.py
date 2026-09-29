"""TypedDict shapes for every entity the PRD declares.

Common identity fields: "every entity carries id, created_at, updated_at and
version" — except LedgerEvent, BalanceInquiry and LawEnforcementReferral, which
"carry only id and created_at" because they are append-only and immutable.
Those three shapes therefore deliberately omit updated_at and version.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class CreateOnlyFields(TypedDict):
    id: str
    created_at: str


class RiskPolicy(CommonFields):
    inquiry_velocity_window_minutes: int
    inquiry_velocity_threshold: int
    redemption_window_minutes: int
    drain_watch_score_threshold: int
    drain_restrict_score_threshold: int
    digital_hold_score_threshold: int
    digital_decline_score_threshold: int
    bulk_identity_threshold_cents: int
    bulk_quantity_limit: int
    rack_shrink_threshold: int
    rack_seal_break_threshold: int
    floor_heightened_alert_threshold: int
    claim_window_days: int
    claim_evidence_round_limit: int
    reissue_cap_cents: int
    recovery_factor_bps: int
    provisional_reserve_rate_bps: int
    final_reserve_rate_bps: int


class RetailStore(CommonFields):
    name: str
    region_code: str
    address_line: str
    floor_posture: str
    tampered_rack_count: int
    suspect_rack_count: int
    open_alert_count: int
    declined_issuance_count: int


class CardRack(CommonFields):
    store_id: str
    rack_label: str
    expected_card_count: int
    tamper_state: str
    observed_card_count: Optional[int]
    seal_breaks_observed: Optional[int]
    missing_card_count: int
    last_audit_at: Optional[str]
    remediation_note: Optional[str]


class GiftCard(CommonFields):
    channel: str
    store_id: Optional[str]
    rack_id: Optional[str]
    reissued_from_card_id: Optional[str]
    card_number_masked: Optional[str]
    activation_state: str
    risk_posture: str
    face_value_cents: int
    current_balance_cents: int
    held_amount_cents: int
    available_balance_cents: int
    total_loaded_cents: int
    total_redeemed_cents: int
    drawdown_ratio: float
    distinct_merchant_count: int
    recent_redemption_count: int
    drain_risk_score_inquiry: int
    drain_risk_score_redemption: int
    activated_at: Optional[str]
    closed_at: Optional[str]


class IssuanceRequest(CommonFields):
    channel: str
    store_id: Optional[str]
    rack_id: Optional[str]
    card_id: Optional[str]
    bulk_order_id: Optional[str]
    pos_terminal_id: Optional[str]
    packaging_seal_intact: Optional[bool]
    face_value_cents: int
    device_reputation_score: Optional[int]
    email_age_days: Optional[int]
    payment_risk_band: Optional[str]
    recipient_email_hash: Optional[str]
    state: str
    screening_score: Optional[int]
    screening_components: Optional[Dict[str, int]]
    decline_reason: Optional[str]
    review_note: Optional[str]
    decided_by_user_id: Optional[str]
    screened_at: Optional[str]


class LedgerEvent(CreateOnlyFields):
    card_id: str
    merchant_store_id: Optional[str]
    reverses_event_id: Optional[str]
    type: str
    amount_cents: int
    signed_amount_cents: int
    occurred_at: str
    pos_terminal_id: Optional[str]
    memo: Optional[str]
    created_by_user_id: str


class BalanceInquiry(CreateOnlyFields):
    card_id: str
    channel: str
    requester_ip_hash: str
    occurred_at: str
    velocity_count_at_inquiry: int
    drain_score_at_inquiry: int
    balance_disclosed_cents: int


class RedemptionHold(CommonFields):
    card_id: str
    amount_cents: int
    hold_start: str
    hold_expires_at: str
    state: str
    disposition: Optional[str]
    settle_note: Optional[str]
    captured_amount_cents: int


class BulkPurchaseOrder(CommonFields):
    store_id: str
    card_quantity: int
    face_value_cents_each: int
    purchaser_name: str
    payment_method: str
    face_value_subtotal_cents: int
    fee_rate_bps: int
    activation_fee_cents: int
    total_cents: int
    state: str
    identity_id_type: Optional[str]
    identity_id_number_hash: Optional[str]
    identity_id_expiry_date: Optional[str]
    info_request_count: int
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]


class DrainingAlert(CommonFields):
    card_id: str
    detection_basis: str
    state: str
    exposure_cents: int
    basis_velocity_count: int
    basis_drain_score: int
    note: Optional[str]
    redemption_pattern_reviewed: Optional[bool]
    triaged_by_user_id: Optional[str]
    triage_note: Optional[str]
    resolution: Optional[str]
    resolved_by_user_id: Optional[str]
    resolution_note: Optional[str]
    reopen_count: int


class VictimClaim(CommonFields):
    card_id: str
    alert_id: Optional[str]
    reissued_card_id: Optional[str]
    claimant_name: str
    claimant_contact: str
    purchase_receipt_ref: Optional[str]
    packaging_photo_ref: Optional[str]
    disputed_amount_cents: int
    purchased_at: str
    state: str
    evidence_round: int
    missing_evidence_kinds: Optional[List[str]]
    unauthorized_line_count: Optional[int]
    gross_reissue_cents: Optional[int]
    reissue_amount_cents: Optional[int]
    residual_transfer_cents: Optional[int]
    intake_user_id: str
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    rescind_reason: Optional[str]


class LawEnforcementReferral(CreateOnlyFields):
    alert_id: str
    agency_name: str
    case_reference: Optional[str]
    packet_summary: str
    exposure_snapshot_cents: int
    referred_by_user_id: str
    referred_at: str


class ResellerListing(CommonFields):
    card_id: str
    reseller_partner_id: str
    marketplace_name: str
    asking_price_cents: int
    listed_balance_cents: int
    state: str
    block_reason: Optional[str]
    validation_note: Optional[str]
    validated_by_user_id: Optional[str]


class LiabilityPeriod(CommonFields):
    label: str
    period_start: str
    period_end: str
    state: str
    outstanding_liability_cents: Optional[int]
    gross_exposure_cents: Optional[int]
    reserve_basis_alert_count: Optional[int]
    provisional_reserve_cents: Optional[int]
    final_reserve_cents: Optional[int]
    unauthorized_writeoff_cents: int
    restatement_count: int
    closed_at: Optional[str]
    restated_at: Optional[str]
    close_note: Optional[str]
    restatement_note: Optional[str]


class ExposureSummary(TypedDict):
    net_funded_liability_cents: int
    funded_card_count: int
    unauthorized_writeoff_cents: int
    outstanding_liability_cents: Optional[int]
    gross_exposure_cents: Optional[int]
    provisional_reserve_cents: Optional[int]
    final_reserve_cents: Optional[int]
    in_period_alert_count: int
    confirmed_alert_count: int


class ClockReading(TypedDict):
    current_utc: str
    expired_hold_count: int


AnyEntity = Dict[str, Any]
