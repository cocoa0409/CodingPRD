"""Catalogue and project records: derived geometry, defaults, filters and 404s.

The product family is where every downstream number comes from, so its derived
block is checked field by field at its declared precision, its optional inputs
are checked for their declared defaults, and its contradictory geometry is
checked for refusal rather than silent repair.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_PROJECT_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    ERR_VALIDATION_FAILED,
)
from test_helpers.assertions import (
    assert_2dp,
    assert_4dp,
    assert_cents,
    assert_common_fields,
    assert_fields_absent_or_null,
    assert_page_meta,
    assert_version,
    ids_of,
)
from test_helpers.constants import (
    ENGINEERING_DRAFT,
    MODULE_CALIBRATED,
    MODULE_MANUFACTURED,
    POSTURE_NORMAL,
    PRODUCTION_NOT_STARTED,
)
from test_helpers.factories import (
    FP10_IN,
    FP16_STD,
    FP25_OUT,
    cabinet_payload,
    display_model_payload,
    module_payload,
    project_payload,
)

AIRPORT_PROJECT_NAME = "Airport Concourse"
TWO_CABINET_FP16_CONTRACT_CENTS = 215040
TWO_CABINET_FP16_REQUIRED_MBPS = 15


def _total_count(response) -> int:
    _, meta = validate_paginated(response)
    return meta["total_count"]


class TestDisplayModelDerivedGeometry:
    """Six derived values, each at its own declared precision."""

    def test_registration_returns_the_whole_derived_block(self, plant):
        """From those inputs the service derives six values at registration time
        and stores them on the family.

        Design: Corner/entities/display_model_creation_returns_all_derived_geometry
        """
        model = validate_success(
            plant.api.create_display_model(display_model_payload(FP25_OUT), plant.admin), 201
        )

        assert_common_fields(model, "display_model")
        assert_version(model, 1, "display_model")
        assert_4dp(model["module_area_sqm"], 0.0512, "module_area_sqm")
        assert_4dp(model["cabinet_area_sqm"], 0.2048, "cabinet_area_sqm")
        assert model["module_pixel_count"] == 8192
        assert model["cabinet_pixel_count"] == 32768
        assert_2dp(
            model["recommended_min_viewing_distance_m"],
            2.5,
            "recommended_min_viewing_distance_m",
        )
        assert_2dp(model["required_load_kg_per_sqm"], 100.10, "required_load_kg_per_sqm")

    def test_a_read_returns_the_stored_row_without_bumping_the_version(self, plant):
        """`version`, an integer that starts at 1 on creation and increments by
        exactly 1 on every mutation of that record.

        Design: Corner/entities/display_model_retrieval_returns_the_stored_row
        """
        created = plant.register_model(FP16_STD)

        model = validate_success(
            plant.api.get_display_model(created["id"], plant.qa), 200
        )

        assert model["name"] == "FP16-STD"
        assert_2dp(model["pixel_pitch_mm"], 5.0, "pixel_pitch_mm")
        assert_4dp(model["module_area_sqm"], 0.0512, "module_area_sqm")
        assert_4dp(model["cabinet_area_sqm"], 0.1024, "cabinet_area_sqm")
        assert model["cabinet_pixel_count"] == 4096
        assert_2dp(
            model["recommended_min_viewing_distance_m"],
            5.0,
            "recommended_min_viewing_distance_m",
        )
        assert_2dp(model["required_load_kg_per_sqm"], 150.00, "required_load_kg_per_sqm")
        assert_version(model, 1, "display_model")

    def test_contradictory_geometry_is_refused_not_repaired(self, plant):
        """**Geometry is validated, never repaired**: a declared slot count that
        contradicts the dimensions, or a division that leaves a remainder, is
        rejected with `ERR_VALIDATION_FAILED` and no product family is created.

        Design: Corner/entities/display_model_geometry_inconsistent_modules_per_cabinet_rejected
        """
        wrong_slot_count = plant.api.create_display_model(
            display_model_payload(FP25_OUT, name="FP25-BAD", modules_per_cabinet=3),
            plant.admin,
        )
        validate_error(wrong_slot_count, ERR_VALIDATION_FAILED, 400)

        inexact_division = plant.api.create_display_model(
            display_model_payload(FP25_OUT, name="FP25-BAD2", module_width_mm=300),
            plant.admin,
        )
        validate_error(inexact_division, ERR_VALIDATION_FAILED, 400)

        assert _total_count(plant.api.list_display_models(plant.admin)) == 0

    def test_a_missing_required_specification_is_refused_and_nothing_persists(self, plant):
        """Screening stops there: no later rule is consulted, no partial write is
        kept, and nothing at all is persisted.

        Design: Corner/entities/display_model_create_missing_required_field_rejected
        """
        payload = display_model_payload(FP10_IN)
        payload.pop("rated_brightness_nits")

        response = plant.api.create_display_model(payload, plant.admin)

        validate_error(response, ERR_VALIDATION_FAILED, 400)
        assert _total_count(plant.api.list_display_models(plant.admin)) == 0

    def test_the_two_optional_pixel_limits_take_their_declared_defaults(self, plant):
        """`module_dead_pixel_max` and `module_cluster_max` govern the single-module
        pixel test: the first is the greatest number of dead pixels tolerated on one
        module and defaults to **3** when the caller omits it, the second is the
        largest adjacent dead-pixel cluster tolerated and defaults to **1**.

        Design: Corner/entities/display_model_omitted_pixel_limits_apply_declared_defaults
        """
        payload = display_model_payload(FP10_IN)
        payload.pop("module_dead_pixel_max")
        payload.pop("module_cluster_max")

        model = validate_success(plant.api.create_display_model(payload, plant.admin), 201)

        assert model["module_dead_pixel_max"] == 3
        assert model["module_cluster_max"] == 1

    def test_an_unknown_family_id_is_a_catalogue_reference_failure(self, plant):
        """For the three catalogue parents — a `display_model_id`, a
        `burn_in_chamber_id` or a `commissioning_crew_id` — a missing target yields
        `ERR_REFERENCE_NOT_FOUND`.

        Design: Corner/entities/display_model_get_unknown_id_returns_reference_not_found
        """
        response = plant.api.get_display_model(NON_EXISTENT_UUID, plant.admin)

        validate_error(response, ERR_REFERENCE_NOT_FOUND, 404)


class TestDisplayModelListing:
    """The rating filter narrows the population before the page window opens."""

    def test_the_rating_filter_narrows_the_count_the_page_window_reports(self, plant):
        """`limit` and `offset` echo the effective values used for the page,
        `total_count` reports how many records matched the filters before the page
        window was applied, and `has_more` is true exactly when records remain
        beyond the current window.

        Design: Corner/entities/display_model_listing_paginates_and_filters_by_environmental_rating
        """
        indoor = plant.register_model(FP10_IN)
        sealed = plant.register_model(FP16_STD)
        sealed_variant = plant.register_model(FP16_STD, name="FP16-STD-B")

        unfiltered, unfiltered_meta = validate_paginated(
            plant.api.list_display_models(plant.service, params={"limit": 2, "offset": 0})
        )
        assert_page_meta(unfiltered_meta, limit=2, offset=0, total_count=3, has_more=True)
        assert len(unfiltered) == 2

        first_page, first_meta = validate_paginated(
            plant.api.list_display_models(
                plant.service,
                params={"environmental_rating": "IP65_FULL", "limit": 1, "offset": 0},
            )
        )
        assert_page_meta(first_meta, limit=1, offset=0, total_count=2, has_more=True)
        assert len(first_page) == 1
        assert first_page[0]["environmental_rating"] == "IP65_FULL"

        second_page, second_meta = validate_paginated(
            plant.api.list_display_models(
                plant.service,
                params={"environmental_rating": "IP65_FULL", "limit": 1, "offset": 1},
            )
        )
        assert_page_meta(second_meta, limit=1, offset=1, total_count=2, has_more=False)
        assert len(second_page) == 1

        filtered_ids = ids_of(first_page) + ids_of(second_page)
        assert indoor["id"] not in filtered_ids
        assert sorted(filtered_ids) == sorted([sealed["id"], sealed_variant["id"]])


class TestModuleRegistrationDefaults:
    """A freshly manufactured module carries no measurements at all."""

    def test_a_new_module_starts_unmeasured_and_unplaced(self, plant):
        """A fresh module starts in `module_state` `MANUFACTURED` with
        `rework_cycles` at 0, no measurements recorded, and no placement — its
        `cabinet_id`, `slot_index`, `replaces_module_id` and
        `reserved_service_contract_id` are all unset, and `dead_pixel_count`,
        `max_cluster_size` and `color_bin` are all null until the relevant test
        runs.

        Design: Corner/entities/module_create_defaults_state_counter_and_nullable_measurements
        """
        model = plant.register_model(FP10_IN)

        module = validate_success(
            plant.api.create_module(module_payload(model["id"], "M-1"), plant.operator), 201
        )

        assert module["module_state"] == MODULE_MANUFACTURED
        assert module["rework_cycles"] == 0
        assert_fields_absent_or_null(
            module,
            "color_bin",
            "color_bin_rank",
            "dead_pixel_count",
            "max_cluster_size",
            "measured_brightness_nits",
            "cabinet_id",
            "slot_index",
            "replaces_module_id",
            "reserved_service_contract_id",
        )
        assert_version(module, 1, "module")


class TestProjectCreationDerivations:
    """The wall's fan-out, price and bandwidth all fall out of the grid."""

    def test_creation_derives_the_fan_out_and_both_state_dimensions(self, plant):
        """A newly created project starts with `engineering_state` at `DRAFT`,
        `production_state` at `NOT_STARTED` and `service_posture` at `NORMAL`, with
        `approved_revision_number` unset and every derived cabinet counter at zero.

        Design: Corner/entities/project_creation_derives_counts_area_and_both_initial_state_fields
        """
        model = plant.register_model(FP16_STD)

        project = validate_success(
            plant.api.create_project(
                project_payload(
                    model["id"],
                    customer_name=AIRPORT_PROJECT_NAME,
                    cabinet_grid_cols=2,
                    cabinet_grid_rows=1,
                    min_viewing_distance_m=5.0,
                ),
                plant.engineer,
            ),
            201,
        )

        assert project["cabinet_count"] == 2
        assert project["module_count"] == 4
        assert_4dp(project["total_area_sqm"], 0.2048, "total_area_sqm")
        assert project["engineering_state"] == ENGINEERING_DRAFT
        assert project["production_state"] == PRODUCTION_NOT_STARTED
        assert project["service_posture"] == POSTURE_NORMAL
        assert_fields_absent_or_null(project, "approved_revision_number")
        assert project["qa_passed_cabinet_count"] == 0
        assert project["mounted_cabinet_count"] == 0
        assert project["quarantined_cabinet_count"] == 0
        assert_cents(
            project["contract_amount_cents"],
            TWO_CABINET_FP16_CONTRACT_CENTS,
            "contract_amount_cents",
        )
        assert project["required_data_mbps"] == TWO_CABINET_FP16_REQUIRED_MBPS
        assert project["effective_capacity_mbps"] == 1000
        assert_2dp(project["data_load_pct"], 1.50, "data_load_pct")

    def test_closed_enums_and_declared_ranges_are_enforced(self, plant):
        """`color_depth_bits` is 8, 10 or 12 bits per colour channel, `refresh_rate_hz`
        is between 24 and 240 inclusive, and `player_count` is the number of content
        players between 1 and 16, each contributing 2500 Mbps of throughput.

        Design: Corner/entities/project_invalid_color_depth_enum_rejected
        """
        model = plant.register_model(FP10_IN)

        nine_bit = plant.api.create_project(
            project_payload(model["id"], customer_name="Nine Bit Wall", color_depth_bits=9),
            plant.engineer,
        )
        validate_error(nine_bit, ERR_VALIDATION_FAILED, 400)

        unknown_mode = plant.api.create_project(
            project_payload(
                model["id"], customer_name="Bad Redundancy", redundancy_mode="TRIPLE_LINK"
            ),
            plant.engineer,
        )
        validate_error(unknown_mode, ERR_VALIDATION_FAILED, 400)

        oversized_grid = plant.api.create_project(
            project_payload(model["id"], customer_name="Grid Too Wide", cabinet_grid_cols=41),
            plant.engineer,
        )
        validate_error(oversized_grid, ERR_VALIDATION_FAILED, 400)

        assert _total_count(plant.api.list_projects(plant.engineer)) == 0

    def test_an_unknown_family_pin_is_refused_before_any_geometry_is_derived(self, plant):
        """The project pins exactly one product family through `display_model_id`,
        and that pin fixes the geometry, the price per square metre and every
        quality threshold for the whole life of the project.

        Design: Corner/entities/project_create_unknown_display_model_returns_reference_not_found
        """
        response = plant.api.create_project(
            project_payload(NON_EXISTENT_UUID, customer_name="Orphan Project"),
            plant.engineer,
        )

        validate_error(response, ERR_REFERENCE_NOT_FOUND, 404)
        assert _total_count(plant.api.list_projects(plant.engineer)) == 0

    def test_an_unknown_project_on_cabinet_planning_has_its_own_code(self, plant):
        """A referenced `project_id`, whether in a path or a body, resolves to a
        project — otherwise `ERR_PROJECT_NOT_FOUND`.

        Design: Corner/entities/cabinet_create_unknown_project_returns_project_not_found
        """
        response = plant.api.create_cabinet(cabinet_payload(NON_EXISTENT_UUID), plant.operator)

        validate_error(response, ERR_PROJECT_NOT_FOUND, 404)
        assert _total_count(plant.api.list_cabinets(plant.operator)) == 0


