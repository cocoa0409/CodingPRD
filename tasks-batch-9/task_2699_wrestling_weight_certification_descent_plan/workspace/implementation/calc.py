"""The eight pinned calculations (PRD 2.6, 3.3, 3.5, 3.7, 3.8, 3.9).

All arithmetic runs through decimal.Decimal with ROUND_HALF_UP.  Where the
specification rounds more than once the rounding order is reproduced
literally: an intermediate is rounded *before* it feeds the next step, and no
closed-form shortcut is ever taken.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from store import DB, parse_date, parse_dt, day_start

Q1 = Decimal("0.1")
Q2 = Decimal("0.01")

# Hard iteration ceiling so a degenerate rate (a delta that rounds to 0.0)
# can never spin forever.
MAX_WEEKS = 1000


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def r1(value):
    return float(D(value).quantize(Q1, rounding=ROUND_HALF_UP))


def r2(value):
    return float(D(value).quantize(Q2, rounding=ROUND_HALF_UP))


def smallest_class_at_least(season, value):
    """Smallest ladder member >= value (inclusive comparison), else None."""
    if value is None:
        return None
    target = D(value)
    for candidate in sorted(int(c) for c in (season.get("weight_classes") or [])):
        if D(candidate) >= target:
            return int(candidate)
    return None


# --------------------------------------------------------------------------
# 1. minimum_certified_weight
# --------------------------------------------------------------------------

def body_fat_floor(season, sex):
    if sex == "F":
        return D(season.get("min_body_fat_pct_female"))
    return D(season.get("min_body_fat_pct_male"))


def minimum_certified_weight(season, sex, measured_weight_lbs, body_fat_pct):
    """Returns (lean_body_weight_lbs, minimum_certified_weight_lbs, min_class)."""
    floor_pct = body_fat_floor(season, sex)
    lean = r1(D(measured_weight_lbs) * (Decimal(1) - D(body_fat_pct) / Decimal(100)))
    # The already-rounded lean weight is what enters the division.
    min_cert = r1(D(lean) / (Decimal(1) - floor_pct / Decimal(100)))
    return lean, min_cert, smallest_class_at_least(season, min_cert)


# --------------------------------------------------------------------------
# 2. descent_schedule_projection
# --------------------------------------------------------------------------

def descent_schedule_projection(variant, alpha_weight_lbs, weekly_rate_pct,
                                target_class_lbs):
    """Returns (weights[0..total_weeks], total_weeks, weekly_delta_lbs|None)."""
    alpha = r1(alpha_weight_lbs)
    rate = D(weekly_rate_pct)
    target = D(target_class_lbs)
    weights = [alpha]
    delta = None

    if variant == "LINEAR_RATE":
        # One fixed pound delta, computed once from the untouched baseline.
        delta = r1(D(alpha) * rate / Decimal(100))
        while D(weights[-1]) > target:
            if len(weights) - 1 >= MAX_WEEKS or D(delta) <= 0:
                break
            week = len(weights)
            weights.append(r1(D(alpha) - Decimal(week) * D(delta)))
    else:
        # Compounding: each week's already-rounded value is the next base.
        factor = Decimal(1) - rate / Decimal(100)
        while D(weights[-1]) > target:
            if len(weights) - 1 >= MAX_WEEKS:
                break
            nxt = r1(D(weights[-1]) * factor)
            if D(nxt) >= D(weights[-1]):
                break
            weights.append(nxt)

    total_weeks = len(weights) - 1
    return weights, total_weeks, delta


def rate_admissible(alpha_weight_lbs, target_class_lbs, requested_weeks,
                    weekly_rate_pct):
    """PRD 3.5 admissibility gate.  True when the request is acceptable."""
    required = r1((D(alpha_weight_lbs) - D(target_class_lbs)) / D(requested_weeks))
    permitted = r1(D(alpha_weight_lbs) * D(weekly_rate_pct) / Decimal(100))
    return D(required) <= D(permitted)


# --------------------------------------------------------------------------
# 3. lowest_eligible_class_at_date
# --------------------------------------------------------------------------

def growth_allowance_total(season_id, as_of_date):
    total = Decimal(0)
    for row in DB.growth.values():
        if row.get("season_id") != season_id:
            continue
        eff = parse_date(row.get("effective_date"))
        if eff is not None and eff <= as_of_date:
            total += D(row.get("allowance_lbs"))
    return r1(total)


def governing_plan(wrestler_id):
    """The wrestler's CERTIFIED or BREACHED plan; greatest created_at wins."""
    candidates = [
        p for p in DB.plans.values()
        if p.get("wrestler_id") == wrestler_id
        and p.get("status") in ("CERTIFIED", "BREACHED")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    return candidates[-1]


def schedule_allowable_weight(plan, as_of_date):
    """Step two of the floor derivation."""
    if plan is None:
        return None
    rows = [m for m in DB.milestones.values() if m.get("plan_id") == plan["id"]]
    if not rows:
        return None
    due = []
    for m in rows:
        eff = parse_date(m.get("effective_date"))
        if eff is not None and eff <= as_of_date:
            due.append((eff, m.get("week_index") or 0, m))
    if due:
        due.sort(key=lambda t: (t[0], t[1]))
        return due[-1][2].get("allowable_weight_lbs")
    zero = [m for m in rows if (m.get("week_index") or 0) == 0]
    if zero:
        return zero[0].get("allowable_weight_lbs")
    rows.sort(key=lambda m: m.get("week_index") or 0)
    return rows[0].get("allowable_weight_lbs")


def lowest_eligible_class_at_date(season, wrestler, as_of_date):
    """The four pinned steps of PRD 3.7.  Never iterates."""
    growth = growth_allowance_total(season["id"], as_of_date)
    plan = governing_plan(wrestler["id"])
    schedule = schedule_allowable_weight(plan, as_of_date)

    min_cert = wrestler.get("minimum_certified_weight_lbs")
    if schedule is None:
        floor = min_cert
    elif min_cert is None:
        floor = schedule
    else:
        floor = float(max(D(min_cert), D(schedule)))

    lowest = None
    if floor is not None:
        candidates = [
            int(c) for c in (season.get("weight_classes") or [])
            if D(c) + D(growth) >= D(floor)
        ]
        if candidates:
            candidate = min(candidates)
            hard_floor = wrestler.get("min_weight_class_lbs")
            if hard_floor is None:
                lowest = candidate
            else:
                lowest = max(int(candidate), int(hard_floor))

    return {
        "growth_allowance_lbs": growth,
        "schedule_allowable_weight_lbs": schedule,
        "floor": floor,
        "lowest_eligible_class_lbs": lowest,
        "plan": plan,
    }


# --------------------------------------------------------------------------
# 4. weigh_in_allowance_and_result
# --------------------------------------------------------------------------

def weigh_in_allowance_and_result(season, event, entry, wrestler, day_index,
                                  recorded_weight_lbs):
    event_date = parse_date(event.get("event_date"))
    growth = growth_allowance_total(season["id"], event_date)
    consecutive = r1(D(day_index) * D(event.get("consecutive_day_allowance_lbs")))
    ceiling = D(season.get("max_consecutive_day_allowance_lbs"))
    if D(consecutive) > ceiling:
        consecutive = float(ceiling)
    allowance = r1(D(growth) + D(consecutive))
    class_lbs = D(entry.get("weight_class_lbs"))
    effective_limit = r1(class_lbs + D(allowance))
    recorded = D(recorded_weight_lbs)

    if recorded <= class_lbs:
        result = "PASS"
    elif recorded <= D(effective_limit):
        result = "PASS_WITH_ALLOWANCE"
    else:
        result = "FAIL"

    min_cert = wrestler.get("minimum_certified_weight_lbs")
    below_minimum = bool(min_cert is not None and recorded < D(min_cert))
    return allowance, effective_limit, result, below_minimum


# --------------------------------------------------------------------------
# 5. milestone_evaluation (weigh-in selection half)
# --------------------------------------------------------------------------

def qualifying_weigh_in(wrestler_id, effective_date):
    """The weigh-in that speaks for a milestone: half-open 3-day window."""
    opens = day_start(effective_date)
    closes = day_start(effective_date + timedelta(days=3))
    candidates = []
    for row in DB.weighins.values():
        if row.get("wrestler_id") != wrestler_id:
            continue
        stamp = parse_dt(row.get("recorded_at"))
        if stamp is None:
            continue
        if opens <= stamp < closes:
            candidates.append((stamp, row.get("created_at") or "", row.get("_seq") or 0, row))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1], t[2]))
    best = candidates[-1]
    # Ties on recorded_at are broken by created_at ascending.
    tied = [c for c in candidates if c[0] == best[0]]
    tied.sort(key=lambda t: (t[1], t[2]))
    return tied[0][3]


