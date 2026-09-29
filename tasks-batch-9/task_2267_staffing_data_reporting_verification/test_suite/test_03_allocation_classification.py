"""Per-line rounding of a split-role allocation set."""

from test_helpers import (
    allocation_line,
    approx_hours,
    assert_hour_entry,
    create_hour_entry_payload,
    validate_success,
)


def _split_allocations(universe):
    return [
        allocation_line(universe.jc_rn["id"], 45.00),
        allocation_line(universe.jc_split["id"], 27.50),
        allocation_line(universe.jc_admin["id"], 27.50),
    ]


class TestAllocationRoundingPerLine:
    def test_01_direct_care_hours_round_each_line_before_summing(
        self, api, draft_submission
    ):
        """PRD: "compute that line's direct-care contribution as `raw_hours`
        multiplied by the line's `percent` divided by 100, multiplied by the
        credit fraction, then rounded half up to 2 decimal places.
        `direct_care_hours` is the sum of those already-rounded per-line
        values." PRD: "A 7.50-hour shift split 45.00 / 27.50 / 27.50 across
        categories crediting 1.00, 0.60, and 0.00 yields 4.62 under the pinned
        per-line rounding and 4.61 under a single final rounding, and 4.62 is the
        required result."

        Design: Difficulty/combinatorial_formula/allocation_rounding_per_line_before_sum
        """
        scenario = draft_submission
        universe = scenario.universe
        data = validate_success(
            api.create_hour_entry(
                create_hour_entry_payload(
                    scenario.id,
                    universe.w_rn["id"],
                    universe.jc_rn["id"],
                    scenario.version,
                    work_date="2026-04-01",
                    shift_start="07:00",
                    shift_end="14:30",
                    allocations=_split_allocations(universe),
                ),
                universe.coord_headers,
            ),
            expected_status=201,
        )

        assert_hour_entry(data)
        assert data["raw_hours"] == approx_hours(7.50)
        assert data["direct_care_hours"] == approx_hours(4.62)
        assert float(data["direct_care_hours"]) != approx_hours(4.61)

    def test_02_excluded_and_nurse_group_subtotals_follow_the_same_line_values(
        self, api, draft_submission
    ):
        """PRD: "`rn_hours` is the sum of the line contributions whose category
        has `nurse_group` `RN`, `lpn_hours` the sum for `LPN`, and `na_hours` the
        sum for `NA`." PRD: "`excluded_hours` is `raw_hours` less
        `direct_care_hours`, rounded half up to 2 decimal places". Both the
        full-credit RN line and the 0.60-credit split line carry `nurse_group`
        `RN`, so all 4.62 credited hours are RN hours and 2.88 hours are excluded.

        Design: Difficulty/combinatorial_formula/allocation_rounding_per_line_before_sum
        """
        scenario = draft_submission
        universe = scenario.universe
        data = validate_success(
            api.create_hour_entry(
                create_hour_entry_payload(
                    scenario.id,
                    universe.w_rn["id"],
                    universe.jc_rn["id"],
                    scenario.version,
                    work_date="2026-04-01",
                    shift_start="07:00",
                    shift_end="14:30",
                    allocations=_split_allocations(universe),
                ),
                universe.coord_headers,
            ),
            expected_status=201,
        )

        assert data["excluded_hours"] == approx_hours(2.88)
        assert data["rn_hours"] == approx_hours(4.62)
        assert data["lpn_hours"] == approx_hours(0.00)
        assert data["na_hours"] == approx_hours(0.00)

    def test_03_the_submission_rollup_carries_the_rounded_line_sums(
        self, api, draft_submission
    ):
        """PRD: "From the hour population, `total_raw_hours` is the sum of
        `raw_hours`, `total_direct_care_hours` the sum of `direct_care_hours`,
        `total_excluded_hours` the sum of `excluded_hours`, and
        `total_rn_direct_care_hours` the sum of `rn_hours`, each rounded half up
        to 2 decimal places."

        Design: Difficulty/combinatorial_formula/allocation_rounding_per_line_before_sum
        """
        scenario = draft_submission
        universe = scenario.universe
        validate_success(
            api.create_hour_entry(
                create_hour_entry_payload(
                    scenario.id,
                    universe.w_rn["id"],
                    universe.jc_rn["id"],
                    scenario.version,
                    work_date="2026-04-01",
                    shift_start="07:00",
                    shift_end="14:30",
                    allocations=_split_allocations(universe),
                ),
                universe.coord_headers,
            ),
            expected_status=201,
        )

        submission = scenario.refresh()
        assert submission["total_raw_hours"] == approx_hours(7.50)
        assert submission["total_direct_care_hours"] == approx_hours(4.62)
        assert submission["total_excluded_hours"] == approx_hours(2.88)
        assert submission["total_rn_direct_care_hours"] == approx_hours(4.62)
