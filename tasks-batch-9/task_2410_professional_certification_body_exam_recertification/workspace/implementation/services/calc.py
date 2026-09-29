"""The sixteen calculations of PRD section 2.5 / 3.

Every quantity is computed with decimal arithmetic and ROUND_HALF_UP, and every
derived field is re-derived from scratch rather than incremented (PRD 2.9), with
the two documented exceptions -- the program's monotonic counters.
"""

from decimal import Decimal

from util import (
    add_days,
    ceil_int,
    dec,
    floor_int,
    round_half_up,
    whole_days_between,
)

# --- constants pinned by the PRD -------------------------------------------
CUT_FLOOR_RATIO = Decimal("0.40")
CUT_CEILING_RATIO = Decimal("0.90")
SCALE_MIN = 200
SCALE_CUT = 500
SCALE_MAX = 800

CEU_MULTIPLIER = {
    "LIVE_INSTRUCTION": Decimal("1.0"),
    "SELF_STUDY": Decimal("0.5"),
    "PRESENTING": Decimal("2.0"),
    "PUBLICATION": Decimal("5.0"),
    "VOLUNTEER": Decimal("0.25"),
}
CEU_CATEGORY_CAP = {
    "SELF_STUDY": Decimal("20.0"),
    "VOLUNTEER": Decimal("5.0"),
}
CARRYOVER_LOOKBACK_DAYS = 90

BASE_FEE_CENTS = 25000
LATE_DAY_RATE_CENTS = 250
MAX_SURCHARGE_CENTS = 30000

POOL_MAX_CONCURRENT_SEATS = 50
CANDIDATE_WINDOW_BUFFER_MINUTES = 120
CHECKIN_LEAD_MINUTES = 30
SECURITY_BAR_DAYS = 730


# ---------------------------------------------------------------------------
# 1. item_statistics + 2. item_flag_evaluation
# ---------------------------------------------------------------------------

def item_statistics(item, program):
    """Classical item analysis over whichever pool the program's basis selects."""
    basis = program["psychometric_stat_basis"]
    if basis == "POOLED":
        responses = item["pretest_response_count"] + item["operational_response_count"]
        correct = item["pretest_correct_count"] + item["operational_correct_count"]
        upper_n = item["pretest_upper_n"] + item["operational_upper_n"]
        upper_c = item["pretest_upper_correct"] + item["operational_upper_correct"]
        lower_n = item["pretest_lower_n"] + item["operational_lower_n"]
        lower_c = item["pretest_lower_correct"] + item["operational_lower_correct"]
    else:
        responses = item["operational_response_count"]
        correct = item["operational_correct_count"]
        upper_n = item["operational_upper_n"]
        upper_c = item["operational_upper_correct"]
        lower_n = item["operational_lower_n"]
        lower_c = item["operational_lower_correct"]

    if responses < program["min_responses_for_stats"] or upper_n == 0 or lower_n == 0:
        return "INSUFFICIENT_DATA", None, None

    p_value = round_half_up(dec(correct) / dec(responses), 4)
    discrimination = round_half_up(
        (dec(upper_c) / dec(upper_n)) - (dec(lower_c) / dec(lower_n)), 4
    )
    return basis, p_value, discrimination


def item_flag_evaluation(program, stat_basis_applied, p_value, discrimination):
    """First-match-wins; the order of the three tests is normative."""
    if stat_basis_applied == "INSUFFICIENT_DATA":
        return None
    if discrimination < dec(program["min_discrimination"]):
        return "LOW_DISCRIMINATION"
    if p_value > dec(program["max_p_value"]):
        return "TOO_EASY"
    if p_value < dec(program["min_p_value"]):
        return "TOO_HARD"
    return None


# ---------------------------------------------------------------------------
# 3. angoff_cut_score
# ---------------------------------------------------------------------------

def panel_quorum_met(form, program):
    n = len(form["panel_ratings"])
    if n < program["min_panelists"]:
        return False
    if n - 2 * int(program["panel_trim_count"]) < 1:
        return False
    return True


def angoff_cut_score(form, program):
    """Trimmed-mean modified-Angoff cut with a SEM haircut and a final clamp."""
    means = [dec(r["mean_expected_pass_rate"]) for r in form["panel_ratings"]]
    n = len(means)
    trim = int(program["panel_trim_count"])
    ordered_means = sorted(means)              # ascending; ties keep insertion order
    trimmed = ordered_means[trim:n - trim] if trim else ordered_means[:]
    k = len(trimmed)

    trimmed_mean = round_half_up(sum(trimmed, Decimal(0)) / dec(k), 6)
    if k == 1:
        sem = Decimal(0)
    else:
        variance = sum(((m - trimmed_mean) ** 2 for m in trimmed), Decimal(0)) / dec(k - 1)
        sem = round_half_up(variance.sqrt() / dec(k).sqrt(), 6)

    adjusted = trimmed_mean - (dec(program["cut_score_sem_multiplier"]) * sem)
    scored_item_count = len(form["item_ids"]) - len(form["pretest_item_ids"])
    raw = int(round_half_up(adjusted * dec(scored_item_count), 0))
    floor_cut = ceil_int(CUT_FLOOR_RATIO * dec(scored_item_count))
    ceil_cut = floor_int(CUT_CEILING_RATIO * dec(scored_item_count))
    raw_cut_score = min(max(raw, floor_cut), ceil_cut)
    return raw_cut_score, trimmed_mean


