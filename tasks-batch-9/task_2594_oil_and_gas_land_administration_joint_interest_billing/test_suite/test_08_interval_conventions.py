"""Two interval conventions on the same well: closed billing periods, half-open interests."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories, fixtures

CLOCK = "2026-08-15T00:00:00Z"


def test_billing_periods_that_merely_touch_at_a_day_cannot_coexist(api):
    """A shared endpoint day blocks the next bill until the first one is withdrawn.

    Because the intervals are closed, **two periods that merely touch at an endpoint collide** — a period ending 2026-06-30 and a period beginning 2026-06-30 share that day and cannot coexist.
    Voided statements are excluded from this check, which is precisely how voiding a statement frees its period for a fresh one.

    Design: Difficulty/resource_temporal_overlap/jib_billing_periods_are_closed_intervals_so_touching_endpoints_collide
    """
    context = fixtures.setup_pooled_producing_well(api, clock=CLOCK)
    well_id = context["well_id"]

    fixtures.book_cost(
        api, well_id, "LEASE_OPERATING", "OPERATING", 200_000, "2026-05-10", "2026-05-11"
    )
    fixtures.book_cost(
        api, well_id, "LEASE_OPERATING", "OPERATING", 300_000, "2026-06-15", "2026-06-16"
    )
    fixtures.book_cost(
        api, well_id, "LEASE_OPERATING", "OPERATING", 400_000, "2026-07-20", "2026-07-21"
    )

    spring = fixtures.open_statement(
        api,
        well_id,
        statement_number="JIB-2026-A",
        billing_period_start="2026-05-01",
        billing_period_end="2026-06-30",
    )
    assert spring["statement_status"] == "DRAFT"
    assert spring["billable_months"] == 2
    assert spring["total_billed_cents"] == 525_000

    validate_error(
        api.create_jib_statement(
            well_id,
            factories.create_jib_statement_payload(
                statement_number="JIB-2026-B",
                billing_period_start="2026-06-30",
                billing_period_end="2026-07-31",
            ),
            fixtures.JIB_ACCOUNTANT,
        ),
        "ERR_STATEMENT_PERIOD_OVERLAP",
        409,
    )
    rows, meta = validate_paginated(
        api.list_jib_statements(fixtures.JIB_ACCOUNTANT, params={"well_id": well_id})
    )
    assert meta["total_count"] == 1

    july = fixtures.open_statement(
        api,
        well_id,
        statement_number="JIB-2026-C",
        billing_period_start="2026-07-01",
        billing_period_end="2026-07-31",
    )
    assert july["billable_months"] == 1
    assert july["total_billed_cents"] == 425_000

    voided = validate_success(
        api.void_jib_statement(
            spring["id"],
            fixtures.JIB_ACCOUNTANT,
            factories.statement_void_payload("PERIOD_RESTATEMENT"),
        ),
        200,
    )
    assert voided["statement_status"] == "VOID"
    assert (
        validate_success(api.get_well(well_id, fixtures.LAND_ADMIN), 200)[
            "billed_to_date_cents"
        ]
        == 0
    )

    replacement = fixtures.open_statement(
        api,
        well_id,
        statement_number="JIB-2026-D",
        billing_period_start="2026-05-01",
        billing_period_end="2026-06-30",
    )
    assert replacement["billing_period_start"] == "2026-05-01"
    assert replacement["billing_period_end"] == "2026-06-30"
    assert replacement["total_billed_cents"] == 525_000

    rows, meta = validate_paginated(
        api.list_jib_statements(fixtures.JIB_ACCOUNTANT, params={"well_id": well_id})
    )
    assert meta["total_count"] == 3


def test_interest_intervals_that_touch_at_a_day_are_adjacent_and_legal(api):
    """The same owner may hold back-to-back positions, but not a straddling third.

    Intervals are **half-open**: `effective_from` is inclusive, `effective_to` is exclusive, and an `effective_to` of null means the position runs open-ended.
    Two intervals that merely touch at an endpoint — one ending 2026-06-01 and the next beginning 2026-06-01 — are adjacent and perfectly legal.

    Design: Difficulty/resource_temporal_overlap/well_interest_intervals_are_half_open_so_touching_endpoints_are_adjacent
    """
    context = fixtures.setup_pooled_producing_well(api, clock=CLOCK)
    well_id = context["well_id"]
    partner_b_id = context["partner_b_id"]
    partner_c_id = context["partner_c_id"]

    terminated = validate_success(
        api.terminate_well_interest(
            context["wi_partner_b_id"],
            factories.interest_termination_payload("2026-06-01"),
            fixtures.LAND_ADMIN,
        ),
        200,
    )
    assert terminated["interest_status"] == "TERMINATED"
    assert terminated["effective_to"] == "2026-06-01"

    early = fixtures.add_interest(
        api,
        well_id,
        partner_c_id,
        0.05,
        0.04,
        effective_from="2026-01-01",
        effective_to="2026-06-01",
    )
    late = fixtures.add_interest(
        api, well_id, partner_c_id, 0.05, 0.04, effective_from="2026-06-01"
    )
    assert early["interest_status"] == "ACTIVE"
    assert late["interest_status"] == "ACTIVE"

    active = fixtures.active_interests(api, well_id)
    assert sum(row["working_interest_pct"] for row in active) == 0.900000

    version = fixtures.well_version(api, well_id)
    validate_error(
        api.create_well_interest(
            well_id,
            factories.create_well_interest_payload(
                partner_c_id, 0.05, 0.04, "2026-03-01", version, effective_to="2026-09-01"
            ),
            fixtures.LAND_ADMIN,
        ),
        "ERR_INTEREST_PERIOD_OVERLAP",
        409,
    )

    rows, meta = validate_paginated(
        api.list_well_interests(
            fixtures.LAND_ADMIN, params={"well_id": well_id, "owner_id": partner_c_id}
        )
    )
    assert meta["total_count"] == 2
    assert fixtures.well_version(api, well_id) == version

    restored = validate_success(
        api.create_well_interest(
            well_id,
            factories.create_well_interest_payload(
                partner_b_id, 0.1, 0.08, "2026-01-01", version
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )
    assert restored["interest_status"] == "ACTIVE"

    active = fixtures.active_interests(api, well_id)
    assert sum(row["working_interest_pct"] for row in active) == 1.000000

    holder = validate_success(
        api.get_interest_owner(partner_b_id, fixtures.LAND_ADMIN), 200
    )
    assert holder["required_bond_cents"] == 1_862_500
