"""Every calculation in PRD section 3, plus the derive-on-read aggregates.

All money is integer cents, all rates integer basis points; every division is
round_half_up (util.rhu) applied exactly where a formula in the PRD applies it.
"""
from datetime import timedelta

from store import db
from util import add_months, fmt_date, parse_date, rhu, whole_months_between

BPS = 10000

# --- PRD 3.4 instant decision constants -------------------------------------
FICO_FLOOR = 620
DTI_CEILING_BPS = 4500
COUNTER_OFFER_FLOOR_CENTS = 200000
OFFER_VALIDITY_DAYS = 14
FICO_TIERS = (
    (760, 850, 6000, 7500000),
    (700, 759, 4500, 5000000),
    (660, 699, 3000, 3000000),
    (620, 659, 2000, 1500000),
)

# --- PRD 3.7 / 3.8 funding constants ----------------------------------------
CERTIFIED_RELEASE_BPS = 10000
SUBSTANTIAL_COMPLETION_BPS = 8000
SPEED_SURCHARGE_BPS = {"NEXT_DAY": 75, "STANDARD_3DAY": 0}
VOLUME_TIERS = ((50000000, 40), (20000000, 25), (5000000, 10))
TARGET_BPS_BY_RISK_TIER = {"LOW": 200, "STANDARD": 400, "ELEVATED": 700, "HIGH": 1200}
HOLDBACK_CAP_BPS_OF_DRAW = 1500
TRAILING_TARGET_WINDOW_DAYS = 180
TRAILING_VOLUME_TIER_DAYS = 90
VELOCITY_WINDOW_DAYS = 7

# --- PRD 3.9 / 3.10 / 3.11 constants ----------------------------------------
CURE_PAYMENT_BPS = 500
RECEIVABLE_CAP_BPS_OF_TRAILING_VOLUME = 5000
RESERVE_SUSPENSION_BPS = 5000
OPEN_ALERT_WEIGHT_DIVISOR = 2
SCORE_CEILING = 100
SYSTEM_ALERT_SEVERITY_WEIGHT = 40
FRAUD_SUSPENSION_SCORE = 60
MIN_SEASONED_DRAWS = 5
TERMINATION_DISPUTE_RATE_BPS = 2500
MERCHANT_RESPONSE_DAYS = 10
DISCLOSURE_ACK_DAYS = 3
DELINQUENCY_GRACE_DAYS = 30
CHARGE_OFF_DAYS = 120
REOPEN_WINDOW_DAYS = 30
DAY_COUNT_BASIS = 365

NON_TERMINAL_DISPUTE = ("SUBMITTED", "MERCHANT_RESPONSE_PENDING", "ESCALATED_NO_RESPONSE")
COUNTED_DISPUTE_STATUSES = (
    "SUBMITTED",
    "MERCHANT_RESPONSE_PENDING",
    "ESCALATED_NO_RESPONSE",
    "RESOLVED_CONSUMER_FAVOR",
)
OPEN_LOAN_STATUSES = ("CURRENT", "DELINQUENT")
CLOSED_LOAN_STATUSES = ("PAID_OFF", "CHARGED_OFF")


def trade_rule_for(trade_type):
    for rule in db.ordered(db.trade_rules):
        if rule["trade_type"] == trade_type:
            return rule
    return None


# =============================================================================
# Consumer aggregates (PRD 3.4)
# =============================================================================
def consumer_loans(consumer_id):
    return [a for a in db.ordered(db.loan_accounts) if a["consumer_id"] == consumer_id]


def existing_program_debt_cents(consumer_id):
    total = 0
    for acct in consumer_loans(consumer_id):
        if acct["balance_status"] in CLOSED_LOAN_STATUSES:
            continue
        total += principal_balance_cents(acct) + acct["capitalized_interest_cents"]
    return total


def active_loan_count(consumer_id):
    return len([a for a in consumer_loans(consumer_id)
                if a["balance_status"] in OPEN_LOAN_STATUSES])


# =============================================================================
# Instant credit decision (PRD 3.4)
# =============================================================================
def dti_bps(debt_cents, ticket_cents, annual_income_cents):
    return rhu((debt_cents + ticket_cents) * BPS, annual_income_cents)


