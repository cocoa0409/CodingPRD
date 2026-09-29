"""Every calculation in the contract (PRD 2.5, 3.4, 3.5, 3.6, 3.9).

Money is integer cents and proportions are integer basis points; all division
goes through Decimal so no float ever touches a money figure. Two rounding
modes only: `rdown` truncates toward zero ("rounded down") and `rhalfup`
rounds to nearest with an exact half going away from zero ("rounded half up").
"""
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from timeutil import add_years_months, day_span, parse_date

BPS_SCALE = 10000
WITHHOLDING_RATE_BPS = 2000
WITHHOLDING_TAXABLE_FLOOR_CENTS = 20000
FEE_TIER_LOW_CENTS = 2500
FEE_TIER_MID_CENTS = 5000
FEE_TIER_HIGH_CENTS = 7500
FEE_TIER_MID_FLOOR_CENTS = 100000
FEE_TIER_HIGH_FLOOR_CENTS = 1000000

_ONE = Decimal(1)


def rdown(numerator, denominator):
    """Truncate the quotient toward zero to a whole unit."""
    if denominator == 0:
        return 0
    quotient = Decimal(int(numerator)) / Decimal(int(denominator))
    return int(quotient.quantize(_ONE, rounding=ROUND_DOWN))


def rhalfup(numerator, denominator):
    """Round the quotient to the nearest whole unit, an exact half away from zero."""
    if denominator == 0:
        return 0
    quotient = Decimal(int(numerator)) / Decimal(int(denominator))
    return int(quotient.quantize(_ONE, rounding=ROUND_HALF_UP))


# --- deficiency review (PRD 3.6) --------------------------------------------

def deficiency_codes(plan, case, draft):
    codes = set()
    provisions = draft.get("provisions") or []
    if plan["requires_model_language"] and not draft["uses_model_language"]:
        codes.add("MISSING_MODEL_LANGUAGE")
    if draft["proposed_formula_code"] not in plan["acceptable_formula_codes"]:
        codes.add("FORMULA_NOT_ACCEPTABLE")
    if case["marital_period_end"] is None and draft["proposed_formula_code"] == "COVERTURE_FRACTION":
        codes.add("MARITAL_PERIOD_UNDEFINED")
    if case["alternate_payee_dob"] is None or not case["alternate_payee_address_on_file"]:
        codes.add("AP_IDENTIFICATION_INCOMPLETE")
    if "BENEFIT_NOT_OTHERWISE_AVAILABLE" in provisions \
            and not plan["permits_benefit_not_otherwise_available"]:
        codes.add("PROHIBITED_BENEFIT_NOT_AVAILABLE")
    if "REQUIRES_INCREASED_TOTAL_BENEFIT" in provisions:
        codes.add("PROHIBITED_INCREASED_BENEFIT")
    if "ASSIGNS_BENEFITS_ALREADY_ASSIGNED" in provisions:
        codes.add("PROHIBITED_ALREADY_ASSIGNED")
    if "SURVIVOR_ANNUITY_FOR_AP" in provisions or "REQUIRES_QJSA_FOR_AP_SPOUSE" in provisions:
        codes.add("PROHIBITED_FORM_NOT_OFFERED")
    return sorted(codes)


# --- assignment sizing (PRD 3.4) --------------------------------------------

def coverture_bps(case, participant):
    """Half-open marital days over days of participation, capped at 100 percent."""
    start = parse_date(case["marital_period_start"])
    # A null marital_period_end is unbounded forward, so the numerator is cut off
    # at the case's valuation date (SCAFFOLD: "valuation_date is the numerator cut-off").
    raw_end = case["marital_period_end"]
    end = parse_date(raw_end) if raw_end else parse_date(case["valuation_date"])
    marital_days = day_span(end, start)
    participation_days = day_span(parse_date(case["valuation_date"]),
                                  parse_date(participant["participation_start_date"]))
    if participation_days <= 0:
        return 0
    share = rhalfup(BPS_SCALE * marital_days, participation_days)
    return min(share, BPS_SCALE)


def gross_assigned_amount(plan, case, participant, base):
    """The raw amount under the operative formula, trimmed by both ceilings."""
    formula = case["formula_code"]
    if formula is None:
        return 0
    if formula == "PERCENTAGE_OF_ACCOUNT":
        raw = rdown(base * (case["assigned_percentage_bps"] or 0), BPS_SCALE)
    elif formula == "FLAT_DOLLAR":
        raw = case["assigned_flat_amount_cents"] or 0
    else:  # COVERTURE_FRACTION
        share = coverture_bps(case, participant)
        effective_bps = rdown(share * (case["assigned_percentage_bps"] or 0), BPS_SCALE)
        raw = rdown(base * effective_bps, BPS_SCALE)
    pct_ceiling = rdown(base * plan["max_assignable_pct_bps"], BPS_SCALE)
    amount_ceiling = plan["max_assignable_amount_cents"]
    return max(0, min(raw, pct_ceiling, amount_ceiling))


