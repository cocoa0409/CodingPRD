"""Domain services: path resolution, serializers, calculations, cascades.

All structural names (headers, envelope fields, error ids, OCC fields) come from
SCAFFOLD.yaml / PRD.md — see those files for provenance.
"""

import math
from datetime import timedelta
from fractions import Fraction

from clock import today_date, now_iso_ms
from db import DB
from errors import (
    err,
    ERR_DISTRICT_NOT_FOUND,
    ERR_SCHOOL_NOT_FOUND,
    ERR_STUDENT_NOT_FOUND,
    ERR_WINDOW_NOT_FOUND,
    ERR_PLAN_NOT_FOUND,
    ERR_MOVEMENT_NOT_FOUND,
    ERR_MEETING_NOT_FOUND,
    ERR_REFERRAL_NOT_FOUND,
    ERR_CATALOG_NOT_FOUND,
    ERR_INTERVENTIONIST_NOT_FOUND,
    ERR_INVALID_REQUEST,
)
from middleware import base_fields, touch, parse_date

# ---- domain constants ----

WINDOW_KINDS = {"FALL", "WINTER", "SPRING"}
SUBJECTS = {"READING", "MATH"}
TIERS = {"TIER_1", "TIER_2", "TIER_3"}
TIER_TARGETS = {"TIER_2", "TIER_3"}
PROBE_FREQUENCIES = {"WEEKLY", "BIWEEKLY"}
SESSION_OUTCOMES = {"DELIVERED", "STUDENT_ABSENT", "STAFF_ABSENT", "CANCELLED"}
SUBGROUP_CODES = ["ELL", "FRL", "IEP", "BLACK", "HISPANIC", "WHITE", "ASIAN", "MULTI"]
SUBGROUP_SET = set(SUBGROUP_CODES)
EXIT_KINDS = {"EXIT_RESPONSIVE", "EXIT_NO_PROGRESS"}
DETERMINE_OUTCOMES = {"ELIGIBLE", "NOT_ELIGIBLE"}

TIER_RANK = {"TIER_1": 1, "TIER_2": 2, "TIER_3": 3}
OPEN_REFERRAL_STATUSES = {"PENDING_CONSENT", "CONSENTED", "EVAL_IN_PROGRESS"}
TERMINAL_PLAN_STATUSES = {
    "EXIT_RESPONSIVE", "EXIT_MOVED", "EXIT_SPED_REFERRAL", "EXIT_NO_PROGRESS", "CANCELLED",
}

WEEKLY_PROBES = 8
BIWEEKLY_PROBES = 4

# =====================================================================
# Serializers (whitelist fields; internal keys are underscore-prefixed)
# =====================================================================