def fico_tier(fico_score):
    for low, high, factor_bps, cap_cents in FICO_TIERS:
        if low <= fico_score <= high:
            return factor_bps, cap_cents
    return None


def instant_credit_decision(consumer, project_amount_cents):
    """Returns (decision, approved_limit_cents, decision_dti_bps, reason_codes)."""
    if consumer["fico_score"] < FICO_FLOOR:
        return "DECLINED", 0, 0, ["FICO_BELOW_FLOOR"]
    tier = fico_tier(consumer["fico_score"])
    if tier is None:
        return "DECLINED", 0, 0, ["FICO_BELOW_FLOOR"]
    factor_bps, cap_cents = tier
    debt = existing_program_debt_cents(consumer["id"])
    ratio = dti_bps(debt, project_amount_cents, consumer["annual_income_cents"])
    if ratio > DTI_CEILING_BPS:
        return "DECLINED", 0, ratio, ["DTI_ABOVE_CEILING"]
    income_ceiling = rhu(consumer["annual_income_cents"] * factor_bps, BPS)
    credit_ceiling = min(income_ceiling, cap_cents)
    if project_amount_cents <= credit_ceiling:
        return "APPROVED", credit_ceiling, ratio, ["WITHIN_LIMIT"]
    if credit_ceiling >= COUNTER_OFFER_FLOOR_CENTS:
        return "COUNTER_OFFERED", credit_ceiling, ratio, ["LIMIT_BELOW_TICKET"]
    return "DECLINED", 0, ratio, ["LIMIT_BELOW_TICKET"]


# =============================================================================
# Loan-account ledger and deferred-interest accrual (PRD 3.9)
# =============================================================================
def account_draws(loan_account_id):
    return [d for d in db.ordered(db.draws) if d["loan_account_id"] == loan_account_id]


def account_payments(loan_account_id):
    return [p for p in db.ordered(db.payments)
            if p["loan_account_id"] == loan_account_id]


def account_chargebacks(loan_account_id):
    return [c for c in db.ordered(db.disputes)
            if c["loan_account_id"] == loan_account_id
            and c["status"] == "RESOLVED_CONSUMER_FAVOR"]


def total_funded_cents(acct):
    return sum(d["funded_amount_cents"] for d in account_draws(acct["id"])
               if d["status"] == "SETTLED")


def principal_balance_cents(acct):
    total = total_funded_cents(acct)
    total -= sum(p["applied_to_principal_cents"] for p in account_payments(acct["id"]))
    total -= sum(c["chargeback_amount_cents"] for c in account_chargebacks(acct["id"]))
    return total


def balance_events(acct):
    """Every event that changes principal_balance_cents, chronologically."""
    events = []
    for draw in account_draws(acct["id"]):
        if draw["status"] == "SETTLED" and draw.get("settled_on"):
            events.append((parse_date(draw["settled_on"]), draw["_seq"],
                           draw["funded_amount_cents"]))
        elif draw["status"] == "REVERSED" and draw.get("settled_on"):
            events.append((parse_date(draw["settled_on"]), draw["_seq"],
                           draw["funded_amount_cents"]))
            events.append((parse_date(draw["_reversed_on"]), draw["_seq"],
                           -draw["funded_amount_cents"]))
    for pay in account_payments(acct["id"]):
        if pay["applied_to_principal_cents"]:
            events.append((parse_date(pay["posted_on"]), pay["_seq"],
                           -pay["applied_to_principal_cents"]))
    for case in account_chargebacks(acct["id"]):
        events.append((parse_date(case["resolved_on"]), case["_seq"],
                       -case["chargeback_amount_cents"]))
    events.sort(key=lambda e: (e[0], e[1]))
    return events


def accrual_numerator(acct, as_of_date):
    """SUM(balance_i * apr_bps * days_i) accumulated exactly, never rounded."""
    if not acct.get("first_funding_on"):
        return 0
    start = parse_date(acct["first_funding_on"])
    if as_of_date <= start:
        return 0
    balance = 0
    cursor = start
    balance_days = 0
    for event_date, _seq, delta in balance_events(acct):
        if event_date < start:
            event_date = start
        if event_date >= as_of_date:
            break
        if event_date > cursor:
            balance_days += balance * (event_date - cursor).days
            cursor = event_date
        balance += delta
    if as_of_date > cursor:
        balance_days += balance * (as_of_date - cursor).days
    return balance_days * acct["apr_bps"]


