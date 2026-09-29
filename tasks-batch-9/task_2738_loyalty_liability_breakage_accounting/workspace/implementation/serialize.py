"""Resource serialisers.

Field names come straight from the scaffold's entity table. Datetime values are
rendered as ISO-8601 UTC with three fractional digits; derived-on-read figures
are recomputed here and never persisted.
"""
from datetime import datetime

import calc
from util import iso

COMMON = ("created_at", "updated_at", "version")


def _pick(rec, names):
    out = {}
    for name in names:
        value = rec.get(name)
        if isinstance(value, datetime):
            value = iso(value)
        out[name] = value
    return out


PROGRAM_FIELDS = (
    "id", "name", "currency_code", "status", "ssp_millicents_per_point",
    "point_expiry_days", "per_issuance_point_cap", "tier_multiplier_bp",
    "promo_multiplier_cap_bp", "breakage_method", "historical_redemption_rate_bp",
    "escheat_disclosure_threshold_cents", "current_breakage_rate_bp",
    "total_escheat_accrual_cents", "escheat_disclosure_required",
) + COMMON

RULE_FIELDS = (
    "id", "program_id", "state_code", "expiry_permitted", "min_dormancy_days",
    "escheatment_required", "escheat_rate_bp",
) + COMMON

COHORT_FIELDS = (
    "id", "program_id", "cohort_code", "enrollment_start_date",
    "enrollment_end_date", "observed_redemption_rate_bp", "sample_size",
    "program_change_adjustment_bp",
) + COMMON

MEMBER_FIELDS = (
    "id", "program_id", "cohort_id", "external_member_ref", "state_code", "tier",
    "status", "enrolled_at", "last_activity_at",
) + COMMON

PERIOD_FIELDS = (
    "id", "program_id", "period_code", "start_at", "end_at", "state",
    "opening_liability_cents", "issuance_deferred_cents",
    "redemption_recognized_cents", "remeasurement_delta_cents",
    "expiry_released_cents", "escheat_accrual_cents",
    "pre_catchup_liability_cents", "required_liability_cents",
    "catch_up_adjustment_cents", "breakage_recognized_cents",
    "closing_liability_cents", "approved_estimate_rate_bp", "soft_closed_at",
    "reopen_count",
) + COMMON

AGREEMENT_FIELDS = (
    "id", "program_id", "partner_code", "relationship_type",
    "issuance_rate_millicents_per_point", "redemption_rate_millicents_per_point",
    "settlement_lag_days", "net_settlement_enabled", "min_invoice_cents",
    "effective_start_date", "effective_end_date", "status",
    "deferred_below_minimum_cents", "outstanding_settlement_cents",
) + COMMON

LOT_FIELDS = (
    "id", "member_id", "period_id", "partner_agreement_id", "base_points",
    "promo_multiplier_bp", "tier_multiplier_bp_at_issue",
    "ssp_millicents_per_point_at_issue", "breakage_rate_bp_at_issue",
    "tier_points", "points_issued", "points_remaining", "gross_ssp_cents",
    "breakage_reserve_cents", "deferred_revenue_cents",
    "tier_benefit_expense_cents", "promo_expense_cents",
    "expired_gross_ssp_cents", "escheated_cents", "issued_at", "expires_at",
    "lifecycle_state", "settlement_state",
) + COMMON

EVENT_FIELDS = (
    "id", "member_id", "period_id", "partner_agreement_id", "points_requested",
    "redemption_type", "state", "provisional_release_cents",
    "final_release_cents", "remeasurement_delta_cents", "partner_cost_cents",
    "requested_at", "allocated_at", "reversal_reason",
) + COMMON

ALLOCATION_FIELDS = (
    "id", "redemption_event_id", "point_lot_id", "entry_type", "allocation_seq",
    "points_allocated", "provisional_release_cents", "final_release_cents",
    "line_gross_ssp_cents", "created_at",
)

ESTIMATE_FIELDS = (
    "id", "program_id", "period_id", "cohort_id", "supersedes_estimate_id",
    "method_applied", "estimated_redemption_rate_bp", "breakage_rate_bp",
    "outstanding_points_at_estimate", "outstanding_gross_ssp_cents_at_estimate",
    "required_liability_cents", "memo_narrative", "sensitivity_low_bp",
    "sensitivity_high_bp", "state", "prepared_by_user_id", "approved_by_user_id",
    "rejection_reason", "revision_count", "submitted_at", "approved_at",
) + COMMON

STATEMENT_FIELDS = (
    "id", "partner_agreement_id", "period_id", "state", "settlement_basis",
    "partner_issued_points", "partner_redeemed_points",
    "issuance_receivable_cents", "redemption_payable_cents",
    "carried_forward_cents", "net_due_cents", "deferred_below_minimum_cents",
    "due_date", "dispute_reason", "resolution_note", "write_off_reason",
    "dispute_count", "issued_at", "paid_at",
) + COMMON

ORDER_FIELDS = (
    "id", "program_id", "change_type", "new_point_expiry_days",
    "new_ssp_millicents_per_point", "new_tier_multiplier_bp",
    "behavior_elasticity_bp", "effective_at", "state",
    "baseline_redemption_rate_bp", "projected_redemption_rate_bp",
    "baseline_outstanding_gross_ssp_cents",
    "projected_outstanding_gross_ssp_cents", "projected_liability_delta_cents",
    "applied_at", "cancelled_by_order_id",
) + COMMON


def program(rec):
    out = _pick(rec, PROGRAM_FIELDS)
    out["total_deferred_revenue_cents"] = calc.program_total_deferred_revenue_cents(rec["id"])
    out["recognized_breakage_ytd_cents"] = calc.program_recognized_breakage_ytd_cents(rec["id"])
    return out


def state_expiry_rule(rec):
    return _pick(rec, RULE_FIELDS)


def cohort(rec):
    return _pick(rec, COHORT_FIELDS)


def member(rec):
    out = _pick(rec, MEMBER_FIELDS)
    out["dormancy_days"] = calc.member_dormancy_days(rec)
    out["point_balance"] = calc.member_point_balance(rec["id"])
    out["outstanding_gross_ssp_cents"] = calc.member_outstanding_gross_ssp_cents(rec["id"])
    return out


def period(rec):
    return _pick(rec, PERIOD_FIELDS)


def partner_agreement(rec):
    return _pick(rec, AGREEMENT_FIELDS)


def point_lot(rec):
    out = _pick(rec, LOT_FIELDS)
    out["remaining_gross_ssp_cents"] = calc.lot_remaining_gross_ssp_cents(rec)
    out["remaining_deferred_cents"] = calc.lot_remaining_deferred_cents(rec)
    return out


def redemption_event(rec):
    return _pick(rec, EVENT_FIELDS)


def allocation(rec):
    return _pick(rec, ALLOCATION_FIELDS)


def breakage_estimate(rec):
    return _pick(rec, ESTIMATE_FIELDS)


def settlement_statement(rec):
    return _pick(rec, STATEMENT_FIELDS)


def change_order(rec):
    return _pick(rec, ORDER_FIELDS)
