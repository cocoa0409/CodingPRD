"""Calculation primitives per scaffold §1.3 / PRD §3.

Includes:
  - Time / timezone helpers (resort timezone is America/New_York)
  - Reservation booking-window opening instant
  - Slot-grid alignment helpers
  - No-show fee tiered pricing (per-seat round-half-up; party_size multiply)
  - Lightning Lane add-on fee tiered pricing (per-seat round-half-up;
    party_size multiply)

All monetary rounding uses ROUND_HALF_UP on Decimal — Python's built-in
`round()` uses banker's rounding and is NOT correct here. Each fee is rounded
exactly ONCE, at the per-seat boundary; the party_size multiply that follows
is pure integer arithmetic.
"""
from datetime import datetime, timedelta, date, time, timezone
from decimal import Decimal, ROUND_HALF_UP

# Resort timezone offset is America/New_York. We rely on Python's zoneinfo,
# which is in the stdlib from 3.9 onward. The Flask test harness Pythons
# (3.10+) always have it.
try:
    from zoneinfo import ZoneInfo
    RESORT_TZ = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover — extremely unlikely on supported Pythons
    RESORT_TZ = timezone(timedelta(hours=-5))  # crude fallback


# --- Constants from scaffold §1.3 ---

# no_show_fee_amount
CHARACTER_SURCHARGE_PER_SEAT_CENTS = 1000
REPEAT_OFFENDER_THRESHOLD = 1            # strike_after 1 -> tier1 ×1.0
REPEAT_OFFENDER_MAX = 3                  # strike_after 2..3 -> tier2; 4+ -> tier3
REPEAT_OFFENDER_MULTIPLIER_TIER1 = Decimal("1.0")
REPEAT_OFFENDER_MULTIPLIER_TIER2 = Decimal("1.075")
REPEAT_OFFENDER_MULTIPLIER_TIER3 = Decimal("1.250")

# lightning_lane_addon_fee
LL_BASE_CENTS = {
    "SINGLE_PASS": 1500,
    "MULTI_PASS":  2500,
}
LL_PARK_MULT = {
    "MAGIC_KINGDOM":     Decimal("1.175"),
    "EPCOT":             Decimal("1.075"),
    "ANIMAL_KINGDOM":    Decimal("1.000"),
    "HOLLYWOOD_STUDIOS": Decimal("1.100"),
}
LL_CHARACTER_UPLIFT_CENTS = 500

# reservation_window_open_at
LEAD_DAYS = 60
DAILY_OPEN_LOCAL_HHMM = (6, 0)   # 06:00 resort time


# =============================================================
# Time parsing / formatting
# =============================================================

def parse_iso_to_dt(s: str) -> datetime:
    """Parse an ISO 8601 string into an aware UTC datetime.

    Accepts trailing 'Z' (UTC) as well as explicit offsets. The returned dt
    is always normalised to UTC.
    """
    if not isinstance(s, str):
        raise ValueError("not a string")
    # Python's fromisoformat doesn't accept trailing Z prior to 3.11.
    if s.endswith("Z"):
        s2 = s[:-1] + "+00:00"
    else:
        s2 = s
    dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_visit_date(s: str) -> date:
    """Parse a YYYY-MM-DD calendar date string."""
    if not isinstance(s, str) or len(s) != 10 or s[4] != "-" or s[7] != "-":
        raise ValueError("visit_date must be YYYY-MM-DD")
    return date.fromisoformat(s)


def parse_hhmm(s: str) -> tuple:
    """Parse 'HH:MM' (24-hour). Returns (h, m)."""
    if not isinstance(s, str) or len(s) != 5 or s[2] != ":":
        raise ValueError("HH:MM expected")
    h = int(s[0:2]); m = int(s[3:5])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("HH:MM out of range")
    return h, m


def utc_to_resort_dt(utc_dt: datetime) -> datetime:
    """Project a UTC datetime into resort wall-clock."""
    return utc_dt.astimezone(RESORT_TZ)


def resort_date_of_utc(utc_dt: datetime) -> date:
    """Resort-timezone calendar date of a UTC instant."""
    return utc_to_resort_dt(utc_dt).date()


def resort_local_dt(d: date, h: int, m: int) -> datetime:
    """Construct an aware datetime at d, h:m in resort timezone."""
    return datetime(d.year, d.month, d.day, h, m, 0, tzinfo=RESORT_TZ)


# =============================================================
# Reservation booking window
# =============================================================

