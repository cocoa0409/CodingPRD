"""Every derived quantity in the system (PRD sections 2.5, 2.8, 2.9 and 3).

There is exactly one rounding convention: half up, away from zero, applied to
exact integer arithmetic.  No float ever touches money.
"""
import datetime
from decimal import Decimal, ROUND_HALF_UP

import store

# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------


def rhu_div(numerator, denominator):
    """Exact integer division rounded half up (away from zero on a tie)."""
    numerator = int(numerator)
    denominator = int(denominator)
    if denominator == 0:
        raise ZeroDivisionError("rhu_div by zero")
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    return -((-2 * numerator + denominator) // (2 * denominator))


def rhu_decimal(value):
    """Half-up rounding of a Decimal to a whole unit (used for symmetry)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def apply_bps(amount, bps):
    """amount * bps / 10000, rounded half up."""
    return rhu_div(int(amount) * int(bps), 10000)


# ---------------------------------------------------------------------------
# Date helpers (all comparisons read the logical clock)
# ---------------------------------------------------------------------------


def parse_date(text):
    return datetime.datetime.strptime(text, "%Y-%m-%d").date()


def date_or_none(text):
    if not text:
        return None
    try:
        return parse_date(text)
    except Exception:
        return None


def inclusive_days(start_text, end_text):
    start = parse_date(start_text)
    end = parse_date(end_text)
    return (end - start).days + 1


def day_span(start_text, end_text):
    start = parse_date(start_text)
    end = parse_date(end_text)
    return (end - start).days


# ---------------------------------------------------------------------------
# C1 — scope benchmark total (round per line, then sum)
# ---------------------------------------------------------------------------


def line_benchmark(line, cost_index_bps):
    unit = int(line["benchmark_unit_cost_cents"])
    qty = int(line["quantity"])
    return rhu_div(unit * qty * int(cost_index_bps), 10000)


def scope_benchmark_total(lines, cost_index_bps):
    return sum(line_benchmark(line, cost_index_bps) for line in lines)


def index_the_sum_total(lines, cost_index_bps):
    """The deliberately wrong variant, reported for comparison only."""
    raw = sum(int(l["benchmark_unit_cost_cents"]) * int(l["quantity"]) for l in lines)
    return rhu_div(raw * int(cost_index_bps), 10000)


# ---------------------------------------------------------------------------
# C2 — yield on cost (ten ordered steps; two variants)
# ---------------------------------------------------------------------------


def yield_on_cost(market, home, purchase_price_cents, closing_costs_cents,
                  renovation_cents, monthly_rent_cents, turn_reserve_annual_cents):
    """The ten ordered steps of PRD 3.2, shared by both variants."""
    basis = int(purchase_price_cents) + int(closing_costs_cents) + int(renovation_cents)
    gpr = int(monthly_rent_cents) * 12
    vacancy = apply_bps(gpr, market["vacancy_loss_bps"])
    bad_debt = apply_bps(gpr, market["bad_debt_bps"])
    egi = gpr - vacancy - bad_debt
    mgmt = apply_bps(egi, market["mgmt_fee_bps"])
    tax = apply_bps(home["assessed_value_cents"], market["millage_bps"])
    opex = (mgmt + tax + int(home["insurance_annual_premium_cents"])
            + int(home["hoa_annual_cents"]) + int(turn_reserve_annual_cents))
    noi = egi - opex
    yield_bps = rhu_div(noi * 10000, basis) if basis else 0
    return {
        "all_in_basis_cents": basis,
        "gross_potential_rent_cents": gpr,
        "vacancy_loss_cents": vacancy,
        "bad_debt_loss_cents": bad_debt,
        "effective_gross_income_cents": egi,
        "management_fee_cents": mgmt,
        "property_tax_cents": tax,
        "operating_expense_cents": opex,
        "net_operating_income_cents": noi,
        "yield_on_cost_bps": yield_bps,
    }


def property_tax_annual(assessed_value_cents, millage_bps):
    return apply_bps(assessed_value_cents, millage_bps)


# ---------------------------------------------------------------------------
# C3 — prospect fraud risk score (two variants)
# ---------------------------------------------------------------------------

WEIGHT_IDENTITY = 3500
WEIGHT_INCOME = 3000
WEIGHT_HISTORY = 2000
WEIGHT_DEVICE = 1500

CREDIT_BASE = {"A": 500, "B": 1500, "C": 3000, "D": 5000}


def _clamp_bps(value):
    return max(0, min(10000, int(value)))


def income_factor(monthly_income_cents, rent_index_cents):
    denominator = int(rent_index_cents) * 3
    if denominator <= 0:
        return 10000
    ratio = rhu_div(int(monthly_income_cents) * 10000, denominator)
    return max(0, 10000 - ratio)


def history_factor(credit_tier, eviction_count):
    base = CREDIT_BASE.get(credit_tier, 5000)
    return min(10000, base + int(eviction_count) * 2500)


def fraud_score(prospect, market):
    """Pre-verification when attempt_count == 0, post-verification otherwise."""
    pre = int(prospect.get("verification_attempt_count", 0)) == 0
    if pre:
        identity = 10000
        income = income_factor(prospect["declared_monthly_income_cents"],
                               market["rent_index_cents"])
        device = 7000
    else:
        if prospect.get("selfie_liveness_pass"):
            identity = max(0, 10000 - int(prospect.get("document_match_score_bps", 0)))
        else:
            identity = 10000
        income = income_factor(prospect.get("verified_monthly_income_cents", 0),
                               market["rent_index_cents"])
        device = max(0, 10000 - int(prospect.get("device_reputation_bps", 0)))
        if int(prospect.get("ip_geo_distance_km", 0)) > 100:
            device += 2000
        device = min(10000, device)
    history = history_factor(prospect.get("credit_tier"),
                            prospect.get("prior_eviction_count", 0))
    identity = _clamp_bps(identity)
    income = _clamp_bps(income)
    history = _clamp_bps(history)
    device = _clamp_bps(device)
    weighted = (identity * WEIGHT_IDENTITY + income * WEIGHT_INCOME
                + history * WEIGHT_HISTORY + device * WEIGHT_DEVICE)
    return rhu_div(weighted, 10000)


def identity_verified(liveness_pass, document_match_score_bps):
    return bool(liveness_pass) and int(document_match_score_bps) >= 5000


# ---------------------------------------------------------------------------
# C4 — home leasing posture (first matching clause, 1..6)
# ---------------------------------------------------------------------------

FROZEN_ASSET_STATUSES = {"PASSED", "RENOVATING", "DISPOSED"}
RESTRICTED_ASSET_STATUSES = {"PIPELINE", "ACQUIRED"}
BLOCKING_OBLIGATION_STATUSES = {"OPEN", "PLANNED", "RESOLUTION_SUBMITTED", "RESOLUTION_REJECTED"}


def home_obligations(home_id):
    return [o for o in store.all_rows("compliance_obligations") if o["home_id"] == home_id]


def blocking_obligation_ids(home_id, severity):
    return [o["id"] for o in home_obligations(home_id)
            if o["severity"] == severity and o["status"] in BLOCKING_OBLIGATION_STATUSES]


def binder_expired(home):
    binder = date_or_none(home.get("insurance_binder_expires_on"))
    if binder is None:
        return False
    return binder < store.clock_date()


def leasing_posture_detail(home):
    """Returns (posture, deciding_clause, blocking_obligation_ids, binder_expired)."""
    expired = binder_expired(home)
    if home["asset_status"] in FROZEN_ASSET_STATUSES:
        return "FROZEN", 1, [], expired
    if expired:
        return "FROZEN", 2, [], expired
    critical = blocking_obligation_ids(home["id"], "CRITICAL")
    if critical:
        return "FROZEN", 3, critical, expired
    major = blocking_obligation_ids(home["id"], "MAJOR")
    if major:
        return "RESTRICTED", 4, major, expired
    if home["asset_status"] in RESTRICTED_ASSET_STATUSES:
        return "RESTRICTED", 5, [], expired
    return "OPEN", 6, [], expired


def leasing_posture(home):
    return leasing_posture_detail(home)[0]


# ---------------------------------------------------------------------------
# C5 — screening decision (five ordered clauses)
# ---------------------------------------------------------------------------

CONDITIONAL_MULTIPLIER = {"A": 15000, "B": 15000, "C": 20000, "D": 25000}


def rent_to_income_bps(asking_rent_cents, verified_monthly_income_cents):
    income = int(verified_monthly_income_cents)
    if income <= 0:
        return 1000000000
    return rhu_div(int(asking_rent_cents) * 10000, income)


def screening_decision(market, prospect, asking_rent_cents):
    """First matching clause of five (PRD 3.8)."""
    rti = rent_to_income_bps(asking_rent_cents, prospect.get("verified_monthly_income_cents", 0))
    score = int(prospect.get("fraud_risk_score_bps", 0))
    evictions = int(prospect.get("prior_eviction_count", 0))
    tier = prospect.get("credit_tier")
    if score > int(market["fraud_block_threshold_bps"]):
        return {"status": "DENIED", "adverse_action_reason": "FRAUD_RISK",
                "rent_to_income_bps": rti, "risk_multiplier_bps": 0}
    if evictions >= 2:
        return {"status": "DENIED", "adverse_action_reason": "EVICTION_HISTORY",
                "rent_to_income_bps": rti, "risk_multiplier_bps": 0}
    if rti > int(market["rent_to_income_max_bps"]):
        return {"status": "DENIED", "adverse_action_reason": "RENT_TO_INCOME",
                "rent_to_income_bps": rti, "risk_multiplier_bps": 0}
    if tier == "A" and evictions == 0 and rti <= 3000:
        return {"status": "APPROVED", "adverse_action_reason": "NONE",
                "rent_to_income_bps": rti, "risk_multiplier_bps": 10000}
    return {"status": "CONDITIONAL_APPROVED", "adverse_action_reason": "NONE",
            "rent_to_income_bps": rti,
            "risk_multiplier_bps": CONDITIONAL_MULTIPLIER.get(tier, 25000)}


def deposit_amounts(market, prospect, asking_rent_cents, multiplier_bps):
    security = apply_bps(asking_rent_cents, multiplier_bps)
    pets = int(prospect.get("pet_count", 0))
    pet_deposit = min(pets * int(market["pet_deposit_per_pet_cents"]),
                      int(market["pet_deposit_cap_cents"]))
    return security, pet_deposit, security + pet_deposit


# ---------------------------------------------------------------------------
# C6 — turn holdback settlement (eight ordered steps)
# ---------------------------------------------------------------------------


def holdback_rate_for(overage_days):
    if overage_days <= 0:
        return 0
    if overage_days <= 3:
        return 1000
    if overage_days <= 7:
        return 2000
    return 3000


def turn_holdback(market, project, gross_turn_cost_cents):
    turn_days = day_span(project["turn_started_on"], project["rent_ready_on"])
    overage = max(0, turn_days - int(market["make_ready_target_days"]))
    rate = holdback_rate_for(overage)
    raw = apply_bps(gross_turn_cost_cents, rate)
    cap = apply_bps(gross_turn_cost_cents, market["turn_holdback_cap_bps"])
    holdback = min(raw, cap)
    return {
        "gross_turn_cost_cents": int(gross_turn_cost_cents),
        "turn_days": turn_days,
        "overage_days": overage,
        "holdback_rate_bps": rate,
        "vendor_holdback_cents": holdback,
        "net_turn_cost_cents": int(gross_turn_cost_cents) - holdback,
    }


# ---------------------------------------------------------------------------
# C7 — tax appeal savings
# ---------------------------------------------------------------------------


def tax_appeal_savings(assessed_value_cents, settled_value_cents, millage_bps,
                       consultant_fee_bps):
    reduction = int(assessed_value_cents) - int(settled_value_cents)
    savings = apply_bps(reduction, millage_bps)
    fee = apply_bps(savings, consultant_fee_bps)
    return {
        "annual_tax_savings_cents": savings,
        "consultant_fee_cents": fee,
        "net_tax_benefit_cents": savings - fee,
    }


# ---------------------------------------------------------------------------
# C9 — work order crew days
# ---------------------------------------------------------------------------


def crew_days(crew_size, start_date, end_date):
    return int(crew_size) * inclusive_days(start_date, end_date)


# ---------------------------------------------------------------------------
# C8 — vendor dispatch eligibility and selection
# ---------------------------------------------------------------------------

CAPACITY_STATUSES = {"DISPATCHED", "ACCEPTED"}


def vendor_certified(vendor_id, certification_code):
    today = store.clock_date()
    for cert in store.all_rows("vendor_certifications"):
        if cert["vendor_id"] != vendor_id or cert["status"] != "ACTIVE":
            continue
        if cert["certification_code"] != certification_code:
            continue
        effective = date_or_none(cert["effective_on"])
        expires = date_or_none(cert["expires_on"])
        if effective is not None and effective > today:
            continue
        if expires is not None and expires < today:
            continue
        return True
    return False


def capacity_available(vendor, work_order):
    """Per-date capacity test across the closed-inclusive work window."""
    start = parse_date(work_order["scheduled_start_date"])
    end = parse_date(work_order["scheduled_end_date"])
    others = [w for w in store.all_rows("work_orders")
              if w["vendor_id"] == vendor["id"] and w["status"] in CAPACITY_STATUSES
              and w["id"] != work_order["id"]]
    capacity = int(vendor["daily_crew_capacity"])
    day = start
    while day <= end:
        used = 0
        for other in others:
            o_start = parse_date(other["scheduled_start_date"])
            o_end = parse_date(other["scheduled_end_date"])
            if o_start <= day <= o_end:
                used += int(other["crew_size"])
        if used + int(work_order["crew_size"]) > capacity:
            return False
        day += datetime.timedelta(days=1)
    return True


def vendor_exclusion_reason(vendor, work_order, certification_code):
    """First failed eligibility clause, in the declared clause order."""
    if vendor["status"] != "ACTIVE":
        return "ERR_VENDOR_INACTIVE"
    expires = date_or_none(vendor["insurance_expires_on"])
    if expires is None or expires < store.clock_date():
        return "ERR_VENDOR_INSURANCE_EXPIRED"
    if not vendor_certified(vendor["id"], certification_code):
        return "ERR_VENDOR_NOT_CERTIFIED"
    if not capacity_available(vendor, work_order):
        return "ERR_VENDOR_CAPACITY_EXCEEDED"
    return None


def vendor_bid(work_order, vendor):
    return apply_bps(work_order["benchmark_total_cents"], vendor["cost_index_bps"])


def vendor_ranking(work_order, home, certification_code):
    """Eligible vendors ranked bid ASC, quality DESC, created_at ASC."""
    candidates = [v for v in store.all_rows("vendors") if v["market_id"] == home["market_id"]]
    eligible = []
    excluded = []
    reasons = []
    for vendor in candidates:
        reason = vendor_exclusion_reason(vendor, work_order, certification_code)
        if reason is None:
            eligible.append(vendor)
        else:
            excluded.append(vendor["id"])
            reasons.append(reason)
    ranked = sorted(
        eligible,
        key=lambda v: (vendor_bid(work_order, v), -int(v["quality_score_bps"]),
                       v["created_at"], v["_seq"]),
    )
    return {
        "work_order_id": work_order["id"],
        "eligible_vendor_ids": [v["id"] for v in ranked],
        "bid_cents": [vendor_bid(work_order, v) for v in ranked],
        "excluded_vendor_ids": excluded,
        "exclusion_reasons": reasons,
        "winning_vendor_id": ranked[0]["id"] if ranked else "",
    }