def accrued_interest_cents(acct, as_of_date):
    """Exact accumulation, one single round_half_up at the very end."""
    numerator = accrual_numerator(acct, as_of_date)
    if numerator <= 0:
        return 0
    return rhu(numerator, BPS * DAY_COUNT_BASIS)


def accrued_deferred_interest_cents(acct):
    if acct["promo_status"] != "PROMO_ACTIVE":
        return 0
    return accrued_interest_cents(acct, db.today())


def capitalization_amount_cents(acct):
    as_of = parse_date(acct["promo_expires_on"]) + timedelta(days=1)
    return accrued_interest_cents(acct, as_of)


def deferred_interest_at_risk_cents(acct):
    return accrued_deferred_interest_cents(acct)


def promo_payoff_cents(acct):
    return principal_balance_cents(acct)


def standard_payoff_cents(acct):
    return (principal_balance_cents(acct) + acct["capitalized_interest_cents"]
            + accrued_deferred_interest_cents(acct))


# =============================================================================
# Project / milestone aggregates (PRD 3.6, 3.7)
# =============================================================================
def project_milestones(project_id):
    return [m for m in db.ordered(db.milestones) if m["project_id"] == project_id]


def project_draws(project):
    milestone_ids = set(m["id"] for m in project_milestones(project["id"]))
    return [d for d in db.ordered(db.draws)
            if d["project_milestone_id"] in milestone_ids]


def project_disputes(project_id):
    return [c for c in db.ordered(db.disputes) if c["project_id"] == project_id]


def verified_release_bps(project):
    return sum(m["release_pct_bps"] for m in project_milestones(project["id"])
               if m["status"] == "VERIFIED")


def settled_funded_cents(project):
    return sum(d["funded_amount_cents"] for d in project_draws(project)
               if d["status"] == "SETTLED")


def funded_pct_bps(project):
    if not project["contract_amount_cents"]:
        return 0
    return rhu(settled_funded_cents(project) * BPS, project["contract_amount_cents"])


def disputed_amount_cents(project):
    return sum(c["claimed_incomplete_amount_cents"] for c in project_disputes(project["id"])
               if c["status"] in NON_TERMINAL_DISPUTE)


def completion_cap_bps(project):
    if project["completion_status"] == "CERTIFIED_COMPLETE":
        return CERTIFIED_RELEASE_BPS
    merchant = db.merchants.get(project["merchant_id"])
    rule = trade_rule_for(merchant["trade_type"]) if merchant else None
    return rule["max_precompletion_release_bps"] if rule else 0


def max_fundable_now_cents(project):
    if project["completion_status"] == "ABANDONED":
        return 0
    release_cap = min(verified_release_bps(project), completion_cap_bps(project))
    releasable = rhu(project["contract_amount_cents"] * release_cap, BPS)
    pending = sum(d["requested_amount_cents"] for d in project_draws(project)
                  if d["status"] == "REQUESTED")
    return max(0, releasable - settled_funded_cents(project) - pending)


def milestone_is_funded(milestone):
    return any(d["project_milestone_id"] == milestone["id"]
               and d["status"] in ("REQUESTED", "SETTLED")
               for d in db.draws.values())


def project_for_milestone(milestone):
    return db.projects.get(milestone["project_id"])


def project_for_draw(draw):
    milestone = db.milestones.get(draw["project_milestone_id"])
    return project_for_milestone(milestone) if milestone else None


# =============================================================================
# Merchant volume windows (PRD 3.8)
# =============================================================================
def merchant_draws(merchant_id):
    return [d for d in db.ordered(db.draws) if d["merchant_id"] == merchant_id]


def settled_volume(merchant_id, start_date, end_date, include_end=True,
                   exclude_draw_id=None):
    total = 0
    for draw in merchant_draws(merchant_id):
        if draw["status"] != "SETTLED" or not draw.get("settled_on"):
            continue
        if exclude_draw_id and draw["id"] == exclude_draw_id:
            continue
        settled = parse_date(draw["settled_on"])
        if settled < start_date:
            continue
        if include_end:
            if settled > end_date:
                continue
        elif settled >= end_date:
            continue
        total += draw["funded_amount_cents"]
    return total


