"""Calculation services: normalization, aggregates, advancement allocation,
scholarship waterfall, mentor recognition.

All numeric work uses Decimal with ROUND_HALF_UP per the PRD:
- per-sheet normalized_score: 3 decimal places, round half up
- project aggregates: 2 decimal places, round half up (normalize first,
  then mean, then round)
- scholarship: integer cents
"""

from decimal import Decimal, ROUND_HALF_UP
import math
import db


# ---------------------------------------------------------------------------
# Normalization (calculation: normalized_score_per_sheet)
# ---------------------------------------------------------------------------

def renormalize_judge_pool(judge_id, fair_edition_id, algorithm):
    """Re-derive normalized_score for every ScoreSheet in this judge's pool
    within the edition whose parent assignment is SUBMITTED.

    Returns the list of affected project ids (whose sheets were re-derived),
    so the caller can recompute every affected project's aggregates.
    """
    # Collect the judge's SUBMITTED-pool sheets within this edition
    pool = []
    for s in db.score_sheets.values():
        if s["judge_id"] != judge_id:
            continue
        asg = db.judging_assignments.get(s["judging_assignment_id"])
        if asg is None or asg["status"] != "SUBMITTED":
            continue
        proj = db.projects.get(s["project_id"])
        if proj is None or proj["fair_edition_id"] != fair_edition_id:
            continue
        pool.append(s)

    if not pool:
        return []

    raws = [s["raw_score"] for s in pool]

    if algorithm == "Z_SCORE":
        mean = Decimal(sum(raws)) / Decimal(len(raws))
        var = sum((Decimal(r) - mean) ** 2 for r in raws) / Decimal(len(raws))
        sd = Decimal(str(math.sqrt(float(var))))
        if sd == 0:
            for s in pool:
                s["normalized_score"] = Decimal("0.000")
        else:
            for s in pool:
                z = (Decimal(s["raw_score"]) - mean) / sd
                s["normalized_score"] = z.quantize(Decimal("0.001"),
                                                   rounding=ROUND_HALF_UP)
    else:  # MIN_MAX
        lo = min(raws)
        hi = max(raws)
        if hi == lo:
            for s in pool:
                s["normalized_score"] = Decimal("0.500")
        else:
            spread = Decimal(hi - lo)
            for s in pool:
                v = (Decimal(s["raw_score"]) - Decimal(lo)) / spread
                s["normalized_score"] = v.quantize(Decimal("0.001"),
                                                   rounding=ROUND_HALF_UP)

    return list({s["project_id"] for s in pool})


# ---------------------------------------------------------------------------
# Project aggregate (calculation: project_aggregate)
# ---------------------------------------------------------------------------