def serialize_district(d):
    return {
        "id": d["id"],
        "name": d["name"],
        "academic_year": d["academic_year"],
        "sped_referral_min_weeks": d["sped_referral_min_weeks"],
        "fidelity_threshold_pct": d["fidelity_threshold_pct"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def serialize_school(s):
    return {
        "id": s["id"],
        "district_id": s["district_id"],
        "name": s["name"],
        "grade_span_low": s["grade_span_low"],
        "grade_span_high": s["grade_span_high"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_window(w):
    return {
        "id": w["id"],
        "school_id": w["school_id"],
        "window_kind": w["window_kind"],
        "opens_on": w["opens_on"],
        "closes_on": w["closes_on"],
        "status": w["status"],
        "screened_student_count": sum(
            1 for sc in DB.screening_scores.values() if sc["window_id"] == w["id"]
        ),
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def serialize_cut_point(c):
    return {
        "id": c["id"],
        "school_id": c["school_id"],
        "window_kind": c["window_kind"],
        "grade_level": c["grade_level"],
        "subject": c["subject"],
        "tier2_max_score": c["tier2_max_score"],
        "tier3_max_score": c["tier3_max_score"],
        "created_at": c["created_at"],
    }


def serialize_student(s):
    return {
        "id": s["id"],
        "school_id": s["school_id"],
        "full_name": s["full_name"],
        "grade_level": s["grade_level"],
        "subgroup_codes": list(s["subgroup_codes"]),
        "current_tier": s["current_tier"],
        "weeks_at_tier3_unresponsive": s["weeks_at_tier3_unresponsive"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_score(sc):
    return {
        "id": sc["id"],
        "window_id": sc["window_id"],
        "student_id": sc["student_id"],
        "subject": sc["subject"],
        "raw_score": sc["raw_score"],
        "risk_band": sc["risk_band"],
        "created_at": sc["created_at"],
    }


def serialize_catalog_entry(c):
    return {
        "id": c["id"],
        "district_id": c["district_id"],
        "title": c["title"],
        "subject": c["subject"],
        "tier_target": c["tier_target"],
        "grade_min": c["grade_min"],
        "grade_max": c["grade_max"],
        "session_minutes": c["session_minutes"],
        "sessions_per_week": c["sessions_per_week"],
        "probe_frequency": c["probe_frequency"],
        "is_active": c["is_active"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_interventionist(i):
    return {
        "id": i["id"],
        "school_id": i["school_id"],
        "full_name": i["full_name"],
        "weekly_minute_capacity": i["weekly_minute_capacity"],
        "committed_minutes_per_week": i["committed_minutes_per_week"],
        "subjects": list(i["subjects"]),
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def serialize_plan(p):
    return {
        "id": p["id"],
        "student_id": p["student_id"],
        "catalog_entry_id": p["catalog_entry_id"],
        "interventionist_id": p["interventionist_id"],
        "tier_at_start": p["tier_at_start"],
        "started_on": p["started_on"],
        "weekly_minute_cost": p["weekly_minute_cost"],
        "probe_due_on": p["probe_due_on"],
        "fidelity_pct": p["fidelity_pct"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_probe(pr):
    return {
        "id": pr["id"],
        "plan_id": pr["plan_id"],
        "administered_on": pr["administered_on"],
        "score": pr["score"],
        "aimline_score": pr["aimline_score"],
        "slope_decision": pr["slope_decision"],
        "created_at": pr["created_at"],
    }


def serialize_session(se):
    return {
        "id": se["id"],
        "plan_id": se["plan_id"],
        "scheduled_on": se["scheduled_on"],
        "minutes": se["minutes"],
        "outcome": se["outcome"],
        "created_at": se["created_at"],
    }


def serialize_movement(m):
    return {
        "id": m["id"],
        "student_id": m["student_id"],
        "from_tier": m["from_tier"],
        "to_tier": m["to_tier"],
        "rationale": m["rationale"],
        "decided_at_meeting_id": m["decided_at_meeting_id"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def serialize_meeting(m):
    return {
        "id": m["id"],
        "school_id": m["school_id"],
        "scheduled_on": m["scheduled_on"],
        "status": m["status"],
        "minuted_movement_count": m["minuted_movement_count"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def serialize_referral(r):
    return {
        "id": r["id"],
        "student_id": r["student_id"],
        "triggered_plan_id": r["triggered_plan_id"],
        "consent_received_on": r["consent_received_on"],
        "evaluation_due_on": r["evaluation_due_on"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


# =====================================================================
# Hierarchical path resolution (PRD §2.4 — left-to-right existence)
# =====================================================================

def resolve_district(district_id):
    d = DB.districts.get(district_id)
    if d is None:
        raise err(ERR_DISTRICT_NOT_FOUND, 404, "districtId does not exist")
    return d


def resolve_school(district_id, school_id):
    resolve_district(district_id)
    s = DB.schools.get(school_id)
    if s is None or s["district_id"] != district_id:
        raise err(ERR_SCHOOL_NOT_FOUND, 404, "schoolId does not exist (within district)")
    return s


def resolve_student(district_id, school_id, student_id):
    resolve_school(district_id, school_id)
    st = DB.students.get(student_id)
    if st is None or st["school_id"] != school_id:
        raise err(ERR_STUDENT_NOT_FOUND, 404, "studentId does not exist (within school)")
    return st


def resolve_window(district_id, school_id, window_id):
    resolve_school(district_id, school_id)
    w = DB.screening_windows.get(window_id)
    if w is None or w["school_id"] != school_id:
        raise err(ERR_WINDOW_NOT_FOUND, 404, "windowId does not exist (within school)")
    return w


def resolve_plan(district_id, school_id, student_id, plan_id):
    resolve_student(district_id, school_id, student_id)
    p = DB.plans.get(plan_id)
    if p is None or p["student_id"] != student_id:
        raise err(ERR_PLAN_NOT_FOUND, 404, "planId does not exist (within student)")
    return p


def resolve_meeting(district_id, school_id, meeting_id):
    resolve_school(district_id, school_id)
    m = DB.team_meetings.get(meeting_id)
    if m is None or m["school_id"] != school_id:
        raise err(ERR_MEETING_NOT_FOUND, 404, "meetingId does not exist (within school)")
    return m


def resolve_movement(district_id, school_id, student_id, movement_id):
    resolve_student(district_id, school_id, student_id)
    m = DB.tier_movements.get(movement_id)
    if m is None or m["student_id"] != student_id:
        raise err(ERR_MOVEMENT_NOT_FOUND, 404, "movementId does not exist (within student)")
    return m


def resolve_referral(district_id, school_id, student_id, referral_id):
    resolve_student(district_id, school_id, student_id)
    r = DB.sped_referrals.get(referral_id)
    if r is None or r["student_id"] != student_id:
        raise err(ERR_REFERRAL_NOT_FOUND, 404, "referralId does not exist (within student)")
    return r


def resolve_catalog_entry(district_id, entry_id):
    resolve_district(district_id)
    c = DB.catalog_entries.get(entry_id)
    if c is None or c["district_id"] != district_id:
        raise err(ERR_CATALOG_NOT_FOUND, 404, "entryId does not exist (within district)")
    return c


def resolve_interventionist(district_id, school_id, interventionist_id):
    resolve_school(district_id, school_id)
    i = DB.interventionists.get(interventionist_id)
    if i is None or i["school_id"] != school_id:
        raise err(ERR_INTERVENTIONIST_NOT_FOUND, 404, "interventionistId does not exist (within school)")
    return i


# =====================================================================
# Logical-clock-driven screening window lifecycle (PRD §2.7, §3.3)
# =====================================================================

def refresh_window_status(w):
    """Apply automatic SCHEDULED→OPEN (clock reaches opens_on) and OPEN→CLOSED
    (clock passes closes_on) transitions. Dates are inclusive on both ends."""
    today = today_date()
    changed = False
    if w["status"] == "SCHEDULED" and today >= parse_date(w["opens_on"]):
        w["status"] = "OPEN"
        changed = True
    if w["status"] == "OPEN" and today > parse_date(w["closes_on"]):
        w["status"] = "CLOSED"
        changed = True
    if changed:
        touch(w)


def get_window_refreshed(window_id):
    w = DB.screening_windows.get(window_id)
    if w is not None:
        refresh_window_status(w)
    return w


# =====================================================================
# Cut points and risk bands (PRD §3.3)
# =====================================================================

def find_cut_point(school_id, window_kind, grade_level, subject):
    """Latest-created cut point matching (school, window_kind, grade, subject)."""
    matches = [
        c for c in DB.cut_points.values()
        if c["school_id"] == school_id
        and c["window_kind"] == window_kind
        and c["grade_level"] == grade_level
        and c["subject"] == subject
    ]
    if not matches:
        return None
    return max(matches, key=lambda c: (c["created_at"], c["_seq"]))


def classify_risk_band(cut, raw_score):
    """CUT_SCORE variant (default, persisted): PRD §3.3."""
    if raw_score <= cut["tier3_max_score"]:
        return "TIER_3"
    if raw_score <= cut["tier2_max_score"]:
        return "TIER_2"
    return "TIER_1"


def latest_scored_window(school_id):
    """Most recently SCORED window at the school (by scoring order)."""
    scored = [
        w for w in DB.screening_windows.values()
        if w["school_id"] == school_id and w["status"] == "SCORED"
    ]
    if not scored:
        return None
    return max(scored, key=lambda w: w.get("_scored_seq", 0))


def student_scores_in_window(student_id, window_id):
    rows = [
        sc for sc in DB.screening_scores.values()
        if sc["window_id"] == window_id and sc["student_id"] == student_id
    ]
    rows.sort(key=lambda sc: (sc["created_at"], sc["_seq"]))
    return rows


def latest_band_for_student(school_id, student_id):
    """Most recently recorded risk_band across all subjects within the school's
    most recently SCORED window (PRD §3.4). None when no such evidence exists."""
    window = latest_scored_window(school_id)
    if window is None:
        return None
    rows = student_scores_in_window(student_id, window["id"])
    if not rows:
        return None
    return rows[-1]["risk_band"]


# =====================================================================
# Interventionist capacity ledger (PRD §2.8)
# =====================================================================

def ledger_adjust(interventionist, delta):
    interventionist["committed_minutes_per_week"] += delta
    touch(interventionist)


def plans_of_student(student_id):
    rows = [p for p in DB.plans.values() if p["student_id"] == student_id]
    rows.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return rows


def movements_of_student(student_id):
    rows = [m for m in DB.tier_movements.values() if m["student_id"] == student_id]
    rows.sort(key=lambda m: (m["created_at"], m["_seq"]))
    return rows


def probes_of_plan(plan_id):
    rows = [pr for pr in DB.probes.values() if pr["plan_id"] == plan_id]
    # Canonical probe order: administered_on ASC, created_at ASC tie-break (PRD §3.6).
    rows.sort(key=lambda pr: (pr["administered_on"], pr["created_at"], pr["_seq"]))
    return rows


def sessions_of_plan(plan_id):
    rows = [se for se in DB.sessions.values() if se["plan_id"] == plan_id]
    rows.sort(key=lambda se: (se["scheduled_on"], se["created_at"], se["_seq"]))
    return rows


def referrals_of_student(student_id):
    rows = [r for r in DB.sped_referrals.values() if r["student_id"] == student_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def has_open_referral(student_id):
    return any(
        r["status"] in OPEN_REFERRAL_STATUSES for r in DB.sped_referrals.values()
        if r["student_id"] == student_id
    )


# =====================================================================
# Tier movements and the ratification cascade (PRD §3.4, §3.7)
# =====================================================================

def propose_movement(student, to_tier, rationale):
    """Create a PROPOSED movement; supersede existing PROPOSED ones; bump student."""
    for m in movements_of_student(student["id"]):
        if m["status"] == "PROPOSED":
            m["status"] = "SUPERSEDED"
            touch(m)
    mv = base_fields()
    mv.update({
        "student_id": student["id"],
        "from_tier": student["current_tier"],
        "to_tier": to_tier,
        "rationale": rationale,
        "decided_at_meeting_id": None,
        "status": "PROPOSED",
    })
    DB.tier_movements[mv["id"]] = mv
    touch(student)
    return mv


def cascade_plan_terminal(plan, terminal_status):
    """System cascade: move an ACTIVE plan to a cascade-only terminal state,
    releasing its committed minutes (PRD §2.8)."""
    iv = DB.interventionists.get(plan["interventionist_id"])
    if iv is not None:
        ledger_adjust(iv, -plan["weekly_minute_cost"])
    plan["status"] = terminal_status
    touch(plan)


def ratify_movement(meeting, movement):
    """PRD §3.7 ratification side effects."""
    student = DB.students[movement["student_id"]]
    movement["status"] = "RATIFIED"
    movement["decided_at_meeting_id"] = meeting["id"]
    touch(movement)

    student["current_tier"] = movement["to_tier"]
    if movement["to_tier"] == "TIER_1":
        student["weeks_at_tier3_unresponsive"] = 0

    # Cascade: ACTIVE plans whose tier_at_start no longer matches -> EXIT_MOVED.
    for p in plans_of_student(student["id"]):
        if p["status"] == "ACTIVE" and p["tier_at_start"] != movement["to_tier"]:
            cascade_plan_terminal(p, "EXIT_MOVED")

    # Other PROPOSED movements for the same student -> SUPERSEDED.
    for m in movements_of_student(student["id"]):
        if m["id"] != movement["id"] and m["status"] == "PROPOSED":
            m["status"] = "SUPERSEDED"
            touch(m)

    meeting["minuted_movement_count"] += 1
    touch(meeting)
    touch(student)


# =====================================================================
# Sped referral creation (manual and probe-cascade) (PRD §3.9)
# =====================================================================

def create_referral_with_cascade(student, triggering_plan):
    """Create a PENDING_CONSENT referral and cascade the ACTIVE plan to
    EXIT_SPED_REFERRAL with minutes released."""
    ref = base_fields()
    ref.update({
        "student_id": student["id"],
        "triggered_plan_id": triggering_plan["id"] if triggering_plan else None,
        "consent_received_on": None,
        "evaluation_due_on": None,
        "status": "PENDING_CONSENT",
    })
    DB.sped_referrals[ref["id"]] = ref
    if triggering_plan is not None and triggering_plan["status"] == "ACTIVE":
        cascade_plan_terminal(triggering_plan, "EXIT_SPED_REFERRAL")
    return ref


# =====================================================================
# Aimline projection (PRD §3.6, calculations.aimline_score)
# =====================================================================

def pin_aimline_params(plan, student, catalog):
    """Pin baseline/goal/total-probes at plan activation.

    baseline = student's first screening raw_score in the plan's subject within the
    school's most recently SCORED window at plan start.
    goal = tier2_max_score of the cut point matching (grade, subject, window_kind
    of that same window).
    """
    school_id = student["school_id"]
    window = latest_scored_window(school_id)
    baseline = None
    goal = None
    if window is not None:
        rows = [
            sc for sc in student_scores_in_window(student["id"], window["id"])
            if sc["subject"] == catalog["subject"]
        ]
        if rows:
            baseline = rows[0]["raw_score"]
        cut = find_cut_point(school_id, window["window_kind"], student["grade_level"], catalog["subject"])
        if cut is not None:
            goal = cut["tier2_max_score"]
    if baseline is None:
        baseline = goal if goal is not None else 0
    if goal is None:
        goal = baseline
    plan["_baseline"] = baseline
    plan["_goal"] = goal
    plan["_total_probes"] = WEEKLY_PROBES if catalog["probe_frequency"] == "WEEKLY" else BIWEEKLY_PROBES


def compute_aimline(plan, k):
    """aimline_score at k-th probe (1-indexed), rounded half-up to integer."""
    baseline = plan["_baseline"]
    goal = plan["_goal"]
    total = plan["_total_probes"]
    val = Fraction(baseline) + Fraction(goal - baseline) * Fraction(k, total)
    # round half-up (toward +infinity on .5): floor(x + 1/2)
    return math.floor(val + Fraction(1, 2))


# =====================================================================
# Slope decision (PRD §3.6, calculations.slope_decision — SLOPE variant)
# =====================================================================

def _least_squares_slope(values):
    """Exact rational least-squares slope over x = 0..k-1."""
    k = len(values)
    if k < 2:
        return Fraction(0)
    x_mean = Fraction(k - 1, 2)
    y_mean = Fraction(sum(values), k)
    num = Fraction(0)
    den = Fraction(0)
    for x in range(k):
        dx = Fraction(x) - x_mean
        num += dx * (Fraction(values[x]) - y_mean)
        den += dx * dx
    if den == 0:
        return Fraction(0)
    return num / den


def compute_slope_decision(plan):
    """Trailing min(4, N) probes including the newest, ordered by administered_on
    ASC with created_at tie-break. RESPONSIVE iff score slope >= aimline slope
    (exact rational comparison, no rounding)."""
    rows = probes_of_plan(plan["id"])
    window_rows = rows[-4:]
    scores = [pr["score"] for pr in window_rows]
    aimlines = [pr["aimline_score"] for pr in window_rows]
    b = _least_squares_slope(scores)
    a = _least_squares_slope(aimlines)
    return "RESPONSIVE" if b >= a else "NON_RESPONSIVE"


# =====================================================================
# Fidelity percentage (PRD §3.6, calculations.fidelity_pct)
# =====================================================================

def compute_fidelity_pct(plan):
    """Per-week-then-average integer truncation, both steps floor (PRD §3.6).

    Step 1: per ISO week W_i = floor(D_i * 100 / N_i).
    Step 2: fidelity_pct = floor(sum(W_i) / weeks-with-sessions).
    """
    sessions = sessions_of_plan(plan["id"])
    if not sessions:
        return plan["fidelity_pct"]
    weeks = {}
    for se in sessions:
        iso = parse_date(se["scheduled_on"]).isocalendar()
        key = (iso[0], iso[1])
        delivered, total = weeks.get(key, (0, 0))
        total += 1
        if se["outcome"] == "DELIVERED":
            delivered += 1
        weeks[key] = (delivered, total)
    weekly = [(d * 100) // n for (d, n) in weeks.values()]
    fid = sum(weekly) // len(weekly)
    return max(0, min(100, fid))


# =====================================================================
# Subgroup outcome index (PRD §3.9, calculations.subgroup_outcome_index)
# =====================================================================

def compute_outcome_report(district_id, window):
    """Per-subgroup outcome index computed on read. Evaluation order pinned:
    raw_index -> subtract small-cohort penalty -> floor -> max(0, .)."""
    school_ids = {
        s["id"] for s in DB.schools.values() if s["district_id"] == district_id
    }
    district_students = [
        st for st in DB.students.values() if st["school_id"] in school_ids
    ]
    report = {}
    for g in SUBGROUP_CODES:
        students_g = [st for st in district_students if g in st["subgroup_codes"]]
        at_risk = []
        for st in students_g:
            rows = student_scores_in_window(st["id"], window["id"])
            if rows and rows[-1]["risk_band"] in ("TIER_2", "TIER_3"):
                at_risk.append((st, rows[-1]["risk_band"]))
        moved_up = [
            st for (st, band) in at_risk
            if TIER_RANK[st["current_tier"]] < TIER_RANK[band]
        ]
        denominator = max(1, len(at_risk))
        raw_index = Fraction(len(moved_up) * 100, denominator)
        size_penalty = 0 if len(students_g) >= 30 else 5
        adjusted = raw_index - size_penalty
        report[g] = max(0, math.floor(adjusted))
    return report
