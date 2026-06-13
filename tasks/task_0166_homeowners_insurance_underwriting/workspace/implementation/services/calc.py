"""Calculation rules (scaffold §1.3, PRD §3.1/§3.2/§3.4/§3.5/§3.7).

All money uses Decimal with ROUND_HALF_UP. Never float.
"""
from decimal import Decimal, ROUND_HALF_UP

# ---- replacement_cost_estimate constants (§1.3) ----
CONSTRUCTION_RATE = {"FRAME": Decimal("120"), "MASONRY": Decimal("150"), "FIRE_RESISTIVE": Decimal("185")}
ROOF_RATE = {"FRAME": Decimal("18"), "MASONRY": Decimal("22"), "FIRE_RESISTIVE": Decimal("26")}
BLEND_UPLIFT = {"FRAME": Decimal("1.18"), "MASONRY": Decimal("1.16"), "FIRE_RESISTIVE": Decimal("1.15")}
STORY_STEP = Decimal("0.04")

# ---- wildfire_score constants (§1.3) ----
W_FUEL = Decimal("0.7")
W_SLOPE = Decimal("0.5")
W_SPACE = Decimal("0.3")
SPACE_CAP = 200
MITIGATION_CREDIT = 12

# ---- annual_premium constants (§1.3) ----
TIER_RATE = [
    {"lo": Decimal("0"), "hi": Decimal("200000"), "rate": Decimal("0.0040")},
    {"lo": Decimal("200000"), "hi": Decimal("400000"), "rate": Decimal("0.0035")},
    {"lo": Decimal("400000"), "hi": Decimal("999999999"), "rate": Decimal("0.0031")},
]
FLOOD_MULT = {"X": Decimal("1.0"), "A": Decimal("1.2"), "AE": Decimal("1.35"), "VE": Decimal("1.6")}
WIND_HAIL_MULT = {"TIER_1": Decimal("1.0"), "TIER_2": Decimal("1.18"), "TIER_3": Decimal("1.4")}
DED_CREDIT = {1: Decimal("0.0"), 2: Decimal("0.05"), 5: Decimal("0.12")}

# ---- wind_hail_deductible_amount (§1.3) ----
MIN_DEDUCTIBLE = Decimal("2500")

# ---- endorsement_premium_delta (§1.3) ----
PERIL_RATE = {
    "WATER_BACKUP": Decimal("0.004"),
    "SCREENED_ENCLOSURE": Decimal("0.003"),
    "ORDINANCE_LAW": Decimal("0.0025"),
    "EARTH_MOVEMENT": Decimal("0.006"),
    "MOLD": Decimal("0.005"),
}
EXCLUSION_CREDIT = {
    "WATER_BACKUP": Decimal("60"),
    "SCREENED_ENCLOSURE": Decimal("45"),
    "ORDINANCE_LAW": Decimal("80"),
    "EARTH_MOVEMENT": Decimal("140"),
    "MOLD": Decimal("70"),
}

# ---- premium_balance (§1.3) ----
REINSTATEMENT_FEE = Decimal("250")

_CENT = Decimal("0.01")
_ONE = Decimal("1")


def D(value):
    """Coerce a numeric (possibly float/int/str) to Decimal safely."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places=2):
    q = Decimal(1).scaleb(-places)  # 10**-places
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def round_int_half_up(value):
    return int(D(value).quantize(_ONE, rounding=ROUND_HALF_UP))


def to_money(value):
    """Normalize a stored money figure to a 2-dp Decimal (no further rounding bias)."""
    return D(value).quantize(_CENT, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# §1.3 replacement_cost_estimate
# ---------------------------------------------------------------------------
def replacement_cost(prop, method):
    ctype = prop["construction_type"]
    base_rate = CONSTRUCTION_RATE[ctype]
    stories = D(prop["stories"])
    story_factor = _ONE + STORY_STEP * (stories - _ONE)
    sqft = D(prop["square_footage"])

    if method == "COMPONENT":
        structure = base_rate * sqft * story_factor
        roof_repl = ROOF_RATE[ctype] * sqft
        capped_age = min(int(prop["roof_age_years"]), 20)
        roof_adj = roof_repl * (_ONE - D(capped_age) * Decimal("0.01"))
        return round_half_up(structure + roof_adj, 2)
    else:  # SQFT_BLEND
        blended_rate = base_rate * BLEND_UPLIFT[ctype]
        return round_half_up(blended_rate * sqft * story_factor, 2)


# ---------------------------------------------------------------------------
# §1.3 wildfire_score
# ---------------------------------------------------------------------------
def _wildfire_raw(ra):
    space = min(int(ra["defensible_space_ft"]), SPACE_CAP)
    raw = (
        W_FUEL * D(ra["wildfire_fuel_density"])
        + W_SLOPE * D(ra["slope_grade_pct"])
        - W_SPACE * D(space)
    )
    return raw


def wildfire_score(ra, stage):
    rounded = round_int_half_up(_wildfire_raw(ra))
    if stage == "FINAL":
        rounded = rounded - MITIGATION_CREDIT
    return max(0, min(100, rounded))


def wind_hail_tier(distance_to_coast_mi):
    d = D(distance_to_coast_mi)
    if d < Decimal("5"):
        return "TIER_3"
    if d <= Decimal("50"):
        return "TIER_2"
    return "TIER_1"


# ---------------------------------------------------------------------------
# §1.3 annual_premium / base_premium  (Quote.base_premium)
# ---------------------------------------------------------------------------
def base_premium(requested_coverage_a, wind_hail_deductible_pct, wf_score, flood_zone, wh_tier):
    cov = D(requested_coverage_a)
    # Step 1 — tier rate on requested_coverage_a in [lo, hi)
    rate = None
    for tier in TIER_RATE:
        if tier["lo"] <= cov < tier["hi"]:
            rate = tier["rate"]
            break
    if rate is None:
        rate = TIER_RATE[-1]["rate"]
    # Step 2 — base
    base = cov * rate
    # Step 3 — zone multipliers
    wf_mult = _ONE + max(0, int(wf_score) - 40) * Decimal("0.005")
    fl_mult = FLOOD_MULT[flood_zone]
    wh_mult = WIND_HAIL_MULT[wh_tier]
    zoned = base * wf_mult * fl_mult * wh_mult
    # Step 4 — deductible credit
    credit = DED_CREDIT[int(wind_hail_deductible_pct)]
    base_premium_raw = zoned * (_ONE - credit)
    return round_half_up(base_premium_raw, 2)


# ---------------------------------------------------------------------------
# §1.3 wind_hail_deductible_amount
# ---------------------------------------------------------------------------
def wind_hail_deductible_amount(requested_coverage_a, wind_hail_deductible_pct):
    raw = D(requested_coverage_a) * (D(wind_hail_deductible_pct) / D(100))
    return round_half_up(max(raw, MIN_DEDUCTIBLE), 2)


# ---------------------------------------------------------------------------
# §1.3 endorsement_premium_delta
# ---------------------------------------------------------------------------
def endorsement_premium_delta(kind, peril_code, coverage_limit):
    if kind == "PERIL_ADD":
        return round_half_up(D(coverage_limit) * PERIL_RATE[peril_code], 2)
    else:  # EXCLUSION
        return -round_half_up(EXCLUSION_CREDIT[peril_code], 2)
