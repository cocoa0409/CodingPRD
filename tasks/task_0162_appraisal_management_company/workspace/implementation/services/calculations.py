"""Calculation rules (SCAFFOLD §1.3 / PRD §3.6, §3.8, §3.9, §3.7)."""
from decimal import Decimal, ROUND_HALF_UP

# ---- Fee split constants ----
RUSH_PREMIUM_PCT = Decimal("0.10")
REVISION_PENALTY_PCT = Decimal("0.05")
APPRAISER_FLOOR_CENTS = 5000

# ---- Panel score constants ----
W_COMPLETION = Decimal("0.4")
W_ON_TIME = Decimal("0.3")
W_LOAD = Decimal("0.3")
MAX_ACTIVE_LOAD = 5

# ---- SLA constants ----
SLA_BASE_HOURS = {"URAR_1004": 120, "CONDO_1073": 96, "EXTERIOR_2055": 72}
RUSH_SHORTEN_HOURS = 48

# ---- ROV constants ----
ROV_DELTA_THRESHOLD_PCT = Decimal("10.0")

# ---- USPAP / UAD constants ----
USPAP_MIN_COMPARABLES = 3
UAD_CONDITION_SET = {"C1", "C2", "C3", "C4", "C5", "C6"}
UAD_QUALITY_SET = {"Q1", "Q2", "Q3", "Q4", "Q5", "Q6"}


def round_half_up(value):
    """Round a Decimal to whole units, half up. Returns int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_n(value, places):
    q = Decimal(1).scaleb(-places)  # e.g. places=4 -> 0.0001
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# fee_split_computation (waterfall, per-component-then-sum)
# ---------------------------------------------------------------------------
def compute_fee_split(order_fee_cents, base_fee_share_pct, rush, revision_round):
    """Return (appraiser_fee_cents, amc_fee_cents, revision_penalty_cents).

    Per-component round_half_up to whole cents FIRST, then combine.
    """
    fee = Decimal(order_fee_cents)
    base = round_half_up(fee * Decimal(str(base_fee_share_pct)))  # component 1
    rush_premium = round_half_up(fee * RUSH_PREMIUM_PCT) if rush else 0  # component 2
    gross_appraiser = base + rush_premium

    penalty = 0
    per_round = round_half_up(fee * REVISION_PENALTY_PCT)
    for _ in range(int(revision_round)):
        penalty += per_round  # component 3, per-round then summed
    revision_penalty_cents = penalty

    appraiser_fee_cents = max(gross_appraiser - penalty, APPRAISER_FLOOR_CENTS)
    amc_fee_cents = order_fee_cents - appraiser_fee_cents  # conserved residual
    return appraiser_fee_cents, amc_fee_cents, revision_penalty_cents


# ---------------------------------------------------------------------------
# appraiser_panel_score (weighted scoring, 4 dp)
# ---------------------------------------------------------------------------
def compute_panel_score(status, completed_count, active_assignment_count, on_time_count):
    if status != "ACTIVE":
        return 0.0
    completed = Decimal(completed_count)
    active = Decimal(active_assignment_count)
    on_time = Decimal(on_time_count)

    completion_rate = completed / max(completed + active, Decimal(1))
    on_time_rate = on_time / max(completed, Decimal(1))
    load_ratio = active / Decimal(MAX_ACTIVE_LOAD)
    load_factor = Decimal(1) - min(load_ratio, Decimal(1))

    score = (W_COMPLETION * completion_rate
             + W_ON_TIME * on_time_rate
             + W_LOAD * load_factor)
    return float(round_half_up_n(score, 4))


# ---------------------------------------------------------------------------
# turnaround_sla
# ---------------------------------------------------------------------------
def projected_sla_hours(product_type, rush):
    base = SLA_BASE_HOURS[product_type]
    return base - RUSH_SHORTEN_HOURS if rush else base


def actual_turnaround_hours(accepted_at_dt, completed_dt):
    """Whole hours elapsed, floored."""
    delta = completed_dt - accepted_at_dt
    seconds = delta.total_seconds()
    if seconds < 0:
        seconds = 0
    return int(seconds // 3600)


def is_on_time(actual_hours, sla_hours):
    # breach iff actual > sla (strictly greater); equal is on-time.
    return actual_hours <= sla_hours


# ---------------------------------------------------------------------------
# rov_value_delta (2 dp)
# ---------------------------------------------------------------------------
def rov_value_delta(requested_value_cents, delivered_value_cents):
    delivered = Decimal(delivered_value_cents)
    pct = (abs(Decimal(requested_value_cents) - delivered) / delivered) * Decimal(100)
    value_delta_pct = round_half_up_n(pct, 2)
    requires_second_review = value_delta_pct > ROV_DELTA_THRESHOLD_PCT
    return float(value_delta_pct), bool(requires_second_review)
