"""All derived figures (PRD 3.1-3.9).  Every rounding point is named by the PRD."""
from core import DB, all_of, rhu, dec, floor_int, ceil_int, day_diff

# --------------------------------------------------------------------------- #
# Constants, all lifted verbatim from the PRD narrative
# --------------------------------------------------------------------------- #
COUNTED_BRANCH_STATUSES = ("ACTIVE", "UNDER_REVIEW", "CLOSURE_SCHEDULED", "DE_NOVO_RAMPING")

NETWORK_DEPOSIT_TARGET_CENTS = 12000000000
TRANSACTION_TARGET = 9000
EFFICIENCY_CEILING_BPS = 9000
EFFICIENCY_FLOOR_BPS = 5000
EFFICIENCY_SPREAD_BPS = 4000

W_DEPOSIT = 3500
W_TRANSACTION = 2000
W_DIGITAL = 1500
W_PROFITABILITY = 3000

TRAILING_WEIGHTS = (5000, 3000, 2000)

RETENTION_BASE_BPS = 9200
RETENTION_FLOOR_BPS = 5000
RETENTION_CEILING_BPS = 9800
DISTANCE_DECAY_PER_MILE_BPS = 400
DIGITAL_UPLIFT_RATE_BPS = 1500
DIGITAL_UPLIFT_CAP_BPS = 800
SEGMENT_RETAIL_BPS = 8200
SEGMENT_SMALL_BUSINESS_BPS = 7000
SEGMENT_WEALTH_BPS = 9100
SEGMENT_PENALTY_PER_MILE_BPS = 250
SEGMENT_PENALTY_CAP_BPS = 2500

DEPOSIT_SPREAD_BPS = 225
GOVERNANCE_FLOOR_CENTS = 15000000
INCENTIVE_TIER_HIGH_CENTS = 100000000
INCENTIVE_TIER_MID_CENTS = 40000000
INCENTIVE_RATE_HIGH_BPS = 12
INCENTIVE_RATE_MID_BPS = 18
INCENTIVE_RATE_LOW_BPS = 25

SEVERANCE_WEEKS_FLOOR = 4
SEVERANCE_WEEKS_CAP = 26
OUTPLACEMENT_STIPEND_CENTS = 120000
WARN_WAITING_DAYS = 60

IMPACT_BASE_POINTS = 20
IMPACT_LMI_POINTS = 25
IMPACT_DISTANCE_PER_MILE = 6
IMPACT_DISTANCE_CAP = 30
IMPACT_SENIOR_BPS_PER_POINT = 800
IMPACT_SENIOR_CAP = 15
IMPACT_ACCESS_RELIEF_PER = 5
IMPACT_ACCESS_RELIEF_CAP = 20
IMPACT_TRANSIT_RELIEF = 3
NOTICE_BASE_HIGH_DAYS = 120
NOTICE_BASE_OTHER_DAYS = 90
NOTICE_EXTENSION_DAYS = 30
NOTICE_CAP_DAYS = 180
NOTICE_EXTENSION_DISTANCE_MILES = dec("5.0")
NOTICE_BUFFER_DAYS = 30

OWNED_ANNUAL_CARRY_CENTS = 1800000
MARKETING_CHARGE_CENTS = 2400000
HOLDOVER_PREMIUM_BPS = 5000
ATM_RETENTION_MARGIN_FLOOR_CENTS = 600000

CAMPAIGN_NOTICE_LEAD_DAYS = 14
UNWIND_WINDOW_DAYS = 30
MONITORING_HORIZON_MONTHS = 12
BREACH_THRESHOLD_BPS = -300
RECOVERY_THRESHOLD_BPS = -150
RUNOFF_CURVE_BPS = (2500, 2000, 1500, 1000, 800, 600, 500, 400, 300, 200, 100, 100)

SITE_SCORE_MINIMUM = 55
SITE_GROWTH_DIVISOR_BPS = 5
SITE_INCOME_DIVISOR_CENTS = 120000
SITE_DEPOSIT_TARGET_CENTS = 15000000000
SITE_COMPETITION_MULTIPLIER = 4
SITE_FACTOR_CAP = 100
SITE_W_GROWTH = 3000
SITE_W_INCOME = 2500
SITE_W_OPPORTUNITY = 2500
SITE_W_COMPETITION = 2000
RAMP_AT_RISK_BPS = 7000
RAMP_MET_BPS = 9000
RAMP_ON_TRACK_BPS = 10000
RAMP_DIVISOR = 144


