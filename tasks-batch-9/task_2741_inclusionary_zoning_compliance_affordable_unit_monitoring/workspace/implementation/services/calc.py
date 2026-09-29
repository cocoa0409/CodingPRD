"""The twenty-one calculation rules (PRD section 3, scaffold `calculations`).

Every monetary figure is an integer number of cents; every rate is an integer
number of basis points where 10000 bps is one whole unit / one hundred percent.
Rounding is always half-up (away from zero) unless the PRD names truncation.
"""

from decimal import Decimal, ROUND_HALF_UP

import db
from errors import ApiError

BPS = 10000

AFFORDABILITY_LEVELS = (5000, 8000, 12000)
RENT_BURDEN_BPS = 3000            # 30 percent of monthly income
IMPROVEMENT_CREDIT_CAP_BPS = 1000  # 10 percent of the original purchase price
COMPARABILITY_FLOOR_BPS = 8000     # 80 percent of the market comparable
FAMILY_UNIT_SHARE_BPS = 5000       # half of the required affordable units
BEDROOM_UNIT_BPS = 10000
INCOME_RECERT_TOLERANCE_BPS = 14000  # 140 percent of the initial limit
PREFERENCE_POINTS = 100
CERT_TERM_DAYS = 365
RECERT_WINDOW_DAYS = 30
BASE_CURE_DAYS = 30
CURE_EXTENSION_DAYS = 15
CURE_EXTENSION_THRESHOLD_CENTS = 100000
OVERCHARGE_MULTIPLE = 3
FLAT_PENALTY_CENTS = 25000
PENALTY_MONTH_DAYS = 30
ROFR_WINDOW_DAYS = 30
ADMIN_USE_CAP_BPS = 1000           # 10 percent of total inflow


def round_half_up(numerator, denominator=1):
    """Half-up rounding to a whole integer, away from zero on an exact half."""
    value = Decimal(numerator) / Decimal(denominator)
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# 1. ordinance_vintage_selection
# --------------------------------------------------------------------------
def select_ordinance(approval_date):
    """Newest ordinance whose effective_date is on or before approval_date.
    Status is deliberately ignored: a SUPERSEDED ordinance still governs the
    projects that were approved during its vintage."""
    target = db.parse_date_loose(approval_date)
    if target is None:
        raise ApiError("ERR_NO_GOVERNING_ORDINANCE")
    candidates = []
    for row in db.all_rows(db.ordinances):
        effective = db.parse_date_loose(row.get("effective_date"))
        if effective is not None and effective <= target:
            candidates.append(row)
    if not candidates:
        raise ApiError("ERR_NO_GOVERNING_ORDINANCE")
    candidates.sort(key=lambda r: (
        db.parse_date_loose(r["effective_date"]).toordinal() * -1,
        r.get("created_at") or "",
        r.get("_seq") or 0,
    ))
    return candidates[0]


# --------------------------------------------------------------------------
# 2. ami_schedule_selection
# --------------------------------------------------------------------------
def select_ami_schedule():
    """Highest effective_year wins, earliest created_at breaks a tie.
    Status is ignored, exactly like ordinance vintage selection."""
    rows = db.all_rows(db.ami_schedules)
    if not rows:
        raise ApiError("ERR_NO_AMI_SCHEDULE")
    rows.sort(key=lambda r: (
        -int(r.get("effective_year") or 0),
        r.get("created_at") or "",
        r.get("_seq") or 0,
    ))
    return rows[0]


def active_ami_or_none():
    try:
        return select_ami_schedule()
    except ApiError:
        return None


# --------------------------------------------------------------------------
# 3. required_units_and_fraction
# --------------------------------------------------------------------------
def required_units_and_fraction(project, ordinance):
    """Returns (applicability, required_units, fractional_bps, total_obligation_bps)."""
    set_aside = (ordinance.get("set_aside_bps_by_district") or {}).get(
        project.get("zoning_district"))
    threshold = int(ordinance.get("min_project_units_threshold") or 0)
    total_units = int(project.get("total_units") or 0)
    if set_aside is None or total_units < threshold:
        return ("EXEMPT", 0, 0, 0)
    raw_bps = total_units * int(set_aside)
    whole = raw_bps // BPS
    fraction = raw_bps - whole * BPS
    if fraction >= 5000:
        required = whole + 1
        fractional = 0
    else:
        required = whole
        fractional = fraction
    total_obligation = required * BPS + fractional
    return ("SUBJECT", required, fractional, total_obligation)


