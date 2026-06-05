"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) for setup calls so setup failures
surface as clear "Setup failed" errors. Every helper builds its preconditions
from scratch using only PRD-declared endpoints; the test harness resets the
database before each test.

Identity threading: Manager / Employee / HrbpPartner / CompApprover are
entity_backed:Employee, so ownership- and segregation-of-duties-gated calls use
make_<role>_headers(employee_id) with the real Employee id (PRD Section 2.1).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_cycle_payload, create_rating_band_payload, create_employee_payload,
    create_review_payload, create_goal_payload, create_feedback_request_payload,
    create_calibration_session_payload, create_comp_plan_payload,
)
from .test_users import (
    TEST_USERS, make_manager_headers, make_employee_headers,
    make_hrbp_headers, make_comp_approver_headers,
)

HR = TEST_USERS["hr_admin_headers"]


# --------------------------------------------------------------------------
# Three-band cycle used across calibration / distribution tests.
# EXCEEDS [80,100], MEETS [50,80), BELOW [0,50). Tiles [0,100] with no gaps.
# --------------------------------------------------------------------------
THREE_BAND_TARGET = {"EXCEEDS": 0.20, "MEETS": 0.65, "BELOW": 0.15}


def _add_three_bands(cycle_id, below_pip_eligible=True):
    api_client.create_rating_band(
        cycle_id, create_rating_band_payload(
            label="BELOW", min_score=0, max_score=50, merit_pct=0.0,
            pip_eligible=below_pip_eligible), HR)
    api_client.create_rating_band(
        cycle_id, create_rating_band_payload(
            label="MEETS", min_score=50, max_score=80, merit_pct=0.04), HR)
    api_client.create_rating_band(
        cycle_id, create_rating_band_payload(
            label="EXCEEDS", min_score=80, max_score=100, merit_pct=0.10), HR)


# --------------------------------------------------------------------------
# Tier 1: State Progression — cycles and employees
# --------------------------------------------------------------------------
def create_employee(full_name="Emp", department="ENG", hire_date=None, manager_id=None):
    payload = create_employee_payload(full_name=full_name, department=department)
    if hire_date is not None:
        payload["hire_date"] = hire_date
    if manager_id is not None:
        payload["manager_id"] = manager_id
    return get_success_data(api_client.create_employee(payload, HR))


def create_draft_cycle_single_band(merit_budget_pct=0.10, equity_refresh_pool=1000,
                                   distribution_tolerance=None, band_merit_pct=0.04):
    """DRAFT cycle with one MEETS band [0,100] and bell_curve_target {MEETS:1.0}."""
    payload = create_cycle_payload(
        merit_budget_pct=merit_budget_pct,
        equity_refresh_pool=equity_refresh_pool,
        bell_curve_target={"MEETS": 1.0})
    if distribution_tolerance is not None:
        payload["distribution_tolerance"] = distribution_tolerance
    cyc = get_success_data(api_client.create_cycle(payload, HR))
    api_client.create_rating_band(
        cyc["id"], create_rating_band_payload(
            label="MEETS", min_score=0, max_score=100, merit_pct=band_merit_pct), HR)
    return cyc


def create_open_cycle_single_band(merit_budget_pct=0.10, equity_refresh_pool=1000,
                                  distribution_tolerance=None, band_merit_pct=0.04):
    """OPEN cycle with one MEETS band [0,100]."""
    cyc = create_draft_cycle_single_band(
        merit_budget_pct=merit_budget_pct,
        equity_refresh_pool=equity_refresh_pool,
        distribution_tolerance=distribution_tolerance,
        band_merit_pct=band_merit_pct)
    return get_success_data(api_client.open_cycle(cyc["id"], HR))


# --------------------------------------------------------------------------
# Tier 2 / 3: Review pipeline shortcuts
# --------------------------------------------------------------------------
def create_review(cycle_id, employee_id, reviewer_id, base_salary=100000):
    return get_success_data(api_client.create_review(
        create_review_payload(cycle_id, employee_id, reviewer_id, base_salary=base_salary), HR))


def drive_review_to_submitted(cycle_id, review_id, employee_id, reviewer_id,
                              self_rating="MEETS", manager_rating="MEETS",
                              goal_attainment=0.8, goal_weight=1.0,
                              feedback_scores=None):
    """Walk a DRAFT review (in an OPEN cycle) to SUBMITTED:
    begin-self-review -> set self_rating -> add+score one goal ->
    submit-self -> set manager_rating -> (optional submitted feedback) -> submit.
    Returns the SUBMITTED review dict.
    """
    emp_hdr = make_employee_headers(employee_id)
    mgr_hdr = make_manager_headers(reviewer_id)

    # One goal, created and scored by the manager.
    goal = get_success_data(api_client.create_goal(
        review_id, create_goal_payload(title="G1", weight=goal_weight), mgr_hdr))

    api_client.begin_self_review(review_id, emp_hdr)
    api_client.patch_review(review_id, {"self_rating": self_rating}, emp_hdr)
    api_client.submit_self(review_id, emp_hdr)
    api_client.patch_review(review_id, {"manager_rating": manager_rating}, mgr_hdr)
    api_client.score_goal(goal["id"], {"attainment_pct": goal_attainment}, mgr_hdr)

    # Optional 360 feedback (submitted by raters).
    if feedback_scores:
        for score in feedback_scores:
            rater = create_employee(full_name="Rater", department="ENG")
            fr = get_success_data(api_client.create_feedback_request(
                review_id, create_feedback_request_payload(rater["id"], relationship="PEER"),
                mgr_hdr))
            api_client.submit_feedback(fr["id"], {"score": score}, make_employee_headers(rater["id"]))

    return get_success_data(api_client.submit_review(review_id, mgr_hdr))


