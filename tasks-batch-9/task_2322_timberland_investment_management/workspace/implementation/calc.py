"""Domain constants and the eleven pinned calculations (PRD 2.6 / 3.x).

Every rounding step named by the specification is performed exactly where the
specification names it: computing an unrounded chain and rounding once at the
end produces different — and wrong — answers.
"""

from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 50

ZERO = Decimal("0.00")

# ----------------------------------------------------------------- constants
DAYS_PER_YEAR = 365

# C1 stand_cruise_volume
MIN_PLOTS_FOR_NORMAL_CONFIDENCE = 5
LOW_CONFIDENCE_HAIRCUT_PCT = Decimal("8")

# C2 growth_projection_volume
PERIODIC_GROWTH_PCT = {
    "LOBLOLLY_PINE": Decimal("4.2"),
    "DOUGLAS_FIR": Decimal("3.1"),
    "NORTHERN_HARDWOOD": Decimal("2.4"),
}
MAI_TONS_PER_ACRE_YEAR = {
    "LOBLOLLY_PINE": Decimal("2.1"),
    "DOUGLAS_FIR": Decimal("1.6"),
    "NORTHERN_HARDWOOD": Decimal("0.9"),
}

# C3 underwritten_value
HARVEST_PERIODS = 3
PERIOD_HARVEST_PCT = Decimal("25")
MIDPERIOD_OFFSET = Decimal("0.5")
REC_INCOME_MULTIPLE = Decimal("6.5")
ACQ_FEE_BREAK_1 = Decimal("1500000.00")
ACQ_FEE_BREAK_2 = Decimal("3250000.00")
MARKET_ACCESS_DISCOUNT_PCT = {
    "TIER_A": Decimal("0.0"),
    "TIER_B": Decimal("4.5"),
    "TIER_C": Decimal("9.0"),
    "TIER_D": Decimal("15.0"),
}

# C4 harvest_block_net_revenue
LOGGING_COST_USD_PER_TON = Decimal("12.75")
HAUL_RATE_USD_PER_TON_MILE = Decimal("0.145")
MAX_BILLABLE_HAUL_MILES = 90
SEVERANCE_TAX_PCT = Decimal("2.5")
MIN_SEVERANCE_TAX_USD = Decimal("250.00")
PRODUCT_MIX_FACTOR = {
    "SAWTIMBER": Decimal("1.00"),
    "MIXED": Decimal("0.82"),
    "PULPWOOD": Decimal("0.61"),
}

# C5 insurance_premium_and_risk_score
WEIGHT_WILDFIRE = Decimal("0.45")
WEIGHT_INSECT = Decimal("0.30")
WEIGHT_WEATHER = Decimal("0.25")
REGION_WILDFIRE_MULT = {
    "SOUTH": Decimal("1.00"),
    "WEST": Decimal("1.25"),
    "NORTHEAST": Decimal("0.80"),
}
SPECIES_INSECT_MULT = {
    "LOBLOLLY_PINE": Decimal("1.15"),
    "DOUGLAS_FIR": Decimal("1.00"),
    "NORTHERN_HARDWOOD": Decimal("1.00"),
}
HAZARD_INDEX_CAP = Decimal("100.00")
BASE_RATE_BPS = Decimal("38")
MIN_PREMIUM_USD = Decimal("1500.00")
TRAILING_CLAIM_WINDOW_DAYS = 1095

# C6 hazard_loss_reallocation
SALVAGE_RECOVERY_PCT = {
    "WILDFIRE": Decimal("35"),
    "INSECT": Decimal("55"),
    "WIND_STORM": Decimal("70"),
    "ICE_STORM": Decimal("60"),
}
INDEMNITY_RATE_USD_PER_TON = Decimal("22.50")
INSURANCE_INDEMNITY_PCT = Decimal("60")
CARBON_BUFFER_POOL_PCT = Decimal("18")
BUFFER_CURE_COST_USD_PER_TON = Decimal("14.00")

# C7 fund_nav_and_cash_yield
STALE_APPRAISAL_HAIRCUT_PCT = Decimal("12")
BPS_SCALE = Decimal("10000")

# C8 lease_rent_and_coverage
MAX_LEASE_COVERAGE_PCT = Decimal("80")

# C9 hbu_disposition_split
HBU_COMMISSION_PCT = Decimal("3.5")
MIN_RETAINED_ACRES = Decimal("5")

# C11 certification_posture_derivation
MAJOR_SUSPENSION_THRESHOLD = 2

# misc
MAX_REVISION_ROUNDS = 2
REENTRY_BUFFER_MONTHS = 24
APPRAISAL_STALE_DAYS = 365