# --------------------------------------------------------------------------- #
# 3.1 trade-area density and saturation tier
# --------------------------------------------------------------------------- #
def competitor_density_index(competitor_branch_count, population):
    return rhu(competitor_branch_count * 100000, population)


def count_own_branches(market_area_id):
    n = 0
    for b in all_of("branches"):
        if b["market_area_id"] == market_area_id and b["status"] in COUNTED_BRANCH_STATUSES:
            n += 1
    return n


def branch_density_per_100k(own_branch_count, competitor_branch_count, population):
    return rhu((own_branch_count + competitor_branch_count) * 100000, population)


def saturation_tier(density):
    if density >= 30:
        return "OVER_BRANCHED"
    if density >= 15:
        return "SATURATED"
    return "UNDER_BRANCHED"


# --------------------------------------------------------------------------- #
# 3.2 snapshot factor scoring and banding
# --------------------------------------------------------------------------- #
def deposit_factor_bps(deposits_cents):
    return min(rhu(deposits_cents * 10000, NETWORK_DEPOSIT_TARGET_CENTS), 10000)


def transaction_factor_bps(transaction_count):
    return min(rhu(transaction_count * 10000, TRANSACTION_TARGET), 10000)


def digital_factor_bps(digital_active_bps):
    return min(digital_active_bps, 10000)


def efficiency_ratio_bps(revenue_cents, noninterest_expense_cents):
    if revenue_cents == 0:
        return 20000
    return rhu(noninterest_expense_cents * 10000, revenue_cents)


def profitability_factor_bps(revenue_cents, noninterest_expense_cents):
    ratio = efficiency_ratio_bps(revenue_cents, noninterest_expense_cents)
    raw = rhu((EFFICIENCY_CEILING_BPS - ratio) * 10000, EFFICIENCY_SPREAD_BPS)
    raw = min(raw, 10000)
    return max(raw, 0)


def composite_score_bps(deposit_bps, transaction_bps, digital_bps, profitability_bps):
    total = (deposit_bps * W_DEPOSIT + transaction_bps * W_TRANSACTION
             + digital_bps * W_DIGITAL + profitability_bps * W_PROFITABILITY)
    return rhu(total, 10000)


def performance_band(score_bps):
    if score_bps >= 7000:
        return "CORE"
    if score_bps >= 4000:
        return "STABLE"
    if score_bps >= 2000:
        return "WATCH"
    return "CONSOLIDATION_CANDIDATE"


def ordered_snapshots(branch_id):
    """Newest first: period_end_date desc, then created_at desc."""
    rows = [s for s in all_of("performance_snapshots") if s["branch_id"] == branch_id]
    rows.sort(key=lambda s: (s["period_end_date"], s["created_at"], s["_seq"]), reverse=True)
    return rows


def score_history(branch_id, variant):
    """Returns (performance_score_bps, band, contributing_snapshot_count)."""
    rows = ordered_snapshots(branch_id)
    if not rows:
        return None, "UNSCORED", 0
    if variant == "POINT_IN_TIME":
        score = rows[0]["composite_score_bps"]
        return score, performance_band(score), 1
    used = rows[:len(TRAILING_WEIGHTS)]
    weights = TRAILING_WEIGHTS[:len(used)]
    numerator = sum(s["composite_score_bps"] * w for s, w in zip(used, weights))
    score = rhu(numerator, sum(weights))
    return score, performance_band(score), len(used)


# --------------------------------------------------------------------------- #
# 3.3 retention model
# --------------------------------------------------------------------------- #
def retention_bps(variant, distance_miles, digital_adoption_bps,
                  retail_share_bps, small_business_share_bps, wealth_share_bps):
    if variant == "DISTANCE_DECAY":
        floored = floor_int(distance_miles)
        decay = max(floored - 1, 0) * DISTANCE_DECAY_PER_MILE_BPS
        base = max(RETENTION_BASE_BPS - decay, RETENTION_FLOOR_BPS)
        uplift = min(rhu(digital_adoption_bps * DIGITAL_UPLIFT_RATE_BPS, 10000),
                     DIGITAL_UPLIFT_CAP_BPS)
        return min(base + uplift, RETENTION_CEILING_BPS)
    weighted = rhu(retail_share_bps * SEGMENT_RETAIL_BPS
                   + small_business_share_bps * SEGMENT_SMALL_BUSINESS_BPS
                   + wealth_share_bps * SEGMENT_WEALTH_BPS, 10000)
    ceiled = ceil_int(distance_miles)
    penalty = min(max(ceiled - 1, 0) * SEGMENT_PENALTY_PER_MILE_BPS, SEGMENT_PENALTY_CAP_BPS)
    scaled = rhu(weighted * (10000 - penalty), 10000)
    return min(scaled, RETENTION_CEILING_BPS)


