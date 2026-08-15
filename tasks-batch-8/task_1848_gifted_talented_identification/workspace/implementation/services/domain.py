"""Business logic: calculations, cascades, state-machine side effects."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db


def today():
    return db.today()


def today_str():
    return db.today().isoformat()


def touch(entity):
    """Bump updated_at + version on a full-lifecycle entity."""
    from services.common import now_iso
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# calculations.composite_score (SCAFFOLD §1.3 / PRD §3.4)
# ---------------------------------------------------------------------------

WEIGHT_FIELD = {
    "ABILITY": "ability_weight",
    "ACHIEVEMENT": "achievement_weight",
    "RATING_SCALE": "rating_weight",
    "PORTFOLIO": "portfolio_weight",
}

REQUIRED_MEASURES = {"ABILITY", "ACHIEVEMENT", "RATING_SCALE"}


def compute_composite(case, profile, measures, student_has_sped):
    """Compute per-measure weighted_contribution and the integer composite.

    Pinned rounding order: round each per-measure contribution half-up to 2dp,
    then round the sum of rounded contributions half-up to 0dp.
    Returns (composite_int, variant, {measure_id: contribution}).
    """
    present = {m["measure_type"]: m for m in measures}
    norm = sum(Decimal(str(profile[WEIGHT_FIELD[t]])) for t in present)

    variant = "TWICE_EXCEPTIONAL" if student_has_sped else "STANDARD"

    if variant == "TWICE_EXCEPTIONAL":
        ability = Decimal(str(present["ABILITY"]["percentile"]))
        achievement = Decimal(str(present["ACHIEVEMENT"]["percentile"]))
        top = max(ability, achievement)
        effective = {"ABILITY": top, "ACHIEVEMENT": top}
    else:
        effective = {}

    contributions = {}
    total = Decimal("0")
    for mtype, m in present.items():
        eff = effective.get(mtype, Decimal(str(m["percentile"])))
        w = Decimal(str(profile[WEIGHT_FIELD[mtype]])) / norm
        line = (eff * w).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        contributions[m["id"]] = line
        total += line

    composite = int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return composite, variant, contributions


def cut_determination(composite, variant, profile):
    """calculations.cut_score_determination. Boundaries: >= cut identifies,
    >= floor enters review, else NOT_IDENTIFIED."""
    if variant == "TWICE_EXCEPTIONAL":
        cut = profile["cut_score_2e"]
        floor = profile["review_band_floor_2e"]
    else:
        cut = profile["cut_score"]
        floor = profile["review_band_floor"]
    if composite >= cut:
        return "IDENTIFIED"
    if composite >= floor:
        return "AWAITING_COMMITTEE"
    return "NOT_IDENTIFIED"


# ---------------------------------------------------------------------------
# calculations.exit_score_and_outcome (PRD §3.7)
# ---------------------------------------------------------------------------


def compute_exit_score(growth_percentile, service_rating, teacher_rating):
    score = (
        Decimal(str(growth_percentile)) * Decimal("0.5")
        + Decimal(str(service_rating)) * Decimal("7.5")
        + Decimal(str(teacher_rating)) * Decimal("4.0")
    )
    return float(score.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def band_for_exit_score(exit_score):
    if exit_score >= 70.0:
        return "RETAINED"
    if exit_score >= 50.0:
        return "PROBATION"
    return "EXITED"


def effective_outcome(exit_score, is_on_probation):
    band = band_for_exit_score(exit_score)
    if band == "PROBATION" and is_on_probation:
        return "EXITED"
    return band


# ---------------------------------------------------------------------------
# calculations.quorum_decision (PRD §3.5)
# ---------------------------------------------------------------------------

SEATS = 3
QUALIFY_THRESHOLD = 2
DENY_THRESHOLD = 2


def quorum_outcome(q, d, a):
    """Return DECIDED outcome or None if no threshold locked yet."""
    if q >= QUALIFY_THRESHOLD:
        return "QUALIFY"
    if d >= DENY_THRESHOLD:
        return "DENY"
    if q + d + a >= SEATS:
        return "DENY"  # no-majority default, covers 1-1-1
    return None


def force_conclude_outcome(q, d, a):
    """Force-decide from votes cast so far; no majority => DENY."""
    if q >= QUALIFY_THRESHOLD:
        return "QUALIFY"
    return "DENY"


# ---------------------------------------------------------------------------
# calculations.waitlist_promotion (PRD §3.6)
# ---------------------------------------------------------------------------


def run_waitlist_promotion(site_id, model):
    """Promote exactly one waitlist head per released seat. Empty pool = no-op."""
    candidates = [
        p for p in db.service_placements.values()
        if p["site_id"] == site_id and p["service_model"] == model and p["status"] == "WAITLISTED"
    ]
    if not candidates:
        return
    candidates.sort(key=lambda p: (p.get("waitlisted_at") or "", p.get("created_at", "")))
    head = candidates[0]
    head["status"] = "OFFERED"
    head["offered_on"] = today_str()
    head["accept_by"] = (today() + timedelta(days=30)).isoformat()
    head["waitlisted_at"] = None
    touch(head)


# ---------------------------------------------------------------------------
# Review decide cascade (PRD §3.5)
# ---------------------------------------------------------------------------


def apply_review_decision(review, outcome):
    """Decide a review and cascade to the case + student."""
    review["status"] = "DECIDED"
    review["outcome"] = outcome
    review["decided_on"] = today_str()
    touch(review)

    case = db.gifted_cases.get(review["case_id"])
    if case is None:
        return

    if review["review_kind"] == "BAND_REVIEW":
        case["status"] = "IDENTIFIED" if outcome == "QUALIFY" else "NOT_IDENTIFIED"
    else:  # APPEAL
        case["status"] = "IDENTIFIED" if outcome == "QUALIFY" else "NOT_IDENTIFIED"
    case["decided_on"] = review["decided_on"]
    touch(case)

    if outcome == "QUALIFY":
        student = db.students.get(case["student_id"])
        if student is not None:
            student["gifted_status"] = "IDENTIFIED"
            touch(student)


# ---------------------------------------------------------------------------
# Placement exit cascade (PRD §3.6/§3.7)
# ---------------------------------------------------------------------------


def run_exit_cascade(placement):
    """ACTIVE -> EXITED: end_on, student EXITED, seat release, promotion."""
    placement["status"] = "EXITED"
    placement["end_on"] = today_str()
    touch(placement)

    student = db.students.get(placement["student_id"])
    if student is not None:
        student["gifted_status"] = "EXITED"
        touch(student)

    run_waitlist_promotion(placement["site_id"], placement["service_model"])


# ---------------------------------------------------------------------------
# Clock-set sweeps (PRD §2.4/§3.6/§3.7)
# ---------------------------------------------------------------------------


def run_clock_sweeps():
    """Re-eval activation + offer-expiry sweeps driven by the logical clock."""
    t = today()
    for r in db.re_evaluations.values():
        if r["status"] == "SCHEDULED":
            from services.common import parse_date
            due = datetime_date(r["due_on"])
            if t >= due:
                r["status"] = "IN_REVIEW"
                touch(r)
    for p in db.service_placements.values():
        if p["status"] == "OFFERED":
            accept_by = datetime_date(p["accept_by"])
            if t > accept_by:
                p["status"] = "EXPIRED"
                touch(p)


def datetime_date(s):
    from datetime import datetime as _dt
    return _dt.strptime(s, "%Y-%m-%d").date()
