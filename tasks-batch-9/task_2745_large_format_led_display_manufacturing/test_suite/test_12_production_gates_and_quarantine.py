"""Production-floor gates, the quarantine cascade and the road back out of it.

The factory refuses work that arrives out of stage, and it refuses it without
writing anything: the soak cannot be adjudicated early, an abandoned soak cannot
be adjudicated at all, and a populated panel is neither retestable, approvable
nor mountable. When a soak does fail, the blast radius is exactly one project.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import (
    ERR_BURN_IN_WINDOW_NOT_ELAPSED,
    ERR_INVALID_CABINET_STATE,
    ERR_INVALID_MODULE_STATE,
    ERR_INVALID_RUN_STATE,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import (
    assert_2dp,
    assert_cabinet_fields,
    assert_fields_absent_or_null,
    assert_module_fields,
    assert_project_fields,
    assert_run_fields,
    assert_version,
    assert_visit_fields,
)
from test_helpers.constants import (
    CABINET_BURN_IN,
    CABINET_BURN_IN_PASSED,
    CABINET_IN_ASSEMBLY,
    CABINET_MOUNTED,
    CABINET_POPULATED,
    CABINET_QA_PASSED,
    CABINET_QUARANTINED,
    MODULE_CALIBRATED,
    MODULE_INSTALLED,
    PRODUCTION_BLOCKED,
    PRODUCTION_IN_ASSEMBLY,
    PRODUCTION_INSTALLED,
    PRODUCTION_NOT_STARTED,
    PRODUCTION_QA_COMPLETE,
    PROJECT_BLOCKED_ABORT_REASON,
    RUN_ABORTED,
    RUN_FAILED,
    RUN_PASSED,
    RUN_SCHEDULED,
    SOAK_WINDOW_END,
    VISIT_ABORTED,
    VISIT_SCHEDULED,
)
from test_helpers.factories import (
    complete_run_payload,
    pixel_test_payload,
    remove_module_payload,
)
from test_helpers.test_users import (
    USER_PRODUCTION_OPERATOR,
    USER_QA_ENGINEER,
    make_field_engineer_headers,
    make_qa_engineer_headers,
)

#: One millisecond short of the 24 hour soak window's end.
ONE_MS_BEFORE_SOAK_WINDOW_END = "2026-08-02T23:59:59.999Z"

ABORT_REASON = "Chamber compressor tripped"

#: A second NA-W crew, and an unrelated wall for it to be booked against.
SECOND_CREW_NAME = "Crew East"
OTHER_CUSTOMER_NAME = "Airport Concourse"

#: One installed dead pixel plus one revealed by the soak, over 1024 pixels.
QUARANTINED_DEAD_PIXEL_PPM = 1953.13

#: The failed run's own dead pixel still counts once the module is pulled.
RECOVERED_DEAD_PIXEL_PPM = 976.56


def _populated_cabinet_in_a_chamber(plant):
    """A POPULATED FP10-IN cabinet holding a SCHEDULED 24 hour soak."""
    scene = plant.populated_cabinet_scene()
    chamber = plant.register_chamber()
    scene.chamber = chamber
    scene.run = plant.schedule_run(scene.cabinet["id"], chamber["id"])
    return scene


def _failing_soak_beside_an_unrelated_booking(plant):
    """One wall about to fail its soak, and a second wall that shares the window.

    Each wall has its own crew, and both crews hold a visit over the same
    on-site window, so an abort that reached too far would be visible.
    """
    scene = _populated_cabinet_in_a_chamber(plant)
    crew_a = plant.register_crew()
    crew_b = plant.register_crew(name=SECOND_CREW_NAME)
    other_project = plant.create_project(
        scene.model["id"], customer_name=OTHER_CUSTOMER_NAME
    )
    scene.crew_a = crew_a
    scene.crew_b = crew_b
    scene.other_project = other_project
    scene.visit_a = plant.book_visit(scene.project["id"], crew_a["id"])
    scene.visit_b = plant.book_visit(other_project["id"], crew_b["id"])
    plant.set_clock(SOAK_WINDOW_END)
    return scene


class TestQaApprovalIndependence:
    """The plant will not let a panel be signed off by the hand that tuned it."""

    def test_the_calibrating_operator_may_not_qa_sign_their_own_panel(self, plant):
        """Independence is enforced here as described in §2.9 — the approving
        `X-User-ID` must not be the `calibrated_by_user_id` of any module currently
        `INSTALLED` in that cabinet, on pain of `ERR_SEGREGATION_OF_DUTIES`.

        Design: Corner/state_machines/qa_approve_by_the_calibrating_operator_rejected
        """
        scene = plant.burn_in_passed_scene()

        refused = plant.api.qa_approve_cabinet(
            scene.cabinet["id"], make_qa_engineer_headers(USER_PRODUCTION_OPERATOR)
        )

        validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 403)
        held = plant.cabinet(scene.cabinet["id"])
        assert_cabinet_fields(
            held, cabinet_state=CABINET_BURN_IN_PASSED, qa_approved_by_user_id=None
        )
        assert_project_fields(
            plant.project(scene.project["id"]),
            qa_passed_cabinet_count=0,
            production_state=PRODUCTION_IN_ASSEMBLY,
        )

        approved = plant.qa_approve(scene.cabinet["id"])

        assert_cabinet_fields(
            approved,
            cabinet_state=CABINET_QA_PASSED,
            qa_approved_by_user_id=USER_QA_ENGINEER,
        )
        assert_project_fields(
            plant.project(scene.project["id"]),
            qa_passed_cabinet_count=1,
            production_state=PRODUCTION_QA_COMPLETE,
        )


class TestBurnInCompletionTemporalGate:
    """The verdict waits for the clock, and the boundary instant is enough."""

    def test_the_soak_cannot_be_adjudicated_one_millisecond_early(self, plant):
        """The run must still be `SCHEDULED` (`ERR_INVALID_RUN_STATE`), and the
        logical clock must have reached the run's `window_end`, with the clock
        exactly at `window_end` counting as elapsed and anything earlier refused as
        `ERR_BURN_IN_WINDOW_NOT_ELAPSED`.

        Design: Corner/state_machines/burn_in_complete_before_window_end_rejected
        """
        scene = _populated_cabinet_in_a_chamber(plant)
        plant.set_clock(ONE_MS_BEFORE_SOAK_WINDOW_END)

        refused = plant.api.complete_burn_in_run(
            scene.run["id"], complete_run_payload(), plant.qa
        )

        validate_error(refused, ERR_BURN_IN_WINDOW_NOT_ELAPSED, 409)
        still_soaking = plant.run(scene.run["id"])
        assert_run_fields(still_soaking, run_state=RUN_SCHEDULED, completed_by_user_id=None)
        assert_fields_absent_or_null(
            still_soaking, "measured_brightness_nits", "measured_uniformity_pct"
        )
        assert_cabinet_fields(
            plant.cabinet(scene.cabinet["id"]), cabinet_state=CABINET_BURN_IN
        )

        plant.set_clock(SOAK_WINDOW_END)
        passed = plant.complete_run(scene.run["id"])

        assert_run_fields(passed, run_state=RUN_PASSED, completed_by_user_id=USER_QA_ENGINEER)
        cabinet = plant.cabinet(scene.cabinet["id"])
        assert_cabinet_fields(cabinet, cabinet_state=CABINET_BURN_IN_PASSED)
        assert cabinet["baseline_module_ids"] == [scene.modules[0]["id"]], (
            "the pass freezes the participating module ids onto the cabinet"
        )

    def test_an_abandoned_soak_can_never_be_adjudicated(self, plant):
        """The abort moves the run `SCHEDULED → ABORTED`, stores the supplied text
        as `abort_reason`, records `completed_by_user_id`, and moves the cabinet
        `BURN_IN → POPULATED` so it can be rescheduled.

        Design: Corner/state_machines/complete_on_an_aborted_run_rejected
        """
        scene = _populated_cabinet_in_a_chamber(plant)
        plant.abort_run(scene.run["id"], ABORT_REASON)
        plant.set_clock(SOAK_WINDOW_END)

        refused = plant.api.complete_burn_in_run(
            scene.run["id"], complete_run_payload(), plant.qa
        )

        validate_error(refused, ERR_INVALID_RUN_STATE, 409)
        aborted = plant.run(scene.run["id"])
        assert_run_fields(aborted, run_state=RUN_ABORTED, abort_reason=ABORT_REASON)
        assert_fields_absent_or_null(
            aborted, "measured_brightness_nits", "measured_uniformity_pct"
        )
        cabinet = plant.cabinet(scene.cabinet["id"])
        assert_cabinet_fields(cabinet, cabinet_state=CABINET_POPULATED)
        assert_fields_absent_or_null(cabinet, "baseline_uniformity_score")
        assert_project_fields(
            plant.project(scene.project["id"]),
            production_state=PRODUCTION_IN_ASSEMBLY,
            quarantined_cabinet_count=0,
        )


class TestQuarantineCascadeBlastRadius:
    """A failed soak blocks one wall and frees one crew — no more than that."""

    def test_only_the_failing_projects_visits_are_aborted(self, plant):
        """Fourth, every commissioning visit of that project whose `visit_state` is
        `SCHEDULED`, `ON_SITE` or `CALIBRATED` is moved to `ABORTED` with
        `abort_reason` set to the exact string `PROJECT_BLOCKED`, and each such
        abort decrements the crew's `scheduled_visit_count`, releasing the window
        for another booking.

        Design: Corner/state_machines/blocked_cascade_aborts_only_the_failing_projects_visits
        """
        scene = _failing_soak_beside_an_unrelated_booking(plant)

        failed = plant.complete_run(scene.run["id"], new_dead_pixel_count=1)

        assert_run_fields(failed, run_state=RUN_FAILED, new_dead_pixel_count=1)
        cabinet = plant.cabinet(scene.cabinet["id"])
        assert_cabinet_fields(
            cabinet, cabinet_state=CABINET_QUARANTINED, total_dead_pixel_count=2
        )
        assert_2dp(
            cabinet["dead_pixel_ppm"], QUARANTINED_DEAD_PIXEL_PPM, "dead_pixel_ppm"
        )
        assert_project_fields(
            plant.project(scene.project["id"]),
            quarantined_cabinet_count=1,
            production_state=PRODUCTION_BLOCKED,
        )

        assert_visit_fields(
            plant.visit(scene.visit_a["id"]),
            visit_state=VISIT_ABORTED,
            abort_reason=PROJECT_BLOCKED_ABORT_REASON,
        )
        assert plant.crew(scene.crew_a["id"])["scheduled_visit_count"] == 0, (
            "the aborting cascade releases the crew that held the blocked wall"
        )

        assert_visit_fields(
            plant.visit(scene.visit_b["id"]),
            visit_state=VISIT_SCHEDULED,
            abort_reason=None,
        )
        assert plant.crew(scene.crew_b["id"])["scheduled_visit_count"] == 1, (
            "an unrelated crew keeps its booking"
        )
        assert_project_fields(
            plant.project(scene.other_project["id"]),
            production_state=PRODUCTION_NOT_STARTED,
            quarantined_cabinet_count=0,
        )

    def test_pulling_the_module_unblocks_the_project_without_rewriting_history(
        self, plant
    ):
        """Removing modules from the quarantined cabinet moves it
        `QUARANTINED → IN_ASSEMBLY`, and once the project's recomputed
        `quarantined_cabinet_count` reaches 0 the project moves
        `BLOCKED → IN_ASSEMBLY`.

        Design: Corner/state_machines/project_recovers_from_blocked_after_the_quarantined_module_is_removed
        """
        scene = _failing_soak_beside_an_unrelated_booking(plant)
        plant.complete_run(scene.run["id"], new_dead_pixel_count=1)
        quarantined = plant.cabinet(scene.cabinet["id"])
        assert_cabinet_fields(quarantined, cabinet_state=CABINET_QUARANTINED)
        assert_project_fields(
            plant.project(scene.project["id"]), production_state=PRODUCTION_BLOCKED
        )
        version_while_quarantined = quarantined["version"]

        removed = plant.remove(scene.cabinet["id"], scene.modules[0]["id"])

        assert_module_fields(
            removed,
            module_state=MODULE_CALIBRATED,
            cabinet_id=None,
            slot_index=None,
            rework_cycles=0,
        )
        recovered = plant.cabinet(scene.cabinet["id"])
        assert_cabinet_fields(
            recovered,
            cabinet_state=CABINET_IN_ASSEMBLY,
            installed_module_count=0,
            occupied_slot_indexes=[],
            total_dead_pixel_count=1,
        )
        assert_2dp(
            recovered["dead_pixel_ppm"], RECOVERED_DEAD_PIXEL_PPM, "dead_pixel_ppm"
        )
        assert_fields_absent_or_null(recovered, "as_built_uniformity_score")
        assert_version(recovered, version_while_quarantined + 1, "cabinet")
        assert_project_fields(
            plant.project(scene.project["id"]),
            quarantined_cabinet_count=0,
            production_state=PRODUCTION_IN_ASSEMBLY,
        )
        assert_run_fields(plant.run(scene.run["id"]), run_state=RUN_FAILED)


class TestOutOfStageWorkOnAPopulatedCabinet:
    """Three operations that all belong to later stages, all refused, none stored."""

    def test_a_populated_panel_is_neither_retestable_approvable_nor_mountable(
        self, plant
    ):
        """The cabinet's `cabinet_state` permits the operation: `PLANNED` or
        `IN_ASSEMBLY` for installation; `IN_ASSEMBLY`, `POPULATED` or `QUARANTINED`
        for removal; `POPULATED` for burn-in scheduling; `BURN_IN_PASSED` for QA
        approval; `QA_PASSED` for mounting — otherwise `ERR_INVALID_CABINET_STATE`.

        Design: Corner/state_machines/out_of_stage_triggers_on_a_populated_cabinet_rejected
        """
        scene = plant.populated_cabinet_scene()
        crew = plant.register_crew()
        version_when_populated = scene.cabinet["version"]

        retest = plant.api.pixel_test_module(
            scene.modules[0]["id"], pixel_test_payload(0, 0), plant.operator
        )
        validate_error(retest, ERR_INVALID_MODULE_STATE, 409)

        approval = plant.api.qa_approve_cabinet(scene.cabinet["id"], plant.qa)
        validate_error(approval, ERR_INVALID_CABINET_STATE, 409)

        mounting = plant.api.mount_cabinet(
            scene.cabinet["id"], make_field_engineer_headers(crew["id"])
        )
        validate_error(mounting, ERR_INVALID_CABINET_STATE, 409)

        assert_module_fields(
            plant.module(scene.modules[0]["id"]),
            module_state=MODULE_INSTALLED,
            dead_pixel_count=1,
            max_cluster_size=1,
        )
        cabinet = plant.cabinet(scene.cabinet["id"])
        assert_cabinet_fields(
            cabinet, cabinet_state=CABINET_POPULATED, qa_approved_by_user_id=None
        )
        assert_version(cabinet, version_when_populated, "cabinet")
        assert_project_fields(
            plant.project(scene.project["id"]),
            qa_passed_cabinet_count=0,
            mounted_cabinet_count=0,
        )


class TestRemovalFromAMountedCabinet:
    """A mounted panel is terminal: a current version does not reopen it."""

    def test_a_current_version_still_cannot_strip_a_mounted_cabinet(self, plant):
        """Mounting takes no request body, moves the cabinet
        `QA_PASSED → MOUNTED`, which is terminal for the cabinet lifecycle, and
        recomputes the project's `mounted_cabinet_count`.

        Design: Corner/state_machines/module_removal_from_a_mounted_cabinet_rejected
        """
        scene = plant.mounted_project_scene()
        version_now = plant.cabinet_version(scene.cabinet["id"])

        refused = plant.api.remove_module(
            scene.cabinet["id"],
            remove_module_payload(scene.modules[0]["id"], version_now),
            plant.operator,
        )

        validate_error(refused, ERR_INVALID_CABINET_STATE, 409)
        cabinet = plant.cabinet(scene.cabinet["id"])
        assert_cabinet_fields(
            cabinet,
            cabinet_state=CABINET_MOUNTED,
            installed_module_count=1,
            occupied_slot_indexes=[1],
        )
        assert_version(cabinet, version_now, "cabinet")
        assert_module_fields(
            plant.module(scene.modules[0]["id"]),
            module_state=MODULE_INSTALLED,
            cabinet_id=scene.cabinet["id"],
        )
        assert_project_fields(
            plant.project(scene.project["id"]),
            production_state=PRODUCTION_INSTALLED,
            mounted_cabinet_count=1,
        )
