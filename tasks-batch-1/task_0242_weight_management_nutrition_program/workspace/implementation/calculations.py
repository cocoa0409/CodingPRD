"""All calculation rules (PRD 2.6 + Section 3). Decimal + ROUND_HALF_UP."""
from decimal import Decimal, ROUND_HALF_UP

GOAL_FRACTION = Decimal("0.10")
ASSUMED_BASELINE_FAT = Decimal("0.30")
MIN_COUNTED_WEIGHINS = 3
SECONDS_PER_DAY = 86400

# eligibility composite-score constants
ELIGIBILITY_THRESHOLD = Decimal("35")
BMI_BASE = Decimal("25.0")
BMI_WEIGHT = Decimal("4")
COMORBID_WEIGHT = Decimal("15")
BMI_CAP = Decimal("40")
COMORBID_CAP = Decimal("30")

# Rx BMI gate
RX_BMI_MIN = Decimal("30.0")
RX_BMI_COMORBID_MIN = Decimal("27.0")


def _d(value):
    return Decimal(str(value))


def round_half_up(value, places):
    quant = Decimal(1).scaleb(-places)  # 10^-places
    return _d(value).quantize(quant, rounding=ROUND_HALF_UP)


def _round_pct(value):
    """2-decimal round-half-up; return as float for JSON."""
    return float(round_half_up(value, 2))


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def compute_bmi(weight_kg, height_cm):
    """BMI = weight_kg / (height_cm/100)^2, round 1 decimal half-up."""
    height_m = _d(height_cm) / Decimal("100")
    bmi = _d(weight_kg) / (height_m * height_m)
    return float(round_half_up(bmi, 1))


def compute_risk_band(bmi, comorbidity_count):
    b = _d(bmi)
    if b >= Decimal("35.0") or comorbidity_count >= 2:
        return "HIGH"
    if b >= Decimal("30.0") or comorbidity_count == 1:
        return "MODERATE"
    return "LOW"


def compute_scale_progress_pct(baseline_weight_kg, latest_weight_kg):
    if baseline_weight_kg is None or latest_weight_kg is None:
        return 0
    baseline = _d(baseline_weight_kg)
    latest = _d(latest_weight_kg)
    lost = baseline - latest
    denom = baseline * GOAL_FRACTION
    if denom == 0:
        return 0
    raw = (lost / denom) * Decimal("100")
    raw = _clamp(raw, Decimal("0"), Decimal("100"))
    return _round_pct(raw)


def compute_lean_adjusted_progress_pct(baseline_weight_kg, latest_weight_kg,
                                       latest_lean_mass_kg):
    if baseline_weight_kg is None or latest_lean_mass_kg is None:
        return 0
    baseline = _d(baseline_weight_kg)
    latest_w = _d(latest_weight_kg)
    latest_lean = _d(latest_lean_mass_kg)
    baseline_lean = baseline * (Decimal("1") - ASSUMED_BASELINE_FAT)
    baseline_fat = baseline - baseline_lean
    latest_fat = latest_w - latest_lean
    fat_lost = baseline_fat - latest_fat
    denom = baseline * GOAL_FRACTION
    if denom == 0:
        return 0
    raw = (fat_lost / denom) * Decimal("100")
    raw = _clamp(raw, Decimal("0"), Decimal("100"))
    return _round_pct(raw)


def compute_goal_progress_pct(baseline_weight_kg, latest_weight_kg, target_weight_kg):
    if latest_weight_kg is None:
        return 0
    baseline = _d(baseline_weight_kg)
    target = _d(target_weight_kg)
    latest = _d(latest_weight_kg)
    span = baseline - target
    if span == 0:
        return 0
    lost = baseline - latest
    raw = (lost / span) * Decimal("100")
    raw = _clamp(raw, Decimal("0"), Decimal("100"))
    return _round_pct(raw)


def compute_lean_mass(weight_kg, body_fat_pct):
    """weight_kg * (1 - body_fat_pct/100), round 2 half-up."""
    val = _d(weight_kg) * (Decimal("1") - _d(body_fat_pct) / Decimal("100"))
    return float(round_half_up(val, 2))


def compute_eligibility_composite_score(bmi, comorbidity_count, tier):
    bmi_pts = min(BMI_CAP, max(Decimal("0"), (_d(bmi) - BMI_BASE) * BMI_WEIGHT))
    comorbid_pts = min(COMORBID_CAP, _d(comorbidity_count) * COMORBID_WEIGHT)
    if tier == "RX":
        tier_pts = Decimal("20")
    elif tier == "COACHING":
        tier_pts = Decimal("10")
    else:  # MEAL
        tier_pts = Decimal("5")
    total = bmi_pts + comorbid_pts + tier_pts
    return _round_pct(total)


def compute_invoice_lines(monthly_fee_cents, enrollment_fee_cents, cycle_index):
    """Round each line to whole cents independently, then sum (PRD 2.6)."""
    lines = [{
        "code": "RECURRING_FEE",
        "amount_cents": int(round_half_up(monthly_fee_cents, 0)),
    }]
    if cycle_index == 0 and enrollment_fee_cents > 0:
        lines.append({
            "code": "ENROLLMENT_FEE",
            "amount_cents": int(round_half_up(enrollment_fee_cents, 0)),
        })
    subtotal = sum(line["amount_cents"] for line in lines)
    return lines, subtotal


def compute_proration_credit(current_utc_seconds, period_start_seconds,
                             cycle_length_days, monthly_fee_cents):
    """Chronological day-counted proration credit (PRD 3.11)."""
    import math
    elapsed_days = math.floor(
        (current_utc_seconds - period_start_seconds) / SECONDS_PER_DAY
    )
    elapsed_days = int(_clamp(elapsed_days, 0, cycle_length_days))
    unused_days = cycle_length_days - elapsed_days
    daily_rate_cents = int(round_half_up(
        _d(monthly_fee_cents) / _d(cycle_length_days), 0
    ))
    proration_credit_cents = daily_rate_cents * unused_days
    return proration_credit_cents


def compute_hsa_fsa_eligible_cents(line_items, eligible):
    """Sum of RECURRING_FEE + PRORATION_CREDIT lines, floored at 0.
    ENROLLMENT_FEE is never reimbursable."""
    if not eligible:
        return 0
    total = 0
    for line in line_items:
        if line["code"] in ("RECURRING_FEE", "PRORATION_CREDIT"):
            total += line["amount_cents"]
    return max(0, total)