class TestModuleListingFilters:
    """The filtered list is the only reverse-reachability channel for a cabinet."""

    def test_the_cabinet_and_state_filters_intersect(self, plant):
        """Every filter is optional, and supplying several narrows the result set by
        all of them at once.

        Design: Corner/entities/module_listing_filters_by_state_and_cabinet_fk
        """
        scene = plant.populated_cabinet_scene(
            model_base=FP16_STD,
            project_overrides={"min_viewing_distance_m": 5.0},
            revision_overrides={"structural_load_kg_per_sqm": 150.00},
        )
        spare = plant.calibrated_module(scene.model["id"])

        installed, installed_meta = validate_paginated(
            plant.api.list_modules(plant.qa, params={"cabinet_id": scene.cabinet["id"]})
        )
        assert installed_meta["total_count"] == 2
        assert sorted(ids_of(installed)) == sorted(
            [scene.modules[0]["id"], scene.modules[1]["id"]]
        )

        shelved, shelved_meta = validate_paginated(
            plant.api.list_modules(plant.qa, params={"module_state": MODULE_CALIBRATED})
        )
        assert shelved_meta["total_count"] == 1
        assert ids_of(shelved) == [spare["id"]]

        intersection, intersection_meta = validate_paginated(
            plant.api.list_modules(
                plant.qa,
                params={
                    "cabinet_id": scene.cabinet["id"],
                    "module_state": MODULE_CALIBRATED,
                },
            )
        )
        assert intersection_meta["total_count"] == 0
        assert intersection_meta["has_more"] is False
        assert intersection == []

        assert _total_count(plant.api.list_modules(plant.qa)) == 3
