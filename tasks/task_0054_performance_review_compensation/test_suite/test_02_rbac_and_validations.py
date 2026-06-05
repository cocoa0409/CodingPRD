"""RBAC permitted/denied, authentication, and single-rule validation errors.

Queue B (Corner) — rbac, validations, errors sections.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_cycle_payload, create_rating_band_payload, create_review_payload,
    create_goal_payload, create_calibration_session_payload,
    create_comp_plan_payload,
    TEST_USERS,
    create_employee, create_open_cycle_single_band, create_draft_cycle_single_band,
    create_review, drive_review_to_submitted,
    setup_calibrated_review_in_comp_planning, setup_proposed_plan,
    setup_comp_planning_with_n_calibrated_reviews, create_comp_plan_for, approve_plan,
    make_manager_headers, make_employee_headers, make_hrbp_headers,
    make_comp_approver_headers,
)

HR = TEST_USERS["hr_admin_headers"]


def _draft_cycle_with_full_coverage():
    """DRAFT cycle whose single MEETS band tiles [0,100] and target sums to 1."""
    return create_draft_cycle_single_band()


# --------------------------------------------------------------------------
# RBAC
# --------------------------------------------------------------------------
def test_hradmin_opens_cycle_permitted(api):
    """PRD §3.1: "Opening the cycle — transitioning it from `DRAFT` to `OPEN` —
    is performed by the `HrAdmin` ... When both checks pass, the cycle advances
    to `OPEN`".

    Design: Corner/rbac/hradmin_opens_cycle_permitted
    """
    cyc = _draft_cycle_with_full_coverage()
    res = api.open_cycle(cyc["id"], HR)
    opened = validate_success(res, 200)
    assert opened["status"] == "OPEN"


def test_employee_cannot_open_cycle(api):
    """PRD Section 4: "POST /cycles/{id}/open ... HrAdmin". PRD §4: "any other
    role is rejected with `ERR_FORBIDDEN_ROLE`".

    Design: Corner/rbac/employee_cannot_open_cycle
    """
    cyc = _draft_cycle_with_full_coverage()
    emp = create_employee(full_name="Emp", department="ENG")
    res = api.open_cycle(cyc["id"], make_employee_headers(emp["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_manager_cannot_begin_self_review(api):
    """PRD Section 4: "POST /reviews/{id}/begin-self-review ... Employee". PRD §4:
    "any other role is rejected with `ERR_FORBIDDEN_ROLE`".

    Design: Corner/rbac/manager_cannot_begin_self_review
    """
    cyc = create_open_cycle_single_band()
    mgr = create_employee(full_name="Mgr", department="ENG")
    emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
    rev = create_review(cyc["id"], emp["id"], mgr["id"])
    res = api.begin_self_review(rev["id"], make_manager_headers(mgr["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_hrbp_creates_calibration_permitted(api):
    """PRD §3.4: "Calibration happens within `CalibrationSession` records, each
    created by an `HrbpPartner` and scoped to a single `cycle_id` and
    `department`". PRD §3.4: "A session begins `OPEN`."

    Design: Corner/rbac/hrbp_creates_calibration_permitted
    """
    cyc = create_open_cycle_single_band()
    hrbp = create_employee(full_name="Hrbp", department="ENG")
    api.start_calibration(cyc["id"], HR)  # OPEN -> CALIBRATION
    res = api.create_calibration_session(
        create_calibration_session_payload(cyc["id"], hrbp["id"], department="ENG"),
        make_hrbp_headers(hrbp["id"]))
    sess = validate_success(res, 201)
    assert sess["status"] == "OPEN"


def test_manager_cannot_approve_comp_plan(api):
    """PRD Section 4: "POST /comp-plans/{id}/approve ... CompApprover". PRD §4:
    "any other role is rejected with `ERR_FORBIDDEN_ROLE`".

    Design: Corner/rbac/manager_cannot_approve_comp_plan
    """
    ctx = setup_proposed_plan()
    res = api.approve_comp_plan(
        ctx["plan"]["id"], {"expected_cycle_version": ctx["cycle"]["version"]},
        make_manager_headers(ctx["manager"]["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_missing_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of
    those five values, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/missing_headers_unauthenticated
    """
    res = api.list_cycles({})
    validate_error(res, "ERR_UNAUTHENTICATED")


