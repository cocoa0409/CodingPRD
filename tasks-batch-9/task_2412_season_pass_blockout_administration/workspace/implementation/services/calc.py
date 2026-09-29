"""Pure arithmetic (PRD 2.9 + 3.x calculations).  Decimal only, never float."""

from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

# --- constants pinned by the PRD ---
PLAN_SETUP_FEE_CENTS = 1500
MIN_DOWN_PAYMENT_PCT = Decimal("0.20")
MIN_INSTALLMENT_COUNT = 3
MAX_INSTALLMENT_COUNT = 10

SLOT_CAPACITY_PCT = Decimal("0.10")

UPGRADE_FEE_BAND_1_MAX_CENTS = 5000
UPGRADE_FEE_BAND_2_MAX_CENTS = 20000
UPGRADE_FEE_BAND_2_FEE_CENTS = 1000
UPGRADE_FEE_BAND_3_FEE_CENTS = 2500
UPGRADE_QUOTE_TTL_DAYS = 14

EARLY_BIRD_DISCOUNT_PCT = Decimal("0.15")
RETENTION_HIGH_VISITS = 10
RETENTION_HIGH_CREDIT_CENTS = 3000
RETENTION_MID_VISITS = 5
RETENTION_MID_CREDIT_CENTS = 1500
RETENTION_CREDIT_CAP_PCT = Decimal("0.20")

GATE_CLUSTER_GATE_WEIGHT = 40
GATE_CLUSTER_MISMATCH_WEIGHT = 25
ROLLING_WINDOW_FREQUENCY_WEIGHT = 15
ROLLING_WINDOW_MISMATCH_WEIGHT = 35
ROLLING_WINDOW_DAYS = 7
ROLLING_WINDOW_FREE_ENTRIES = 3
ANTIPASSBACK_MINUTES = 90


def dec(value):
    return Decimal(str(value))


def half_up(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def half_up_int(value):
    return int(half_up(value, 0))


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


# ---------- park day capacity posture ----------

def derive_posture(program, capacity_total, forecast_attendance):
    utilization = half_up(dec(forecast_attendance) / dec(capacity_total), 4)
    lock = dec(program["capacity_lock_threshold_pct"])
    peak = dec(program["capacity_peak_threshold_pct"])
    if utilization >= lock:
        day_class = "CAPACITY_LOCKED"
    elif utilization >= peak:
        day_class = "PEAK"
    else:
        day_class = "STANDARD"
    slot_capacity = max(
        0,
        min(floor_int(dec(capacity_total) * SLOT_CAPACITY_PCT), capacity_total - forecast_attendance),
    )
    window_capacity = max(1, floor_int(dec(slot_capacity) / dec(2)))
    return float(utilization), day_class, slot_capacity, window_capacity


# ---------- payment plan amortisation ----------

def min_down_payment_cents(contract_value_cents):
    return half_up_int(dec(contract_value_cents) * MIN_DOWN_PAYMENT_PCT)


def amortize(outstanding_cents, down_payment_cents, installment_count):
    financed = outstanding_cents - down_payment_cents + PLAN_SETUP_FEE_CENTS
    monthly = half_up_int(dec(financed) / dec(installment_count))
    final = financed - monthly * (installment_count - 1)
    return financed, monthly, final


# ---------- upgrade pricing ----------

def upgrade_admin_fee_cents(net_delta_cents):
    if net_delta_cents <= UPGRADE_FEE_BAND_1_MAX_CENTS:
        return 0
    if net_delta_cents <= UPGRADE_FEE_BAND_2_MAX_CENTS:
        return UPGRADE_FEE_BAND_2_FEE_CENTS
    return UPGRADE_FEE_BAND_3_FEE_CENTS


def prorated_ratio(future_days, total_days):
    if total_days == 0:
        return Decimal("0.0000")
    return half_up(dec(future_days) / dec(total_days), 4)


def upgrade_settlement(gross_delta_cents, raw_credit_cents):
    credit = min(raw_credit_cents, gross_delta_cents)
    net = gross_delta_cents - credit
    fee = upgrade_admin_fee_cents(net)
    return credit, net, fee, net + fee


# ---------- renewal pricing ----------

def early_bird_discount_cents(standard_price_cents):
    return half_up_int(dec(standard_price_cents) * EARLY_BIRD_DISCOUNT_PCT)


def raw_retention_credit_cents(prior_visit_count):
    if prior_visit_count >= RETENTION_HIGH_VISITS:
        return RETENTION_HIGH_CREDIT_CENTS
    if prior_visit_count >= RETENTION_MID_VISITS:
        return RETENTION_MID_CREDIT_CENTS
    return 0


def retention_credit_cents(raw_credit_cents, discounted_price_cents):
    cap = floor_int(dec(discounted_price_cents) * RETENTION_CREDIT_CAP_PCT)
    return min(raw_credit_cents, cap)


# ---------- analytics ----------

def visits_per_active_pass(total_visit_count, active_pass_count):
    if active_pass_count == 0:
        return 0.00
    return float(half_up(dec(total_visit_count) / dec(active_pass_count), 2))


def spend_per_visit_cents(total_spend_cents, visit_count):
    if visit_count == 0:
        return 0
    return floor_int(dec(total_spend_cents) / dec(visit_count))
