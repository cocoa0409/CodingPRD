"""Colour calibration: the three tolerance bands and the two binning thresholds.

One endpoint reads a single chroma error against three constants and can
calibrate, rework or refuse outright, and a calibrated module is then binned by
two independent comparisons — one on the chroma error, one on brightness.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import ERR_CHROMA_OUT_OF_TOLERANCE
from test_helpers.assertions import assert_module_fields, assert_version
from test_helpers.constants import (
    MODULE_CALIBRATED,
    MODULE_PIXEL_TESTED,
    MODULE_REWORK,
)
from test_helpers.factories import calibrate_payload
from test_helpers.test_users import USER_PRODUCTION_OPERATOR

#: The FP10-IN family declares reference_color_x 0.3128 and reference_color_y
#: 0.3290, so holding y at the reference makes the x offset the chroma error.
REFERENCE_COLOR_Y = 0.3290

#: A chroma error of exactly 0.003 — the inner letter threshold.
LETTER_A_EDGE_X = 0.3158
#: One ten-thousandth past the letter threshold, still well inside the
#: calibrate band.
LETTER_B_EDGE_X = 0.3159
#: A chroma error of exactly 0.008 — the upper edge of the calibrate band.
CALIBRATE_EDGE_X = 0.3208
#: A chroma error of 0.0081 — the first value in the rework band.
REWORK_BAND_X = 0.3209
#: A chroma error of 0.0201 — the first value past the reworkable band.
BEYOND_REWORK_X = 0.3329
#: A chroma error of exactly zero: the module measures the reference colour.
EXACT_REFERENCE_X = 0.3128

#: ceil(5000 x 0.96) = 4800 nits, the floor for bin digit 1 on a 5000 nit family.
DIGIT_1_FLOOR_NITS = 4800
#: One nit below that floor, so the module bins with digit 2.
DIGIT_2_NITS = 4799
#: Comfortably above the digit floor, so brightness never decides the letter tests.
BRIGHT_NITS = 4900


def _pixel_tested_module(plant, model_id, serial_no):
    """A module that has passed its dead-pixel test and awaits calibration."""
    module = plant.register_module(model_id, serial_no)
    return plant.pixel_test(module["id"])


class TestColourBinLetter:
    """The letter split sits at 0.003, not at the calibrate-or-rework line."""

    def test_a_chroma_error_at_the_inner_threshold_still_bins_as_letter_a(self, plant):
        """The service computes the module's chroma error as the larger of two
        absolute differences: the gap between `measured_color_x` and the family's
        `reference_color_x`, and the gap between `measured_color_y` and the
        family's `reference_color_y`. A calibrated module is also **binned**, and
        the bin letter uses a stricter inner threshold than the
        calibrate-or-rework split, so a module can legitimately calibrate and
        still land in the weaker letter band. The letter is `A` when the chroma
        error is at most 0.003 and `B` otherwise.

        Design: Corner/calculations/color_bin_letter_and_digit_sit_on_their_own_thresholds
        """
        model = plant.register_model()
        at_threshold = _pixel_tested_module(plant, model["id"], "M-A1")
        past_threshold = _pixel_tested_module(plant, model["id"], "M-B1")

        binned_a = plant.calibrate(
            at_threshold["id"], BRIGHT_NITS, LETTER_A_EDGE_X, REFERENCE_COLOR_Y
        )
        binned_b = plant.calibrate(
            past_threshold["id"], BRIGHT_NITS, LETTER_B_EDGE_X, REFERENCE_COLOR_Y
        )

        assert_module_fields(
            binned_a,
            module_state=MODULE_CALIBRATED,
            color_bin="A1",
            color_bin_rank=0,
            rework_cycles=0,
            calibrated_by_user_id=USER_PRODUCTION_OPERATOR,
        )
        assert_module_fields(
            binned_b,
            module_state=MODULE_CALIBRATED,
            color_bin="B1",
            color_bin_rank=2,
            rework_cycles=0,
            calibrated_by_user_id=USER_PRODUCTION_OPERATOR,
        )

    def test_the_digit_floor_is_the_ninety_six_percent_fraction_rounded_up(self, plant):
        """The digit is `1` when `measured_brightness_nits` is at least 96 percent
        of the family's `rated_brightness_nits`, that floor being rounded **up**
        to a whole number of nits, and `2` otherwise. The two characters
        concatenate into `color_bin`, which is therefore one of `A1`, `A2`, `B1`
        or `B2`, and the service also stores `color_bin_rank` as the bin's ordinal
        for later replacement matching: `A1` ranks 0, `A2` ranks 1, `B1` ranks 2
        and `B2` ranks 3.

        Design: Corner/calculations/color_bin_letter_and_digit_sit_on_their_own_thresholds
        """
        model = plant.register_model()
        at_floor = _pixel_tested_module(plant, model["id"], "M-A1-FLOOR")
        below_floor = _pixel_tested_module(plant, model["id"], "M-A2")

        binned_one = plant.calibrate(
            at_floor["id"], DIGIT_1_FLOOR_NITS, EXACT_REFERENCE_X, REFERENCE_COLOR_Y
        )
        binned_two = plant.calibrate(
            below_floor["id"], DIGIT_2_NITS, EXACT_REFERENCE_X, REFERENCE_COLOR_Y
        )

        assert_module_fields(
            binned_one,
            module_state=MODULE_CALIBRATED,
            color_bin="A1",
            color_bin_rank=0,
            rework_cycles=0,
            measured_brightness_nits=DIGIT_1_FLOOR_NITS,
        )
        assert_module_fields(
            binned_two,
            module_state=MODULE_CALIBRATED,
            color_bin="A2",
            color_bin_rank=1,
            rework_cycles=0,
            measured_brightness_nits=DIGIT_2_NITS,
        )


class TestChromaThreeBandLadder:
    """One measurement, three outcomes, and each boundary belongs to the lower band."""

    def test_the_calibrate_band_includes_its_own_upper_edge(self, plant):
        """A chroma error of 0.008 or less calibrates the module: the measurements
        are stored, the module moves `PIXEL_TESTED → CALIBRATED`, and the acting
        `X-User-ID` is recorded as `calibrated_by_user_id` — the field that later
        blocks that same identity from QA-approving any cabinet holding this
        module.

        Design: Corner/calculations/chroma_three_band_ladder_calibrates_reworks_and_rejects
        """
        model = plant.register_model()
        module = _pixel_tested_module(plant, model["id"], "M-EDGE")

        calibrated = plant.calibrate(
            module["id"], BRIGHT_NITS, CALIBRATE_EDGE_X, REFERENCE_COLOR_Y
        )

        assert_module_fields(
            calibrated,
            module_state=MODULE_CALIBRATED,
            color_bin="B1",
            color_bin_rank=2,
            rework_cycles=0,
            calibrated_by_user_id=USER_PRODUCTION_OPERATOR,
        )

    def test_one_ten_thousandth_further_out_reworks_and_keeps_the_evidence(self, plant):
        """A chroma error greater than 0.008 but no greater than 0.020 lands in the
        rework band: the three measurements are stored, `color_bin` stays null, and
        the rework accounting above runs — so the module goes
        `PIXEL_TESTED → REWORK` (or `REWORK → REWORK`) while the two-cycle
        allowance holds, and `PIXEL_TESTED → SCRAPPED` (or `REWORK → SCRAPPED`)
        once the incremented count exceeds it.

        Design: Corner/calculations/chroma_three_band_ladder_calibrates_reworks_and_rejects
        """
        model = plant.register_model()
        module = _pixel_tested_module(plant, model["id"], "M-REWORK")

        reworked = plant.calibrate(
            module["id"], BRIGHT_NITS, REWORK_BAND_X, REFERENCE_COLOR_Y
        )

        assert_module_fields(
            reworked,
            module_state=MODULE_REWORK,
            color_bin=None,
            color_bin_rank=None,
            rework_cycles=1,
            measured_brightness_nits=BRIGHT_NITS,
        )
        assert reworked["measured_color_x"] == REWORK_BAND_X
        assert reworked["measured_color_y"] == REFERENCE_COLOR_Y

    def test_beyond_the_reworkable_band_the_call_stores_nothing_at_all(self, plant):
        """A chroma error greater than 0.020 means the panel is not reworkable at
        all: the request is refused with `ERR_CHROMA_OUT_OF_TOLERANCE`, **no
        measurement is stored, `rework_cycles` is untouched and the module does not
        change state**.

        Design: Corner/calculations/chroma_three_band_ladder_calibrates_reworks_and_rejects
        """
        model = plant.register_model()
        module = _pixel_tested_module(plant, model["id"], "M-REFUSED")
        assert_version(module, 2, "module")

        response = plant.api.calibrate_module(
            module["id"],
            calibrate_payload(BRIGHT_NITS, BEYOND_REWORK_X, REFERENCE_COLOR_Y),
            plant.operator,
        )

        validate_error(response, ERR_CHROMA_OUT_OF_TOLERANCE, 422)
        untouched = plant.module(module["id"])
        assert_module_fields(
            untouched,
            module_state=MODULE_PIXEL_TESTED,
            rework_cycles=0,
            color_bin=None,
            color_bin_rank=None,
            measured_brightness_nits=None,
            calibrated_by_user_id=None,
        )
        assert untouched["measured_color_x"] is None
        assert untouched["measured_color_y"] is None
        assert_version(untouched, 2, "module")
