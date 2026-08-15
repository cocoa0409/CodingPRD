"""Serialize internal entity dicts to wire format (datetime -> ISO string)."""
from services.clock import format_iso

_DT_FIELDS = {
    "season_start_date", "season_end_date", "window_start", "window_end",
    "executed_at", "term_start", "term_end", "due_date", "paid_at",
    "scheduled_kickoff_utc", "actual_air_start_utc", "reporting_period_end",
    "requested_window_start", "requested_window_end", "blackout_start",
    "blackout_end", "matching_window_end",
}

_INT_FIELDS = {
    "total_package_pool", "guaranteed_rating_basis_points", "active_package_count",
    "minimum_bid_cents", "games_committed", "round_number", "offered_fee_cents",
    "fee_cap_cents", "production_commitment_games", "base_fee_cents",
    "total_contracted_fee_cents", "audience_commitment_basis_points",
    "cumulative_rating_basis_points", "accrued_shortfall_liability_cents",
    "accrued_make_good_credit_cents", "payment_delinquency_count",
    "season_index", "sequence_in_season", "base_amount_cents",
    "escalated_amount_cents", "late_fee_cents", "games_required",
    "games_delivered", "shortfall_games", "make_good_credit_cents",
    "credit_settled_cents", "rating_basis_points", "proposed_fee_cents",
    "version",
}

_FLOAT_FIELDS = {
    "upfront_pct", "escalator_rate_pct", "minimum_growth_pct",
    "audience_commitment_pct", "milestone_weight", "league_share_pct",
}


_INTERNAL_FIELDS = {"posture_frozen_since", "shortfall_declared_at"}


def serialize(entity):
    out = {}
    for k, v in entity.items():
        if k in _INTERNAL_FIELDS:
            continue
        if v is None:
            out[k] = None
        elif k in _DT_FIELDS:
            out[k] = format_iso(v)
        elif k in ("created_at", "updated_at", "detected_at"):
            out[k] = v if isinstance(v, str) else format_iso(v)
        elif k in _INT_FIELDS:
            out[k] = int(v)
        elif k in _FLOAT_FIELDS:
            out[k] = float(v)
        else:
            out[k] = v
    return out
