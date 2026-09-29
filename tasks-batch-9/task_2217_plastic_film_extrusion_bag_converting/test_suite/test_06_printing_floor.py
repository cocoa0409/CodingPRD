"""Print job setup dimensions, press cylinder capacity and the roll-release gate."""
import pytest

from test_helpers import (
    PRINTER,
    QUALITY,
    ApiErrorId,
    create_print_job_payload,
    get_success_data,
    setup_food_run_completed,
    setup_food_rolls_released,
    setup_mounted_plate,
    setup_print_job_in_setup,
    validate_error,
    validate_paginated,
    validate_success,
)


def _job_payload(world, roll, plate, job_code, start, end):
    return create_print_job_payload(roll["id"], plate["id"], world["press"]["id"],
                                    job_code=job_code,
                                    window_start=start, window_end=end)


class TestSetupDimensionsEvolveIndependently:
    """Registration and colour move on their own axes inside SETUP."""

    def test_registration_pass_leaves_colour_pending(self, api):
        """One dimension may advance while the other has not been measured.

        PRD: "A job may sit at `REG_PASS` while still `COLOR_PENDING`, or vice
        versa; neither dimension constrains the other."

        Design: Difficulty/non_linear_state_machine/print_job_registration_and_color_dimensions_advance_independently
        """
        world = setup_print_job_in_setup(api)
        job = validate_success(
            api.registration_check(world["print_job"]["id"], 40.0, PRINTER), 200)

        assert job["registration_state"] == "REG_PASS"
        assert job["color_state"] == "COLOR_PENDING"
        assert job["status"] == "SETUP"
        assert job["setup_attempt_count"] == 1

    def test_start_print_refused_while_colour_is_still_pending(self, api):
        """Both dimensions must read PASS before printing may begin.

        PRD: "Starting to print advances `SETUP → PRINTING` and requires all of:
        `registration_state` equal to `REG_PASS` and `color_state` equal to
        `COLOR_PASS`, either being otherwise refused".

        Design: Difficulty/non_linear_state_machine/print_job_registration_and_color_dimensions_advance_independently
        """
        world = setup_print_job_in_setup(api)
        get_success_data(api.registration_check(world["print_job"]["id"], 40.0,
                                                PRINTER))

        validate_error(api.start_print(world["print_job"]["id"], PRINTER),
                       ApiErrorId.ERR_PRINT_JOB_STATE_INVALID, 409)
        job = get_success_data(api.get_print_job(world["print_job"]["id"], PRINTER))
        assert job["status"] == "SETUP"

    def test_failed_then_corrected_colour_proof_does_not_disturb_registration(self, api):
        """A colour failure and its correction leave REG_PASS untouched.

        PRD: "`color_state` becomes `COLOR_PASS` when the recorded deviation is
        no greater than the press's `max_delta_e` and `COLOR_FAIL` when it is
        greater".

        Design: Difficulty/non_linear_state_machine/print_job_registration_and_color_dimensions_advance_independently
        """
        world = setup_print_job_in_setup(api)
        job_id = world["print_job"]["id"]
        get_success_data(api.registration_check(job_id, 40.0, PRINTER))

        failed = validate_success(api.color_proof(job_id, 3.0, PRINTER), 200)
        assert failed["color_state"] == "COLOR_FAIL"
        assert failed["registration_state"] == "REG_PASS"
        assert failed["delta_e_measured"] == pytest.approx(3.0, abs=0.01)
        assert failed["setup_attempt_count"] == 2

        passed = validate_success(api.color_proof(job_id, 1.2, PRINTER), 200)
        assert passed["color_state"] == "COLOR_PASS"
        assert passed["delta_e_measured"] == pytest.approx(1.2, abs=0.01)
        assert passed["setup_attempt_count"] == 3
        assert passed["status"] == "SETUP"

    def test_both_dimensions_passing_admits_the_start(self, api):
        """With both axes at PASS the job moves into PRINTING.

        PRD: "Because `setup_attempt_count` counts registration measurements and
        color proofs together, a job that cannot be dialled in eventually gives
        up". Three attempts is well inside the allowance.

        Design: Difficulty/non_linear_state_machine/print_job_registration_and_color_dimensions_advance_independently
        """
        world = setup_print_job_in_setup(api)
        job_id = world["print_job"]["id"]
        get_success_data(api.registration_check(job_id, 40.0, PRINTER))
        get_success_data(api.color_proof(job_id, 3.0, PRINTER))
        get_success_data(api.color_proof(job_id, 1.2, PRINTER))

        printing = validate_success(api.start_print(job_id, PRINTER), 200)
        assert printing["status"] == "PRINTING"
        assert printing["registration_drift_micron"] == pytest.approx(40.0, abs=0.01)
        assert printing["cylinders_required"] == 4


