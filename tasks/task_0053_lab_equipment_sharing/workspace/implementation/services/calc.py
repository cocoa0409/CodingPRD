"""Calculation rules: estimated_fee, final_fee, cancellation_refund_policy,
peak_overlap_minutes, authorization_eligibility_score.

All monetary values in integer cents. Uses Decimal + ROUND_HALF_UP for
deterministic precision.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import math


TRAINING_WEIGHT = 30
SAMPLE_WEIGHT = 30
AFFILIATION_WEIGHT = 20
IDENTITY_WEIGHT = 20
QUALIFICATION_THRESHOLD = 100
AUTHORIZATION_TTL_DAYS = 30


def round_half_up(x) -> int:
    """Round a Decimal/float/int to an integer using ROUND_HALF_UP."""
    if isinstance(x, Decimal):
        d = x
    else:
        # Use repr for floats to avoid binary surprises
        d = Decimal(str(x))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pick_rate(rule: dict, affiliation: str, kind: str) -> int:
    """kind in {"time", "sample"}, affiliation in {WITHIN_SCHOOL, INTER_SCHOOL, EXTERNAL}."""
    if kind == "time":
        if affiliation == "WITHIN_SCHOOL":
            return rule["internal_rate_per_hour_cents"]
        if affiliation == "INTER_SCHOOL":
            return rule["inter_school_rate_per_hour_cents"]
        if affiliation == "EXTERNAL":
            return rule["external_rate_per_hour_cents"]
        return 0
    else:
        if affiliation == "WITHIN_SCHOOL":
            return rule["internal_rate_per_sample_cents"]
        if affiliation == "INTER_SCHOOL":
            return rule["inter_school_rate_per_sample_cents"]
        if affiliation == "EXTERNAL":
            return rule["external_rate_per_sample_cents"]
        return 0


def peak_overlap_minutes(a: datetime, b: datetime,
                         peak_start_hour: int, peak_end_hour: int) -> int:
    """Sum minutes [a, b) intersects with daily peak window across calendar days.

    peak_start_hour: 0..23 (inclusive open)
    peak_end_hour:   1..24 (exclusive close, half-open)
    """
    if a >= b:
        return 0
    total_minutes = 0
    # Iterate through each calendar day spanned by [a, b)
    day = datetime(a.year, a.month, a.day, tzinfo=timezone.utc)
    end_day_excl = b
    while day < end_day_excl:
        peak_start_d = day + timedelta(hours=peak_start_hour)
        peak_end_d = day + timedelta(hours=peak_end_hour)
        overlap_start = max(a, peak_start_d)
        overlap_end = min(b, peak_end_d)
        if overlap_end > overlap_start:
            delta = overlap_end - overlap_start
            total_minutes += int(delta.total_seconds() // 60)
            # If there's a fractional minute, the half-open semantics already
            # exclude it; total_seconds is exact for our hour-aligned grids.
        day = day + timedelta(days=1)
    return total_minutes


def estimated_fee(rule: dict, lab: dict, user: dict, start_at: datetime, end_at: datetime,
                  requested_sample_count: int,
                  peak_start_hour: int, peak_end_hour: int) -> dict:
    """Forward-looking fee calculation. Returns dict of fee fields."""
    # rational billed_hours = total_minutes / 60
    total_minutes = Decimal(int((end_at - start_at).total_seconds() // 60))
    billed_hours = total_minutes / Decimal(60)
    affiliation = user["affiliation"]
    time_rate = Decimal(pick_rate(rule, affiliation, "time"))
    sample_rate = Decimal(pick_rate(rule, affiliation, "sample"))
    mode = rule["mode"]

    if mode == "BY_TIME":
        time_component = billed_hours * time_rate
        sample_component = Decimal(0)
    elif mode == "BY_SAMPLE":
        time_component = Decimal(0)
        sample_component = Decimal(int(requested_sample_count)) * sample_rate
    elif mode == "HYBRID":
        time_component = billed_hours * time_rate
        sample_component = Decimal(int(requested_sample_count)) * sample_rate
    else:
        time_component = Decimal(0)
        sample_component = Decimal(0)

    peak_min = peak_overlap_minutes(start_at, end_at, peak_start_hour, peak_end_hour)
    if peak_min > 0:
        time_component = time_component * Decimal(rule["peak_multiplier_bps"]) / Decimal(10000)

    equipment_fee_cents = round_half_up(time_component + sample_component)
    platform_fee_cents = round_half_up(
        Decimal(equipment_fee_cents) * Decimal(rule["platform_fee_bps"]) / Decimal(10000)
    )
    consumables_cents = int(rule["consumables_flat_cents"])
    estimated = equipment_fee_cents + platform_fee_cents + consumables_cents

    owner_share = round_half_up(
        Decimal(equipment_fee_cents) * Decimal(lab["revenue_share_bps"]) / Decimal(10000)
    )

    return {
        "equipment_fee_cents": equipment_fee_cents,
        "estimated_fee_cents": estimated,
        "estimated_platform_fee_cents": platform_fee_cents,
        "estimated_owner_share_cents": owner_share,
        "consumables_cents": consumables_cents,
    }


def final_fee(rule: dict, lab: dict, user: dict,
              check_in_at: datetime, check_out_at: datetime,
              actual_sample_count: int,
              peak_start_hour: int, peak_end_hour: int) -> dict:
    """Chronological fee calculation. Uses ceil-minutes, ceil-hours."""
    delta_seconds = (check_out_at - check_in_at).total_seconds()
    actual_minutes = int(math.ceil(delta_seconds / 60.0))
    actual_billed_hours = int(math.ceil(actual_minutes / 60.0))

    affiliation = user["affiliation"]
    time_rate = Decimal(pick_rate(rule, affiliation, "time"))
    sample_rate = Decimal(pick_rate(rule, affiliation, "sample"))
    mode = rule["mode"]

    if mode == "BY_TIME":
        time_component = Decimal(actual_billed_hours) * time_rate
        sample_component = Decimal(0)
    elif mode == "BY_SAMPLE":
        time_component = Decimal(0)
        sample_component = Decimal(int(actual_sample_count)) * sample_rate
    elif mode == "HYBRID":
        time_component = Decimal(actual_billed_hours) * time_rate
        sample_component = Decimal(int(actual_sample_count)) * sample_rate
    else:
        time_component = Decimal(0)
        sample_component = Decimal(0)

    peak_min = peak_overlap_minutes(check_in_at, check_out_at, peak_start_hour, peak_end_hour)
    if peak_min > 0:
        time_component = time_component * Decimal(rule["peak_multiplier_bps"]) / Decimal(10000)

    equipment_fee_cents = round_half_up(time_component + sample_component)
    platform_fee_cents = round_half_up(
        Decimal(equipment_fee_cents) * Decimal(rule["platform_fee_bps"]) / Decimal(10000)
    )
    consumables_cents = int(rule["consumables_flat_cents"])
    final_cents = equipment_fee_cents + platform_fee_cents + consumables_cents

    owner_share = round_half_up(
        Decimal(equipment_fee_cents) * Decimal(lab["revenue_share_bps"]) / Decimal(10000)
    )

    return {
        "equipment_fee_cents": equipment_fee_cents,
        "final_fee_cents": final_cents,
        "final_platform_fee_cents": platform_fee_cents,
        "final_owner_share_cents": owner_share,
        "actual_duration_minutes": actual_minutes,
    }


def cancellation_refund_bps(start_at: datetime, now_dt: datetime) -> int:
    """Refund tier in basis points based on lead time."""
    delta = start_at - now_dt
    delta_minutes = delta.total_seconds() / 60.0
    if delta_minutes >= 24 * 60:
        return 10000
    if delta_minutes >= 2 * 60:
        return 5000
    return 0


def eligibility(equipment: dict, user: dict, sample_type: str) -> dict:
    """Compute the four binary eligibility inputs.

    Returns dict with: training_match, sample_match, affiliation_match,
    identity_match (each 0 or 1), score, passes_gate (bool).
    """
    required = set(equipment.get("required_training_codes") or [])
    held = set(user.get("training_certificates") or [])
    training_match = 1 if required.issubset(held) else 0

    allowed = set(equipment.get("allowed_sample_types") or [])
    sample_match = 1 if (sample_type in allowed) else 0

    scope = equipment["sharing_scope"]
    affil = user["affiliation"]
    if scope == "WITHIN_SCHOOL":
        affiliation_match = 1 if affil == "WITHIN_SCHOOL" else 0
    elif scope == "INTER_SCHOOL":
        affiliation_match = 1 if affil in ("WITHIN_SCHOOL", "INTER_SCHOOL") else 0
    elif scope == "EXTERNAL":
        affiliation_match = 1
    else:
        affiliation_match = 0

    identity_match = 1 if user.get("identity_verified") else 0

    score = (TRAINING_WEIGHT * training_match
             + SAMPLE_WEIGHT * sample_match
             + AFFILIATION_WEIGHT * affiliation_match
             + IDENTITY_WEIGHT * identity_match)
    passes = (score >= QUALIFICATION_THRESHOLD)
    return {
        "training_match": training_match,
        "sample_match": sample_match,
        "affiliation_match": affiliation_match,
        "identity_match": identity_match,
        "score": score,
        "passes_gate": passes,
    }


def aligned_to_grid(dt: datetime, granularity: str) -> bool:
    """Check that dt aligns to the slot granularity grid in UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    if dt.microsecond != 0 or dt.second != 0 or dt.minute != 0:
        return False
    if granularity == "HOUR":
        return True
    if granularity == "HALF_DAY":
        return dt.hour in (0, 12)
    if granularity == "DAY":
        return dt.hour == 0
    return False


def grid_seconds(granularity: str) -> int:
    if granularity == "HOUR":
        return 3600
    if granularity == "HALF_DAY":
        return 12 * 3600
    if granularity == "DAY":
        return 24 * 3600
    return 0
