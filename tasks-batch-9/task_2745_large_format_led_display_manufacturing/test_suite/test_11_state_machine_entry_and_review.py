"""Entry states and the two-person engineering review loop.

A record's first stored shape is as much a contract as its transitions, so this
module pins the opening state of a planned cabinet, a submitted drawing revision
and a pixel-tested module, then walks the review loop through rejection,
resubmission, the independence gate and the terminal approval that closes it.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_ENGINEERING_ALREADY_APPROVED,
    ERR_ENGINEERING_NOT_APPROVED,
    ERR_INVALID_REVISION_STATE,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import (
    assert_2dp,
    assert_cabinet_fields,
    assert_fields_absent_or_null,
    assert_module_fields,
    assert_page_meta,
    assert_project_fields,
    assert_version,
)
from test_helpers.constants import (
    CABINET_IN_ASSEMBLY,
    CABINET_MOUNTED,
    CABINET_PLANNED,
    CABINET_POPULATED,
    ENGINEERING_APPROVED,
    ENGINEERING_DRAFT,
    ENGINEERING_REJECTED,
    ENGINEERING_UNDER_REVIEW,
    MODULE_CALIBRATED,
    MODULE_INSTALLED,
    MODULE_PIXEL_TESTED,
    PRODUCTION_IN_ASSEMBLY,
    PRODUCTION_INSTALLED,
    PRODUCTION_NOT_STARTED,
    PRODUCTION_QA_COMPLETE,
    REVISION_APPROVED,
    REVISION_REJECTED,
    REVISION_SUBMITTED,
    SOAK_WINDOW_END,
)
from test_helpers.factories import (
    FP16_STD,
    FP25_OUT,
    drawing_revision_payload,
    install_module_payload,
    review_payload,
)
from test_helpers.test_users import (
    USER_DESIGN_ENGINEER,
    USER_STRUCTURAL_REVIEWER,
    make_structural_reviewer_headers,
)

#: A stadium wall must be rated for at least 160 kph, and the drawing certifies
#: a 120.00 kg/sqm capacity against the family's 100.10 kg/sqm floor.
STADIUM_CERTIFIED_LOAD = 120.00
STADIUM_WIND_LOAD_KPH = 160

#: The FP25-OUT load floor the revision snapshots, unchanged by what is certified.
FP25_OUT_REQUIRED_LOAD = 100.10

REJECTION_REASON = "Anchor spacing does not clear the sprinkler main"
SECOND_THOUGHTS_REASON = "Second thoughts about the anchors"

#: One dead pixel in a 4096-pixel FP16-STD cabinet.
HALF_FILLED_DEAD_PIXEL_PPM = 244.14

#: A second FP16-STD module, calibrated slightly brighter than the first.
SECOND_MODULE_BRIGHTNESS = 4950
SECOND_MODULE_CHROMA_X = 0.3128
SECOND_MODULE_CHROMA_Y = 0.3291


def _two_cabinet_wall_ready_to_mount(plant):
    """A 2x1 FP10-IN wall whose two cabinets have both been QA-signed."""
    scene = plant.approved_project_scene(
        project_overrides={"cabinet_grid_rows": 2, "cabinet_grid_cols": 1}
    )
    chamber = plant.register_chamber()
    cabinets = []
    runs = []
    for grid_row in (1, 2):
        cabinet = plant.plan_cabinet(scene.project["id"], grid_row=grid_row, grid_col=1)
        plant.populate_cabinet(cabinet["id"], scene.model["id"], modules_per_cabinet=1)
        runs.append(plant.schedule_run(cabinet["id"], chamber["id"]))
        cabinets.append(cabinet)
    plant.set_clock(SOAK_WINDOW_END)
    for run in runs:
        plant.complete_run(run["id"])
    for cabinet in cabinets:
        plant.qa_approve(cabinet["id"])
    scene.cabinets = cabinets
    scene.crew = plant.register_crew()
    return scene


class TestCabinetPlanningEntryState:
    """Planning a position reserves it without starting any lifecycle."""

    def test_a_planned_cabinet_starts_empty_and_moves_neither_project_dimension(
        self, plant
    ):
        """A planned cabinet begins in `cabinet_state` `PLANNED` with
        `installed_module_count` at 0, an empty `occupied_slot_indexes` list,
        `total_dead_pixel_count` at 0, `dead_pixel_ppm` at 0.00, an empty
        `baseline_module_ids` list, and both `as_built_uniformity_score` and
        `baseline_uniformity_score` null.

        Design: Corner/state_machines/cabinet_created_starts_in_planned_with_empty_slot_map
        """
        model = plant.register_model()
        project = plant.create_project(model["id"])

        cabinet = plant.plan_cabinet(project["id"])

        assert_cabinet_fields(
            cabinet,
            cabinet_state=CABINET_PLANNED,
            installed_module_count=0,
            occupied_slot_indexes=[],
            total_dead_pixel_count=0,
            qa_approved_by_user_id=None,
        )
        assert_2dp(cabinet["dead_pixel_ppm"], 0.00, "dead_pixel_ppm")
        assert cabinet["baseline_module_ids"] == [], (
            f"baseline_module_ids must start empty, got {cabinet['baseline_module_ids']!r}"
        )
        assert_fields_absent_or_null(
            cabinet, "as_built_uniformity_score", "baseline_uniformity_score"
        )
        assert_version(cabinet, 1, "cabinet")

        unchanged = plant.project(project["id"])
        assert_project_fields(
            unchanged,
            engineering_state=ENGINEERING_DRAFT,
            production_state=PRODUCTION_NOT_STARTED,
        )


class TestDrawingRevisionSubmissionEntryState:
    """Submission freezes the bar the drawing will be judged against."""

    def test_submission_snapshots_the_family_load_floor_and_opens_the_review(self, plant):
        """It snapshots the family's current `required_load_kg_per_sqm` onto the
        revision's own `required_load_kg_per_sqm` field, freezing the bar the
        drawing was judged against, records `submitted_by_user_id` as the
        submitting `X-User-ID`, sets `revision_state` to `SUBMITTED`, and moves the
        project's `engineering_state` from `DRAFT` or `REJECTED` to `UNDER_REVIEW`,
        taking a version increment and a fresh `updated_at` on the project as well
        as on the new revision.

        Design: Corner/state_machines/drawing_revision_created_starts_submitted_and_snapshots_required_load
        """
        model = plant.register_model(FP25_OUT)
        project = plant.create_project(model["id"], install_environment="STADIUM")

        revision = plant.submit_revision(
            project["id"],
            structural_load_kg_per_sqm=STADIUM_CERTIFIED_LOAD,
            wind_load_kph=STADIUM_WIND_LOAD_KPH,
            mounting_type="GANTRY",
            service_access_side="REAR",
        )

        assert revision["revision_state"] == REVISION_SUBMITTED
        assert revision["revision_number"] == 1
        assert_2dp(
            revision["required_load_kg_per_sqm"],
            FP25_OUT_REQUIRED_LOAD,
            "required_load_kg_per_sqm",
        )
        assert_2dp(
            revision["structural_load_kg_per_sqm"],
            STADIUM_CERTIFIED_LOAD,
            "structural_load_kg_per_sqm",
        )
        assert revision["submitted_by_user_id"] == USER_DESIGN_ENGINEER
        assert_fields_absent_or_null(revision, "reviewed_by_user_id", "rejection_reason")

        opened = plant.project(project["id"])
        assert_project_fields(
            opened,
            engineering_state=ENGINEERING_UNDER_REVIEW,
            production_state=PRODUCTION_NOT_STARTED,
            approved_revision_number=None,
        )


class TestModulePixelTestEntryTransition:
    """A test exactly at both ceilings is a pass, not a rework."""

    def test_a_test_at_both_ceilings_advances_the_module_to_pixel_tested(self, plant):
        """The test passes when the reported dead-pixel count is at most the
        family's `module_dead_pixel_max` **and** the reported cluster size is at
        most the family's `module_cluster_max`; a passing test advances the module
        `MANUFACTURED → PIXEL_TESTED`, or `REWORK → PIXEL_TESTED` when it is a
        retest after rework, and in the retest case it does so **without touching
        `rework_cycles`**.

        Design: Corner/state_machines/pixel_test_moves_module_manufactured_to_pixel_tested
        """
        model = plant.register_model()
        module = plant.register_module(model["id"])

        tested = plant.pixel_test(module["id"], 3, 1)

        assert_module_fields(
            tested,
            module_state=MODULE_PIXEL_TESTED,
            dead_pixel_count=3,
            max_cluster_size=1,
            rework_cycles=0,
            color_bin=None,
            color_bin_rank=None,
        )
        assert_version(tested, 2, "module")


class TestRevisionReviewCycle:
    """The engineering dimension loops until one drawing is finally approved."""

    def test_a_rejection_then_a_resubmission_returns_the_project_to_review(self, plant):
        """`REJECT` moves the revision `SUBMITTED → REJECTED`, requires the `reason`
        to be present and between 1 and 240 characters (a missing or empty reason is
        refused with `ERR_VALIDATION_FAILED`), stores it as the revision's
        `rejection_reason`, moves the project's `engineering_state`
        `UNDER_REVIEW → REJECTED`, and leaves `approved_revision_number` unset.

        Design: Corner/state_machines/revision_reject_then_resubmit_returns_project_to_under_review
        """
        model = plant.register_model()
        project = plant.create_project(model["id"])
        first = plant.submit_revision(project["id"])

        rejected = plant.review_revision(first["id"], "REJECT", REJECTION_REASON)

        assert rejected["revision_state"] == REVISION_REJECTED
        assert rejected["rejection_reason"] == REJECTION_REASON
        assert rejected["reviewed_by_user_id"] == USER_STRUCTURAL_REVIEWER
        assert_project_fields(
            plant.project(project["id"]),
            engineering_state=ENGINEERING_REJECTED,
            approved_revision_number=None,
        )

        second = plant.submit_revision(project["id"])
        assert second["revision_number"] == 2
        assert second["revision_state"] == REVISION_SUBMITTED
        assert_project_fields(
            plant.project(project["id"]), engineering_state=ENGINEERING_UNDER_REVIEW
        )

        approved = plant.review_revision(second["id"], "APPROVE")
        assert approved["revision_state"] == REVISION_APPROVED
        assert_project_fields(
            plant.project(project["id"]),
            engineering_state=ENGINEERING_APPROVED,
            approved_revision_number=2,
        )
        assert plant.revision(first["id"])["revision_state"] == REVISION_REJECTED

        listed, meta = validate_paginated(
            plant.api.list_drawing_revisions(plant.engineer, {"project_id": project["id"]})
        )
        assert_page_meta(meta, total_count=2)
        assert len(listed) == 2

    def test_the_submitter_may_not_review_their_own_drawing(self, plant):
        """The reviewer's `X-User-ID` must differ from the revision's
        `submitted_by_user_id`, or the decision is refused with
        `ERR_SEGREGATION_OF_DUTIES`.

        Design: Corner/state_machines/revision_review_by_the_submitter_rejected
        """
        model = plant.register_model()
        project = plant.create_project(model["id"])
        revision = plant.submit_revision(project["id"])

        refused = plant.api.review_drawing_revision(
            revision["id"],
            review_payload("APPROVE"),
            make_structural_reviewer_headers(USER_DESIGN_ENGINEER),
        )

        validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 403)
        still_open = plant.revision(revision["id"])
        assert still_open["revision_state"] == REVISION_SUBMITTED
        assert_fields_absent_or_null(still_open, "reviewed_by_user_id")
        assert_project_fields(
            plant.project(project["id"]), engineering_state=ENGINEERING_UNDER_REVIEW
        )

        approved = plant.review_revision(revision["id"], "APPROVE")
        assert approved["revision_state"] == REVISION_APPROVED
        assert approved["reviewed_by_user_id"] == USER_STRUCTURAL_REVIEWER
        assert_project_fields(
            plant.project(project["id"]),
            engineering_state=ENGINEERING_APPROVED,
            approved_revision_number=1,
        )

    def test_an_approved_package_refuses_both_a_re_review_and_a_new_drawing(self, plant):
        """First, a project whose `engineering_state` has already reached `APPROVED`
        accepts nothing further: the submission is refused with
        `ERR_ENGINEERING_ALREADY_APPROVED`.

        Design: Corner/state_machines/review_and_resubmission_after_approval_both_rejected
        """
        scene = plant.approved_project_scene()

        re_review = plant.api.review_drawing_revision(
            scene.revision["id"],
            review_payload("REJECT", SECOND_THOUGHTS_REASON),
            make_structural_reviewer_headers(),
        )
        validate_error(re_review, ERR_INVALID_REVISION_STATE, 409)

        resubmission = plant.api.create_drawing_revision(
            drawing_revision_payload(
                scene.project["id"],
                structural_load_kg_per_sqm=130.00,
                wind_load_kph=120,
            ),
            plant.engineer,
        )
        validate_error(resubmission, ERR_ENGINEERING_ALREADY_APPROVED, 409)

        revision = plant.revision(scene.revision["id"])
        assert revision["revision_state"] == REVISION_APPROVED
        assert_fields_absent_or_null(revision, "rejection_reason")
        assert_project_fields(
            plant.project(scene.project["id"]),
            engineering_state=ENGINEERING_APPROVED,
            approved_revision_number=1,
        )

        listed, meta = validate_paginated(
            plant.api.list_drawing_revisions(
                plant.engineer, {"project_id": scene.project["id"]}
            )
        )
        assert_page_meta(meta, total_count=1)
        assert len(listed) == 1


class TestInstallEngineeringGate:
    """An unapproved package stops assembly without consuming the version."""

    def test_the_refused_install_writes_nothing_and_leaves_the_version_usable(self, plant):
        """A project's `engineering_state` is `APPROVED` before any module may be
        installed into one of its cabinets or any of its cabinets mounted —
        otherwise `ERR_ENGINEERING_NOT_APPROVED`.

        Design: Corner/state_machines/install_module_before_engineering_approval_rejected
        """
        model = plant.register_model()
        project = plant.create_project(model["id"])
        revision = plant.submit_revision(project["id"])
        cabinet = plant.plan_cabinet(project["id"])
        module = plant.calibrated_module(model["id"])
        version_at_plan = cabinet["version"]

        refused = plant.api.install_module(
            cabinet["id"],
            install_module_payload(module["id"], 1, version_at_plan),
            plant.operator,
        )

        validate_error(refused, ERR_ENGINEERING_NOT_APPROVED, 409)
        untouched = plant.cabinet(cabinet["id"])
        assert_cabinet_fields(
            untouched, cabinet_state=CABINET_PLANNED, installed_module_count=0
        )
        assert_version(untouched, version_at_plan, "cabinet")
        assert_module_fields(
            plant.module(module["id"]), module_state=MODULE_CALIBRATED, cabinet_id=None
        )

        plant.review_revision(revision["id"], "APPROVE")
        installed = validate_success(
            plant.api.install_module(
                cabinet["id"],
                install_module_payload(module["id"], 1, version_at_plan),
                plant.operator,
            ),
            201,
        )

        assert_module_fields(
            installed,
            module_state=MODULE_INSTALLED,
            cabinet_id=cabinet["id"],
            slot_index=1,
        )
        assert_cabinet_fields(
            plant.cabinet(cabinet["id"]),
            cabinet_state=CABINET_POPULATED,
            installed_module_count=1,
        )
        assert_project_fields(
            plant.project(project["id"]), production_state=PRODUCTION_IN_ASSEMBLY
        )


class TestFirstInstallAssemblyTransition:
    """A half-filled cabinet is in assembly, and assembly is not population."""

    def test_a_half_filled_cabinet_enters_assembly_without_reaching_populated(
        self, plant
    ):
        """The first module installed in a cabinet moves it `PLANNED → IN_ASSEMBLY`,
        and the install that brings `installed_module_count` up to the family's
        `modules_per_cabinet` moves it `IN_ASSEMBLY → POPULATED`.

        Design: Corner/state_machines/first_module_install_moves_cabinet_and_project_into_assembly
        """
        scene = plant.approved_project_scene(
            model_base=FP16_STD,
            revision_overrides={"structural_load_kg_per_sqm": 150.00},
        )
        cabinet = plant.plan_cabinet(scene.project["id"])
        first = plant.calibrated_module(scene.model["id"])
        second = plant.calibrated_module(
            scene.model["id"],
            measured_brightness_nits=SECOND_MODULE_BRIGHTNESS,
            measured_color_x=SECOND_MODULE_CHROMA_X,
            measured_color_y=SECOND_MODULE_CHROMA_Y,
        )
        version_at_plan = cabinet["version"]

        installed = plant.install(cabinet["id"], first["id"], 1)

        assert_module_fields(
            installed,
            module_state=MODULE_INSTALLED,
            cabinet_id=cabinet["id"],
            slot_index=1,
        )
        half_filled = plant.cabinet(cabinet["id"])
        assert_cabinet_fields(
            half_filled,
            cabinet_state=CABINET_IN_ASSEMBLY,
            installed_module_count=1,
            occupied_slot_indexes=[1],
            total_dead_pixel_count=1,
        )
        assert_2dp(
            half_filled["dead_pixel_ppm"], HALF_FILLED_DEAD_PIXEL_PPM, "dead_pixel_ppm"
        )
        assert_fields_absent_or_null(half_filled, "as_built_uniformity_score")
        assert_version(half_filled, version_at_plan + 1, "cabinet")
        assert_module_fields(
            plant.module(second["id"]), module_state=MODULE_CALIBRATED, cabinet_id=None
        )

        project = plant.project(scene.project["id"])
        assert_project_fields(project, production_state=PRODUCTION_IN_ASSEMBLY)
        assert project["version"] > scene.project["version"], (
            "the project takes a version increment when its dimension moved"
        )


class TestFinalMountPromotion:
    """Only the mount that completes the wall promotes the project."""

    def test_the_last_mount_bubbles_the_project_to_installed(self, plant):
        """When every cabinet of the project is mounted — that is, when the
        recomputed count equals `cabinet_count` — the project rises
        `QA_COMPLETE → INSTALLED`.

        Design: Corner/state_machines/mount_of_the_last_cabinet_bubbles_the_project_to_installed
        """
        scene = _two_cabinet_wall_ready_to_mount(plant)
        assert_project_fields(
            plant.project(scene.project["id"]),
            engineering_state=ENGINEERING_APPROVED,
            production_state=PRODUCTION_QA_COMPLETE,
            cabinet_count=2,
            qa_passed_cabinet_count=2,
        )

        first = plant.mount(scene.cabinets[0]["id"], scene.crew["id"])

        assert_cabinet_fields(first, cabinet_state=CABINET_MOUNTED)
        assert_project_fields(
            plant.project(scene.project["id"]),
            mounted_cabinet_count=1,
            production_state=PRODUCTION_QA_COMPLETE,
        )

        second = plant.mount(scene.cabinets[1]["id"], scene.crew["id"])

        assert_cabinet_fields(second, cabinet_state=CABINET_MOUNTED)
        assert_project_fields(
            plant.project(scene.project["id"]),
            mounted_cabinet_count=2,
            production_state=PRODUCTION_INSTALLED,
            engineering_state=ENGINEERING_APPROVED,
        )
