"""Composite setup helpers for MTSS tests.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints: the harness restarts the server before each test, so nothing is
carried over. Setup calls use the lenient get_success_data validator so a
failed precondition surfaces as a clear "Setup failed" error.

Version-bearing writes (plan create, propose, ratify, pause/resume/exit/cancel)
always re-read the entity's current version immediately before the write, per
the optimistic-concurrency rules in PRD §2.9.
"""
import datetime

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as _default_api
from .constants import (
    CLOCK_IN_FALL_WINDOW,
    CLOCK_IN_WINTER_WINDOW,
    FALL_WINDOW_CLOSES,
    FALL_WINDOW_OPENS,
    WINTER_WINDOW_CLOSES,
    WINTER_WINDOW_OPENS,
)
from .factories import (
    create_benchmark_cut_point_payload,
    create_catalog_entry_payload,
    create_district_payload,
    create_interventionist_payload,
    create_plan_payload,
    create_school_payload,
    create_screening_window_payload,
    create_student_payload,
    create_team_meeting_payload,
    propose_tier_movement_payload,
    ratify_payload,
    record_probe_payload,
    record_screening_score_payload,
    record_session_payload,
)
from .test_users import TEST_USERS, make_interventionist_role_headers

ADMIN = TEST_USERS["platform_admin_headers"]
COORD = TEST_USERS["district_coordinator_headers"]
REGISTRAR = TEST_USERS["school_registrar_headers"]
TEACHER = TEST_USERS["teacher_headers"]
LEAD = TEST_USERS["team_lead_headers"]
SPED = TEST_USERS["sped_director_headers"]


def _api(api):
    return api if api is not None else _default_api


# ---------------------------------------------------------------------------
# Primitive creators
# ---------------------------------------------------------------------------

def set_clock(api, to_iso8601):
    api = _api(api)
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


def create_district(api, name="District D", sped_referral_min_weeks=None,
                    fidelity_threshold_pct=None):
    api = _api(api)
    overrides = {}
    if sped_referral_min_weeks is not None:
        overrides["sped_referral_min_weeks"] = sped_referral_min_weeks
    if fidelity_threshold_pct is not None:
        overrides["fidelity_threshold_pct"] = fidelity_threshold_pct
    return get_success_data(api.create_district(
        create_district_payload(name=name, **overrides), ADMIN))


def create_school(api, district_id, name="School S", grade_span_low=3,
                  grade_span_high=5):
    api = _api(api)
    return get_success_data(api.create_school(
        district_id,
        create_school_payload(name=name, grade_span_low=grade_span_low,
                              grade_span_high=grade_span_high),
        ADMIN))


def setup_district_school(api, district_name="District D", school_name="School S",
                          grade_span_low=3, grade_span_high=5,
                          sped_referral_min_weeks=None):
    """Create a district plus one school. Returns (district, school)."""
    api = _api(api)
    district = create_district(api, name=district_name,
                               sped_referral_min_weeks=sped_referral_min_weeks)
    school = create_school(api, district["id"], name=school_name,
                           grade_span_low=grade_span_low,
                           grade_span_high=grade_span_high)
    return district, school


def define_cut_point(api, district_id, school_id, window_kind="FALL", grade_level=3,
                     subject="READING", tier2_max_score=100, tier3_max_score=70):
    api = _api(api)
    return get_success_data(api.create_benchmark_cut_point(
        district_id, school_id,
        create_benchmark_cut_point_payload(
            window_kind=window_kind, grade_level=grade_level, subject=subject,
            tier2_max_score=tier2_max_score, tier3_max_score=tier3_max_score),
        COORD))


def create_screening_window(api, district_id, school_id, window_kind="FALL",
                            opens_on=FALL_WINDOW_OPENS,
                            closes_on=FALL_WINDOW_CLOSES):
    api = _api(api)
    return get_success_data(api.create_screening_window(
        district_id, school_id,
        create_screening_window_payload(window_kind=window_kind, opens_on=opens_on,
                                        closes_on=closes_on),
        COORD))


def enroll_student(api, district_id, school_id, full_name="Student", grade_level=3,
                   subgroup_codes=None):
    api = _api(api)
    overrides = {}
    if subgroup_codes is not None:
        overrides["subgroup_codes"] = list(subgroup_codes)
    return get_success_data(api.create_student(
        district_id, school_id,
        create_student_payload(full_name=full_name, grade_level=grade_level,
                               **overrides),
        REGISTRAR))


