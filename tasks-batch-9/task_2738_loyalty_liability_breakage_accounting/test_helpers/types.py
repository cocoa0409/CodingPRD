"""
The field inventory of every resource the API returns.

Each entity gets one tuple of the fields the contract declares for it, plus the
common system fields where the entity carries them. Tests use these tuples to
assert that a representation is complete and that immutable ledger rows really
do lack the mutable-entity system fields.
"""

from typing import Dict, Tuple

# ─── Common system fields ────────────────────────────────────────────────────
# Every mutable entity carries all four.
COMMON_FIELDS: Tuple[str, ...] = ("id", "created_at", "updated_at", "version")

# An immutable ledger row carries only these two.
IMMUTABLE_COMMON_FIELDS: Tuple[str, ...] = ("id", "created_at")

# The system fields an immutable ledger row must NOT expose.
MUTABLE_ONLY_FIELDS: Tuple[str, ...] = ("updated_at", "version")


# ─── Declared and computed fields, entity by entity ──────────────────────────
LOYALTY_PROGRAM_FIELDS: Tuple[str, ...] = (
    "name",
    "currency_code",
    "status",
    "ssp_millicents_per_point",
    "point_expiry_days",
    "per_issuance_point_cap",
    "tier_multiplier_bp",
    "promo_multiplier_cap_bp",
    "breakage_method",
    "historical_redemption_rate_bp",
    "escheat_disclosure_threshold_cents",
    "current_breakage_rate_bp",
    "total_escheat_accrual_cents",
    "escheat_disclosure_required",
    "total_deferred_revenue_cents",
    "recognized_breakage_ytd_cents",
)

STATE_EXPIRY_RULE_FIELDS: Tuple[str, ...] = (
    "program_id",
    "state_code",
    "expiry_permitted",
    "min_dormancy_days",
    "escheatment_required",
    "escheat_rate_bp",
)

COHORT_FIELDS: Tuple[str, ...] = (
    "program_id",
    "cohort_code",
    "enrollment_start_date",
    "enrollment_end_date",
    "observed_redemption_rate_bp",
    "sample_size",
    "program_change_adjustment_bp",
)

MEMBER_FIELDS: Tuple[str, ...] = (
    "program_id",
    "cohort_id",
    "external_member_ref",
    "state_code",
    "tier",
    "status",
    "enrolled_at",
    "last_activity_at",
    "dormancy_days",
    "point_balance",
    "outstanding_gross_ssp_cents",
)

ACCOUNTING_PERIOD_FIELDS: Tuple[str, ...] = (
    "program_id",
    "period_code",
    "start_at",
    "end_at",
    "state",
    "opening_liability_cents",
    "issuance_deferred_cents",
    "redemption_recognized_cents",
    "remeasurement_delta_cents",
    "expiry_released_cents",
    "escheat_accrual_cents",
    "pre_catchup_liability_cents",
    "required_liability_cents",
    "catch_up_adjustment_cents",
    "breakage_recognized_cents",
    "closing_liability_cents",
    "approved_estimate_rate_bp",
    "soft_closed_at",
    "reopen_count",
)

PARTNER_AGREEMENT_FIELDS: Tuple[str, ...] = (
    "program_id",
    "partner_code",
    "relationship_type",
    "issuance_rate_millicents_per_point",
    "redemption_rate_millicents_per_point",
    "settlement_lag_days",
    "net_settlement_enabled",
    "min_invoice_cents",
    "effective_start_date",
    "effective_end_date",
    "status",
    "deferred_below_minimum_cents",
    "outstanding_settlement_cents",
)

POINT_LOT_FIELDS: Tuple[str, ...] = (
    "member_id",
    "period_id",
    "partner_agreement_id",
    "base_points",
    "promo_multiplier_bp",
    "tier_multiplier_bp_at_issue",
    "ssp_millicents_per_point_at_issue",
    "breakage_rate_bp_at_issue",
    "tier_points",
    "points_issued",
    "points_remaining",
    "gross_ssp_cents",
    "breakage_reserve_cents",
    "deferred_revenue_cents",
    "tier_benefit_expense_cents",
    "promo_expense_cents",
    "remaining_gross_ssp_cents",
    "remaining_deferred_cents",
    "expired_gross_ssp_cents",
    "escheated_cents",
    "issued_at",
    "expires_at",
    "lifecycle_state",
    "settlement_state",
)

# The four configuration values a lot pins at issuance and never re-reads.
POINT_LOT_PINNED_FIELDS: Tuple[str, ...] = (
    "tier_multiplier_bp_at_issue",
    "ssp_millicents_per_point_at_issue",
    "breakage_rate_bp_at_issue",
    "expires_at",
)

REDEMPTION_EVENT_FIELDS: Tuple[str, ...] = (
    "member_id",
    "period_id",
    "partner_agreement_id",
    "points_requested",
    "redemption_type",
    "state",
    "provisional_release_cents",
    "final_release_cents",
    "remeasurement_delta_cents",
    "partner_cost_cents",
    "requested_at",
    "allocated_at",
    "reversal_reason",
)

REDEMPTION_ALLOCATION_FIELDS: Tuple[str, ...] = (
    "redemption_event_id",
    "point_lot_id",
    "entry_type",
    "allocation_seq",
    "points_allocated",
    "provisional_release_cents",
    "final_release_cents",
    "line_gross_ssp_cents",
)

