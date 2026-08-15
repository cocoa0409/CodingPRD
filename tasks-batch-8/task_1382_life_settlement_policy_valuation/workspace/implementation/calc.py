"""Calculation rules (PRD §3). Money is integer cents; LE is integer months."""

from datetime import date, datetime, time, timezone
from decimal import Decimal

from db import store
from util import add_months, days_between, rhu, rhu_div

# --- calc_eligibility_screening constants ---
MIN_FACE_CENTS = 10000000
MIN_AGE_YEARS = 65
CONTESTABILITY_MONTHS = 24

# --- calc_le_adjust_blend constants ---
TIER_WEIGHT = {"A": 3, "B": 1}

# --- calc_reserve_price constants ---
PRICING_RATE_BPS = 1300
EXPENSE_FLAT_CENTS = 250000
EXPENSE_FACE_BPS = 150
PRICE_CAP_FACE_BPS = 8000

# --- calc_escrow_waterfall constants ---
ESCROW_FEE_CENTS = 75000
SERVICING_FEE_BPS = 25
COMMISSION_CAP_FACE_BPS = 600

# --- calc_premium_optimization constants ---
CREDITING_MONTHLY = 0.0033333333333333335
COI_MONTHLY_RATE = 0.006
MF_BISECTION_ITERATIONS = 40

# --- calc_portfolio_performance constants ---
XIRR_ITERATIONS = 64
XIRR_LOW = -0.9999
XIRR_HIGH = 10.0

COMMISSION_ACCEPT_CAP_BPS = 600
MAX_NEGOTIATION_ROUND = 4
OFFER_EXPIRES_DEFAULT_DAYS = 10
OFFER_EXPIRES_MAX_DAYS = 30
LE_VALIDITY_DAYS = 180
MARKETING_WINDOW_DAYS = 90
RESCISSION_WINDOW_DAYS = 15
PREMIUM_DUE_STEP_DAYS = 30
PREMIUM_GRACE_DAYS = 31
PAYMENT_ROW_CAP = 360
TRACKING_COVERAGE_DAYS = 90
APPROVE_LICENSE_HORIZON_DAYS = 30

CHECK_ORDER = ["LICENSE", "FACE", "AGE", "CONTESTABILITY", "TYPE"]

REQUIRED_PACKET_TYPES = {"COMPENSATION", "ALTERNATIVES", "TAX", "PRIVACY", "RESCISSION_RIGHTS"}

BASE_CLOSING_DOCS = [
    "CHANGE_OF_OWNERSHIP",
    "CHANGE_OF_BENEFICIARY",
    "COMPENSATION_DISCLOSURE",
    "ALTERNATIVES_DISCLOSURE",
    "TAX_DISCLOSURE",
    "PRIVACY_NOTICE",
    "RESCISSION_NOTICE",
]
STATE_SUPPLEMENT_DOC = "STATE_SUPPLEMENT"
STATE_SUPPLEMENT_STATES = {"CA", "NY"}


# ---------------------------------------------------------------------------
# calc_age_years
# ---------------------------------------------------------------------------


def age_years(dob, at_date):
    age = at_date.year - dob.year
    if (at_date.month, at_date.day) < (dob.month, dob.day):
        age -= 1
    return age


def policy_in_contestability(policy, at_date):
    return at_date < add_months(policy["issue_date"], CONTESTABILITY_MONTHS)


def claim_in_contestability(case_acquired_at, date_of_death):
    if case_acquired_at is None:
        return False
    return date_of_death < add_months(case_acquired_at.date(), CONTESTABILITY_MONTHS)


# ---------------------------------------------------------------------------
# Governing license
# ---------------------------------------------------------------------------


def governing_license(state_code, at_date):
    """ACTIVE row for the state whose closed window covers the clock date."""
    for lic in store.licenses.values():
        if (
            lic["state_code"] == state_code
            and lic["status"] == "ACTIVE"
            and lic["effective_date"] <= at_date <= lic["expiry_date"]
        ):
            return lic
    return None


# ---------------------------------------------------------------------------
# calc_eligibility_screening
# ---------------------------------------------------------------------------


