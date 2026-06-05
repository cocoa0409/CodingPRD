"""State-machine valid and invalid transitions.

Queue B (Corner) — state_machines section.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    assert_version_incremented,
    create_goal_payload,
    TEST_USERS,
    create_employee, create_open_cycle_single_band, create_review,
    drive_review_to_submitted, setup_calibrated_review_in_comp_planning,
    setup_comp_planning_with_n_calibrated_reviews, create_comp_plan_for, approve_plan,
    make_manager_headers, make_employee_headers, make_hrbp_headers,
)

HR = TEST_USERS["hr_admin_headers"]


def test_review_self_review_flow(api):
    """PRD §3.2: "The subject employee begins their self-review, moving it from
    `DRAFT` to `SELF_REVIEW`". PRD §3.2: "The subject then submits their
    self-review, advancing it from `SELF_REVIEW` to `MANAGER_REVIEW`".

    Design: Corner/state_machines/review_self_review_flow
    """
    cyc = create_open_cycle_single_band()
    mgr = create_employee(full_name="Mgr", department="ENG")
    emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
    rev = create_review(cyc["id"], emp["id"], mgr["id"])
    emp_hdr = make_employee_headers(emp["id"])
    api.begin_self_review(rev["id"], emp_hdr)
    api.patch_review(rev["id"], {"self_rating": "MEETS"}, emp_hdr)
    res = api.submit_self(rev["id"], emp_hdr)
    updated = validate_success(res, 200)
    assert updated["status"] == "MANAGER_REVIEW"


def test_goal_open_to_scored(api):
    """PRD §3.3: "A `Manager` later scores it by setting `attainment_pct` and
    moving it from `OPEN` to `SCORED`, which increments the goal's `version`."

    Design: Corner/state_machines/goal_open_to_scored
    """
    cyc = create_open_cycle_single_band()
    mgr = create_employee(full_name="Mgr", department="ENG")
    emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
    rev = create_review(cyc["id"], emp["id"], mgr["id"])
    mgr_hdr = make_manager_headers(mgr["id"])
    goal = get_success_data(api.create_goal(rev["id"], create_goal_payload(weight=1.0), mgr_hdr))
    res = api.score_goal(goal["id"], {"attainment_pct": 1.0}, mgr_hdr)
    scored = validate_success(res, 200)
    assert scored["status"] == "SCORED"
    assert scored["attainment_pct"] == 1.0


def test_feedback_pending_to_submitted(api):
    """PRD §3.3: "either submits it, supplying a numeric `score` between one and
    five inclusive and moving it from `PENDING` to `SUBMITTED`".

    Design: Corner/state_machines/feedback_pending_to_submitted
    """
    cyc = create_open_cycle_single_band()
    mgr = create_employee(full_name="Mgr", department="ENG")
    emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
    rater = create_employee(full_name="Rater", department="ENG")
    rev = create_review(cyc["id"], emp["id"], mgr["id"])
    from test_helpers import create_feedback_request_payload
    fr = get_success_data(api.create_feedback_request(
        rev["id"], create_feedback_request_payload(rater["id"], relationship="PEER"),
        make_manager_headers(mgr["id"])))
    res = api.submit_feedback(fr["id"], {"score": 4}, make_employee_headers(rater["id"]))
    submitted = validate_success(res, 200)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["score"] == 4


def test_feedback_pending_to_declined(api):
    """PRD §3.3: "or declines it, moving it from `PENDING` to `DECLINED`."

    Design: Corner/state_machines/feedback_pending_to_declined
    """
    cyc = create_open_cycle_single_band()
    mgr = create_employee(full_name="Mgr", department="ENG")
    emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
    rater = create_employee(full_name="Rater", department="ENG")
    rev = create_review(cyc["id"], emp["id"], mgr["id"])
    from test_helpers import create_feedback_request_payload
    fr = get_success_data(api.create_feedback_request(
        rev["id"], create_feedback_request_payload(rater["id"], relationship="PEER"),
        make_manager_headers(mgr["id"])))
    res = api.decline_feedback(fr["id"], make_employee_headers(rater["id"]))
    declined = validate_success(res, 200)
    assert declined["status"] == "DECLINED"


def test_calibration_open_to_balanced(api):
    """PRD §3.4: "The facilitator first balances the session, moving it from
    `OPEN` to `BALANCED`." PRD §3.4: "It computes `bell_curve_actual` over the
    in-scope `SUBMITTED` reviews".

    Design: Corner/state_machines/calibration_open_to_balanced
    """
    from test_helpers import create_calibration_session_payload, create_rating_band_payload, create_cycle_payload
    # Single MEETS band so the one in-scope review (actual 1.0) matches target 1.0.
    cyc = get_success_data(api.create_cycle(create_cycle_payload(
        name="Cal", cadence="ANNUAL", merit_budget_pct=0.5, equity_refresh_pool=0,
        bell_curve_target={"MEETS": 1.0}), HR))
    api.create_rating_band(cyc["id"], create_rating_band_payload(
        label="MEETS", min_score=0, max_score=100, merit_pct=0.04), HR)
    api.open_cycle(cyc["id"], HR)
    mgr = create_employee(full_name="Mgr", department="ENG")
    emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
    rev = create_review(cyc["id"], emp["id"], mgr["id"])
    drive_review_to_submitted(cyc["id"], rev["id"], emp["id"], mgr["id"],
                              self_rating="MEETS", manager_rating="MEETS", goal_attainment=0.6)
    api.start_calibration(cyc["id"], HR)
    hrbp = create_employee(full_name="Hrbp", department="ENG")
    sess = get_success_data(api.create_calibration_session(
        create_calibration_session_payload(cyc["id"], hrbp["id"], department="ENG"),
        make_hrbp_headers(hrbp["id"])))
    res = api.balance_session(sess["id"], make_hrbp_headers(hrbp["id"]))
    balanced = validate_success(res, 200)
    assert balanced["status"] == "BALANCED"
    assert balanced["bell_curve_actual"] is not None


def test_comp_plan_recompute_on_draft(api):
    """PRD §3.8: "A `Manager` may later recompute these on a draft plan (for
    instance after changing `plan_type` or `promo_band_jump`), which re-derives
    the figures and increments the plan's `version`." PRD §3.8: "For a
    `MERIT_AND_PROMO` plan, add a promotion uplift of three hundredths for each
    band level jumped".

    Design: Corner/state_machines/comp_plan_recompute_on_draft
    """
    ctx = setup_calibrated_review_in_comp_planning(band_label="MEETS", band_merit_pct=0.04)
    plan = create_comp_plan_for(ctx["cycle"]["id"], ctx["review"]["id"], ctx["manager"]["id"])
    assert plan["merit_pct"] == 0.04
    old_version = plan["version"]
    res = api.recompute_comp_plan(
        plan["id"], {"plan_type": "MERIT_AND_PROMO", "promo_band_jump": 1},
        make_manager_headers(ctx["manager"]["id"]))
    recomputed = validate_success(res, 200)
    assert recomputed["merit_pct"] == pytest.approx(0.04 + 0.03, abs=1e-9)
    assert_version_incremented(recomputed["version"], old_version)


def test_pip_open_to_active_to_cured(api):
    """PRD §3.7: "The HR business partner activates it, supplying a
    `duration_days` improvement window ... moving the case from `OPEN` to
    `ACTIVE`". PRD §3.7: "If the `outcome_score` is at least the `target_score`,
    the case is cured, moving from `ACTIVE` to `CURED`".

    Design: Corner/state_machines/pip_open_to_active_to_cured
    """
    pip, hrbp_id = _open_pip_via_finalize(api)
    hrbp_hdr = make_hrbp_headers(hrbp_id)
    api.activate_pip_case(pip["id"], {"duration_days": 30, "target_score": 60}, hrbp_hdr)
    res = api.assess_pip_case(pip["id"], {"outcome_score": 75}, hrbp_hdr)
    cured = validate_success(res, 200)
    assert cured["status"] == "CURED"


def test_review_submit_from_draft_invalid(api):
    """PRD §3.2: "The manager then submits the review, moving it from
    `MANAGER_REVIEW` to `SUBMITTED`." PRD §3.1: "any attempt to perform a
    transition from a state in which it is not defined is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/review_submit_from_draft_invalid
    """
    cyc = create_open_cycle_single_band()
    mgr = create_employee(full_name="Mgr", department="ENG")
    emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
    rev = create_review(cyc["id"], emp["id"], mgr["id"])  # DRAFT
    res = api.submit_review(rev["id"], make_manager_headers(mgr["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_cycle_full_lifecycle_to_closed(api):
    """PRD §3.9: "every compensation plan on the cycle must be in a terminal
    state — `APPROVED` or `REJECTED` — and the cycle's `merit_committed_total`
    must not exceed `merit_budget_pct` multiplied by the summed `base_salary` of
    the cycle's `FINALIZED` reviews. When both hold, the cycle moves to
    `CLOSED`".

    Design: Corner/state_machines/cycle_full_lifecycle_to_closed
    """
    ctx = setup_comp_planning_with_n_calibrated_reviews(
        n=1, band_label="MEETS", band_merit_pct=0.04,
        merit_budget_pct=0.5, equity_refresh_pool=100000)
    cyc_id = ctx["cycle"]["id"]
    plan = create_comp_plan_for(cyc_id, ctx["reviews"][0]["id"], ctx["reviewers"][0]["id"])
    validate_success(api.propose_comp_plan(plan["id"], make_manager_headers(ctx["reviewers"][0]["id"])), 200)
    validate_success(approve_plan(plan["id"], cyc_id, ctx["approver"]["id"]), 200)
    res = api.close_cycle(cyc_id, HR)
    closed = validate_success(res, 200)
    assert closed["status"] == "CLOSED"


# --------------------------------------------------------------------------
# Helper: reach an OPEN PipCase via calibration finalize landing in a
# pip_eligible band, so PIP-lifecycle tests have a real subject case.
# --------------------------------------------------------------------------
def _open_pip_via_finalize(api):
    """Single BELOW(pip_eligible) band cycle; one review lands BELOW (composite
    0) -> finalize cascade-creates an OPEN PipCase. Returns (pip_case, hrbp_id)."""
    from test_helpers import (create_cycle_payload, create_rating_band_payload,
                              create_calibration_session_payload)
    cyc = get_success_data(api.create_cycle(create_cycle_payload(
        name="Pip", cadence="ANNUAL", merit_budget_pct=0.5, equity_refresh_pool=0,
        bell_curve_target={"BELOW": 1.0}), HR))
    api.create_rating_band(cyc["id"], create_rating_band_payload(
        label="BELOW", min_score=0, max_score=100, merit_pct=0.0, pip_eligible=True), HR)
    api.open_cycle(cyc["id"], HR)
    mgr = create_employee(full_name="Mgr", department="ENG")
    emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
    rev = create_review(cyc["id"], emp["id"], mgr["id"])
    drive_review_to_submitted(cyc["id"], rev["id"], emp["id"], mgr["id"],
                              self_rating="BELOW", manager_rating="BELOW", goal_attainment=0.0)
    api.start_calibration(cyc["id"], HR)
    hrbp = create_employee(full_name="Hrbp", department="ENG")
    sess = get_success_data(api.create_calibration_session(
        create_calibration_session_payload(cyc["id"], hrbp["id"], department="ENG"),
        make_hrbp_headers(hrbp["id"])))
    api.balance_session(sess["id"], make_hrbp_headers(hrbp["id"]))
    api.finalize_session(sess["id"], make_hrbp_headers(hrbp["id"]))
    data, _ = _list_pip(api, rev["id"])
    return data[0], hrbp["id"]


def _list_pip(api, review_id):
    from test_helpers import validate_paginated
    return validate_paginated(api.list_review_pip_cases(review_id, HR))