def record_score(api, district_id, school_id, window_id, student_id,
                 subject="READING", raw_score=80):
    """Record a screening score as a Teacher. Returns the ScreeningScore row."""
    api = _api(api)
    return get_success_data(api.record_screening_score(
        district_id, school_id, window_id,
        record_screening_score_payload(student_id, subject=subject,
                                       raw_score=raw_score),
        TEACHER))


def close_window(api, district_id, school_id, window_id):
    api = _api(api)
    return get_success_data(api.close_screening_window(
        district_id, school_id, window_id, COORD))


def score_window(api, district_id, school_id, window_id):
    api = _api(api)
    return get_success_data(api.score_screening_window(
        district_id, school_id, window_id, COORD))


def create_team_meeting(api, district_id, school_id, scheduled_on="2026-08-06"):
    api = _api(api)
    return get_success_data(api.create_team_meeting(
        district_id, school_id, create_team_meeting_payload(scheduled_on), LEAD))


def convene_meeting(api, district_id, school_id, meeting_id):
    api = _api(api)
    return get_success_data(api.convene_team_meeting(
        district_id, school_id, meeting_id, LEAD))


def get_student(api, district_id, school_id, student_id):
    api = _api(api)
    return get_success_data(api.get_student(district_id, school_id, student_id, LEAD))


def get_plan(api, district_id, school_id, student_id, plan_id):
    api = _api(api)
    return get_success_data(api.get_plan(
        district_id, school_id, student_id, plan_id, LEAD))


def get_interventionist(api, district_id, school_id, interventionist_id):
    api = _api(api)
    return get_success_data(api.get_interventionist(
        district_id, school_id, interventionist_id, LEAD))


def list_movements(api, district_id, school_id, student_id, status=None):
    api = _api(api)
    params = {"status": status} if status else None
    data = get_success_data(api.list_tier_movements(
        district_id, school_id, student_id, LEAD, params=params))
    assert isinstance(data, list), f"Expected movement list, got {type(data)}"
    return data


def first_proposed_movement(api, district_id, school_id, student_id):
    """Return the student's single currently-PROPOSED movement."""
    proposed = list_movements(api, district_id, school_id, student_id,
                              status="PROPOSED")
    assert len(proposed) == 1, (
        f"Expected exactly one PROPOSED movement, got {len(proposed)}")
    return proposed[0]


def ratify_movement(api, district_id, school_id, meeting_id, movement_id,
                    student_id):
    """Ratify a movement, threading the student's current version (PRD §2.9)."""
    api = _api(api)
    student = get_student(api, district_id, school_id, student_id)
    return get_success_data(api.ratify_movement(
        district_id, school_id, meeting_id,
        ratify_payload(movement_id, student["version"]), LEAD))


def propose_movement(api, district_id, school_id, student_id, to_tier,
                     rationale="proposal"):
    """Propose a tier movement, threading the student's current version."""
    api = _api(api)
    student = get_student(api, district_id, school_id, student_id)
    return get_success_data(api.propose_tier_movement(
        district_id, school_id, student_id,
        propose_tier_movement_payload(to_tier, rationale, student["version"]),
        LEAD))


# ---------------------------------------------------------------------------
# Tier-1: screening chain producing a ratified tier (screening evidence path)
# ---------------------------------------------------------------------------