def setup_submitted_review(self_rating="MEETS", manager_rating="MEETS",
                           goal_attainment=0.8, base_salary=100000,
                           feedback_scores=None):
    """OPEN cycle (single MEETS band) + a SUBMITTED review.
    Returns (cycle, manager_emp, subject_emp, review).
    """
    cyc = create_open_cycle_single_band()
    mgr = create_employee(full_name="Mgr", department="ENG", hire_date="2019-01-01T00:00:00.000Z")
    emp = create_employee(full_name="Subject", department="ENG",
                          hire_date="2020-01-01T00:00:00.000Z", manager_id=mgr["id"])
    rev = create_review(cyc["id"], emp["id"], mgr["id"], base_salary=base_salary)
    review = drive_review_to_submitted(
        cyc["id"], rev["id"], emp["id"], mgr["id"],
        self_rating=self_rating, manager_rating=manager_rating,
        goal_attainment=goal_attainment, feedback_scores=feedback_scores)
    return cyc, mgr, emp, review


# --------------------------------------------------------------------------
# Tier 4 / 5: Calibration -> CALIBRATED reviews -> COMP_PLANNING
# --------------------------------------------------------------------------
def setup_calibrated_review_in_comp_planning(
        band_label="MEETS", band_merit_pct=0.04,
        merit_budget_pct=0.5, equity_refresh_pool=100000,
        base_salary=100000, hire_date="2018-01-01T00:00:00.000Z",
        below_pip_eligible=False):
    """Build a cycle with a single band covering [0,100] labelled `band_label`,
    drive one review to CALIBRATED via calibration finalize, then advance the
    cycle to COMP_PLANNING.

    Returns dict with: cycle, manager, subject, hrbp, approver, review (CALIBRATED),
    session.
    """
    # Single band tiling [0,100] so every review lands in `band_label`.
    cyc_payload = create_cycle_payload(
        merit_budget_pct=merit_budget_pct,
        equity_refresh_pool=equity_refresh_pool,
        bell_curve_target={band_label: 1.0},
        distribution_tolerance=0.05)
    cyc = get_success_data(api_client.create_cycle(cyc_payload, HR))
    api_client.create_rating_band(
        cyc["id"], create_rating_band_payload(
            label=band_label, min_score=0, max_score=100,
            merit_pct=band_merit_pct, pip_eligible=below_pip_eligible), HR)
    cyc = get_success_data(api_client.open_cycle(cyc["id"], HR))

    mgr = create_employee(full_name="Mgr", department="ENG", hire_date="2010-01-01T00:00:00.000Z")
    subject = create_employee(full_name="Subject", department="ENG",
                              hire_date=hire_date, manager_id=mgr["id"])
    hrbp = create_employee(full_name="Hrbp", department="ENG", hire_date="2010-01-01T00:00:00.000Z")
    approver = create_employee(full_name="Approver", department="ENG",
                               hire_date="2010-01-01T00:00:00.000Z")

    rev = create_review(cyc["id"], subject["id"], mgr["id"], base_salary=base_salary)
    drive_review_to_submitted(
        cyc["id"], rev["id"], subject["id"], mgr["id"],
        self_rating=band_label, manager_rating=band_label, goal_attainment=1.0)

    # OPEN -> CALIBRATION
    api_client.start_calibration(cyc["id"], HR)

    # Calibration session: HRBP facilitator who is NOT the reviewer.
    sess = get_success_data(api_client.create_calibration_session(
        create_calibration_session_payload(cyc["id"], hrbp["id"], department="ENG"),
        make_hrbp_headers(hrbp["id"])))
    api_client.balance_session(sess["id"], make_hrbp_headers(hrbp["id"]))
    api_client.finalize_session(sess["id"], make_hrbp_headers(hrbp["id"]))

    # CALIBRATION -> COMP_PLANNING
    cyc = get_success_data(api_client.start_comp_planning(cyc["id"], HR))

    review = get_success_data(api_client.get_review(rev["id"], HR))
    return {
        "cycle": cyc, "manager": mgr, "subject": subject, "hrbp": hrbp,
        "approver": approver, "review": review, "session": sess,
    }


