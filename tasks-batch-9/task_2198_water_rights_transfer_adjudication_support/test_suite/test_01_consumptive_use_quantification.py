"""Quantifying historical consumptive use — the five pinned volume steps.

PRD §3.3: "Nothing may be transferred out of a right until the department has
quantified what the right has historically consumed, as distinct from what its
certificate nominally authorizes."
"""
import pytest
from test_helpers import ApiErrorId, get_success_data, validate_error, validate_success
from test_helpers.fixtures import (
    activate_right,
    add_use_records_from_spec,
    create_study,
    setup_documented_right,
)


class TestMethodDivergenceOverIdenticalRecords:
    """PRD §3.3 — "For identical records the two methods return materially
    different volumes, so which method gets certified determines how much water
    the right may ever move."
    """

    # 2023 / 2024 / 2025 metered diversions on a steady 100.00 irrigated acres.
    RECORDS = (
        (2023, 210.500, 100.00, "METER"),
        (2024, 198.250, 100.00, "METER"),
        (2025, 205.000, 100.00, "METER"),
    )

    def _quantified_right(self):
        bundle = setup_documented_right()
        add_use_records_from_spec(bundle["right"]["id"], self.RECORDS)
        bundle["right"] = activate_right(bundle["right"]["id"])
        return bundle

    def test_diversion_based_study_discounts_metered_volume_for_conveyance_loss(self):
        """PRD §3.3: "Under `DIVERSION_BASED` the per-year value is that year's
        `reported_diversion_af` multiplied by a ditch efficiency of 0.65, which
        reads the metered or imaged diversion volume and discounts it for
        conveyance losses; `irrigated_acres` is ignored entirely."

        210.500, 198.250 and 205.000 discounted year by year give 136.825,
        128.863 and 133.250, whose mean is 132.979; the face-value cap of
        400.00 * 0.65 = 260.000 does not bind and three qualifying years take
        no haircut, so `transferable_cu_af` is 132.98.

        Design: Difficulty/dual_variant_calc/hcu_method_variant_divergence
        """
        bundle = self._quantified_right()

        response = create_study(bundle["right"]["id"], 2023, 2025, "DIVERSION_BASED")

        study = validate_success(response, expected_status=201)
        assert study["method"] == "DIVERSION_BASED"
        assert study["qualifying_year_count"] == 3
        assert study["average_annual_cu_af"] == pytest.approx(132.979, abs=0.0005)
        assert study["short_history_haircut_applied"] is False
        assert study["transferable_cu_af"] == pytest.approx(132.98, abs=0.01)
        assert study["status"] == "DRAFT", (
            "PRD §3.3 stores a fresh study in DRAFT — advisory only"
        )

    def test_cir_based_study_prices_irrigated_acreage_instead(self):
        """PRD §3.3: "Under `CIR_BASED` the per-year value is that year's
        `irrigated_acres` multiplied by a crop irrigation requirement of 2.10
        acre-feet per acre, which reads the requirement of the acreage actually
        farmed and ignores `reported_diversion_af` beyond having used it as an
        admissibility filter."

        100.00 acres at 2.10 acre-feet per acre is 210.000 in every one of the
        three years, so the mean is 210.000 and, the 260.000 cap not binding,
        `transferable_cu_af` is 210.00.

        Design: Difficulty/dual_variant_calc/hcu_method_variant_divergence
        """
        bundle = self._quantified_right()

        response = create_study(bundle["right"]["id"], 2023, 2025, "CIR_BASED")

        study = validate_success(response, expected_status=201)
        assert study["method"] == "CIR_BASED"
        assert study["qualifying_year_count"] == 3
        assert study["average_annual_cu_af"] == pytest.approx(210.000, abs=0.0005)
        assert study["short_history_haircut_applied"] is False
        assert study["transferable_cu_af"] == pytest.approx(210.00, abs=0.01)

    def test_both_methods_on_one_right_diverge_materially(self):
        """PRD §3.3: "For identical records the two methods return materially
        different volumes, so which method gets certified determines how much
        water the right may ever move."

        Both studies read the same three rows on the same right, yet the
        acreage reading exceeds the discounted-diversion reading by 77.02 AF.

        Design: Difficulty/dual_variant_calc/hcu_method_variant_divergence
        """
        bundle = self._quantified_right()
        right_id = bundle["right"]["id"]

        diversion = get_success_data(create_study(right_id, 2023, 2025, "DIVERSION_BASED"))
        cir = get_success_data(create_study(right_id, 2023, 2025, "CIR_BASED"))

        assert diversion["transferable_cu_af"] == pytest.approx(132.98, abs=0.01)
        assert cir["transferable_cu_af"] == pytest.approx(210.00, abs=0.01)
        assert cir["transferable_cu_af"] - diversion["transferable_cu_af"] == (
            pytest.approx(77.02, abs=0.01)
        )
        # Neither study binds anything: both are DRAFT and the right's ledger
        # has not moved.
        assert diversion["status"] == "DRAFT"
        assert cir["status"] == "DRAFT"


