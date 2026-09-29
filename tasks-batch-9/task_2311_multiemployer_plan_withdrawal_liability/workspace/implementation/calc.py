"""Deterministic calculations (SCAFFOLD §1.5).

Every rounding boundary, ranking expression and tie-break below is transcribed
from the scaffold formula blocks; the evaluation order is pinned.
"""

from decimal import Decimal, ROUND_HALF_UP, getcontext

from clockutil import add_days, add_months, now
from db import db

getcontext().prec = 60

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------

VALUATION_QUIET_BUFFER_DAYS = 30

RATIO_WINDOW_YEARS = 5
PRESUMPTIVE_POOL_YEARS = 3
PRESUMPTIVE_RATIO_WINDOW_YEARS = 3
POOL_DECAY_PER_YEAR = Decimal("0.05")

DE_MINIMIS_CAP_STATUTORY_CENTS = 5000000
DE_MINIMIS_PHASEOUT_START_STATUTORY_CENTS = 10000000
DE_MINIMIS_CAP_HIGH_CENTS = 15000000
DE_MINIMIS_PHASEOUT_START_HIGH_CENTS = 15000000
DE_MINIMIS_UVB_FRACTION_BPS = 75

ANNUAL_PAYMENT_LOOKBACK_YEARS = 10
HIGH_AVERAGE_WINDOW_YEARS = 3

MAX_AMORTIZATION_YEARS_CAP = 20
MAX_AMORTIZATION_SEARCH_YEARS = 100
FIRST_DUE_OFFSET_DAYS = 60
INSTALLMENT_INTERVAL_MONTHS = 3
INSTALLMENT_GRACE_DAYS = 60

DEFAULT_ELIGIBLE_DELINQUENT_COUNT = 2
CURE_WINDOW_DAYS = 60

DECLINE_THRESHOLD = Decimal("0.30")
DECLINE_TEST_TESTING_PERIOD_YEARS = 3
DECLINE_TEST_BASE_POOL_YEARS = 5
DECLINE_TEST_BASE_YEARS_USED = 2

REVIEW_WINDOW_DAYS = 90
PLAN_RESPONSE_WINDOW_DAYS = 120
ARBITRATION_WINDOW_DAYS = 60
ARBITRATION_OUTER_WINDOW_DAYS = 180
MAX_ARBITRATION_ROUNDS = 3

BOND_PERIOD_PLAN_YEARS = 5
BOND_LOOKBACK_YEARS = 3

CONTINUITY_WEIGHT_WORKFORCE = Decimal("0.50")
CONTINUITY_WEIGHT_ASSETS = Decimal("0.30")
CONTINUITY_WEIGHT_CUSTOMERS = Decimal("0.20")
SUCCESSOR_CONTINUITY_THRESHOLD = Decimal("0.70")

CONTINGENT_EXPOSURE_WEIGHT_4204 = Decimal("0.25")

EXPOSURE_SCALE_CENTS = Decimal(100000)


# --------------------------------------------------------------------------
# rounding helpers
# --------------------------------------------------------------------------

def rhu(value, places=0):
    """round_half_up to `places` decimals; returns int when places == 0."""
    quantum = Decimal(1).scaleb(-places)
    result = Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)
    if places == 0:
        return int(result)
    return float(result)