def recompute_project_aggregates(project, edition):
    """Recompute provisional_aggregate / final_aggregate for a project from
    its SUBMITTED sheets' normalized_score values (already at 3dp)."""
    submitted = []
    for a in db.judging_assignments.values():
        if a["project_id"] == project["id"] and a["status"] == "SUBMITTED":
            s = _sheet_for_assignment(a["id"])
            if s is not None and s["normalized_score"] is not None:
                submitted.append(s["normalized_score"])

    count = len(submitted)
    max_j = edition["max_judges_per_project"]
    quorum = -(-(max_j * edition["min_quorum_ratio_pct"]) // 100)  # ceil

    if count >= quorum and count > 0:
        mean = sum(submitted) / Decimal(count)
        project["provisional_aggregate"] = mean.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        project["provisional_aggregate"] = None

    if count == max_j:
        mean = sum(submitted) / Decimal(count)
        project["final_aggregate"] = mean.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        project["final_aggregate"] = None


def _sheet_for_assignment(assignment_id):
    for s in db.score_sheets.values():
        if s["judging_assignment_id"] == assignment_id:
            return s
    return None


# ---------------------------------------------------------------------------
# Advancement allocation (calculation: advancement_allocation)
# ---------------------------------------------------------------------------

def _median_raw(project_id):
    raws = []
    for a in db.judging_assignments.values():
        if a["project_id"] == project_id and a["status"] == "SUBMITTED":
            s = _sheet_for_assignment(a["id"])
            if s is not None:
                raws.append(s["raw_score"])
    if not raws:
        return Decimal(0)
    raws.sort()
    n = len(raws)
    if n % 2 == 1:
        return Decimal(raws[n // 2])
    return (Decimal(raws[n // 2 - 1]) + Decimal(raws[n // 2])) / Decimal(2)


def _submitted_count(project_id):
    return sum(1 for a in db.judging_assignments.values()
               if a["project_id"] == project_id and a["status"] == "SUBMITTED")


def run_advancement_allocation(edition):
    """Rank eligible projects per category and stamp advancement_result/rank.
    Eligible: registration_status CONFIRMED, judging_status JUDGED,
    inspection_status PASSED."""
    eid = edition["id"]

    # Group eligible projects by category
    by_cat = {}
    for p in db.projects.values():
        if p["fair_edition_id"] != eid:
            continue
        if (p["registration_status"] == "CONFIRMED"
                and p["judging_status"] == "JUDGED"
                and p["inspection_status"] == "PASSED"):
            by_cat.setdefault(p["category_id"], []).append(p)

    def rank_key(p):
        # final_aggregate DESC, median raw DESC, submitted count DESC,
        # created_at ASC
        fa = p["final_aggregate"] if p["final_aggregate"] is not None else Decimal("-999999")
        return (
            -fa,                      # DESC
            -_median_raw(p["id"]),    # DESC
            -_submitted_count(p["id"]),  # DESC
            p["created_at"],          # ASC
        )

    at_large_pool = 0
    waitlisted_all = []

    for cat_id, plist in by_cat.items():
        cat = db.categories.get(cat_id)
        slots = cat["advancement_slots"] if cat else 0
        waitlist_depth = max(1, slots // 2)

        ranked = sorted(plist, key=rank_key)
        for idx, p in enumerate(ranked):
            rank = idx + 1
            _touch_project(p)
            p["advancement_rank"] = rank
            if rank <= slots:
                p["advancement_result"] = "ADVANCED"
            elif rank <= slots + waitlist_depth:
                p["advancement_result"] = "WAITLISTED"
                waitlisted_all.append(p)
            else:
                p["advancement_result"] = "NOT_ADVANCED"

        # Unused slots flow into at-large pool
        if len(ranked) < slots:
            at_large_pool += (slots - len(ranked))

    # Distribute at-large slots to highest-final_aggregate WAITLISTED
    # projects across all categories (same tie-break), one extra slot each.
    if at_large_pool > 0 and waitlisted_all:
        waitlisted_all.sort(key=rank_key)
        for p in waitlisted_all[:at_large_pool]:
            _touch_project(p)
            p["advancement_result"] = "ADVANCED"


def _touch_project(p):
    """Cascade touch: refresh updated_at and bump version."""
    p["updated_at"] = db.now_display_iso()
    p["version"] += 1


# ---------------------------------------------------------------------------
# Scholarship waterfall (calculation: scholarship_waterfall)
# ---------------------------------------------------------------------------

_AWARD_CAPS = {
    "GRAND_PRIZE": 400000,
    "CATEGORY_FIRST": 300000,
    "CATEGORY_SECOND": 150000,
    "SPECIAL_TOPIC": 100000,
}

_AWARD_PRECEDENCE = ["GRAND_PRIZE", "CATEGORY_FIRST", "CATEGORY_SECOND",
                     "SPECIAL_TOPIC"]


def run_scholarship_waterfall(edition):
    """Process every PROPOSED award in the edition in fixed precedence order.
    Debit the pool's remaining_cents; confer each award (even at 0)."""
    eid = edition["id"]
    pool = _pool_for_edition(eid)
    if pool is None:
        return

    remaining = pool["remaining_cents"]

    proposed = [a for a in db.awards.values()
                if a["fair_edition_id"] == eid and a["status"] == "PROPOSED"]

    def tier_order(a):
        return _AWARD_PRECEDENCE.index(a["award_type"])

    def within_tier_key(a):
        proj = db.projects.get(a["project_id"])
        fa = proj["final_aggregate"] if proj and proj["final_aggregate"] is not None else Decimal("-999999")
        created = proj["created_at"] if proj else ""
        return (-fa, created)

    for tier in _AWARD_PRECEDENCE:
        tier_awards = [a for a in proposed if a["award_type"] == tier]
        tier_awards.sort(key=within_tier_key)
        cap = _AWARD_CAPS[tier]
        for a in tier_awards:
            alloc = min(cap, remaining)
            if alloc < 0:
                alloc = 0
            a["scholarship_amount_cents"] = alloc
            a["status"] = "CONFERRED"
            a["updated_at"] = db.now_display_iso()
            a["version"] += 1
            remaining -= alloc

    pool["remaining_cents"] = remaining
    pool["updated_at"] = db.now_display_iso()
    pool["version"] += 1


def _pool_for_edition(fair_edition_id):
    for p in db.scholarship_pools.values():
        if p["fair_edition_id"] == fair_edition_id:
            return p
    return None


# ---------------------------------------------------------------------------
# Mentor recognition (calculation: mentor_recognition)
# ---------------------------------------------------------------------------

_POINTS = {
    "GRAND_PRIZE": 8,
    "CATEGORY_FIRST": 4,
    "CATEGORY_SECOND": 2,
    "SPECIAL_TOPIC": 1,
}


def recompute_mentor_recognition(fair_edition_id):
    """Recompute recognition_points (STRICT), leaderboard_points (INCLUSIVE),
    and recognition_tier for every mentor with projects in this edition."""
    # Group projects by mentor within this edition
    mentors_in_edition = set()
    for p in db.projects.values():
        if p["fair_edition_id"] == fair_edition_id:
            mentors_in_edition.add(p["mentor_id"])

    for mid in mentors_in_edition:
        mentor = db.mentors.get(mid)
        if mentor is None:
            continue
        strict = 0
        inclusive_extra = 0
        for p in db.projects.values():
            if p["fair_edition_id"] != fair_edition_id:
                continue
            if p["mentor_id"] != mid:
                continue
            if p["advancement_result"] == "ADVANCED":
                strict += 5
            elif p["advancement_result"] == "WAITLISTED":
                inclusive_extra += 4
            # CONFERRED awards for this project
            for a in db.awards.values():
                if (a["project_id"] == p["id"]
                        and a["fair_edition_id"] == fair_edition_id
                        and a["status"] == "CONFERRED"):
                    strict += _POINTS.get(a["award_type"], 0)

        leaderboard = strict + inclusive_extra
        if strict >= 50:
            tier = "GOLD"
        elif strict >= 25:
            tier = "SILVER"
        elif strict >= 10:
            tier = "BRONZE"
        else:
            tier = "NONE"

        if (mentor["recognition_points"] != strict
                or mentor["leaderboard_points"] != leaderboard
                or mentor["recognition_tier"] != tier):
            mentor["recognition_points"] = strict
            mentor["leaderboard_points"] = leaderboard
            mentor["recognition_tier"] = tier
            mentor["updated_at"] = db.now_display_iso()
            mentor["version"] += 1
