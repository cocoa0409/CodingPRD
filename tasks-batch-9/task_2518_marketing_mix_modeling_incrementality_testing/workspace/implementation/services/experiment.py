"""Experiment power, holdout share, occupancy and lift read-out (PRD section 3.6)."""

from datetime import timedelta
from decimal import Decimal

import db as store
from db import db
from errors import ApiError
from services.numeric import D, HUNDRED, ONE, ZERO, dsqrt, q2, q4, q6

TWO = Decimal(2)

POWER_FLOOR = Decimal("0.80")
HOLDOUT_SHARE_PCT = 20
REDESIGN_LIMIT = 2
Z_SCORE = Decimal("1.96")

# Strict less-than ladder, first match wins (PRD 3.6).
POWER_STEPS = (
    (Decimal("1.0000"), Decimal("0.2000")),
    (Decimal("1.6000"), Decimal("0.4500")),
    (Decimal("2.0000"), Decimal("0.6500")),
    (Decimal("2.5000"), Decimal("0.7500")),
    (Decimal("2.8000"), Decimal("0.8000")),
    (Decimal("3.2400"), Decimal("0.9000")),
)
POWER_TOP = Decimal("0.9500")

OCCUPYING_STATUSES = ("DESIGN_LOCKED", "CELLS_ASSIGNED", "RUNNING", "READ_OUT", "ACCEPTED")


def power_index(experiment):
    rate = D(experiment["baseline_conversion_rate"])
    smaller_arm = min(experiment["planned_treatment_population"],
                      experiment["planned_control_population"])
    inner = D(smaller_arm) * rate / (TWO * (ONE - rate))
    return q4(D(experiment["minimum_detectable_effect_pct"]) / HUNDRED * dsqrt(inner))


def computed_power(index):
    for threshold, power in POWER_STEPS:
        if index < threshold:
            return power
    return POWER_TOP


def assert_holdout_share(market, additional_population):
    """(held_out + additional) * 100 must not exceed 20 * total_population."""
    left = (market["held_out_population"] + additional_population) * 100
    right = HOLDOUT_SHARE_PCT * market["total_population"]
    if left > right:
        raise ApiError("ERR_HOLDOUT_SHARE_EXCEEDED",
                       "The held-out share would exceed 20 percent of the market population.")


def assert_channel_unoccupied(experiment):
    """The washout buffer extends the incumbent's tail only; touching windows are allowed."""
    candidate_start = experiment["_start_date"]
    candidate_end = experiment["_end_date"]
    for other in db.all("experiments"):
        if other["id"] == experiment["id"]:
            continue
        if other["market_id"] != experiment["market_id"]:
            continue
        if other["channel_id"] != experiment["channel_id"]:
            continue
        if other["status"] not in OCCUPYING_STATUSES:
            continue
        incumbent_end = other["_end_date"] + timedelta(days=other["washout_days"])
        if candidate_start < incumbent_end and other["_start_date"] < candidate_end:
            raise ApiError("ERR_EXPERIMENT_WINDOW_CONFLICT",
                           "Another experiment already occupies this channel over that window.")


def read_out_lift(experiment, treatment_conversions, control_conversions,
                  pre_treatment_conversions, pre_control_conversions):
    """Returns the four lift figures plus the synthetic-control weight (or None)."""
    treatment_population = D(experiment["treatment_population"])
    control_population = D(experiment["control_population"])

    t_post = D(treatment_conversions) / treatment_population
    c_post = D(control_conversions) / control_population
    t_pre = D(pre_treatment_conversions) / treatment_population
    c_pre = D(pre_control_conversions) / control_population

    if experiment["readout_method"] == "SYNTHETIC_CONTROL":
        weight = q6(t_pre / c_pre)
        scaled = weight * c_post
        measured = q2(HUNDRED * (t_post - scaled) / scaled)
    else:
        weight = None
        difference = (t_post - t_pre) - (c_post - c_pre)
        measured = q2(HUNDRED * difference / c_post)

    pooled = (D(treatment_conversions) + D(control_conversions)) / \
        (treatment_population + control_population)
    variance = pooled * (ONE - pooled) * (ONE / treatment_population + ONE / control_population)
    standard_error = dsqrt(variance)
    half_width = q2(HUNDRED * Z_SCORE * standard_error / c_post)

    return {
        "measured_lift_pct": measured,
        "lift_ci_half_width_pct": half_width,
        "lift_ci_low_pct": q2(measured - half_width),
        "lift_ci_high_pct": q2(measured + half_width),
        "synthetic_control_weight": weight,
    }
