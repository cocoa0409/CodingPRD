"""Operations whose legality is decided by the state of a neighbouring entity.

Scheduling a soak reads the cabinet, a crew's arrival reads the project, and
opening a warranty claim reads the contract. In each case the operated-on record
is already in the right state and the refusal comes from elsewhere.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_CABINETS_NOT_MOUNTED,
    ERR_CONTRACT_NOT_ACTIVE,
    ERR_INVALID_CABINET_STATE,
)
from test_helpers.assertions import (
    assert_2dp,
    assert_cabinet_fields,
    assert_case_fields,
    assert_cents,
    assert_chamber_fields,
    assert_contract_fields,
    assert_fields_absent_or_null,
    assert_instant_equals,
    assert_project_fields,
    assert_run_fields,
    assert_visit_fields,
)
from test_helpers.constants import (
    CABINET_BURN_IN,
    CABINET_IN_ASSEMBLY,
    CABINET_MOUNTED,
    CABINET_POPULATED,
    CABINET_QA_PASSED,
    CASE_OPEN,
    CONTRACT_ACTIVE,
    CONTRACT_PENDING,
    ENGINEERING_APPROVED,
    PRODUCTION_COMMISSIONED,
    PRODUCTION_INSTALLED,
    PRODUCTION_QA_COMPLETE,
    RUN_SCHEDULED,
    SOAK_WINDOW_END,
    VISIT_INSTANT,
    VISIT_ON_SITE,
    VISIT_SCHEDULED,
    VISIT_WINDOW_END,
    VISIT_WINDOW_START,
)
from test_helpers.factories import (
    FP16_STD,
    burn_in_run_payload,
    module_fault_case_payload,
)
from test_helpers.test_users import make_field_engineer_headers

SECOND_MODULE_BRIGHTNESS = 4950
SECOND_MODULE_CHROMA_X = 0.3128
SECOND_MODULE_CHROMA_Y = 0.3291
CASE_SYMPTOM = "Dead quadrant reported by the customer"
RESPONSE_DEADLINE_AT = "2026-08-05T17:00:00.000Z"


def _half_filled_two_slot_cabinet(plant):
    """A two-slot wall panel holding one of its two modules, so it is IN_ASSEMBLY."""
    scene = plant.approved_project_scene(
        model_base=FP16_STD,
        project_overrides={"min_viewing_distance_m": 5.0},
        revision_overrides={"structural_load_kg_per_sqm": 150.00},
    )
    cabinet = plant.plan_cabinet(scene.project["id"])
    first = plant.calibrated_module(scene.model["id"])
    plant.install(cabinet["id"], first["id"], slot_index=1)
    scene.chamber = plant.register_chamber()
    scene.cabinet = plant.cabinet(cabinet["id"])
    scene.first_module = plant.module(first["id"])
    return scene


class TestBurnInSchedulingReadsTheCabinetState:
    """A chamber booking is legal or not according to how full the cabinet is."""

    def test_a_half_filled_cabinet_cannot_take_chamber_time(self, plant):
        """The cabinet must be `POPULATED`, since a partly built wall panel is not
        worth chamber time (`ERR_INVALID_CABINET_STATE`).

        Design: Difficulty/cross_entity_state_dependency/burn_in_scheduling_requires_cabinet_populated
        """
        scene = _half_filled_two_slot_cabinet(plant)
        assert_cabinet_fields(
            scene.cabinet, cabinet_state=CABINET_IN_ASSEMBLY, installed_module_count=1
        )

        response = plant.api.create_burn_in_run(
            burn_in_run_payload(scene.cabinet["id"], scene.chamber["id"]), plant.qa
        )

        validate_error(response, ERR_INVALID_CABINET_STATE, 409)
        assert_chamber_fields(
            plant.chamber(scene.chamber["id"]), reserved_slot_total=0, scheduled_run_count=0
        )
        assert_cabinet_fields(
            plant.cabinet(scene.cabinet["id"]), cabinet_state=CABINET_IN_ASSEMBLY
        )

    def test_filling_the_last_slot_completes_the_panel(self, plant):
        """The install that brings `installed_module_count` up to the family's
        `modules_per_cabinet` moves it `IN_ASSEMBLY → POPULATED`.

        Design: Difficulty/cross_entity_state_dependency/burn_in_scheduling_requires_cabinet_populated
        """
        scene = _half_filled_two_slot_cabinet(plant)

        second = plant.calibrated_module(
            scene.model["id"],
            measured_brightness_nits=SECOND_MODULE_BRIGHTNESS,
            measured_color_x=SECOND_MODULE_CHROMA_X,
            measured_color_y=SECOND_MODULE_CHROMA_Y,
        )
        plant.install(scene.cabinet["id"], second["id"], slot_index=2)

        cabinet = plant.cabinet(scene.cabinet["id"])
        assert_cabinet_fields(
            cabinet,
            cabinet_state=CABINET_POPULATED,
            installed_module_count=2,
            occupied_slot_indexes=[1, 2],
        )
        assert_2dp(cabinet["as_built_uniformity_score"], 97.88, "as_built_uniformity_score")
        assert_fields_absent_or_null(cabinet, "baseline_uniformity_score")

    def test_the_identical_booking_succeeds_once_the_panel_is_complete(self, plant):
        """A successful booking creates the run in `run_state` `SCHEDULED`, stores
        its `occupied_until`, adds the run's `slots_required` to the chamber's
        `reserved_slot_total` and 1 to its `scheduled_run_count`, and moves the
        cabinet `POPULATED → BURN_IN` with a version increment.

        Design: Difficulty/cross_entity_state_dependency/burn_in_scheduling_requires_cabinet_populated
        """
        scene = _half_filled_two_slot_cabinet(plant)
        payload = burn_in_run_payload(scene.cabinet["id"], scene.chamber["id"])
        validate_error(
            plant.api.create_burn_in_run(payload, plant.qa), ERR_INVALID_CABINET_STATE, 409
        )

        second = plant.calibrated_module(
            scene.model["id"],
            measured_brightness_nits=SECOND_MODULE_BRIGHTNESS,
            measured_color_x=SECOND_MODULE_CHROMA_X,
            measured_color_y=SECOND_MODULE_CHROMA_Y,
        )
        plant.install(scene.cabinet["id"], second["id"], slot_index=2)
        run = validate_success(plant.api.create_burn_in_run(payload, plant.qa), 201)

        assert_run_fields(run, run_state=RUN_SCHEDULED, slots_required=1)
        assert_cabinet_fields(
            plant.cabinet(scene.cabinet["id"]), cabinet_state=CABINET_BURN_IN
        )
        assert_chamber_fields(
            plant.chamber(scene.chamber["id"]), reserved_slot_total=1, scheduled_run_count=1
        )


def _two_cabinet_wall_with_one_cabinet_still_unmounted(plant):
    """A two-panel wall, both panels QA-signed, only the first one mounted."""
    scene = plant.approved_project_scene(
        project_overrides={"cabinet_grid_cols": 2, "cabinet_grid_rows": 1}
    )
    cabinet_a = plant.plan_cabinet(scene.project["id"], grid_row=1, grid_col=1)
    cabinet_b = plant.plan_cabinet(scene.project["id"], grid_row=1, grid_col=2)
    plant.populate_cabinet(cabinet_a["id"], scene.model["id"])
    plant.populate_cabinet(
        cabinet_b["id"],
        scene.model["id"],
        brightnesses=[SECOND_MODULE_BRIGHTNESS],
        chroma=[(SECOND_MODULE_CHROMA_X, SECOND_MODULE_CHROMA_Y)],
    )
    chamber = plant.register_chamber()
    run_a = plant.schedule_run(cabinet_a["id"], chamber["id"])
    run_b = plant.schedule_run(cabinet_b["id"], chamber["id"])
    plant.set_clock(SOAK_WINDOW_END)
    plant.complete_run(run_a["id"])
    plant.complete_run(run_b["id"])
    plant.qa_approve(cabinet_a["id"])
    plant.qa_approve(cabinet_b["id"])
    crew = plant.register_crew()
    plant.mount(cabinet_a["id"], crew["id"])
    visit = plant.book_visit(
        scene.project["id"],
        crew["id"],
        window_start=VISIT_WINDOW_START,
        window_end=VISIT_WINDOW_END,
    )
    plant.set_clock(VISIT_INSTANT)
    scene.cabinet_a = plant.cabinet(cabinet_a["id"])
    scene.cabinet_b = plant.cabinet(cabinet_b["id"])
    scene.chamber = plant.chamber(chamber["id"])
    scene.crew = plant.crew(crew["id"])
    scene.visit = plant.visit(visit["id"])
    scene.project = plant.project(scene.project["id"])
    return scene


class TestArrivalReadsTheProjectProductionState:
    """A crew standing on site is admitted or turned away by the wall's progress."""

    def test_a_crew_is_turned_away_while_one_panel_is_unmounted(self, plant):
        """The project's `production_state` must be `INSTALLED`, meaning every
        cabinet is mounted, or the crew is turned away with
        `ERR_CABINETS_NOT_MOUNTED`.

        Design: Difficulty/cross_entity_state_dependency/visit_arrive_requires_all_cabinets_mounted
        """
        scene = _two_cabinet_wall_with_one_cabinet_still_unmounted(plant)
        assert_project_fields(
            scene.project,
            production_state=PRODUCTION_QA_COMPLETE,
            cabinet_count=2,
            qa_passed_cabinet_count=2,
            mounted_cabinet_count=1,
        )

        response = plant.api.arrive_at_visit(
            scene.visit["id"], make_field_engineer_headers(scene.crew["id"])
        )

        validate_error(response, ERR_CABINETS_NOT_MOUNTED, 409)
        visit = plant.visit(scene.visit["id"])
        assert_visit_fields(visit, visit_state=VISIT_SCHEDULED)
        assert_fields_absent_or_null(visit, "arrived_at")

    def test_mounting_the_last_panel_raises_the_project_to_installed(self, plant):
        """When every cabinet of the project is mounted — that is, when the
        recomputed count equals `cabinet_count` — the project rises `QA_COMPLETE →
        INSTALLED`.

        Design: Difficulty/cross_entity_state_dependency/visit_arrive_requires_all_cabinets_mounted
        """
        scene = _two_cabinet_wall_with_one_cabinet_still_unmounted(plant)
        assert_cabinet_fields(scene.cabinet_b, cabinet_state=CABINET_QA_PASSED)

        plant.mount(scene.cabinet_b["id"], scene.crew["id"])

        assert_cabinet_fields(
            plant.cabinet(scene.cabinet_b["id"]), cabinet_state=CABINET_MOUNTED
        )
        project = plant.project(scene.project["id"])
        assert_project_fields(
            project,
            engineering_state=ENGINEERING_APPROVED,
            production_state=PRODUCTION_INSTALLED,
            cabinet_count=2,
            module_count=2,
            qa_passed_cabinet_count=2,
            mounted_cabinet_count=2,
            quarantined_cabinet_count=0,
        )
        assert_cents(project["contract_amount_cents"], 215040, "contract_amount_cents")
        assert_2dp(project["data_load_pct"], 0.40, "data_load_pct")

    def test_the_identical_arrival_succeeds_once_the_wall_is_complete(self, plant):
        """Arrival stamps `arrived_at` from the logical clock and moves the visit
        `SCHEDULED → ON_SITE`.

        Design: Difficulty/cross_entity_state_dependency/visit_arrive_requires_all_cabinets_mounted
        """
        scene = _two_cabinet_wall_with_one_cabinet_still_unmounted(plant)
        crew_headers = make_field_engineer_headers(scene.crew["id"])
        validate_error(
            plant.api.arrive_at_visit(scene.visit["id"], crew_headers),
            ERR_CABINETS_NOT_MOUNTED,
            409,
        )

        plant.mount(scene.cabinet_b["id"], scene.crew["id"])
        visit = validate_success(plant.api.arrive_at_visit(scene.visit["id"], crew_headers), 200)

        assert_visit_fields(
            visit, visit_state=VISIT_ON_SITE, commissioning_crew_id=scene.crew["id"]
        )
        assert_instant_equals(visit["arrived_at"], VISIT_INSTANT, "arrived_at")


