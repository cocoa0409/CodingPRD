"""Three-link cascades where each link is caused by the one before it."""

import pytest
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    assert_bay_ledger,
    assert_project_state,
    assert_skid_state,
    fixtures,
    make_application_engineer_headers,
    make_engineer_of_record_headers,
    make_fabrication_manager_headers,
    make_quality_engineer_headers,
)


class TestFailedFactoryTestPropagatesThreeLevels:
    """A failed witness result reverts the skid, holds the package, holds the project."""

    FAIL_NOTE = "Membrane rack header weld leaked at 1.5x design pressure"

    def _failed_run(self, api):
        state = fixtures.scheduled_fat_run_project(api)
        state["witnessed"] = validate_success(
            api.witness_fat_run(
                state["fat_run"]["id"],
                {
                    "result": "FAIL",
                    "punchlist_item_count": 7,
                    "result_note": self.FAIL_NOTE,
                },
                make_quality_engineer_headers(),
            )
        )
        return state

    def test_failure_reverts_the_mechanical_axis_and_preserves_controls(self, api):
        """The skid reverts to REWORK and blocks, while its controls integration survives.

        Link one of the rework cascade says "the skid's mechanical axis reverts
        `MECH_COMPLETE → REWORK`, `rework_count` increments by 1, `fat_readiness`
        recomputes to `BLOCKED`, and the skid's `version` advances by 1 -- while
        `controls_status` is deliberately preserved, since a mechanical failure does
        not undo controls integration."

        Design: Difficulty/transitive_cascade/fat_failure_propagates_skid_to_package_to_project
        """
        state = self._failed_run(api)

        run = state["witnessed"]
        assert run["status"] == "FAILED"
        assert run["punchlist_item_count"] == 7
        assert run["witnessed_by_user_id"] == "qa-1"

        skid = validate_success(
            api.get_skid(state["skid"]["id"], make_fabrication_manager_headers())
        )
        assert_skid_state(
            skid,
            mechanical_status="REWORK",
            controls_status="CONTROLS_COMPLETE",
            fat_readiness="BLOCKED",
            rework_count=1,
        )

    def test_failure_holds_the_package_and_the_project_and_frees_the_bay(self, api):
        """The package moves to REWORK_HOLD, the project posture becomes HELD, the ledger empties.

        Link two says "the parent package transitions
        `RELEASED_FOR_FAB → REWORK_HOLD` and its `version` advances by 1", and link
        three says "the project's `delivery_posture` becomes `HELD`." Every witnessed
        outcome also "releases the run's footprint-minutes from the bay ledger by
        subtracting exactly `footprint_sf` multiplied by `duration_minutes`."

        Design: Difficulty/transitive_cascade/fat_failure_propagates_skid_to_package_to_project
        """
        state = self._failed_run(api)

        package = validate_success(
            api.get_equipment_package(
                state["package"]["id"], make_application_engineer_headers()
            )
        )
        assert package["status"] == "REWORK_HOLD"

        project = validate_success(
            api.get_project(state["project"]["id"], make_application_engineer_headers())
        )
        assert_project_state(project, status="IN_FABRICATION", delivery_posture="HELD")

        bay = validate_success(
            api.get_test_bay(state["test_bay"]["id"], make_fabrication_manager_headers())
        )
        assert_bay_ledger(bay, 0)


class TestSubmittalRejectionWithdrawsAndRescores:
    """Rejection withdraws the pending deviations, which raises the compliance score."""

    REJECT_NOTE = "Proposed rack is not equal to the named basis"

    def _rejected_submittal(self, api):
        state = fixtures.project_with_approved_package(api)
        submittal = fixtures.add_submittal(api, state["project"]["id"])
        moderate = fixtures.add_deviation(api, submittal["id"], "MODERATE")
        minor = fixtures.add_deviation(
            api,
            submittal["id"],
            "MINOR",
            spec_paragraph="2.05.C",
            description="Nameplate layout differs from named basis",
        )
        api.submit_or_equal_submittal(submittal["id"], make_application_engineer_headers())
        state["submittal"] = submittal
        state["moderate_deviation"] = moderate
        state["minor_deviation"] = minor
        state["decided"] = validate_success(
            api.decide_or_equal_submittal(
                submittal["id"],
                {"decision": "REJECTED", "decision_note": self.REJECT_NOTE},
                make_engineer_of_record_headers(),
            )
        )
        return state

    def test_rejection_withdraws_every_pending_deviation_and_zeroes_its_penalty(
        self, api
    ):
        """Both disclosed deviations end WITHDRAWN carrying 0.00 penalty points.

        Link one of the rejection cascade says "every child deviation still `PENDING`
        transitions `PENDING → WITHDRAWN`", and a `WITHDRAWN` disposition "writes its
        `weighted_penalty_points` to 0.00 so it contributes nothing".

        Design: Difficulty/transitive_cascade/submittal_rejection_withdraws_deviations_and_rescores
        """
        state = self._rejected_submittal(api)

        rows, meta = validate_paginated(
            api.list_submittal_spec_deviations(
                state["submittal"]["id"], make_engineer_of_record_headers()
            )
        )
        assert meta["total_count"] == 2
        for deviation in rows:
            assert deviation["disposition"] == "WITHDRAWN"
            assert deviation["weighted_penalty_points"] == pytest.approx(0.00, abs=0.01)

    def test_rejection_raises_the_score_and_blocks_the_project_for_bidding(self, api):
        """The score climbs from 92.00 back to 100.00 and the project moves to BID_BLOCKED.

        Link two says "because those deviations are now `WITHDRAWN`, their
        `weighted_penalty_points` collapse to 0.00, so the compliance score is
        re-derived -- and it *rises*, while `open_fundamental_count` *drops*; a
        rejected submittal therefore ends up with a better score than it had when it
        was rejected". Link three says "because this submittal is rejected, the
        project loses its only path to pre-approval, so the owning project transitions
        to `BID_BLOCKED`."

        Design: Difficulty/transitive_cascade/submittal_rejection_withdraws_deviations_and_rescores
        """
        state = self._rejected_submittal(api)

        submittal = state["decided"]
        assert submittal["status"] == "REJECTED"
        assert submittal["decided_by_user_id"] == "eor-1"
        assert submittal["compliance_score"] == pytest.approx(100.00, abs=0.01)
        assert submittal["open_fundamental_count"] == 0

        project = validate_success(
            api.get_project(state["project"]["id"], make_application_engineer_headers())
        )
        assert_project_state(project, status="BID_BLOCKED")
