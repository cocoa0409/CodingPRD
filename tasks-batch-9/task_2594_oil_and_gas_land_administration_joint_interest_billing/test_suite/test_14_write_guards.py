"""Ordered business checks on writes, and the boundary rows that are legitimately admitted."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures

CLOCK = "2026-08-10T00:00:00Z"
UNKNOWN_LEASE_ID = "00000000-0000-0000-0000-0000000000ff"


def _bare_well(api, **overrides):
    return validate_success(
        api.create_well(
            factories.create_well_payload(omit_fields=["spud_date"], **overrides),
            fixtures.LAND_ADMIN,
        ),
        201,
    )


def _owner(api, name, email, bond):
    return validate_success(
        api.create_interest_owner(
            factories.create_interest_owner_payload(
                owner_name=name, contact_email=email, bond_posted_cents=bond
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )


def test_a_partner_cannot_take_more_revenue_than_it_bears_of_the_cost(api):
    """A three-tenths cost bearer taking four-tenths of the revenue is not a division order.

    Finally, on the row itself, `net_revenue_interest_pct` may not exceed `working_interest_pct`, since an owner cannot take more of the revenue than it bears of the cost; a breach is rejected with `ERR_NRI_EXCEEDS_WI`.

    Design: Corner/validations/net_revenue_interest_above_working_interest_is_rejected
    """
    fixtures.set_clock(api, CLOCK)
    well = _bare_well(api)
    owner = _owner(api, "Delta Partners LP", "delta@example.com", 10_000_000)
    version = fixtures.well_version(api, well["id"])

    validate_error(
        api.create_well_interest(
            well["id"],
            factories.create_well_interest_payload(
                owner["id"], 0.3, 0.4, "2026-01-01", version
            ),
            fixtures.LAND_ADMIN,
        ),
        "ERR_NRI_EXCEEDS_WI",
        422,
    )

    _, meta = validate_paginated(
        api.list_well_interests(fixtures.LAND_ADMIN, params={"well_id": well["id"]})
    )
    assert meta["total_count"] == 0

    after = validate_success(api.get_well(well["id"], fixtures.LAND_ADMIN), 200)
    assert after["version"] == version

    read_owner = validate_success(
        api.get_interest_owner(owner["id"], fixtures.LAND_ADMIN), 200
    )
    assert read_owner["required_bond_cents"] == 0


def test_the_row_that_completes_the_cost_side_exactly_is_admitted(api):
    """A unit is fully subscribed at one, and the row that gets it there is not oversubscription.

    Next, the well's cost side may not be oversubscribed: the sum of `working_interest_pct` over the well's `ACTIVE` positions, counting the row about to be written, may not exceed 1.000000, else the request is rejected with `ERR_WI_SUM_EXCEEDED`.
    A well's `consent_working_interest_pct` is a derived figure: the sum of `working_interest_pct` across the well's positions that are both `ACTIVE` and carry `non_consent_flag` false.

    Design: Corner/validations/an_interest_row_completing_exactly_one_hundred_percent_is_accepted
    """
    fixtures.set_clock(api, CLOCK)
    well = _bare_well(api)
    operator = _owner(api, "Operator Energy LLC", "operator@example.com", 50_000_000)
    partner_a = _owner(api, "Delta Partners LP", "delta@example.com", 10_000_000)
    partner_b = _owner(api, "Epsilon Resources Inc", "epsilon@example.com", 0)
    fixtures.add_interest(
        api,
        well["id"],
        operator["id"],
        0.5,
        0.4125,
        is_operator=True,
        preferential_right=True,
    )
    fixtures.add_interest(
        api, well["id"], partner_a["id"], 0.3, 0.24, preferential_right=True
    )
    version = fixtures.well_version(api, well["id"])

    interest = validate_success(
        api.create_well_interest(
            well["id"],
            factories.create_well_interest_payload(
                partner_b["id"], 0.2, 0.15, "2026-01-01", version
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )

    assert interest["interest_status"] == "ACTIVE"
    assert interest["non_consent_flag"] is False
    assert interest["working_interest_pct"] == 0.200000

    after = validate_success(api.get_well(well["id"], fixtures.LAND_ADMIN), 200)
    assert after["consent_working_interest_pct"] == 1.000000

    _, meta = validate_paginated(
        api.list_well_interests(
            fixtures.LAND_ADMIN, params={"well_id": well["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 3


def test_a_tract_cannot_contribute_acreage_it_has_already_dedicated(api):
    """Six hundred and forty acres cannot be committed twice over to two different units.

    And a lease cannot contribute acreage it does not have left: `committed_acres` must be strictly greater than zero and no greater than the lease's `gross_acres` less its `committed_acres_total`, else the request is rejected with `ERR_ALLOCATION_EXCEEDS_LEASE`.

    Design: Corner/validations/an_allocation_exceeding_the_leases_remaining_acres_is_rejected
    """
    fixtures.set_clock(api, CLOCK)
    lease = validate_success(
        api.create_lease(factories.minimal_lease_payload(), fixtures.LAND_ADMIN), 201
    )
    well1 = _bare_well(api)
    well2 = _bare_well(
        api, well_name="Sandstone 2H", api_number="42-123-45679", total_depth_ft=9000
    )
    fixtures.commit_acreage(api, well1["id"], lease["id"], 480.0)

    validate_error(
        api.create_lease_allocation(
            well2["id"],
            factories.lease_allocation_payload(lease["id"], 200.0),
            fixtures.LAND_ADMIN,
        ),
        "ERR_ALLOCATION_EXCEEDS_LEASE",
        422,
    )

    read_lease = validate_success(api.get_lease(lease["id"], fixtures.LAND_ADMIN), 200)
    assert read_lease["committed_acres_total"] == 480.00
    assert read_lease["held_acres"] == 480.00

    read_well2 = validate_success(api.get_well(well2["id"], fixtures.LAND_ADMIN), 200)
    assert read_well2["allocation_factor_total"] == 0.000000

    validate_success(
        api.create_lease_allocation(
            well2["id"],
            factories.lease_allocation_payload(lease["id"], 160.00),
            fixtures.LAND_ADMIN,
        ),
        201,
    )
    final_lease = validate_success(api.get_lease(lease["id"], fixtures.LAND_ADMIN), 200)
    assert final_lease["committed_acres_total"] == 640.00


def test_a_commitment_naming_no_real_tract_reports_the_missing_tract_first(api):
    """An impossible acreage figure is beside the point when the instrument does not exist.

    A `lease_id` supplied in an acreage-commitment body must resolve to a lease, else `ERR_LEASE_NOT_FOUND` (404).

    Design: Corner/validations/body_lease_existence_is_checked_before_the_acreage_aggregate
    """
    fixtures.set_clock(api, CLOCK)
    well = _bare_well(api)

    validate_error(
        api.create_lease_allocation(
            well["id"],
            factories.lease_allocation_payload(UNKNOWN_LEASE_ID, 9999.0),
            fixtures.LAND_ADMIN,
        ),
        "ERR_LEASE_NOT_FOUND",
        404,
    )

    after = validate_success(api.get_well(well["id"], fixtures.LAND_ADMIN), 200)
    assert after["allocation_factor_total"] == 0.000000


def test_an_election_arriving_the_day_after_the_deadline_is_too_late(api):
    """The deadline day itself is open; the day after it is not.

    The logical clock date must be on or before `election_deadline_date` — the deadline day itself is still open — else `ERR_ELECTION_DEADLINE_PASSED`.

    Design: Corner/validations/an_election_filed_after_the_deadline_day_is_rejected
    """
    context = fixtures.setup_pooled_producing_well(api, clock=CLOCK)
    afe = fixtures.raise_afe(
        api,
        context["well_id"],
        afe_number="AFE-001",
        operation_type="COMPLETION",
        estimated_cost_cents=2_000_000,
        cost_class="CAPITAL",
        election_deadline_date="2026-08-31",
        non_consent_penalty_multiple=3.0,
        minimum_consent_pct=0.5,
    )
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")

    validate_error(
        api.submit_afe_election(
            afe["id"],
            factories.afe_election_payload(context["partner_a_id"], "CONSENT"),
            fixtures.LAND_ADMIN,
        ),
        "ERR_ELECTION_DEADLINE_PASSED",
        422,
    )

    read_afe = validate_success(api.get_afe(afe["id"], fixtures.LAND_ADMIN), 200)
    assert read_afe["afe_status"] == "ELECTIONS_OPEN"

    _, meta = validate_paginated(
        api.list_afe_elections(fixtures.LAND_ADMIN, params={"afe_id": afe["id"]})
    )
    assert meta["total_count"] == 0

    closed = validate_success(
        api.close_afe_elections(
            afe["id"], factories.election_closure_payload(), fixtures.LAND_ADMIN
        ),
        200,
    )
    assert closed["elections_closed_at"] is not None


def test_an_instrument_that_never_granted_an_option_cannot_have_one_exercised(api):
    """Availability is settled before the money is counted, so a zero tender is not the complaint.

    A lease failing any of those conditions, including a second exercise attempt on an option already used, is rejected with `ERR_EXTENSION_NOT_AVAILABLE`.
    The lease must still be in `PRIMARY_TERM`, must have `extension_exercised` false, must have an `extension_option_months` strictly greater than zero, and the logical clock date must be on or before `primary_term_end_date` — an option cannot be exercised out of a term that has already run.

    Design: Corner/validations/extending_a_lease_configured_without_an_option_is_rejected
    """
    fixtures.set_clock(api, CLOCK)
    with_option = validate_success(
        api.create_lease(
            factories.create_lease_payload(
                omit_fields=[
                    "shut_in_royalty_per_acre_cents",
                    "continuous_dev_window_days",
                ]
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )
    without_option = validate_success(
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
    validate_success(
        api.exercise_lease_extension(
            with_option["id"],
            factories.lease_extension_payload(9_600_000),
            fixtures.LAND_ADMIN,
        ),
        200,
    )

    validate_error(
        api.exercise_lease_extension(
            without_option["id"],
            factories.lease_extension_payload(0),
            fixtures.LAND_ADMIN,
        ),
        "ERR_EXTENSION_NOT_AVAILABLE",
        409,
    )

    read_without = validate_success(
        api.get_lease(without_option["id"], fixtures.LAND_ADMIN), 200
    )
    assert read_without["tenure_status"] == "PRIMARY_TERM"
    assert read_without["primary_term_end_date"] == "2028-06-30"
    assert read_without["extension_exercised"] is False

    read_with = validate_success(
        api.get_lease(with_option["id"], fixtures.LAND_ADMIN), 200
    )
    assert read_with["tenure_status"] == "PRIMARY_TERM"
    assert read_with["extension_exercised"] is True
    assert read_with["primary_term_end_date"] == "2028-09-30"