def setup_student_with_ratified_tier(api, target_tier="TIER_2", raw_score=None,
                                     grade_level=3, subject="READING",
                                     window_kind="FALL",
                                     opens_on=FALL_WINDOW_OPENS,
                                     closes_on=FALL_WINDOW_CLOSES,
                                     clock_in_window=CLOCK_IN_FALL_WINDOW,
                                     tier2_max_score=100, tier3_max_score=70,
                                     sped_referral_min_weeks=None,
                                     subgroup_codes=None,
                                     full_name="Student",
                                     grade_span_low=3, grade_span_high=5):
    """District + school + cut point + window; student screens into `target_tier`'s
    band, the window is closed and scored, and the auto-proposed movement is
    ratified at a convened meeting. Returns a context dict.

    Default raw_score: 80 lands at TIER_2 with the default cuts (100/70);
    50 lands at TIER_3.
    """
    api = _api(api)
    if raw_score is None:
        raw_score = 80 if target_tier == "TIER_2" else 50
    district, school = setup_district_school(
        api, grade_span_low=grade_span_low, grade_span_high=grade_span_high,
        sped_referral_min_weeks=sped_referral_min_weeks)
    d_id, s_id = district["id"], school["id"]
    cut_point = define_cut_point(api, d_id, s_id, window_kind=window_kind,
                                 grade_level=grade_level, subject=subject,
                                 tier2_max_score=tier2_max_score,
                                 tier3_max_score=tier3_max_score)
    window = create_screening_window(api, d_id, s_id, window_kind=window_kind,
                                     opens_on=opens_on, closes_on=closes_on)
    set_clock(api, clock_in_window)
    student = enroll_student(api, d_id, s_id, full_name=full_name,
                             grade_level=grade_level, subgroup_codes=subgroup_codes)
    record_score(api, d_id, s_id, window["id"], student["id"], subject=subject,
                 raw_score=raw_score)
    close_window(api, d_id, s_id, window["id"])
    score_window(api, d_id, s_id, window["id"])
    meeting = create_team_meeting(api, d_id, s_id)
    convene_meeting(api, d_id, s_id, meeting["id"])
    movement = first_proposed_movement(api, d_id, s_id, student["id"])
    ratify_movement(api, d_id, s_id, meeting["id"], movement["id"], student["id"])
    student = get_student(api, d_id, s_id, student["id"])
    assert student["current_tier"] == target_tier, (
        f"Setup failed: student at {student['current_tier']}, expected {target_tier}")
    return {
        "district": district,
        "school": school,
        "cut_point": cut_point,
        "window": window,
        "student": student,
        "movement": movement,
        "meeting": meeting,
    }


def add_second_window_screening(api, ctx, raw_score=60, window_kind="WINTER",
                                opens_on=WINTER_WINDOW_OPENS,
                                closes_on=WINTER_WINDOW_CLOSES,
                                clock_in_window=CLOCK_IN_WINTER_WINDOW,
                                tier2_max_score=100, tier3_max_score=70,
                                subject="READING"):
    """Run a second screening window for the same student and score it, so the
    student's latest screening band reflects the new window. Returns the window."""
    api = _api(api)
    d_id, s_id = ctx["district"]["id"], ctx["school"]["id"]
    grade_level = ctx["student"]["grade_level"]
    define_cut_point(api, d_id, s_id, window_kind=window_kind,
                     grade_level=grade_level, subject=subject,
                     tier2_max_score=tier2_max_score,
                     tier3_max_score=tier3_max_score)
    window = create_screening_window(api, d_id, s_id, window_kind=window_kind,
                                     opens_on=opens_on, closes_on=closes_on)
    set_clock(api, clock_in_window)
    record_score(api, d_id, s_id, window["id"], ctx["student"]["id"],
                 subject=subject, raw_score=raw_score)
    close_window(api, d_id, s_id, window["id"])
    score_window(api, d_id, s_id, window["id"])
    return window


def setup_students_with_ratified_tiers(api, raw_scores, grade_level=3,
                                       subject="READING", tier2_max_score=100,
                                       tier3_max_score=70,
                                       sped_referral_min_weeks=None):
    """One district/school/window; each entry in `raw_scores` is a student who is
    screened, then has their auto-proposed movement ratified at a single convened
    meeting. Returns a context dict with a `students` list (post-ratify)."""
    api = _api(api)
    district, school = setup_district_school(
        api, sped_referral_min_weeks=sped_referral_min_weeks)
    d_id, s_id = district["id"], school["id"]
    define_cut_point(api, d_id, s_id, window_kind="FALL", grade_level=grade_level,
                     subject=subject, tier2_max_score=tier2_max_score,
                     tier3_max_score=tier3_max_score)
    window = create_screening_window(api, d_id, s_id, window_kind="FALL")
    set_clock(api, CLOCK_IN_FALL_WINDOW)
    students = [enroll_student(api, d_id, s_id, full_name=f"Student {i}",
                               grade_level=grade_level)
                for i in range(len(raw_scores))]
    for student, raw in zip(students, raw_scores):
        record_score(api, d_id, s_id, window["id"], student["id"],
                     subject=subject, raw_score=raw)
    close_window(api, d_id, s_id, window["id"])
    score_window(api, d_id, s_id, window["id"])
    meeting = create_team_meeting(api, d_id, s_id)
    convene_meeting(api, d_id, s_id, meeting["id"])
    movements = []
    for student in students:
        movement = first_proposed_movement(api, d_id, s_id, student["id"])
        movements.append(movement)
        ratify_movement(api, d_id, s_id, meeting["id"], movement["id"],
                        student["id"])
    students = [get_student(api, d_id, s_id, st["id"]) for st in students]
    return {"district": district, "school": school, "window": window,
            "meeting": meeting, "students": students, "movements": movements}


