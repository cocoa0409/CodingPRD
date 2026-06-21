"""Calculation rules (scaffold §1.3 / PRD §3.3, §3.7, §3.8).

All derived numeric quantities are rounded to exactly 2 decimal places using
round-half-up, computed with Decimal to avoid float drift. Where a rounding
order is pinned (round-per-item then combine), it is honoured exactly.
"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

# ---- Composite eligibility score constants (§1.3 / PRD §3.3) ----
W_ADAPTIVE = Decimal("0.30")
W_ACADEMIC = Decimal("0.20")
ELIGIBILITY_THRESHOLD = Decimal("15.0")
GAP_WEIGHT_INITIAL = Decimal("0.5")
GAP_WEIGHT_TRIENNIAL = Decimal("0.6")

# ---- LRE constants (§1.3 / PRD §3.8) ----
DAYS_PER_WEEK = Decimal("5")
FULL_INCLUSION_FLOOR = Decimal("80.0")
RESOURCE_FLOOR = Decimal("40.0")

# ---- Reevaluation / transition (§1.4) ----
REEVAL_DAYS = 1095
TRANSITION_AGE = 16


def _round2(value: Decimal) -> Decimal:
    """Round half-up to 2 decimal places."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _clamp(value: Decimal, lo: Decimal, hi: Decimal) -> Decimal:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def _to_float2(value: Decimal) -> float:
    """Return a float pinned to 2 decimals (JSON number)."""
    return float(_round2(value))


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

def parse_iso_to_dt(value: str) -> datetime:
    """Parse an ISO 8601 string into a timezone-aware UTC datetime.

    Accepts a trailing 'Z' (treated as +00:00) and naive values (assumed UTC).
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# eligibility_composite_score (§1.3 / PRD §3.3)
# ---------------------------------------------------------------------------

def eligibility_composite_score(cognitive_score, academic_score, adaptive_score,
                                eval_type):
    """Return (composite_eligibility_score_float, outcome).

    Pinned evaluation order:
      discrepancy = cognitive - academic, floored at 0
      gap_weight = 0.5 (INITIAL) / 0.6 (TRIENNIAL)
      adaptive_deficit = max(0, 100 - adaptive)
      academic_deficit = max(0, 100 - academic)
      raw = gap_weight*discrepancy + 0.30*adaptive_deficit + 0.20*academic_deficit
      composite = round_half_up(raw, 2)
      outcome = ELIGIBLE if composite >= 15.0 else INELIGIBLE
    """
    cog = Decimal(str(cognitive_score))
    aca = Decimal(str(academic_score))
    ada = Decimal(str(adaptive_score))

    discrepancy = cog - aca
    if discrepancy < 0:
        discrepancy = Decimal("0")

    gap_weight = GAP_WEIGHT_INITIAL if eval_type == "INITIAL" else GAP_WEIGHT_TRIENNIAL

    adaptive_deficit = Decimal("100") - ada
    if adaptive_deficit < 0:
        adaptive_deficit = Decimal("0")
    academic_deficit = Decimal("100") - aca
    if academic_deficit < 0:
        academic_deficit = Decimal("0")

    raw = (gap_weight * discrepancy) \
        + (W_ADAPTIVE * adaptive_deficit) \
        + (W_ACADEMIC * academic_deficit)
    composite = _round2(raw)
    outcome = "ELIGIBLE" if composite >= ELIGIBILITY_THRESHOLD else "INELIGIBLE"
    return _to_float2(composite), outcome


# ---------------------------------------------------------------------------
# goal_progress_provisional + cumulative (§1.3 / PRD §3.7)
# ---------------------------------------------------------------------------

def _per_report_progress(measured_value, baseline_value, target_value) -> Decimal:
    """round_half_up(clamp((measured - baseline)/(target - baseline)*100, 0, 100), 2)."""
    measured = Decimal(str(measured_value))
    baseline = Decimal(str(baseline_value))
    target = Decimal(str(target_value))
    denom = target - baseline
    progress = (measured - baseline) / denom * Decimal("100")
    progress = _clamp(progress, Decimal("0"), Decimal("100"))
    return _round2(progress)


def goal_progress_provisional(reports, baseline_value, target_value) -> float:
    """Provisional: single most-recent report only.

    Most recent = max(reporting_period); tie-break by created_at ASC then take
    the last (i.e. the latest-created among the highest period). Empty -> 0.0.
    """
    if not reports:
        return 0.0
    # max reporting_period; among ties take the one with the latest creation
    # (created_at ASC, take last => max created_at, with seq as a stable tiebreak).
    chosen = max(
        reports,
        key=lambda r: (r["reporting_period"], r["created_at"], r.get("_seq", 0)),
    )
    p = _per_report_progress(chosen["measured_value"], baseline_value, target_value)
    return _to_float2(p)


def goal_progress_cumulative(reports, baseline_value, target_value) -> float:
    """Cumulative: round per-report then average then round. Empty -> 0.0."""
    if not reports:
        return 0.0
    total = Decimal("0")
    for r in reports:
        total += _per_report_progress(r["measured_value"], baseline_value, target_value)
    avg = total / Decimal(len(reports))
    return _to_float2(_round2(avg))


# ---------------------------------------------------------------------------
# lre_general_ed_pct + lre_setting_bucket (§1.3 / PRD §3.8)
# ---------------------------------------------------------------------------

def lre_general_ed_pct(active_pullout_services, school_day_minutes) -> float:
    """Round-per-service-then-sum-then-divide.

    active_pullout_services: iterable of RelatedService dicts that are ACTIVE and
    delivered_in_general_ed == False. school_day_minutes is the denominator.
    No pull-out services -> 100.0.
    """
    denom = Decimal(str(school_day_minutes))
    pullout_daily_total = Decimal("0.00")
    for s in active_pullout_services:
        daily_minutes_s = _round2(Decimal(str(s["minutes_per_week"])) / DAYS_PER_WEEK)
        pullout_daily_total += daily_minutes_s
    pullout_daily_total = _round2(pullout_daily_total)
    pct = (denom - pullout_daily_total) / denom * Decimal("100")
    pct = _clamp(pct, Decimal("0"), Decimal("100"))
    return _to_float2(pct)


def lre_setting_bucket(pct_value) -> str:
    """Boundary precision pinned with >= on upper edges (80.0 / 40.0)."""
    pct = Decimal(str(pct_value))
    if pct >= FULL_INCLUSION_FLOOR:
        return "FULL_INCLUSION"
    if pct >= RESOURCE_FLOOR:
        return "RESOURCE"
    return "SEPARATE_CLASS"


# ---------------------------------------------------------------------------
# clock-derived helpers
# ---------------------------------------------------------------------------

def add_days_iso(iso_value: str, days: int) -> str:
    """Return iso_value + days as an ISO 8601 UTC string with millisecond precision."""
    dt = parse_iso_to_dt(iso_value) + timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def full_years_between(dob_iso: str, now_iso: str) -> int:
    """Number of complete years between dob and now (age at the clock instant)."""
    dob = parse_iso_to_dt(dob_iso)
    now = parse_iso_to_dt(now_iso)
    years = now.year - dob.year
    # subtract one if the anniversary has not yet occurred this year
    if (now.month, now.day, now.hour, now.minute, now.second, now.microsecond) < \
       (dob.month, dob.day, dob.hour, dob.minute, dob.second, dob.microsecond):
        years -= 1
    return years
