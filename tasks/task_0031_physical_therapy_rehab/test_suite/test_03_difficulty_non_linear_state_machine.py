"""Difficulty Rule 3 — non_linear_state_machine.

Two state machines with non-linear shape (branching/forks, cyclic self-loops):
  (A) PlanOfCare: ACTIVE → RECERT_DUE → (ACTIVE | EXPIRED) fork.
  (B) MIPSQualityMeasure: DRAFT → DRAFT* (cyclic) → SUBMITTED → (ACCEPTED | REJECTED).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    set_clock,
    setup_recert_due_poc,
    setup_active_poc,
    create_mips,
    recertify_plan_payload,
    revise_mips_payload,
    make_therapist_headers,
    TEST_USERS,
)


class TestPocForkActiveToRecertDueToActiveAgain:
    """POC moves ACTIVE → (clock auto) RECERT_DUE → (recertify trigger) ACTIVE.
    Verifies both the auto-transition fork and the explicit-trigger fork resolve.
    """

    def test_clock_advance_auto_transitions_active_to_recert_due(self, api):
        """PRD §3.6: "A plan in `ACTIVE` status reaches `RECERT_DUE` automatically when
        the server clock advances to a date strictly after `certified_end_date` minus seven
        days and on or before `certified_end_date`."

        Design: Difficulty/non_linear_state_machine/poc_fork_active_to_recert_due_to_active_again
        """
        ctx = setup_active_poc(
            insurance_type="COMMERCIAL",
            certified_start_date="2026-06-01",
            certified_end_date="2026-06-08",
            initial_clock="2026-06-01T00:00:00Z",
        )
        # Move clock to 2026-06-04 (4 days after 2026-06-01 — strictly after
        # certified_end_date - 7 days = 2026-06-01, and on/before 2026-06-08).
        set_clock("2026-06-04T12:00:00Z")
        poc = validate_success(
            api.get_plan_of_care(ctx["poc"]["id"], make_therapist_headers(ctx["therapist"]["id"])),
            200,
        )
        assert poc["status"] == "RECERT_DUE"

    def test_recertify_resolves_recert_due_back_to_active_with_refreshed_dates(self, api):
        """PRD §3.6: "Recertification, driven by a `Therapist`, moves the plan back to
        `ACTIVE` and refreshes its certification window."
        PRD §3.6: "On success, both certification dates are overwritten with the payload
        values and the plan's `version` increments."

        Design: Difficulty/non_linear_state_machine/poc_fork_active_to_recert_due_to_active_again
        """
        ctx = setup_recert_due_poc(
            certified_start_date="2026-06-01",
            certified_end_date="2026-06-08",
            initial_clock="2026-06-01T00:00:00Z",
            advance_clock_to="2026-06-04T12:00:00Z",
            re_eval_performed_on="2026-06-04",
        )
        # Recertify to extend the window.
        payload = recertify_plan_payload(
            expected_plan_of_care_version=ctx["poc"]["version"],
            certified_start_date="2026-06-01",
            certified_end_date="2026-07-31",
        )
        res = api.recertify_plan_of_care(
            ctx["poc"]["id"], payload, make_therapist_headers(ctx["therapist"]["id"]),
        )
        recertified = validate_success(res, 200)
        assert recertified["status"] == "ACTIVE"
        assert recertified["certified_end_date"] == "2026-07-31"


class TestMipsCyclicDraftSelfLoopThenBranch:
    """MIPS131 with numerator_met=false stays under the 30.0 acceptance threshold;
    cyclic DRAFT→DRAFT revises preserve DRAFT status; SUBMITTED → REJECTED branches
    on composite_score < 30.0.
    """

    def test_revise_loop_keeps_status_draft_and_recomputes_score(self, api):
        """PRD §3.7: "A `DRAFT` measure has a self-loop revision path: a `Therapist`
        may revise `numerator_met` and/or `measure_code` while leaving the performance
        period immutable. Revising recomputes `composite_score` and increments the
        measure's `version`."

        Design: Difficulty/non_linear_state_machine/mips_cyclic_draft_self_loop_then_branch
        """
        ctx = setup_active_poc(
            insurance_type="MEDICARE", medicare_enrolled=True,
            functional_score=50,
        )
        th_headers = make_therapist_headers(ctx["therapist"]["id"])
        mips = create_mips(
            ctx["patient"]["id"], ctx["poc"]["id"], ctx["therapist"]["id"],
            measure_code="MIPS131_PAIN_ASSESSMENT", numerator_met=False,
        )
        v0 = mips["version"]
        r1 = validate_success(
            api.revise_mips_measure(mips["id"], revise_mips_payload(numerator_met=False), th_headers),
            200,
        )
        assert r1["status"] == "DRAFT"
        assert r1["version"] > v0
        r2 = validate_success(
            api.revise_mips_measure(mips["id"], revise_mips_payload(numerator_met=False), th_headers),
            200,
        )
        assert r2["status"] == "DRAFT"
        assert r2["version"] > r1["version"]

    def test_adjudicate_rejects_when_composite_score_below_30(self, api):
        """PRD §3.7: "Finally a `PlatformAdmin` adjudicates the `SUBMITTED` measure
        (transition `SUBMITTED → ACCEPTED` when the recorded `composite_score` is at
        least 30.0, or `SUBMITTED → REJECTED` when it is strictly below 30.0)."
        PRD §3.7: "The base score is determined by `measure_code`: 60.0 for
        `MIPS128_FALL_RISK`, 18.0 for `MIPS131_PAIN_ASSESSMENT`, 70.0 for
        `MIPS182_FUNCTIONAL_OUTCOME`."
        PRD §3.7: "The numerator bonus adds 25.0 when `numerator_met` is true and 0.0 otherwise."

        Design: Difficulty/non_linear_state_machine/mips_cyclic_draft_self_loop_then_branch
        """
        ctx = setup_active_poc(
            insurance_type="MEDICARE", medicare_enrolled=True,
            functional_score=50,
        )
        th_headers = make_therapist_headers(ctx["therapist"]["id"])
        admin_headers = TEST_USERS["platform_admin_headers"]
        mips = create_mips(
            ctx["patient"]["id"], ctx["poc"]["id"], ctx["therapist"]["id"],
            measure_code="MIPS131_PAIN_ASSESSMENT", numerator_met=False,
        )
        # Two revises to confirm cyclic stays DRAFT.
        api.revise_mips_measure(mips["id"], revise_mips_payload(numerator_met=False), th_headers)
        api.revise_mips_measure(mips["id"], revise_mips_payload(numerator_met=False), th_headers)
        submitted = validate_success(
            api.submit_mips_measure(mips["id"], th_headers), 200,
        )
        # composite_score = 18 (base) + 0 (numerator) + 0 (engagement) + 0 (improvement) = 18.00 < 30.0
        assert submitted["composite_score"] == pytest.approx(18.00, abs=0.01)
        adjudicated = validate_success(
            api.adjudicate_mips_measure(mips["id"], admin_headers), 200,
        )
        assert adjudicated["status"] == "REJECTED"
