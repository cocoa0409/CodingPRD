"""Pure calculation rules and constants (SCAFFOLD 1.3, PRD 2.8 / 3.5 / 3.7 / 3.8)."""
import math
from datetime import timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

# --- trip_fee (SCAFFOLD 1.3 / PRD 3.5) ---
BASE_FEE_CENTS_BY_TYPE = {"TNC": 350, "TAXI": 300, "LIMO": 500, "SHUTTLE": 200}
PEAK_HOURS_UTC = {7, 8, 9, 16, 17, 18}
PEAK_MULTIPLIER = Decimal("1.5")
WAV_DISCOUNT_CENTS = 100
FEE_FLOOR_CENTS = 200
DEADHEAD_FEE_CENTS = 100

# --- operator_penalty_score (SCAFFOLD 1.3 / PRD 3.7) ---
PENALTY_POINTS_BY_TYPE = {
    "STAGING": 3,
    "CURB": 4,
    "AVI_MISMATCH": 6,
    "NO_DECAL": 6,
    "WAV_SHORTFALL": 5,
}
# Fine amounts are "fixed per type" (PRD 3.7) but no numeric schedule is given
# anywhere in the PRD or scaffold; these deterministic values are therefore not
# derivable/assertable from the spec. Chosen fixed schedule:
FINE_CENTS_BY_TYPE = {
    "STAGING": 5000,
    "CURB": 7500,
    "AVI_MISMATCH": 15000,
    "NO_DECAL": 15000,
    "WAV_SHORTFALL": 10000,
}
ROLLING_WINDOW_DAYS = 90
SUSPENSION_THRESHOLD_POINTS = 12

# --- settlement_statement_totals (SCAFFOLD 1.3 / PRD 3.8) ---
ADMIN_RATE = Decimal("0.025")
WAV_INCENTIVE_CENTS = 50

# --- other temporal constants ---
APPEAL_WINDOW_DAYS = 14
STAGING_COOLDOWN_MINUTES = 30

VALID_VIOLATION_TYPES = set(PENALTY_POINTS_BY_TYPE.keys())
VALID_OPERATOR_TYPES = set(BASE_FEE_CENTS_BY_TYPE.keys())


def round_half_up(value):
    """Round a Decimal to a whole integer, half away from zero (PRD 2.8)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def trip_fee(operator_type, trip_kind, is_wheelchair_trip, reference_ts):
    """Tiered per-trip fee. Single rounding on base*mult before WAV subtraction."""
    if trip_kind == "DEADHEAD":
        return DEADHEAD_FEE_CENTS
    base = BASE_FEE_CENTS_BY_TYPE[operator_type]
    hour = reference_ts.astimezone(timezone.utc).hour
    mult = PEAK_MULTIPLIER if hour in PEAK_HOURS_UTC else Decimal("1")
    gross = round_half_up(Decimal(base) * mult)
    wav_adj = WAV_DISCOUNT_CENTS if is_wheelchair_trip else 0
    return max(FEE_FLOOR_CENTS, gross - wav_adj)


def rolling_window_start(clock):
    return clock - timedelta(days=ROLLING_WINDOW_DAYS)


def haversine_m(lat1, lng1, lat2, lng2):
    """Great-circle distance in meters."""
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
