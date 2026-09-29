"""Values sitting exactly on a threshold, where the comparison word decides."""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    ApiErrorId,
    assert_bay_ledger,
    assert_project_state,
    fixtures,
    make_application_engineer_headers,
    make_fabrication_manager_headers,
    make_quality_engineer_headers,
)

WINDOW_START = "2026-08-10T08:00:00.000Z"
WINDOW_END = "2026-08-10T16:00:00.000Z"


class TestBayCapacityAcceptsASumExactlyEqualToCapacity:
    """6600 sf of skid fits a 6600 sf bay and is refused by a 6599 sf bay."""

    def _two_bays_and_two_ready_skids(self, api):
        state = fixtures.fat_ready_two_stage_project(api)
        state["bay_exact"] = fixtures.seed_test_bay(
            api, bay_code="BAY-EXACT", max_skid_footprint_sf=6600.0
        )
        state["bay_tight"] = fixtures.seed_test_bay(
            api, bay_code="BAY-TIGHT", max_skid_footprint_sf=6599.0
        )
        return state

    def _fill_the_exact_bay_then_clear_it(self, api, state):
        """Share BAY-EXACT between both skids at exactly its capacity, then cancel both."""
        run_f = fixtures.schedule_fat_run(
            api,
            fixtures.current_skid(api, state["filtration_skid"]["id"]),
            state["bay_exact"]["id"],
            WINDOW_START,
            WINDOW_END,
        )
        run_d = fixtures.schedule_fat_run(
            api,
            fixtures.current_skid(api, state["disinfection_skid"]["id"]),
            state["bay_exact"]["id"],
            WINDOW_START,
            WINDOW_END,
        )
        api.cancel_fat_run(run_f["id"], make_fabrication_manager_headers())
        api.cancel_fat_run(run_d["id"], make_fabrication_manager_headers())
        return run_f, run_d

    def test_a_sum_one_square_foot_above_capacity_is_refused(self, api):
        """5400 plus 1200 exceeds 6599 by one square foot and the booking is refused.

        The PRD says "several runs may share one bay, provided the summed
        `footprint_sf` of the overlap set plus the incoming run's own footprint stays
        at or below the bay's `max_skid_footprint_sf`; the comparison is strictly
        greater-than, so a sum exactly equal to the bay's capacity is accepted, and
        only a sum above it is refused with `ERR_TEST_BAY_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/bay_footprint_sum_exactly_equal_to_capacity_is_accepted
        """
        state = self._two_bays_and_two_ready_skids(api)
        self._fill_the_exact_bay_then_clear_it(api, state)

        fixtures.schedule_fat_run(
            api,
            fixtures.current_skid(api, state["filtration_skid"]["id"]),
            state["bay_tight"]["id"],
            WINDOW_START,
            WINDOW_END,
        )

        disinfection_skid = fixtures.current_skid(
            api, state["disinfection_skid"]["id"]
        )
        response = api.create_fat_run(
            {
                "skid_id": disinfection_skid["id"],
                "test_bay_id": state["bay_tight"]["id"],
                "scheduled_start_at": WINDOW_START,
                "scheduled_end_at": WINDOW_END,
                "expected_skid_version": disinfection_skid["version"],
            },
            make_fabrication_manager_headers(),
        )

        validate_error(response, ApiErrorId.TEST_BAY_CAPACITY_EXCEEDED.value, 409)

    def test_the_exactly_equal_pair_was_accepted_and_its_ledger_returns_to_zero(
        self, api
    ):
        """Both runs shared the 6600 sf bay, and cancelling them restores its ledger exactly.

        Section 2.11 pins that "booking a run adds its footprint-minutes; every exit
        from `SCHEDULED` -- a witnessed result, a cancellation, or a supersede by a
        newer booking on the same skid -- subtracts exactly the same footprint-minutes
        that the booking added. Scheduling a run and then cancelling it restores the
        bay's ledger to its exact pre-booking value."

        Design: Difficulty/boundary_precision_check/bay_footprint_sum_exactly_equal_to_capacity_is_accepted
        """
        state = self._two_bays_and_two_ready_skids(api)
        run_f, run_d = self._fill_the_exact_bay_then_clear_it(api, state)

        assert run_f["footprint_sf"] == 5400
        assert run_d["footprint_sf"] == 1200

        for run_id in (run_f["id"], run_d["id"]):
            run = validate_success(
                api.get_fat_run(run_id, make_fabrication_manager_headers())
            )
            assert run["status"] == "CANCELLED"

        bay_exact = validate_success(
            api.get_test_bay(state["bay_exact"]["id"], make_fabrication_manager_headers())
        )
        assert_bay_ledger(bay_exact, 0)

    def test_only_the_first_booking_survives_in_the_tight_bay(self, api):
        """The tight bay holds one scheduled run and exactly its footprint-minutes.

        A booking "creates a run in `SCHEDULED`, copying `footprint_sf` from the skid
        as a snapshot and deriving `duration_minutes` as the whole minutes between
        `scheduled_start_at` and `scheduled_end_at`, discarding any partial minute",
        and then "the new run's `footprint_sf` multiplied by its `duration_minutes` is
        added to the bay's `reserved_footprint_minutes`".

        Design: Difficulty/boundary_precision_check/bay_footprint_sum_exactly_equal_to_capacity_is_accepted
        """
        state = self._two_bays_and_two_ready_skids(api)
        self._fill_the_exact_bay_then_clear_it(api, state)

        tight_run = fixtures.schedule_fat_run(
            api,
            fixtures.current_skid(api, state["filtration_skid"]["id"]),
            state["bay_tight"]["id"],
            WINDOW_START,
            WINDOW_END,
        )

        disinfection_skid = fixtures.current_skid(api, state["disinfection_skid"]["id"])
        api.create_fat_run(
            {
                "skid_id": disinfection_skid["id"],
                "test_bay_id": state["bay_tight"]["id"],
                "scheduled_start_at": WINDOW_START,
                "scheduled_end_at": WINDOW_END,
                "expected_skid_version": disinfection_skid["version"],
            },
            make_fabrication_manager_headers(),
        )

        rows, meta = validate_paginated(
            api.list_fat_runs(
                make_fabrication_manager_headers(),
                {"test_bay_id": state["bay_tight"]["id"]},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == tight_run["id"]
        assert rows[0]["status"] == "SCHEDULED"

        bay_tight = validate_success(
            api.get_test_bay(state["bay_tight"]["id"], make_fabrication_manager_headers())
        )
        assert_bay_ledger(bay_tight, 2592000)


class TestGuaranteeMarginExactlyAtTheBandPasses:
    """A thinnest margin of exactly 5.00 percent is a pass, not a conditional pass."""

    def _certified_demo(self, api):
        state = fixtures.commissioning_project(api)
        state["demo"] = fixtures.record_demo(
            api,
            state["project"]["id"],
            state["skid"]["id"],
            [{"parameter": "TURBIDITY_NTU", "measured_value": 0.285}],
        )
        state["certified"] = validate_success(
            api.certify_performance_demo(
                state["demo"]["id"],
                {
                    "certification": "PASS",
                    "certification_note": "Seven-day demonstration witnessed",
                },
                make_quality_engineer_headers(),
            )
        )
        return state

    def test_a_margin_of_exactly_five_percent_is_recorded_as_passed(self, api):
        """0.285 against a 0.300 limit gives 5.00 percent, and the at-least test passes it.

        The margin "is the shortfall from the limit expressed as a percentage of the
        limit: the limit minus the compared value, divided by the limit, multiplied by
        100, rounded half up to two decimal places." The band then says "if
        `min_margin_pct` is at least the guarantee margin band of 5.0 percent, the
        result is `PASSED`; the comparison is at-least, so a smallest margin of
        exactly 5.0 passes."

        Design: Difficulty/boundary_precision_check/guarantee_margin_exactly_at_five_percent_passes
        """
        state = self._certified_demo(api)

        demo = state["certified"]
        assert demo["result"] == "PASSED"
        assert demo["min_margin_pct"] == pytest.approx(5.00, abs=0.01)
        assert demo["round_no"] == 1
        assert demo["certified_by_user_id"] == "qa-1"

    def test_the_passing_certification_guarantees_the_project(self, api):
        """The success chain meets the guarantee and rests the project in GUARANTEED.

        "A `PASSED` certification moves the demonstration `PENDING → PASSED` and
        starts a four-link cascade. Link one: the project's `guarantee_status` becomes
        `MET`. Link two: the project moves `COMMISSIONING → GUARANTEED`." And "a
        project with no service agreement yet stops at link two and rests in
        `GUARANTEED` until one is opened."

        Design: Difficulty/boundary_precision_check/guarantee_margin_exactly_at_five_percent_passes
        """
        state = self._certified_demo(api)

        project = validate_success(
            api.get_project(state["project"]["id"], make_application_engineer_headers())
        )
        assert_project_state(
            project,
            status="GUARANTEED",
            delivery_posture="ON_TRACK",
            guarantee_status="MET",
        )

        package = validate_success(
            api.get_equipment_package(
                state["package"]["id"], make_application_engineer_headers()
            )
        )
        assert package["status"] == "SHIPPED"
