"""Calculation rules (scaffold §1.3 / PRD §2.6, §2.8, §3.6, §3.7).

All money is integer cents. Decimal is used for the cycle-charge proration so
that the sum-then-round semantics are exact (no IEEE-754 float drift). Counts
(ad breaks, watch minutes, download sizes) are whole integers.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# System constants
# ---------------------------------------------------------------------------
PERIOD_DAYS = 30           # cycle_charge: billing period spans 30 whole days
MINUTES_PER_DAY = 1440     # watch_minutes_attributed
AD_CADENCE_MIN = 30        # ad_break_count: one mid-roll per full 30 minutes
HD_MULTIPLIER = 2          # download_size: HD doubles the SD footprint

# Time-to-live constants for the logical clock (PRD §2.9, §3.7, §3.8). The PRD
# names these windows without pinning exact magnitudes; the tests assert
# behavior across them (an invite valid "before" expires_at, a download license
# valid "before" license_expires_at) and advance the clock well past them.
INVITE_TTL_HOURS = 72          # send-time + 72h -> expires_at
DOWNLOAD_LICENSE_HOURS = 48    # complete-time + 48h -> license_expires_at

# Per-seat hold debited on invite send and committed on accept (PRD §3.8). The
# PRD describes the hold qualitatively; the amount is system-fixed. Chosen > 0
# and small so that a funded wallet can send and conservation holds on release.
INVITE_SEAT_HOLD_CENTS = 100

# Ordered maturity-rating scale (PRD §2.8): G < PG < PG13 < R < NC17.
RATING_ORDER = ["G", "PG", "PG13", "R", "NC17"]
RATING_RANK = {r: i for i, r in enumerate(RATING_ORDER)}

# Per-kind default rating ceilings (PRD §2.8 / scaffold rating_ceiling).
KIND_DEFAULT_RATING = {"KID": "G", "TEEN": "PG13", "ADULT": "NC17"}


# ---------------------------------------------------------------------------
# Clock / time helpers
# ---------------------------------------------------------------------------
def parse_iso_to_dt(s: str) -> datetime:
    """Parse an ISO 8601 timestamp to an aware UTC datetime.

    Accepts a trailing 'Z' and optional fractional seconds. Raises ValueError
    on anything unparseable (callers translate to ERR_INVALID_REQUEST).
    """
    if not isinstance(s, str):
        raise ValueError("timestamp must be a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def minute_of_day(dt: datetime) -> int:
    """Minutes-after-UTC-midnight for an aware UTC datetime (0..1439)."""
    return dt.hour * 60 + dt.minute


def utc_day_ordinal(dt: datetime) -> int:
    """Whole-day ordinal (proleptic Gregorian) of the datetime's UTC date.

    Used to detect UTC-midnight rollovers and to count whole days between two
    instants for cycle-charge segmentation.
    """
    return dt.date().toordinal()


# ---------------------------------------------------------------------------
# rating_ceiling (scaffold §1.3 / PRD §2.8)
# ---------------------------------------------------------------------------
def rating_ceiling(kind: str, control_max_rating):
    """max_rating_allowed = MIN(kind default, ParentalControl.max_rating).

    The stricter (lower-on-scale) of the two always wins; a permissive control
    can never raise a profile above its kind default.
    """
    kind_default = KIND_DEFAULT_RATING[kind]
    if control_max_rating is None:
        return kind_default
    if RATING_RANK[control_max_rating] < RATING_RANK[kind_default]:
        return control_max_rating
    return kind_default


# ---------------------------------------------------------------------------
# ad_break_count (scaffold §1.3 / PRD §3.6)
# ---------------------------------------------------------------------------
def ad_break_count(ad_free: bool, runtime_minutes: int) -> int:
    """0 on ad-free plans; else 1 pre-roll + floor(runtime/30) mid-rolls."""
    if ad_free:
        return 0
    return 1 + (runtime_minutes // AD_CADENCE_MIN)


# ---------------------------------------------------------------------------
# download_size (scaffold §1.3 / PRD §3.7)
# ---------------------------------------------------------------------------
def download_size(license_size_mb: int, quality: str) -> int:
    """SD passes through; HD doubles the SD footprint."""
    if quality == "HD":
        return license_size_mb * HD_MULTIPLIER
    return license_size_mb


# ---------------------------------------------------------------------------
# watch_minutes_attributed (scaffold §1.3 / PRD §3.6)
# ---------------------------------------------------------------------------
def watch_minutes_attributed(started_at_min: int, current_minute_of_day: int,
                             runtime_minutes: int) -> int:
    """Elapsed clock time, clamped to [0, runtime].

    Same-day: current >= started -> elapsed = current - started.
    Midnight-cross: current < started -> elapsed = (1440 - started) + current.
    """
    if current_minute_of_day >= started_at_min:
        elapsed = current_minute_of_day - started_at_min
    else:
        elapsed = (MINUTES_PER_DAY - started_at_min) + current_minute_of_day
    elapsed = max(elapsed, 0)
    return min(elapsed, runtime_minutes)


# ---------------------------------------------------------------------------
# cycle_charge (scaffold §1.3 / PRD §2.6)
# ---------------------------------------------------------------------------
def cycle_charge(period_open_dt: datetime, open_plan_fee: int,
                 changes: list):
    """Chronological proration over the 30-day period.

    Args:
      period_open_dt: the instant the current period opened (account created_at
        clock value, or — after invoice — would re-anchor; we use account
        period_open).
      open_plan_fee: monthly_fee_cents of the plan in force at period open.
      changes: list of dicts {effective_dt, fee} for each PlanChange landing in
        the period, already sorted chronologically (created_at ASC, then id).

    Returns period_charge_cents (int). Builds half-open day segments: a day d
    (0..29) belongs to whichever plan is in force at that day's 00:00:00Z.
    Each segment contributes daily_rate(plan) * days_in_segment as an exact
    real; the segment contributions are summed exactly, then rounded ONCE with
    round-half-up at the very end.
    """
    period_open_day = utc_day_ordinal(period_open_dt)

    # For each PlanChange, its effective day index within the period (0..29):
    # whole days from period open to the change's effective instant.
    seg_starts = [(0, open_plan_fee)]
    for ch in changes:
        day_index = utc_day_ordinal(ch["effective_dt"]) - period_open_day
        if day_index < 0:
            day_index = 0
        if day_index > PERIOD_DAYS:
            day_index = PERIOD_DAYS
        seg_starts.append((day_index, ch["fee"]))

    # Walk days 0..PERIOD_DAYS-1; the plan in force at day d is the last segment
    # whose start day <= d. seg_starts is in chronological (and thus start-day
    # non-decreasing) order because changes are sorted chronologically.
    total = Decimal(0)
    for d in range(PERIOD_DAYS):
        fee = open_plan_fee
        for (start_day, seg_fee) in seg_starts:
            if start_day <= d:
                fee = seg_fee
            else:
                break
        daily_rate = Decimal(fee) / Decimal(PERIOD_DAYS)  # exact real, never per-day rounded
        total += daily_rate

    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