def rhu_dec(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def dec(value):
    return Decimal(str(value))


def clamp01(value):
    if value < 0:
        return Decimal(0)
    if value > 1:
        return Decimal(1)
    return value


# --------------------------------------------------------------------------
# per_year_contribution_index
# --------------------------------------------------------------------------

def _certified_record(employer_id, year):
    for rec in db.contribution_records.values():
        if (rec["employer_id"] == employer_id
                and rec["status"] == "CERTIFIED"
                and rec["plan_year_start"] <= year <= rec["plan_year_end"]):
            return rec
    return None


def per_year_index(employer, year):
    """Returns (cbu, dollars, rate) for the employer in the given plan year."""
    rec = _certified_record(employer["id"], year)
    if rec is None:
        return 0, 0, 0
    n = rec["plan_year_end"] - rec["plan_year_start"] + 1
    bc = rec["contribution_base_units"] // n
    rc = rec["contribution_base_units"] - bc * n
    cbu = bc + (rc if year == rec["plan_year_start"] else 0)
    ba = rec["contribution_amount_cents"] // n
    ra = rec["contribution_amount_cents"] - ba * n
    dollars = ba + (ra if year == rec["plan_year_start"] else 0)
    return cbu, dollars, rec["contribution_rate_cents_per_cbu"]


def cbu_of(employer, year):
    return per_year_index(employer, year)[0]


def dollars_of(employer, year):
    return per_year_index(employer, year)[1]


def rate_of(employer, year):
    return per_year_index(employer, year)[2]


def _certified_sort_key(row):
    # certified_at DESC then created_at DESC; _seq breaks the logical-clock tie.
    certified = row.get("certified_at")
    stamp = certified.timestamp() if certified is not None else float("-inf")
    return (-stamp, -row["_seq"])


def certified_valuations(plan_id, year):
    rows = [v for v in db.valuations.values()
            if v["plan_id"] == plan_id and v["plan_year"] == year
            and v["status"] == "CERTIFIED"]
    rows.sort(key=_certified_sort_key)
    return rows


def valuation_for_year(plan_id, year):
    rows = certified_valuations(plan_id, year)
    return rows[0] if rows else None


def all_dollars(plan_id, year):
    v = valuation_for_year(plan_id, year)
    return v["all_employer_contributions_cents"] if v else 0


def all_cbu(plan_id, year):
    v = valuation_for_year(plan_id, year)
    return v["all_employer_cbu"] if v else 0


# --------------------------------------------------------------------------
# seventy_percent_decline_test
# --------------------------------------------------------------------------

def seventy_percent_decline_test(employer, W):
    pool = [W - 7, W - 6, W - 5, W - 4, W - 3]
    ordered = sorted(pool, key=lambda y: (-cbu_of(employer, y), y))
    b1, b2 = ordered[0], ordered[1]
    base_year_one = min(b1, b2)
    base_year_two = max(b1, b2)
    high = rhu_dec(Decimal(cbu_of(employer, b1) + cbu_of(employer, b2)) / 2, 4)
    testing = rhu_dec(
        Decimal(cbu_of(employer, W - 2) + cbu_of(employer, W - 1) + cbu_of(employer, W)) / 3, 4)
    if high == 0:
        ratio = Decimal("0.000000")
    else:
        ratio = rhu_dec(testing / high, 6)
    return {
        "high_base_year_average_cbu": float(high),
        "testing_period_average_cbu": float(testing),
        "decline_ratio": float(ratio),
        "base_year_one": base_year_one,
        "base_year_two": base_year_two,
        "is_decline": ratio <= DECLINE_THRESHOLD,
    }


# --------------------------------------------------------------------------
# withdrawal_type_determination
# --------------------------------------------------------------------------

def rules_variant_for(plan):
    industry = plan["industry"]
    if industry == "CONSTRUCTION":
        return "CONSTRUCTION_RULES"
    if industry == "ENTERTAINMENT":
        return "ENTERTAINMENT_RULES"
    return "GENERAL_RULES"


# --------------------------------------------------------------------------
# partial_withdrawal_fraction
# --------------------------------------------------------------------------

def partial_withdrawal_fraction(employer, event, determined_type):
    W = event["withdrawal_plan_year"]
    if determined_type == "COMPLETE":
        return 1.0
    if determined_type == "NONE":
        return 0.0
    if determined_type == "PARTIAL_70_DECLINE":
        total = sum(cbu_of(employer, W - k) for k in (5, 4, 3, 2, 1))
        avg5 = Decimal(total) / 5
        if avg5 == 0:
            return 0.0
        value = 1 - Decimal(cbu_of(employer, W)) / avg5
        return float(rhu_dec(clamp01(value), 4))
    if determined_type == "PARTIAL_CBA_CESSATION":
        return float(rhu_dec(
            Decimal(event["ceased_cba_count"]) / Decimal(employer["cba_count"]), 4))
    prior = cbu_of(employer, W - 1)
    if prior == 0:
        return 0.0
    value = 1 - Decimal(cbu_of(employer, W)) / Decimal(prior)
    return float(rhu_dec(clamp01(value), 4))


# --------------------------------------------------------------------------
# allocation_fraction_and_gross_share
# --------------------------------------------------------------------------

def allocation_gross_share(plan, employer, event, anchor, method):
    """Returns (gross_allocated_cents, pool_term_breakdown)."""
    W = event["withdrawal_plan_year"]
    f = dec(event["partial_withdrawal_fraction"])
    breakdown = []

    window = list(range(W - 5, W))  # [W-5 .. W-1]

    if method == "MODIFIED_PRESUMPTIVE":
        num = sum(dollars_of(employer, t) for t in window)
        den = sum(all_dollars(plan["id"], t) for t in window)
        basis = 0 if den == 0 else rhu(
            Decimal(anchor["uvb_total_cents"]) * Decimal(num) / Decimal(den))
    elif method == "ROLLING_5":
        num = sum(cbu_of(employer, t) for t in window)
        den = sum(all_cbu(plan["id"], t) for t in window)
        basis = 0 if den == 0 else rhu(
            Decimal(anchor["uvb_total_cents"]) * Decimal(num) / Decimal(den))
    elif method == "PRESUMPTIVE":
        basis = 0
        for y in (W - 3, W - 2, W - 1):
            valuation = valuation_for_year(plan["id"], y)
            pool = valuation["uvb_pool_cents"] if valuation else 0
            decay = Decimal(1) - POOL_DECAY_PER_YEAR * Decimal(W - 1 - y)
            if decay < 0:
                decay = Decimal(0)
            rnum = sum(dollars_of(employer, t) for t in range(y - 2, y + 1))
            rden = sum(all_dollars(plan["id"], t) for t in range(y - 2, y + 1))
            ratio = Decimal(0) if rden == 0 else Decimal(rnum) / Decimal(rden)
            term = rhu(Decimal(pool) * decay * ratio)
            breakdown.append({
                "plan_year": y,
                "decay_factor": float(decay),
                "ratio": float(rhu_dec(ratio, 10)),
                "term_cents": term,
            })
            basis += term
    else:  # DIRECT_ATTRIBUTION
        num = sum(cbu_of(employer, t) for t in window)
        den = sum(all_cbu(plan["id"], t) for t in window)
        share = 0 if den == 0 else rhu(
            Decimal(plan["unattributable_uvb_cents"]) * Decimal(num) / Decimal(den))
        basis = max(0, employer["directly_attributed_vested_benefits_cents"]
                    - employer["directly_attributed_assets_cents"] + share)

    if f == Decimal("1.0"):
        gross = basis
    else:
        gross = rhu(Decimal(basis) * f)
    return gross, breakdown


# --------------------------------------------------------------------------
# de_minimis_reduction
# --------------------------------------------------------------------------

def de_minimis_reduction(plan, anchor, variant, gross):
    uvb = anchor["uvb_total_cents"]
    if variant == "STATUTORY":
        cap = DE_MINIMIS_CAP_STATUTORY_CENTS
        phaseout = DE_MINIMIS_PHASEOUT_START_STATUTORY_CENTS
    else:
        cap = DE_MINIMIS_CAP_HIGH_CENTS
        phaseout = DE_MINIMIS_PHASEOUT_START_HIGH_CENTS
    base = min(cap, (uvb * DE_MINIMIS_UVB_FRACTION_BPS) // 10000)
    if plan["mass_withdrawal_declared"]:
        reduction = 0
    elif gross <= phaseout:
        reduction = base
    else:
        reduction = max(0, base - (gross - phaseout))
    return min(reduction, gross)


def net_assessed(gross, de_minimis, award_adjustment):
    return gross - de_minimis - award_adjustment


# --------------------------------------------------------------------------
# annual_payment_amount
# --------------------------------------------------------------------------

def annual_payment_amount(employer, W):
    best_start = None
    best_avg = None
    for s in range(W - 10, W - 2):  # [W-10 .. W-3] ascending
        avg = Decimal(cbu_of(employer, s) + cbu_of(employer, s + 1)
                      + cbu_of(employer, s + 2)) / 3
        if best_avg is None or avg > best_avg:
            best_avg = avg
            best_start = s
    high3 = rhu_dec(best_avg, 4)

    peak_rate = None
    peak_year = None
    for y in range(W - 10, W):  # [W-10 .. W-1] ascending
        r = rate_of(employer, y)
        if peak_rate is None or r > peak_rate:
            peak_rate = r
            peak_year = y

    annual = rhu(high3 * Decimal(peak_rate))
    return {
        "high_3yr_average_cbu": float(high3),
        "high_3yr_window_start_year": best_start,
        "peak_contribution_rate_cents_per_cbu": peak_rate,
        "peak_rate_plan_year": peak_year,
        "annual_payment_cents": annual,
    }


# --------------------------------------------------------------------------
# amortization_and_twenty_year_cap
# --------------------------------------------------------------------------

def _present_value(annual, i, n):
    return Decimal(annual) * (1 - (1 + i) ** Decimal(-n)) / i


def build_amortization(net_assessed_cents, annual_payment_cents, rate_bps,
                       applied_credit_cents, mass_withdrawal):
    """Returns a dict of schedule figures, or None when unamortizable."""
    i = Decimal(rate_bps) / Decimal(10000)
    annual = Decimal(annual_payment_cents)
    basis = net_assessed_cents - applied_credit_cents
    P = Decimal(basis)

    n_req = None
    if annual > 0:
        for n in range(1, MAX_AMORTIZATION_SEARCH_YEARS + 1):
            if _present_value(annual, i, n) >= P:
                n_req = n
                break

    if mass_withdrawal:
        if n_req is None:
            return None
        years = n_req
        forgiven = 0
    else:
        if n_req is not None and n_req <= MAX_AMORTIZATION_YEARS_CAP:
            years = n_req
            forgiven = 0
        else:
            years = MAX_AMORTIZATION_YEARS_CAP
            forgiven = basis - rhu(_present_value(annual, i, MAX_AMORTIZATION_YEARS_CAP))

    capped = basis - forgiven
    count = years * 4
    quarterly = capped // count if count else 0
    final = capped - quarterly * (count - 1) if count else 0
    first_due = add_days(now(), FIRST_DUE_OFFSET_DAYS)

    installments = []
    for k in range(1, count + 1):
        due = add_months(first_due, INSTALLMENT_INTERVAL_MONTHS * (k - 1))
        principal = final if k == count else quarterly
        installments.append({
            "sequence_number": k,
            "due_date": due,
            "principal_cents": principal,
            "delinquent_on": add_days(due, INSTALLMENT_GRACE_DAYS),
        })

    return {
        "interest_rate_bps": rate_bps,
        "annual_payment_cents": annual_payment_cents,
        "applied_credit_cents": applied_credit_cents,
        "amortization_basis_cents": basis,
        "forgiven_by_cap_cents": forgiven,
        "capped_basis_cents": capped,
        "amortization_years": years,
        "installment_count": count,
        "quarterly_installment_cents": quarterly,
        "final_installment_cents": final,
        "first_due_date": first_due,
        "installments": installments,
    }


# --------------------------------------------------------------------------
# arbitration_window
# --------------------------------------------------------------------------

def arbitration_deadline(review_request):
    filed_at = review_request["filed_at"]
    prd = review_request["plan_response_deadline_at"]
    status = review_request["status"]
    if status == "DECIDED":
        decided = review_request.get("decided_at") or prd
        trigger = min(decided, prd)
    elif status == "DEEMED_DENIED":
        trigger = prd
    else:
        trigger = None
    inner = None if trigger is None else add_days(trigger, ARBITRATION_WINDOW_DAYS)
    outer = add_days(filed_at, ARBITRATION_OUTER_WINDOW_DAYS)
    return outer if inner is None else min(inner, outer)


# --------------------------------------------------------------------------
# required_sale_of_assets_bond
# --------------------------------------------------------------------------

def required_sale_of_assets_bond(seller, closing_plan_year, purchase_price_cents):
    C = closing_plan_year
    total = (dollars_of(seller, C - 1) + dollars_of(seller, C - 2)
             + dollars_of(seller, C - 3))
    avg3 = rhu(Decimal(total) / 3)
    last = dollars_of(seller, C - 1)
    return min(max(avg3, last), purchase_price_cents)


# --------------------------------------------------------------------------
# substantial_continuity_score
# --------------------------------------------------------------------------

def substantial_continuity_score(txn):
    score = rhu_dec(
        CONTINUITY_WEIGHT_WORKFORCE * dec(txn["workforce_continuity_pct"])
        + CONTINUITY_WEIGHT_ASSETS * dec(txn["asset_continuity_pct"])
        + CONTINUITY_WEIGHT_CUSTOMERS * dec(txn["customer_continuity_pct"]), 4)
    liable = score >= SUCCESSOR_CONTINUITY_THRESHOLD
    return float(score), liable
