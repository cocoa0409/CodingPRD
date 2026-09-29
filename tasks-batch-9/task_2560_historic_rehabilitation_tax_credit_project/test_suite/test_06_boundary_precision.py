"""Boundaries where one cent or one day changes the answer.

The substantial rehabilitation test is inclusive on its threshold, so equality
passes and one cent above fails. The measuring period is half-open, so its first
day counts and its last day does not.
"""

from test_helpers import (
    ApiErrorId,
    assertions,
    fixtures,
    get_success_data,
    validate_error,
    validate_success,
)


def test_substantial_test_passes_on_equality_and_fails_one_cent_above(api):
    """Equality is MET; a threshold one cent higher is NOT_MET.

    Two in-period qualified costs total 210000000 against an adjusted basis of
    250000000, so the project starts NOT_MET. Revising the basis down to exactly
    210000000 makes the threshold equal to the qualified total, and the inclusive
    comparison reads MET. Revising it to 210000001, one cent above the qualified
    total, reads NOT_MET.

    PRD: "The threshold, held in `substantial_test_threshold_cents`, is the greater of the project's `adjusted_basis_cents` and a statutory floor of five thousand dollars expressed in cents."
    PRD: "`substantial_test_status` reads `MET` when `qre_total_final_cents` is greater than or equal to that threshold and `NOT_MET` otherwise; the comparison is inclusive, so an amount landing exactly on the threshold is `MET`."
    PRD: "A basis-and-period revision by the owning `Developer` may change `adjusted_basis_cents`, `measuring_period_start_date`, `measuring_period_months`, or any combination of them, and must carry `expected_project_version` as described in §2.8."

    Design: Difficulty/boundary_precision_check/substantial_test_met_at_exact_threshold_then_not_met_one_cent_above
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api,
        cast,
        structure_type="SINGLE_TIER",
        adjusted_basis_cents=250_000_000,
        measuring_period_months=24,
        measuring_period_start_date="2026-09-01",
    )
    fixtures.add_qre_cost(
        api, cast, project["id"], 200_000_000, incurred_date="2027-01-15"
    )
    fixtures.add_qre_cost(
        api,
        cast,
        project["id"],
        10_000_000,
        category="ARCHITECTURAL_ENGINEERING",
        incurred_date="2027-02-10",
    )
    before = fixtures.read_project(api, cast, project["id"])
    assertions.assert_ledger(
        before, qre_total_final_cents=210_000_000, substantial_test_status="NOT_MET"
    )

    at_threshold = validate_success(
        api.patch_project(
            project["id"],
            cast.developer_headers,
            expected_project_version=before["version"],
            adjusted_basis_cents=210_000_000,
        )
    )
    one_cent_above = validate_success(
        api.patch_project(
            project["id"],
            cast.developer_headers,
            expected_project_version=at_threshold["version"],
            adjusted_basis_cents=210_000_001,
        )
    )

    assertions.assert_ledger(
        at_threshold,
        substantial_test_threshold_cents=210_000_000,
        substantial_test_status="MET",
    )
    assertions.assert_ledger(
        one_cent_above,
        substantial_test_threshold_cents=210_000_001,
        substantial_test_status="NOT_MET",
    )


def test_the_credit_schedule_follows_the_test_across_the_one_cent_boundary(api):
    """The schedule appears at equality and vanishes one cent above it.

    At the exact threshold the schedule runs: four percent of 210000000 is 8400000
    a year and five of those is 42000000. One cent above the threshold the test
    fails, and both schedule fields are driven back to zero rather than left at
    their previous values.

    PRD: "Otherwise `annual_credit_cents` is four percent of `qre_total_final_cents`, rounded half up to a whole cent, and `total_claimable_credit_cents` is that **already-rounded** per-year amount multiplied by five, the number of ratable years."
    PRD: "When `substantial_test_status` is `NOT_MET`, both `annual_credit_cents` and `total_claimable_credit_cents` are zero."
    PRD: "When a revision moves the window, the consequences ripple in a fixed order: `measuring_period_end_date` is recomputed, then every cost line item of the project has its `in_measuring_period` flag re-evaluated against the new half-open window, then the qualified/non-qualified segregation is recomputed, then the substantial rehabilitation test, and only then the ratable credit schedule."

    Design: Difficulty/boundary_precision_check/substantial_test_met_at_exact_threshold_then_not_met_one_cent_above
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api,
        cast,
        structure_type="SINGLE_TIER",
        adjusted_basis_cents=250_000_000,
        measuring_period_months=24,
        measuring_period_start_date="2026-09-01",
    )
    fixtures.add_qre_cost(
        api, cast, project["id"], 200_000_000, incurred_date="2027-01-15"
    )
    fixtures.add_qre_cost(
        api,
        cast,
        project["id"],
        10_000_000,
        category="ARCHITECTURAL_ENGINEERING",
        incurred_date="2027-02-10",
    )
    version = fixtures.project_version(api, cast, project["id"])

    at_threshold = validate_success(
        api.patch_project(
            project["id"],
            cast.developer_headers,
            expected_project_version=version,
            adjusted_basis_cents=210_000_000,
        )
    )
    assertions.assert_ratable_schedule(at_threshold, 8_400_000)
    assertions.assert_ledger(
        at_threshold, annual_credit_cents=8_400_000, total_claimable_credit_cents=42_000_000
    )

    one_cent_above = validate_success(
        api.patch_project(
            project["id"],
            cast.developer_headers,
            expected_project_version=at_threshold["version"],
            adjusted_basis_cents=210_000_001,
        )
    )

    assertions.assert_ledger(
        one_cent_above,
        annual_credit_cents=0,
        total_claimable_credit_cents=0,
        credit_unclaimed_cents=0,
    )


