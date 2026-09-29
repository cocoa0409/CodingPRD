"""Requests that break two rules at once, where only the higher rung answers.

Each pair here is armed on both sides: a control call proves the lower-priority
rule really would have fired had the higher one not been in the way.
"""

from prd_bench_local_runner.testing import NON_EXISTENT_UUID, validate_error, validate_success

from test_helpers.api_errors import (
    ERR_BURN_IN_DURATION_TOO_SHORT,
    ERR_DRIVE_LEVEL_UNSAFE,
    ERR_ENGINEERING_NOT_APPROVED,
    ERR_INVALID_CASE_STATE,
    ERR_MODULE_NOT_FOUND,
    ERR_SPARE_NOT_RESERVED,
)
from test_helpers.assertions import (
    assert_cabinet_fields,
    assert_case_fields,
    assert_chamber_fields,
    assert_contract_fields,
    assert_instant_equals,
    assert_module_fields,
    assert_project_fields,
    assert_version,
)
from test_helpers.constants import (
    CABINET_BURN_IN,
    CABINET_PLANNED,
    CABINET_POPULATED,
    CASE_APPROVED,
    ENGINEERING_DRAFT,
    MODULE_CALIBRATED,
    PRODUCTION_NOT_STARTED,
    RUN_SCHEDULED,
    WARRANTY_CASE_INSTANT,
)
from test_helpers.factories import (
    burn_in_run_payload,
    fulfil_payload,
    install_module_payload,
    next_serial,
)

SHORT_WINDOW_END = "2026-08-02T12:00:00.000Z"
FULL_WINDOW_START = "2026-08-02T00:00:00.000Z"
FULL_WINDOW_END = "2026-08-03T00:00:00.000Z"
FULL_WINDOW_OCCUPIED_UNTIL = "2026-08-03T01:00:00.000Z"


def _responded_claim_with_an_unreserved_spare(plant):
    """A commissioned GOLD wall, a spare nobody reserved, and an unassessed claim."""
    scene = plant.commissioned_scene()
    spare = plant.calibrated_module(
        scene.model["id"],
        serial_no=next_serial("S"),
        measured_brightness_nits=4850,
        measured_color_x=0.3124,
        measured_color_y=0.3287,
    )
    plant.set_clock(WARRANTY_CASE_INSTANT)
    case = plant.open_degradation_case(
        scene.contract["id"], scene.cabinet["id"], measured_brightness_nits=4600
    )
    plant.respond(case["id"])
    scene.spare = plant.module(spare["id"])
    scene.case = plant.case(case["id"])
    return scene


def _draft_wall_with_a_planned_cabinet(plant):
    """A wall whose drawing was never submitted, with a slot ready and a module ready."""
    model = plant.register_model()
    project = plant.create_project(model["id"])
    cabinet = plant.plan_cabinet(project["id"])
    module = plant.calibrated_module(model["id"], serial_no="M-1")
    return model, project, cabinet, module


