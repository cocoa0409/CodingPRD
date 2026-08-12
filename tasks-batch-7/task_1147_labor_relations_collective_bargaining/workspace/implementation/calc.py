"""Calculation rules (SCAFFOLD 1.3 / PRD section 3). Monetary values are integer
cents; per-line rounding is half-up; Decimal is used everywhere (never float math)."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

# scenario_total_cost constants
HOURS_PER_YEAR = 2080
WAGE_DRIFT_CAP_PCT = Decimal("0.15")
BENEFITS_LOAD = Decimal("1.32")
TIER_HIGH_THRESHOLD = Decimal("0.80")
TIER_HIGH_MULT = Decimal("1.10")
TIER_MID_THRESHOLD = Decimal("0.50")
TIER_MID_MULT = Decimal("1.05")
TIER_LOW_MULT = Decimal("1.00")
CONTINGENCY_PCT = Decimal("0.05")

# ratification_retro_payout constants
RETRO_PERIOD_DAYS = 30
MONTHS_PER_YEAR = 12

# past_practice_strength constants
LEGALISTIC_DECAY = Decimal("0.85")
LEGALISTIC_RECENCY_WEIGHT = Decimal("0.6")
LEGALISTIC_FREQUENCY_WEIGHT = Decimal("0.4")
OPERATIONAL_RECENCY_WEIGHT = Decimal("0.4")
OPERATIONAL_FREQUENCY_WEIGHT = Decimal("0.6")
OPERATIONAL_STEP_YEARS = 5
OPERATIONAL_STEP_VALUE = Decimal("0.5")

# information_request_deadline constants
RESPONSE_BUSINESS_DAYS = 10
DUE_HOUR_UTC = 17
EXTENSION_MAX_COUNT = 2
EXTENSION_MAX_DAYS = 5

# agreement_posture constants
SUNSET_DAYS = 180
CRITICAL_DAYS = 30

MAX_ROUNDS = 12
SESSION_MAX_DURATION = timedelta(hours=12)
NEGOTIATOR_BUFFER = timedelta(minutes=45)


def _cents(value):
    """Round a Decimal half-up to whole cents (integer)."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _round4(value):
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def to_decimal_number(value):
    """Convert a JSON number to Decimal via its shortest string form."""
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# agreement_posture
# ---------------------------------------------------------------------------

def compute_posture(agreement, now):
    status = agreement["status"]
    if status == "DRAFT":
        return "NEGOTIATING"
    if status in ("REPLACED", "ARCHIVED"):
        return "CLOSED"
    if status == "EXPIRED":
        return "UNCOVERED"
    # ACTIVE | EXTENDED: whole calendar days, floor toward past midnight UTC
    days_left = (agreement["expiration_date"].date() - now.date()).days
    if days_left > SUNSET_DAYS:
        return "OPEN"
    if days_left > CRITICAL_DAYS:
        return "SUNSET"
    return "CRITICAL"


def is_bargainable(agreement, now):
    if agreement["status"] in ("DRAFT", "EXPIRED", "EXTENDED"):
        return True
    return compute_posture(agreement, now) in ("SUNSET", "CRITICAL")


# ---------------------------------------------------------------------------
# scenario_total_cost
# ---------------------------------------------------------------------------

def compute_scenario(scenario, agreement, proposals):
    """Returns (year_breakdown_cents, subtotal, reserve, total, per_proposal_y1).

    per_proposal_y1 maps proposal id -> its year-1 line (estimated_year1_cost_cents).
    """
    if scenario["scenario_mode"] == "PROVISIONAL":
        basis = agreement["fte_projected"]
    else:
        basis = agreement["headcount_baseline"]
    term_years = scenario["term_years"]
    base_payroll = Decimal(basis) * Decimal(agreement["avg_loaded_wage_cents"]) * Decimal(HOURS_PER_YEAR)

    year_totals = [0] * term_years
    per_proposal_y1 = {}

    for p in proposals:
        pct = to_decimal_number(p["wage_increase_pct"]) if p["wage_increase_pct"] is not None else Decimal("0")
        wage_y1 = base_payroll * pct
        cap = base_payroll * WAGE_DRIFT_CAP_PCT
        if wage_y1 > cap:
            wage_y1 = cap
        if p["includes_benefits"]:
            wage_y1 = wage_y1 * BENEFITS_LOAD
        r = Decimal(p["affected_headcount"] or 0) / Decimal(basis)
        if r >= TIER_HIGH_THRESHOLD:
            mult = TIER_HIGH_MULT
        elif r >= TIER_MID_THRESHOLD:
            mult = TIER_MID_MULT
        else:
            mult = TIER_LOW_MULT
        wage_y1 = _cents(wage_y1 * mult)  # per-line rounding, pinned

        if scenario["scenario_mode"] == "PROVISIONAL":
            one_time_share = _cents(Decimal(p["one_time_cost_cents"]) / Decimal(term_years))
            one_time_y1 = one_time_share
        else:
            one_time_share = 0
            one_time_y1 = p["one_time_cost_cents"]  # FINAL charges year 1 in full

        recurring = p["recurring_annual_cost_cents"]
        line_y1 = wage_y1 + recurring + one_time_y1
        year_totals[0] += line_y1
        per_proposal_y1[p["id"]] = line_y1

        growth = Decimal("1") + pct
        for k in range(2, term_years + 1):
            wage_k = _cents(Decimal(wage_y1) * (growth ** (k - 1)))  # from year-1 base
            one_time_k = one_time_share if scenario["scenario_mode"] == "PROVISIONAL" else 0
            year_totals[k - 1] += wage_k + recurring + one_time_k

    subtotal = sum(year_totals)
    reserve = _cents(CONTINGENCY_PCT * Decimal(subtotal))  # reserve AFTER subtotal, pinned
    total = subtotal + reserve
    return year_totals, subtotal, reserve, total, per_proposal_y1