def retention_split(baseline_deposits_cents, bps):
    retained = rhu(baseline_deposits_cents * bps, 10000)
    return retained, baseline_deposits_cents - retained


# --------------------------------------------------------------------------- #
# 3.4 the savings chain - seven steps, exactly once each, top to bottom
# --------------------------------------------------------------------------- #
def incentive_rate_bps(gross_annual_savings_cents):
    if gross_annual_savings_cents >= INCENTIVE_TIER_HIGH_CENTS:
        return INCENTIVE_RATE_HIGH_BPS
    if gross_annual_savings_cents >= INCENTIVE_TIER_MID_CENTS:
        return INCENTIVE_RATE_MID_BPS
    return INCENTIVE_RATE_LOW_BPS


def case_property_carry_cents(case_id):
    total = 0
    for p in all_of("property_dispositions"):
        if p["consolidation_case_id"] == case_id:
            total += p["annual_carry_cents"]
    return total


def recompute_savings_chain(case):
    """Recomputes the chain in full (never incrementally).  Does not bump version."""
    closing = DB["branches"].get(case["closing_branch_id"])
    expense_avoided = closing["annual_noninterest_expense_cents"] if closing else 0
    revenue_attrition = rhu(case["forecast_runoff_cents"] * DEPOSIT_SPREAD_BPS, 10000)
    property_carry = case_property_carry_cents(case["id"])
    gross = expense_avoided - revenue_attrition - property_carry
    rate = incentive_rate_bps(gross)
    incentive = rhu(case["forecast_retained_deposits_cents"] * rate, 10000)
    case["gross_annual_savings_cents"] = gross
    case["transition_incentive_rate_bps"] = rate
    case["transition_incentive_cents"] = incentive
    case["net_annual_savings_cents"] = gross - incentive
    return case


# --------------------------------------------------------------------------- #
# 3.6 severance economics
# --------------------------------------------------------------------------- #
def severance_terms(proposed_disposition, tenure_months, annual_salary_cents):
    if proposed_disposition != "SEVERANCE":
        return 0, 0, 0
    service_years = tenure_months // 12
    weeks = max(2 * service_years, SEVERANCE_WEEKS_FLOOR)
    weeks = min(weeks, SEVERANCE_WEEKS_CAP)
    weekly = rhu(annual_salary_cents, 52)
    return weeks, weekly, weeks * weekly + OUTPLACEMENT_STIPEND_CENTS


def service_years_of(tenure_months):
    return tenure_months // 12


def recompute_severance_pool(case):
    total = 0
    for d in all_of("staff_dispositions"):
        if d["consolidation_case_id"] != case["id"]:
            continue
        if d["proposed_disposition"] != "SEVERANCE":
            continue
        if d["disposition_state"] not in ("PROPOSED", "SEVERED"):
            continue
        total += d["severance_amount_cents"]
    case["severance_pool_cents"] = total
    return total


