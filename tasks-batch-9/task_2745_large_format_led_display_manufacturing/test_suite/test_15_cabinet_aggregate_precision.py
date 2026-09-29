"""The two cabinet aggregates that a single install or removal has to recompute.

Uniformity stacks three roundings at three different precisions and needs two
modules before it means anything, while dead-pixel density keeps the family's
whole pixel count in the denominator however many modules are currently fitted.
"""

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_2dp,
    assert_cabinet_fields,
    assert_module_fields,
    assert_project_fields,
)
from test_helpers.constants import (
    CABINET_IN_ASSEMBLY,
    CABINET_POPULATED,
    MODULE_CALIBRATED,
    MODULE_INSTALLED,
    PRODUCTION_IN_ASSEMBLY,
)
from test_helpers.factories import FP16_STD, remove_module_payload

#: The FP16-STD family needs 150.00 kg/sqm of structural capacity, so its drawing
#: package has to clear a higher floor than the default FP10-IN wall.
FP16_REQUIRED_LOAD_KG_PER_SQM = 150.00

#: Two modules 50 nits apart around a mean of 4925 and one ten-thousandth apart
#: on each chroma axis.
DIM_MODULE_NITS = 4900
BRIGHT_MODULE_NITS = 4950
DIM_MODULE_CHROMA = (0.3130, 0.3292)
BRIGHT_MODULE_CHROMA = (0.3128, 0.3291)

#: 100 - 1.5 x 1.0152 - 2000 x 0.000300 = 97.8772, rounded to 97.88.
TWO_MODULE_UNIFORMITY_SCORE = 97.88

#: A tolerance tight enough to separate 97.88 from 97.89, from 97.87 and from the
#: unrounded 97.8772.
SCORE_EPSILON = 0.001

#: An FP16-STD cabinet carries 4096 pixels whatever is fitted into its two slots.
FULL_CABINET_DEAD_PIXEL_PPM = 488.28
HALF_CABINET_DEAD_PIXEL_PPM = 244.14


def _assert_uniformity_score(actual, expected, field):
    """Compare a uniformity score tightly enough that the roundings are pinned."""
    assert actual is not None, f"{field} must not be null"
    assert actual == pytest.approx(expected, abs=SCORE_EPSILON), (
        f"{field}: expected {expected}, got {actual}"
    )


def _fp16_wall_with_two_calibrated_modules(plant):
    """An approved two-slot wall, one planned cabinet, two modules ready to fit."""
    scene = plant.approved_project_scene(
        model_base=FP16_STD,
        revision_overrides={"structural_load_kg_per_sqm": FP16_REQUIRED_LOAD_KG_PER_SQM},
    )
    scene.cabinet = plant.plan_cabinet(scene.project["id"])
    scene.dim = plant.calibrated_module(
        scene.model["id"],
        serial_no="M-DIM",
        measured_brightness_nits=DIM_MODULE_NITS,
        measured_color_x=DIM_MODULE_CHROMA[0],
        measured_color_y=DIM_MODULE_CHROMA[1],
    )
    scene.bright = plant.calibrated_module(
        scene.model["id"],
        serial_no="M-BRIGHT",
        measured_brightness_nits=BRIGHT_MODULE_NITS,
        measured_color_x=BRIGHT_MODULE_CHROMA[0],
        measured_color_y=BRIGHT_MODULE_CHROMA[1],
    )
    return scene


class TestAsBuiltUniformityScore:
    """A live score with a two-module floor and three pinned roundings."""

    def test_one_installed_module_leaves_the_score_null(self, plant):
        """The score requires at least **two** modules in the set; with fewer than
        two it is null. It is therefore a live figure, and it is null until the
        cabinet holds two installed modules.

        Design: Corner/calculations/cabinet_uniformity_score_precision_and_two_module_floor
        """
        scene = _fp16_wall_with_two_calibrated_modules(plant)

        plant.install(scene.cabinet["id"], scene.dim["id"], 1)

        half_filled = plant.cabinet(scene.cabinet["id"])
        assert half_filled["as_built_uniformity_score"] is None
        assert_cabinet_fields(
            half_filled,
            cabinet_state=CABINET_IN_ASSEMBLY,
            installed_module_count=1,
            occupied_slot_indexes=[1],
        )

    def test_the_second_module_pins_all_three_roundings_at_once(self, plant):
        """Over whichever set applies, take the mean of the modules'
        `measured_brightness_nits` — carried at full precision, not rounded — and
        compute the brightness spread as the highest measured brightness minus the
        lowest, divided by that mean, multiplied by 100, rounded to 4 decimal
        places. Compute the chroma spread as the range of `measured_color_x` across
        the set (its maximum minus its minimum) plus the range of `measured_color_y`,
        rounded to 6 decimal places. The score is then 100, less 1.5 times the
        brightness spread percentage, less 2000 times the chroma spread, rounded to
        2 decimal places and floored at 0.00 so that a badly mismatched cabinet
        never scores negative.

        Design: Corner/calculations/cabinet_uniformity_score_precision_and_two_module_floor
        """
        scene = _fp16_wall_with_two_calibrated_modules(plant)
        plant.install(scene.cabinet["id"], scene.dim["id"], 1)

        plant.install(scene.cabinet["id"], scene.bright["id"], 2)

        cabinet = plant.cabinet(scene.cabinet["id"])
        _assert_uniformity_score(
            cabinet["as_built_uniformity_score"],
            TWO_MODULE_UNIFORMITY_SCORE,
            "as_built_uniformity_score",
        )
        assert cabinet["baseline_uniformity_score"] is None
        assert cabinet["baseline_module_ids"] == []
        assert_cabinet_fields(
            cabinet,
            cabinet_state=CABINET_POPULATED,
            installed_module_count=2,
            occupied_slot_indexes=[1, 2],
        )


