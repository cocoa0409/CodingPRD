"""Calculation modules per PRD Section 3 and scaffold Table 3.

All money is integer cents; fractional results round half-up at the pinned
step. Rates/indices round half-up to 4 decimal places.
"""

from decimal import Decimal, ROUND_HALF_UP

# --- Constants (scaffold Table 3) ---
BASE_RATE_CENTS = 1000000
DRG_WEIGHTS = {"470": Decimal("1.5"), "193": Decimal("0.95"), "392": Decimal("0.72")}
MEAN_LOS = {"470": 5, "193": 4, "392": 3}
OUTLIER_LOS_THRESHOLD = 10
OUTLIER_PER_DIEM_CENTS = 50000
OUTLIER_CAP_PCT = Decimal("0.20")
CONTRACT_DISCOUNT = Decimal("0.065")
FP_SUSPEND_THRESHOLD = Decimal("0.25")
FP_MIN_SAMPLE = 4
WEIGHT_OVERTURN = Decimal("0.6")
WEIGHT_FP = Decimal("0.4")
TIER_MEDIUM_MIN = Decimal("0.25")
TIER_HIGH_MIN = Decimal("0.50")
READMISSION_WINDOW_DAYS = 30
HIGH_DOLLAR_THRESHOLD_CENTS = 10000000
IBR_DOCUMENTS_DUE_DAYS = 30
IBR_OCCUPANCY_BUFFER_DAYS = 14
DISPUTE_WINDOW_DAYS = 45
DECISION_DEADLINE_DAYS = 60
MAX_IN_REVIEW_TASKS = 3
TRAILING_DAYS = 90


def round_half_up_cents(x: Decimal) -> int:
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round4(x: Decimal) -> float:
    """Round half-up to 4 decimals; return as float for JSON rendering."""
    return float(x.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def whole_days(later, earlier) -> int:
    """Whole days between two datetimes (later - earlier)."""
    delta = later - earlier
    return delta.days


def drg_payment(drg_code: str, admission_date, discharge_date, discharge_disposition: str) -> int:
    """DRG base payment per PRD 3.4 / calc drg_base_payment.

    Pinned rounding: round base first, then outlier cap, then per-diem;
    final payment is an exact integer min.
    """
    los = whole_days(discharge_date, admission_date)
    weight = DRG_WEIGHTS[drg_code]
    base = round_half_up_cents(Decimal(BASE_RATE_CENTS) * weight)
    if los > OUTLIER_LOS_THRESHOLD:
        per_day_extra = (los - OUTLIER_LOS_THRESHOLD) * OUTLIER_PER_DIEM_CENTS
        cap = round_half_up_cents(OUTLIER_CAP_PCT * Decimal(base))
        outlier_addon = min(per_day_extra, cap)
    else:
        outlier_addon = 0
    gross = base + outlier_addon
    if discharge_disposition == "TRANSFER":
        per_diem = round_half_up_cents(Decimal(base) / Decimal(MEAN_LOS[drg_code]))
        return min(gross, los * per_diem)
    return gross


def itemized_reprice(lines) -> int:
    """Itemized reprice: per-line round_half_up then sum (pinned order)."""
    total = 0
    for line in lines:
        repriced = round_half_up_cents(Decimal(line["billed_cents"]) * (Decimal(1) - CONTRACT_DISCOUNT))
        total += repriced
    return total