# --------------------------------------------------------------------------
# Validation errors (single-rule scenarios)
# --------------------------------------------------------------------------
def test_promo_jump_invalid_for_merit_only(api):
    """PRD §3.8: "The `promo_band_jump` must be exactly zero for a `MERIT_ONLY`
    plan and either one or two for a `MERIT_AND_PROMO` plan; any other
    combination is rejected with `ERR_PROMO_JUMP_INVALID` (HTTP 422)."

    Design: Corner/validations/promo_jump_invalid_for_merit_only
    """
    ctx = setup_calibrated_review_in_comp_planning()
    rev = get_success_data(api.get_review(ctx["review"]["id"], make_manager_headers(ctx["manager"]["id"])))
    payload = create_comp_plan_payload(
        ctx["cycle"]["id"], ctx["review"]["id"], rev["version"],
        plan_type="MERIT_ONLY", promo_band_jump=1)
    res = api.create_comp_plan(payload, make_manager_headers(ctx["manager"]["id"]))
    validate_error(res, "ERR_PROMO_JUMP_INVALID")


def test_promo_jump_three_rejected(api):
    """PRD §3.8: "The `promo_band_jump` must be exactly zero for a `MERIT_ONLY`
    plan and either one or two for a `MERIT_AND_PROMO` plan; any other
    combination is rejected with `ERR_PROMO_JUMP_INVALID` (HTTP 422)."

    Design: Corner/validations/promo_jump_three_rejected
    """
    ctx = setup_calibrated_review_in_comp_planning()
    rev = get_success_data(api.get_review(ctx["review"]["id"], make_manager_headers(ctx["manager"]["id"])))
    payload = create_comp_plan_payload(
        ctx["cycle"]["id"], ctx["review"]["id"], rev["version"],
        plan_type="MERIT_AND_PROMO", promo_band_jump=3)
    res = api.create_comp_plan(payload, make_manager_headers(ctx["manager"]["id"]))
    validate_error(res, "ERR_PROMO_JUMP_INVALID")


def test_goal_weights_sum_over_one(api):
    """PRD §3.3: "the sum of a review's goal weights must lie in the half-open
    range above zero and up to and including one ... Any of these failures is
    reported as `ERR_GOAL_WEIGHTS_INVALID` (HTTP 422), and the check is applied
    both when submitting a review and when adding a goal to one."

    Design: Corner/validations/goal_weights_sum_over_one
    """
    cyc = create_open_cycle_single_band()
    mgr = create_employee(full_name="Mgr", department="ENG")
    emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
    rev = create_review(cyc["id"], emp["id"], mgr["id"])
    api.create_goal(rev["id"], create_goal_payload(title="G1", weight=0.7),
                    make_manager_headers(mgr["id"]))
    res = api.create_goal(rev["id"], create_goal_payload(title="G2", weight=0.6),
                          make_manager_headers(mgr["id"]))
    validate_error(res, "ERR_GOAL_WEIGHTS_INVALID")


def test_err_rating_band_unknown(api):
    """PRD §3.2: "A supplied rating label — `self_rating`, `manager_rating`, or
    `final_rating` — that does not match any band on the cycle is rejected with
    `ERR_RATING_BAND_UNKNOWN` (HTTP 422)".

    Design: Corner/errors/err_rating_band_unknown
    """
    cyc = create_open_cycle_single_band()  # only a MEETS band
    mgr = create_employee(full_name="Mgr", department="ENG")
    emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
    rev = create_review(cyc["id"], emp["id"], mgr["id"])
    api.begin_self_review(rev["id"], make_employee_headers(emp["id"]))
    res = api.patch_review(rev["id"], {"self_rating": "STELLAR"},
                           make_employee_headers(emp["id"]))
    validate_error(res, "ERR_RATING_BAND_UNKNOWN")


