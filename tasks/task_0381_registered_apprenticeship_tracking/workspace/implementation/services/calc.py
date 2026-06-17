"""Business calculations and cascade recomputation (PRD §2.5, §2.6, §2.7, §3.7, §3.8)."""
import math
from decimal import Decimal, ROUND_HALF_UP

import db

PROBATION_WEIGHT = Decimal("0.5")

# Open agreement statuses that consume a ratio slot / count toward active counts.
OPEN_STATUSES = {"REGISTERED", "ACTIVE", "SUSPENDED"}

# Enum declaration order for largest-remainder tie-breaks (PRD §3.2 / scaffold).
GENDER_ORDER = ["MALE", "FEMALE", "NONBINARY", "UNDISCLOSED"]
RACE_ORDER = [
    "HISPANIC",
    "WHITE",
    "BLACK",
    "ASIAN",
    "NATIVE_AMERICAN",
    "PACIFIC_ISLANDER",
    "TWO_OR_MORE",
    "UNDISCLOSED",
]


def _program_wage_steps(program_id):
    steps = [w for w in db.wage_steps.values() if w["program_id"] == program_id]
    steps.sort(key=lambda w: w["step_number"])
    return steps


# --- journeyman_ratio_capacity (PRD §2.6) ---
def recompute_available_slots(program):
    """Recompute and store program.available_apprentice_slots from current capacity.

    Order is fixed: weighted sum -> floor -> subtract active_agreement_count ->
    max(0, .). Does NOT mutate updated_at/version; capacity is derived on read and
    on the transitions that already touch the program.
    """
    sponsor_id = program["sponsor_id"]
    q = sum(
        1
        for j in db.journeyworkers.values()
        if j["sponsor_id"] == sponsor_id and j["status"] == "QUALIFIED"
    )
    p = sum(
        1
        for j in db.journeyworkers.values()
        if j["sponsor_id"] == sponsor_id and j["status"] == "PROBATIONARY"
    )
    ratio = program["journeyman_ratio"]
    weighted = (
        Decimal(q) * Decimal(ratio)
        + Decimal(p) * Decimal(ratio) * PROBATION_WEIGHT
    )
    ratio_capacity = int(math.floor(weighted))
    slots = max(0, ratio_capacity - program["active_agreement_count"])
    program["available_apprentice_slots"] = slots
    return slots


# --- wage_step_determination (PRD §3.7) ---
def compute_wage_step(agreement, program):
    steps = _program_wage_steps(program["id"])
    if not steps:
        return 1
    ctype = program["completion_type"]
    if ctype in ("HOURS_BASED", "HYBRID"):
        qualifying = [
            s["step_number"]
            for s in steps
            if s["ojt_hours_threshold"] <= agreement["ojt_hours_completed"]
        ]
        if not qualifying:
            return 1
        return max(qualifying)
    # COMPETENCY_BASED
    top = max(s["step_number"] for s in steps)
    count = agreement["milestones_attained_count"]
    return max(1, min(count, top))


# --- current_hourly_wage (PRD §2.7) ---
def compute_hourly_wage_cents(agreement, program):
    steps = _program_wage_steps(program["id"])
    step = next(
        (s for s in steps if s["step_number"] == agreement["current_wage_step"]),
        None,
    )
    if step is None:
        return 0
    base = Decimal(program["base_journeyworker_wage_cents"])
    pct = Decimal(str(step["wage_pct"]))
    product = base * pct
    return int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- completion_eligibility (PRD §3.7) ---
def compute_completion_eligible(agreement, program):
    ojt_ok = agreement["ojt_hours_completed"] >= program["ojt_hours_required"]
    rti_ok = agreement["rti_hours_completed"] >= program["rti_hours_required"]

    required_milestones = [
        m
        for m in db.milestones.values()
        if m["program_id"] == program["id"] and m.get("required_for_completion", True)
    ]
    required_ids = {m["id"] for m in required_milestones}
    approved_required = sum(
        1
        for a in db.milestone_attainments.values()
        if a["agreement_id"] == agreement["id"]
        and a["status"] == "APPROVED"
        and a["milestone_id"] in required_ids
    )
    comp_ok = approved_required == len(required_milestones)

    ctype = program["completion_type"]
    if ctype == "HOURS_BASED":
        return ojt_ok and rti_ok
    if ctype == "COMPETENCY_BASED":
        return comp_ok and rti_ok
    # HYBRID
    return ojt_ok and rti_ok and comp_ok


