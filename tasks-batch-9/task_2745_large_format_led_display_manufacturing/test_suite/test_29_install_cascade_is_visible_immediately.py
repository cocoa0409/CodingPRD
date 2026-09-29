"""One write, four rows, and no second chance to get them right.

An install moves the module, the cabinet's counters and state, the project's
production dimension, and the index that answers a filtered module listing. Every
one of them is read back by a different role on the very next request, so nothing
here can be reconciled by a later sweep or recomputed lazily on read.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.assertions import (
    assert_2dp,
    assert_cabinet_fields,
    assert_module_fields,
    assert_page_meta,
    assert_project_fields,
    assert_version,
    ids_of,
)
from test_helpers.constants import (
    CABINET_IN_ASSEMBLY,
    ENGINEERING_APPROVED,
    MODULE_INSTALLED,
    PRODUCTION_IN_ASSEMBLY,
)
from test_helpers.factories import FP16_STD, install_module_payload

#: The FP16-STD family certifies 150.00 kg/sqm and counts 4096 pixels per cabinet.
FP16_REQUIRED_LOAD_KG_PER_SQM = 150.00

#: One dead pixel over 4096 is 244.14 parts per million at 2 decimal places.
ONE_DEAD_PIXEL = 1
ONE_DEAD_PIXEL_PPM = 244.14

#: A freshly planned cabinet is at version 1, and the first slot is slot 1.
FIRST_VERSION = 1
FIRST_SLOT = 1


def _one_calibrated_module_and_an_empty_cabinet(plant):
    """An approved FP16-STD wall, a cabinet still at PLANNED, and one panel ready."""
    scene = plant.approved_project_scene(
        model_base=FP16_STD,
        revision_overrides={"structural_load_kg_per_sqm": FP16_REQUIRED_LOAD_KG_PER_SQM},
    )
    scene.cabinet = plant.plan_cabinet(scene.project["id"])
    scene.module = plant.calibrated_module(
        scene.model["id"],
        serial_no="M-1",
        dead_pixel_count=ONE_DEAD_PIXEL,
        max_cluster_size=1,
    )
    return scene


class TestTheInstallResponseAlreadyCarriesTheWrite:
    """The body answers with the row as the handler left it, not as it found it."""

    def test_the_returned_module_is_the_written_module(self, plant):
        """A successful install writes the cabinet's id into the module's `cabinet_id`,
        stores the `slot_index`, and moves the module `CALIBRATED → INSTALLED`. The
        response returns the updated module rather than the cabinet.

        Design: Corner/consistency_model/one_install_call_publishes_its_whole_cascade_immediately
        """
        scene = _one_calibrated_module_and_an_empty_cabinet(plant)
        assert_version(scene.cabinet, FIRST_VERSION, "cabinet")
        calibrated_version = scene.module["version"]

        installed = validate_success(
            plant.api.install_module(
                scene.cabinet["id"],
                install_module_payload(
                    scene.module["id"], FIRST_SLOT, scene.cabinet["version"]
                ),
                plant.operator,
            ),
            201,
        )

        assert_module_fields(
            installed,
            module_state=MODULE_INSTALLED,
            cabinet_id=scene.cabinet["id"],
            slot_index=FIRST_SLOT,
            dead_pixel_count=ONE_DEAD_PIXEL,
        )
        assert_version(installed, calibrated_version + 1, "module")

        read_back = plant.module(scene.module["id"])
        assert_module_fields(
            read_back,
            module_state=MODULE_INSTALLED,
            cabinet_id=scene.cabinet["id"],
            slot_index=FIRST_SLOT,
        )
        assert_version(read_back, calibrated_version + 1, "module")
        assert read_back["updated_at"] == installed["updated_at"]


class TestTheWholeCascadeIsTrueOnItsFirstObservation:
    """Three further rows, read by a role that took no part in the write."""

    def test_the_cabinet_counters_and_density_are_current_at_once(self, plant):
        """On the cabinet side it recomputes `installed_module_count`, rebuilds
        `occupied_slot_indexes` as the ascending sorted list of slot indexes held by
        modules currently `INSTALLED` there, and refreshes `total_dead_pixel_count`,
        `dead_pixel_ppm` and `as_built_uniformity_score`. The first module installed in
        a cabinet moves it `PLANNED → IN_ASSEMBLY`.

        Design: Corner/consistency_model/one_install_call_publishes_its_whole_cascade_immediately
        """
        scene = _one_calibrated_module_and_an_empty_cabinet(plant)
        cabinet_version = scene.cabinet["version"]

        validate_success(
            plant.api.install_module(
                scene.cabinet["id"],
                install_module_payload(scene.module["id"], FIRST_SLOT, cabinet_version),
                plant.operator,
            ),
            201,
        )

        cabinet = validate_success(
            plant.api.get_cabinet(scene.cabinet["id"], plant.qa), 200
        )
        assert_cabinet_fields(
            cabinet,
            cabinet_state=CABINET_IN_ASSEMBLY,
            installed_module_count=1,
            occupied_slot_indexes=[FIRST_SLOT],
            total_dead_pixel_count=ONE_DEAD_PIXEL,
        )
        assert_2dp(cabinet["dead_pixel_ppm"], ONE_DEAD_PIXEL_PPM, "dead_pixel_ppm")
        assert_version(cabinet, cabinet_version + 1, "cabinet")

    def test_the_project_dimension_and_the_module_index_move_in_the_same_write(self, plant):
        """This holds for every record a cascade touches, not only the record the
        caller named: when a module installation lifts a cabinet out of `PLANNED` and a
        project out of `NOT_STARTED`, the module, the cabinet and the project each take
        a version increment.

        Design: Corner/consistency_model/one_install_call_publishes_its_whole_cascade_immediately
        """
        scene = _one_calibrated_module_and_an_empty_cabinet(plant)
        project_version = scene.project["version"]

        validate_success(
            plant.api.install_module(
                scene.cabinet["id"],
                install_module_payload(
                    scene.module["id"], FIRST_SLOT, scene.cabinet["version"]
                ),
                plant.operator,
            ),
            201,
        )

        project = validate_success(
            plant.api.get_project(scene.project["id"], plant.qa), 200
        )
        assert_project_fields(
            project,
            engineering_state=ENGINEERING_APPROVED,
            production_state=PRODUCTION_IN_ASSEMBLY,
        )
        assert_version(project, project_version + 1, "project")

        rows, meta = validate_paginated(
            plant.api.list_modules(plant.qa, {"cabinet_id": scene.cabinet["id"]})
        )
        assert ids_of(rows) == [scene.module["id"]]
        assert_page_meta(meta, total_count=1, has_more=False)