# --------------------------------------------------------------------------
# 4. in_lieu_fee_assessment
# --------------------------------------------------------------------------
def in_lieu_fee_assessment(project, ordinance, basis):
    if basis == "FULL":
        unit_equivalent = (int(project.get("total_obligation_bps") or 0)
                           - int(project.get("onsite_unit_equivalents_bps") or 0)
                           - int(project.get("fee_covered_equivalents_bps") or 0))
    elif basis == "FRACTIONAL":
        unit_equivalent = int(project.get("fractional_obligation_bps") or 0)
    else:  # SUBSTITUTION -- exactly one whole unit equivalent
        unit_equivalent = BPS
    if unit_equivalent <= 0:
        raise ApiError("ERR_NO_REMAINING_OBLIGATION")

    gap_map = ordinance.get("gap_basis_cents_by_level") or {}
    level_key = str(int(ordinance.get("fee_gap_level_bps")))
    if level_key not in gap_map:
        raise ApiError("ERR_NO_GOVERNING_ORDINANCE")
    gap = int(gap_map[level_key])

    base_amount = round_half_up(unit_equivalent * gap, BPS)
    surcharge_raw = round_half_up(base_amount * int(ordinance.get("surcharge_bps") or 0), BPS)
    surcharge = min(int(ordinance.get("surcharge_cap_cents") or 0), surcharge_raw)
    pre_discount_total = base_amount + surcharge

    discount_bps_applied = 0
    for tier in (ordinance.get("discount_tiers") or []):
        if int(tier.get("min_pre_discount_cents") or 0) <= pre_discount_total:
            discount_bps_applied = int(tier.get("discount_bps") or 0)
        else:
            break
    discount = round_half_up(pre_discount_total * discount_bps_applied, BPS)
    assessed = pre_discount_total - discount

    due_days = int(ordinance.get("fee_due_days") or 0)
    due_date = (db.logical_now().date() + _days(due_days)).isoformat()

    return {
        "unit_equivalent_bps": unit_equivalent,
        "base_amount_cents": base_amount,
        "surcharge_cents": surcharge,
        "pre_discount_total_cents": pre_discount_total,
        "discount_bps_applied": discount_bps_applied,
        "discount_cents": discount,
        "assessed_amount_cents": assessed,
        "due_date": due_date,
    }


def _days(n):
    from datetime import timedelta
    return timedelta(days=n)


# --------------------------------------------------------------------------
# 5. income_limit
# --------------------------------------------------------------------------
def income_limit(ami, household_size, level_bps):
    medians = ami.get("median_income_cents_by_size") or {}
    key = str(int(household_size))
    if key not in medians:
        raise ApiError("ERR_NO_AMI_SCHEDULE")
    median = int(medians[key])
    # median * level / 10000, then published to the whole dollar:
    # divide by 100, round half up, multiply by 100 again.
    return round_half_up(median * int(level_bps), BPS * 100) * 100


# --------------------------------------------------------------------------
# 6. max_allowed_rent -- four pinned steps, never algebraically collapsed
# --------------------------------------------------------------------------
def max_allowed_rent(ami, bedrooms, level_bps):
    household_size = int(bedrooms) + 1
    annual_limit = income_limit(ami, household_size, level_bps)
    monthly_income = annual_limit // 12                      # truncated
    gross_rent = round_half_up(monthly_income * RENT_BURDEN_BPS, BPS)
    allowances = ami.get("utility_allowance_cents_by_bedrooms") or {}
    key = str(int(bedrooms))
    if key not in allowances:
        raise ApiError("ERR_NO_AMI_SCHEDULE")
    allowance = int(allowances[key])
    return max(0, gross_rent - allowance)


def ami_pct_bps(ami, household_size, certified_income_cents):
    medians = ami.get("median_income_cents_by_size") or {}
    key = str(int(household_size))
    if key not in medians:
        raise ApiError("ERR_NO_AMI_SCHEDULE")
    median = int(medians[key])
    if median == 0:
        return 0
    return round_half_up(int(certified_income_cents) * BPS, median)