BREAKAGE_ESTIMATE_FIELDS: Tuple[str, ...] = (
    "program_id",
    "period_id",
    "cohort_id",
    "supersedes_estimate_id",
    "method_applied",
    "estimated_redemption_rate_bp",
    "breakage_rate_bp",
    "outstanding_points_at_estimate",
    "outstanding_gross_ssp_cents_at_estimate",
    "required_liability_cents",
    "memo_narrative",
    "sensitivity_low_bp",
    "sensitivity_high_bp",
    "state",
    "prepared_by_user_id",
    "approved_by_user_id",
    "rejection_reason",
    "revision_count",
    "submitted_at",
    "approved_at",
)

SETTLEMENT_STATEMENT_FIELDS: Tuple[str, ...] = (
    "partner_agreement_id",
    "period_id",
    "state",
    "settlement_basis",
    "partner_issued_points",
    "partner_redeemed_points",
    "issuance_receivable_cents",
    "redemption_payable_cents",
    "carried_forward_cents",
    "net_due_cents",
    "deferred_below_minimum_cents",
    "due_date",
    "dispute_reason",
    "resolution_note",
    "write_off_reason",
    "dispute_count",
    "issued_at",
    "paid_at",
)

PROGRAM_CHANGE_ORDER_FIELDS: Tuple[str, ...] = (
    "program_id",
    "change_type",
    "new_point_expiry_days",
    "new_ssp_millicents_per_point",
    "new_tier_multiplier_bp",
    "behavior_elasticity_bp",
    "effective_at",
    "state",
    "baseline_redemption_rate_bp",
    "projected_redemption_rate_bp",
    "baseline_outstanding_gross_ssp_cents",
    "projected_outstanding_gross_ssp_cents",
    "projected_liability_delta_cents",
    "applied_at",
    "cancelled_by_order_id",
)


# ─── Computed read shapes ────────────────────────────────────────────────────
LIABILITY_ROLLFORWARD_FIELDS: Tuple[str, ...] = (
    "opening_liability_cents",
    "issuance_deferred_cents",
    "redemption_recognized_cents",
    "remeasurement_delta_cents",
    "expiry_released_cents",
    "pre_catchup_liability_cents",
    "outstanding_gross_ssp_cents",
    "required_liability_cents",
    "catch_up_adjustment_cents",
    "closing_liability_cents",
    "breakage_recognized_cents",
    "approved_estimate_rate_bp",
)

SENSITIVITY_FIELDS: Tuple[str, ...] = (
    "outstanding_gross_ssp_cents",
    "low_bp",
    "base_bp",
    "high_bp",
    "low_required_liability_cents",
    "base_required_liability_cents",
    "high_required_liability_cents",
    "band_range_cents",
    "memo_narrative",
)


# ─── Lookup by entity name ───────────────────────────────────────────────────
ENTITY_FIELDS: Dict[str, Tuple[str, ...]] = {
    "LoyaltyProgram": LOYALTY_PROGRAM_FIELDS,
    "StateExpiryRule": STATE_EXPIRY_RULE_FIELDS,
    "Cohort": COHORT_FIELDS,
    "Member": MEMBER_FIELDS,
    "AccountingPeriod": ACCOUNTING_PERIOD_FIELDS,
    "PartnerAgreement": PARTNER_AGREEMENT_FIELDS,
    "PointLot": POINT_LOT_FIELDS,
    "RedemptionEvent": REDEMPTION_EVENT_FIELDS,
    "RedemptionAllocation": REDEMPTION_ALLOCATION_FIELDS,
    "BreakageEstimate": BREAKAGE_ESTIMATE_FIELDS,
    "SettlementStatement": SETTLEMENT_STATEMENT_FIELDS,
    "ProgramChangeOrder": PROGRAM_CHANGE_ORDER_FIELDS,
}

# Every entity except the immutable allocation ledger carries the common fields.
IMMUTABLE_ENTITIES: Tuple[str, ...] = ("RedemptionAllocation",)


def expected_fields(entity_name: str) -> Tuple[str, ...]:
    """The full field list of an entity's representation, system fields included."""
    declared = ENTITY_FIELDS[entity_name]
    if entity_name in IMMUTABLE_ENTITIES:
        return IMMUTABLE_COMMON_FIELDS + declared
    return COMMON_FIELDS + declared


# ─── Envelope shapes ─────────────────────────────────────────────────────────
# An error body carries exactly these two keys.
ERROR_ENVELOPE_FIELDS: Tuple[str, ...] = ("error_id", "message")

# Every response, whatever its status, carries these three top-level keys.
ENVELOPE_TOP_LEVEL_FIELDS: Tuple[str, ...] = ("meta", "response_type", "data")

# The meta keys present on every response.
ENVELOPE_META_FIELDS: Tuple[str, ...] = ("api_request_id", "api_request_timestamp")

# The extra meta keys a list read adds.
PAGINATION_META_FIELDS: Tuple[str, ...] = ("limit", "offset", "total_count", "has_more")

RESPONSE_TYPE_OBJECT = "object"
RESPONSE_TYPE_ARRAY = "array"
RESPONSE_TYPE_ERROR = "error"
