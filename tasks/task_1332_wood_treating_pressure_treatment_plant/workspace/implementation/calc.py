"""Calculation rules (scaffold Table 3 / PRD section 3).

All retention chemistry is carried at three decimal places, round-half-up,
applied only after the underlying multiplications finish (the final-retention
workflow adds an intermediate four-decimal per-piece rounding). Money is
integer cents, rounded half-up at each pinned multiplication step.
"""

from decimal import Decimal, ROUND_HALF_UP

# --- Retention target lookup keyed by use_category ---
TARGET_RETENTION_PCF = {
    "UC3B": 0.25,
    "UC4A": 0.40,
    "UC4B": 0.60,
    "UC4C": 0.60,
}

# --- Species penetration factors (provisional_retention_calc) ---
SPECIES_FACTOR = {
    "SPF": Decimal("0.85"),
    "SYP": Decimal("0.92"),
    "DOUGLAS_FIR": Decimal("0.65"),
    "HEM_FIR": Decimal("0.72"),
    "PONDEROSA_PINE": Decimal("0.78"),
}
SPECIES_FACTOR_INCISED = {
    "DOUGLAS_FIR": Decimal("0.95"),
    "HEM_FIR": Decimal("0.93"),
}

# --- hazard_liability_calc constants ---
PER_LITER_RATE_CENTS = 250
BREACH_THRESHOLD_LITERS = 50
CRITICAL_BREACH_SURCHARGE_CENTS = 250000
SCRAP_DISPOSAL_PER_MBF_CENTS = 75000
COMPLIANCE_BREACH_PENALTY = 50
COMPLIANCE_SCRAP_PENALTY = 100

# --- registration_fee_calc constants ---
BASE_FEE_CENTS = {"UC3B": 1500, "UC4A": 3200, "UC4B": 5800, "UC4C": 9100}
TIER2_DISCOUNT = Decimal("0.05")
TIER3_DISCOUNT = Decimal("0.12")
CUSTOM_TREAT_UPLIFT = Decimal("0.18")
TERM_MULTIPLIER = {5: Decimal("1.00"), 25: Decimal("1.45"), 50: Decimal("1.95")}

# --- preservative stock-level threshold (gallons) ---
LOW_STOCK_GALLONS = 100.0

# --- compliance thresholds ---
SUSPEND_THRESHOLD = 300

# --- estimated preservative consumption per cycle start (gallons per mbf) ---
CONSUMPTION_GALLONS_PER_MBF = 10.0

MARGINAL_THRESHOLD_PCT = Decimal("0.90")

INCISING_SPECIES = {"DOUGLAS_FIR", "HEM_FIR"}
INCISING_USE_CATEGORIES = {"UC4B", "UC4C"}


def _dec(v):
    return Decimal(str(v))