def create_comp_plan_for(cycle_id, review_id, manager_id, plan_type="MERIT_ONLY",
                         promo_band_jump=None):
    """Create a CompPlan (DRAFT) against a CALIBRATED review using the review's
    current version. Returns the created plan dict."""
    mgr_hdr = make_manager_headers(manager_id)
    rev = get_success_data(api_client.get_review(review_id, mgr_hdr))
    payload = create_comp_plan_payload(
        cycle_id, review_id, rev["version"], plan_type=plan_type)
    if promo_band_jump is not None:
        payload["promo_band_jump"] = promo_band_jump
    return get_success_data(api_client.create_comp_plan(payload, mgr_hdr))


def setup_comp_planning_with_n_calibrated_reviews(
        n=2, band_label="EXCEEDS", band_merit_pct=0.10,
        merit_budget_pct=0.5, equity_refresh_pool=100000,
        base_salaries=None, hire_date="2010-01-01T00:00:00.000Z"):
    """Build a single-band cycle ([0,100] -> band_label), drive N reviews to
    SUBMITTED, finalize calibration so all become CALIBRATED, advance to
    COMP_PLANNING. Distinct manager/subject per review.

    Returns dict: cycle, hrbp, approver, reviewers (list of manager employees),
    subjects (list), reviews (list of CALIBRATED review dicts), session.
    """
    if base_salaries is None:
        base_salaries = [100000] * n

    cyc_payload = create_cycle_payload(
        merit_budget_pct=merit_budget_pct,
        equity_refresh_pool=equity_refresh_pool,
        bell_curve_target={band_label: 1.0},
        distribution_tolerance=0.05)
    cyc = get_success_data(api_client.create_cycle(cyc_payload, HR))
    api_client.create_rating_band(
        cyc["id"], create_rating_band_payload(
            label=band_label, min_score=0, max_score=100, merit_pct=band_merit_pct), HR)
    cyc = get_success_data(api_client.open_cycle(cyc["id"], HR))

    hrbp = create_employee(full_name="Hrbp", department="ENG", hire_date="2010-01-01T00:00:00.000Z")
    approver = create_employee(full_name="Approver", department="ENG",
                               hire_date="2010-01-01T00:00:00.000Z")

    reviewers, subjects, review_ids = [], [], []
    for i in range(n):
        mgr = create_employee(full_name=f"Mgr{i}", department="ENG",
                              hire_date="2010-01-01T00:00:00.000Z")
        subj = create_employee(full_name=f"Subj{i}", department="ENG",
                               hire_date=hire_date, manager_id=mgr["id"])
        rev = create_review(cyc["id"], subj["id"], mgr["id"], base_salary=base_salaries[i])
        drive_review_to_submitted(
            cyc["id"], rev["id"], subj["id"], mgr["id"],
            self_rating=band_label, manager_rating=band_label, goal_attainment=1.0)
        reviewers.append(mgr)
        subjects.append(subj)
        review_ids.append(rev["id"])

    api_client.start_calibration(cyc["id"], HR)
    sess = get_success_data(api_client.create_calibration_session(
        create_calibration_session_payload(cyc["id"], hrbp["id"], department="ENG"),
        make_hrbp_headers(hrbp["id"])))
    api_client.balance_session(sess["id"], make_hrbp_headers(hrbp["id"]))
    api_client.finalize_session(sess["id"], make_hrbp_headers(hrbp["id"]))
    cyc = get_success_data(api_client.start_comp_planning(cyc["id"], HR))

    reviews = [get_success_data(api_client.get_review(rid, HR)) for rid in review_ids]
    return {
        "cycle": cyc, "hrbp": hrbp, "approver": approver,
        "reviewers": reviewers, "subjects": subjects,
        "reviews": reviews, "session": sess,
    }


def setup_proposed_plan(band_label="MEETS", band_merit_pct=0.04,
                        merit_budget_pct=0.5, equity_refresh_pool=100000,
                        base_salary=100000, plan_type="MERIT_ONLY",
                        promo_band_jump=None, hire_date="2010-01-01T00:00:00.000Z"):
    """Full setup through a PROPOSED comp plan on a CALIBRATED review.
    Returns dict adding 'plan' to the keys of setup_calibrated_review_in_comp_planning.
    """
    ctx = setup_calibrated_review_in_comp_planning(
        band_label=band_label, band_merit_pct=band_merit_pct,
        merit_budget_pct=merit_budget_pct, equity_refresh_pool=equity_refresh_pool,
        base_salary=base_salary, hire_date=hire_date)
    plan = create_comp_plan_for(
        ctx["cycle"]["id"], ctx["review"]["id"], ctx["manager"]["id"],
        plan_type=plan_type, promo_band_jump=promo_band_jump)
    mgr_hdr = make_manager_headers(ctx["manager"]["id"])
    plan = get_success_data(api_client.propose_comp_plan(plan["id"], mgr_hdr))
    ctx["plan"] = plan
    return ctx


def approve_plan(plan_id, cycle_id, approver_id):
    """Approve a PROPOSED plan, reading the current cycle version first."""
    appr_hdr = make_comp_approver_headers(approver_id)
    cyc = get_success_data(api_client.get_cycle(cycle_id, appr_hdr))
    return api_client.approve_comp_plan(
        plan_id, {"expected_cycle_version": cyc["version"]}, appr_hdr)
