"""Composite setup helpers.

Every test starts against a fresh, empty database (the harness restarts the
server before each test), so every precondition is built from scratch here.
Fixtures use the lenient get_success_data() validator: a setup failure raises
a clear "Setup failed" assertion rather than a confusing test assertion.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_TODAY
from .factories import (
    create_bulk_enroll_payload,
    create_case_payload,
    create_committee_review_payload,
    create_cut_score_profile_payload,
    create_measure_score_payload,
    create_placement_payload,
    create_re_eval_conclusion_payload,
    create_re_evaluation_payload,
    create_school_site_payload,
    create_screening_cycle_payload,
    create_sped_plan_payload,
    create_student_payload,
    create_transfer_honor_case_payload,
    create_vote_payload,
)
from .test_users import (
    TEST_USERS,
    make_committee_member_headers,
    make_parent_guardian_headers,
)

GC = TEST_USERS["gifted_coordinator_headers"]
SE = TEST_USERS["special_ed_coordinator_headers"]


def _setup_failed(step: str, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code}: {resp.text}")


def _ok(resp, step, expected_status=None):
    if expected_status is not None and resp.status_code != expected_status:
        _setup_failed(step, resp)
    if resp.status_code >= 400:
        _setup_failed(step, resp)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 0: clock + primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Set the logical clock (runs the re-evaluation activation and
    offer-expiry sweeps)."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, GC)
    return _ok(resp, f"set_clock({to_iso8601})")


def create_site(**overrides):
    resp = api_client.create_school_site(create_school_site_payload(**overrides), GC)
    return _ok(resp, "create_school_site", 201)


def create_student(site_id, **overrides):
    payload = create_student_payload(school_site_id=site_id, **overrides)
    resp = api_client.create_student(payload, GC)
    return _ok(resp, "create_student", 201)


def bulk_enroll(site_id, grade_level, demographic_group, count):
    payload = create_bulk_enroll_payload(
        school_site_id=site_id, grade_level=grade_level,
        demographic_group=demographic_group, count=count)
    resp = api_client.bulk_enroll_students(payload, GC)
    return _ok(resp, "bulk_enroll", 201)


def create_sped_plan(student_id, **overrides):
    resp = api_client.create_sped_plan(
        student_id, create_sped_plan_payload(**overrides), SE)
    return _ok(resp, "create_sped_plan", 201)


# ---------------------------------------------------------------------------
# Tier 1: cycle + profile progression
# ---------------------------------------------------------------------------

def create_cycle(**overrides):
    """Create a DRAFT cycle. Returns the cycle dict (status DRAFT, version 1)."""
    resp = api_client.create_screening_cycle(
        create_screening_cycle_payload(**overrides), GC)
    return _ok(resp, "create_cycle", 201)


def create_profile(cycle_id, **overrides):
    resp = api_client.create_cut_score_profile(
        cycle_id, create_cut_score_profile_payload(**overrides), GC)
    return _ok(resp, "create_profile", 201)


def publish_profile(profile_id, expected_cycle_version):
    resp = api_client.publish_cut_score_profile(
        profile_id, {"expected_cycle_version": expected_cycle_version}, GC)
    return _ok(resp, "publish_profile", 200)


def advance_cycle(cycle_id, target_state):
    resp = api_client.advance_cycle(cycle_id, {"target_state": target_state}, GC)
    return _ok(resp, f"advance_cycle({target_state})", 200)


def get_cycle(cycle_id):
    return _ok(api_client.get_screening_cycle(cycle_id, GC), "get_cycle")


def setup_cycle_with_published_profile(cycle_overrides=None, profile_overrides=None):
    """DRAFT cycle + published P_BAND profile. Returns (cycle, profile).
    The cycle is still DRAFT after the publish."""
    cycle = create_cycle(**(cycle_overrides or {}))
    profile = create_profile(cycle["id"], **(profile_overrides or {}))
    publish_profile(profile["id"], cycle["version"])
    return get_cycle(cycle["id"]), profile


def setup_cycle_in_state(target_state, cycle_overrides=None, profile_overrides=None):
    """Cycle with a published P_BAND profile, advanced to target_state.
    target_state one of OPEN / SCORING / REVIEW. Returns (cycle, profile)."""
    assert target_state in ("OPEN", "SCORING", "REVIEW")
    cycle, profile = setup_cycle_with_published_profile(
        cycle_overrides, profile_overrides)
    for state in ("OPEN", "SCORING", "REVIEW"):
        cycle = advance_cycle(cycle["id"], state)
        if state == target_state:
            break
    return cycle, profile


# ---------------------------------------------------------------------------
# Tier 2: cases
# ---------------------------------------------------------------------------

def create_case(student_id, cycle_id, headers=None, **overrides):
    resp = api_client.create_case(
        create_case_payload(student_id=student_id, cycle_id=cycle_id, **overrides),
        headers or GC)
    return _ok(resp, "create_case", 201)


def create_transfer_honor_case(student_id, cycle_id, **overrides):
    resp = api_client.create_case(
        create_transfer_honor_case_payload(
            student_id=student_id, cycle_id=cycle_id, **overrides),
        GC)
    return _ok(resp, "create_transfer_honor_case", 201)


def enter_measure(case_id, measure_type, percentile, administered_on="2026-08-20"):
    resp = api_client.create_measure_score(
        case_id,
        create_measure_score_payload(
            measure_type=measure_type, percentile=percentile,
            administered_on=administered_on),
        GC)
    return _ok(resp, f"enter_measure({measure_type})", 201)


def enter_standard_measures(case_id, ability, achievement, rating,
                            portfolio=None, administered_on="2026-08-20"):
    """Enter ABILITY/ACHIEVEMENT/RATING_SCALE (+ optional PORTFOLIO) on a case."""
    enter_measure(case_id, "ABILITY", ability, administered_on)
    enter_measure(case_id, "ACHIEVEMENT", achievement, administered_on)
    enter_measure(case_id, "RATING_SCALE", rating, administered_on)
    if portfolio is not None:
        enter_measure(case_id, "PORTFOLIO", portfolio, administered_on)


def finalize_case(case_id):
    resp = api_client.finalize_scoring(case_id, GC)
    return _ok(resp, "finalize_case", 200)


def setup_scored_case(ability, achievement, rating, portfolio=None,
                      with_sped_plan=False, student_overrides=None,
                      cycle_overrides=None, profile_overrides=None,
                      pathway="UNIVERSAL_SCREEN", referrer_headers=None,
                      referral_source=None):
    """Full scoring setup: clock at canonical today, site, student, cycle with
    published profile advanced to SCORING, one case with the given measures
    entered (entered while the cycle was OPEN).

    Returns dict(case, student, cycle, profile, site, finalized=<response data
    of finalize-scoring>).
    """
    set_clock(CLOCK_TODAY)
    site = create_site()
    student = create_student(site["id"], **(student_overrides or {}))
    if with_sped_plan:
        create_sped_plan(student["id"])
    cycle, profile = setup_cycle_in_state(
        "OPEN", cycle_overrides, profile_overrides)
    case_kwargs = {}
    headers = None
    if pathway == "REFERRAL":
        # PRD §3.3: the pathway itself must reach the payload — without it the
        # factory default (UNIVERSAL_SCREEN) plus referral_source is a shape
        # violation / role violation the PRD-faithful server rightly rejects.
        case_kwargs["pathway"] = "REFERRAL"
        case_kwargs["referral_source"] = referral_source or "TEACHER"
        headers = referrer_headers
    elif pathway == "TRANSFER_HONOR":
        case = create_transfer_honor_case(student["id"], cycle["id"])
        advance_cycle(cycle["id"], "SCORING")
        return {"case": case, "student": student, "cycle": get_cycle(cycle["id"]),
                "profile": profile, "site": site, "finalized": None}
    case = create_case(student["id"], cycle["id"], headers=headers, **case_kwargs)
    enter_standard_measures(case["id"], ability, achievement, rating, portfolio)
    advance_cycle(cycle["id"], "SCORING")
    finalized = finalize_case(case["id"])
    return {"case": get_case(case["id"]), "student": student,
            "cycle": get_cycle(cycle["id"]), "profile": profile, "site": site,
            "finalized": finalized}


def get_case(case_id):
    return _ok(api_client.get_case(case_id, GC), "get_case")


def get_student(student_id):
    return _ok(api_client.get_student(student_id, GC), "get_student")


def get_site(site_id):
    return _ok(api_client.get_school_site(site_id, GC), "get_site")


def get_placement(placement_id):
    return _ok(api_client.get_placement(placement_id, GC), "get_placement")


def get_review(review_id):
    return _ok(api_client.get_committee_review(review_id, GC), "get_review")


def get_re_evaluation_list(placement_id):
    return _ok(api_client.list_re_evaluations(placement_id, GC),
               "list_re_evaluations")


# ---------------------------------------------------------------------------
# Tier 3: committee reviews
# ---------------------------------------------------------------------------

def open_band_review(case_id, grounds="band review"):
    resp = api_client.create_committee_review(
        case_id, create_committee_review_payload(
            review_kind="BAND_REVIEW", grounds=grounds), GC)
    return _ok(resp, "open_band_review", 201)


def open_appeal(case_id, headers, grounds="appeal"):
    resp = api_client.create_committee_review(
        case_id, create_committee_review_payload(
            review_kind="APPEAL", grounds=grounds), headers)
    return _ok(resp, "open_appeal", 201)


def cast_vote(review_id, verdict, member_user_id):
    resp = api_client.cast_vote(
        review_id, create_vote_payload(verdict=verdict),
        make_committee_member_headers(member_user_id))
    return _ok(resp, f"cast_vote({member_user_id})", 201)


def setup_case_in_review(ability=99, achievement=90, rating=88, **kwargs):
    """Scored case in a REVIEW-state cycle. Returns the setup_scored_case dict
    with the cycle advanced to REVIEW."""
    ctx = setup_scored_case(ability, achievement, rating, **kwargs)
    advance_cycle(ctx["cycle"]["id"], "REVIEW")
    ctx["cycle"] = get_cycle(ctx["cycle"]["id"])
    return ctx


def setup_band_case_with_open_review(ability=99, achievement=90, rating=88,
                                     **kwargs):
    """Case AWAITING_COMMITTEE in a REVIEW cycle with a BAND_REVIEW open (VOTING).
    Returns ctx dict plus ctx['review']."""
    ctx = setup_case_in_review(ability, achievement, rating, **kwargs)
    assert ctx["case"]["status"] == "AWAITING_COMMITTEE", (
        f"setup_band_case_with_open_review requires an in-band composite; "
        f"got status {ctx['case']['status']}")
    ctx["review"] = open_band_review(ctx["case"]["id"])
    return ctx


def setup_not_identified_case_in_review(ability=80, achievement=80, rating=80,
                                        **kwargs):
    """Case finalized below the floor (NOT_IDENTIFIED) in a REVIEW cycle."""
    ctx = setup_case_in_review(ability, achievement, rating, **kwargs)
    assert ctx["case"]["status"] == "NOT_IDENTIFIED", (
        f"setup_not_identified_case_in_review requires a below-floor composite; "
        f"got status {ctx['case']['status']}")
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: placements
# ---------------------------------------------------------------------------

def setup_honored_student(student_overrides=None, site_overrides=None):
    """Clock at canonical today; site; OPEN cycle with published profile; one
    student honored via TRANSFER_HONOR (case IDENTIFIED at creation).
    Returns dict(site, cycle, profile, student, case)."""
    set_clock(CLOCK_TODAY)
    site = create_site(**(site_overrides or {}))
    cycle, profile = setup_cycle_in_state("OPEN")
    student = create_student(site["id"], **(student_overrides or {}))
    case = create_transfer_honor_case(student["id"], cycle["id"])
    return {"site": site, "cycle": cycle, "profile": profile,
            "student": student, "case": case}


def offer_placement(case_id, site_id, service_model="PULL_OUT", start_on="2026-09-01"):
    resp = api_client.create_placement(
        case_id,
        create_placement_payload(
            site_id=site_id, service_model=service_model, start_on=start_on),
        GC)
    return _ok(resp, "offer_placement", 201)


def accept_placement(placement_id, guardian_user_id):
    resp = api_client.accept_placement(
        placement_id, make_parent_guardian_headers(guardian_user_id))
    return _ok(resp, "accept_placement", 200)


def setup_active_placement(student_overrides=None, site_overrides=None,
                           service_model="PULL_OUT", start_on="2026-09-01"):
    """Honored student with an ACTIVE placement (offered + accepted by the
    student's guardian). Returns ctx dict plus ctx['placement']."""
    ctx = setup_honored_student(student_overrides, site_overrides)
    placement = offer_placement(ctx["case"]["id"], ctx["site"]["id"],
                                service_model, start_on)
    placement = accept_placement(
        placement["id"], ctx["student"]["primary_guardian_user_id"])
    assert placement["status"] == "ACTIVE", (
        f"setup_active_placement expected ACTIVE, got {placement['status']}")
    ctx["placement"] = placement
    return ctx


def schedule_re_evaluation(placement_id, due_on="2027-01-15"):
    resp = api_client.create_re_evaluation(
        placement_id, create_re_evaluation_payload(due_on=due_on), GC)
    return _ok(resp, "schedule_re_evaluation", 201)


def setup_active_placement_with_reeval(due_on="2027-01-15", activate=False,
                                       **kwargs):
    """ACTIVE placement plus one SCHEDULED re-evaluation. With activate=True the
    clock is advanced to due_on so the sweep moves the record to IN_REVIEW.
    Returns ctx dict plus ctx['re_evaluation']."""
    ctx = setup_active_placement(**kwargs)
    ctx["re_evaluation"] = schedule_re_evaluation(ctx["placement"]["id"], due_on)
    if activate:
        set_clock(f"{due_on}T00:00:00Z")
    return ctx


def conclude_re_evaluation(re_eval_id, growth_percentile, service_rating,
                           teacher_rating, outcome):
    resp = api_client.conclude_re_evaluation(
        re_eval_id,
        create_re_eval_conclusion_payload(
            growth_percentile=growth_percentile, service_rating=service_rating,
            teacher_rating=teacher_rating, outcome=outcome),
        GC)
    return _ok(resp, "conclude_re_evaluation", 200)


# ---------------------------------------------------------------------------
# Tier 5: waitlist scenarios
# ---------------------------------------------------------------------------

def setup_full_site_with_waitlist(capacity=1):
    """Site with pull_out_capacity == capacity; honored students A (ACTIVE,
    occupying the seat) and B (offered; accept attempt lands WAITLISTED).
    Returns dict with site, cycle, profile, stu_a, case_a, pa, stu_b, case_b, pb
    where pb is the (waitlisted) placement dict as last observed."""
    set_clock(CLOCK_TODAY)
    site = create_site(pull_out_capacity=capacity)
    cycle, profile = setup_cycle_in_state("OPEN")
    stu_a = create_student(site["id"], student_number="ST-A",
                           legal_name="Stu A", demographic_group="WHITE",
                           primary_guardian_user_id="guard-a")
    case_a = create_transfer_honor_case(stu_a["id"], cycle["id"])
    stu_b = create_student(site["id"], student_number="ST-B",
                           legal_name="Stu B", demographic_group="BLACK",
                           primary_guardian_user_id="guard-b")
    case_b = create_transfer_honor_case(stu_b["id"], cycle["id"])
    pa = offer_placement(case_a["id"], site["id"], "PULL_OUT")
    pa = accept_placement(pa["id"], "guard-a")
    pb = offer_placement(case_b["id"], site["id"], "PULL_OUT")
    pb = accept_placement(pb["id"], "guard-b")
    assert pb["status"] == "WAITLISTED", (
        f"expected WAITLISTED, got {pb['status']}")
    return {"site": site, "cycle": cycle, "profile": profile,
            "stu_a": stu_a, "case_a": case_a, "pa": pa,
            "stu_b": stu_b, "case_b": case_b, "pb": pb}


def withdraw_placement(placement_id):
    resp = api_client.withdraw_placement(placement_id, GC)
    return _ok(resp, "withdraw_placement", 200)