# ---------------------------------------------------------------------------
# 4. scaled_score_equating
# ---------------------------------------------------------------------------

def scaled_score_equating(raw_score, cut, total):
    if raw_score >= cut:
        if total == cut:
            scaled = dec(SCALE_MAX)
        else:
            scaled = dec(SCALE_CUT) + (
                dec(raw_score - cut) * dec(SCALE_MAX - SCALE_CUT) / dec(total - cut)
            )
    else:
        if cut == 0:
            scaled = dec(SCALE_CUT)
        else:
            scaled = dec(SCALE_MIN) + (
                dec(raw_score) * dec(SCALE_CUT - SCALE_MIN) / dec(cut)
            )
    scaled_score = min(max(int(round_half_up(scaled, 0)), SCALE_MIN), SCALE_MAX)
    outcome = "PASS" if scaled_score >= SCALE_CUT else "FAIL"
    return scaled_score, outcome


# ---------------------------------------------------------------------------
# 5. ceu_credit_accrual
# ---------------------------------------------------------------------------

def accrual_window(cycle):
    """Inclusive both ends; CARRYOVER_ALLOWED adds a 90-day look-back."""
    if cycle["accrual_basis_snapshot"] == "CARRYOVER_ALLOWED":
        return add_days(cycle["starts_on"], -CARRYOVER_LOOKBACK_DAYS), cycle["ends_on"]
    return cycle["starts_on"], cycle["ends_on"]


def in_accrual_window(cycle, activity_date):
    low, high = accrual_window(cycle)
    return low <= activity_date <= high


def carry_in_credits(cycle, program):
    if cycle["accrual_basis_snapshot"] == "STRICT_CYCLE":
        return Decimal("0.00")
    return min(dec(cycle["carryover_credits_in"]), dec(program["ceu_carryover_max_credits"]))


def ceu_award(activity):
    """Per-activity award, rounded to 2 dp BEFORE any capping."""
    return round_half_up(
        dec(activity["contact_hours"]) * CEU_MULTIPLIER[activity["category"]], 2
    )


def ceu_credit_accrual(cycle, program, activities):
    """Return (credits_applied, {activity_id: credits_counted}) for the cycle."""
    low, high = accrual_window(cycle)
    counted_map = {a["id"]: Decimal("0.00") for a in activities}
    eligible = [
        a for a in activities
        if a["counted"] and low <= a["activity_date"] <= high
    ]
    remaining = dict(CEU_CATEGORY_CAP)
    ordered_eligible = sorted(
        eligible,
        key=lambda a: (a["created_at"], a["activity_date"], dec(a["contact_hours"]), a["_seq"]),
    )
    for activity in ordered_eligible:
        award = ceu_award(activity)
        category = activity["category"]
        if category in remaining:
            granted = min(award, remaining[category])
            remaining[category] = remaining[category] - granted
        else:
            granted = award
        counted_map[activity["id"]] = round_half_up(granted, 2)

    total = sum((counted_map[a["id"]] for a in eligible), Decimal(0))
    credits_applied = round_half_up(total + carry_in_credits(cycle, program), 2)
    return credits_applied, counted_map


# ---------------------------------------------------------------------------
# 6. carryover_computation
# ---------------------------------------------------------------------------

def carryover_computation(cycle, program):
    surplus = dec(cycle["credits_applied"]) - dec(cycle["required_credits"])
    if cycle["accrual_basis_snapshot"] == "STRICT_CYCLE" or surplus <= 0:
        return Decimal("0.00")
    return round_half_up(min(surplus, dec(program["ceu_carryover_max_credits"])), 2)


# ---------------------------------------------------------------------------
# 7. reinstatement_fee_assessment
# ---------------------------------------------------------------------------

def reinstatement_fee_assessment(current_utc, grace_ends_on):
    days_late = max(1, whole_days_between(current_utc, grace_ends_on))
    surcharge = min(days_late * LATE_DAY_RATE_CENTS, MAX_SURCHARGE_CENTS)
    subtotal = BASE_FEE_CENTS + surcharge
    if subtotal <= 30000:
        rate = Decimal("0.02")
    elif subtotal <= 45000:
        rate = Decimal("0.05")
    else:
        rate = Decimal("0.08")
    admin_fee = int(round_half_up(rate * dec(subtotal), 0))
    return subtotal + admin_fee


# ---------------------------------------------------------------------------
# 9. form_retirement_tolerance (integer cross-multiplication, strict >)
# ---------------------------------------------------------------------------

def form_needs_rebuild(retired_item_count, item_count, tolerance_pct):
    return retired_item_count * 100 > int(tolerance_pct) * item_count


# ---------------------------------------------------------------------------
# 12. eligibility_dimension_evaluation
# ---------------------------------------------------------------------------

def education_ok(application, program, current_year):
    if application["education_credential"] not in program["accepted_education_credentials"]:
        return False
    return application["education_completion_year"] >= (
        current_year - int(program["education_recency_years"])
    )


def experience_ok(application, program):
    return application["experience_months"] >= int(program["min_experience_months"])


# ---------------------------------------------------------------------------
# 15. certificate_number_minting
# ---------------------------------------------------------------------------

def certificate_number(credential_code, year, sequence):
    return "%s-%d-%05d" % (credential_code, year, sequence)
