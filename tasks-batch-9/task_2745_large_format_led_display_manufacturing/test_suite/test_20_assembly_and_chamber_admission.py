"""Admission rules on the shop floor, where one code covers two failures.

A cabinet position, a module serial and a slot index each have a single error
code standing in front of two distinct failures, so an implementation that
enforces only the uniqueness half passes half the checks. The install ladder then
distinguishes a foreign module from a reserved spare, and the chamber booking
takes the lower of two independent drive-level certifications.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import (
    ERR_CABINET_POSITION_TAKEN,
    ERR_CABINET_SLOT_OCCUPIED,
    ERR_CREW_REGION_MISMATCH,
    ERR_DRIVE_LEVEL_UNSAFE,
    ERR_MODULE_MODEL_MISMATCH,
    ERR_MODULE_RESERVED_AS_SPARE,
    ERR_MODULE_SERIAL_DUPLICATE,
)
from test_helpers.assertions import (
    assert_4dp,
    assert_cabinet_fields,
    assert_chamber_fields,
    assert_contract_fields,
    assert_module_fields,
    assert_page_meta,
    assert_project_fields,
    assert_run_fields,
    assert_version,
    assert_visit_fields,
    ids_of,
)
from test_helpers.constants import (
    CABINET_BURN_IN,
    CABINET_PLANNED,
    CABINET_POPULATED,
    MODULE_CALIBRATED,
    MODULE_INSTALLED,
    MODULE_MANUFACTURED,
    RUN_SCHEDULED,
    VISIT_SCHEDULED,
    VISIT_WINDOW_END,
    VISIT_WINDOW_START,
)
from test_helpers.factories import (
    FP16_STD,
    burn_in_run_payload,
    cabinet_payload,
    commissioning_visit_payload,
    install_module_payload,
    module_payload,
)

#: A 1x1 FP10-IN wall: one cabinet, one module, 0.1024 sqm of active area.
SINGLE_CABINET_AREA_SQM = 0.1024

#: FP16-STD carries two slots, so slot 3 is outside the family geometry.
FP16_SLOT_COUNT = 2
OUT_OF_RANGE_SLOT = 3
FP16_REQUIRED_LOAD_KG_PER_SQM = 150.00

#: The serial reused across two different product families.
DUPLICATE_SERIAL = "M-DUP"

#: The site region the project is licensed for, and the crew that is not.
WEST_REGION_CODE = "NAW"
EAST_REGION_CODE = "NAE"

#: The FP10-IN family tops out at 90 percent drive; the two chambers are
#: certified either side of that figure.
MODEL_MAX_DRIVE_PCT = 90
GENEROUS_CHAMBER_DRIVE_PCT = 95
CONSERVATIVE_CHAMBER_DRIVE_PCT = 80


class TestCabinetPositionEnvelope:
    """One code for a taken position and for a position off the grid entirely."""

    def test_a_duplicate_position_and_a_position_off_the_grid_share_one_code(self, plant):
        """The position must lie inside the project's declared grid — the row no
        greater than `cabinet_grid_rows`, the column no greater than
        `cabinet_grid_cols` — and no other cabinet of that project may already hold
        it; a duplicate position and a position outside the grid are both refused
        with `ERR_CABINET_POSITION_TAKEN`.

        Design: Corner/validations/cabinet_position_must_be_free_and_inside_the_grid
        """
        model = plant.register_model()
        project = plant.create_project(model["id"])
        cabinet = plant.plan_cabinet(project["id"])

        duplicate = plant.api.create_cabinet(
            cabinet_payload(project["id"], grid_row=1, grid_col=1), plant.operator
        )
        outside = plant.api.create_cabinet(
            cabinet_payload(project["id"], grid_row=1, grid_col=2), plant.operator
        )

        validate_error(duplicate, ERR_CABINET_POSITION_TAKEN, 409)
        validate_error(outside, ERR_CABINET_POSITION_TAKEN, 409)
        read = plant.project(project["id"])
        assert_project_fields(read, cabinet_count=1, module_count=1)
        assert_4dp(read["total_area_sqm"], SINGLE_CABINET_AREA_SQM, "total_area_sqm")
        rows, meta = validate_paginated(
            plant.api.list_cabinets(plant.operator, {"project_id": project["id"]})
        )
        assert ids_of(rows) == [cabinet["id"]]
        assert_page_meta(meta, total_count=1, has_more=False)


class TestModuleSerialUniquenessScope:
    """The scope is the whole module population, not one product family."""

    def test_the_same_serial_is_refused_against_a_different_family(self, plant):
        """Serials are globally unique across all modules; reusing one is refused
        with `ERR_MODULE_SERIAL_DUPLICATE`.

        Design: Corner/validations/module_serial_number_is_globally_unique
        """
        first_model = plant.register_model()
        second_model = plant.register_model(FP16_STD)
        original = plant.register_module(first_model["id"], DUPLICATE_SERIAL)

        response = plant.api.create_module(
            module_payload(second_model["id"], DUPLICATE_SERIAL), plant.operator
        )

        validate_error(response, ERR_MODULE_SERIAL_DUPLICATE, 409)
        rows, meta = validate_paginated(
            plant.api.list_modules(
                plant.operator, {"display_model_id": second_model["id"]}
            )
        )
        assert rows == []
        assert_page_meta(meta, total_count=0, has_more=False)
        untouched = plant.module(original["id"])
        assert_module_fields(untouched, module_state=MODULE_MANUFACTURED)
        assert_version(untouched, 1, "module")


class TestSlotIndexEnvelope:
    """A filled slot and a slot beyond the geometry are refused identically."""

    def test_neither_refusal_consumes_the_module_or_the_cabinet_version(self, plant):
        """The requested `slot_index` must lie between 1 and the family's
        `modules_per_cabinet` inclusive and must not already appear in the
        cabinet's `occupied_slot_indexes` (`ERR_CABINET_SLOT_OCCUPIED`).

        Design: Corner/validations/slot_index_must_be_free_and_within_the_model_geometry
        """
        scene = plant.approved_project_scene(
            FP16_STD,
            revision_overrides={
                "structural_load_kg_per_sqm": FP16_REQUIRED_LOAD_KG_PER_SQM
            },
        )
        assert scene.model["modules_per_cabinet"] == FP16_SLOT_COUNT
        cabinet = plant.plan_cabinet(scene.project["id"])
        first = plant.calibrated_module(scene.model["id"], serial_no="M-SLOT-1")
        second = plant.calibrated_module(scene.model["id"], serial_no="M-SLOT-2")
        plant.install(cabinet["id"], first["id"], 1)
        held_version = plant.cabinet_version(cabinet["id"])

        occupied = plant.api.install_module(
            cabinet["id"],
            install_module_payload(second["id"], 1, held_version),
            plant.operator,
        )
        out_of_range = plant.api.install_module(
            cabinet["id"],
            install_module_payload(second["id"], OUT_OF_RANGE_SLOT, held_version),
            plant.operator,
        )

        validate_error(occupied, ERR_CABINET_SLOT_OCCUPIED, 409)
        validate_error(out_of_range, ERR_CABINET_SLOT_OCCUPIED, 409)
        assert plant.cabinet_version(cabinet["id"]) == held_version

        installed = validate_success(
            plant.api.install_module(
                cabinet["id"],
                install_module_payload(second["id"], 2, held_version),
                plant.operator,
            ),
            201,
        )

        assert_module_fields(installed, module_state=MODULE_INSTALLED, slot_index=2)
        assert_cabinet_fields(
            plant.cabinet(cabinet["id"]),
            cabinet_state=CABINET_POPULATED,
            installed_module_count=FP16_SLOT_COUNT,
            occupied_slot_indexes=[1, 2],
        )


class TestReservedSpareIsNotProductionStock:
    """A reserved spare is still CALIBRATED, so only the reservation check stops it."""

    def test_a_held_spare_is_refused_on_the_reservation_not_the_module_state(self, plant):
        """And finally the module must not be held as a contracted spare, meaning
        its `reserved_service_contract_id` must be unset
        (`ERR_MODULE_RESERVED_AS_SPARE`).

        Design: Corner/validations/contracted_spare_cannot_be_installed_into_production
        """
        scene = plant.approved_project_scene()
        cabinet = plant.plan_cabinet(scene.project["id"])
        contract = plant.sell_contract(scene.project["id"])
        spare = plant.calibrated_module(scene.model["id"], serial_no="M-SPARE")
        plant.reserve_spare(contract["id"], spare["id"])

        response = plant.api.install_module(
            cabinet["id"],
            install_module_payload(spare["id"], 1, plant.cabinet_version(cabinet["id"])),
            plant.operator,
        )

        validate_error(response, ERR_MODULE_RESERVED_AS_SPARE, 409)
        held = plant.module(spare["id"])
        assert_module_fields(
            held,
            module_state=MODULE_CALIBRATED,
            cabinet_id=None,
            slot_index=None,
            reserved_service_contract_id=contract["id"],
        )
        untouched = plant.cabinet(cabinet["id"])
        assert_cabinet_fields(
            untouched,
            cabinet_state=CABINET_PLANNED,
            installed_module_count=0,
            occupied_slot_indexes=[],
        )
        assert_version(untouched, 1, "cabinet")
        assert_contract_fields(
            plant.contract(contract["id"]), spare_reserved_count=1, spare_required_count=1
        )


class TestModuleFamilyMustMatchTheWall:
    """The comparison walks the cabinet's project, because a cabinet has no family."""

    def test_a_calibrated_module_of_another_family_is_refused(self, plant):
        """The module's `display_model_id` must equal the display model pinned by
        the cabinet's project (`ERR_MODULE_MODEL_MISMATCH`).

        Design: Corner/validations/module_of_a_foreign_display_model_cannot_be_installed
        """
        scene = plant.approved_project_scene()
        cabinet = plant.plan_cabinet(scene.project["id"])
        foreign_model = plant.register_model(FP16_STD)
        foreign = plant.calibrated_module(foreign_model["id"], serial_no="M-FOREIGN")

        response = plant.api.install_module(
            cabinet["id"],
            install_module_payload(
                foreign["id"], 1, plant.cabinet_version(cabinet["id"])
            ),
            plant.operator,
        )

        validate_error(response, ERR_MODULE_MODEL_MISMATCH, 422)
        assert_module_fields(
            plant.module(foreign["id"]),
            module_state=MODULE_CALIBRATED,
            cabinet_id=None,
            slot_index=None,
        )
        untouched = plant.cabinet(cabinet["id"])
        assert_cabinet_fields(
            untouched, cabinet_state=CABINET_PLANNED, installed_module_count=0
        )
        assert_version(untouched, 1, "cabinet")