# ---------------------------------------------------------------------------
# Tier-2: catalog, interventionist, and an ACTIVE plan
# ---------------------------------------------------------------------------

def add_catalog_entry(api, district_id, title="Read Naturally", subject="READING",
                      tier_target="TIER_2", grade_min=3, grade_max=5,
                      session_minutes=30, sessions_per_week=3,
                      probe_frequency="WEEKLY", is_active=None):
    api = _api(api)
    overrides = {}
    if is_active is not None:
        overrides["is_active"] = is_active
    return get_success_data(api.create_catalog_entry(
        district_id,
        create_catalog_entry_payload(
            title=title, subject=subject, tier_target=tier_target,
            grade_min=grade_min, grade_max=grade_max,
            session_minutes=session_minutes, sessions_per_week=sessions_per_week,
            probe_frequency=probe_frequency, **overrides),
        COORD))


def add_interventionist(api, district_id, school_id, full_name="Interventionist I",
                        weekly_minute_capacity=600, subjects=("READING",)):
    api = _api(api)
    return get_success_data(api.create_interventionist(
        district_id, school_id,
        create_interventionist_payload(full_name=full_name,
                                       weekly_minute_capacity=weekly_minute_capacity,
                                       subjects=list(subjects)),
        REGISTRAR))


def create_plan(api, district_id, school_id, student_id, catalog_entry_id,
                interventionist_id):
    """Start a plan as TeamLead, threading the student's current version."""
    api = _api(api)
    student = get_student(api, district_id, school_id, student_id)
    return get_success_data(api.create_plan(
        district_id, school_id, student_id,
        create_plan_payload(catalog_entry_id, interventionist_id,
                            student["version"]),
        LEAD))


def setup_active_plan(api, tier="TIER_2", raw_score=None, probe_frequency="WEEKLY",
                      session_minutes=30, sessions_per_week=3,
                      weekly_minute_capacity=600, sped_referral_min_weeks=None,
                      tier2_max_score=100, tier3_max_score=70, grade_level=3,
                      subject="READING", full_name="Student"):
    """Full chain: ratified-tier student + catalog entry + interventionist +
    ACTIVE plan. Returns a context dict with plan, catalog_entry, interventionist."""
    api = _api(api)
    ctx = setup_student_with_ratified_tier(
        api, target_tier=tier, raw_score=raw_score, grade_level=grade_level,
        subject=subject, sped_referral_min_weeks=sped_referral_min_weeks,
        tier2_max_score=tier2_max_score, tier3_max_score=tier3_max_score,
        full_name=full_name)
    d_id, s_id = ctx["district"]["id"], ctx["school"]["id"]
    catalog_entry = add_catalog_entry(
        api, d_id, subject=subject, tier_target=tier, grade_min=3, grade_max=5,
        session_minutes=session_minutes, sessions_per_week=sessions_per_week,
        probe_frequency=probe_frequency)
    interventionist = add_interventionist(
        api, d_id, s_id, weekly_minute_capacity=weekly_minute_capacity,
        subjects=(subject,))
    plan = create_plan(api, d_id, s_id, ctx["student"]["id"],
                       catalog_entry["id"], interventionist["id"])
    assert plan["status"] == "ACTIVE", f"Setup failed: plan is {plan['status']}"
    ctx.update({"catalog_entry": catalog_entry, "interventionist": interventionist,
                "plan": plan})
    return ctx


# ---------------------------------------------------------------------------
# Tier-3: probe and session drivers
# ---------------------------------------------------------------------------

def interventionist_headers_for(ctx):
    """Ownership-correct headers for the plan's interventionist (PRD §2.1)."""
    return make_interventionist_role_headers(ctx["interventionist"]["id"])