class TestPressCylinderCapacityIsAggregate:
    """Concurrent jobs share the press's cylinders with no buffer."""

    @staticmethod
    def _two_mounted_plates(api):
        world = setup_food_rolls_released(api)
        world = setup_mounted_plate(api, world, plate_code="PL-1", color_count=4)
        world["plate1"] = world["plate"]
        world = setup_mounted_plate(api, world, plate_code="PL-2", color_count=6)
        world["plate2"] = world["plate"]
        return world

    def test_first_job_freezes_its_cylinder_requirement(self, api):
        """The requirement is copied off the plate at creation time.

        PRD: "Creation freezes `cylinders_required` as a copy of the plate set's
        `color_count` at that moment, and it claims the roll: the roll moves
        `RELEASED → CONSUMED`".

        Design: Difficulty/resource_temporal_overlap/press_cylinder_capacity_is_aggregate_across_overlapping_windows
        """
        world = self._two_mounted_plates(api)
        job_a = validate_success(api.create_print_job(
            _job_payload(world, world["rolls"][1], world["plate1"], "PJ-A",
                         "2026-08-05T06:00:00Z", "2026-08-05T12:00:00Z"),
            PRINTER), 201)

        assert job_a["cylinders_required"] == 4
        assert job_a["status"] == "SETUP"
        press = get_success_data(api.get_print_press(world["press"]["id"], PRINTER))
        assert press["cylinder_capacity"] == 8
        assert press["max_colors"] == 6

    def test_overlapping_windows_sum_beyond_capacity_and_are_refused(self, api):
        """Four occupied plus six requested breaches the capacity of eight.

        PRD: "It sums those jobs' `cylinders_required`, adds the new job's own
        requirement, and refuses with `ERR_PRESS_CYLINDER_CAPACITY` when the
        total exceeds the press's `cylinder_capacity`."

        Design: Difficulty/resource_temporal_overlap/press_cylinder_capacity_is_aggregate_across_overlapping_windows
        """
        world = self._two_mounted_plates(api)
        get_success_data(api.create_print_job(
            _job_payload(world, world["rolls"][1], world["plate1"], "PJ-A",
                         "2026-08-05T06:00:00Z", "2026-08-05T12:00:00Z"),
            PRINTER))

        validate_error(api.create_print_job(
            _job_payload(world, world["rolls"][2], world["plate2"], "PJ-B",
                         "2026-08-05T09:00:00Z", "2026-08-05T15:00:00Z"),
            PRINTER), ApiErrorId.ERR_PRESS_CYLINDER_CAPACITY, 409)

        roll2 = get_success_data(api.get_film_roll(world["rolls"][2]["id"], QUALITY))
        assert roll2["status"] == "RELEASED"

    def test_disjoint_half_open_windows_admit_the_same_six_cylinder_job(self, api):
        """Shifting the window to abut at 12:00 removes the overlap entirely.

        PRD: "overlap meaning that job's `window_start` falls earlier than the
        new `window_end` and the new `window_start` falls earlier than that job's
        `window_end`, so the intervals are half-open."

        Design: Difficulty/resource_temporal_overlap/press_cylinder_capacity_is_aggregate_across_overlapping_windows
        """
        world = self._two_mounted_plates(api)
        get_success_data(api.create_print_job(
            _job_payload(world, world["rolls"][1], world["plate1"], "PJ-A",
                         "2026-08-05T06:00:00Z", "2026-08-05T12:00:00Z"),
            PRINTER))
        validate_error(api.create_print_job(
            _job_payload(world, world["rolls"][2], world["plate2"], "PJ-B",
                         "2026-08-05T09:00:00Z", "2026-08-05T15:00:00Z"),
            PRINTER), ApiErrorId.ERR_PRESS_CYLINDER_CAPACITY, 409)

        job_c = validate_success(api.create_print_job(
            _job_payload(world, world["rolls"][2], world["plate2"], "PJ-C",
                         "2026-08-05T12:00:00Z", "2026-08-05T18:00:00Z"),
            PRINTER), 201)
        assert job_c["cylinders_required"] == 6

        roll2 = get_success_data(api.get_film_roll(world["rolls"][2]["id"], QUALITY))
        assert roll2["status"] == "CONSUMED"

        _rows, meta = validate_paginated(api.list_print_jobs(
            PRINTER, params={"press_id": world["press"]["id"]}))
        assert meta["total_count"] == 2

        plate2 = get_success_data(api.get_plate_set(world["plate2"]["id"], PRINTER))
        assert plate2["color_count"] == 6
        assert plate2["mounted_press_id"] == world["press"]["id"]


