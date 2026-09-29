"""Calibration multiplier derivation and platform reconciliation (PRD 3.7, 3.9)."""

from decimal import Decimal

import db as store
from db import db
from errors import ApiError
from services import ordering
from services.numeric import D, HUNDRED, ZERO, q2, q4

MULTIPLIER_MIN = Decimal("0.25")
MULTIPLIER_MAX = Decimal("4.00")
ALIGNED_LOW = Decimal("0.95")
ALIGNED_HIGH = Decimal("1.05")
MATERIALITY_PCT = Decimal("15.00")


def model_implied_lift_pct(run, contribution):
    """The share of non-channel sales the model attributes to this channel."""
    units = D(contribution["contribution_units"])
    residual = D(run["modeled_sales_units"]) - units
    if residual == 0:
        raise ApiError("ERR_CALIBRATION_MULTIPLIER_OUT_OF_RANGE",
                       "The model implies no residual sales to lift against.")
    return q4(HUNDRED * units / residual)


def calibration_figures(run, contribution, experiment):
    implied = model_implied_lift_pct(run, contribution)
    if implied == 0:
        raise ApiError("ERR_CALIBRATION_MULTIPLIER_OUT_OF_RANGE",
                       "The model implies zero lift for this channel.")
    experiment_lift = D(experiment["measured_lift_pct"])
    raw = experiment_lift / implied
    if raw < MULTIPLIER_MIN or raw > MULTIPLIER_MAX:
        raise ApiError("ERR_CALIBRATION_MULTIPLIER_OUT_OF_RANGE",
                       "The calibration multiplier %s falls outside 0.25 to 4.00." % q4(raw))
    multiplier = q4(raw)
    if multiplier < ALIGNED_LOW:
        bias = "OVER_ATTRIBUTED"
    elif multiplier > ALIGNED_HIGH:
        bias = "UNDER_ATTRIBUTED"
    else:
        bias = "ALIGNED"
    return {
        "experiment_lift_pct": experiment_lift,
        "model_implied_lift_pct": implied,
        "calibration_multiplier": multiplier,
        "bias_direction": bias,
    }


def build_reconciliation(run, platform_lines):
    """Per-line percentages are rounded first, then revenue-weighted (PRD 3.9)."""
    contributions = store.contributions_of_run(run["id"], current_only=True)
    by_channel = {c["channel_id"]: c for c in contributions}
    seen = []
    for line in platform_lines:
        channel_id = line["channel_id"]
        if channel_id in seen:
            raise ApiError("ERR_PLATFORM_LINE_MISMATCH",
                           "platform_lines repeats a channel.")
        seen.append(channel_id)
        if channel_id not in by_channel:
            raise ApiError("ERR_PLATFORM_LINE_MISMATCH",
                           "platform_lines names a channel with no current contribution row.")
    for channel_id in by_channel:
        if channel_id not in seen:
            raise ApiError("ERR_PLATFORM_LINE_MISMATCH",
                           "platform_lines omits a channel that carries a current contribution row.")

    basis = "CALIBRATED" if run["calibration_status"] == "CALIBRATED" else "RAW"
    field = ("calibrated_contribution_revenue_cents" if basis == "CALIBRATED"
             else "contribution_revenue_cents")

    lines_by_channel = {line["channel_id"]: line for line in platform_lines}
    ordered = ordering.by_channel_code(contributions)

    variance_lines = []
    platform_total = 0
    model_total = 0
    weighted_numerator = ZERO
    for contribution in ordered:
        channel_id = contribution["channel_id"]
        platform_cents = lines_by_channel[channel_id]["platform_revenue_cents"]
        model_cents = contribution[field]
        variance_cents = platform_cents - model_cents
        if model_cents == 0:
            variance_pct = Decimal("0.00")
        else:
            variance_pct = q2(HUNDRED * D(variance_cents) / D(model_cents))
        variance_lines.append({
            "channel_id": channel_id,
            "platform_revenue_cents": platform_cents,
            "model_cents": model_cents,
            "variance_cents": variance_cents,
            "variance_pct": variance_pct,
        })
        platform_total += platform_cents
        model_total += model_cents
        weighted_numerator += variance_pct * D(model_cents)

    if model_total == 0:
        weighted = Decimal("0.00")
    else:
        weighted = q2(weighted_numerator / D(model_total))
    flag = "MATERIAL" if abs(weighted) >= MATERIALITY_PCT else "IMMATERIAL"
    return {
        "variance_lines": variance_lines,
        "platform_reported_revenue_cents": platform_total,
        "model_attributed_revenue_cents": model_total,
        "total_variance_cents": platform_total - model_total,
        "weighted_variance_pct": weighted,
        "attribution_gap_flag": flag,
        "basis": basis,
    }
