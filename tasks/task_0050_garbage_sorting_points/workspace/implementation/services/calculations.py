"""Business calculations (scaffold §1.3).

Encapsulates:
  - disposal_points_award (effective weight, accuracy multiplier, bonuses, daily cap)
  - violation_deduction (repeat-window escalation)
  - ranking_score (weekly/monthly/yearly leaderboards)
  - rule_effectiveness_score
  - consecutive_disposal_days
"""

from __future__ import annotations

import datetime as dt
from typing import Iterable

from db import db
from services.common import calendar_day, parse_iso8601_utc, round_half_up


# ----- Constants -----

VOLUME_TO_WEIGHT_KG_PER_L = {
    "RECYCLABLE": 0.150,
    "HAZARDOUS": 0.500,
    "KITCHEN": 0.800,
    "OTHER": 0.300,
}

VIOLATION_DEDUCTION_BY_TYPE = {
    "MIS_SORTING": 20,
    "LITTERING": 50,
    "NO_CLASSIFICATION": 30,
}

# Largest-tier-min <= count
REPEAT_ESCALATION_TIERS = [
    (1, 1.00),
    (2, 1.50),
    (3, 2.00),
    (4, 3.00),
]


# =========================================================================
# Disposal points award
# =========================================================================

def _accuracy_multiplier(scoring_method: str, accuracy_score: float) -> float:
    if scoring_method == "MANUAL":
        return 0.50 + 0.50 * accuracy_score
    if scoring_method == "AI":
        if accuracy_score >= 0.80:
            return 1.00
        if accuracy_score >= 0.50:
            return 0.70
        return 0.40
    # SCALE
    return 1.00


def compute_effective_weight_kg(weight_kg, volume_liters, actual_category: str) -> float:
    if weight_kg is not None:
        return float(weight_kg)
    factor = VOLUME_TO_WEIGHT_KG_PER_L[actual_category]
    return float(round_half_up(volume_liters * factor, 3))


def compute_disposal_points(
    *,
    rule: dict,
    scoring_method: str,
    accuracy_score: float,
    effective_weight_kg: float,
    consecutive_disposal_days: int,
    disposal_time_utc: dt.datetime,
    community_timezone: str,
    household_id: str,
    exclude_disposal_id: str | None = None,
) -> dict:
    """Compute the disposal points award per scaffold §1.3 disposal_points_award.

    Returns a dict with: base_points, bonus, raw_points, awarded_points,
    cap_overflow_points, effective_weight_kg, accuracy_multiplier.
    """
    accuracy_mult = _accuracy_multiplier(scoring_method, accuracy_score)
    base_points = int(round_half_up(
        rule["base_rate_per_kg"] * effective_weight_kg * accuracy_mult,
        0,
    ))

    bonus = 0
    if consecutive_disposal_days >= rule["bonus_consecutive_threshold_days"]:
        consecutive_bonus = int(round_half_up(
            base_points * (rule["bonus_consecutive_multiplier"] - 1.0),
            0,
        ))
        bonus += consecutive_bonus

    from services.common import to_zone
    local_hour = to_zone(disposal_time_utc, community_timezone).hour
    if rule["peak_period_start_hour"] <= local_hour < rule["peak_period_end_hour"]:
        bonus += int(rule["peak_period_bonus_flat"])

    bonus += int(rule["category_bonus_flat"])

    raw_points = base_points + bonus

    # Daily cap: sum of DISPOSAL_CREDIT for this household where
    # calendar_day(created_at, community.timezone) == calendar_day(disposal_time, community.timezone)
    cap_target_day = calendar_day(disposal_time_utc, community_timezone)
    already_credited_today = 0
    for tx in db.points_transactions.values():
        if tx["household_id"] != household_id:
            continue
        if tx["kind"] != "DISPOSAL_CREDIT":
            continue
        if exclude_disposal_id is not None and tx.get("related_entity_id") == exclude_disposal_id:
            continue
        tx_day = calendar_day(parse_iso8601_utc(tx["created_at"]), community_timezone)
        if tx_day == cap_target_day:
            already_credited_today += tx["amount"]

    headroom = max(0, int(rule["daily_cap_points"]) - already_credited_today)
    awarded_points = min(raw_points, headroom)
    cap_overflow_points = raw_points - awarded_points

    return {
        "base_points": base_points,
        "bonus": bonus,
        "raw_points": raw_points,
        "awarded_points": awarded_points,
        "cap_overflow_points": cap_overflow_points,
        "effective_weight_kg": effective_weight_kg,
        "accuracy_multiplier": accuracy_mult,
    }