def _calibrated_visit_with_a_pending_contract(plant):
    """A GOLD contract sold before commissioning, so it is still PENDING."""
    scene = plant.mounted_project_scene()
    scene.contract = plant.sell_contract(scene.project["id"])
    visit = plant.book_visit(
        scene.project["id"],
        scene.crew["id"],
        window_start=VISIT_WINDOW_START,
        window_end=VISIT_WINDOW_END,
    )
    plant.set_clock(VISIT_INSTANT)
    plant.arrive(visit["id"], scene.crew["id"])
    plant.calibrate_on_site(visit["id"], scene.crew["id"])
    scene.visit = plant.visit(visit["id"])
    scene.contract = plant.contract(scene.contract["id"])
    return scene


class TestCaseCreationReadsTheContractState:
    """A warranty claim can only be raised against a contract that is live."""

    def test_a_claim_against_a_pending_contract_is_refused(self, plant):
        """Three rules guard case creation in this order: the contract must be
        `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`); then the named cabinet must belong to
        the contract's project.

        Design: Difficulty/cross_entity_state_dependency/service_case_open_requires_contract_active
        """
        scene = _calibrated_visit_with_a_pending_contract(plant)
        assert_contract_fields(scene.contract, contract_state=CONTRACT_PENDING)
        assert_fields_absent_or_null(scene.contract, "warranty_start_at")

        response = plant.api.create_service_case(
            module_fault_case_payload(
                scene.contract["id"],
                scene.cabinet["id"],
                scene.modules[0]["id"],
                symptom=CASE_SYMPTOM,
            ),
            plant.service,
        )

        validate_error(response, ERR_CONTRACT_NOT_ACTIVE, 409)
        contract = plant.contract(scene.contract["id"])
        assert_contract_fields(contract, contract_state=CONTRACT_PENDING)
        assert_fields_absent_or_null(contract, "warranty_start_at")

    def test_sign_off_activates_the_contract_and_starts_the_warranty(self, plant):
        """The write then stamps `signed_off_at` from the logical clock and moves
        the visit `CALIBRATED → SIGNED_OFF`; moves the project
        `INSTALLED → COMMISSIONED`; activates the warranty by moving **every**
        service contract of that project whose `contract_state` is `PENDING` to
        `ACTIVE`, setting each one's `warranty_start_at` to the same `signed_off_at`
        instant and incrementing each contract's `version`; and decrements the crew's
        `scheduled_visit_count`, releasing the crew.

        Design: Difficulty/cross_entity_state_dependency/service_case_open_requires_contract_active
        """
        scene = _calibrated_visit_with_a_pending_contract(plant)

        plant.sign_off(scene.visit["id"], scene.crew["id"])

        contract = plant.contract(scene.contract["id"])
        assert_contract_fields(contract, contract_state=CONTRACT_ACTIVE, response_hours=8)
        assert_instant_equals(contract["warranty_start_at"], VISIT_INSTANT, "warranty_start_at")
        assert_project_fields(
            plant.project(scene.project["id"]), production_state=PRODUCTION_COMMISSIONED
        )

    def test_the_identical_claim_is_accepted_once_the_contract_is_active(self, plant):
        """Creation stamps `reported_at` from the logical clock, sets `case_state`
        to `OPEN`, and computes `response_deadline_at` as `reported_at` advanced by
        the contract's `response_hours` multiplied by a severity multiplier: half
        the contracted hours for `CRITICAL`, the full contracted hours for `MAJOR`,
        and double for `MINOR`.

        Design: Difficulty/cross_entity_state_dependency/service_case_open_requires_contract_active
        """
        scene = _calibrated_visit_with_a_pending_contract(plant)
        payload = module_fault_case_payload(
            scene.contract["id"],
            scene.cabinet["id"],
            scene.modules[0]["id"],
            symptom=CASE_SYMPTOM,
        )
        validate_error(
            plant.api.create_service_case(payload, plant.service), ERR_CONTRACT_NOT_ACTIVE, 409
        )

        plant.sign_off(scene.visit["id"], scene.crew["id"])
        case = validate_success(plant.api.create_service_case(payload, plant.service), 201)

        assert_case_fields(
            case,
            case_state=CASE_OPEN,
            case_type="MODULE_FAULT",
            severity="MAJOR",
            response_breached=False,
            faulty_module_id=scene.modules[0]["id"],
        )
        assert_instant_equals(case["reported_at"], VISIT_INSTANT, "reported_at")
        assert_instant_equals(
            case["response_deadline_at"], RESPONSE_DEADLINE_AT, "response_deadline_at"
        )