# ---------------------------------------------------------------------------
# ratification_outcome / ratification_retro_payout
# ---------------------------------------------------------------------------

def ratification_outcome(vote, votes_for, votes_against):
    votes_cast = votes_for + votes_against
    quorum_needed = -(-vote["eligible_voter_count"] // 2)  # ceil(eligible / 2)
    quorum_met = votes_cast >= quorum_needed  # exactly half is enough
    approved = (votes_for * 2) > votes_cast  # an exact tie FAILS
    return votes_cast, quorum_met, (quorum_met and approved)


def retro_payout(agreement, proposals_implemented, tally_now):
    diff_days = (tally_now - agreement["effective_date"]).days
    if diff_days <= 0:
        return 0
    retro_periods = diff_days // RETRO_PERIOD_DAYS
    if retro_periods <= 0:
        return 0
    total = 0
    for p in proposals_implemented:
        if p["proposal_type"] != "ECONOMIC":
            continue
        monthly = _cents(Decimal(p["recurring_annual_cost_cents"]) / Decimal(MONTHS_PER_YEAR))
        total += monthly * retro_periods
    return total


# ---------------------------------------------------------------------------
# past_practice_strength
# ---------------------------------------------------------------------------

def compute_strengths(practice, now):
    """Returns (strength_legalistic, strength_operational) as floats at 4dp."""
    recency_days = (now.date() - practice["last_observed_date"].date()).days
    recency_years = Decimal(recency_days) / Decimal(365)
    frequency = min(Decimal(practice["occurrence_count"]) / Decimal(10), Decimal("1.0"))

    # LEGALISTIC: exponential recency decay 0.85^floor(years), recency-weighted 0.6
    floor_years = recency_days // 365
    recency_component = LEGALISTIC_DECAY ** floor_years
    legalistic = _round4(LEGALISTIC_RECENCY_WEIGHT * recency_component
                         + LEGALISTIC_FREQUENCY_WEIGHT * frequency)

    # OPERATIONAL: step decay (full within 5 years, half beyond), frequency-weighted 0.6
    step = Decimal("1.0") if recency_years < Decimal(OPERATIONAL_STEP_YEARS) else OPERATIONAL_STEP_VALUE
    operational = _round4(OPERATIONAL_RECENCY_WEIGHT * step
                          + OPERATIONAL_FREQUENCY_WEIGHT * frequency)
    return float(legalistic), float(operational)


# ---------------------------------------------------------------------------
# information_request_deadline
# ---------------------------------------------------------------------------

def _at_due_time(d):
    return d.replace(hour=DUE_HOUR_UTC, minute=0, second=0, microsecond=0)


def _add_business_days(start_date, days):
    """Advance `days` Mon-Fri days, counting starts the day AFTER start_date."""
    current = start_date
    remaining = days
    while remaining > 0:
        current = current + timedelta(days=1)
        if current.weekday() < 5:  # Mon=0 .. Fri=4
            remaining -= 1
    return current


def compute_due_at(received_at, mode):
    if mode == "CALENDAR":
        due_date = received_at + timedelta(days=RESPONSE_BUSINESS_DAYS)
        return _at_due_time(due_date)
    # BUSINESS (default): start the day after received_at, count 10 business days
    due_date = _add_business_days(received_at, RESPONSE_BUSINESS_DAYS)
    return _at_due_time(due_date)


def extend_due_at(due_at, extra_days, mode):
    if mode == "CALENDAR":
        return _at_due_time(due_at + timedelta(days=extra_days))
    return _at_due_time(_add_business_days(due_at, extra_days))


# ---------------------------------------------------------------------------
# envelope_commitment
# ---------------------------------------------------------------------------

def envelope_committed(agreement_id, proposals_by_id):
    total = 0
    for p in proposals_by_id.values():
        if p["agreement_id"] != agreement_id:
            continue
        if p["status"] in ("ACCEPTED", "IMPLEMENTED"):
            if p["estimated_year1_cost_cents"] is not None:
                total += p["estimated_year1_cost_cents"]
    return total


# ---------------------------------------------------------------------------
# expiration_task_due_date
# ---------------------------------------------------------------------------

def task_due_date(expiration_date, due_offset_days):
    return expiration_date + timedelta(days=due_offset_days)
