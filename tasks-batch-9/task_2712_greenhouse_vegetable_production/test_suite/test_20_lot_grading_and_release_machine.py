"""Non-linear state machines: the harvest lot's two parallel dimensions and the
bounded approve / return-for-revision cycle on a biological-control request.

A harvest lot carries a grading dimension and a cold-chain dimension that advance
independently of one another, while a release request cycles between REQUESTED and
APPROVED a bounded number of times.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_release,
    create_scout_worker,
    make_harvest_supervisor_headers,
    make_ipm_coordinator_headers,
    read_release,
    request_release,
    setup_registered_lot,
    setup_scout_alert_zone,
    transition_release_as_coordinator,
    validate_error,
    validate_success,
)

QI = TEST_USERS["quality_inspector_headers"]


class TestHarvestLotParallelDimensions:
    """The grading and cold-chain dimensions of one lot never gate each other."""

    def test_cold_chain_reaches_cold_held_while_the_lot_is_still_ungraded(self, api):
        """PRD §3.9: "A lot may be pre-cooled before it is graded or graded before it is pre-cooled; the two dimensions cross-reference each other only at the specific points named below."

        Design: Difficulty/non_linear_state_machine/harvest_lot_grading_and_cold_chain_dimensions_advance_independently
        """
        state = setup_registered_lot()
        lot_id = state["lot"]["id"]

        assert state["lot"]["grading_status"] == "UNGRADED", (
            f"a freshly registered lot is UNGRADED, got {state['lot']['grading_status']}"
        )
        assert state["lot"]["cold_chain_status"] == "AMBIENT", (
            f"a freshly registered lot is AMBIENT, got {state['lot']['cold_chain_status']}"
        )

        after_precool = validate_success(
            api.create_cold_chain_event(
                lot_id, {"to_status": "PRECOOLED", "pulp_temp_c": 10.0}, QI
            )
        )
        assert after_precool["cold_chain_status"] == "PRECOOLED"
        assert after_precool["grading_status"] == "UNGRADED", (
            "pre-cooling must not touch the grading dimension, got "
            f"{after_precool['grading_status']}"
        )

        after_cold_hold = validate_success(
            api.create_cold_chain_event(
                lot_id, {"to_status": "COLD_HELD", "pulp_temp_c": 6.0}, QI
            )
        )
        assert after_cold_hold["cold_chain_status"] == "COLD_HELD"
        assert after_cold_hold["grading_status"] == "UNGRADED", (
            "cold holding must not touch the grading dimension, got "
            f"{after_cold_hold['grading_status']}"
        )

    def test_grade_then_regrade_leaves_the_cold_chain_dimension_at_cold_held(self, api):
        """PRD §3.9: "A lot may be pre-cooled before it is graded or graded before it is pre-cooled; the two dimensions cross-reference each other only at the specific points named below."

        Design: Difficulty/non_linear_state_machine/harvest_lot_grading_and_cold_chain_dimensions_advance_independently
        """
        state = setup_registered_lot()
        lot_id = state["lot"]["id"]
        supervisor = make_harvest_supervisor_headers(state["harvest_worker"]["id"])

        validate_success(
            api.create_cold_chain_event(
                lot_id, {"to_status": "PRECOOLED", "pulp_temp_c": 10.0}, QI
            )
        )
        validate_success(
            api.create_cold_chain_event(
                lot_id, {"to_status": "COLD_HELD", "pulp_temp_c": 6.0}, QI
            )
        )

        graded = validate_success(
            api.grade_harvest_lot(
                lot_id,
                {"grade_a_lbs": 1200.00, "grade_b_lbs": 700.00, "cull_lbs": 100.00},
                supervisor,
            )
        )
        assert graded["grading_status"] == "GRADED"
        assert graded["cold_chain_status"] == "COLD_HELD", (
            "grading must not drag the cold chain, got "
            f"{graded['cold_chain_status']}"
        )

        regraded = validate_success(
            api.regrade_harvest_lot(
                lot_id,
                {
                    "grade_a_lbs": 1100.00,
                    "grade_b_lbs": 800.00,
                    "cull_lbs": 100.00,
                    "expected_lot_version": graded["version"],
                },
                supervisor,
            )
        )
        assert regraded["grading_status"] == "REGRADED"
        assert regraded["cold_chain_status"] == "COLD_HELD", (
            "regrading must not drag the cold chain, got "
            f"{regraded['cold_chain_status']}"
        )

    def test_regrade_recomputes_pack_out_and_availability_and_counts_the_pass(self, api):
        """PRD §3.9: "A successful regrade runs the **regrade variant** of the pack-out calculation, which subtracts the already-allocated pounds from the new split when computing `available_a_lbs` and `available_b_lbs`, recomputes `pack_out_pct`, increments `regrade_count` by one and increments the lot's `version` by one."

        Design: Difficulty/non_linear_state_machine/harvest_lot_grading_and_cold_chain_dimensions_advance_independently
        """
        state = setup_registered_lot()
        lot_id = state["lot"]["id"]
        supervisor = make_harvest_supervisor_headers(state["harvest_worker"]["id"])

        graded = validate_success(
            api.grade_harvest_lot(
                lot_id,
                {"grade_a_lbs": 1200.00, "grade_b_lbs": 700.00, "cull_lbs": 100.00},
                supervisor,
            )
        )
        assert graded["regrade_count"] == 0, "the initial grade is not a regrade pass"

        regraded = validate_success(
            api.regrade_harvest_lot(
                lot_id,
                {
                    "grade_a_lbs": 1100.00,
                    "grade_b_lbs": 800.00,
                    "cull_lbs": 100.00,
                    "expected_lot_version": graded["version"],
                },
                supervisor,
            )
        )

        assert regraded["regrade_count"] == 1, (
            f"regrade_count increments by one, got {regraded['regrade_count']}"
        )
        assert regraded["version"] == graded["version"] + 1, (
            "the lot version advances on a regrade, got "
            f"{regraded['version']} from {graded['version']}"
        )
        assert regraded["pack_out_pct"] == pytest.approx(95.00, abs=0.01), (
            f"pack_out_pct for 1100 A plus 800 B of 2000 lbs is 95.00, got {regraded['pack_out_pct']}"
        )
        assert regraded["available_a_lbs"] == pytest.approx(1100.00, abs=0.01), (
            f"expected available_a_lbs 1100.00, got {regraded['available_a_lbs']}"
        )
        assert regraded["available_b_lbs"] == pytest.approx(800.00, abs=0.01), (
            f"expected available_b_lbs 800.00, got {regraded['available_b_lbs']}"
        )


def _release_awaiting_decision():
    """A SCOUT_ALERT compartment, a scout-filed observation and one REQUESTED release.

    A second SCOUT worker acts as the coordinator so segregation of duties is satisfiable.
    """
    state = setup_scout_alert_zone()
    state["coordinator"] = create_scout_worker(
        full_name="Tomas Reyn", hourly_rate_usd=26.00
    )
    state["release"] = request_release(
        state["zone"]["id"],
        state["observation"]["id"],
        state["scout"]["id"],
        planned_release_count=6000,
        planned_release_date="2026-08-06",
    )
    return state


class TestReleaseRevisionCycle:
    """REQUESTED -> APPROVED -> REQUESTED is a real cycle with a hard revision cap."""

    def test_returning_an_approved_request_for_revision_clears_the_approval(self, api):
        """PRD §3.6: "A coordinator may return an approved request for revision, moving `APPROVED` → `REQUESTED` with a `decision_reason`, which increments `revision_count` by one, resets `approved_release_count` to null, clears `decided_by_worker_id`, and is subject to the same segregation-of-duties comparison against the observation's `observed_by_worker_id`."

        Design: Difficulty/non_linear_state_machine/biocontrol_release_approve_return_revision_loop_is_bounded_at_two_passes
        """
        state = _release_awaiting_decision()
        release_id = state["release"]["id"]
        coordinator_id = state["coordinator"]["id"]

        approve_release(release_id, coordinator_id)
        returned = transition_release_as_coordinator(
            release_id,
            "REQUESTED",
            coordinator_id,
            decision_reason="Split the release across two days",
        )

        assert returned["status"] == "REQUESTED", (
            f"a returned request goes back to REQUESTED, got {returned['status']}"
        )
        assert returned["revision_count"] == 1, (
            f"revision_count increments by one on a return, got {returned['revision_count']}"
        )
        assert returned["approved_release_count"] is None, (
            "approved_release_count resets to null on a return, got "
            f"{returned['approved_release_count']}"
        )
        assert returned["decided_by_worker_id"] is None, (
            "decided_by_worker_id is cleared on a return, got "
            f"{returned['decided_by_worker_id']}"
        )

    def test_reapproval_takes_the_revised_count_and_records_the_coordinator(self, api):
        """PRD §3.6: "`approved_release_count` becomes `revised_release_count` when one was supplied and `planned_release_count` otherwise, `decided_by_worker_id` records the coordinator, and the request moves `REQUESTED` → `APPROVED`."

        Design: Difficulty/non_linear_state_machine/biocontrol_release_approve_return_revision_loop_is_bounded_at_two_passes
        """
        state = _release_awaiting_decision()
        release_id = state["release"]["id"]
        coordinator_id = state["coordinator"]["id"]

        first_approval = approve_release(release_id, coordinator_id)
        assert first_approval["status"] == "APPROVED"
        assert first_approval["approved_release_count"] == pytest.approx(6000, abs=0.01), (
            "with no revised count the planned 6000 agents are approved, got "
            f"{first_approval['approved_release_count']}"
        )
        assert first_approval["decided_by_worker_id"] == coordinator_id

        transition_release_as_coordinator(
            release_id,
            "REQUESTED",
            coordinator_id,
            decision_reason="Coordinator wants a fresh scouting count first",
        )
        second_approval = approve_release(
            release_id, coordinator_id, revised_release_count=5500
        )

        assert second_approval["status"] == "APPROVED"
        assert second_approval["approved_release_count"] == pytest.approx(
            5500, abs=0.01
        ), (
            "a supplied revised_release_count becomes approved_release_count, got "
            f"{second_approval['approved_release_count']}"
        )
        assert second_approval["decided_by_worker_id"] == coordinator_id

    def test_a_third_return_for_revision_is_refused_once_two_revisions_are_spent(
        self, api
    ):
        """PRD §3.6: "This is a genuine cycle: the pair `REQUESTED` → `APPROVED` → `REQUESTED` may repeat while `revision_count` remains below 2, and the third attempt to send it back — when `revision_count` already equals 2 — is rejected with `ERR_MAX_REVISIONS_EXCEEDED`, closing the loop."

        Design: Difficulty/non_linear_state_machine/biocontrol_release_approve_return_revision_loop_is_bounded_at_two_passes
        """
        state = _release_awaiting_decision()
        release_id = state["release"]["id"]
        coordinator_id = state["coordinator"]["id"]
        coordinator = make_ipm_coordinator_headers(coordinator_id)

        approve_release(release_id, coordinator_id)
        first_return = transition_release_as_coordinator(
            release_id,
            "REQUESTED",
            coordinator_id,
            decision_reason="Split the release across two days",
        )
        assert first_return["revision_count"] == 1

        approve_release(release_id, coordinator_id, revised_release_count=5500)
        second_return = transition_release_as_coordinator(
            release_id,
            "REQUESTED",
            coordinator_id,
            decision_reason="Coordinator wants a fresh scouting count first",
        )
        assert second_return["revision_count"] == 2, (
            "two passes round the loop spend both revisions, got "
            f"{second_return['revision_count']}"
        )

        approve_release(release_id, coordinator_id)
        refused = api.transition_bio_control_release(
            release_id,
            {"to_status": "REQUESTED", "decision_reason": "Third revision attempt"},
            coordinator,
        )
        validate_error(refused, ApiErrorId.ERR_MAX_REVISIONS_EXCEEDED.value)

        after = read_release(release_id)
        assert after["status"] == "APPROVED", (
            f"the refused return leaves the request APPROVED, got {after['status']}"
        )
        assert after["revision_count"] == 2, (
            f"the refused return does not spend a revision, got {after['revision_count']}"
        )
