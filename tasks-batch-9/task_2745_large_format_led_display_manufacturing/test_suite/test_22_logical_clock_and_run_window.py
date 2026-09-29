"""The logical clock and the one-state window the two run verdicts share.

The clock is observable only through the rules that read it, so the burn-in
window gate doubles as its probe: with no clock call at all the window is not
elapsed, one millisecond short still fails, and exact equality passes. Abort and
complete then compete for the same `SCHEDULED`-only window.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import (
    ERR_BURN_IN_WINDOW_NOT_ELAPSED,
    ERR_INVALID_RUN_STATE,
)
from test_helpers.assertions import (
    assert_2dp,
    assert_cabinet_fields,
    assert_chamber_fields,
    assert_instant_equals,
    assert_page_meta,
    assert_run_fields,
    ids_of,
)
from test_helpers.constants import (
    CABINET_BURN_IN,
    CABINET_BURN_IN_PASSED,
    CABINET_POPULATED,
    RUN_ABORTED,
    RUN_PASSED,
    RUN_SCHEDULED,
    SOAK_WINDOW_END,
    SOAK_WINDOW_END_48H,
)
from test_helpers.factories import abort_run_payload, complete_run_payload

#: One millisecond before the soak window closes.
ONE_MILLISECOND_SHORT_OF_WINDOW_END = "2026-08-02T23:59:59.999Z"

#: The second soak window, another whole 24 hours, booked after the abort.
RESCHEDULED_WINDOW_START = SOAK_WINDOW_END_48H
RESCHEDULED_WINDOW_END = "2026-08-05T00:00:00.000Z"

#: One dead pixel over the FP10-IN cabinet's 1024 pixels: 976.5625 ppm, which is
#: exactly the family's 976.56 ppm allowance once rounded to 2 places.
SINGLE_DEAD_PIXEL_PPM = 976.56

ABORT_REASON = "Chamber door seal replaced before the soak started"
LATE_ABORT_REASON = "Too late, the soak already finished"


def _scheduled_soak(plant):
    """A populated FP10-IN cabinet in a booked chamber, with the clock untouched."""
    scene = plant.populated_cabinet_scene()
    chamber = plant.register_chamber()
    run = plant.schedule_run(scene.cabinet["id"], chamber["id"])
    scene.chamber = chamber
    scene.run = run
    return scene


class TestBurnInWindowReadsTheLogicalClock:
    """The gate is a `>=` against a clock that never consults the host."""

    def test_an_untouched_clock_and_one_millisecond_short_both_refuse(self, plant):
        """The clock's startup default is exactly `2026-08-01T00:00:00Z`, and until
        it is moved the clock reads exactly that value; it never falls back to the
        host's real time. The run must still be `SCHEDULED`
        (`ERR_INVALID_RUN_STATE`), and the logical clock must have reached the run's
        `window_end`, with the clock exactly at `window_end` counting as elapsed and
        anything earlier refused as `ERR_BURN_IN_WINDOW_NOT_ELAPSED`.

        Design: Corner/endpoints/logical_clock_drives_the_burn_in_window_gate
        """
        scene = _scheduled_soak(plant)

        untouched = plant.api.complete_burn_in_run(
            scene.run["id"], complete_run_payload(), plant.qa
        )

        validate_error(untouched, ERR_BURN_IN_WINDOW_NOT_ELAPSED, 409)
        assert_run_fields(
            plant.run(scene.run["id"]),
            run_state=RUN_SCHEDULED,
            new_dead_pixel_count=None,
            completed_by_user_id=None,
        )

        moved = validate_success(
            plant.api.set_clock(ONE_MILLISECOND_SHORT_OF_WINDOW_END, plant.admin), 200
        )
        assert_instant_equals(
            moved["current_utc"], ONE_MILLISECOND_SHORT_OF_WINDOW_END, "current_utc"
        )
        one_millisecond_short = plant.api.complete_burn_in_run(
            scene.run["id"], complete_run_payload(), plant.qa
        )

        validate_error(one_millisecond_short, ERR_BURN_IN_WINDOW_NOT_ELAPSED, 409)
        assert_run_fields(plant.run(scene.run["id"]), run_state=RUN_SCHEDULED)
        assert_cabinet_fields(
            plant.cabinet(scene.cabinet["id"]), cabinet_state=CABINET_BURN_IN
        )

    def test_exact_equality_with_the_window_end_elapses_and_stores_one_verdict(self, plant):
        """A `PlantAdmin` may move the clock to an absolute instant by supplying
        `to_iso8601`, and the service answers with the new `current_utc`. Either
        outcome stores the three measurements, records `completed_by_user_id` as the
        acting `X-User-ID`, recomputes the cabinet's dead-pixel density with the new
        count folded in, and snapshots that figure onto the run as
        `cabinet_dead_pixel_ppm`, rounded to 2 decimal places.

        Design: Corner/endpoints/logical_clock_drives_the_burn_in_window_gate
        """
        scene = _scheduled_soak(plant)
        validate_error(
            plant.api.complete_burn_in_run(
                scene.run["id"], complete_run_payload(), plant.qa
            ),
            ERR_BURN_IN_WINDOW_NOT_ELAPSED,
            409,
        )

        at_window_end = validate_success(
            plant.api.set_clock(SOAK_WINDOW_END, plant.admin), 200
        )
        response = plant.api.complete_burn_in_run(
            scene.run["id"], complete_run_payload(), plant.qa
        )

        assert_instant_equals(
            at_window_end["current_utc"], SOAK_WINDOW_END, "current_utc"
        )
        passed = validate_success(response, 200)
        assert_run_fields(
            passed,
            run_state=RUN_PASSED,
            new_dead_pixel_count=0,
            completed_by_user_id="qa-1",
            abort_reason=None,
        )
        assert passed["measured_brightness_nits"] == 4900
        assert_2dp(
            passed["cabinet_dead_pixel_ppm"], SINGLE_DEAD_PIXEL_PPM, "cabinet_dead_pixel_ppm"
        )
        cabinet = plant.cabinet(scene.cabinet["id"])
        assert_cabinet_fields(
            cabinet, cabinet_state=CABINET_BURN_IN_PASSED, total_dead_pixel_count=1
        )
        assert_2dp(cabinet["dead_pixel_ppm"], SINGLE_DEAD_PIXEL_PPM, "dead_pixel_ppm")
        assert cabinet["baseline_module_ids"] == [scene.modules[0]["id"]]
        assert cabinet["baseline_uniformity_score"] is None


class TestAbortAndCompleteShareOneWindow:
    """The two verdicts are mutually exclusive, not ordered."""

    def test_an_abort_frees_the_chamber_and_closes_the_window_to_completion(self, plant):
        """The abort moves the run `SCHEDULED → ABORTED`, stores the supplied text as
        `abort_reason`, records `completed_by_user_id`, and moves the cabinet
        `BURN_IN → POPULATED` so it can be rescheduled. Abortion is the exact
        compensating action for scheduling: the chamber's `reserved_slot_total`
        returns to its pre-schedule value and `scheduled_run_count` drops by 1.

        Design: Corner/endpoints/run_abort_is_offered_only_while_the_run_is_scheduled
        """
        scene = _scheduled_soak(plant)

        aborted = validate_success(
            plant.api.abort_burn_in_run(
                scene.run["id"], abort_run_payload(ABORT_REASON), plant.qa
            ),
            200,
        )
        refused = plant.api.complete_burn_in_run(
            scene.run["id"], complete_run_payload(), plant.qa
        )

        assert_run_fields(
            aborted,
            run_state=RUN_ABORTED,
            abort_reason=ABORT_REASON,
            completed_by_user_id="qa-1",
        )
        validate_error(refused, ERR_INVALID_RUN_STATE, 409)
        assert_run_fields(
            plant.run(scene.run["id"]),
            run_state=RUN_ABORTED,
            abort_reason=ABORT_REASON,
            new_dead_pixel_count=None,
        )
        assert_cabinet_fields(
            plant.cabinet(scene.cabinet["id"]),
            cabinet_state=CABINET_POPULATED,
            total_dead_pixel_count=1,
        )
        assert_chamber_fields(
            plant.chamber(scene.chamber["id"]),
            reserved_slot_total=0,
            scheduled_run_count=0,
        )

    def test_a_late_abort_cannot_drag_a_passed_cabinet_back(self, plant):
        """A scheduled run may be abandoned before its verdict by supplying a
        `reason`. The run must still be `SCHEDULED`, or the request is refused with
        `ERR_INVALID_RUN_STATE`. All three of `PASSED`, `FAILED` and `ABORTED` are
        terminal for a run.

        Design: Corner/endpoints/run_abort_is_offered_only_while_the_run_is_scheduled
        """
        scene = _scheduled_soak(plant)
        plant.abort_run(scene.run["id"], ABORT_REASON)

        rescheduled = plant.schedule_run(
            scene.cabinet["id"],
            scene.chamber["id"],
            window_start=RESCHEDULED_WINDOW_START,
            window_end=RESCHEDULED_WINDOW_END,
        )
        assert_run_fields(rescheduled, run_state=RUN_SCHEDULED, slots_required=1)
        plant.set_clock(RESCHEDULED_WINDOW_END)
        plant.complete_run(rescheduled["id"])

        late_abort = plant.api.abort_burn_in_run(
            rescheduled["id"], abort_run_payload(LATE_ABORT_REASON), plant.qa
        )

        validate_error(late_abort, ERR_INVALID_RUN_STATE, 409)
        assert_run_fields(
            plant.run(rescheduled["id"]), run_state=RUN_PASSED, abort_reason=None
        )
        assert_cabinet_fields(
            plant.cabinet(scene.cabinet["id"]), cabinet_state=CABINET_BURN_IN_PASSED
        )
        rows, meta = validate_paginated(
            plant.api.list_burn_in_runs(plant.qa, {"cabinet_id": scene.cabinet["id"]})
        )
        assert ids_of(rows) == [scene.run["id"], rescheduled["id"]]
        assert_page_meta(meta, total_count=2, has_more=False)