def velocity_window_volume(merchant_id, exclude_draw_id=None):
    """Closed window [clock_date - 6 days, clock_date]."""
    today = db.today()
    start = today - timedelta(days=VELOCITY_WINDOW_DAYS - 1)
    return settled_volume(merchant_id, start, today, True, exclude_draw_id)


def trailing_target_volume(merchant_id, as_of_date=None, exclude_draw_id=None):
    """Closed window [as_of - 180 days, as_of]."""
    as_of = as_of_date or db.today()
    start = as_of - timedelta(days=TRAILING_TARGET_WINDOW_DAYS)
    return settled_volume(merchant_id, start, as_of, True, exclude_draw_id)


def trailing_tier_volume(merchant_id, exclude_draw_id=None):
    """Half-open window [clock_date - 90 days, clock_date)."""
    today = db.today()
    start = today - timedelta(days=TRAILING_VOLUME_TIER_DAYS)
    return settled_volume(merchant_id, start, today, False, exclude_draw_id)


def funded_volume_cents(merchant_id):
    return sum(d["funded_amount_cents"] for d in merchant_draws(merchant_id)
               if d["status"] == "SETTLED")


def settled_draw_count(merchant_id):
    return len([d for d in merchant_draws(merchant_id) if d["status"] == "SETTLED"])


# =============================================================================
# Merchant portfolio performance and fraud score (PRD 3.11)
# =============================================================================
def merchant_alerts(merchant_id):
    return [a for a in db.ordered(db.alerts) if a["merchant_id"] == merchant_id]


def phantom_risk_score(merchant_id):
    confirmed = sum(a["severity_weight"] for a in merchant_alerts(merchant_id)
                    if a["status"] == "CONFIRMED")
    open_total = sum(a["severity_weight"] for a in merchant_alerts(merchant_id)
                     if a["status"] == "OPEN")
    score = confirmed + rhu(open_total, OPEN_ALERT_WEIGHT_DIVISOR)
    return min(SCORE_CEILING, score)


def merchant_loans(merchant_id):
    return [a for a in db.ordered(db.loan_accounts) if a["merchant_id"] == merchant_id]


def merchant_disputes(merchant_id):
    return [c for c in db.ordered(db.disputes) if c["merchant_id"] == merchant_id]


def dispute_rate_bps(merchant_id):
    loan_count = len(merchant_loans(merchant_id))
    if loan_count == 0:
        return 0
    counted = len([c for c in merchant_disputes(merchant_id)
                   if c["status"] in COUNTED_DISPUTE_STATUSES])
    return rhu(counted * BPS, loan_count)


def delinquency_rate_bps(merchant_id):
    loans = merchant_loans(merchant_id)
    if not loans:
        return 0
    bad = len([a for a in loans
               if a["balance_status"] in ("DELINQUENT", "CHARGED_OFF")])
    return rhu(bad * BPS, len(loans))


def portfolio_grade(dispute_bps, delinquency_bps, phantom_score):
    if dispute_bps <= 200 and delinquency_bps <= 300 and phantom_score <= 20:
        return "A"
    if dispute_bps <= 500 and delinquency_bps <= 700 and phantom_score <= 40:
        return "B"
    if dispute_bps <= 1000 and delinquency_bps <= 1500 and phantom_score <= 60:
        return "C"
    return "D"


def merchant_grade(merchant_id):
    return portfolio_grade(dispute_rate_bps(merchant_id),
                           delinquency_rate_bps(merchant_id),
                           phantom_risk_score(merchant_id))


def merchant_risk_tier(merchant_id):
    if settled_draw_count(merchant_id) < MIN_SEASONED_DRAWS:
        return "STANDARD"
    return {"A": "LOW", "B": "STANDARD", "C": "ELEVATED", "D": "HIGH"}[
        merchant_grade(merchant_id)]


def termination_recommended(merchant_id):
    return (merchant_grade(merchant_id) == "D"
            or phantom_risk_score(merchant_id) >= FRAUD_SUSPENSION_SCORE
            or dispute_rate_bps(merchant_id) >= TERMINATION_DISPUTE_RATE_BPS)


