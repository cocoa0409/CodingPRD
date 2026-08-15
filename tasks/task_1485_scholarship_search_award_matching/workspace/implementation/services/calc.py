"""Calculation rules per PRD §3.4-§3.7 and SCAFFOLD §1.3."""

from decimal import Decimal, ROUND_HALF_UP

ELIGIBILITY_WEIGHTS = {
    "MERIT": (Decimal("0.50"), Decimal("0.10"), Decimal("0.15"), Decimal("0.25")),
    "NEED": (Decimal("0.20"), Decimal("0.50"), Decimal("0.10"), Decimal("0.20")),
    "HYBRID": (Decimal("0.35"), Decimal("0.30"), Decimal("0.15"), Decimal("0.20")),
}

RANKING_WEIGHTS = {
    "MERIT": (Decimal("0.60"), Decimal("0.25"), Decimal("0.15")),
    "NEED": (Decimal("0.25"), Decimal("0.25"), Decimal("0.50")),
    "HYBRID": None,  # exact thirds
}

DEEP_NEED_BONUS = Decimal(5)
SCORE_CAP = Decimal(100)


def q2(x):
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def eligibility_match_score(student, program, gpa_input):
    """PRD §3.4. Returns a Decimal rounded half-up to 2dp.

    STRICT: any hard-criterion miss forces 0.00. HOLISTIC: partial credit.
    """
    min_gpa = program["min_gpa_hundredths"]
    gpa_hard_miss = gpa_input < min_gpa
    if not gpa_hard_miss:
        gpa_component = Decimal(100)
    elif program["match_policy"] == "HOLISTIC" and (min_gpa - gpa_input) <= 20:
        gpa_component = Decimal(50)
    else:
        gpa_component = Decimal(0)

    max_income = program.get("max_household_income_cents")
    if max_income is None:
        income_component = Decimal(100)
        income_hard_miss = False
    else:
        ok = student["household_income_cents"] <= max_income
        income_component = Decimal(100) if ok else Decimal(0)
        income_hard_miss = not ok

    req_state = program.get("required_residency_state")
    if req_state is None:
        residency_component = Decimal(100)
        residency_hard_miss = False
    else:
        ok = student["residency_state"] == req_state
        residency_component = Decimal(100) if ok else Decimal(0)
        residency_hard_miss = not ok

    required_tags = program.get("required_tags") or []
    if not required_tags:
        tags_component = Decimal(100)
        tags_hard_miss = False
    else:
        held = set(student.get("tags") or [])
        hits = sum(1 for t in required_tags if t in held)
        tags_component = Decimal(100 * hits) / Decimal(len(required_tags))
        tags_hard_miss = hits < len(required_tags)

    eligible_majors = program.get("eligible_majors") or []
    major_hard_miss = bool(eligible_majors) and student["intended_major"] not in eligible_majors

    if program["match_policy"] == "STRICT" and (
        gpa_hard_miss or income_hard_miss or residency_hard_miss
        or tags_hard_miss or major_hard_miss
    ):
        return Decimal("0.00")

    w_gpa, w_inc, w_res, w_tags = ELIGIBILITY_WEIGHTS[program["program_type"]]
    base = (w_gpa * gpa_component + w_inc * income_component
            + w_res * residency_component + w_tags * tags_component)
    return q2(base)


def committee_weighted_total(program, student, academic, essay, need):
    """PRD §3.5 per-score weighted total, 2dp half-up, capped at 100."""
    if program["program_type"] == "HYBRID":
        base = (Decimal(academic) + Decimal(essay) + Decimal(need)) / Decimal(3)
    else:
        wa, we, wn = RANKING_WEIGHTS[program["program_type"]]
        base = wa * Decimal(academic) + we * Decimal(essay) + wn * Decimal(need)
    deep_need = False
    max_income = program.get("max_household_income_cents")
    if max_income is not None:
        deep_need = (2 * student["household_income_cents"]) < max_income
    total = base + (DEEP_NEED_BONUS if deep_need else Decimal(0))
    if total > SCORE_CAP:
        total = SCORE_CAP
    return q2(total)


def stacking_cap_cents(student, scope):
    """PRD §3.6: ANNUAL cap = COA - EFC; PER_TERM cap = floor((COA - EFC)/2)."""
    diff = student["cost_of_attendance_cents"] - student["efc_cents"]
    if scope == "PER_TERM":
        return diff // 2  # floor division
    return diff


def split_amounts(amount_cents, term_count):
    """PRD §3.7 pinned rounding: floor base, remainder cents to the EARLIEST terms."""
    base = amount_cents // term_count
    r = amount_cents - base * term_count
    return [base + 1 if i <= r else base for i in range(1, term_count + 1)]
