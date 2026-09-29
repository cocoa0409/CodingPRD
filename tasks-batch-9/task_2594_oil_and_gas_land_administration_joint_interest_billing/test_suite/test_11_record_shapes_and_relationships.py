"""Derived acreage roll-ups, minted well posture, field shapes and the allocation junction."""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures

CLOCK = "2026-08-10T00:00:00Z"
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


def _bare_well(api, **overrides):
    return validate_success(
        api.create_well(
            factories.create_well_payload(omit_fields=["spud_date"], **overrides),
            fixtures.LAND_ADMIN,
        ),
        201,
    )


def test_a_tract_committed_to_two_units_rolls_its_acreage_up_across_both(api):
    """One lease can feed several units, and the land record must total all of them.

    In the same pass, each contributing lease has its `committed_acres_total` recomputed as the sum of `committed_acres` over that lease's committed allocations, and its `held_acres` recomputed as the lesser of its `gross_acres` and that committed total — except on a lease whose `tenure_status` is `EXPIRED`, where `held_acres` is 0.
    Each allocation is written with `allocation_status` set to `COMMITTED` and `withdrawn_reason` null, and the first commitment on a well moves its `pooling_status` from `UNPOOLED` to `POOLED_FORMING`.

    Design: Corner/entities/lease_committed_acres_total_and_held_acres_are_computed_from_allocations
    """
    fixtures.set_clock(api, CLOCK)
    lease = validate_success(
        api.create_lease(factories.minimal_lease_payload(), fixtures.LAND_ADMIN), 201
    )
    well_a = _bare_well(api)
    well_b = _bare_well(api, well_name="Sandstone 2H", api_number="42-123-45679")
    alloc_a = validate_success(
        api.create_lease_allocation(
            well_a["id"],
            factories.lease_allocation_payload(lease["id"], 480.0),
            fixtures.LAND_ADMIN,
        ),
        201,
    )

    alloc_b = validate_success(
        api.create_lease_allocation(
            well_b["id"],
            factories.lease_allocation_payload(lease["id"], 100.0),
            fixtures.LAND_ADMIN,
        ),
        201,
    )

    assert alloc_b["allocation_status"] == "COMMITTED"
    assert alloc_b["withdrawn_reason"] is None
    assert alloc_b["allocation_factor"] == 1.000000

    read_lease = validate_success(api.get_lease(lease["id"], fixtures.LAND_ADMIN), 200)
    assert read_lease["committed_acres_total"] == 580.00
    assert read_lease["held_acres"] == 580.00

    read_a = validate_success(
        api.get_lease_allocation(alloc_a["id"], fixtures.LAND_ADMIN), 200
    )
    assert read_a["allocation_status"] == "COMMITTED"
    assert read_a["allocation_factor"] == 1.000000

    for well_id in (well_a["id"], well_b["id"]):
        read_well = validate_success(api.get_well(well_id, fixtures.LAND_ADMIN), 200)
        assert read_well["allocation_factor_total"] == 1.000000
        assert read_well["pooling_status"] == "POOLED_FORMING"


def test_a_proposed_well_mints_its_own_status_unit_and_ledger_fields(api):
    """The driller supplies geology only; status, unit and money are the service's to mint.

    A new well begins with `well_status` set to `PROPOSED` and `pooling_status` set to `UNPOOLED`, with `allocation_factor_total`, `consent_working_interest_pct` and `billed_to_date_cents` all 0, `first_production_date` and `shut_in_since` null, and `version` 1.
    The estimate is a base charge of $35,000 plus $12 for every foot of measured depth, and it is capped at $250,000; expressed in the cents the service actually stores, it is 3,500,000 plus 1,200 multiplied by `total_depth_ft`, and if that sum exceeds 25,000,000 the estimate is 25,000,000 instead.

    Design: Corner/entities/well_creation_mints_its_own_status_pooling_and_ledger_fields
    """
    fixtures.set_clock(api, CLOCK)

    well = _bare_well(api)

    assert is_valid_uuid(well["id"])
    assert is_iso8601_timestamp(well["created_at"])
    assert is_iso8601_timestamp(well["updated_at"])
    assert well["version"] == 1
    assert well["well_status"] == "PROPOSED"
    assert well["pooling_status"] == "UNPOOLED"
    assert well["first_production_date"] is None
    assert well["shut_in_since"] is None
    assert well["allocation_factor_total"] == 0.000000
    assert well["consent_working_interest_pct"] == 0.000000
    assert well["billed_to_date_cents"] == 0
    assert well["plugging_liability_cents"] == 14_900_000


