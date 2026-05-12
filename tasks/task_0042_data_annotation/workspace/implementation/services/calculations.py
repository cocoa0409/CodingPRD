"""Core calculation rules: piece-rate, bonus/penalty, consistency, sample size."""

import math

from money import round_half_up, round_half_up_4dp
from config import (
    DIFFICULTY_MULTIPLIER,
    TIER_MULTIPLIER,
    BONUS_BAND,
    PENALTY_BAND,
    BONUS_RATE,
    PENALTY_RATE,
    SENIOR_SAMPLE_RATE,
    EXPERT_SAMPLE_RATE,
    GOLDEN_RATIO,
    MAX_DEFECT_RATIO,
    CONSISTENCY_LOW_THRESHOLD,
)


def piece_rate_amount(*, base_unit_price_cents: int, item_count: int,
                       difficulty: str, tier: str) -> int:
    """Pinned: round per-item rate first, then multiply by item_count."""
    multiplier = DIFFICULTY_MULTIPLIER[difficulty] * TIER_MULTIPLIER[tier]
    per_item_raw = base_unit_price_cents * multiplier
    per_item_rounded = round_half_up(per_item_raw)
    return per_item_rounded * item_count


def bonus_or_penalty(gross_cents: int, package_pass_rate: float,
                      target: float):
    """Returns (kind, signed_cents) or (None, 0)."""
    if package_pass_rate >= target + BONUS_BAND:
        return "BONUS", round_half_up(gross_cents * BONUS_RATE)
    if package_pass_rate <= target - PENALTY_BAND:
        return "PENALTY", -round_half_up(gross_cents * PENALTY_RATE)
    return None, 0


def sample_size_for_inspection(item_count: int, tier: str) -> int:
    if tier == "JUNIOR":
        return item_count
    if tier == "SENIOR":
        return math.ceil(SENIOR_SAMPLE_RATE * item_count)
    if tier == "EXPERT":
        return math.ceil(EXPERT_SAMPLE_RATE * item_count)
    return item_count


def golden_inserted_count(item_count: int) -> int:
    return math.floor(item_count * GOLDEN_RATIO)


def is_pass(defects_found: int, sample_size: int) -> bool:
    if sample_size <= 0:
        return defects_found == 0
    return (defects_found / sample_size) <= MAX_DEFECT_RATIO


def inspection_pass_rate(defects_found: int, sample_size: int) -> float:
    if sample_size <= 0:
        return 1.0
    return round_half_up_4dp(1 - defects_found / sample_size)


# --- Consistency scoring -------------------------------------------------

def _cohen_kappa(labels_a, labels_b) -> float:
    n = len(labels_a)
    if n == 0:
        return 0.0
    agree = sum(1 for i in range(n) if labels_a[i] == labels_b[i])
    po = agree / n

    # Marginal probabilities by class.
    classes = set(labels_a) | set(labels_b)

    def _hashable(x):
        # JSON-safe normalization for label keys.
        if isinstance(x, (str, int, float, bool)) or x is None:
            return x
        return repr(x)

    counts_a, counts_b = {}, {}
    for x in labels_a:
        counts_a[_hashable(x)] = counts_a.get(_hashable(x), 0) + 1
    for x in labels_b:
        counts_b[_hashable(x)] = counts_b.get(_hashable(x), 0) + 1

    pe = 0.0
    for c in {_hashable(x) for x in classes}:
        pa = counts_a.get(c, 0) / n
        pb = counts_b.get(c, 0) / n
        pe += pa * pb
    if abs(1 - pe) < 1e-12:
        kappa = 1.0 if po == 1.0 else 0.0
    else:
        kappa = (po - pe) / (1 - pe)
    return max(0.0, kappa)


def _iou_pair(a, b) -> float:
    """IoU of two boxes/keypoints/segmentations represented as dicts with
    x, y, w, h or {area_a, area_b, intersection}."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    # Treat as axis-aligned rectangles {x, y, w, h}
    try:
        ax, ay, aw, ah = a["x"], a["y"], a["w"], a["h"]
        bx, by, bw, bh = b["x"], b["y"], b["w"], b["h"]
    except (KeyError, TypeError):
        return 1.0 if a == b else 0.0
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    if union <= 0:
        return 1.0
    return inter / union


def _iou_mean(labels_a, labels_b) -> float:
    n = len(labels_a)
    if n == 0:
        return 0.0
    s = sum(_iou_pair(labels_a[i], labels_b[i]) for i in range(n))
    return s / n


def _f1_tokens(labels_a, labels_b) -> float:
    """Token-level F1 across all aligned items."""
    tp = fp = fn = 0
    for la, lb in zip(labels_a, labels_b):
        ta = la if isinstance(la, list) else (la.split() if isinstance(la, str) else [])
        tb = lb if isinstance(lb, list) else (lb.split() if isinstance(lb, str) else [])
        from collections import Counter
        ca, cb = Counter(ta), Counter(tb)
        for tok, cnt in ca.items():
            common = min(cnt, cb.get(tok, 0))
            tp += common
            fp += cnt - common
        for tok, cnt in cb.items():
            common = min(cnt, ca.get(tok, 0))
            fn += cnt - common
    if tp + fp == 0 or tp + fn == 0:
        return 0.0 if tp == 0 else 1.0
    precision = tp / (tp + fp)
    recall = tp / (tp + fn)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def consistency_score(task_type: str, labels_a, labels_b) -> float:
    if task_type in ("CLASSIFICATION", "TEXT_NER"):
        score = _cohen_kappa(labels_a, labels_b)
    elif task_type in ("BBOX", "SEGMENTATION", "KEYPOINT"):
        score = _iou_mean(labels_a, labels_b)
    elif task_type == "AUDIO_TRANSCRIPTION":
        score = _f1_tokens(labels_a, labels_b)
    else:
        score = 0.0
    return round_half_up_4dp(max(0.0, min(1.0, score)))


def is_low_consistency(score: float) -> bool:
    return score < CONSISTENCY_LOW_THRESHOLD


def golden_correct_count(submitted_labels, golden_indices, golden_expected):
    """Count how many of the inserted golden positions match expected_label."""
    correct = 0
    for idx, expected in zip(golden_indices, golden_expected):
        if idx < len(submitted_labels) and submitted_labels[idx] == expected:
            correct += 1
    return correct
