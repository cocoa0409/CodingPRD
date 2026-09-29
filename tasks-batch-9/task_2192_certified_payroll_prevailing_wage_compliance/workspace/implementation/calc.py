"""The ten calculations. Every monetary result is whole cents, rounded half up;
every derived hour quantity carries two decimal places, rounded half up."""

from decimal import Decimal, ROUND_HALF_UP

import db

# --- pinned constants -------------------------------------------------------
OVERTIME_BASE_MULTIPLIER = Decimal("1.5")

CRITICAL_WEIGHT = 40
MAJOR_WEIGHT = 15
MINOR_WEIGHT = 8
RESTITUTION_FLAG_WEIGHT = 25
RESTITUTION_FLAG_THRESHOLD_CENTS = 500000
DECAY_PER_PERIOD = 5
DECAY_PERIOD_DAYS = 28
DEBARMENT_PROPOSAL_THRESHOLD = 70

POSTURE_FROZEN_RESTITUTION_CENTS = 500000
POSTURE_RESTRICTED_FINDING_COUNT = 2

RESPONSE_WINDOW_DAYS = 30
PORTAL_HARD_CLOSE_DAYS = 90
INTERVIEW_BUFFER_MINUTES = 60

ZERO = Decimal("0")
HOURS_Q = Decimal("0.01")

NON_TERMINAL_FINDING_STATUSES = ("OPEN", "RESPONSE_SUBMITTED", "RESPONSE_REJECTED")
LIVE_WORKFLOW_STATUSES = ("DRAFT", "PENDING_CERTIFICATION", "SUBMITTED", "UNDER_REVIEW", "ACCEPTED")
NON_TERMINAL_WORKFLOW_STATUSES = (
    "DRAFT",
    "PENDING_CERTIFICATION",
    "SUBMITTED",
    "UNDER_REVIEW",
    "RETURNED",
)