# --------------------------------------------------------------------------
# 7. unit_mix_compliance
# --------------------------------------------------------------------------
def check_comparability(sqft, market_comparable_sqft):
    minimum = round_half_up(int(market_comparable_sqft) * COMPARABILITY_FLOOR_BPS, BPS)
    if int(sqft) < minimum:
        raise ApiError("ERR_COMPARABILITY_STANDARD_FAILED")


def check_bedroom_distribution(project, project_units):
    family_units = sum(
        1 for unit in project_units
        if unit.get("occupancy_status") != "WITHDRAWN" and int(unit.get("bedrooms") or 0) >= 2
    )
    required = int(project.get("required_affordable_units") or 0)
    if family_units * BEDROOM_UNIT_BPS < required * FAMILY_UNIT_SHARE_BPS:
        raise ApiError("ERR_BEDROOM_DISTRIBUTION_FAILED")


# --------------------------------------------------------------------------
# 8. lottery_ranking
# --------------------------------------------------------------------------
def eligible_pool(event, plan, ami):
    pool = []
    for household in db.all_rows(db.households):
        if household.get("lottery_event_id") != event["id"]:
            continue
        if household.get("state") not in ("APPLIED", "SELECTED", "WAITLISTED"):
            continue
        limit = income_limit(ami, household.get("household_size"),
                             event.get("eligibility_level_bps"))
        if int(household.get("gross_annual_income_cents") or 0) <= limit:
            pool.append(household)
    return pool


def preference_score(claims, categories):
    claim_set = set(claims or [])
    category_set = set(categories or [])
    return PREFERENCE_POINTS * len(claim_set & category_set)


def rank_pool(pool, plan):
    scored = []
    for household in pool:
        score = preference_score(household.get("preference_claims"),
                                 plan.get("preference_categories"))
        scored.append((score, household))
    scored.sort(key=lambda pair: (
        -pair[0],
        pair[1].get("created_at") or "",
        pair[1].get("_seq") or 0,
    ))
    return scored


# --------------------------------------------------------------------------
# 9. max_resale_price
# --------------------------------------------------------------------------
def improvement_credit(original_purchase_price_cents, capital_improvements_cents):
    cap = round_half_up(int(original_purchase_price_cents) * IMPROVEMENT_CREDIT_CAP_BPS, BPS)
    return min(int(capital_improvements_cents), cap)


def max_resale_price(unit, agreement, ami, appraised_value_cents,
                     capital_improvements_cents, deferred_maintenance_cents):
    original = int(unit.get("original_purchase_price_cents") or 0)
    credit = improvement_credit(original, capital_improvements_cents)
    formula = agreement.get("resale_formula")
    if formula == "SHARED_APPRECIATION":
        appreciation = max(0, int(appraised_value_cents) - original)
        share = int(agreement.get("owner_appreciation_share_bps") or 0)
        indexed_base = original + round_half_up(appreciation * share, BPS)
    else:  # AMI_INDEXED
        current_median = current_median_for_unit(unit, ami)
        anchor = int(unit.get("ami_income_at_purchase_cents") or 0)
        if anchor <= 0:
            indexed_base = original
        else:
            indexed_base = round_half_up(original * current_median, anchor)
    return {
        "resale_formula_applied": formula,
        "improvement_credit_cents": credit,
        "indexed_base_cents": indexed_base,
        "max_resale_price_cents": indexed_base + credit - int(deferred_maintenance_cents),
    }


def current_median_for_unit(unit, ami):
    medians = ami.get("median_income_cents_by_size") or {}
    key = str(int(unit.get("bedrooms") or 0) + 1)
    if key not in medians:
        raise ApiError("ERR_NO_AMI_SCHEDULE")
    return int(medians[key])


# --------------------------------------------------------------------------
# 10. resale_proceeds_waterfall
# --------------------------------------------------------------------------
def resale_waterfall(txn, agreement, via_rofr_exercise):
    net = int(txn.get("proposed_price_cents") or 0) - int(txn.get("broker_fee_cents") or 0)
    remaining = net

    seller_equity = min(remaining, int(txn.get("_original_purchase_price_cents") or 0))
    remaining -= seller_equity

    seller_credit = min(remaining, int(txn.get("improvement_credit_cents") or 0))
    remaining -= seller_credit

    if via_rofr_exercise:
        appreciation_share = remaining
        recapture = 0
    else:
        share_bps = int(agreement.get("owner_appreciation_share_bps") or 0)
        appreciation_share = round_half_up(remaining * share_bps, BPS)
        recapture = remaining - appreciation_share

    return {
        "net_proceeds_cents": net,
        "seller_equity_cents": seller_equity,
        "seller_improvement_credit_cents": seller_credit,
        "seller_appreciation_share_cents": appreciation_share,
        "city_recapture_cents": recapture,
    }