def test_a_cost_incurred_on_the_period_end_date_cannot_be_qualified(api):
    """The end date is outside the window, so qualifying such a cost is refused.

    A 24-month window opened on 2026-09-01 has an end date of 2028-09-01, which is
    the exclusive upper bound. A cost incurred exactly on 2028-09-01 and submitted
    as qualified is refused as outside the measuring period, while the same cost one
    day earlier, on 2028-08-31, is accepted and flagged in period.

    PRD: "It runs from `measuring_period_start_date` inclusive to `measuring_period_end_date` exclusive."
    PRD: "A cost incurred exactly on the start date is inside the period; a cost incurred exactly on the end date is outside it."
    PRD: "From these the server derives `measuring_period_end_date` as the start date advanced by that many calendar months on the same day of month, and this derived date is the exclusive upper bound of the window."

    Design: Difficulty/boundary_precision_check/cost_incurred_on_measuring_period_end_date_excluded_by_half_open_window
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api,
        cast,
        structure_type="SINGLE_TIER",
        adjusted_basis_cents=60_000_000,
        measuring_period_months=24,
        measuring_period_start_date="2026-09-01",
    )
    assertions.assert_fields(
        project, "project window", measuring_period_end_date="2028-09-01"
    )
    fixtures.set_clock(api, "2028-10-01T00:00:00Z")

    on_end_date = api.create_cost_line_item(
        cast.developer_headers,
        project_id=project["id"],
        vendor_name="Keystone Masonry",
        category="HARD_CONSTRUCTION",
        amount_cents=5_000_000,
        incurred_date="2028-09-01",
        classification="QRE",
    )
    day_before = validate_success(
        api.create_cost_line_item(
            cast.developer_headers,
            project_id=project["id"],
            vendor_name="Keystone Masonry",
            category="HARD_CONSTRUCTION",
            amount_cents=5_000_000,
            incurred_date="2028-08-31",
            classification="QRE",
        ),
        201,
    )

    validate_error(on_end_date, ApiErrorId.OUTSIDE_MEASURING_PERIOD.value, 422)
    assertions.assert_fields(
        day_before,
        "cost on the day before the end date",
        in_measuring_period=True,
        classification="QRE",
    )


def test_a_cost_incurred_on_the_period_start_date_counts_toward_the_total(api):
    """The start date is inside the window, and only in-period costs are counted.

    A cost incurred exactly on 2026-09-01, the inclusive first day of the window, is
    in period. Together with the 5000000 incurred on 2028-08-31 the qualified total
    is 8000000; the 5000000 dated on the exclusive end date never entered the
    ledger at all, so it appears in neither the qualified nor the classified total.

    PRD: "The server also derives `in_measuring_period`, which is true exactly when the `incurred_date` falls on or after the project's `measuring_period_start_date` and strictly before its `measuring_period_end_date`, and initialises `exclusion_reason` to `NONE` and `reclassification_count` to zero."
    PRD: "Only items whose `in_measuring_period` is true participate at all."

    Design: Difficulty/boundary_precision_check/cost_incurred_on_measuring_period_end_date_excluded_by_half_open_window
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api,
        cast,
        structure_type="SINGLE_TIER",
        adjusted_basis_cents=60_000_000,
        measuring_period_months=24,
        measuring_period_start_date="2026-09-01",
    )
    fixtures.set_clock(api, "2028-10-01T00:00:00Z")
    validate_error(
        api.create_cost_line_item(
            cast.developer_headers,
            project_id=project["id"],
            vendor_name="Keystone Masonry",
            category="HARD_CONSTRUCTION",
            amount_cents=5_000_000,
            incurred_date="2028-09-01",
            classification="QRE",
        ),
        ApiErrorId.OUTSIDE_MEASURING_PERIOD.value,
        422,
    )
    fixtures.add_qre_cost(
        api, cast, project["id"], 5_000_000, incurred_date="2028-08-31"
    )

    on_start_date = fixtures.add_qre_cost(
        api, cast, project["id"], 3_000_000, incurred_date="2026-09-01"
    )

    assertions.assert_fields(
        on_start_date,
        "cost on the inclusive start date",
        in_measuring_period=True,
        classification="QRE",
    )
    stored = fixtures.read_project(api, cast, project["id"])
    assertions.assert_ledger(
        stored,
        qre_total_final_cents=8_000_000,
        classified_cost_total_cents=8_000_000,
        nonqualified_total_cents=0,
    )
    items, _ = assertions.assert_page(
        api.list_project_cost_line_items(project["id"], cast.developer_headers),
        total_count=2,
    )
    assert get_success_data(
        api.get_cost_line_item(items[0]["id"], cast.developer_headers)
    )["in_measuring_period"] is True, "only in-period items were recorded"