def round_cents(value):
    """Round a Decimal to a whole cent, half away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_hours(value):
    return Decimal(value).quantize(HOURS_Q, rounding=ROUND_HALF_UP)


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# calculations.fringe_hourly_credit  (dual variant)
# ---------------------------------------------------------------------------
def fringe_hourly_credit(plan):
    if plan["plan_type"] == "CASH_IN_LIEU":
        return 0, 0
    contribution = dec(plan["annual_contribution_cents"])
    annualized = round_cents(contribution / dec(plan["annual_total_hours"]))
    claimed = round_cents(contribution / dec(plan["annual_public_works_hours"]))
    return annualized, claimed


# ---------------------------------------------------------------------------
# WageRate matching for a project + classification
# ---------------------------------------------------------------------------
def match_wage_rate(project, classification_code):
    for rate in db.wage_rates.values():
        if (
            rate["wage_determination_id"] == project["wage_determination_id"]
            and rate["classification_code"] == classification_code
            and rate["zone_code"] == project["zone_code"]
        ):
            return rate
    return None


def journey_base_cents(rate):
    return rate["base_hourly_rate_cents"] + rate["zone_adjustment_cents"]


# ---------------------------------------------------------------------------
# calculations.required_prevailing_rate
# ---------------------------------------------------------------------------
def required_prevailing_rate(line, worker, rate):
    """Returns (required_base_cents, required_fringe_cents). Callers run the
    apprentice referential checks first, in ladder order."""
    base = journey_base_cents(rate)
    if not line["reported_as_apprentice"]:
        required_base = base
    else:
        pct = rate["apprentice_scale_pct"][worker["apprentice_period"] - 1]
        required_base = round_cents(dec(base) * dec(pct) / dec(100))
    return required_base, rate["fringe_hourly_rate_cents"]


# ---------------------------------------------------------------------------
# calculations.creditable_fringe_per_line
# ---------------------------------------------------------------------------
def creditable_fringe_per_line(line, plan, required_fringe_cents):
    if plan is None:
        plan_credit = 0
    elif plan["approval_status"] != "APPROVED":
        plan_credit = 0
    elif plan["plan_type"] == "UNFUNDED":
        plan_credit = 0
    else:
        plan_credit = plan["annualized_credit_cents"]
    return min(plan_credit, required_fringe_cents)


# ---------------------------------------------------------------------------
# calculations.apprentice_ratio_compliance
# ---------------------------------------------------------------------------
def apprentice_ratio_compliance(lines, trade_of_line, program_of_line):
    """One pass, pre-reclassification journeyworker pool. Writes
    reclassified_journey_hours onto each line and returns total excess hours."""
    for line in lines:
        line["reclassified_journey_hours"] = ZERO

    trades = []
    for line in lines:
        trade = trade_of_line(line)
        if trade not in trades:
            trades.append(trade)

    total_excess = ZERO
    for trade in trades:
        trade_lines = [ln for ln in lines if trade_of_line(ln) == trade]
        apprentice_lines = [ln for ln in trade_lines if ln["reported_as_apprentice"]]
        if not apprentice_lines:
            continue
        a_total = sum((line_hours(ln) for ln in apprentice_lines), ZERO)
        j_total = sum(
            (line_hours(ln) for ln in trade_lines if not ln["reported_as_apprentice"]), ZERO
        )
        ratios = []
        for ln in apprentice_lines:
            program = program_of_line(ln)
            if program is not None and program["id"] not in [p["id"] for p in ratios]:
                ratios.append(program)
        if not ratios:
            continue
        ratio_pct = min(p["allowed_apprentice_hours_per_100_journey"] for p in ratios)
        allowed = round_hours(j_total * dec(ratio_pct) / dec(100))
        excess = a_total - allowed
        if excess <= ZERO:
            continue
        total_excess += excess
        candidates = sorted(
            apprentice_lines,
            key=lambda ln: (-line_hours(ln), ln["created_at"], ln["_seq"]),
        )
        remaining = excess
        for candidate in candidates:
            if remaining <= ZERO:
                break
            absorbed = min(remaining, line_hours(candidate))
            candidate["reclassified_journey_hours"] = absorbed
            remaining -= absorbed
    return total_excess


def line_hours(line):
    return dec(line["straight_hours"]) + dec(line["overtime_hours"])


# ---------------------------------------------------------------------------
# calculations.underpayment_restitution  (dual variant)
# ---------------------------------------------------------------------------
def underpayment_restitution(lines, rate_of_line):
    """Round once per line per hour category, then sum categories, then lines."""
    straight_total = 0
    make_whole_total = 0
    for line in lines:
        rate = rate_of_line(line)
        recl = dec(line["reclassified_journey_hours"])
        straight = dec(line["straight_hours"])
        overtime = dec(line["overtime_hours"])
        recl_straight = min(recl, straight)
        recl_ot = recl - recl_straight
        scaled_straight = straight - recl_straight
        scaled_ot = overtime - recl_ot

        base = journey_base_cents(rate)
        required_base = line["required_base_cents"]
        required_fringe = line["required_fringe_cents"]

        paid_st = line["base_rate_paid_cents"] + line["fringe_cash_paid_cents"] + line["creditable_fringe_cents"]
        paid_ot = line["overtime_rate_paid_cents"] + line["fringe_cash_paid_cents"] + line["creditable_fringe_cents"]

        req_st_scaled = required_base + required_fringe
        req_st_journey = base + required_fringe
        req_ot_scaled = round_cents(dec(required_base) * OVERTIME_BASE_MULTIPLIER) + required_fringe
        req_ot_journey = round_cents(dec(base) * OVERTIME_BASE_MULTIPLIER) + required_fringe

        def_st_scaled = max(0, req_st_scaled - paid_st)
        def_st_journey = max(0, req_st_journey - paid_st)
        def_ot_scaled = max(0, req_ot_scaled - paid_ot)
        def_ot_journey = max(0, req_ot_journey - paid_ot)

        line_straight_cents = round_cents(
            dec(def_st_scaled) * scaled_straight + dec(def_st_journey) * recl_straight
        )
        line_ot_cents = round_cents(
            dec(def_ot_scaled) * scaled_ot + dec(def_ot_journey) * recl_ot
        )
        line["line_underpayment_cents"] = line_straight_cents + line_ot_cents
        straight_total += line_straight_cents
        make_whole_total += line["line_underpayment_cents"]
    return straight_total, make_whole_total


# ---------------------------------------------------------------------------
# calculations.portal_filing_deadline
# ---------------------------------------------------------------------------
def portal_filing_deadline(submission, portal):
    return (
        submission["week_ending_date"]
        + db.days(portal["cutoff_offset_days"])
        + db.hours(portal["grace_hours"])
    )


def hard_close_at(submission):
    return submission["week_ending_date"] + db.days(PORTAL_HARD_CLOSE_DAYS)


def response_due_at(instant):
    return instant + db.days(RESPONSE_WINDOW_DAYS)
