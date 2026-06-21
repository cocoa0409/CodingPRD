"""Pure calculation rules from PRD section 3 / scaffold 1.3.

All money is integer cents. Percentage fees use Decimal with ROUND_HALF_UP,
rounded as a single pinned step at the boundary each calculation specifies.
"""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

# --- repair_vs_replace_decision constants ---
CRACK_REPAIRABLE_LIMIT_MM = 150
EDGE_SAFE_MARGIN_MM = 12
MAX_REPAIRABLE_CHIPS = 3

# --- price_quote constants ---
REPAIR_BASE_CENTS = 8900
REPLACE_BASE_CENTS = 32500
ADAS_RECALIBRATION_FEE_CENTS = 19900
SHOP_FEE_PCT = Decimal("0.085")

# --- schedule_trip_fee constants ---
SHOP_HOME_STATE = "CA"
LOCAL_TRIP_PCT = Decimal("0.04")
OUT_OF_STATE_TRIP_PCT = Decimal("0.09")

# --- safe_drive_away_time constants (minutes) ---
WARM_THRESHOLD_C = 24
COLD_THRESHOLD_C = 4
WARM_CURE_MIN = 60
MILD_CURE_MIN = 120
COLD_CURE_MIN = 240
DRY_HUMIDITY_PCT = 15
DRY_PENALTY_MIN = 30

# --- refund_amount constants ---
RESTOCK_PCT = Decimal("0.15")
POST_SERVICE_STATES = {"IN_SERVICE", "AWAITING_RECALIBRATION", "CURING", "COMPLETED"}


def round_half_up_cents(amount):
    """Round a Decimal amount of cents to the nearest whole cent, half up."""
    return int(Decimal(amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def repair_vs_replace_decision(chip_count, longest_crack_mm, in_driver_primary_view,
                               edge_distance_mm):
    """Deterministic REPAIR/REPLACE recommendation. First disqualifier that
    fires forces REPLACE; boundaries are one-sided (PRD 3.2).
        1. in_driver_primary_view == true
        2. longest_crack_mm > 150 (strictly greater)
        3. edge_distance_mm < 12  (strictly less)
        4. chip_count > 3         (strictly greater)
    """
    if in_driver_primary_view:
        return "REPLACE"
    if longest_crack_mm > CRACK_REPAIRABLE_LIMIT_MM:
        return "REPLACE"
    if edge_distance_mm < EDGE_SAFE_MARGIN_MM:
        return "REPLACE"
    if chip_count > MAX_REPAIRABLE_CHIPS:
        return "REPLACE"
    return "REPAIR"


def price_quote(service_decision, adas_equipped):
    """Quote in cents for the accepted service_decision (PRD 3.3).

    shop_fee = round_half_up((base + adas_fee) * 8.5%), summed then rounded once.
    No mobile trip fee here; that is added at scheduling.
    """
    if service_decision == "REPAIR":
        base = REPAIR_BASE_CENTS
        adas_fee = 0
    else:  # REPLACE
        base = REPLACE_BASE_CENTS
        adas_fee = ADAS_RECALIBRATION_FEE_CENTS if adas_equipped else 0
    shop_fee = round_half_up_cents(Decimal(base + adas_fee) * SHOP_FEE_PCT)
    return base + adas_fee + shop_fee


def schedule_trip_fee(frozen_total_cents, service_location, customer_state):
    """Mobile trip fee added at scheduling (PRD 3.4). Percentage of the frozen
    total, rounded half-up. IN_SHOP => 0; MOBILE CA => 4%; MOBILE non-CA => 9%.
    Returns the trip fee in cents (caller adds it to the frozen total).
    """
    if service_location == "IN_SHOP":
        return 0
    if customer_state == SHOP_HOME_STATE:
        rate = LOCAL_TRIP_PCT
    else:
        rate = OUT_OF_STATE_TRIP_PCT
    return round_half_up_cents(Decimal(frozen_total_cents) * rate)


def cure_minutes(temp_c, humidity_pct):
    """Cure interval in minutes from temperature band + humidity penalty (PRD 3.5).
    Boundaries one-sided: temp_c==24 is WARM (>=); temp_c==4 is MILD (>=);
    humidity==15 takes NO dry penalty (penalty is strictly < 15).
    """
    if temp_c >= WARM_THRESHOLD_C:
        base = WARM_CURE_MIN
    elif temp_c >= COLD_THRESHOLD_C:
        base = MILD_CURE_MIN
    else:
        base = COLD_CURE_MIN
    penalty = DRY_PENALTY_MIN if humidity_pct < DRY_HUMIDITY_PCT else 0
    return base + penalty


def safe_drive_away_at(now_dt, temp_c, humidity_pct):
    """Compute the safe-drive-away instant = now + cure minutes (PRD 3.5)."""
    minutes = cure_minutes(temp_c, humidity_pct)
    return now_dt + timedelta(minutes=minutes)


def posted_sdat_minutes():
    """Conservative posted estimate: worst band 240 + dry penalty 30 = 270 (PRD 3.5)."""
    return COLD_CURE_MIN + DRY_PENALTY_MIN


def refund_amount(amount_cents, work_order_status, service_decision):
    """Refunded delta for a CAPTURED payment (PRD 3.7).

    Restock fee (15%) applies ONLY when the work order is IN_SERVICE or beyond
    AND service_decision == REPLACE. Otherwise full refund.
    """
    if work_order_status in POST_SERVICE_STATES and service_decision == "REPLACE":
        restock_fee = round_half_up_cents(Decimal(amount_cents) * RESTOCK_PCT)
    else:
        restock_fee = 0
    return amount_cents - restock_fee