def recompute_agreement_derived(agreement):
    """Run the cascade chain: wage step -> wage snapshot -> completion eligibility.

    The caller is responsible for first updating the hours/competency totals.
    Returns True if any derived field changed.
    """
    program = db.programs[agreement["program_id"]]
    before = (
        agreement["current_wage_step"],
        agreement["current_hourly_wage_cents"],
        agreement["completion_eligible"],
    )
    agreement["current_wage_step"] = compute_wage_step(agreement, program)
    agreement["current_hourly_wage_cents"] = compute_hourly_wage_cents(agreement, program)
    agreement["completion_eligible"] = compute_completion_eligible(agreement, program)
    after = (
        agreement["current_wage_step"],
        agreement["current_hourly_wage_cents"],
        agreement["completion_eligible"],
    )
    return before != after


# --- EEO completion rate (PRD §3.8) ---
def _cohort_agreements(program_id, cohort_basis):
    ags = [a for a in db.agreements.values() if a["program_id"] == program_id]
    if cohort_basis == "REGISTERED_COHORT":
        return [a for a in ags if a["status"] != "DRAFT"]
    # ACTIVE_COHORT
    return [a for a in ags if a["status"] in ("ACTIVE", "COMPLETED")]


def compute_completion_rate(program_id, cohort_basis):
    """Returns (total_apprentices, completed_count, completion_rate_pct)."""
    cohort = _cohort_agreements(program_id, cohort_basis)
    total = len(cohort)
    completed = sum(
        1
        for a in db.agreements.values()
        if a["program_id"] == program_id and a["status"] == "COMPLETED"
    )
    if total == 0:
        rate = 0.0
    else:
        raw = Decimal(completed) / Decimal(total) * Decimal(100)
        rate = float(raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return total, completed, rate


# --- EEO largest-remainder distribution (PRD §3.8) ---
def _distinct_cohort_apprentices(program_id, cohort_basis):
    cohort = _cohort_agreements(program_id, cohort_basis)
    seen = {}
    for a in cohort:
        ap_id = a["apprentice_id"]
        if ap_id in seen:
            continue
        ap = db.apprentices.get(ap_id)
        if ap is not None:
            seen[ap_id] = ap
    return list(seen.values())


def largest_remainder(counts_by_category, category_order):
    """Whole-percent largest-remainder allocation summing to 100.

    counts_by_category: dict category -> count over the cohort.
    Categories with zero count are still present in the output (value 0) only if
    they appear in category_order? No — PRD computes over categories present in
    the data. We include every category that has count > 0; categories with 0
    count get 0% naturally. To keep output stable we emit the categories that
    actually occur in the cohort.
    """
    n = sum(counts_by_category.values())
    if n == 0:
        return {}
    raw = {}
    floors = {}
    for cat, cnt in counts_by_category.items():
        share = Decimal(cnt) / Decimal(n) * Decimal(100)
        raw[cat] = share
        floors[cat] = int(math.floor(share))
    remainder_units = 100 - sum(floors.values())

    # Order categories by descending fractional remainder; ties by declaration order.
    def order_index(cat):
        try:
            return category_order.index(cat)
        except ValueError:
            return len(category_order)

    ordered = sorted(
        counts_by_category.keys(),
        key=lambda c: (-(raw[c] - Decimal(floors[c])), order_index(c)),
    )
    result = dict(floors)
    i = 0
    while remainder_units > 0 and ordered:
        cat = ordered[i % len(ordered)]
        result[cat] += 1
        remainder_units -= 1
        i += 1
    return result


def compute_distributions(program_id, cohort_basis):
    apprentices = _distinct_cohort_apprentices(program_id, cohort_basis)
    gender_counts = {}
    race_counts = {}
    veteran_count = 0
    disability_count = 0
    for ap in apprentices:
        gender_counts[ap["gender"]] = gender_counts.get(ap["gender"], 0) + 1
        race_counts[ap["race_ethnicity"]] = race_counts.get(ap["race_ethnicity"], 0) + 1
        if ap.get("is_veteran"):
            veteran_count += 1
        if ap.get("has_disability"):
            disability_count += 1
    gender_dist = largest_remainder(gender_counts, GENDER_ORDER)
    race_dist = largest_remainder(race_counts, RACE_ORDER)
    return gender_dist, race_dist, veteran_count, disability_count