class TestPerYearRoundingPrecedesAveraging:
    """PRD §3.3 — "The order here is pinned and consequential: rounding each
    year first and then averaging is the specified reading, and averaging the
    raw values with a single rounding at the end yields a different final cent."
    """

    RECORDS = (
        (2023, 103.825, 90.00, "METER"),
        (2024, 121.425, 90.00, "METER"),
        (2025, 121.525, 90.00, "AERIAL_IMAGERY"),
    )

    def _study(self):
        bundle = setup_documented_right()
        add_use_records_from_spec(bundle["right"]["id"], self.RECORDS)
        activate_right(bundle["right"]["id"])
        return validate_success(
            create_study(bundle["right"]["id"], 2023, 2025, "DIVERSION_BASED"),
            expected_status=201,
        )

    def test_average_rounds_each_year_before_summing(self):
        """PRD §3.3: "First, a per-year consumptive use is computed for each
        qualifying row and each of those per-year values is rounded to 3 decimal
        places *before* anything is summed."

        The three per-year values 67.48625, 78.92625 and 78.99125 are rounded to
        67.486, 78.926 and 78.991 first; their sum 225.403 over three qualifying
        years gives `average_annual_cu_af` 75.134. Averaging the raw products
        instead would give 75.135, so the pinned order is observable here.

        Design: Difficulty/combinatorial_formula/hcu_round_per_year_then_average_order
        """
        study = self._study()

        assert study["qualifying_year_count"] == 3, (
            "one METER row, one METER row and one AERIAL_IMAGERY row all qualify"
        )
        assert study["average_annual_cu_af"] == pytest.approx(75.134, abs=0.0005)
        assert study["average_annual_cu_af"] != pytest.approx(75.135, abs=0.0001), (
            "75.135 is the averaged-then-rounded reading the PRD rejects"
        )

    def test_transferable_volume_keeps_the_rounded_average_cent(self):
        """PRD §3.3: "Fifth and last, the result is rounded once to 2 decimal
        places to give `transferable_cu_af`."

        75.134 rounds to 75.13. The face-value cap of 400.00 * 0.65 = 260.000
        does not bind and three qualifying years is not "strictly fewer than
        three", so no haircut intervenes between the average and the cent.

        Design: Difficulty/combinatorial_formula/hcu_round_per_year_then_average_order
        """
        study = self._study()

        assert study["short_history_haircut_applied"] is False
        assert study["transferable_cu_af"] == pytest.approx(75.13, abs=0.01)
        assert study["transferable_cu_af"] != pytest.approx(75.14, abs=0.001), (
            "75.14 is the wrong-order artefact"
        )


