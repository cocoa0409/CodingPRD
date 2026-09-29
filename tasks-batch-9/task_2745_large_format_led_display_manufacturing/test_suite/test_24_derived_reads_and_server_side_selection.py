"""What a cabinet reports before each of its derived fields has a trigger, and
the ranking the server applies when the caller declines to name a replacement.

The cabinet read is one surface over four fields with four different lifecycles:
a density that gains the soak's own findings, a live score that needs two
modules, and a baseline that only a passing verdict can write. The fulfil-side
selector then ranks on a different pair of keys from the reservation-side one.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_2dp,
    assert_cabinet_fields,
    assert_case_fields,
    assert_cents,
    assert_contract_fields,
    assert_module_fields,
    assert_run_fields,
)
from test_helpers.constants import (
    CABINET_BURN_IN_PASSED,
    CABINET_IN_ASSEMBLY,
    CABINET_PLANNED,
    CABINET_POPULATED,
    CASE_FULFILLED,
    CONTRACT_ACTIVE,
    MODULE_CALIBRATED,
    MODULE_INSTALLED,
    MODULE_RETURNED,
    SOAK_WINDOW_END,
)
from test_helpers.factories import FP16_STD, fulfil_payload

#: An FP16-STD cabinet is 2 modules x 64 x 32 = 4096 pixels, so one dead pixel is
#: 244.140625 ppm and two are 488.28125 ppm, both inside the family's 500.00 limit.
ONE_DEAD_PIXEL_PPM = 244.14
TWO_DEAD_PIXEL_PPM = 488.28

#: FP16-STD needs 150.00 kg/sqm of certified structural capacity.
FP16_REQUIRED_LOAD_KG_PER_SQM = 150.00

#: The wall's own pair, and the uniformity score they produce.
DIM_INSTALLED_NITS = 4900
BRIGHT_INSTALLED_NITS = 4950
DIM_INSTALLED_CHROMA = (0.3130, 0.3292)
BRIGHT_INSTALLED_CHROMA = (0.3128, 0.3290)
WALL_UNIFORMITY_SCORE = 97.68

#: Four reserved spares. The B1 panel is the brightest thing in stock and the
#: furthest from the outgoing A1 module; the two A1 panels share its bin gap of 0.
B1_SPARE_COLOR_X = 0.3178
A1_SPARE_CHROMA = (0.3130, 0.3290)
B1_SPARE_NITS = 4950
BRIGHTEST_A1_SPARE_NITS = 4850
DIMMER_A1_SPARE_NITS = 4820
A2_SPARE_NITS = 4700

#: The live score once (4850, 4950) hold the two slots.
UNIFORMITY_AFTER_SWAP = 96.54

#: A 300 basis point holding on the two-module wall obliges a single spare, so
#: three of the four held modules keep the contract comfortably above its floor.
TWO_MODULE_SPARE_REQUIRED_COUNT = 1


def _planned_cabinet_and_two_measured_modules(plant):
    """An FP16-STD cabinet still empty, with both its panels calibrated in stock."""
    scene = plant.approved_project_scene(
        model_base=FP16_STD,
        revision_overrides={"structural_load_kg_per_sqm": FP16_REQUIRED_LOAD_KG_PER_SQM},
    )
    scene.cabinet = plant.plan_cabinet(scene.project["id"])
    scene.dim = plant.calibrated_module(
        scene.model["id"],
        serial_no="M-DIM",
        dead_pixel_count=1,
        max_cluster_size=1,
        measured_brightness_nits=DIM_INSTALLED_NITS,
        measured_color_x=DIM_INSTALLED_CHROMA[0],
        measured_color_y=DIM_INSTALLED_CHROMA[1],
    )
    scene.bright = plant.calibrated_module(
        scene.model["id"],
        serial_no="M-BRIGHT",
        dead_pixel_count=0,
        max_cluster_size=0,
        measured_brightness_nits=BRIGHT_INSTALLED_NITS,
        measured_color_x=BRIGHT_INSTALLED_CHROMA[0],
        measured_color_y=BRIGHT_INSTALLED_CHROMA[1],
    )
    return scene


class TestCabinetReadAtEachStage:
    """Each derived field reads null or zero until its own trigger has fired."""

    def test_the_live_score_waits_for_the_second_module_and_the_baseline_for_the_soak(self, plant):
        """A planned cabinet begins in `cabinet_state` `PLANNED` with
        `installed_module_count` at 0, an empty `occupied_slot_indexes` list,
        `total_dead_pixel_count` at 0, `dead_pixel_ppm` at 0.00, an empty
        `baseline_module_ids` list, and both `as_built_uniformity_score` and
        `baseline_uniformity_score` null. It is therefore a live figure, and it is
        null until the cabinet holds two installed modules.

        Design: Corner/endpoints/cabinet_read_exposes_every_derived_field_at_each_stage
        """
        scene = _planned_cabinet_and_two_measured_modules(plant)

        empty = plant.cabinet(scene.cabinet["id"])
        assert_cabinet_fields(
            empty,
            cabinet_state=CABINET_PLANNED,
            installed_module_count=0,
            occupied_slot_indexes=[],
            total_dead_pixel_count=0,
        )
        assert_2dp(empty["dead_pixel_ppm"], 0.00, "dead_pixel_ppm")
        assert empty["as_built_uniformity_score"] is None
        assert empty["baseline_uniformity_score"] is None
        assert empty["baseline_module_ids"] == []

        plant.install(scene.cabinet["id"], scene.dim["id"], 1)

        half_built = plant.cabinet(scene.cabinet["id"])
        assert_cabinet_fields(
            half_built,
            cabinet_state=CABINET_IN_ASSEMBLY,
            installed_module_count=1,
            occupied_slot_indexes=[1],
            total_dead_pixel_count=1,
        )
        assert_2dp(half_built["dead_pixel_ppm"], ONE_DEAD_PIXEL_PPM, "dead_pixel_ppm")
        assert half_built["as_built_uniformity_score"] is None

        plant.install(scene.cabinet["id"], scene.bright["id"], 2)

        full = plant.cabinet(scene.cabinet["id"])
        assert_cabinet_fields(
            full,
            cabinet_state=CABINET_POPULATED,
            installed_module_count=2,
            occupied_slot_indexes=[1, 2],
            total_dead_pixel_count=1,
        )
        assert_2dp(
            full["as_built_uniformity_score"],
            WALL_UNIFORMITY_SCORE,
            "as_built_uniformity_score",
        )
        assert full["baseline_uniformity_score"] is None
        assert full["baseline_module_ids"] == []

    def test_the_soak_folds_its_own_findings_into_the_density_and_freezes_the_pair(self, plant):
        """Either outcome stores the three measurements, records
        `completed_by_user_id` as the acting `X-User-ID`, recomputes the cabinet's
        dead-pixel density with the new count folded in, and snapshots that figure
        onto the run as `cabinet_dead_pixel_ppm`, rounded to 2 decimal places. The
        uniformity procedure of §3.5 is evaluated once, at that instant, over the
        modules then holding `module_state` `INSTALLED` in the cabinet, and the
        result is written to `baseline_uniformity_score` while the participating
        module ids — ordered ascending by their `created_at` — are written to
        `baseline_module_ids`.

        Design: Corner/endpoints/cabinet_read_exposes_every_derived_field_at_each_stage
        """
        scene = _planned_cabinet_and_two_measured_modules(plant)
        plant.install(scene.cabinet["id"], scene.dim["id"], 1)
        plant.install(scene.cabinet["id"], scene.bright["id"], 2)
        chamber = plant.register_chamber()
        run = plant.schedule_run(scene.cabinet["id"], chamber["id"])
        plant.set_clock(SOAK_WINDOW_END)

        passed = plant.complete_run(run["id"], new_dead_pixel_count=1)

        assert_run_fields(passed, new_dead_pixel_count=1, completed_by_user_id="qa-1")
        assert_2dp(
            passed["cabinet_dead_pixel_ppm"], TWO_DEAD_PIXEL_PPM, "cabinet_dead_pixel_ppm"
        )
        soaked = plant.cabinet(scene.cabinet["id"])
        assert_cabinet_fields(
            soaked, cabinet_state=CABINET_BURN_IN_PASSED, total_dead_pixel_count=2
        )
        assert_2dp(soaked["dead_pixel_ppm"], TWO_DEAD_PIXEL_PPM, "dead_pixel_ppm")
        assert_2dp(
            soaked["baseline_uniformity_score"],
            WALL_UNIFORMITY_SCORE,
            "baseline_uniformity_score",
        )
        assert_2dp(
            soaked["as_built_uniformity_score"],
            WALL_UNIFORMITY_SCORE,
            "as_built_uniformity_score",
        )
        assert soaked["baseline_module_ids"] == [scene.dim["id"], scene.bright["id"]]
        assert_module_fields(
            plant.module(scene.dim["id"]),
            module_state=MODULE_INSTALLED,
            measured_brightness_nits=DIM_INSTALLED_NITS,
            dead_pixel_count=1,
        )


def _four_reserved_spares_and_an_approved_fault_case(plant):
    """A live wall whose slot-1 panel is approved for replacement, with a B1, two
    A1s and an A2 all held against the same contract."""
    scene = plant.commissioned_scene(
        model_base=FP16_STD,
        revision_overrides={"structural_load_kg_per_sqm": FP16_REQUIRED_LOAD_KG_PER_SQM},
        brightnesses=[DIM_INSTALLED_NITS, BRIGHT_INSTALLED_NITS],
        chroma=[DIM_INSTALLED_CHROMA, BRIGHT_INSTALLED_CHROMA],
    )
    scene.two_bins_away = plant.calibrated_module(
        scene.model["id"],
        serial_no="M-B1-SPARE",
        measured_brightness_nits=B1_SPARE_NITS,
        measured_color_x=B1_SPARE_COLOR_X,
        measured_color_y=A1_SPARE_CHROMA[1],
    )
    scene.brightest_same_bin = plant.calibrated_module(
        scene.model["id"],
        serial_no="M-A1-HIGH",
        measured_brightness_nits=BRIGHTEST_A1_SPARE_NITS,
        measured_color_x=A1_SPARE_CHROMA[0],
        measured_color_y=A1_SPARE_CHROMA[1],
    )
    scene.dimmer_same_bin = plant.calibrated_module(
        scene.model["id"],
        serial_no="M-A1-LOW",
        measured_brightness_nits=DIMMER_A1_SPARE_NITS,
        measured_color_x=A1_SPARE_CHROMA[0],
        measured_color_y=A1_SPARE_CHROMA[1],
    )
    scene.one_bin_away = plant.calibrated_module(
        scene.model["id"],
        serial_no="M-A2-SPARE",
        measured_brightness_nits=A2_SPARE_NITS,
        measured_color_x=A1_SPARE_CHROMA[0],
        measured_color_y=A1_SPARE_CHROMA[1],
    )
    for spare in (
        scene.two_bins_away,
        scene.brightest_same_bin,
        scene.dimmer_same_bin,
        scene.one_bin_away,
    ):
        plant.reserve_spare(scene.contract["id"], spare["id"])
    case = plant.open_module_fault_case(
        scene.contract["id"], scene.cabinet["id"], scene.modules[0]["id"]
    )
    plant.respond(case["id"])
    scene.case = plant.assess(case["id"], decision="APPROVE")
    scene.contract = plant.contract(scene.contract["id"])
    return scene


class TestServerSideReplacementSelection:
    """Closest colour first, and only then the brightest of that group."""

    def test_the_closest_bin_beats_the_brightest_panel_in_stock(self, plant):
        """When `replacement_module_id` is omitted the server picks from the modules
        that are `CALIBRATED`, match the project's pinned display model, are reserved
        to this contract, and sit within that colour-bin tolerance of the outgoing
        module; candidates are ordered by the absolute colour-bin rank gap
        **ascending** — closest colour match first — then by
        `measured_brightness_nits` **descending**, then by `created_at` ascending,
        and an empty pool is refused with `ERR_NO_ELIGIBLE_SPARE_MODULE`.

        Design: Corner/endpoints/fulfil_without_a_named_replacement_runs_the_spare_selector
        """
        scene = _four_reserved_spares_and_an_approved_fault_case(plant)
        assert_module_fields(
            plant.module(scene.two_bins_away["id"]), color_bin="B1", color_bin_rank=2
        )
        assert_module_fields(
            plant.module(scene.brightest_same_bin["id"]), color_bin="A1", color_bin_rank=0
        )
        assert_module_fields(
            plant.module(scene.one_bin_away["id"]), color_bin="A2", color_bin_rank=1
        )
        assert_module_fields(
            plant.module(scene.modules[0]["id"]), color_bin="A1", color_bin_rank=0
        )

        response = plant.api.fulfil_case(
            scene.case["id"],
            fulfil_payload(plant.cabinet_version(scene.cabinet["id"])),
            plant.service,
        )

        fulfilled = validate_success(response, 200)
        assert fulfilled["replacement_module_id"] == scene.brightest_same_bin["id"]
        for passed_over in (
            scene.two_bins_away,
            scene.dimmer_same_bin,
            scene.one_bin_away,
        ):
            assert_module_fields(
                plant.module(passed_over["id"]),
                module_state=MODULE_CALIBRATED,
                cabinet_id=None,
                slot_index=None,
                reserved_service_contract_id=scene.contract["id"],
            )
        assert_contract_fields(
            plant.contract(scene.contract["id"]),
            contract_state=CONTRACT_ACTIVE,
            spare_reserved_count=3,
            spare_required_count=TWO_MODULE_SPARE_REQUIRED_COUNT,
        )

    def test_the_swap_moves_the_live_score_and_leaves_the_frozen_one(self, plant):
        """Along the way the cabinet's `total_dead_pixel_count`, `dead_pixel_ppm` and
        `as_built_uniformity_score` are recomputed over its new module set while
        `baseline_uniformity_score` and `baseline_module_ids` are left exactly as
        burn-in froze them, and version increments land on the cabinet, the case and
        both modules.

        Design: Corner/endpoints/fulfil_without_a_named_replacement_runs_the_spare_selector
        """
        scene = _four_reserved_spares_and_an_approved_fault_case(plant)
        outgoing = scene.modules[0]

        fulfilled = validate_success(
            plant.api.fulfil_case(
                scene.case["id"],
                fulfil_payload(plant.cabinet_version(scene.cabinet["id"])),
                plant.service,
            ),
            200,
        )

        assert_case_fields(
            fulfilled,
            case_state=CASE_FULFILLED,
            resolved_faulty_module_id=outgoing["id"],
            replacement_module_id=scene.brightest_same_bin["id"],
        )
        assert_cents(fulfilled["credit_cents"], 0, "credit_cents")
        assert_module_fields(
            plant.module(outgoing["id"]),
            module_state=MODULE_RETURNED,
            cabinet_id=scene.cabinet["id"],
            slot_index=None,
        )
        assert_module_fields(
            plant.module(scene.brightest_same_bin["id"]),
            module_state=MODULE_INSTALLED,
            cabinet_id=scene.cabinet["id"],
            slot_index=1,
            replaces_module_id=outgoing["id"],
            reserved_service_contract_id=None,
        )
        swapped = plant.cabinet(scene.cabinet["id"])
        assert_cabinet_fields(
            swapped, installed_module_count=2, occupied_slot_indexes=[1, 2]
        )
        assert_2dp(
            swapped["as_built_uniformity_score"],
            UNIFORMITY_AFTER_SWAP,
            "as_built_uniformity_score",
        )
        assert_2dp(
            swapped["baseline_uniformity_score"],
            WALL_UNIFORMITY_SCORE,
            "baseline_uniformity_score",
        )
        assert swapped["baseline_module_ids"] == [
            outgoing["id"],
            scene.modules[1]["id"],
        ]