def round3(v):
    return float(_dec(v).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def round_cents(v):
    return int(_dec(v).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def requires_incising(species_group, use_category):
    return species_group in INCISING_SPECIES and use_category in INCISING_USE_CATEGORIES


def piece_factor(charge, piece):
    """Applicable species penetration factor for one piece."""
    if charge["requires_incising"] and piece.get("incised"):
        return SPECIES_FACTOR_INCISED.get(charge["species_group"], SPECIES_FACTOR[charge["species_group"]])
    return SPECIES_FACTOR[charge["species_group"]]


def provisional_retention(charge, pieces, gross_absorption_pcf, solution_assay_at_start_pct):
    """forward_looking: gross_absorption * (assay/100) * species factor, per piece,
    averaged to the charge level; rounded to 3 dp half-up after all
    multiplications are complete."""
    gross = _dec(gross_absorption_pcf)
    assay_frac = _dec(solution_assay_at_start_pct) / Decimal(100)
    live = [p for p in pieces if p.get("status") != "SCRAPPED"]
    if not live:
        return round3(gross * assay_frac * SPECIES_FACTOR[charge["species_group"]])
    total = Decimal(0)
    for p in live:
        total += gross * assay_frac * piece_factor(charge, p)
    return round3(total / Decimal(len(live)))


def piece_volume_cuft(piece):
    return (_dec(piece["length_ft"]) * _dec(piece["width_in"]) * _dec(piece["thickness_in"])) / Decimal(12)


def final_retention(charge, pieces, mean_retention_pcf):
    """chronological: volume-weighted mean across pieces. Each piece retention is
    mean * (applicable factor / charge-wide average factor); each per-piece
    contribution (retention * volume) is rounded to 4 dp before the sum; the
    final ratio is rounded half-up to 3 dp."""
    mean = _dec(mean_retention_pcf)
    live = sorted(
        [p for p in pieces if p.get("status") != "SCRAPPED"],
        key=lambda p: (p["created_at"], p["_seq"]),
    )
    if not live:
        return round3(mean)
    factor_avg = sum(piece_factor(charge, p) for p in live) / Decimal(len(live))
    total_contrib = Decimal(0)
    total_volume = Decimal(0)
    for p in live:
        piece_ret = mean * piece_factor(charge, p) / factor_avg
        vol = piece_volume_cuft(p)
        contrib = (piece_ret * vol).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        total_contrib += contrib
        total_volume += vol
    if total_volume == 0:
        return round3(mean)
    return round3(total_contrib / total_volume)


def assay_outcome(target_retention_pcf, mean_retention_pcf, min_sample_retention_pcf):
    """Returns (pass_threshold_pcf, outcome). Boundaries are inclusive at both
    the target and the threshold."""
    target = _dec(target_retention_pcf).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    mean = _dec(mean_retention_pcf).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    min_sample = _dec(min_sample_retention_pcf).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    threshold = (target * MARGINAL_THRESHOLD_PCT).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    if mean >= target and min_sample >= threshold:
        outcome = "PASS"
    elif mean < threshold:
        outcome = "FAIL_GROSS"
    else:
        outcome = "FAIL_MARGINAL"
    return float(threshold), outcome


def registration_fee_cents(charge, warranty_term_years):
    """tiered_pricing with a pinned order: base -> volume_discount ->
    custom_uplift -> term_multiplier; each multiplication rounds half-up to
    whole cents before the next factor is applied."""
    base = Decimal(BASE_FEE_CENTS[charge["use_category"]])
    volume = _dec(charge["volume_mbf"])
    if volume > 50:
        discount = TIER3_DISCOUNT
    elif volume > 10:
        discount = TIER2_DISCOUNT
    else:
        discount = Decimal(0)
    step = _dec(round_cents(base * (Decimal(1) - discount)))
    if charge["is_custom_treat"]:
        step = _dec(round_cents(step * (Decimal(1) + CUSTOM_TREAT_UPLIFT)))
    fee = round_cents(step * TERM_MULTIPLIER[warranty_term_years])
    return fee


def breach_liability_cents(drip_volume_liters):
    """$2.50/L rounded half-up to whole cents; +$2,500 surcharge when the spill
    exceeds 50 liters."""
    liability = round_cents(_dec(drip_volume_liters) * PER_LITER_RATE_CENTS)
    critical = _dec(drip_volume_liters) > BREACH_THRESHOLD_LITERS
    if critical:
        liability += CRITICAL_BREACH_SURCHARGE_CENTS
    return liability, critical


def scrap_liability_cents(volume_mbf):
    return round_cents(_dec(volume_mbf) * SCRAP_DISPOSAL_PER_MBF_CENTS)


def clamp_score(score):
    return max(0, score)


def refresh_stock_status(pres):
    """Automatic stock-level transitions after an inventory change."""
    if pres["status"] in ("IN_STOCK", "LOW_STOCK"):
        if pres["inventory_gallons"] == 0:
            pres["status"] = "DEPLETED"
        elif pres["inventory_gallons"] < LOW_STOCK_GALLONS:
            pres["status"] = "LOW_STOCK"
        else:
            pres["status"] = "IN_STOCK"


def refresh_customer_status(cust):
    """Automatic credit-hold transition when exposure exceeds the limit."""
    if cust["status"] == "ACTIVE" and cust["outstanding_balance_cents"] > cust["credit_limit_cents"]:
        cust["status"] = "CREDIT_HOLD"
    elif cust["status"] == "CREDIT_HOLD" and cust["outstanding_balance_cents"] <= cust["credit_limit_cents"]:
        cust["status"] = "ACTIVE"