def test_err_band_coverage_invalid_gap(api):
    """PRD §3.1: "The bands must tile the score range from 0 to 100 completely,
    with no gaps and no overlaps; a failure of this coverage condition, or a
    mismatch between the set of band labels and the set of keys in
    `bell_curve_target`, is rejected with `ERR_BAND_COVERAGE_INVALID` (HTTP 422)."

    Design: Corner/errors/err_band_coverage_invalid_gap
    """
    cyc = get_success_data(api.create_cycle(create_cycle_payload(
        name="Gap", cadence="ANNUAL", merit_budget_pct=0.04, equity_refresh_pool=0,
        bell_curve_target={"LOW": 0.5, "HIGH": 0.5}), HR))
    api.create_rating_band(cyc["id"], create_rating_band_payload(
        label="LOW", min_score=0, max_score=50, merit_pct=0.0), HR)
    api.create_rating_band(cyc["id"], create_rating_band_payload(
        label="HIGH", min_score=60, max_score=100, merit_pct=0.08), HR)
    res = api.open_cycle(cyc["id"], HR)
    validate_error(res, "ERR_BAND_COVERAGE_INVALID")


def test_err_distribution_not_normalized(api):
    """PRD §3.1: "Separately, the `bell_curve_target` fractions must sum to one
    within five ten-thousandths; a sum outside that window is rejected with
    `ERR_DISTRIBUTION_NOT_NORMALIZED` (HTTP 422)."

    Design: Corner/errors/err_distribution_not_normalized
    """
    cyc = get_success_data(api.create_cycle(create_cycle_payload(
        name="Bad", cadence="ANNUAL", merit_budget_pct=0.04, equity_refresh_pool=0,
        bell_curve_target={"EXCEEDS": 0.3, "MEETS": 0.6}), HR))
    api.create_rating_band(cyc["id"], create_rating_band_payload(
        label="MEETS", min_score=0, max_score=50, merit_pct=0.04), HR)
    api.create_rating_band(cyc["id"], create_rating_band_payload(
        label="EXCEEDS", min_score=50, max_score=100, merit_pct=0.08), HR)
    res = api.open_cycle(cyc["id"], HR)
    validate_error(res, "ERR_DISTRIBUTION_NOT_NORMALIZED")


def test_err_goal_weights_zero_goals_submit(api):
    """PRD §3.3: "and a review may not be submitted with zero goals. Any of these
    failures is reported as `ERR_GOAL_WEIGHTS_INVALID` (HTTP 422)".

    Design: Corner/errors/err_goal_weights_zero_goals_submit
    """
    cyc = create_open_cycle_single_band()
    mgr = create_employee(full_name="Mgr", department="ENG")
    emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
    rev = create_review(cyc["id"], emp["id"], mgr["id"])
    emp_hdr = make_employee_headers(emp["id"])
    mgr_hdr = make_manager_headers(mgr["id"])
    api.begin_self_review(rev["id"], emp_hdr)
    api.patch_review(rev["id"], {"self_rating": "MEETS"}, emp_hdr)
    api.submit_self(rev["id"], emp_hdr)
    api.patch_review(rev["id"], {"manager_rating": "MEETS"}, mgr_hdr)
    res = api.submit_review(rev["id"], mgr_hdr)  # zero goals
    validate_error(res, "ERR_GOAL_WEIGHTS_INVALID")


