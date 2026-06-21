from decimal import Decimal
from util import round_half_up

COUNT_TABLE = {
    3: 1, 4: 1, 5: 1,
    6: 2, 7: 2, 8: 2,
    9: 3, 10: 3, 11: 3,
    12: 4, 13: 4, 14: 4,
    15: 5, 16: 5,
    17: 6, 18: 6,
    19: 7,
    20: 8,
}

ADJUSTMENT_TABLE = {
    3: Decimal("-2.0"), 4: Decimal("-1.0"), 5: Decimal("0.0"),
    6: Decimal("-1.0"), 7: Decimal("0.0"), 8: Decimal("0.0"),
    9: Decimal("0.0"), 10: Decimal("0.0"), 11: Decimal("0.0"),
    12: Decimal("0.0"), 13: Decimal("0.0"), 14: Decimal("0.0"),
    15: Decimal("0.0"), 16: Decimal("0.0"),
    17: Decimal("0.0"), 18: Decimal("0.0"),
    19: Decimal("0.0"), 20: Decimal("0.0"),
}

SOFT_CAP_THRESHOLD = Decimal("3.0")
SOFT_CAP_FACTOR = Decimal("0.5")
HARD_CAP_CEILING = Decimal("5.0")


def _base_index(eligible_scores):
    """eligible_scores: list of POSTED Score dicts already filtered.
    Trim to most recent 20 by (played_on DESC, created_at DESC), then take lowest-k
    of score_differentials, average, add adjustment, round half-up to one decimal.
    Returns a Decimal or None when fewer than 3."""
    n_total = len(eligible_scores)
    if n_total < 3:
        return None

    # trim to recent 20 first (by played_on DESC, created_at DESC)
    if n_total > 20:
        recent = sorted(
            eligible_scores,
            key=lambda s: (s["played_on"], s["created_at"]),
            reverse=True,
        )[:20]
    else:
        recent = list(eligible_scores)

    n = len(recent)  # <= 20
    diffs = sorted(Decimal(str(s["score_differential"])) for s in recent)
    k = COUNT_TABLE[n]
    adj = ADJUSTMENT_TABLE[n]
    best = diffs[:k]
    mean = sum(best) / Decimal(k)
    return round_half_up(mean + adj, 1)


def compute_provisional(golfer_id, db):
    """Live running index over golfer's POSTED scores (VOID excluded), all dates."""
    eligible = [
        s for s in db.scores.values()
        if s["golfer_id"] == golfer_id and s["status"] == "POSTED"
    ]
    result = _base_index(eligible)
    if result is None:
        return None
    return float(result)


def compute_official_base(golfer_id, effective_date, db):
    """Base figure for official index: POSTED scores with played_on <= effective_date.
    Returns (Decimal base or None, list of contributing score ids)."""
    eligible = [
        s for s in db.scores.values()
        if s["golfer_id"] == golfer_id
        and s["status"] == "POSTED"
        and s["played_on"] <= effective_date
    ]
    base = _base_index(eligible)
    if base is None:
        return None, []
    # determine contributing scores (the recent-20-trim then lowest-k set)
    n_total = len(eligible)
    if n_total > 20:
        recent = sorted(
            eligible,
            key=lambda s: (s["played_on"], s["created_at"]),
            reverse=True,
        )[:20]
    else:
        recent = list(eligible)
    n = len(recent)
    k = COUNT_TABLE[n]
    # the k lowest by differential
    by_diff = sorted(recent, key=lambda s: Decimal(str(s["score_differential"])))
    contributing = [s["id"] for s in by_diff[:k]]
    return base, contributing


def apply_caps(base, low_handicap_index):
    """Apply soft then hard caps. base is a Decimal. low_handicap_index is float or None.
    Returns a Decimal final official index (rounded to 1 decimal)."""
    if low_handicap_index is None:
        return round_half_up(base, 1)

    low = Decimal(str(low_handicap_index))
    soft_threshold = low + SOFT_CAP_THRESHOLD
    if base > soft_threshold:
        capped = soft_threshold + (base - soft_threshold) * SOFT_CAP_FACTOR
    else:
        capped = base

    hard_ceiling = low + HARD_CAP_CEILING
    if capped > hard_ceiling:
        capped = hard_ceiling

    return round_half_up(capped, 1)
