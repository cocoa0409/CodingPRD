"""Calculation rules (scaffold §1.3 / PRD §3.5, §3.6, §3.8).

All durations/counts are integer seconds with no rounding. Money divisions are
round_half_up to whole cents.
"""
from datetime import timedelta

from money import round_half_up

# --- UV dose schedule constants (§1.3 uv_dose_allowed_seconds / PRD §3.8) ---
STEP_SECONDS = 30
SKIN_BASE_SECONDS = {"II": 90, "III": 120, "IV": 180, "V": 240, "VI": 300}
SKIN_CAP_SECONDS = {"II": 240, "III": 480, "IV": 600, "V": 720, "VI": 900}

# --- frequency / cooldown constants ---
MINOR_WEEKLY_UV_CAP = 1
COOLDOWN_SECONDS = 86400

# --- proration / cycle ---
CYCLE_DAYS = 30
DAY_SECONDS = 86400

# --- service threshold ---
SERVICE_THRESHOLD = 2


def uv_dose_allowed_seconds(skin_type, completed_uv_session_count, equipment_max_exposure_seconds):
    """Escalated allowance bounded by per-type cap and the equipment ceiling.

    Caller is responsible for rejecting skin_type I before invoking this
    (it is UV-prohibited, PRD §3.5). Returns integer seconds.
    """
    base = SKIN_BASE_SECONDS[skin_type]
    cap = SKIN_CAP_SECONDS[skin_type]
    escalated = base + completed_uv_session_count * STEP_SECONDS
    return min(escalated, cap, equipment_max_exposure_seconds)


def iso_week_bounds(start_at):
    """Monday 00:00:00Z .. next Monday 00:00:00Z (half-open) containing start_at.

    ISO week: weekday() Monday == 0. Returns (week_start, week_end).
    """
    day_start = start_at.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=start_at.weekday())
    week_end = week_start + timedelta(days=7)
    return week_start, week_end


def freeze_proration_credit(monthly_fee_cents, cycle_anchor_at, now):
    """daily_rate * unused_days (PRD §3.8 freeze proration credit)."""
    daily_rate = round_half_up(monthly_fee_cents, CYCLE_DAYS)
    elapsed_seconds = (now - cycle_anchor_at).total_seconds()
    elapsed_days = int(elapsed_seconds // DAY_SECONDS)
    elapsed_days = max(0, min(CYCLE_DAYS, elapsed_days))
    unused_days = CYCLE_DAYS - elapsed_days
    return daily_rate * unused_days


def upgrade_proration_charge(current_monthly_fee_cents, new_monthly_fee_cents, cycle_anchor_at, now):
    """(new_daily - old_daily) * remaining_days (PRD §3.8 upgrade charge).

    Caller must have already verified new fee > current fee.
    """
    old_daily = round_half_up(current_monthly_fee_cents, CYCLE_DAYS)
    new_daily = round_half_up(new_monthly_fee_cents, CYCLE_DAYS)
    elapsed_seconds = (now - cycle_anchor_at).total_seconds()
    elapsed_days = int(elapsed_seconds // DAY_SECONDS)
    elapsed_days = max(0, min(CYCLE_DAYS, elapsed_days))
    remaining_days = CYCLE_DAYS - elapsed_days
    return (new_daily - old_daily) * remaining_days