REGIONS = ("SOUTH", "WEST", "NORTHEAST")
SPECIES = ("LOBLOLLY_PINE", "DOUGLAS_FIR", "NORTHERN_HARDWOOD")
GROWTH_VARIANTS = ("YIELD_TABLE", "MAI_LINEAR")


# ------------------------------------------------------------------ rounding
def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, dp=2):
    """Round half up to dp decimal places."""
    return D(value).quantize(Decimal(1).scaleb(-dp), rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


# ----------------------------------------------------------------------- C1
def cruise_volume(plot_net_tpa_values, acres):
    """Returns (mean_net_tons_per_acre, gross, confidence, net)."""
    plot_count = len(plot_net_tpa_values)
    total = sum((D(v) for v in plot_net_tpa_values), Decimal(0))
    mean = rhu(total / plot_count, 3)
    gross = rhu(mean * D(acres), 2)
    confidence = "NORMAL" if plot_count >= MIN_PLOTS_FOR_NORMAL_CONFIDENCE else "LOW"
    if confidence == "NORMAL":
        net = gross
    else:
        net = rhu(gross * (Decimal(1) - LOW_CONFIDENCE_HAIRCUT_PCT / 100), 2)
    return mean, gross, confidence, net


def plot_net_tons_per_acre(tons_per_acre, defect_pct):
    return rhu(D(tons_per_acre) * (Decimal(1) - D(defect_pct) / 100), 3)


# ----------------------------------------------------------------------- C2
def growth_projection_volume(base_tons, acres, species_code, years, variant):
    base = D(base_tons)
    if species_code is None:
        return rhu(base, 2)
    years = int(years)
    if variant == "YIELD_TABLE":
        factor = (Decimal(1) + PERIODIC_GROWTH_PCT[species_code] / 100) ** years
        return rhu(base * factor, 2)
    return rhu(base + MAI_TONS_PER_ACRE_YEAR[species_code] * D(acres) * years, 2)


def years_to_start(clock_date, start_date):
    return (start_date - clock_date).days // DAYS_PER_YEAR


# ----------------------------------------------------------------------- C3
def market_access(haul_distance_miles):
    miles = int(haul_distance_miles)
    if miles <= 40:
        tier = "TIER_A"
    elif miles <= 80:
        tier = "TIER_B"
    elif miles <= 140:
        tier = "TIER_C"
    else:
        tier = "TIER_D"
    return tier, MARKET_ACCESS_DISCOUNT_PCT[tier]


def underwritten_value(base_tons, acres, species_code, discount_pct,
                       growth_variant, discount_rate_bps,
                       stumpage_price_usd_per_ton, hbu_acres,
                       hbu_price_per_acre_usd, annual_rec_income_usd):
    disc = D(discount_pct)
    stumpage = D(stumpage_price_usd_per_ton)
    bps = D(discount_rate_bps)
    timber_pv = Decimal(0)
    for k in range(1, HARVEST_PERIODS + 1):
        vol_k = growth_projection_volume(base_tons, acres, species_code, k, growth_variant)
        tons_k = rhu(vol_k * PERIOD_HARVEST_PCT / 100, 2)
        rev_k = rhu(tons_k * stumpage * (Decimal(1) - disc / 100), 2)
        df_k = (Decimal(1) + bps / BPS_SCALE) ** (Decimal(k) - MIDPERIOD_OFFSET)
        pv_k = rhu(rev_k / df_k, 2)
        timber_pv += pv_k
    timber_pv_usd = rhu(timber_pv, 2)
    hbu_premium_usd = rhu(D(hbu_acres) * D(hbu_price_per_acre_usd), 2)
    rec_income_pv_usd = rhu(D(annual_rec_income_usd) * REC_INCOME_MULTIPLE, 2)
    pre_fee_value_usd = rhu(timber_pv_usd + hbu_premium_usd + rec_income_pv_usd, 2)

    # The tier is keyed on the PRE-fee value, never on the post-fee figure.
    if pre_fee_value_usd < ACQ_FEE_BREAK_1:
        fee_pct = Decimal("1.50")
    elif pre_fee_value_usd < ACQ_FEE_BREAK_2:
        fee_pct = Decimal("1.00")
    else:
        fee_pct = Decimal("0.75")
    acquisition_fee_usd = rhu(pre_fee_value_usd * fee_pct / 100, 2)
    underwritten = rhu(pre_fee_value_usd - acquisition_fee_usd, 2)
    return {
        "timber_pv_usd": timber_pv_usd,
        "hbu_premium_usd": hbu_premium_usd,
        "rec_income_pv_usd": rec_income_pv_usd,
        "pre_fee_value_usd": pre_fee_value_usd,
        "acquisition_fee_pct": fee_pct,
        "acquisition_fee_usd": acquisition_fee_usd,
        "underwritten_value_usd": underwritten,
    }


# ----------------------------------------------------------------------- C4
def net_revenue(tons, stumpage, index, product_mix, haul_miles):
    tons = D(tons)
    effective_price = rhu(D(stumpage) * D(index) * PRODUCT_MIX_FACTOR[product_mix], 4)
    gross_usd = rhu(tons * effective_price, 2)
    logging_usd = rhu(tons * LOGGING_COST_USD_PER_TON, 2)
    billable_miles = min(int(haul_miles), MAX_BILLABLE_HAUL_MILES)
    haul_usd = rhu(tons * HAUL_RATE_USD_PER_TON_MILE * billable_miles, 2)
    severance_usd = max(rhu(gross_usd * SEVERANCE_TAX_PCT / 100, 2), MIN_SEVERANCE_TAX_USD)
    net_usd = rhu(gross_usd - logging_usd - haul_usd - severance_usd, 2)
    return {
        "effective_price": effective_price,
        "gross_usd": gross_usd,
        "logging_usd": logging_usd,
        "haul_usd": haul_usd,
        "severance_tax_usd": severance_usd,
        "net_revenue_usd": net_usd,
    }


# ----------------------------------------------------------------------- C5
def composite_risk_score(region_code, species_code, wildfire, insect, weather):
    wildfire_adj = min(HAZARD_INDEX_CAP,
                       rhu(D(wildfire) * REGION_WILDFIRE_MULT[region_code], 2))
    insect_mult = SPECIES_INSECT_MULT[species_code] if species_code else Decimal("1.00")
    insect_adj = min(HAZARD_INDEX_CAP, rhu(D(insect) * insect_mult, 2))
    return rhu(WEIGHT_WILDFIRE * wildfire_adj
               + WEIGHT_INSECT * insect_adj
               + WEIGHT_WEATHER * D(weather), 2)


def insurance_premium(basis, insured_value_usd, composite, trailing_claims_usd):
    insured = D(insured_value_usd)
    base_premium = rhu(insured * BASE_RATE_BPS / BPS_SCALE, 2)
    if basis == "ACTUARIAL":
        premium = max(rhu(base_premium * (Decimal(1) + D(composite) / 100), 2),
                      MIN_PREMIUM_USD)
        return premium, None
    if insured == 0:
        loss_ratio = Decimal("0.0000")
    else:
        loss_ratio = rhu(D(trailing_claims_usd) / insured, 4)
    premium = max(rhu(base_premium * (Decimal(1) + loss_ratio), 2), MIN_PREMIUM_USD)
    return premium, loss_ratio


# ----------------------------------------------------------------------- C6
def salvageable_tons(event_type, damaged_tons):
    return rhu(D(damaged_tons) * SALVAGE_RECOVERY_PCT[event_type] / 100, 2)


def insurance_claim_usd(damaged_tons):
    return rhu(D(damaged_tons) * INDEMNITY_RATE_USD_PER_TON
               * INSURANCE_INDEMNITY_PCT / 100, 2)


# ----------------------------------------------------------------------- C8
def annual_rent(leased_acres, rent_per_acre_usd):
    return rhu(D(leased_acres) * D(rent_per_acre_usd), 2)


def first_year_prorated_rent(annual_rent_usd, term_days):
    days = min(int(term_days), DAYS_PER_YEAR)
    return rhu(D(annual_rent_usd) * days / DAYS_PER_YEAR, 2)


def earned_rent(annual_rent_usd, earned_days):
    return rhu(D(annual_rent_usd) * int(earned_days) / DAYS_PER_YEAR, 2)


def lease_capacity(total_acres):
    return rhu(D(total_acres) * MAX_LEASE_COVERAGE_PCT / 100, 2)


# ----------------------------------------------------------------------- C9
def hbu_withdrawn_tons(stand_net_merch_tons, parcel_acres, stand_acres):
    return rhu(D(stand_net_merch_tons) * D(parcel_acres) / D(stand_acres), 2)


def hbu_commission(contract_price_usd):
    return rhu(D(contract_price_usd) * HBU_COMMISSION_PCT / 100, 2)


# ---------------------------------------------------------------------- C10
def appraised_value(methodology, total_acres, timber_basis_tons, inputs):
    if methodology == "INCOME":
        return rhu(D(inputs["stabilized_noi_usd"]) / (D(inputs["cap_rate_bps"]) / BPS_SCALE), 2)
    if methodology == "MARKET":
        return rhu(D(total_acres) * D(inputs["comparable_price_per_acre_usd"]), 2)
    return rhu(D(total_acres) * D(inputs["bare_land_value_per_acre_usd"])
               + D(timber_basis_tons) * D(inputs["timber_unit_value_usd_per_ton"]), 2)