# --------------------------------------------------------------------------- #
# 3.5 community impact
# --------------------------------------------------------------------------- #
def impact_score(lmi_tract, distance_miles, alternative_access_count,
                 senior_household_pct_bps, public_transit_access, market_tier):
    total = IMPACT_BASE_POINTS
    if lmi_tract:
        total += IMPACT_LMI_POINTS
    total += min(rhu(dec(distance_miles) * IMPACT_DISTANCE_PER_MILE), IMPACT_DISTANCE_CAP)
    total += min(senior_household_pct_bps // IMPACT_SENIOR_BPS_PER_POINT, IMPACT_SENIOR_CAP)
    if market_tier == "UNDER_BRANCHED":
        total += 10
    elif market_tier == "OVER_BRANCHED":
        total -= 5
    total -= min(IMPACT_ACCESS_RELIEF_PER * alternative_access_count, IMPACT_ACCESS_RELIEF_CAP)
    if public_transit_access:
        total -= IMPACT_TRANSIT_RELIEF
    total = max(total, 0)
    return min(total, 100)


def impact_tier(score):
    if score >= 60:
        return "HIGH"
    if score >= 35:
        return "MODERATE"
    return "LOW"


def notice_required_days(tier, lmi_tract, distance_miles):
    base = NOTICE_BASE_HIGH_DAYS if tier == "HIGH" else NOTICE_BASE_OTHER_DAYS
    if lmi_tract and dec(distance_miles) >= NOTICE_EXTENSION_DISTANCE_MILES:
        base += NOTICE_EXTENSION_DAYS
    return min(base, NOTICE_CAP_DAYS)


# --------------------------------------------------------------------------- #
# 3.7 premises carry and the ATM adjudication
# --------------------------------------------------------------------------- #
MARKETING_STATUSES = ("MARKETED", "HOLDOVER", "ASSIGNMENT_PENDING", "SALE_PENDING")


def annual_carry_cents(status, tenure_class, monthly_rent_cents):
    if status == "DISPOSED":
        base = 0
    elif tenure_class == "LEASED":
        base = 12 * (monthly_rent_cents or 0)
    else:
        base = OWNED_ANNUAL_CARRY_CENTS
    premium = rhu(base * HOLDOVER_PREMIUM_BPS, 10000) if status == "HOLDOVER" else 0
    marketing = MARKETING_CHARGE_CENTS if status in MARKETING_STATUSES else 0
    return base + premium + marketing


def refresh_carry(prop):
    prop["annual_carry_cents"] = annual_carry_cents(
        prop["status"], prop["tenure_class"], prop.get("monthly_rent_cents"))
    return prop["annual_carry_cents"]


def atm_adjudication(atm_disposition, atm_monthly_cost_cents, atm_monthly_surcharge_revenue_cents):
    margin = 12 * (atm_monthly_surcharge_revenue_cents - atm_monthly_cost_cents)
    breakeven = margin >= ATM_RETENTION_MARGIN_FLOOR_CENTS
    final = atm_disposition
    if atm_disposition == "RETAIN_OFFSITE" and not breakeven:
        final = "DECOMMISSION"
    return margin, breakeven, final


# --------------------------------------------------------------------------- #
# 3.8 transition waves
# --------------------------------------------------------------------------- #
def wave_metrics(wave_start_date, wave_end_date, inbound_household_count):
    days = day_diff(wave_end_date, wave_start_date)
    if days <= 0:
        return days, 0
    return days, rhu(inbound_household_count, days)


# --------------------------------------------------------------------------- #
# 3.9 runoff curve, ramp curve and de novo siting
# --------------------------------------------------------------------------- #
def cumulative_runoff_weight_bps(month_index):
    return sum(RUNOFF_CURVE_BPS[:month_index])


def case_forecast_deposits_cents(pre_close_deposits_cents, forecast_runoff_cents, month_index):
    weight = cumulative_runoff_weight_bps(month_index)
    return pre_close_deposits_cents - rhu(forecast_runoff_cents * weight, 10000)


def variance_against_forecast_bps(observed_deposits_cents, forecast_deposits_cents):
    if forecast_deposits_cents == 0:
        return 0
    return rhu((observed_deposits_cents - forecast_deposits_cents) * 10000, forecast_deposits_cents)


def ramp_target_cents(target_year1_deposits_cents, month_index):
    return rhu(target_year1_deposits_cents * month_index * month_index, RAMP_DIVISOR)


def ramp_attainment_bps(observed_deposits_cents, cumulative_target_cents):
    if cumulative_target_cents == 0:
        return 0
    return rhu(observed_deposits_cents * 10000, cumulative_target_cents)


def ramp_status_for(month_index, attainment_bps):
    if month_index == MONITORING_HORIZON_MONTHS and attainment_bps >= RAMP_MET_BPS:
        return "MET"
    if attainment_bps < RAMP_AT_RISK_BPS:
        return "AT_RISK"
    if attainment_bps >= RAMP_ON_TRACK_BPS:
        return "ON_TRACK"
    return "BEHIND"


def site_score(market):
    growth = min(rhu(market["household_growth_pct_bps"], SITE_GROWTH_DIVISOR_BPS), SITE_FACTOR_CAP)
    income = min(rhu(market["median_household_income_cents"], SITE_INCOME_DIVISOR_CENTS),
                 SITE_FACTOR_CAP)
    opportunity = min(
        rhu(market["deposit_market_total_cents"] * 100,
            (market["competitor_branch_count"] + 1) * SITE_DEPOSIT_TARGET_CENTS),
        SITE_FACTOR_CAP)
    competition = min(rhu(market["competitor_density_index"] * SITE_COMPETITION_MULTIPLIER),
                      SITE_FACTOR_CAP)
    inverted = 100 - competition
    return rhu(growth * SITE_W_GROWTH + income * SITE_W_INCOME
               + opportunity * SITE_W_OPPORTUNITY + inverted * SITE_W_COMPETITION, 10000)
