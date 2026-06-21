"""Calculation engines: tier_credit_accrual, comp_room_rate, velocity_monitor.

All money handled in integer cents. Tier credits rounded HALF_UP to 2 dp
per session. Comp-room rate uses round-per-multiplication (Rule 2 mode b).
"""
from decimal import Decimal, ROUND_HALF_UP

import clock


# --- constants from SCAFFOLD §1.3 ------------------------------------------

GAME_TYPE_MULT = {
    "SLOTS": Decimal("1.0"),
    "TABLE_GAMES": Decimal("2.0"),
    "POKER": Decimal("1.5"),
}

TIER_MULT = {
    "GOLD": Decimal("1.00"),
    "PLATINUM": Decimal("1.25"),
    "DIAMOND": Decimal("1.50"),
    "SEVEN_STARS": Decimal("2.00"),
}

PLATINUM_THRESHOLD = Decimal("15000")
DIAMOND_THRESHOLD = Decimal("75000")
SEVEN_STARS_THRESHOLD = Decimal("150000")

DISCOUNT = {
    "GOLD": Decimal("0.10"),
    "PLATINUM": Decimal("0.40"),
    "DIAMOND": Decimal("0.70"),
    "SEVEN_STARS": Decimal("1.00"),
}

MARKET_MULT = {
    "VEGAS_STRIP": Decimal("1.20"),
    "REGIONAL": Decimal("1.00"),
    "INTERNATIONAL": Decimal("1.10"),
}

VELOCITY_FLAG_THRESHOLD_CENTS = 500_000
VELOCITY_SUSPEND_THRESHOLD_CENTS = 1_500_000
VELOCITY_WINDOW_SECONDS = 3600


# --- rounding helper -------------------------------------------------------

def _round_half_up_int(x) -> int:
    if not isinstance(x, Decimal):
        x = Decimal(str(x))
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _round_half_up_2dp_to_float(x) -> float:
    if not isinstance(x, Decimal):
        x = Decimal(str(x))
    q = x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


# --- tier_credit_accrual ---------------------------------------------------

def tier_credit_accrual(theoretical_loss_cents: int, game_type: str, tier_status: str) -> float:
    """Compute tier credits for a single session.

    Per SCAFFOLD: base = loss_cents / 100. Multiply by game_type then tier
    multiplier. Round HALF_UP to 2 dp before summing into member totals.
    """
    base = Decimal(theoretical_loss_cents) / Decimal(100)
    base = base * GAME_TYPE_MULT[game_type]
    earned = base * TIER_MULT[tier_status]
    return _round_half_up_2dp_to_float(earned)


def next_tier_for(tier_credits_ytd) -> str:
    """Highest reachable tier from the given ytd value (monotonic upgrade)."""
    ytd = Decimal(str(tier_credits_ytd))
    if ytd >= SEVEN_STARS_THRESHOLD:
        return "SEVEN_STARS"
    if ytd >= DIAMOND_THRESHOLD:
        return "DIAMOND"
    if ytd >= PLATINUM_THRESHOLD:
        return "PLATINUM"
    return "GOLD"


_TIER_RANK = {"GOLD": 0, "PLATINUM": 1, "DIAMOND": 2, "SEVEN_STARS": 3}


def tier_at_least(a: str, b: str) -> bool:
    return _TIER_RANK[a] >= _TIER_RANK[b]


def promote_tier(current_tier: str, ytd) -> str:
    """Return the new tier after considering accrued ytd.

    Tier never decreases via accrual; only annual reset demotes.
    """
    derived = next_tier_for(ytd)
    if _TIER_RANK[derived] > _TIER_RANK[current_tier]:
        return derived
    return current_tier


# --- comp_room_rate --------------------------------------------------------

def comp_room_rate(base_room_rate_cents: int, tier_status: str, market_segment: str) -> int:
    """Provisional/Final share the same formula, only the inputs differ.

    Round HALF_UP at each multiplication step (Rule 2 mode b).
    """
    base = Decimal(base_room_rate_cents)
    discount = DISCOUNT[tier_status]
    step_a = base * (Decimal("1") - discount)
    step_a_cents = _round_half_up_int(step_a)
    step_b = Decimal(step_a_cents) * MARKET_MULT[market_segment]
    return _round_half_up_int(step_b)


# --- velocity_monitor ------------------------------------------------------

def velocity_monitor(member_id: str, new_session_ended_at_iso: str, gaming_sessions: dict):
    """Compute the 60-minute rolling window ending at the new session's ended_at.

    Returns (severity, total_cents, window_start_iso, window_end_iso) or
    (None, total_cents, ws, we) if neither threshold is crossed.
    Window semantics: (window_start, window_end] (half-open left, closed right).
    """
    window_end_dt = clock.parse_iso(new_session_ended_at_iso)
    window_start_dt = window_end_dt - _td_seconds(VELOCITY_WINDOW_SECONDS)

    total = 0
    for s in gaming_sessions.values():
        if s["member_id"] != member_id:
            continue
        if s["status"] != "RECORDED":
            continue
        ended_dt = clock.parse_iso(s["ended_at"])
        if ended_dt > window_start_dt and ended_dt <= window_end_dt:
            total += int(s["theoretical_loss_cents"])

    severity = None
    if total >= VELOCITY_SUSPEND_THRESHOLD_CENTS:
        severity = "SUSPENDED"
    elif total >= VELOCITY_FLAG_THRESHOLD_CENTS:
        severity = "FLAGGED"

    return severity, total, clock.iso(window_start_dt), clock.iso(window_end_dt)


def _td_seconds(seconds: int):
    from datetime import timedelta
    return timedelta(seconds=seconds)