class TestDeadPixelDensityAcrossARemoval:
    """The numerator follows the fitted modules; the denominator never moves."""

    def _populated_fp16_cabinet(self, plant):
        return plant.populated_cabinet_scene(
            model_base=FP16_STD,
            revision_overrides={"structural_load_kg_per_sqm": FP16_REQUIRED_LOAD_KG_PER_SQM},
            dead_pixel_counts=[1, 1],
        )

    def test_the_density_halves_over_the_same_pixel_count(self, plant):
        """`dead_pixel_ppm` is then that total divided by the family's
        `cabinet_pixel_count`, multiplied by one million to express it in parts per
        million, rounded to 2 decimal places. This is the figure burn-in compares
        against the family's `dead_pixel_ppm_limit`, and it is recomputed on every
        module install, every module removal, every burn-in completion and every
        warranty module swap.

        Design: Corner/calculations/cabinet_dead_pixel_ppm_drops_the_removed_module
        """
        scene = self._populated_fp16_cabinet(plant)
        before = plant.cabinet(scene.cabinet["id"])
        assert_cabinet_fields(before, total_dead_pixel_count=2)
        assert_2dp(before["dead_pixel_ppm"], FULL_CABINET_DEAD_PIXEL_PPM, "dead_pixel_ppm")

        response = plant.api.remove_module(
            scene.cabinet["id"],
            remove_module_payload(
                scene.modules[1]["id"], plant.cabinet_version(scene.cabinet["id"])
            ),
            plant.operator,
        )

        validate_success(response, 201)
        after = plant.cabinet(scene.cabinet["id"])
        assert_cabinet_fields(after, total_dead_pixel_count=1)
        assert_2dp(after["dead_pixel_ppm"], HALF_CABINET_DEAD_PIXEL_PPM, "dead_pixel_ppm")

    def test_the_removal_takes_the_module_out_and_steps_the_cabinet_back(self, plant):
        """A cabinet's `total_dead_pixel_count` is the sum of `dead_pixel_count`
        over the modules whose `cabinet_id` is this cabinet **and** whose
        `module_state` is `INSTALLED` — modules that have been returned or scrapped
        are excluded even where they retain a `cabinet_id` for traceability — plus
        the `new_dead_pixel_count` of the cabinet's most recent burn-in run whose
        `run_state` is `PASSED` or `FAILED`, taking the last such run in ascending
        `created_at` order, and adding nothing when no such run exists.

        Design: Corner/calculations/cabinet_dead_pixel_ppm_drops_the_removed_module
        """
        scene = self._populated_fp16_cabinet(plant)
        retained, withdrawn = scene.modules[0], scene.modules[1]

        plant.remove(scene.cabinet["id"], withdrawn["id"])

        assert_cabinet_fields(
            plant.cabinet(scene.cabinet["id"]),
            cabinet_state=CABINET_IN_ASSEMBLY,
            installed_module_count=1,
            occupied_slot_indexes=[1],
            total_dead_pixel_count=1,
        )
        assert plant.cabinet(scene.cabinet["id"])["as_built_uniformity_score"] is None
        assert_module_fields(
            plant.module(withdrawn["id"]),
            module_state=MODULE_CALIBRATED,
            cabinet_id=None,
            slot_index=None,
            dead_pixel_count=1,
        )
        assert_module_fields(
            plant.module(retained["id"]), module_state=MODULE_INSTALLED, slot_index=1
        )
        assert_project_fields(
            plant.project(scene.project["id"]), production_state=PRODUCTION_IN_ASSEMBLY
        )