# --------------------------------------------------------------------------
# 11. cure_penalty_and_deadline
# --------------------------------------------------------------------------
def overcharge_monthly(reported_rent_cents, max_allowed_rent_cents):
    return max(0, int(reported_rent_cents) - int(max_allowed_rent_cents))


def penalty_at_base(overcharge_cents):
    return int(overcharge_cents) * OVERCHARGE_MULTIPLE + FLAT_PENALTY_CENTS * 1


def cure_extension_for(penalty_base_cents):
    return CURE_EXTENSION_DAYS if int(penalty_base_cents) >= CURE_EXTENSION_THRESHOLD_CENTS else 0


def cure_deadline(finding_issued_at, extension_days):
    issued = db.parse_dt(finding_issued_at)
    if issued is None:
        return None
    return db.fmt_dt(issued + _days(BASE_CURE_DAYS + int(extension_days)))


def penalty_final(overcharge_cents, finding_issued_at, cure_submitted_at):
    issued = db.parse_dt(finding_issued_at)
    submitted = db.parse_dt(cure_submitted_at)
    if issued is None or submitted is None:
        elapsed_days = 0
    else:
        elapsed_days = (submitted - issued).days
    if elapsed_days < 0:
        elapsed_days = 0
    months = -(-elapsed_days // PENALTY_MONTH_DAYS)
    months = max(1, months)
    return int(overcharge_cents) * OVERCHARGE_MULTIPLE + FLAT_PENALTY_CENTS * months


# --------------------------------------------------------------------------
# 12. monitoring_findings -- fixed evaluation order
# --------------------------------------------------------------------------
def monitoring_findings(unit, review_inputs, occupant, ami):
    findings = []
    reported_rent = int(review_inputs.get("reported_rent_cents") or 0)
    reported_income = int(review_inputs.get("reported_income_cents") or 0)

    if unit.get("tenure") == "RENTAL" and reported_rent > int(unit.get("max_allowed_rent_cents") or 0):
        findings.append("RENT_OVERCHARGE")

    if occupant is not None and ami is not None:
        base_limit = income_limit(ami, occupant.get("household_size"),
                                 unit.get("affordability_level_bps"))
        ceiling = round_half_up(base_limit * INCOME_RECERT_TOLERANCE_BPS, BPS)
        if reported_income > ceiling:
            findings.append("INCOME_OVER_LIMIT")

    if review_inputs.get("occupancy_verified") is False:
        findings.append("OCCUPANCY_UNVERIFIED")

    return findings


# --------------------------------------------------------------------------
# 13. refinance_capacity
# --------------------------------------------------------------------------
def refinance_cap(unit, agreement, ami):
    current_median = current_median_for_unit(unit, ami)
    original = int(unit.get("original_purchase_price_cents") or 0)
    anchor = int(unit.get("ami_income_at_purchase_cents") or 0)
    if anchor <= 0:
        restricted_value = original
    else:
        restricted_value = round_half_up(original * current_median, anchor)
    ltv = int(agreement.get("max_refinance_ltv_bps") or 0)
    return round_half_up(restricted_value * ltv, BPS)


# --------------------------------------------------------------------------
# 21. certification_period_overlap / marketing_window_overlap / rofr_window
# --------------------------------------------------------------------------
def certification_expiry(effective_date, tenure):
    if tenure == "OWNERSHIP":
        return None
    return db.add_days_date(effective_date, CERT_TERM_DAYS)


def periods_collide(new_start, new_end, existing_start, existing_end):
    """Closed intervals: touching endpoints collide."""
    return new_start <= existing_end and existing_start <= new_end


def windows_overlap(new_open, new_close, existing_open, existing_close):
    """Half-open intervals: exact adjacency is accepted."""
    return new_open < existing_close and existing_open < new_close