class TestCrewLicensingByRegion:
    """A free calendar does not license a crew for somebody else's region."""

    def test_only_the_in_region_crew_takes_the_identical_window(self, plant):
        """And only afterwards is licensing checked, where a crew whose
        `region_code` differs from the project's `site_region_code` is refused with
        `ERR_CREW_REGION_MISMATCH`. A booking that survives both is created with
        `visit_state` `SCHEDULED`, and the crew's `scheduled_visit_count` rises by
        1.

        Design: Corner/validations/crew_region_must_match_the_project_site
        """
        model = plant.register_model()
        project = plant.create_project(model["id"], site_region_code=WEST_REGION_CODE)
        east_crew = plant.register_crew(
            name="Crew East", region_code=EAST_REGION_CODE
        )
        west_crew = plant.register_crew(region_code=WEST_REGION_CODE)

        refused = plant.api.create_commissioning_visit(
            commissioning_visit_payload(
                project["id"],
                east_crew["id"],
                window_start=VISIT_WINDOW_START,
                window_end=VISIT_WINDOW_END,
            ),
            plant.admin,
        )
        accepted = plant.api.create_commissioning_visit(
            commissioning_visit_payload(
                project["id"],
                west_crew["id"],
                window_start=VISIT_WINDOW_START,
                window_end=VISIT_WINDOW_END,
            ),
            plant.admin,
        )

        validate_error(refused, ERR_CREW_REGION_MISMATCH, 422)
        assert plant.crew(east_crew["id"])["scheduled_visit_count"] == 0
        visit = validate_success(accepted, 201)
        assert_visit_fields(
            visit,
            visit_state=VISIT_SCHEDULED,
            commissioning_crew_id=west_crew["id"],
        )
        assert plant.crew(west_crew["id"])["scheduled_visit_count"] == 1