def reservation_window_open_utc(visit_date_str: str) -> datetime:
    """Compute the UTC instant the 60-day window opens for a given visit_date.

    Per scaffold:
        visit_local_open = datetime(visit_date.year, visit_date.month, visit_date.day,
                                    06, 00, 00, tzinfo='America/New_York')
        window_open_utc  = visit_local_open - timedelta(days=60)
    The implementation must compute wall-clock first and convert — the UTC
    offset of 06:00 resort time shifts across DST boundaries.
    """
    vd = parse_visit_date(visit_date_str)
    h, m = DAILY_OPEN_LOCAL_HHMM
    visit_local_open = resort_local_dt(vd, h, m)
    window_open_local = visit_local_open - timedelta(days=LEAD_DAYS)
    return window_open_local.astimezone(timezone.utc)


# =============================================================
# Slot grid alignment
# =============================================================

def slot_grid_offset_minutes(slot_resort_dt: datetime, opening_hhmm: tuple,
                             slot_minutes: int) -> int:
    """Return how many minutes past `opening_hhmm` the slot starts, modulo nothing.

    A slot is aligned iff the result is a non-negative multiple of slot_minutes.
    """
    open_h, open_m = opening_hhmm
    open_local = datetime(slot_resort_dt.year, slot_resort_dt.month,
                          slot_resort_dt.day, open_h, open_m, 0,
                          tzinfo=slot_resort_dt.tzinfo)
    delta = slot_resort_dt - open_local
    return int(delta.total_seconds() // 60)


# =============================================================
# Fee calculations
# =============================================================

def _round_half_up(d: Decimal) -> int:
    """Round a Decimal to the nearest integer using half-up."""
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def no_show_fee_amount(*, base_fee_cents: int, is_character_dining: bool,
                       party_size: int, strike_after: int) -> dict:
    """Compute the no_show_fee_amount per scaffold §1.3.

    `strike_after` is the guest's no_show_strike_count AFTER incrementing for
    this NO_SHOW (i.e., the count that includes the current event).

    Returns a dict with: base_amount_cents, character_surcharge_cents,
    repeat_offender_multiplier (as string for verbatim storage), per_seat_cents,
    total_amount_cents.
    """
    # 1. per-seat surcharge component
    surcharge_per_seat = CHARACTER_SURCHARGE_PER_SEAT_CENTS if is_character_dining else 0
    # 2. per-seat pre-multiplier
    per_seat_pre = Decimal(base_fee_cents) + Decimal(surcharge_per_seat)
    # 3. tier multiplier branch
    if strike_after <= REPEAT_OFFENDER_THRESHOLD:
        mult = REPEAT_OFFENDER_MULTIPLIER_TIER1
    elif strike_after <= REPEAT_OFFENDER_MAX:
        mult = REPEAT_OFFENDER_MULTIPLIER_TIER2
    else:
        mult = REPEAT_OFFENDER_MULTIPLIER_TIER3
    # 4. per-seat decimal -> round_half_up (FIRST and ONLY round)
    per_seat_decimal = per_seat_pre * mult
    per_seat_cents = _round_half_up(per_seat_decimal)
    # 5. total = integer multiply by party_size
    total_cents = per_seat_cents * int(party_size)
    return {
        "base_amount_cents": int(base_fee_cents) * int(party_size),
        "character_surcharge_cents": int(surcharge_per_seat) * int(party_size),
        "repeat_offender_multiplier": float(mult),  # stored verbatim as decimal
        "per_seat_cents": per_seat_cents,
        "total_amount_cents": total_cents,
    }


def lightning_lane_addon_fee(*, tier: str, park_code: str,
                             is_character_dining: bool, party_size: int) -> int:
    """Compute LL add-on fee_cents per scaffold §1.3.

    Order is PINNED:
      1. base = BASE_CENTS[tier]
      2. character_uplift = is_character_dining ? CHARACTER_UPLIFT_CENTS : 0
      3. per_seat_decimal = (base + character_uplift) * PARK_MULT[park_code]
      4. per_seat_rounded = round_half_up(per_seat_decimal)   # ONLY round
      5. fee_cents = per_seat_rounded * party_size            # integer multiply
    """
    base = LL_BASE_CENTS[tier]
    uplift = LL_CHARACTER_UPLIFT_CENTS if is_character_dining else 0
    park_mult = LL_PARK_MULT[park_code]
    per_seat_decimal = (Decimal(base) + Decimal(uplift)) * park_mult
    per_seat_cents = _round_half_up(per_seat_decimal)
    return per_seat_cents * int(party_size)


# =============================================================
# Dining-Plan credit calculation
# =============================================================

def credit_cost(restaurant: dict, party_size: int) -> int:
    """Integer credits required for a single reservation seat-set."""
    return int(restaurant["dining_plan_credit_cost"]) * int(party_size)