def test_err_distribution_out_of_tolerance_balance(api):
    """PRD §3.4: "for every band, the absolute difference between that band's
    actual fraction and its target fraction must be at most the cycle's
    `distribution_tolerance`. If any band deviates by more than the tolerance,
    the balance is blocked with `ERR_DISTRIBUTION_OUT_OF_TOLERANCE` (HTTP 422)."

    Design: Corner/errors/err_distribution_out_of_tolerance_balance
    """
    # Three-band cycle; the single review lands EXCEEDS (actual 1.0) vs target 0.20.
    cyc = get_success_data(api.create_cycle(create_cycle_payload(
        name="Cal", cadence="ANNUAL", merit_budget_pct=0.5, equity_refresh_pool=0,
        bell_curve_target={"EXCEEDS": 0.20, "MEETS": 0.65, "BELOW": 0.15},
        distribution_tolerance=0.05), HR))
    api.create_rating_band(cyc["id"], create_rating_band_payload(
        label="BELOW", min_score=0, max_score=50, merit_pct=0.0), HR)
    api.create_rating_band(cyc["id"], create_rating_band_payload(
        label="MEETS", min_score=50, max_score=80, merit_pct=0.04), HR)
    api.create_rating_band(cyc["id"], create_rating_band_payload(
        label="EXCEEDS", min_score=80, max_score=100, merit_pct=0.10), HR)
    api.open_cycle(cyc["id"], HR)

    mgr = create_employee(full_name="Mgr", department="ENG")
    emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
    rev = create_review(cyc["id"], emp["id"], mgr["id"])
    drive_review_to_submitted(cyc["id"], rev["id"], emp["id"], mgr["id"],
                              self_rating="EXCEEDS", manager_rating="EXCEEDS",
                              goal_attainment=1.0)  # composite 100 -> EXCEEDS
    api.start_calibration(cyc["id"], HR)
    hrbp = create_employee(full_name="Hrbp", department="ENG")
    sess = get_success_data(api.create_calibration_session(
        create_calibration_session_payload(cyc["id"], hrbp["id"], department="ENG"),
        make_hrbp_headers(hrbp["id"])))
    res = api.balance_session(sess["id"], make_hrbp_headers(hrbp["id"]))
    validate_error(res, "ERR_DISTRIBUTION_OUT_OF_TOLERANCE")


def test_err_equity_pool_exceeded_on_approve(api):
    """PRD §3.8: "The equity pool must likewise hold: the cycle's current
    `equity_committed_total` plus this plan's `equity_refresh_units` must not
    exceed the `equity_refresh_pool`; exceeding it is rejected with
    `ERR_EQUITY_POOL_EXCEEDED` (HTTP 422)."

    Design: Corner/errors/err_equity_pool_exceeded_on_approve
    """
    # Both EXCEEDS subjects are hired in 2010 (tenure capped at 5 years), so each
    # raw_target = 400 * (1 + 0.10*5) = 600. The pool holds exactly 600 — room for
    # one grant. Both plans are created before any approval, so both see the full
    # pool and store a grant of 600. Approving the first consumes the pool
    # (equity_committed_total -> 600); the second's stored 600 then makes
    # 600 + 600 > 600, tripping ERR_EQUITY_POOL_EXCEEDED.
    ctx = setup_comp_planning_with_n_calibrated_reviews(
        n=2, band_label="EXCEEDS", band_merit_pct=0.10,
        merit_budget_pct=0.5, equity_refresh_pool=600,
        hire_date="2010-01-01T00:00:00.000Z")
    cyc_id = ctx["cycle"]["id"]
    appr_id = ctx["approver"]["id"]

    plan0 = create_comp_plan_for(cyc_id, ctx["reviews"][0]["id"], ctx["reviewers"][0]["id"])
    plan1 = create_comp_plan_for(cyc_id, ctx["reviews"][1]["id"], ctx["reviewers"][1]["id"])
    assert plan0["equity_refresh_units"] == 600
    assert plan1["equity_refresh_units"] == 600

    validate_success(api.propose_comp_plan(plan0["id"], make_manager_headers(ctx["reviewers"][0]["id"])), 200)
    validate_success(api.propose_comp_plan(plan1["id"], make_manager_headers(ctx["reviewers"][1]["id"])), 200)

    validate_success(approve_plan(plan0["id"], cyc_id, appr_id), 200)  # consumes pool
    res = approve_plan(plan1["id"], cyc_id, appr_id)
    validate_error(res, "ERR_EQUITY_POOL_EXCEEDED")


def test_err_validation_bad_cadence_enum(api):
    """PRD §3.1: "a `cadence` that is either `ANNUAL` or `SEMI_ANNUAL`." PRD §5:
    catalogue maps `ERR_VALIDATION` to HTTP 400 for a value outside declared
    field constraints.

    Design: Corner/errors/err_validation_bad_cadence_enum
    """
    res = api.create_cycle(create_cycle_payload(
        name="C", cadence="WEEKLY", merit_budget_pct=0.04, equity_refresh_pool=0,
        bell_curve_target={"MEETS": 1.0}), HR)
    validate_error(res, "ERR_VALIDATION")