def run_screening(case, policy, insured):
    today = store.clock.date()
    checks = {
        "license_ok": governing_license(insured["state_code"], today) is not None,
        "face_ok": policy["face_amount_cents"] >= MIN_FACE_CENTS,
        "age_ok": age_years(insured["date_of_birth"], today) >= MIN_AGE_YEARS,
        "contestability_ok": today
        >= add_months(policy["issue_date"], CONTESTABILITY_MONTHS),
        "type_ok": policy["policy_type"] != "TERM_NONCONVERTIBLE",
    }
    failure_reasons = [c for c in CHECK_ORDER if not checks[c.lower() + "_ok"]]
    result = "PASSED" if not failure_reasons else "FAILED"
    return checks, failure_reasons, result


# ---------------------------------------------------------------------------
# calc_le_adjust_blend
# ---------------------------------------------------------------------------


def adjust_le(base_le_months, impairment_debits):
    prod = Decimal(1)
    for d in impairment_debits:
        prod *= Decimal(1) - Decimal(str(d))
    adjusted = int(Decimal(base_le_months) * prod)  # floor for non-negative
    return max(1, adjusted)


def eligible_le_reports(case_id):
    """Reports entering the blend: DELIVERED and valid_through >= clock."""
    now = store.clock
    return [
        r
        for r in store.le_reports.values()
        if r["case_id"] == case_id
        and r["status"] == "DELIVERED"
        and r["valid_through"] >= now
    ]


def blend_le(reports):
    if len(reports) == 1:
        return reports[0]["adjusted_le_months"]
    num = sum(TIER_WEIGHT[r["underwriter_tier"]] * r["adjusted_le_months"] for r in reports)
    den = sum(TIER_WEIGHT[r["underwriter_tier"]] for r in reports)
    return rhu_div(num, den)


def latest_eligible_report(case_id):
    reps = eligible_le_reports(case_id)
    if not reps:
        return None
    return max(reps, key=lambda r: (r["delivered_at"], r["_seq"]))


def latest_delivered_report(case_id):
    reps = [r for r in store.le_reports.values() if r["case_id"] == case_id and r["delivered_at"] is not None]
    if not reps:
        return None
    return max(reps, key=lambda r: (r["delivered_at"], r["_seq"]))


