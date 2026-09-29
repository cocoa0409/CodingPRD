"""Overhead branch selection, per-bucket residuals and reallocation weighting."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures


def test_overhead_clamps_down_lands_inside_the_band_and_clamps_up(api):
    """Three statements on one well take the cap, the open band and the floor in turn.

    Under the `FIXED_RATE` mode the rate is per month and depends on the activity class: a `DRILLING` statement is charged $9,500 per billable month and a `PRODUCING` statement $950 per billable month — that is, 950000 cents per month for drilling activity and 95000 cents per month for producing activity.
    Where a computed amount is subject to a floor or a cap, the raw amount is rounded to whole cents first and the floor and the cap are applied to the rounded value.

    Design: Difficulty/combinatorial_formula/overhead_branch_selection_with_cap_and_floor_clamps
    """
    context = fixtures.setup_pooled_producing_well(
        api, clock="2026-08-05T00:00:00Z", produce=False
    )
    well_id = context["well_id"]

    fixtures.book_cost(
        api, well_id, "DRILLING", "CAPITAL", 1_000_000, "2026-05-10", "2026-05-12"
    )
    fixtures.book_cost(
        api, well_id, "LEASE_OPERATING", "OPERATING", 200_000, "2026-07-10", "2026-07-12"
    )
    fixtures.book_cost(
        api, well_id, "COMPLETION", "CAPITAL", 100_000, "2026-03-15", "2026-03-20"
    )

    drilling_draft = fixtures.open_statement(
        api,
        well_id,
        statement_number="JIB-A",
        billing_period_start="2026-05-01",
        billing_period_end="2026-06-30",
        activity_class="DRILLING",
        overhead_rate_class="FIXED_RATE",
    )
    drilling = validate_success(
        api.issue_jib_statement(drilling_draft["id"], fixtures.JIB_ACCOUNTANT), 200
    )
    # 950000 * 2 * 1.042 = 1979800 raw, clamped down to the 1500000 cap.
    assert drilling["billable_months"] == 2
    assert drilling["overhead_cents"] == 1_500_000
    assert drilling["direct_cost_cents"] == 1_000_000
    assert drilling["total_billed_cents"] == 2_500_000

    fixtures.change_status(api, well_id, "PRODUCING", "2026-07-01")

    producing_draft = fixtures.open_statement(
        api,
        well_id,
        statement_number="JIB-B",
        billing_period_start="2026-07-01",
        billing_period_end="2026-07-31",
        activity_class="PRODUCING",
        overhead_rate_class="FIXED_RATE",
    )
    producing = validate_success(
        api.issue_jib_statement(producing_draft["id"], fixtures.JIB_ACCOUNTANT), 200
    )
    # 95000 * 1 * 1.042 = 98990 exactly, strictly inside the band.
    assert producing["billable_months"] == 1
    assert producing["overhead_cents"] == 98_990
    assert producing["total_billed_cents"] == 298_990

    percentage_draft = fixtures.open_statement(
        api,
        well_id,
        statement_number="JIB-C",
        billing_period_start="2026-03-01",
        billing_period_end="2026-03-31",
        activity_class="PRODUCING",
        overhead_rate_class="PERCENTAGE_BASIS",
    )
    percentage = validate_success(
        api.issue_jib_statement(percentage_draft["id"], fixtures.JIB_ACCOUNTANT), 200
    )
    # 5% of 100000 is 5000 raw, clamped up to the 25000 floor.
    assert percentage["billable_months"] == 1
    assert percentage["overhead_cents"] == 25_000
    assert percentage["total_billed_cents"] == 125_000

    well = validate_success(api.get_well(well_id, fixtures.LAND_ADMIN), 200)
    assert well["billed_to_date_cents"] == 2_923_990


def test_each_bucket_closes_with_its_own_signed_residual_in_a_fixed_order(api):
    """Odd pools push a negative residual onto the largest holder in both money buckets.

    For each bucket in turn, every owner's raw share for that bucket is rounded half up to whole cents on its own; the signed residual is the bucket total less the sum of those rounded amounts; and the whole residual is added to one target owner's amount for that bucket and also accumulated into that owner's `rounding_residual_cents`.
    Rounding each owner's share per bucket and then summing is mandatory.

    Design: Difficulty/combinatorial_formula/owner_share_rounding_signed_residual_per_bucket_in_fixed_order
    """
    context = fixtures.setup_residual_statement(api, clock="2026-08-10T00:00:00Z")
    statement_id = context["statement_id"]

    issued = validate_success(
        api.issue_jib_statement(statement_id, fixtures.JIB_ACCOUNTANT), 200
    )
    assert issued["overhead_cents"] == 53_000
    assert issued["total_billed_cents"] == 1_153_008

    operator = fixtures.line_item_for(api, statement_id, context["operator_id"])
    assert operator["direct_capital_cents"] == 500_002
    assert operator["direct_operating_cents"] == 50_001
    assert operator["overhead_cents"] == 26_500
    assert operator["rounding_residual_cents"] == -2
    assert operator["total_billed_cents"] == 576_503

    partner_a = fixtures.line_item_for(api, statement_id, context["partner_a_id"])
    assert partner_a["direct_capital_cents"] == 300_002
    assert partner_a["direct_operating_cents"] == 30_001
    assert partner_a["overhead_cents"] == 15_900
    assert partner_a["rounding_residual_cents"] == 0
    assert partner_a["total_billed_cents"] == 345_903

    partner_b = fixtures.line_item_for(api, statement_id, context["partner_b_id"])
    assert partner_b["direct_capital_cents"] == 200_001
    assert partner_b["direct_operating_cents"] == 20_001
    assert partner_b["overhead_cents"] == 10_600
    assert partner_b["total_billed_cents"] == 230_602


def test_overhead_is_fixed_from_gross_pools_then_shared_on_post_reallocation_weights(api):
    """The operator absorbs 78,964 cents of overhead, not the 67,000 a pre-reallocation split gives.

    The statement's `overhead_cents` was already fixed from the gross pools and is never recomputed here.
    Each owner's raw overhead share is `overhead_cents` multiplied by the sum of that owner's raw capital and raw operating shares, divided by the statement's `direct_cost_cents`.

    Design: Difficulty/combinatorial_formula/non_consent_reallocation_pinned_dependency_cut
    """
    context = fixtures.setup_non_consent_statement(api, clock="2026-08-10T00:00:00Z")
    statement_id = context["statement_id"]

    afe = validate_success(api.get_afe(context["afe_id"], fixtures.LAND_ADMIN), 200)
    assert afe["afe_status"] == "PARTIALLY_CONSENTED"
    assert afe["consent_working_interest_pct"] == 0.800000

    issued = validate_success(
        api.issue_jib_statement(statement_id, fixtures.JIB_ACCOUNTANT), 200
    )
    assert issued["overhead_cents"] == 134_000
    assert issued["total_billed_cents"] == 2_934_000

    operator = fixtures.line_item_for(api, statement_id, context["operator_id"])
    assert operator["consent_normalized_wi_pct"] == 0.625000
    assert operator["direct_capital_cents"] == 1_500_000
    assert operator["direct_operating_cents"] == 150_000
    assert operator["overhead_cents"] == 78_964
    assert operator["non_consent_reallocated_cents"] == 250_000
    assert operator["total_billed_cents"] == 1_728_964

    partner_a = fixtures.line_item_for(api, statement_id, context["partner_a_id"])
    assert partner_a["consent_normalized_wi_pct"] == 0.375000
    assert partner_a["direct_capital_cents"] == 900_000
    assert partner_a["overhead_cents"] == 47_379
    assert partner_a["non_consent_reallocated_cents"] == 150_000
    assert partner_a["total_billed_cents"] == 1_037_379

    partner_b = fixtures.line_item_for(api, statement_id, context["partner_b_id"])
    assert partner_b["consent_normalized_wi_pct"] == 0.000000
    assert partner_b["direct_capital_cents"] == 100_000
    assert partner_b["direct_operating_cents"] == 60_000
    assert partner_b["overhead_cents"] == 7_657
    assert partner_b["non_consent_withheld_cents"] == 400_000
    assert partner_b["penalty_accrued_cents"] == 1_200_000
    assert partner_b["total_billed_cents"] == 167_657

    position = validate_success(
        api.get_well_interest(context["wi_partner_b_id"], fixtures.LAND_ADMIN), 200
    )
    assert position["non_consent_recoverable_balance_cents"] == 1_600_000