# =========================================================================
# Violation deduction
# =========================================================================

def pick_escalation_multiplier(repeat_count: int) -> float:
    chosen = 1.00
    for min_count, mult in REPEAT_ESCALATION_TIERS:
        if repeat_count >= min_count:
            chosen = mult
    return chosen


def count_repeat_in_window(
    *,
    resident_id: str,
    violation_type: str,
    occurred_at_utc: dt.datetime,
    include_this_id: str | None,
    exclude_ids: set[str] | None = None,
    window_days: int = 30,
) -> int:
    """Count Violation rows for the same resident & type, status IN
    {NEW, APPEALED, UNDER_REVIEW, UPHELD}, whose occurred_at falls within
    the trailing window ending at `occurred_at_utc` (inclusive of `occurred_at_utc`).

    `include_this_id` allows counting a violation about to be created
    (provide the new violation's id, after it's been stored in db).
    """
    exclude_ids = exclude_ids or set()
    statuses = {"NEW", "APPEALED", "UNDER_REVIEW", "UPHELD"}
    window_start = occurred_at_utc - dt.timedelta(days=window_days)
    count = 0
    for v in db.violations.values():
        if v["id"] in exclude_ids:
            continue
        if v["resident_id"] != resident_id:
            continue
        if v["violation_type"] != violation_type:
            continue
        if v["status"] not in statuses:
            continue
        v_occ = parse_iso8601_utc(v["occurred_at"])
        if window_start < v_occ <= occurred_at_utc:
            count += 1
    return count


def compute_violation_deduction(
    *,
    violation_type: str,
    repeat_count: int,
) -> dict:
    base = VIOLATION_DEDUCTION_BY_TYPE[violation_type]
    mult = pick_escalation_multiplier(repeat_count)
    final = int(round_half_up(base * mult, 0))
    return {
        "base_deduction_points": base,
        "escalation_multiplier": mult,
        "final_deduction_points": final,
    }


# =========================================================================
# Consecutive disposal days streak
# =========================================================================

def compute_consecutive_disposal_days(
    resident_id: str,
    community_timezone: str,
    *,
    now_utc: dt.datetime,
) -> int:
    days = set()
    for d in db.disposals.values():
        if d["resident_id"] != resident_id:
            continue
        if d["status"] not in ("COMMITTED", "CORRECTED"):
            continue
        days.add(calendar_day(parse_iso8601_utc(d["disposal_time"]), community_timezone))
    if not days:
        return 0
    today = calendar_day(now_utc, community_timezone)
    streak = 0
    cur = today
    while cur in days:
        streak += 1
        cur = cur - dt.timedelta(days=1)
    return streak


# =========================================================================
# Ranking score
# =========================================================================