def reserve_coverage_bps(merchant):
    target = merchant["holdback_target_cents"]
    if target == 0:
        return BPS
    return rhu(merchant["holdback_reserve_cents"] * BPS, target)


def recompute_holdback_target(merchant, as_of_date=None):
    """Target only: trailing-180 SETTLED volume x the risk-tier target rate."""
    volume = trailing_target_volume(merchant["id"], as_of_date)
    rate = TARGET_BPS_BY_RISK_TIER[merchant_risk_tier(merchant["id"])]
    merchant["holdback_target_cents"] = rhu(volume * rate, BPS)
    return merchant["holdback_target_cents"]


# =============================================================================
# Draw economics (PRD 3.7 provisional / PRD 3.8 final)
# =============================================================================
def governing_enrollment(merchant_id, promotion_plan_id):
    candidates = [e for e in db.ordered(db.enrollments)
                  if e["merchant_id"] == merchant_id
                  and e["promotion_plan_id"] == promotion_plan_id
                  and e["status"] == "ACTIVE"]
    today = db.today()
    for enrollment in candidates:
        if (parse_date(enrollment["window_start_date"]) <= today
                <= parse_date(enrollment["window_end_date"])):
            return enrollment
    return candidates[0] if candidates else None


def provisional_economics(funded_cents, plan, rule):
    discount = rhu(funded_cents * plan["merchant_discount_bps"], BPS)
    holdback = rhu(funded_cents * rule["holdback_pct_bps"], BPS)
    return discount, holdback, funded_cents - discount - holdback


def volume_tier_credit_bps(trailing90_cents):
    for threshold, credit in VOLUME_TIERS:
        if trailing90_cents >= threshold:
            return credit
    return 0


def final_discount(funded_cents, effective_bps, speed_bps, credit_bps):
    """Component-wise: three independent roundings, then floored at zero."""
    base = rhu(funded_cents * effective_bps, BPS)
    speed = rhu(funded_cents * speed_bps, BPS)
    credit = rhu(funded_cents * credit_bps, BPS)
    return max(0, base + speed - credit)


def holdback_reserve_target(merchant, funded_cents, rule, draw_id=None):
    """The pinned six-step order. Returns (withheld_cents, target_after_cents)."""
    trailing = trailing_target_volume(merchant["id"], None, draw_id) + funded_cents
    rate = TARGET_BPS_BY_RISK_TIER[merchant_risk_tier(merchant["id"])]
    target_after = rhu(trailing * rate, BPS)
    gap = max(0, target_after - merchant["holdback_reserve_cents"])
    base_withhold = rhu(funded_cents * rule["holdback_pct_bps"], BPS)
    per_draw_cap = rhu(funded_cents * HOLDBACK_CAP_BPS_OF_DRAW, BPS)
    return min(base_withhold, gap, per_draw_cap), target_after


# =============================================================================
# Chargeback waterfall (PRD 3.10)
# =============================================================================
def chargeback_waterfall(merchant, claim_cents, resolved_on_date):
    absorbed = min(claim_cents, merchant["holdback_reserve_cents"])
    remainder = claim_cents - absorbed
    trailing = trailing_target_volume(merchant["id"], resolved_on_date)
    cap = rhu(trailing * RECEIVABLE_CAP_BPS_OF_TRAILING_VOLUME, BPS)
    receivable = min(remainder, cap)
    write_off = remainder - receivable
    return absorbed, receivable, write_off


def cure_threshold_cents(acct):
    total = principal_balance_cents(acct) + acct["capitalized_interest_cents"]
    return rhu(total * CURE_PAYMENT_BPS, BPS)


def promo_expiry_date(start_date, promo_term_months):
    return add_months(start_date, promo_term_months)


def license_covers(license_rec, on_date):
    """Half-open coverage [effective_from, expires_on)."""
    return (parse_date(license_rec["effective_from"]) <= on_date
            < parse_date(license_rec["expires_on"]))


def months_of_coverage_left(license_rec, from_date):
    return whole_months_between(from_date, parse_date(license_rec["expires_on"]))


def iso_date(value):
    return fmt_date(value)
