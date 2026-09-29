"""The abandonment score's components and bands, and the two 0.65 constants.

PRD §3.2: "The score itself is a weighted sum of four terms less one credit."

PRD §3.3: "The admissible record set is narrower than the forfeiture window."
"""
import pytest
from test_helpers import api_client, get_success_data
from test_helpers.fixtures import (
    ANALYST,
    add_use_record,
    add_use_records_from_spec,
    create_claimant,
    create_study,
    create_water_right,
    read_right,
    set_clock,
    setup_base_right,
    setup_certified_right,
)

CLOCK = "2026-03-01T00:00:00Z"


def _assessment(right_id):
    return get_success_data(api_client.get_forfeiture_assessment(right_id, ANALYST))


def _metered_right(claimant_id, right_number, use_years):
    """A 400.00 AF right carrying one 300.000 AF metered record per listed year."""
    right = create_water_right(claimant_id, right_number=right_number)
    add_use_records_from_spec(
        right["id"], [(year, 300.000, 100.00, "METER") for year in use_years]
    )
    return right


class TestOneBeneficialUseYearDecidesTheBand:
    """PRD §3.2 — "`consecutive_nonuse_years` is the length of the longest
    unbroken run of non-use years inside the window."

    Two rights are identical in every respect except that the first reports
    beneficial use from 2020 and the second only from 2021. That single year
    lengthens the leading non-use run from four years to five, which is worth nine
    points, and nine points is exactly what separates 33.50 from 42.50 — one on
    each side of the `ELEVATED` floor.
    """

    def _two_rights(self):
        set_clock(CLOCK)
        claimant = create_claimant(
            "Vega Ditch Company",
            contact_email="ops@vega.example",
            entity_type="IRRIGATION_DISTRICT",
        )
        return {
            "claimant": claimant,
            "six_year_record": _metered_right(
                claimant["id"], "WR-2198-001", range(2020, 2026)
            ),
            "five_year_record": _metered_right(
                claimant["id"], "WR-2198-002", range(2021, 2026)
            ),
        }

    def test_four_consecutive_nonuse_years_score_low_and_are_not_eligible(self):
        """PRD §3.2: "The raw score is then: nine points for each consecutive
        non-use year, plus twenty-five points multiplied by the unverified ratio,
        plus thirty points multiplied by one minus utilization, plus a flat
        twelve-point penalty when the right's `status` is currently `SUSPENDED`,
        less a flat ten-point credit when any record in the window carries a
        `verification_source` of `METER`."

        With the clock in 2026 the window is the closed band 2016 through 2025.
        Six metered years at 300.000 AF against an authorized 400.00 AF give a
        0.7500 utilization, so the four unrecorded years 2016-2019 carry 36 points,
        underuse carries 7.50 and the meter credit takes 10 back: 33.50, `LOW`.
        PRD §3.2: "Statutory forfeiture eligibility is that boolean, and it is
        inclusive: exactly five consecutive non-use years is eligible, four is not."

        Design: Corner/calculations/calc_forfeiture_risk_score_weighted_components_and_bands
        """
        rights = self._two_rights()

        assessment = _assessment(rights["six_year_record"]["id"])

        assert assessment["lookback_start_year"] == 2016
        assert assessment["lookback_end_year"] == 2025
        assert assessment["nonuse_year_count"] == 4
        assert assessment["consecutive_nonuse_years"] == 4
        assert assessment["nonuse_component"] == pytest.approx(36, abs=0.01)
        assert assessment["unverified_component"] == pytest.approx(0.00, abs=0.01)
        assert assessment["underuse_component"] == pytest.approx(7.50, abs=0.01)
        assert assessment["suspended_penalty"] == pytest.approx(0, abs=0.01)
        assert assessment["meter_credit"] == pytest.approx(10, abs=0.01)
        assert assessment["forfeiture_risk_score"] == pytest.approx(33.50, abs=0.01)
        assert assessment["forfeiture_risk_band"] == "LOW"
        assert assessment["forfeiture_eligible"] is False

    def test_the_fifth_nonuse_year_is_worth_nine_points_and_crosses_into_elevated(self):
        """PRD §3.2: "Bands are inclusive at the bottom: a score of 70.00 or above
        reads `HIGH`, a score from 40.00 up to but not including 70.00 reads
        `ELEVATED`, and anything below reads `LOW`."

        The right missing its 2020 record has the same 0.7500 utilization, the same
        clean verification record and the same meter credit; only the run length
        differs. PRD §3.2: "Every other year in the window is a non-use year, and
        that emphatically includes years for which no record exists at all."

        Design: Corner/calculations/calc_forfeiture_risk_score_weighted_components_and_bands
        """
        rights = self._two_rights()

        assessment = _assessment(rights["five_year_record"]["id"])

        assert assessment["consecutive_nonuse_years"] == 5
        assert assessment["nonuse_component"] == pytest.approx(45, abs=0.01)
        assert assessment["unverified_component"] == pytest.approx(0.00, abs=0.01)
        assert assessment["underuse_component"] == pytest.approx(7.50, abs=0.01)
        assert assessment["meter_credit"] == pytest.approx(10, abs=0.01)
        assert assessment["forfeiture_risk_score"] == pytest.approx(42.50, abs=0.01)
        assert assessment["forfeiture_risk_band"] == "ELEVATED"
        assert assessment["forfeiture_eligible"] is True
        stored = read_right(rights["five_year_record"]["id"])
        assert stored["forfeiture_risk_score"] == pytest.approx(42.50, abs=0.01)
        assert stored["forfeiture_risk_band"] == "ELEVATED"
        assert stored["consecutive_nonuse_years"] == 5

    def test_a_record_for_the_current_calendar_year_is_inert(self):
        """PRD §3.2: "The scoring window is a closed ten-year band ending with the
        year *before* the calendar year of the logical clock, taken in UTC; the
        current calendar year is deliberately excluded because its reporting year
        is not yet complete."

        Appending a 2026 record re-runs the assessment — PRD §3.2: "Abandonment
        risk is scored on demand and after every event that could move it —
        appending a beneficial-use record, perfecting a right, reinstating a right,
        and any movement of the right into or out of `SUSPENDED`" — and the re-run
        must land on the same figures, because 2026 sits outside 2016-2025.

        Design: Corner/calculations/calc_forfeiture_risk_score_weighted_components_and_bands
        """
        rights = self._two_rights()
        before = _assessment(rights["six_year_record"]["id"])

        add_use_record(
            rights["six_year_record"]["id"],
            2026,
            reported_diversion_af=300.000,
            irrigated_acres=100.00,
            verification_source="METER",
        )

        after = _assessment(rights["six_year_record"]["id"])
        breakdown = (
            "lookback_start_year",
            "lookback_end_year",
            "nonuse_year_count",
            "consecutive_nonuse_years",
            "unverified_component",
            "underuse_component",
            "nonuse_component",
            "suspended_penalty",
            "meter_credit",
            "forfeiture_risk_score",
            "forfeiture_risk_band",
            "forfeiture_eligible",
        )
        for field in breakdown:
            assert after[field] == before[field], f"{field} moved with a 2026 record"
        assert after["lookback_end_year"] == 2025
        assert after["consecutive_nonuse_years"] == 4
        assert after["forfeiture_risk_score"] == pytest.approx(33.50, abs=0.01)
        assert after["forfeiture_risk_band"] == "LOW"


