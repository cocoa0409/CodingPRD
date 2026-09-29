"""Arithmetic the service owns: unit factors, cost pools, depth estimates, bonds, overhead."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories, fixtures

CLOCK = "2026-08-10T00:00:00Z"


def _bare_well(api, **overrides):
    return validate_success(
        api.create_well(
            factories.create_well_payload(omit_fields=["spud_date"], **overrides),
            fixtures.LAND_ADMIN,
        ),
        201,
    )


def test_the_unit_factor_remainder_is_handed_to_the_earliest_of_the_tied_tracts(api):
    """Three equal tracts cannot each hold a third of a unit, so one tract absorbs the dust.

    Those provisional factors will generally not sum to exactly one, so the signed difference between 1.000000 and their sum — always some whole multiple of 0.000001, and possibly negative — is added in its entirety to a single allocation: the one with the largest `committed_acres`, and among ties the one with the earliest `created_at`.
    After that adjustment the well's `allocation_factor_total` is exactly 1.000000.

    Design: Corner/calculations/allocation_factor_residual_lands_on_the_first_largest_allocation
    """
    fixtures.set_clock(api, CLOCK)
    lease1 = validate_success(
        api.create_lease(
            factories.minimal_lease_payload(gross_acres=160.0), fixtures.LAND_ADMIN
        ),
        201,
    )
    lease2 = validate_success(
        api.create_lease(
            factories.minimal_lease_payload(
                lease_number="L-002",
                lessor_name="Beta Royalties",
                gross_acres=160.0,
                royalty_rate=0.25,
                primary_term_end_date="2027-12-31",
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )
    lease3 = validate_success(
        api.create_lease(
            factories.minimal_lease_payload(
                lease_number="L-003",
                lessor_name="Gamma Minerals",
                gross_acres=160.0,
                royalty_rate=0.2,
                primary_term_end_date="2028-06-30",
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )
    well = _bare_well(api)
    alloc1 = fixtures.commit_acreage(api, well["id"], lease1["id"], 100.0)
    alloc2 = fixtures.commit_acreage(api, well["id"], lease2["id"], 100.0)

    alloc3 = validate_success(
        api.create_lease_allocation(
            well["id"],
            factories.lease_allocation_payload(lease3["id"], 100.0),
            fixtures.LAND_ADMIN,
        ),
        201,
    )

    factors = {}
    for allocation in (alloc1, alloc2, alloc3):
        row = validate_success(
            api.get_lease_allocation(allocation["id"], fixtures.LAND_ADMIN), 200
        )
        factors[allocation["id"]] = row["allocation_factor"]

    assert factors[alloc1["id"]] == 0.333334
    assert factors[alloc2["id"]] == 0.333333
    assert factors[alloc3["id"]] == 0.333333

    read_well = validate_success(api.get_well(well["id"], fixtures.LAND_ADMIN), 200)
    assert read_well["allocation_factor_total"] == 1.000000

    for lease_id in (lease1["id"], lease3["id"]):
        lease = validate_success(api.get_lease(lease_id, fixtures.LAND_ADMIN), 200)
        assert lease["committed_acres_total"] == 100.00
        assert lease["held_acres"] == 100.00


def test_charges_incurred_outside_the_billing_period_stay_out_of_the_pool(api):
    """A June bill is a June bill: May and July invoices sit in the joint account untouched.

    Under the `ACCRUAL` basis, an entry qualifies when its `cost_status` is `ACCRUED` or `PAID` and its `incurred_date` falls on or after `billing_period_start` and on or before `billing_period_end`. A charge incurred inside the period but settled with the vendor after the period closes **is** billed.

    Design: Corner/calculations/the_accrual_cost_pool_excludes_costs_outside_the_billing_period
    """
    context = fixtures.setup_pooled_producing_well(api, clock=CLOCK)
    well_id = context["well_id"]
    early = fixtures.book_cost(
        api, well_id, "COMPLETION", "CAPITAL", 888_000, "2026-05-20"
    )
    late = fixtures.book_cost(
        api, well_id, "LEASE_OPERATING", "OPERATING", 777_000, "2026-07-05"
    )
    fixtures.book_june_cost_history(api, well_id)
    statement = fixtures.open_statement(api, well_id)

    issued = validate_success(
        api.issue_jib_statement(statement["id"], fixtures.JIB_ACCOUNTANT), 200
    )

    assert issued["capital_direct_cents"] == 2_500_000
    assert issued["operating_direct_cents"] == 300_000
    assert issued["direct_cost_cents"] == 2_800_000
    assert issued["overhead_cents"] == 134_000
    assert issued["total_billed_cents"] == 2_934_000

    for entry in (early, late):
        row = validate_success(
            api.get_cost_entry(entry["id"], fixtures.JIB_ACCOUNTANT), 200
        )
        assert row["cost_status"] == "ACCRUED"

    well = validate_success(api.get_well(well_id, fixtures.LAND_ADMIN), 200)
    assert well["billed_to_date_cents"] == 2_934_000


def test_the_abandonment_estimate_follows_the_depth_formula_up_to_its_cap(api):
    """Depth alone drives the estimate, and a quarter of a million dollars is the ceiling.

    The estimate is a base charge of $35,000 plus $12 for every foot of measured depth, and it is capped at $250,000; expressed in the cents the service actually stores, it is 3,500,000 plus 1,200 multiplied by `total_depth_ft`, and if that sum exceeds 25,000,000 the estimate is 25,000,000 instead.

    Design: Corner/calculations/plugging_liability_uses_the_base_depth_rate_and_cap_constants
    """
    fixtures.set_clock(api, CLOCK)
    shallow = _bare_well(api)
    just_under = _bare_well(
        api,
        well_name="Sandstone 2H",
        api_number="42-123-45679",
        product_type="GAS",
        total_depth_ft=17916,
    )

    over_the_cap = _bare_well(
        api,
        well_name="Sandstone 3H",
        api_number="42-123-45680",
        product_type="GAS",
        total_depth_ft=17917,
    )

    assert shallow["plugging_liability_cents"] == 14_900_000
    assert just_under["plugging_liability_cents"] == 24_999_200
    assert over_the_cap["plugging_liability_cents"] == 25_000_000


def test_the_bond_requirement_rounds_each_well_before_the_coverage_factor_is_applied(api):
    """Rounding after the factor instead of before it produces a different, wrong figure.

    For each such position, the owner's share of that well's plugging cost is its `working_interest_pct` multiplied by that well's `plugging_liability_cents`, and **that per-well product is rounded half up to whole cents before anything is added together**.
    Those rounded per-well amounts are then summed, the sum is multiplied by a coverage factor of 1.25 — the joint operating agreement requires 125% of estimated exposure, not merely 100% — and that product is rounded half up once more to produce `required_bond_cents`.

    Design: Corner/calculations/bond_coverage_rounds_the_per_well_product_before_the_factor
    """
    fixtures.set_clock(api, CLOCK)
    well = _bare_well(api, well_name="Sandstone 9H", api_number="42-123-45699")
    owner = validate_success(
        api.create_interest_owner(
            factories.create_interest_owner_payload(
                owner_name="Gamma Operating LP",
                contact_email="gamma@example.com",
                bond_posted_cents=20_000_000,
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )
    version = fixtures.well_version(api, well["id"])

    interest = validate_success(
        api.create_well_interest(
            well["id"],
            factories.create_well_interest_payload(
                owner["id"], 0.333333, 0.3, "2026-01-01", version
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )

    assert interest["working_interest_pct"] == 0.333333
    assert interest["interest_status"] == "ACTIVE"

    read_owner = validate_success(
        api.get_interest_owner(owner["id"], fixtures.LAND_ADMIN), 200
    )
    assert read_owner["required_bond_cents"] == 6_208_328
    assert read_owner["required_bond_cents"] != 6_208_327
    assert read_owner["bond_posted_cents"] == 20_000_000


def test_fixed_rate_overhead_is_a_monthly_rate_escalated_by_the_wage_index(api):
    """Two calendar months touched by the period means two months of escalated overhead.

    Under the `FIXED_RATE` mode the rate is per month and depends on the activity class: a `DRILLING` statement is charged $9,500 per billable month and a `PRODUCING` statement $950 per billable month — that is, 950000 cents per month for drilling activity and 95000 cents per month for producing activity.
    That per-month rate is multiplied by `billable_months` and by a wage index adjustment of 1.042, reflecting the annually published labour escalation the joint operating agreement incorporates.

    Design: Corner/calculations/fixed_rate_overhead_multiplies_the_wage_index_by_billable_months
    """
    context = fixtures.setup_pooled_producing_well(api, clock=CLOCK)
    fixtures.book_june_cost_history(api, context["well_id"])
    statement = fixtures.open_statement(
        api,
        context["well_id"],
        statement_number="JIB-2026-Q2",
        billing_period_start="2026-05-01",
        billing_period_end="2026-06-30",
        overhead_rate_class="FIXED_RATE",
    )

    issued = validate_success(
        api.issue_jib_statement(statement["id"], fixtures.JIB_ACCOUNTANT), 200
    )

    assert issued["billable_months"] == 2
    assert issued["overhead_cents"] == 197_980
    assert issued["direct_cost_cents"] == 2_800_000
    assert issued["total_billed_cents"] == 2_997_980

    well = validate_success(api.get_well(context["well_id"], fixtures.LAND_ADMIN), 200)
    assert well["billed_to_date_cents"] == 2_997_980

    rows, meta = validate_paginated(
        api.list_jib_statement_line_items(
            statement["id"], fixtures.JIB_ACCOUNTANT, params={"limit": 100}
        )
    )
    assert meta["total_count"] == 3
    assert sum(row["total_billed_cents"] for row in rows) == 2_997_980