class TestDriveLevelCeiling:
    """The ceiling is the lower of two certifications and both must be consulted."""

    def test_each_of_the_two_ceilings_binds_on_its_own(self, plant):
        """The requested `drive_pct` must not exceed **either** the family's
        `max_drive_pct` **or** the chamber's `certified_max_drive_pct` — that is,
        it must be at most the smaller of the two — and exceeding either ceiling is
        refused as `ERR_DRIVE_LEVEL_UNSAFE`.

        Design: Corner/validations/drive_level_is_capped_by_the_lower_of_two_certifications
        """
        scene = plant.populated_cabinet_scene()
        assert scene.model["max_drive_pct"] == MODEL_MAX_DRIVE_PCT
        generous = plant.register_chamber(
            name="CH-HI", certified_max_drive_pct=GENEROUS_CHAMBER_DRIVE_PCT
        )
        conservative = plant.register_chamber(
            name="CH-LO", certified_max_drive_pct=CONSERVATIVE_CHAMBER_DRIVE_PCT
        )

        over_model = plant.api.create_burn_in_run(
            burn_in_run_payload(
                scene.cabinet["id"],
                generous["id"],
                drive_pct=GENEROUS_CHAMBER_DRIVE_PCT,
            ),
            plant.qa,
        )
        over_chamber = plant.api.create_burn_in_run(
            burn_in_run_payload(
                scene.cabinet["id"], conservative["id"], drive_pct=MODEL_MAX_DRIVE_PCT
            ),
            plant.qa,
        )

        validate_error(over_model, ERR_DRIVE_LEVEL_UNSAFE, 422)
        validate_error(over_chamber, ERR_DRIVE_LEVEL_UNSAFE, 422)
        assert_cabinet_fields(
            plant.cabinet(scene.cabinet["id"]), cabinet_state=CABINET_POPULATED
        )

        booked = validate_success(
            plant.api.create_burn_in_run(
                burn_in_run_payload(
                    scene.cabinet["id"], generous["id"], drive_pct=MODEL_MAX_DRIVE_PCT
                ),
                plant.qa,
            ),
            201,
        )

        assert booked["drive_pct"] == MODEL_MAX_DRIVE_PCT
        assert_run_fields(booked, run_state=RUN_SCHEDULED, slots_required=1)
        assert_cabinet_fields(
            plant.cabinet(scene.cabinet["id"]), cabinet_state=CABINET_BURN_IN
        )
        assert_chamber_fields(
            plant.chamber(generous["id"]), reserved_slot_total=1, scheduled_run_count=1
        )
        assert_chamber_fields(
            plant.chamber(conservative["id"]),
            reserved_slot_total=0,
            scheduled_run_count=0,
        )