class TestQualifyingSetAndHaircutBoundaries:
    """PRD §3.3 — the admissibility filter and the strict three-year threshold.

    The right carries an affidavit year (2022), which no study may count, and two
    metered years (2024, 2025), which every study in range must count.
    """

    RECORDS = (
        (2022, 250.000, 100.00, "AFFIDAVIT"),
        (2024, 300.000, 100.00, "METER"),
        (2025, 300.000, 100.00, "METER"),
    )

    def _right(self):
        bundle = setup_documented_right()
        add_use_records_from_spec(bundle["right"]["id"], self.RECORDS)
        bundle["right"] = activate_right(bundle["right"]["id"])
        return bundle

    @pytest.mark.parametrize(
        "start_year,end_year,why",
        [
            (2019, 2020, "no beneficial-use record exists in the period at all"),
            (2022, 2022, "the only record in the period rests on an affidavit"),
        ],
    )
    def test_period_with_no_qualifying_record_is_refused(self, start_year, end_year, why):
        """PRD §3.3: "When none do, the request is rejected with
        `ERR_INSUFFICIENT_USE_HISTORY` (HTTP 422) — an empty study period is
        refused, never quantified as zero acre-feet."

        A period holding no rows and a period holding only an affidavit row are
        equally empty, because PRD §3.3 admits a row only when "its
        `verification_source` is `METER` or `AERIAL_IMAGERY`".

        Design: Difficulty/boundary_precision_check/hcu_qualifying_set_and_haircut_boundaries
        """
        bundle = self._right()

        response = create_study(bundle["right"]["id"], start_year, end_year, "DIVERSION_BASED")

        validate_error(
            response, ApiErrorId.ERR_INSUFFICIENT_USE_HISTORY.value, expected_status=422
        )

    def test_two_qualifying_years_take_the_short_history_haircut(self):
        """PRD §3.3: "Fourth, a short-history haircut applies when
        `qualifying_year_count` is strictly fewer than three years, in which case
        `short_history_haircut_applied` is set true and the carried value is
        multiplied by 0.85; the comparison is strict, so exactly three qualifying
        years takes no haircut while two years does."

        2024 and 2025 each discount to 195.000, so the average is 195.000 and the
        260.000 face-value cap does not bind; two qualifying years then take the
        haircut, giving `transferable_cu_af` 165.75.

        Design: Difficulty/boundary_precision_check/hcu_qualifying_set_and_haircut_boundaries
        """
        bundle = self._right()

        response = create_study(bundle["right"]["id"], 2024, 2025, "DIVERSION_BASED")

        study = validate_success(response, expected_status=201)
        assert study["qualifying_year_count"] == 2
        assert study["average_annual_cu_af"] == pytest.approx(195.000, abs=0.0005)
        assert study["short_history_haircut_applied"] is True
        assert study["transferable_cu_af"] == pytest.approx(165.75, abs=0.01)

    def test_exactly_three_qualifying_years_take_no_haircut(self):
        """PRD §3.3: "the comparison is strict, so exactly three qualifying years
        takes no haircut while two years does."

        Adding a metered 2023 row and widening the period to 2023-2025 moves
        `qualifying_year_count` from two to exactly three. The average is
        unchanged at 195.000, so the whole 29.25 AF difference in
        `transferable_cu_af` is attributable to the haircut lifting.

        Design: Difficulty/boundary_precision_check/hcu_qualifying_set_and_haircut_boundaries
        """
        bundle = self._right()
        add_use_records_from_spec(
            bundle["right"]["id"], ((2023, 300.000, 100.00, "METER"),)
        )

        response = create_study(bundle["right"]["id"], 2023, 2025, "DIVERSION_BASED")

        study = validate_success(response, expected_status=201)
        assert study["qualifying_year_count"] == 3
        assert study["average_annual_cu_af"] == pytest.approx(195.000, abs=0.0005)
        assert study["short_history_haircut_applied"] is False
        assert study["transferable_cu_af"] == pytest.approx(195.00, abs=0.01)
