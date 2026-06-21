"""Entity lookups and computed-field recomputation helpers.

Path/body existence checks raise ERR_NOT_FOUND (PRD §2.5). Recompute helpers
mutate (touch) the affected resource only when a tracked value actually changes,
per PRD §2.4 ("whenever a resource's stored or derived fields change ... that
change is a mutation").
"""
import db
import errors
from services import calc


def _get_or_404(coll, rid):
    obj = coll.get(rid)
    if obj is None:
        raise errors.err(errors.ERR_NOT_FOUND, "resource not found: %s" % rid)
    return obj


def get_facility(rid):
    return _get_or_404(db.facilities, rid)


def get_resident(rid):
    return _get_or_404(db.residents, rid)


def get_pasrr(rid):
    return _get_or_404(db.pasrr_screenings, rid)


def get_qualifying_stay(rid):
    return _get_or_404(db.qualifying_stays, rid)


def get_admission(rid):
    return _get_or_404(db.admissions, rid)


def get_assessment(rid):
    return _get_or_404(db.assessments, rid)


def get_therapy_log(rid):
    return _get_or_404(db.therapy_logs, rid)


def get_care_plan(rid):
    return _get_or_404(db.care_plans, rid)


def get_goal(rid):
    return _get_or_404(db.care_plan_goals, rid)


def get_bed_hold(rid):
    return _get_or_404(db.bed_holds, rid)


def get_claim(rid):
    return _get_or_404(db.claims, rid)


def get_quality_measure(rid):
    return _get_or_404(db.quality_measures, rid)


# ---------------------------------------------------------------------------
# Reverse-reachability collections
# ---------------------------------------------------------------------------
def assessments_for_admission(admission_id):
    return [a for a in db.assessments.values() if a["admission_id"] == admission_id]


def therapy_logs_for_admission(admission_id):
    return [t for t in db.therapy_logs.values() if t["admission_id"] == admission_id]


def care_plans_for_admission(admission_id):
    return [c for c in db.care_plans.values() if c["admission_id"] == admission_id]


def bed_holds_for_admission(admission_id):
    return [b for b in db.bed_holds.values() if b["admission_id"] == admission_id]


def claims_for_admission(admission_id):
    return [c for c in db.claims.values() if c["admission_id"] == admission_id]


def goals_for_plan(care_plan_id):
    return [g for g in db.care_plan_goals.values() if g["care_plan_id"] == care_plan_id]


def claims_for_assessment(assessment_id):
    return [c for c in db.claims.values() if c["driving_assessment_id"] == assessment_id]


def quality_measures_for_facility(facility_id):
    return [q for q in db.quality_measures.values() if q["facility_id"] == facility_id]


# ---------------------------------------------------------------------------
# Active-rate snapshot for pricing
# ---------------------------------------------------------------------------
def active_rates():
    return [r for r in db.pdpm_rates.values() if r.get("active")]


# ---------------------------------------------------------------------------
# Computed-field recomputation
# ---------------------------------------------------------------------------
def recompute_facility_census(facility_id):
    """occupied_bed_count = residents ADMITTED|ON_LEAVE whose active Admission
    is at this facility (PRD §2.9). Mutates the facility iff the count changed.
    """
    facility = db.facilities.get(facility_id)
    if facility is None:
        return
    count = 0
    for adm in db.admissions.values():
        if adm["facility_id"] != facility_id:
            continue
        if adm["status"] not in ("ACTIVE", "NON_COVERED", "DISCHARGE_PLANNED"):
            continue
        res = db.residents.get(adm["resident_id"])
        if res is None:
            continue
        if res["status"] in ("ADMITTED", "ON_LEAVE"):
            count += 1
    if facility.get("occupied_bed_count") != count:
        facility["occupied_bed_count"] = count
        db.touch(facility)


def recompute_open_goal_count(care_plan_id):
    """open_goal_count = goals OPEN|IN_PROGRESS under the plan (PRD §3.7).
    Mutates the plan iff the count changed.
    """
    plan = db.care_plans.get(care_plan_id)
    if plan is None:
        return
    count = sum(
        1 for g in db.care_plan_goals.values()
        if g["care_plan_id"] == care_plan_id and g["status"] in ("OPEN", "IN_PROGRESS")
    )
    if plan.get("open_goal_count") != count:
        plan["open_goal_count"] = count
        db.touch(plan)


def recompute_facility_stars(facility, touch_if_changed=True):
    """Recompute quality_measure_rating + overall_star_rating (PRD §3.1).

    qm_total = sum over the four measure codes of the latest reporting period's
    measure_points; missing measure -> 50 baseline.
    """
    rows = quality_measures_for_facility(facility["id"])
    qm_total = 0
    for code in calc.MEASURE_CODES:
        code_rows = [r for r in rows if r["measure_code"] == code]
        if not code_rows:
            qm_total += calc.QM_BASELINE_MISSING
            continue
        # latest reporting period = most-recently-created row for that code.
        latest = max(code_rows, key=lambda r: r.get("_seq", 0))
        qm_total += latest["measure_points"]
    qm_rating = calc.quality_measure_rating_from_total(qm_total)
    overall = calc.overall_star_rating(
        facility["health_inspection_rating"],
        facility["staffing_rating"],
        qm_rating,
    )
    changed = (
        facility.get("quality_measure_rating") != qm_rating
        or facility.get("overall_star_rating") != overall
    )
    facility["quality_measure_rating"] = qm_rating
    facility["overall_star_rating"] = overall
    if changed and touch_if_changed:
        db.touch(facility)
    return changed
