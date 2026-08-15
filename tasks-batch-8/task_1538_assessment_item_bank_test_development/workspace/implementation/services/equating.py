"""Equating: mean/sigma scaling coefficients over anchor p_value_final (PRD §3.7).

Nested rounding order is pinned: p_value_final is rounded to 4 decimals when the
FINAL row is written; mean and population SD are computed over those rounded
values; slope/intercept are then rounded to 6 decimals ROUND_HALF_UP.
"""
from decimal import Decimal

from db import db
from errors import raise_error, ERR_ANCHOR_SET_TOO_HOMOGENEOUS
from services.stats import round6, to_float


def _most_recent_final_p_value(item_id, now_dt):
    """Most recent FINAL ItemStatistic for the item whose window's end_utc is on or
    before the program clock. Returns the stored (4-dp rounded) p_value as Decimal."""
    best = None
    best_end = None
    for stat in db["item_statistics"].values():
        if stat["item_id"] != item_id or stat["stats_kind"] != "FINAL":
            continue
        window = db["field_test_windows"].get(stat["window_id"])
        if window is None:
            continue
        end_dt = window["_end_dt"]
        if end_dt > now_dt:
            continue
        if best_end is None or end_dt > best_end or (end_dt == best_end and stat.get("_seq", 0) > best.get("_seq", 0)):
            best_end = end_dt
            best = stat
    if best is None:
        return None
    return Decimal(str(best["p_value"]))


def compute_scaling(anchor_item_ids, now_dt):
    """Mean/sigma equating over anchor items' rounded p_value_final values.

    Returns (scaling_slope, scaling_intercept) as floats rounded to 6 dp.
    Raises ERR_ANCHOR_SET_TOO_HOMOGENEOUS when fewer than two anchors carry a usable
    FINAL statistic or when the anchor p_values have zero variance.
    """
    values = []
    for item_id in anchor_item_ids:
        pv = _most_recent_final_p_value(item_id, now_dt)
        if pv is not None:
            values.append(pv)
    if len(values) < 2:
        raise_error(
            ERR_ANCHOR_SET_TOO_HOMOGENEOUS,
            "fewer than two anchor items carry a usable FINAL statistic",
        )
    n = Decimal(len(values))
    mean = sum(values) / n
    var = sum((v - mean) * (v - mean) for v in values) / n
    sd = var.sqrt()
    if sd == 0:
        raise_error(
            ERR_ANCHOR_SET_TOO_HOMOGENEOUS,
            "anchor p_value_final set has zero variance",
        )
    # Source and target sets are the same anchor items' FINAL p_values.
    mean_src, sd_src = mean, sd
    mean_tgt, sd_tgt = mean, sd
    slope = round6(sd_tgt / sd_src)
    intercept = round6(mean_tgt - (sd_tgt / sd_src) * mean_src)
    return to_float(slope), to_float(intercept)