class TestCaseStateOutranksTheSpareReservationRule:
    """A claim that was never assessed hears about its state, not its spare."""

    def test_an_unassessed_claim_reports_the_state_failure(self, plant):
        """The case's `case_state` permits the operation: `OPEN` for response,
        `RESPONDED` for assessment, `APPROVED` for fulfilment — otherwise
        `ERR_INVALID_CASE_STATE`.

        Design: Difficulty/priority_pair_validation_conflict/state_outranks_business_constraint_on_case_fulfil
        """
        scene = _responded_claim_with_an_unreserved_spare(plant)

        response = plant.api.fulfil_case(
            scene.case["id"],
            fulfil_payload(
                plant.cabinet_version(scene.cabinet["id"]), scene.spare["id"]
            ),
            plant.service,
        )

        validate_error(response, ERR_INVALID_CASE_STATE, 409)

    def test_the_reservation_rule_was_armed_all_along(self, plant):
        """The nominated module is reserved to this contract — otherwise
        `ERR_SPARE_NOT_RESERVED`. This rung guards case fulfilment and spare
        release.

        Design: Difficulty/priority_pair_validation_conflict/state_outranks_business_constraint_on_case_fulfil
        """
        scene = _responded_claim_with_an_unreserved_spare(plant)
        plant.api.fulfil_case(
            scene.case["id"],
            fulfil_payload(
                plant.cabinet_version(scene.cabinet["id"]), scene.spare["id"]
            ),
            plant.service,
        )

        plant.assess(
            scene.case["id"],
            decision="APPROVE",
            assessment_basis="PRO_RATA_REMAINING_TERM",
        )
        response = plant.api.fulfil_case(
            scene.case["id"],
            fulfil_payload(
                plant.cabinet_version(scene.cabinet["id"]), scene.spare["id"]
            ),
            plant.service,
        )

        validate_error(response, ERR_SPARE_NOT_RESERVED, 409)

    def test_neither_rejected_swap_left_a_trace(self, plant):
        """Screening stops there: no later rule is consulted, no partial write is
        kept, and nothing at all is persisted.

        Design: Difficulty/priority_pair_validation_conflict/state_outranks_business_constraint_on_case_fulfil
        """
        scene = _responded_claim_with_an_unreserved_spare(plant)
        plant.api.fulfil_case(
            scene.case["id"],
            fulfil_payload(
                plant.cabinet_version(scene.cabinet["id"]), scene.spare["id"]
            ),
            plant.service,
        )
        plant.assess(
            scene.case["id"],
            decision="APPROVE",
            assessment_basis="PRO_RATA_REMAINING_TERM",
        )
        plant.api.fulfil_case(
            scene.case["id"],
            fulfil_payload(
                plant.cabinet_version(scene.cabinet["id"]), scene.spare["id"]
            ),
            plant.service,
        )

        assert_case_fields(
            plant.case(scene.case["id"]),
            case_state=CASE_APPROVED,
            replacement_module_id=None,
        )
        assert_module_fields(
            plant.module(scene.spare["id"]),
            module_state=MODULE_CALIBRATED,
            reserved_service_contract_id=None,
        )
        assert_contract_fields(
            plant.contract(scene.contract["id"]), spare_reserved_count=0
        )


class TestDriveCeilingOutranksTheSoakDurationFloor:
    """An unsafe drive level is reported even when the window is also too short."""

    def test_an_unsafe_drive_level_reports_the_safety_failure(self, plant, chamber):
        """The run's `drive_pct` is within both the model's and the chamber's safe
        ceiling — otherwise `ERR_DRIVE_LEVEL_UNSAFE`.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_outranks_business_temporal_on_burn_in_create
        """
        scene = plant.populated_cabinet_scene()

        response = plant.api.create_burn_in_run(
            burn_in_run_payload(
                scene.cabinet["id"],
                chamber["id"],
                window_start=FULL_WINDOW_START,
                window_end=SHORT_WINDOW_END,
                drive_pct=95,
            ),
            plant.qa,
        )

        validate_error(response, ERR_DRIVE_LEVEL_UNSAFE, 422)

    def test_the_duration_floor_was_armed_all_along(self, plant, chamber):
        """The window must be at least as long as the family's
        `burn_in_hours_required` in whole hours, with a window of exactly that
        length passing and anything shorter refused as
        `ERR_BURN_IN_DURATION_TOO_SHORT`.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_outranks_business_temporal_on_burn_in_create
        """
        scene = plant.populated_cabinet_scene()

        response = plant.api.create_burn_in_run(
            burn_in_run_payload(
                scene.cabinet["id"],
                chamber["id"],
                window_start=FULL_WINDOW_START,
                window_end=SHORT_WINDOW_END,
                drive_pct=90,
            ),
            plant.qa,
        )

        validate_error(response, ERR_BURN_IN_DURATION_TOO_SHORT, 422)
        assert_cabinet_fields(
            plant.cabinet(scene.cabinet["id"]), cabinet_state=CABINET_POPULATED
        )
        assert_chamber_fields(
            plant.chamber(chamber["id"]), reserved_slot_total=0, scheduled_run_count=0
        )

    def test_a_full_soak_at_a_legal_drive_level_is_scheduled(self, plant, chamber):
        """A successful booking creates the run in `run_state` `SCHEDULED`, stores
        its `occupied_until`, adds the run's `slots_required` to the chamber's
        `reserved_slot_total` and 1 to its `scheduled_run_count`, and moves the
        cabinet `POPULATED → BURN_IN` with a version increment.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_outranks_business_temporal_on_burn_in_create
        """
        scene = plant.populated_cabinet_scene()
        plant.api.create_burn_in_run(
            burn_in_run_payload(
                scene.cabinet["id"],
                chamber["id"],
                window_start=FULL_WINDOW_START,
                window_end=SHORT_WINDOW_END,
                drive_pct=95,
            ),
            plant.qa,
        )
        plant.api.create_burn_in_run(
            burn_in_run_payload(
                scene.cabinet["id"],
                chamber["id"],
                window_start=FULL_WINDOW_START,
                window_end=SHORT_WINDOW_END,
                drive_pct=90,
            ),
            plant.qa,
        )

        run = validate_success(
            plant.api.create_burn_in_run(
                burn_in_run_payload(
                    scene.cabinet["id"],
                    chamber["id"],
                    window_start=FULL_WINDOW_START,
                    window_end=FULL_WINDOW_END,
                    drive_pct=90,
                ),
                plant.qa,
            ),
            201,
        )

        assert run["run_state"] == RUN_SCHEDULED
        assert_instant_equals(
            run["occupied_until"], FULL_WINDOW_OCCUPIED_UNTIL, "occupied_until"
        )
        assert_cabinet_fields(
            plant.cabinet(scene.cabinet["id"]), cabinet_state=CABINET_BURN_IN
        )
        assert_chamber_fields(
            plant.chamber(chamber["id"]), reserved_slot_total=1, scheduled_run_count=1
        )