def per_source_allocation(capped, sources, base):
    """Spread `capped` over the assignable sources; the last one absorbs the residue."""
    allocations = []
    running = 0
    count = len(sources)
    for index, source in enumerate(sources):
        if index < count - 1:
            share = rhalfup(capped * source["balance_cents"], base) if base else 0
            allocations.append(share)
            running += share
        else:
            allocations.append(capped - running)
    return allocations


# --- earnings between valuation and segregation (PRD 3.5) --------------------

def period_growth_bps(baseline, endpoint):
    if baseline["balance_cents"] == 0:
        return 0
    delta = endpoint["balance_cents"] - baseline["balance_cents"]
    return rhalfup(BPS_SCALE * delta, baseline["balance_cents"])


def credited_growth_bps(plan, baseline, endpoint, segregation_date):
    """PERIOD_END credits the whole move; PRO_RATA_DAILY only the elapsed fraction."""
    period = period_growth_bps(baseline, endpoint)
    if plan["earnings_adjustment_method"] == "PERIOD_END":
        return period
    span_days = day_span(parse_date(endpoint["as_of_date"]), parse_date(baseline["as_of_date"]))
    elapsed_days = day_span(segregation_date, parse_date(baseline["as_of_date"]))
    if span_days <= 0:
        return 0
    return rhalfup(period * elapsed_days, span_days)


def per_source_earnings(allocations, growth_bps):
    """Round EACH source's earnings and only then sum (the pinned order)."""
    return [rhalfup(share * growth_bps, BPS_SCALE) for share in allocations]


def per_source_basis(sources, allocations):
    """Each source's own contribution to the carryover, rounded down (PRD 3.5)."""
    out = []
    for index, source in enumerate(sources):
        if source["balance_cents"] == 0:
            out.append(0)
            continue
        out.append(rdown(source["basis_cents"] * allocations[index],
                         source["balance_cents"]))
    return out


def basis_carryover(sources, allocations):
    """After-tax basis follows the principal, rounded down per source."""
    return sum(per_source_basis(sources, allocations))


def shared_payment_per_period(plan_account, case):
    return rdown((plan_account["monthly_payment_cents"] or 0)
                 * (case["assigned_percentage_bps"] or 0), BPS_SCALE)


# --- distribution settlement (PRD 3.9) --------------------------------------

def settle_distribution(election, gross, basis_pool, balance_pool, payee_dob, today):
    """The seven pinned settlement steps."""
    if balance_pool == 0:
        basis_recovery = 0
    else:
        basis_recovery = rdown(basis_pool * gross, balance_pool)
    basis_recovery = min(basis_recovery, basis_pool)
    taxable = gross - basis_recovery
    if election == "DIRECT_ROLLOVER":
        withheld = 0
    elif taxable >= WITHHOLDING_TAXABLE_FLOOR_CENTS:
        withheld = rhalfup(taxable * WITHHOLDING_RATE_BPS, BPS_SCALE)
    else:
        withheld = 0
    net_before_fee = gross - withheld
    if net_before_fee < FEE_TIER_MID_FLOOR_CENTS:
        admin_fee = FEE_TIER_LOW_CENTS
    elif net_before_fee < FEE_TIER_HIGH_FLOOR_CENTS:
        admin_fee = FEE_TIER_MID_CENTS
    else:
        admin_fee = FEE_TIER_HIGH_CENTS
    net_amount = net_before_fee - admin_fee
    if election == "DIRECT_ROLLOVER":
        code = "CODE_G"
    else:
        code = _cash_distribution_code(payee_dob, today)
    return {
        "basis_recovery_cents": basis_recovery,
        "taxable_amount_cents": taxable,
        "federal_withheld_cents": withheld,
        "net_before_fee_cents": net_before_fee,
        "admin_fee_cents": admin_fee,
        "net_amount_cents": net_amount,
        "distribution_code": code,
        "tax_year": today.year,
    }


def _cash_distribution_code(payee_dob, today):
    """CODE_2 strictly before the payee's fifty-nine-and-a-half birthday, else CODE_7."""
    if not payee_dob:
        return "CODE_7"
    born = parse_date(payee_dob)
    if born is None:
        return "CODE_7"
    threshold = add_years_months(born, 59, 6)
    return "CODE_2" if today < threshold else "CODE_7"