def record_probe(api, ctx, administered_on, score):
    """Record a probe as the plan's interventionist. Caller manages the clock."""
    api = _api(api)
    return get_success_data(api.record_probe(
        ctx["district"]["id"], ctx["school"]["id"], ctx["student"]["id"],
        ctx["plan"]["id"],
        record_probe_payload(administered_on, score),
        interventionist_headers_for(ctx)))


def _plus_days(iso_date, days):
    d = datetime.date.fromisoformat(iso_date)
    return (d + datetime.timedelta(days=days)).isoformat()


def record_weekly_probes(api, ctx, scores, first_date="2026-08-12"):
    """Record WEEKLY-cadence probes, stepping the logical clock seven days per
    probe so each lands on or after probe_due_on (PRD §3.6). Returns the probes."""
    api = _api(api)
    probes = []
    for i, score in enumerate(scores):
        date = _plus_days(first_date, 7 * i)
        set_clock(api, f"{date}T00:00:00Z")
        probes.append(record_probe(api, ctx, date, score))
    return probes


def record_biweekly_probes(api, ctx, scores, first_date="2026-08-19"):
    """Record BIWEEKLY-cadence probes, stepping the clock fourteen days per probe."""
    api = _api(api)
    probes = []
    for i, score in enumerate(scores):
        date = _plus_days(first_date, 14 * i)
        set_clock(api, f"{date}T00:00:00Z")
        probes.append(record_probe(api, ctx, date, score))
    return probes


def list_referrals(api, ctx, status=None):
    api = _api(api)
    params = {"status": status} if status else None
    data = get_success_data(api.list_sped_referrals(
        ctx["district"]["id"], ctx["school"]["id"], ctx["student"]["id"],
        LEAD, params=params))
    assert isinstance(data, list)
    return data


def probe_until_sped_referral(api, ctx, max_probes, score=50,
                              first_date="2026-08-12"):
    """Record flat-score (non-responsive) probes one at a time, stopping as soon
    as the system has auto-created a referral. Never probes a plan that has
    already exited. Returns the referral list (asserted non-empty by callers).

    Robust to the single-probe trailing-window reading of the slope rule: the
    loop continues until the referral appears, up to max_probes probes.
    """
    api = _api(api)
    referrals = list_referrals(api, ctx)
    sent = 0
    while not referrals and sent < max_probes:
        date = _plus_days(first_date, 7 * sent)
        set_clock(api, f"{date}T00:00:00Z")
        record_probe(api, ctx, date, score)
        sent += 1
        referrals = list_referrals(api, ctx)
    return referrals


def record_session(api, ctx, scheduled_on, minutes=30, outcome="DELIVERED"):
    """Record a session as the plan's interventionist."""
    api = _api(api)
    return get_success_data(api.record_session(
        ctx["district"]["id"], ctx["school"]["id"], ctx["student"]["id"],
        ctx["plan"]["id"],
        record_session_payload(scheduled_on, minutes=minutes, outcome=outcome),
        interventionist_headers_for(ctx)))


def pause_plan(api, ctx):
    """Pause the plan, threading its current version. Returns the plan."""
    api = _api(api)
    plan = get_plan(api, ctx["district"]["id"], ctx["school"]["id"],
                    ctx["student"]["id"], ctx["plan"]["id"])
    return get_success_data(api.pause_plan(
        ctx["district"]["id"], ctx["school"]["id"], ctx["student"]["id"],
        plan["id"], {"expected_plan_version": plan["version"]}, LEAD))


def resume_plan(api, ctx):
    """Resume the plan, threading its current version. Returns the plan."""
    api = _api(api)
    plan = get_plan(api, ctx["district"]["id"], ctx["school"]["id"],
                    ctx["student"]["id"], ctx["plan"]["id"])
    return get_success_data(api.resume_plan(
        ctx["district"]["id"], ctx["school"]["id"], ctx["student"]["id"],
        plan["id"], {"expected_plan_version": plan["version"]}, LEAD))


def committed_minutes(api, ctx):
    """Current committed_minutes_per_week of the context's interventionist."""
    api = _api(api)
    return get_interventionist(api, ctx["district"]["id"], ctx["school"]["id"],
                               ctx["interventionist"]["id"])[
        "committed_minutes_per_week"]


# ---------------------------------------------------------------------------
# Tier-5: outcome-report cohort (PRD §3.9)
# ---------------------------------------------------------------------------