class TestModuleExistenceOutranksTheEngineeringGate:
    """A nonexistent module is reported before the unapproved drawing package."""

    def test_a_nonexistent_module_reports_the_not_found(self, plant):
        """A referenced `module_id`, in path or body, resolves — otherwise
        `ERR_MODULE_NOT_FOUND`. This rung guards the single-module read, pixel
        testing, factory calibration, module installation, module removal, spare
        reservation, spare release, service-case opening and case fulfilment.

        Design: Difficulty/priority_pair_validation_conflict/existence_outranks_state_on_module_install
        """
        _, _, cabinet, _ = _draft_wall_with_a_planned_cabinet(plant)

        response = plant.api.install_module(
            cabinet["id"],
            install_module_payload(NON_EXISTENT_UUID, 1, cabinet["version"]),
            plant.operator,
        )

        validate_error(response, ERR_MODULE_NOT_FOUND, 404)

    def test_the_engineering_gate_was_armed_all_along(self, plant):
        """A project's `engineering_state` is `APPROVED` before any module may be
        installed into one of its cabinets or any of its cabinets mounted —
        otherwise `ERR_ENGINEERING_NOT_APPROVED`.

        Design: Difficulty/priority_pair_validation_conflict/existence_outranks_state_on_module_install
        """
        _, project, cabinet, module = _draft_wall_with_a_planned_cabinet(plant)
        plant.api.install_module(
            cabinet["id"],
            install_module_payload(NON_EXISTENT_UUID, 1, cabinet["version"]),
            plant.operator,
        )

        response = plant.api.install_module(
            cabinet["id"],
            install_module_payload(module["id"], 1, cabinet["version"]),
            plant.operator,
        )

        validate_error(response, ERR_ENGINEERING_NOT_APPROVED, 409)
        assert_project_fields(
            plant.project(project["id"]),
            engineering_state=ENGINEERING_DRAFT,
            production_state=PRODUCTION_NOT_STARTED,
        )
        still_planned = plant.cabinet(cabinet["id"])
        assert_cabinet_fields(
            still_planned, cabinet_state=CABINET_PLANNED, installed_module_count=0
        )
        assert_version(still_planned, cabinet["version"], "cabinet")
        assert_module_fields(
            plant.module(module["id"]),
            module_state=MODULE_CALIBRATED,
            cabinet_id=None,
        )
