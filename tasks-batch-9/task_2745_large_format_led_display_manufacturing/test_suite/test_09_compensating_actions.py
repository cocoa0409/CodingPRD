"""Compensating actions that must give back exactly what their partner took.

Releasing a spare undoes a reservation and aborting a run undoes a chamber
booking. Each pair is walked forwards, backwards and forwards again so that the
conserved quantity is shown to return to its starting value with no drift, while
the optimistic-concurrency counter is shown never to rewind.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ERR_INVALID_RUN_STATE
from test_helpers.assertions import (
    assert_cabinet_fields,
    assert_cents,
    assert_chamber_fields,
    assert_contract_fields,
    assert_fields_absent_or_null,
    assert_module_fields,
    assert_project_fields,
    assert_run_fields,
)
from test_helpers.constants import (
    CABINET_BURN_IN,
    CABINET_POPULATED,
    CONTRACT_ACTIVE,
    CONTRACT_SUSPENDED,
    MODULE_CALIBRATED,
    MODULE_INSTALLED,
    POSTURE_AT_RISK,
    POSTURE_NORMAL,
    RUN_ABORTED,
    RUN_SCHEDULED,
)
from test_helpers.factories import abort_run_payload, burn_in_run_payload, next_serial

SPARE_BRIGHTNESS_NITS = 4850
SPARE_COLOR_X = 0.3124
SPARE_COLOR_Y = 0.3287
GOLD_ANNUAL_FEE_CENTS = 31943
ABORT_REASON = "Chamber humidity sensor out of calibration"


def _commissioned_wall_with_one_free_spare(plant):
    """A live GOLD contract that owes one spare, and one unreserved candidate."""
    scene = plant.commissioned_scene()
    spare = plant.calibrated_module(
        scene.model["id"],
        serial_no=next_serial("S"),
        measured_brightness_nits=SPARE_BRIGHTNESS_NITS,
        measured_color_x=SPARE_COLOR_X,
        measured_color_y=SPARE_COLOR_Y,
    )
    scene.spare = plant.module(spare["id"])
    scene.contract = plant.contract(scene.contract["id"])
    return scene


class TestSpareReservationRoundTrip:
    """`spare_reserved_count` and the module pointer come back to where they were."""

    def test_reserving_the_only_candidate_satisfies_the_pool(self, plant):
        """A reservation writes the contract's id into the module's
        `reserved_service_contract_id` and raises `spare_reserved_count`, which is
        always the count of modules whose `reserved_service_contract_id` is this
        contract **and** whose `module_state` is `CALIBRATED`.

        Design: Difficulty/compensating_invariant/spare_reservation_and_release_conserve_reserved_count
        """
        scene = _commissioned_wall_with_one_free_spare(plant)
        assert_contract_fields(
            scene.contract,
            contract_state=CONTRACT_ACTIVE,
            spare_required_count=1,
            spare_reserved_count=0,
        )

        plant.reserve_spare(scene.contract["id"], scene.spare["id"])

        assert_contract_fields(
            plant.contract(scene.contract["id"]),
            contract_state=CONTRACT_ACTIVE,
            spare_reserved_count=1,
        )
        assert_module_fields(
            plant.module(scene.spare["id"]),
            module_state=MODULE_CALIBRATED,
            reserved_service_contract_id=scene.contract["id"],
        )
        assert_project_fields(
            plant.project(scene.project["id"]), service_posture=POSTURE_NORMAL
        )

    def test_releasing_the_spare_drains_the_pool_and_suspends_the_contract(self, plant):
        """The release clears the module's `reserved_service_contract_id` and lowers
        `spare_reserved_count` by 1, and if that drops the pool below
        `spare_required_count` the contract moves `ACTIVE → SUSPENDED` and the
        project's `service_posture` becomes `AT_RISK`.

        Design: Difficulty/compensating_invariant/spare_reservation_and_release_conserve_reserved_count
        """
        scene = _commissioned_wall_with_one_free_spare(plant)
        plant.reserve_spare(scene.contract["id"], scene.spare["id"])

        plant.release_spare(scene.contract["id"], scene.spare["id"])

        assert_contract_fields(
            plant.contract(scene.contract["id"]),
            contract_state=CONTRACT_SUSPENDED,
            spare_reserved_count=0,
        )
        released = plant.module(scene.spare["id"])
        assert_module_fields(released, module_state=MODULE_CALIBRATED)
        assert_fields_absent_or_null(released, "reserved_service_contract_id")
        assert_project_fields(
            plant.project(scene.project["id"]), service_posture=POSTURE_AT_RISK
        )

    def test_the_round_trip_restores_every_value_except_the_version(self, plant):
        """The contract therefore cycles: `ACTIVE → SUSPENDED → ACTIVE` may repeat
        without bound as the spare pool is drained and refilled.

        Design: Difficulty/compensating_invariant/spare_reservation_and_release_conserve_reserved_count
        """
        scene = _commissioned_wall_with_one_free_spare(plant)

        plant.reserve_spare(scene.contract["id"], scene.spare["id"])
        after_first_reserve = plant.contract(scene.contract["id"])
        plant.release_spare(scene.contract["id"], scene.spare["id"])
        after_release = plant.contract(scene.contract["id"])
        plant.reserve_spare(scene.contract["id"], scene.spare["id"])
        after_second_reserve = plant.contract(scene.contract["id"])

        assert_contract_fields(
            after_second_reserve,
            contract_state=CONTRACT_ACTIVE,
            spare_required_count=after_first_reserve["spare_required_count"],
            spare_reserved_count=after_first_reserve["spare_reserved_count"],
            sla_breach_count=0,
        )
        assert_module_fields(
            plant.module(scene.spare["id"]),
            module_state=MODULE_CALIBRATED,
            reserved_service_contract_id=scene.contract["id"],
        )
        assert_project_fields(
            plant.project(scene.project["id"]), service_posture=POSTURE_NORMAL
        )
        assert_cents(
            after_second_reserve["annual_fee_cents"],
            GOLD_ANNUAL_FEE_CENTS,
            "annual_fee_cents",
        )
        assert (
            after_second_reserve["version"] > after_release["version"]
            > after_first_reserve["version"]
        )


def _populated_cabinet_and_an_empty_chamber(plant):
    """One finished wall panel and a four-slot chamber with nothing booked in it."""
    scene = plant.populated_cabinet_scene()
    scene.chamber = plant.register_chamber()
    return scene


class TestBurnInAbortRoundTrip:
    """Abortion hands back exactly three slots, one run count and one state."""

    def test_scheduling_takes_three_of_the_four_slots(self, plant):
        """Both are maintained by the service as runs are scheduled, completed,
        failed and aborted, and both are visible on a chamber read so a
        `QAEngineer` can see live reservation pressure before scheduling.

        Design: Difficulty/compensating_invariant/burn_in_schedule_and_abort_conserve_chamber_reserved_slots
        """
        scene = _populated_cabinet_and_an_empty_chamber(plant)
        assert_chamber_fields(
            scene.chamber, reserved_slot_total=0, scheduled_run_count=0, slot_capacity=4
        )

        run = plant.schedule_run(
            scene.cabinet["id"], scene.chamber["id"], slots_required=3
        )

        assert_run_fields(run, run_state=RUN_SCHEDULED, slots_required=3)
        assert_chamber_fields(
            plant.chamber(scene.chamber["id"]), reserved_slot_total=3, scheduled_run_count=1
        )
        assert_cabinet_fields(
            plant.cabinet(scene.cabinet["id"]), cabinet_state=CABINET_BURN_IN
        )

    def test_aborting_returns_exactly_what_scheduling_took(self, plant):
        """Abortion is the exact compensating action for scheduling: the chamber's
        `reserved_slot_total` returns to its pre-schedule value and
        `scheduled_run_count` drops by 1.

        Design: Difficulty/compensating_invariant/burn_in_schedule_and_abort_conserve_chamber_reserved_slots
        """
        scene = _populated_cabinet_and_an_empty_chamber(plant)
        run = plant.schedule_run(
            scene.cabinet["id"], scene.chamber["id"], slots_required=3
        )

        aborted = plant.abort_run(run["id"], reason=ABORT_REASON)

        assert_run_fields(aborted, run_state=RUN_ABORTED, abort_reason=ABORT_REASON)
        assert_chamber_fields(
            plant.chamber(scene.chamber["id"]), reserved_slot_total=0, scheduled_run_count=0
        )
        assert_cabinet_fields(
            plant.cabinet(scene.cabinet["id"]),
            cabinet_state=CABINET_POPULATED,
            installed_module_count=1,
            occupied_slot_indexes=[1],
        )
        assert_module_fields(
            plant.module(scene.modules[0]["id"]), module_state=MODULE_INSTALLED
        )

    def test_the_released_slots_are_bookable_again_but_not_refundable_twice(self, plant):
        """The abort moves the run `SCHEDULED → ABORTED`, stores the supplied text as
        `abort_reason`, records `completed_by_user_id`, and moves the cabinet
        `BURN_IN → POPULATED` so it can be rescheduled.

        Design: Difficulty/compensating_invariant/burn_in_schedule_and_abort_conserve_chamber_reserved_slots
        """
        scene = _populated_cabinet_and_an_empty_chamber(plant)
        payload = burn_in_run_payload(
            scene.cabinet["id"], scene.chamber["id"], slots_required=3
        )
        first = plant.schedule_run(
            scene.cabinet["id"], scene.chamber["id"], slots_required=3
        )
        plant.abort_run(first["id"], reason=ABORT_REASON)

        second = validate_success(plant.api.create_burn_in_run(payload, plant.qa), 201)

        assert_run_fields(second, run_state=RUN_SCHEDULED, slots_required=3)
        assert_chamber_fields(
            plant.chamber(scene.chamber["id"]), reserved_slot_total=3, scheduled_run_count=1
        )

        response = plant.api.abort_burn_in_run(
            first["id"], abort_run_payload(ABORT_REASON), plant.qa
        )

        validate_error(response, ERR_INVALID_RUN_STATE, 409)
        assert_chamber_fields(
            plant.chamber(scene.chamber["id"]), reserved_slot_total=3, scheduled_run_count=1
        )
        assert_run_fields(plant.run(first["id"]), run_state=RUN_ABORTED)
        assert_module_fields(
            plant.module(scene.modules[0]["id"]), module_state=MODULE_INSTALLED
        )