class TestTheFourVerificationSourcesPartitionThreeWays:
    """PRD §3.2 — the same four-value enum is read by two different rules at once.

    Two rights each carry four records at 300.000 AF for 2022 through 2025, one of
    them on an affidavit and one on no evidence at all. The first right's remaining
    two years are metered; the second's are aerial imagery. The unverified ratio
    cannot tell them apart, and the meter credit cannot confuse them.
    """

    LATE_YEARS = ((2024, "AFFIDAVIT"), (2025, "NONE"))

    def _two_rights(self):
        set_clock(CLOCK)
        claimant = create_claimant(
            "Vega Ditch Company",
            contact_email="ops@vega.example",
            entity_type="IRRIGATION_DISTRICT",
        )
        rights = {}
        for key, number, early_source in (
            ("metered", "WR-2198-003", "METER"),
            ("imaged", "WR-2198-004", "AERIAL_IMAGERY"),
        ):
            right = create_water_right(claimant["id"], right_number=number)
            spec = [(2022, 300.000, 100.00, early_source), (2023, 300.000, 100.00, early_source)]
            spec += [(year, 300.000, 100.00, source) for year, source in self.LATE_YEARS]
            add_use_records_from_spec(right["id"], spec)
            rights[key] = right
        return rights

    def test_affidavit_and_no_evidence_drive_the_ratio_while_a_meter_earns_credit(self):
        """PRD §3.2: "The unverified ratio is the proportion of those records whose
        `verification_source` is `AFFIDAVIT` or `NONE`, rounded to 4 decimal
        places."

        Two of the four in-window records are unverified, so the 0.5000 ratio is
        worth 12.50 points, while the two metered years still earn the whole credit.
        PRD §3.2: "the `unverified_component` (the unverified ratio multiplied by
        twenty-five, at 2 decimal places)". Six leading non-use years carry 54, and
        54 + 12.50 + 7.50 - 10 is 64.00.

        Design: Corner/calculations/calc_forfeiture_unverified_ratio_counts_affidavits_not_aerial_imagery
        """
        rights = self._two_rights()

        assessment = _assessment(rights["metered"]["id"])

        assert assessment["unverified_component"] == pytest.approx(12.50, abs=0.01)
        assert assessment["underuse_component"] == pytest.approx(7.50, abs=0.01)
        assert assessment["nonuse_component"] == pytest.approx(54, abs=0.01)
        assert assessment["meter_credit"] == pytest.approx(10, abs=0.01)
        assert assessment["forfeiture_risk_score"] == pytest.approx(64.00, abs=0.01)
        assert assessment["forfeiture_risk_band"] == "ELEVATED"
        assert assessment["forfeiture_eligible"] is True

    def test_aerial_imagery_is_verified_but_uncredited(self):
        """PRD §3.2: "less a flat ten-point credit when any record in the window
        carries a `verification_source` of `METER`."

        Imagery is good enough to keep a record out of the unverified numerator —
        the component is the same 12.50 as on the metered right — but it earns no
        credit, and losing those ten points is what carries the score from
        `ELEVATED` to `HIGH`: "a score of 70.00 or above reads `HIGH`".

        Design: Corner/calculations/calc_forfeiture_unverified_ratio_counts_affidavits_not_aerial_imagery
        """
        rights = self._two_rights()

        assessment = _assessment(rights["imaged"]["id"])

        assert assessment["unverified_component"] == pytest.approx(12.50, abs=0.01)
        assert assessment["underuse_component"] == pytest.approx(7.50, abs=0.01)
        assert assessment["nonuse_component"] == pytest.approx(54, abs=0.01)
        assert assessment["meter_credit"] == pytest.approx(0, abs=0.01)
        assert assessment["forfeiture_risk_score"] == pytest.approx(74.00, abs=0.01)
        assert assessment["forfeiture_risk_band"] == "HIGH"

    def test_an_unverified_record_still_marks_the_year_as_used(self):
        """PRD §3.2: "Within that window, a year counts as a used year when a record
        exists for it whose `reported_diversion_af` is at least 0.50 acre-feet."

        The used-year test reads the volume and nothing else, so the 2025 record
        resting on no evidence at all still stops the non-use run at 2021 on both
        rights. Were unverified rows excluded from the use test as they are from the
        study window, the run would reach 2023 and the score would be far higher.

        Design: Corner/calculations/calc_forfeiture_unverified_ratio_counts_affidavits_not_aerial_imagery
        """
        rights = self._two_rights()

        metered = _assessment(rights["metered"]["id"])
        imaged = _assessment(rights["imaged"]["id"])

        for assessment in (metered, imaged):
            assert assessment["lookback_start_year"] == 2016
            assert assessment["lookback_end_year"] == 2025
            assert assessment["consecutive_nonuse_years"] == 6
            assert assessment["nonuse_year_count"] == 6