def test_an_owner_registered_under_an_unrecognised_capacity_is_refused(api):
    """A mineral owner is not one of the capacities the division order recognises.

    Enum-typed fields carry a declared value; integer cent fields are zero or greater; percentage fields lie within the inclusive range 0.000000 through 1.000000 and carry at most six decimal places; date fields are valid ISO 8601 calendar dates; `production_month` matches a four-digit year, a hyphen, and a two-digit month in the range 01 through 12; `non_consent_penalty_multiple` lies within the inclusive range 1.0 through 5.0 and carries at most one decimal place.
    A `LandAdministrator` registers an interest owner with an `owner_name`, an `owner_type` of `WORKING_INTEREST_PARTNER`, `ROYALTY_OWNER` or `OVERRIDING_ROYALTY_OWNER`, and a `contact_email` that serves as the notice address for AFE, audit and division-order correspondence.

    Design: Corner/entities/create_interest_owner_with_an_undeclared_owner_type_is_rejected
    """
    fixtures.set_clock(api, CLOCK)

    validate_error(
        api.create_interest_owner(
            factories.minimal_interest_owner_payload(
                owner_name="Zeta Minerals",
                owner_type="MINERAL_OWNER",
                contact_email="zeta@example.com",
            ),
            fixtures.LAND_ADMIN,
        ),
        "ERR_VALIDATION",
        400,
    )

    _, meta = validate_paginated(api.list_interest_owners(fixtures.LAND_ADMIN))
    assert meta["total_count"] == 0


def test_a_lease_reserving_more_than_the_whole_proceeds_is_refused(api):
    """A royalty above unity would leave the working interest owing money on every barrel.

    The royalty rate is strictly greater than zero and strictly less than one, carried to exactly six decimal places, because a lease that reserved the whole proceeds or none of them is not a lease the land department can administer.

    Design: Corner/entities/create_lease_with_a_royalty_rate_above_one_is_rejected
    """
    fixtures.set_clock(api, CLOCK)

    validate_error(
        api.create_lease(
            factories.minimal_lease_payload(
                lease_number="L-010",
                lessor_name="Theta Minerals",
                gross_acres=200.0,
                royalty_rate=1.25,
                primary_term_end_date="2027-03-31",
            ),
            fixtures.LAND_ADMIN,
        ),
        "ERR_VALIDATION",
        400,
    )

    _, meta = validate_paginated(api.list_leases(fixtures.LAND_ADMIN))
    assert meta["total_count"] == 0


def test_an_authorization_circulated_under_an_unknown_well_reports_the_missing_well(api):
    """The path is resolved before the body, so a bad well is a missing well, not bad data.

    Each identifier embedded in the URL path is resolved in the order it appears, outermost segment first, before any body content is inspected.
    `well_id` must resolve to a well, else `ERR_WELL_NOT_FOUND` (404).

    Design: Corner/entities/create_afe_under_an_unknown_well_returns_not_found
    """
    fixtures.set_clock(api, CLOCK)
    _bare_well(api)

    validate_error(
        api.create_afe(
            UNKNOWN_ID,
            factories.minimal_afe_payload(
                afe_number="AFE-901",
                operation_type="DRILL",
                estimated_cost_cents=500_000,
                cost_class="CAPITAL",
                election_deadline_date="2026-08-31",
            ),
            fixtures.LAND_ADMIN,
        ),
        "ERR_WELL_NOT_FOUND",
        404,
    )

    _, meta = validate_paginated(api.list_afes(fixtures.LAND_ADMIN))
    assert meta["total_count"] == 0


