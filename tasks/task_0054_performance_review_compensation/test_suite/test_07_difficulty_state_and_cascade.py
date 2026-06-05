"""Difficulty queue: non-linear state machines, transitive cascade chains,
cross-entity state dependencies.

Queue A (Difficulty) — rules non_linear_state_machine, transitive_cascade,
cross_entity_state_dependency.

SKIPPED (PRD-first filter, not emitted):
- Difficulty/transitive_cascade/approve_cascade_depth3 — PRD §3.8 cures an OPEN
  PipCase on approve only "if the review's band is no longer `pip_eligible`". A
  PipCase is created at finalize precisely because the final_rating band IS
  pip_eligible; for that band to become non-pip-eligible by approval time the
  review's final_rating would have to change after PipCase creation, which PRD
  prose offers no deterministic, uniquely-derivable mechanism to reach (no
  re-finalize/re-rate endpoint is specified). The cure-on-approve branch is thus
  not constructible from PRD alone, so the instance is skipped rather than
  weakened.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    create_cycle_payload, create_rating_band_payload, create_calibration_session_payload,
    create_review_payload,
    TEST_USERS,
    create_employee, create_open_cycle_single_band, create_draft_cycle_single_band,
    create_review, drive_review_to_submitted,
    setup_calibrated_review_in_comp_planning, create_comp_plan_for,
    make_manager_headers, make_employee_headers, make_hrbp_headers,
)

HR = TEST_USERS["hr_admin_headers"]


def _submitted_review(api):
    """OPEN single-MEETS-band cycle + one SUBMITTED review.
    Returns (cycle, mgr, emp, review)."""
    cyc = create_open_cycle_single_band()
    mgr = create_employee(full_name="Mgr", department="ENG")
    emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
    rev = create_review(cyc["id"], emp["id"], mgr["id"])
    review = drive_review_to_submitted(cyc["id"], rev["id"], emp["id"], mgr["id"],
                                       self_rating="MEETS", manager_rating="MEETS",
                                       goal_attainment=0.6)
    return cyc, mgr, emp, review


# ==========================================================================
# Rule: non_linear_state_machine
# ==========================================================================
class TestReviewReturnRevertCycle:
    """Review revision loop: SUBMITTED -> RETURNED -> MANAGER_REVIEW -> SUBMITTED."""

    def test_return_then_reopen_then_resubmit(self, api):
        """PRD §3.2: "an `HrbpPartner` may send it back for rework, transitioning
        it from `SUBMITTED` to `RETURNED`." PRD §3.2: "The authoring manager then
        reopens the returned review, moving it from `RETURNED` back to
        `MANAGER_REVIEW` for another pass". PRD §3.2: "The manager then submits
        the review, moving it from `MANAGER_REVIEW` to `SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/review_return_revert_cycle
        """
        cyc, mgr, emp, review = _submitted_review(api)
        hrbp = create_employee(full_name="Hrbp", department="ENG")
        validate_success(api.return_review(review["id"], make_hrbp_headers(hrbp["id"])), 200)
        validate_success(api.reopen_review(review["id"], make_manager_headers(mgr["id"])), 200)
        resubmitted = validate_success(api.submit_review(review["id"], make_manager_headers(mgr["id"])), 200)
        assert resubmitted["status"] == "SUBMITTED"

    def test_returned_status_observable_mid_loop(self, api):
        """PRD §3.2: "an `HrbpPartner` may send it back for rework, transitioning
        it from `SUBMITTED` to `RETURNED`."

        Design: Difficulty/non_linear_state_machine/review_return_revert_cycle
        """
        cyc, mgr, emp, review = _submitted_review(api)
        hrbp = create_employee(full_name="Hrbp", department="ENG")
        returned = validate_success(api.return_review(review["id"], make_hrbp_headers(hrbp["id"])), 200)
        assert returned["status"] == "RETURNED"


class TestPipCaseBranchCuredVsFailed:
    """PipCase branches ACTIVE -> {CURED, FAILED} with divergent side-effects
    (FAILED sets Employee.is_active=false)."""

    def test_failed_branch_separates_employee(self, api):
        """PRD §3.7: "If the `outcome_score` is below the `target_score`, the case
        fails, moving from `ACTIVE` to `FAILED`; failure additionally sets the
        subject `Employee`'s `is_active` to false to record the separation".

        Design: Difficulty/non_linear_state_machine/pipcase_branch_cured_vs_failed
        """
        pip, hrbp_id, emp_id = _open_pip(api)
        hrbp_hdr = make_hrbp_headers(hrbp_id)
        api.activate_pip_case(pip["id"], {"duration_days": 60, "target_score": 70}, hrbp_hdr)
        failed = validate_success(api.assess_pip_case(pip["id"], {"outcome_score": 65}, hrbp_hdr), 200)
        assert failed["status"] == "FAILED"
        emp = validate_success(api.get_employee(emp_id, HR), 200)
        assert emp["is_active"] is False

    def test_cured_branch_leaves_employee_active(self, api):
        """PRD §3.7: "If the `outcome_score` is at least the `target_score`, the
        case is cured, moving from `ACTIVE` to `CURED`". PRD §3.7: "These two
        branches are the only outcomes of an assessment, and which one fires
        depends solely on the comparison of the outcome to the target."

        Design: Difficulty/non_linear_state_machine/pipcase_branch_cured_vs_failed
        """
        pip, hrbp_id, emp_id = _open_pip(api)
        hrbp_hdr = make_hrbp_headers(hrbp_id)
        api.activate_pip_case(pip["id"], {"duration_days": 60, "target_score": 70}, hrbp_hdr)
        cured = validate_success(api.assess_pip_case(pip["id"], {"outcome_score": 75}, hrbp_hdr), 200)
        assert cured["status"] == "CURED"
        emp = validate_success(api.get_employee(emp_id, HR), 200)
        assert emp["is_active"] is True


# ==========================================================================
# Rule: transitive_cascade (finalize chain; approve chain skipped — see header)
# ==========================================================================
class TestFinalizeCascadeDepth3:
    """finalize -> Review SUBMITTED->CALIBRATED (link1) -> pip_eligible
    final_rating cascade-creates PipCase OPEN (link2)."""

    def test_finalize_calibrates_and_creates_pip(self, api):
        """PRD §3.4: "For each in-scope `SUBMITTED` review it sets the review's
        `final_rating` by the calibration algorithm (Section 3.6) and transitions
        that review from `SUBMITTED` to `CALIBRATED`. For each review that is
        newly `CALIBRATED` and whose `final_rating` falls in a `pip_eligible`
        band, it cascade-creates a `PipCase` for that review in the `OPEN` state."

        Design: Difficulty/transitive_cascade/finalize_cascade_depth3
        """
        review, _ = _finalize_below_pip(api)
        assert review["status"] == "CALIBRATED"
        assert review["final_rating"] == "BELOW"
        data, _ = validate_paginated(api.list_review_pip_cases(review["id"], HR))
        assert len(data) == 1
        assert data[0]["status"] == "OPEN"

    def test_finalize_pip_references_review_and_employee(self, api):
        """PRD §3.7: "A `PipCase` is opened automatically when calibration lands a
        review in a `pip_eligible` band, as described above; it references the
        triggering `review_id` and the subject `employee_id` and starts in
        `OPEN`."

        Design: Difficulty/transitive_cascade/finalize_cascade_depth3
        """
        review, _ = _finalize_below_pip(api)
        data, _ = validate_paginated(api.list_review_pip_cases(review["id"], HR))
        assert data[0]["review_id"] == review["id"]
        assert data[0]["employee_id"] == review["employee_id"]


# ==========================================================================
# Rule: cross_entity_state_dependency
# ==========================================================================
class TestReviewSubmitRequiresCycleOpen:
    """Review can begin-self-review only when parent ReviewCycle.status == OPEN."""

    def test_begin_self_review_blocked_when_cycle_draft(self, api):
        """PRD §3.2: "The subject employee begins their self-review, moving it
        from `DRAFT` to `SELF_REVIEW`; this is allowed only while the parent cycle
        is `OPEN`". PRD §3.1: "any attempt to perform a transition from a state in
        which it is not defined is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/review_submit_requires_cycle_open
        """
        cyc = create_draft_cycle_single_band()  # DRAFT, not opened
        mgr = create_employee(full_name="Mgr", department="ENG")
        emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
        rev = get_success_data(api.create_review(
            create_review_payload(cyc["id"], emp["id"], mgr["id"]), HR))
        res = api.begin_self_review(rev["id"], make_employee_headers(emp["id"]))
        validate_error(res, "ERR_INVALID_STATE")

    def test_begin_self_review_succeeds_when_cycle_open(self, api):
        """PRD §3.2: "The subject employee begins their self-review, moving it
        from `DRAFT` to `SELF_REVIEW`; this is allowed only while the parent cycle
        is `OPEN` and only when the acting employee is the review's subject."

        Design: Difficulty/cross_entity_state_dependency/review_submit_requires_cycle_open
        """
        cyc = create_open_cycle_single_band()  # OPEN
        mgr = create_employee(full_name="Mgr", department="ENG")
        emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
        rev = create_review(cyc["id"], emp["id"], mgr["id"])
        res = api.begin_self_review(rev["id"], make_employee_headers(emp["id"]))
        moved = validate_success(res, 200)
        assert moved["status"] == "SELF_REVIEW"


class TestCompPlanProposeRequiresReviewCalibrated:
    """CompPlan can move DRAFT->PROPOSED only when its referenced Review is
    CALIBRATED and the parent cycle is COMP_PLANNING."""

    def test_propose_on_calibrated_review_succeeds(self, api):
        """PRD §3.8: "Proposal requires that the plan's review is `CALIBRATED`,
        that the parent cycle is in `COMP_PLANNING`, and that `merit_amount` and
        `equity_refresh_units` have been computed; it increments the plan's
        `version`."

        Design: Difficulty/cross_entity_state_dependency/compplan_propose_requires_review_calibrated
        """
        ctx = setup_calibrated_review_in_comp_planning(band_label="MEETS", band_merit_pct=0.04)
        rev = get_success_data(api.get_review(ctx["review"]["id"], HR))
        assert rev["status"] == "CALIBRATED"
        plan = create_comp_plan_for(ctx["cycle"]["id"], ctx["review"]["id"], ctx["manager"]["id"])
        proposed = validate_success(
            api.propose_comp_plan(plan["id"], make_manager_headers(ctx["manager"]["id"])), 200)
        assert proposed["status"] == "PROPOSED"

    def test_propose_already_proposed_invalid_state(self, api):
        """PRD §3.8: "Proposal requires that the plan's review is `CALIBRATED`".
        PRD §3.1: "any attempt to perform a transition from a state in which it is
        not defined is rejected with `ERR_INVALID_STATE` (HTTP 409)." A plan that
        is already PROPOSED is no longer in DRAFT, so re-proposing is undefined.

        Design: Difficulty/cross_entity_state_dependency/compplan_propose_requires_review_calibrated
        """
        ctx = setup_calibrated_review_in_comp_planning(band_label="MEETS", band_merit_pct=0.04)
        plan = create_comp_plan_for(ctx["cycle"]["id"], ctx["review"]["id"], ctx["manager"]["id"])
        validate_success(api.propose_comp_plan(plan["id"], make_manager_headers(ctx["manager"]["id"])), 200)
        res = api.propose_comp_plan(plan["id"], make_manager_headers(ctx["manager"]["id"]))
        validate_error(res, "ERR_INVALID_STATE")


# ==========================================================================
# Local scenario helpers
# ==========================================================================
def _below_pip_cycle_finalized(api):
    """BELOW(pip_eligible) single-band cycle; one review lands BELOW (composite 0)
    -> finalize cascade-creates an OPEN PipCase. Returns (review_id, emp_id, hrbp_id)."""
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
    return rev["id"], emp["id"], hrbp["id"]


def _open_pip(api):
    rev_id, emp_id, hrbp_id = _below_pip_cycle_finalized(api)
    data, _ = validate_paginated(api.list_review_pip_cases(rev_id, HR))
    return data[0], hrbp_id, emp_id


def _finalize_below_pip(api):
    rev_id, emp_id, hrbp_id = _below_pip_cycle_finalized(api)
    review = get_success_data(api.get_review(rev_id, HR))
    return review, hrbp_id