class TestTheTwoPointSixFiveConstantsReadDifferentBases:
    """PRD §3.3 — two constants of equal magnitude, multiplied into different figures.

    A right authorized at 400.00 AF has been metering 700.000 AF a year through
    2023, 2024 and 2025. The ditch efficiency reads the 700.000 and the face-value
    cap reads the 400.00, so the two legs of the calculation land 195 acre-feet
    apart and the cap is what binds.
    """

    OVER_DIVERSION = 700.000

    def test_the_efficiency_leg_reads_reported_diversion_and_the_cap_clamps_it(self):
        """PRD §3.3: "Under `DIVERSION_BASED` the per-year value is that year's
        `reported_diversion_af` multiplied by a ditch efficiency of 0.65, which
        reads the metered or imaged diversion volume and discounts it for conveyance
        losses; `irrigated_acres` is ignored entirely."

        Each of the three metered years yields 455.000 acre-feet, so
        `average_annual_cu_af` is 455.000 — and then PRD §3.3: "Third, a face-value
        cap is computed as the right's `authorized_diversion_af` multiplied by 0.65,
        rounded to 3 decimal places, and the smaller of the average and that cap is
        carried forward." That cap is 260.000, computed from the authorized figure
        and not from the reported one, so `transferable_cu_af` is 260.00 rather than
        455.00. Three qualifying years take no haircut: "the comparison is strict, so
        exactly three qualifying years takes no haircut while two years does."

        Design: Corner/calculations/calc_hcu_constants_efficiency_and_face_value_cap_use_different_bases
        """
        bundle = setup_base_right(
            clock=CLOCK,
            use_years=(2023, 2024, 2025),
            reported_diversion_af=self.OVER_DIVERSION,
        )

        study = get_success_data(
            create_study(bundle["right"]["id"], 2023, 2025, "DIVERSION_BASED")
        )

        assert study["qualifying_year_count"] == 3
        assert study["short_history_haircut_applied"] is False
        assert study["average_annual_cu_af"] == pytest.approx(455.000, abs=0.0005)
        assert study["transferable_cu_af"] == pytest.approx(260.00, abs=0.01)
        assert study["status"] == "DRAFT"

    def test_the_capped_volume_is_what_certification_moves_onto_the_right(self):
        """PRD §3.3: "The right's `certified_hcu_af` is overwritten with the newly
        certified study's `transferable_cu_af`, `transferable_af` is recomputed as
        certified volume less encumbered less transferred-away so that the conserved
        identity of §2.9 still holds".

        The capped 260.00 is the figure that becomes transferable, so over-diverting
        buys the right nothing at all: 260.00 == 260.00 + 0.00 + 0.00.

        Design: Corner/calculations/calc_hcu_constants_efficiency_and_face_value_cap_use_different_bases
        """
        bundle = setup_certified_right(
            clock=CLOCK,
            method="DIVERSION_BASED",
            study_start_year=2023,
            study_end_year=2025,
            use_years=(2023, 2024, 2025),
            reported_diversion_af=self.OVER_DIVERSION,
        )

        study = bundle["study"]
        right = bundle["right"]
        assert study["status"] == "CERTIFIED"
        assert study["transferable_cu_af"] == pytest.approx(260.00, abs=0.01)
        assert right["certified_hcu_af"] == pytest.approx(260.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(260.00, abs=0.01)