def compute_leaderboard(period: dict) -> list[dict]:
    """Compute the leaderboard array for a ranking period per scaffold §1.3."""
    community_id = period["community_id"]
    granularity = period["granularity"]
    dimension = period["dimension"]
    window_start = parse_iso8601_utc(period["window_start"])
    window_end = parse_iso8601_utc(period["window_end"])

    # Eligible disposals & violations
    eligible_disposals = []
    for d in db.disposals.values():
        if d.get("community_id") != community_id:
            continue
        if d["status"] != "COMMITTED":
            continue
        dt_d = parse_iso8601_utc(d["disposal_time"])
        if window_start <= dt_d < window_end:
            eligible_disposals.append(d)

    eligible_violations = []
    for v in db.violations.values():
        if v.get("community_id") != community_id:
            continue
        if v["status"] != "UPHELD":
            continue
        v_occ = parse_iso8601_utc(v["occurred_at"])
        if window_start <= v_occ < window_end:
            eligible_violations.append(v)

    # Build per-subject sums depending on dimension
    earned_by_subject: dict[tuple[str, str], int] = {}
    deducted_by_subject: dict[tuple[str, str], int] = {}

    def subject_for_disposal(d: dict) -> tuple[str, str] | None:
        if dimension == "HOUSEHOLD":
            return ("HOUSEHOLD", d["household_id"])
        if dimension == "BUILDING":
            hh = db.households.get(d["household_id"])
            if hh is None:
                return None
            return ("BUILDING", hh["building_code"])
        if dimension == "COMMUNITY":
            return ("COMMUNITY", community_id)
        return None

    def subject_for_violation(v: dict) -> tuple[str, str] | None:
        if dimension == "HOUSEHOLD":
            return ("HOUSEHOLD", v["household_id"])
        if dimension == "BUILDING":
            hh = db.households.get(v["household_id"])
            if hh is None:
                return None
            return ("BUILDING", hh["building_code"])
        if dimension == "COMMUNITY":
            return ("COMMUNITY", community_id)
        return None

    subjects: set[tuple[str, str]] = set()
    for d in eligible_disposals:
        s = subject_for_disposal(d)
        if s is None:
            continue
        subjects.add(s)
        earned_by_subject[s] = earned_by_subject.get(s, 0) + int(d["awarded_points"])
    for v in eligible_violations:
        s = subject_for_violation(v)
        if s is None:
            continue
        subjects.add(s)
        deducted_by_subject[s] = deducted_by_subject.get(s, 0) + int(v["final_deduction_points"])

    if not subjects:
        return []

    days_in_window = max(1, (window_end - window_start).days)

    entries = []
    for s in subjects:
        earned = earned_by_subject.get(s, 0)
        deducted = deducted_by_subject.get(s, 0)
        raw_score = earned - deducted
        if granularity == "WEEKLY":
            score = raw_score
        elif granularity == "MONTHLY":
            score = int(round_half_up(raw_score * 30.0 / days_in_window, 0))
        else:  # YEARLY
            denom = earned + abs(deducted)
            quality = (earned / denom) if denom > 0 else 0.0
            score = int(round_half_up(raw_score * (0.5 + 0.5 * quality), 0))
        entries.append({
            "subject_id": s[1],
            "subject_kind": s[0],
            "score": int(score),
            "rank": 0,
        })

    # Sort by score desc, ties broken by subject_id asc lexicographic
    entries.sort(key=lambda e: (-e["score"], e["subject_id"]))
    for i, e in enumerate(entries, start=1):
        e["rank"] = i
    return entries


# =========================================================================
# Rule effectiveness
# =========================================================================

def compute_rule_effectiveness(rule: dict) -> dict:
    """Compute participation tier and weighted score for a PointRule.

    Tier is determined from raw participation count BEFORE the score is computed.
    """
    # Disposals applying this rule
    applying = [d for d in db.disposals.values() if d.get("applied_rule_id") == rule["id"]]
    committed = [d for d in applying if d["status"] == "COMMITTED"]
    corrected = [d for d in applying if d["status"] == "CORRECTED"]

    households = {d["household_id"] for d in committed}
    participation = len(households)

    if committed:
        avg_accuracy = sum(d["accuracy_score"] for d in committed) / len(committed)
    else:
        avg_accuracy = 0.0

    total_applying = len(applying)
    misjudgment_ratio = (len(corrected) / max(1, total_applying))

    if participation >= 50:
        tier = "HIGH"
        weights = {"accuracy": 0.50, "misjudgment": 0.30, "participation": 0.20}
    elif participation >= 10:
        tier = "MEDIUM"
        weights = {"accuracy": 0.40, "misjudgment": 0.40, "participation": 0.20}
    else:
        tier = "LOW"
        weights = {"accuracy": 0.30, "misjudgment": 0.50, "participation": 0.20}

    participation_normalized = min(1.0, participation / 100.0)
    score = round_half_up(
        100.0
        * (
            weights["accuracy"] * avg_accuracy
            + weights["misjudgment"] * (1.0 - misjudgment_ratio)
            + weights["participation"] * participation_normalized
        ),
        1,
    )

    return {
        "participation": participation,
        "participation_tier": tier,
        "avg_accuracy": float(avg_accuracy),
        "misjudgment_ratio": float(misjudgment_ratio),
        "score": float(score),
    }