# --------------------------------------------------------------------------
# 6. audit_discrepancy_score
# --------------------------------------------------------------------------

def audit_discrepancy_score(season, audit):
    samples = audit.get("samples") or []
    sample_count = len(samples)
    deviations = []
    for sample in samples:
        assessment = DB.assessments.get(sample.get("assessment_id"))
        if assessment is None:
            continue
        deviations.append(
            r2(abs(D(sample.get("remeasured_body_fat_pct")) - D(assessment.get("body_fat_pct"))))
        )
    if sample_count < int(season.get("audit_min_sample_count")):
        return None, "INCONCLUSIVE"
    if not deviations:
        return None, "INCONCLUSIVE"
    if audit.get("scoring_variant") == "SAMPLE_MEAN":
        total = Decimal(0)
        for value in deviations:
            total += D(value)
        score = r2(total / D(sample_count))
    else:
        score = float(max(D(v) for v in deviations))
    threshold = D(season.get("audit_fail_threshold_pct"))
    outcome = "FAIL" if D(score) >= threshold else "PASS"
    return score, outcome


# --------------------------------------------------------------------------
# 7. team_compliance_posture
# --------------------------------------------------------------------------

def team_compliance_posture(total):
    total = int(total or 0)
    if total <= 0:
        return "CLEAR"
    if total <= 4:
        return "WATCH"
    return "PROBATION"


# --------------------------------------------------------------------------
# 8. seed_assignment
# --------------------------------------------------------------------------

def seed_rank_key(entry):
    """season_win_count DESC, latest_effective_weight_lbs ASC (nulls last),
    created_at ASC.  The row id is never consulted."""
    weight = entry.get("latest_effective_weight_lbs")
    return (
        -int(entry.get("season_win_count") or 0),
        1 if weight is None else 0,
        D(weight) if weight is not None else Decimal(0),
        entry.get("created_at") or "",
        entry.get("_seq") or 0,
    )


def seed_assignment(pool):
    """Returns [(entry, seed_number)] walking classes in ascending order."""
    assigned = []
    classes = sorted({int(e.get("weight_class_lbs")) for e in pool})
    for class_lbs in classes:
        group = [e for e in pool if int(e.get("weight_class_lbs")) == class_lbs]
        group.sort(key=seed_rank_key)
        for index, entry in enumerate(group, start=1):
            assigned.append((entry, index))
    return assigned