def _ratify_movements_for_students(api, d_id, s_id, meeting_id, students):
    for student in students:
        movement = first_proposed_movement(api, d_id, s_id, student["id"])
        ratify_movement(api, d_id, s_id, meeting_id, movement["id"], student["id"])


def build_outcome_report_cohort(api):
    """Build the district cohort for the subgroup outcome index (PRD §3.9):

    - ELL: 35 enrolled (>= small-cohort threshold, no penalty); 10 at-risk in the
      FALL window; 4 of them moved up to TIER_1 via plan-outcome evidence.
    - BLACK: 20 enrolled (< threshold, penalty applies); 5 at-risk; 3 moved up.

    Returns (district, school, window).
    """
    api = _api(api)
    district, school = setup_district_school(api, grade_span_low=3, grade_span_high=3)
    d_id, s_id = district["id"], school["id"]
    define_cut_point(api, d_id, s_id, window_kind="FALL", grade_level=3,
                     subject="READING", tier2_max_score=100, tier3_max_score=70)
    window = create_screening_window(api, d_id, s_id, window_kind="FALL",
                                     opens_on=FALL_WINDOW_OPENS,
                                     closes_on=FALL_WINDOW_CLOSES)
    set_clock(api, CLOCK_IN_FALL_WINDOW)

    ell_at_risk, black_at_risk = [], []
    # ELL: 10 at-risk (band TIER_2), 25 not at-risk (band TIER_1)
    for i in range(35):
        st = enroll_student(api, d_id, s_id, full_name=f"ELL-{i}", grade_level=3,
                            subgroup_codes=["ELL"])
        at_risk = i < 10
        record_score(api, d_id, s_id, window["id"], st["id"],
                     raw_score=80 if at_risk else 150)
        if at_risk:
            ell_at_risk.append(st)
    # BLACK: 5 at-risk, 15 not at-risk
    for i in range(20):
        st = enroll_student(api, d_id, s_id, full_name=f"BLACK-{i}", grade_level=3,
                            subgroup_codes=["BLACK"])
        at_risk = i < 5
        record_score(api, d_id, s_id, window["id"], st["id"],
                     raw_score=80 if at_risk else 150)
        if at_risk:
            black_at_risk.append(st)

    close_window(api, d_id, s_id, window["id"])
    score_window(api, d_id, s_id, window["id"])

    meeting = create_team_meeting(api, d_id, s_id)
    convene_meeting(api, d_id, s_id, meeting["id"])

    # Every at-risk student is ratified TIER_1 -> TIER_2 (15 ratifications).
    _ratify_movements_for_students(api, d_id, s_id, meeting["id"],
                                   ell_at_risk + black_at_risk)

    # Movers: 4 ELL + 3 BLACK run a TIER_2 plan with four responsive probes,
    # then step down to TIER_1 via proposal + ratification.
    movers = ell_at_risk[:4] + black_at_risk[:3]
    catalog_entry = add_catalog_entry(api, d_id, tier_target="TIER_2",
                                      session_minutes=30, sessions_per_week=3,
                                      probe_frequency="WEEKLY")
    interventionist = add_interventionist(api, d_id, s_id,
                                          weekly_minute_capacity=5000)
    plans = {}
    for st in movers:
        plan = create_plan(api, d_id, s_id, st["id"], catalog_entry["id"],
                           interventionist["id"])
        plans[st["id"]] = plan

    # Responsive probes: baseline 80, goal 100 (WEEKLY -> aimlines 83,85,88,90);
    # scores 84, 88, 92, 96 keep the regression slope steeper than the aimline's.
    probe_scores = [84, 88, 92, 96]
    for i, score in enumerate(probe_scores):
        date = _plus_days("2026-08-13", 7 * i)
        set_clock(api, f"{date}T00:00:00Z")
        for st in movers:
            plan = plans[st["id"]]
            get_success_data(api.record_probe(
                d_id, s_id, st["id"], plan["id"],
                record_probe_payload(date, score),
                make_interventionist_role_headers(interventionist["id"])))

    for st in movers:
        propose_movement(api, d_id, s_id, st["id"], "TIER_1",
                         rationale="plan-outcome evidence: responsive probes")
    for st in movers:
        movement = first_proposed_movement(api, d_id, s_id, st["id"])
        ratify_movement(api, d_id, s_id, meeting["id"], movement["id"], st["id"])
        assert get_student(api, d_id, s_id, st["id"])["current_tier"] == "TIER_1"

    return district, school, window