def test_the_acreage_junction_reads_the_same_from_the_tract_side_and_the_unit_side(api):
    """A title examiner works from the lease; a bookkeeper works from the unit.

    Allocations are browsable filtered by `well_id`, by `lease_id` or by `allocation_status`, and a single allocation is readable by its own identifier.
    Otherwise the total committed acreage of the unit is the sum of `committed_acres` across the committed allocations, and each allocation's provisional factor is its own `committed_acres` divided by that total, rounded half up to six decimal places.

    Design: Corner/entities/the_lease_well_allocation_junction_is_discoverable_from_both_sides
    """
    fixtures.set_clock(api, CLOCK)
    lease1 = validate_success(
        api.create_lease(factories.minimal_lease_payload(), fixtures.LAND_ADMIN), 201
    )
    lease2 = validate_success(
        api.create_lease(
            factories.minimal_lease_payload(
                lease_number="L-002",
                lessor_name="Beta Royalties",
                gross_acres=320.0,
                royalty_rate=0.25,
                primary_term_end_date="2027-12-31",
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )
    well_a = _bare_well(api)
    well_b = _bare_well(api, well_name="Sandstone 2H", api_number="42-123-45679")
    fixtures.commit_acreage(api, well_a["id"], lease1["id"], 480.0)
    fixtures.commit_acreage(api, well_a["id"], lease2["id"], 160.0)
    fixtures.commit_acreage(api, well_b["id"], lease1["id"], 100.0)

    by_lease, lease_meta = validate_paginated(
        api.list_lease_allocations(
            fixtures.LAND_ADMIN, params={"lease_id": lease1["id"], "limit": 100}
        )
    )
    assert lease_meta["total_count"] == 2
    assert sorted(row["committed_acres"] for row in by_lease) == [100.00, 480.00]
    assert {row["well_id"] for row in by_lease} == {well_a["id"], well_b["id"]}
    lease1_by_well = {row["well_id"]: row for row in by_lease}
    assert lease1_by_well[well_a["id"]]["committed_acres"] == 480.00
    assert lease1_by_well[well_a["id"]]["allocation_factor"] == 0.750000
    assert lease1_by_well[well_b["id"]]["committed_acres"] == 100.00
    assert lease1_by_well[well_b["id"]]["allocation_factor"] == 1.000000

    by_well, well_meta = validate_paginated(
        api.list_lease_allocations(
            fixtures.LAND_ADMIN, params={"well_id": well_a["id"], "limit": 100}
        )
    )
    assert well_meta["total_count"] == 2
    factors = {row["lease_id"]: row["allocation_factor"] for row in by_well}
    assert factors[lease1["id"]] == 0.750000
    assert factors[lease2["id"]] == 0.250000
    assert round(sum(factors.values()), 6) == 1.000000

    read_well_a = validate_success(api.get_well(well_a["id"], fixtures.LAND_ADMIN), 200)
    assert read_well_a["allocation_factor_total"] == 1.000000


def test_a_charge_row_carries_no_version_and_never_moves_when_the_bill_settles(api):
    """Charge rows are the audit floor of the joint account, so cash application cannot touch them.

    A JIB line item therefore carries only `id` and `created_at`: it has no `updated_at` field and no `version` field at all.
    Line items are the only immutable rows in the system, and they are discoverable in two ways: as the line items of one statement, optionally filtered by `owner_id`; and as everything ever billed to one owner across statements, optionally filtered by `statement_status`.

    Design: Corner/entities/jib_line_items_expose_no_version_field_and_no_write_endpoint
    """
    context = fixtures.setup_issued_june_statement(api, clock=CLOCK)
    statement_id = context["statement_id"]
    before = fixtures.get_line_items(api, statement_id)
    assert sorted(row["total_billed_cents"] for row in before) == [
        586_800,
        880_200,
        1_467_000,
    ]

    settled = validate_success(
        api.settle_jib_statement(
            statement_id,
            fixtures.JIB_ACCOUNTANT,
            factories.statement_settlement_payload("2026-07-10"),
        ),
        200,
    )

    assert settled["statement_status"] == "SETTLED"
    assert settled["total_billed_cents"] == 2_934_000

    after, meta = validate_paginated(
        api.list_jib_statement_line_items(
            statement_id, fixtures.JIB_ACCOUNTANT, params={"limit": 100}
        )
    )
    assert meta["total_count"] == 3
    assert sorted(row["total_billed_cents"] for row in after) == [
        586_800,
        880_200,
        1_467_000,
    ]
    assert {row["id"] for row in after} == {row["id"] for row in before}
    for row in after:
        assert "version" not in row
        assert "updated_at" not in row
        assert is_iso8601_timestamp(row["created_at"])

    well = validate_success(api.get_well(context["well_id"], fixtures.LAND_ADMIN), 200)
    assert well["billed_to_date_cents"] == 2_934_000