class TestPrintJobRequiresAReleasedRoll:
    """The blocking state lives on the roll, not on the job being created."""

    @staticmethod
    def _one_released_roll(api):
        world = setup_food_run_completed(api)
        world = setup_food_rolls_released(api, world, roll_numbers=(1,))
        world = setup_mounted_plate(api, world)
        return world

    def test_job_against_a_wound_roll_is_refused(self, api):
        """Roll 3 was never released, so no job may feed it.

        PRD: "The named roll must be in `RELEASED` status, or
        `ERR_ROLL_STATE_INVALID`; the named plate set must be `MOUNTED`, or
        `ERR_PLATE_STATE_INVALID`."

        Design: Difficulty/cross_entity_state_dependency/print_job_creation_requires_film_roll_released
        """
        world = self._one_released_roll(api)
        validate_error(api.create_print_job(
            _job_payload(world, world["rolls"][3], world["plate"], "PJ-3",
                         "2026-08-05T06:00:00Z", "2026-08-05T18:00:00Z"),
            PRINTER), ApiErrorId.ERR_ROLL_STATE_INVALID, 409)

        roll3 = get_success_data(api.get_film_roll(world["rolls"][3]["id"], QUALITY))
        assert roll3["status"] == "WOUND"
        _rows, meta = validate_paginated(api.list_print_jobs(
            PRINTER, params={"press_id": world["press"]["id"]}))
        assert meta["total_count"] == 0

    def test_releasing_the_roll_passes_all_four_release_conditions(self, api):
        """The producing run is COMPLETED and CAPABLE and the line is not frozen.

        PRD: "A `QualityManager` moves a roll `WOUND → RELEASED` subject to four
        conditions: the producing run must be `COMPLETED`, or
        `ERR_RUN_STATE_INVALID`".

        Design: Difficulty/cross_entity_state_dependency/print_job_creation_requires_film_roll_released
        """
        world = self._one_released_roll(api)
        released = validate_success(
            api.release_film_roll(world["rolls"][3]["id"], QUALITY), 200)

        assert released["status"] == "RELEASED"
        assert released["actual_recycled_content_pct"] == pytest.approx(0.000, abs=0.01)
        assert released["layflat_mm"] == pytest.approx(300.0, abs=0.01)

    def test_the_identical_payload_succeeds_once_the_roll_is_released(self, api):
        """Creation then claims the roll straight into CONSUMED.

        PRD: "Creation freezes `cylinders_required` as a copy of the plate set's
        `color_count` at that moment, and it claims the roll: the roll moves
        `RELEASED → CONSUMED`".

        Design: Difficulty/cross_entity_state_dependency/print_job_creation_requires_film_roll_released
        """
        world = self._one_released_roll(api)
        payload = _job_payload(world, world["rolls"][3], world["plate"], "PJ-3",
                               "2026-08-05T06:00:00Z", "2026-08-05T18:00:00Z")
        validate_error(api.create_print_job(payload, PRINTER),
                       ApiErrorId.ERR_ROLL_STATE_INVALID, 409)
        get_success_data(api.release_film_roll(world["rolls"][3]["id"], QUALITY))

        job = validate_success(api.create_print_job(payload, PRINTER), 201)
        assert job["status"] == "SETUP"
        assert job["cylinders_required"] == 4
        assert job["registration_state"] == "REG_PENDING"
        assert job["color_state"] == "COLOR_PENDING"
        assert job["setup_attempt_count"] == 0

        roll3 = get_success_data(api.get_film_roll(world["rolls"][3]["id"], QUALITY))
        assert roll3["status"] == "CONSUMED"