def remaining_le_months(case, as_of):
    """remaining LE = blended minus whole 30-day months since latest delivery."""
    rep = latest_eligible_report(case["id"]) or latest_delivered_report(case["id"])
    blended = case.get("blended_le_months")
    if rep is None or blended is None:
        return max(1, blended or 1)
    months_elapsed = int(days_between(rep["delivered_at"], as_of) // 30)
    return max(1, blended - months_elapsed)


# ---------------------------------------------------------------------------
# calc_reserve_price
# ---------------------------------------------------------------------------


def reserve_price(policy, k):
    i = PRICING_RATE_BPS / 10000 / 12
    v = 1 / (1 + i)
    pv_benefit = policy["face_amount_cents"] * v**k
    a_k = (1 - v**k) / i
    pv_premiums = (policy["annual_premium_cents"] / 12) * a_k
    expense_load = EXPENSE_FLAT_CENTS + rhu_div(
        policy["face_amount_cents"] * EXPENSE_FACE_BPS, 10000
    )
    raw = pv_benefit - pv_premiums - expense_load
    cap = rhu_div(policy["face_amount_cents"] * PRICE_CAP_FACE_BPS, 10000)
    return min(cap, max(0, rhu(raw)))


# ---------------------------------------------------------------------------
# calc_escrow_waterfall / expected funding
# ---------------------------------------------------------------------------


def expected_funding(price_cents):
    return price_cents + ESCROW_FEE_CENTS + rhu_div(price_cents * SERVICING_FEE_BPS, 10000)


def waterfall(case, policy):
    """Returns the four bucket amounts in pinned creation order."""
    price = case["purchase_price_cents"]
    fee_escrow = ESCROW_FEE_CENTS
    fee_servicing = rhu_div(price * SERVICING_FEE_BPS, 10000)
    commission = min(
        rhu_div(price * (case.get("broker_commission_bps") or 0), 10000),
        rhu_div(policy["face_amount_cents"] * COMMISSION_CAP_FACE_BPS, 10000),
    )
    seller_net = price - commission
    return [
        ("ESCROW_FEE", fee_escrow),
        ("SERVICING_FEE", fee_servicing),
        ("BROKER_COMMISSION", commission),
        ("SELLER_NET", seller_net),
    ]


# ---------------------------------------------------------------------------
# calc_premium_optimization
# ---------------------------------------------------------------------------


def _mf_project(cash_value, monthly, k, face):
    cv = cash_value
    for _ in range(1, k + 1):
        coi = rhu(max(0, face - cv) * COI_MONTHLY_RATE)
        cv = rhu(cv * (1 + CREDITING_MONTHLY)) + monthly - coi
    return cv


def _mf_solve(cash_value, k, ap12, face):
    lo, hi = 0.0, ap12 * 4
    for _ in range(MF_BISECTION_ITERATIONS):
        mid = (lo + hi) / 2
        if _mf_project(cash_value, mid, k, face) >= 0:
            hi = mid
        else:
            lo = mid
    return hi


def premium_optimization(case, policy, portfolio):
    k = remaining_le_months(case, store.clock)
    i = portfolio["discount_rate_bps"] / 10000 / 12
    v = 1 / (1 + i)
    a_k = (1 - v**k) / i
    face = policy["face_amount_cents"]
    cv = policy["cash_value_cents"]
    ap12 = policy["annual_premium_cents"] / 12

    # PAY_AS_DUE
    m_due = rhu(ap12)
    env_due = face * v**k - ap12 * a_k

    # REDUCED_PAID_UP
    pv_prem = ap12 * a_k
    reduced_face = rhu(face * cv / (cv + pv_prem)) if cv + pv_prem > 0 else 0
    env_rpu = reduced_face * v**k

    # MINIMUM_FUNDING (excluded when the solved premium rounds to 0)
    m_mf = rhu(_mf_solve(cv, k, ap12, face))
    env_mf = face * v**k - m_mf * a_k

    candidates = [
        ("PAY_AS_DUE", env_due, m_due, None),
        ("REDUCED_PAID_UP", env_rpu, 0, reduced_face),
    ]
    if m_mf > 0:
        candidates.append(("MINIMUM_FUNDING", env_mf, m_mf, None))

    best = candidates[0]
    for cand in candidates[1:]:
        if cand[1] > best[1]:  # ties keep the earlier-priority strategy
            best = cand
    strategy, env, monthly, reduced = best
    return {
        "strategy": strategy,
        "optimized_monthly_premium_cents": monthly,
        "planned_months": k,
        "reduced_face_cents": reduced,
        "expected_net_value_cents": rhu(env),
    }


# ---------------------------------------------------------------------------
# calc_policy_value / calc_portfolio_performance
# ---------------------------------------------------------------------------


def active_schedule(case_id):
    for s in store.schedules.values():
        if s["case_id"] == case_id and s["status"] == "ACTIVE":
            return s
    return None


def total_paid_premiums(case_id):
    total = 0
    for s in store.schedules.values():
        if s["case_id"] == case_id:
            total += s["total_paid_cents"]
    return total


def paid_claim(case_id):
    for c in store.death_claims.values():
        if c["case_id"] == case_id and c["status"] == "PAID":
            return c
    return None


def policy_value(case, policy, portfolio, period_end):
    """One policy_valuations row: {case_id, remaining_le_months, value_cents}."""
    remaining = remaining_le_months(case, period_end)
    if case["status"] == "MATURED":
        claim = paid_claim(case["id"])
        value = claim["net_proceeds_cents"] if claim else 0
    elif case["status"] == "LAPSED":
        value = 0
    else:  # ACQUIRED
        face = policy["face_amount_cents"]
        if portfolio["valuation_method"] == "PROSPECTIVE":
            i = portfolio["discount_rate_bps"] / 10000 / 12
            v = 1 / (1 + i)
            k = remaining
            a_k = (1 - v**k) / i
            sched = active_schedule(case["id"])
            monthly = (
                sched["optimized_monthly_premium_cents"]
                if sched
                else policy["annual_premium_cents"] / 12
            )
            value = rhu(face * v**k - monthly * a_k)
        else:  # INVESTMENT — cost accretion
            years_held = days_between(case["acquired_at"], period_end) / 365
            cost = case["purchase_price_cents"] + total_paid_premiums(case["id"])
            value = min(
                face,
                rhu(cost * (1 + portfolio["discount_rate_bps"] / 10000) ** years_held),
            )
    value = max(0, value)
    return {
        "case_id": case["id"],
        "remaining_le_months": remaining,
        "value_cents": value,
    }


def portfolio_cases(portfolio_id):
    return [
        c
        for c in store.cases.values()
        if c["portfolio_id"] == portfolio_id
    ]


def portfolio_cash_flows(portfolio_id):
    """Signed external flows (datetime, cents): funding outflows and premiums."""
    flows = []
    case_ids = {c["id"] for c in portfolio_cases(portfolio_id)}
    for esc in store.escrows.values():
        if esc["case_id"] not in case_ids:
            continue
        if esc["status"] in ("FUNDED", "RELEASED", "CLOSED") and esc["funded_at"] is not None:
            case = store.cases[esc["case_id"]]
            price = case["purchase_price_cents"]
            if price is None:
                # purchase price cleared only by rescission, which reverses the escrow
                offer = store.offers.get(case["accepted_offer_id"]) if case["accepted_offer_id"] else None
                price = offer["effective_price_cents"] if offer else 0
            flows.append((esc["funded_at"], -price))
    for pay in store.payments.values():
        if pay["status"] != "PAID":
            continue
        sched = store.schedules[pay["schedule_id"]]
        if sched["case_id"] in case_ids:
            flows.append((pay["paid_at"], -pay["amount_cents"]))
    return flows


def _day_offset(t, start_dt):
    return (t - start_dt).total_seconds() / 86400.0


def portfolio_performance(portfolio_id, period_start, period_end, nav_cents):
    start_dt = datetime(
        period_start.year, period_start.month, period_start.day, tzinfo=timezone.utc
    )
    end_dt = datetime(period_end.year, period_end.month, period_end.day, tzinfo=timezone.utc)
    flows = portfolio_cash_flows(portfolio_id)
    v0 = sum(-amt for t, amt in flows if t < start_dt)
    window = [(_day_offset(t, start_dt), amt) for t, amt in flows if start_dt <= t < end_dt]
    d_total = (period_end - period_start).days

    # MONEY_WEIGHTED: XIRR via 64-iteration bisection
    cfs = []
    if v0 > 0:
        cfs.append((0.0, -v0))
    cfs.extend(window)
    cfs.append((float(d_total), nav_cents))

    def npv(r):
        return sum(cf / (1 + r) ** (d / 365) for d, cf in cfs)

    lo, hi = XIRR_LOW, XIRR_HIGH
    for _ in range(XIRR_ITERATIONS):
        mid = (lo + hi) / 2
        if npv(mid) > 0:
            lo = mid
        else:
            hi = mid
    money_weighted = rhu(((lo + hi) / 2) * 10000)

    # TIME_WEIGHTED: Modified Dietz
    f_sum = sum(amt for _, amt in window)
    if d_total > 0:
        w_sum = sum(((d_total - d) / d_total) * amt for d, amt in window)
    else:
        w_sum = 0
    denom = v0 + w_sum
    r_dietz = 0 if denom == 0 else (nav_cents - v0 - f_sum) / denom
    time_weighted = rhu(r_dietz * 10000)

    return money_weighted, time_weighted


# ---------------------------------------------------------------------------
# calc_death_claim_net
# ---------------------------------------------------------------------------


def claim_net_proceeds(case, policy, gross_proceeds_cents, date_of_death):
    cutoff = datetime.combine(date_of_death, time(23, 59, 59), tzinfo=timezone.utc)
    unpaid = 0
    sched = active_schedule(case["id"])
    if sched:
        for pay in store.payments.values():
            if (
                pay["schedule_id"] == sched["id"]
                and pay["status"] in ("SCHEDULED", "MISSED")
                and pay["due_date"] <= cutoff
            ):
                unpaid += pay["amount_cents"]
    return max(0, gross_proceeds_cents - policy["policy_loan_cents"] - unpaid)


# ---------------------------------------------------------------------------
# calc_investor_share
# ---------------------------------------------------------------------------


def investor_shares(portfolio, nav_cents):
    allocations = portfolio["allocations"]
    total_units = sum(a["units"] for a in allocations)
    if total_units <= 0:
        return []
    shares = [rhu_div(nav_cents * a["units"], total_units) for a in allocations]
    drift = nav_cents - sum(shares)
    if drift != 0:
        max_units = max(a["units"] for a in allocations)
        candidates = [idx for idx, a in enumerate(allocations) if a["units"] == max_units]
        # tie -> allocation whose Investor.created_at is earliest
        def inv_key(idx):
            inv = store.investors.get(allocations[idx]["investor_id"])
            return (inv["created_at"], inv["_seq"]) if inv else (datetime.max.replace(tzinfo=timezone.utc), 0)
        target = min(candidates, key=inv_key)
        shares[target] += drift
    return [
        {"investor_id": a["investor_id"], "share_cents": shares[idx]}
        for idx, a in enumerate(allocations)
    ]
