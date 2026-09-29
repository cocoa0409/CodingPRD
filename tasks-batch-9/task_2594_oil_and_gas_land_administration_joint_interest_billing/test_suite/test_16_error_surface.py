"""Every error the joint account can raise on purpose, raised on purpose."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures

CLOCK = "2026-08-10T00:00:00Z"
UNKNOWN_ID = "00000000-0000-0000-0000-0000000000ff"


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


def test_every_addressable_record_reports_its_own_kind_of_miss(api):
    """A land examiner needs to know which record is missing, not merely that one is.

    Each identifier embedded in the URL path is resolved in the order it appears, outermost segment first, before any body content is inspected.
    `transfer_id` must resolve to an assignment transfer, else `ERR_TRANSFER_NOT_FOUND` (404).

    Design: Corner/errors/unknown_ids_on_every_addressable_resource_return_their_own_not_found
    """
    fixtures.set_clock(api, CLOCK)

    validate_error(
        api.get_lease(UNKNOWN_ID, fixtures.LAND_ADMIN), "ERR_LEASE_NOT_FOUND", 404
    )
    validate_error(
        api.get_well(UNKNOWN_ID, fixtures.LAND_ADMIN), "ERR_WELL_NOT_FOUND", 404
    )
    validate_error(
        api.get_interest_owner(UNKNOWN_ID, fixtures.LAND_ADMIN),
        "ERR_INTEREST_OWNER_NOT_FOUND",
        404,
    )
    validate_error(
        api.get_well_interest(UNKNOWN_ID, fixtures.LAND_ADMIN),
        "ERR_WELL_INTEREST_NOT_FOUND",
        404,
    )
    validate_error(
        api.get_afe(UNKNOWN_ID, fixtures.LAND_ADMIN), "ERR_AFE_NOT_FOUND", 404
    )
    validate_error(
        api.get_jib_statement(UNKNOWN_ID, fixtures.JIB_ACCOUNTANT),
        "ERR_JIB_STATEMENT_NOT_FOUND",
        404,
    )
    validate_error(
        api.get_dispute(UNKNOWN_ID, fixtures.JIB_ACCOUNTANT), "ERR_DISPUTE_NOT_FOUND", 404
    )
    validate_error(
        api.get_production_revenue(UNKNOWN_ID, fixtures.JIB_ACCOUNTANT),
        "ERR_PRODUCTION_REVENUE_NOT_FOUND",
        404,
    )
    validate_error(
        api.get_owner_disbursement(UNKNOWN_ID, fixtures.JIB_ACCOUNTANT),
        "ERR_DISBURSEMENT_NOT_FOUND",
        404,
    )
    validate_error(
        api.get_assignment_transfer(UNKNOWN_ID, fixtures.LAND_ADMIN),
        "ERR_TRANSFER_NOT_FOUND",
        404,
    )


def test_a_page_window_outside_the_permitted_range_is_refused_at_either_end(api):
    """Neither an oversized page nor a negative starting point is a page of results.

    If `limit` is not an integer within the inclusive range of 1 through 100, or `offset` is not an integer of zero or greater, the request is rejected with `ERR_PAGINATION_INVALID` (HTTP 400).

    Design: Corner/errors/pagination_bounds_are_rejected_at_both_ends
    """
    fixtures.set_clock(api, CLOCK)
    validate_success(
        api.create_lease(factories.minimal_lease_payload(), fixtures.LAND_ADMIN), 201
    )

    validate_error(
        api.list_leases(fixtures.LAND_ADMIN, params={"limit": 101, "offset": 0}),
        "ERR_PAGINATION_INVALID",
        400,
    )
    validate_error(
        api.list_leases(fixtures.LAND_ADMIN, params={"limit": 20, "offset": -1}),
        "ERR_PAGINATION_INVALID",
        400,
    )

    _, meta = validate_paginated(
        api.list_leases(fixtures.LAND_ADMIN, params={"limit": 100, "offset": 0})
    )
    assert meta["total_count"] == 1


def test_each_natural_key_in_the_land_and_billing_records_refuses_a_second_holder(api):
    """Lease numbers, API numbers, unit membership and production months are all one-of-a-kind.

    The lease number is printed on the instrument and must be unique across the whole inventory, between 1 and 32 characters long; a collision is rejected with `ERR_DUPLICATE_LEASE_NUMBER`.
    The `production_month` must be unique for the well across every revenue record, else `ERR_DUPLICATE_PRODUCTION_MONTH` with status 409.

    Design: Corner/errors/duplicate_natural_keys_are_rejected_on_every_uniqueness_rule
    """
    context = fixtures.setup_pooled_producing_well(api, clock=CLOCK)
    revenue = fixtures.book_revenue(
        api, context["well_id"], "2026-05", 4_000_000, 8000.0, "2026-06-15"
    )

    validate_error(
        api.create_lease(
            factories.minimal_lease_payload(
                lease_number="L-001",
                lessor_name="Duplicate Lessor",
                gross_acres=100.0,
                royalty_rate=0.2,
                primary_term_end_date="2029-01-31",
            ),
            fixtures.LAND_ADMIN,
        ),
        "ERR_DUPLICATE_LEASE_NUMBER",
        409,
    )
    validate_error(
        api.create_well(
            factories.create_well_payload(
                well_name="Sandstone 1H bis",
                api_number="42-123-45678",
                total_depth_ft=9000,
                omit_fields=["spud_date"],
            ),
            fixtures.LAND_ADMIN,
        ),
        "ERR_DUPLICATE_API_NUMBER",
        409,
    )
    # A duplicate commitment is only reachable while the target unit is still
    # forming, so the second holder is refused on a fresh well whose pooling
    # has not yet been effectuated.
    forming_well = validate_success(
        api.create_well(
            factories.create_well_payload(
                well_name="Sandstone 2H",
                api_number="42-123-99999",
                total_depth_ft=9200,
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )
    validate_success(
        api.create_lease_allocation(
            forming_well["id"],
            factories.lease_allocation_payload(context["lease1_id"], 40.0),
            fixtures.LAND_ADMIN,
        ),
        201,
    )
    validate_error(
        api.create_lease_allocation(
            forming_well["id"],
            factories.lease_allocation_payload(context["lease1_id"], 40.0),
            fixtures.LAND_ADMIN,
        ),
        "ERR_DUPLICATE_ALLOCATION",
        409,
    )
    validate_error(
        api.create_production_revenue(
            context["well_id"],
            factories.create_production_revenue_payload(
                production_month="2026-05",
                gross_revenue_cents=1_000_000,
                volume_units=2000.0,
                sale_date="2026-06-20",
            ),
            fixtures.JIB_ACCOUNTANT,
        ),
        "ERR_DUPLICATE_PRODUCTION_MONTH",
        409,
    )

    _, lease_meta = validate_paginated(api.list_leases(fixtures.LAND_ADMIN))
    assert lease_meta["total_count"] == 2
    _, well_meta = validate_paginated(api.list_wells(fixtures.LAND_ADMIN))
    # The pooled well plus the forming well; the duplicate API number was refused.
    assert well_meta["total_count"] == 2

    lease2 = validate_success(
        api.get_lease(context["lease2_id"], fixtures.LAND_ADMIN), 200
    )
    assert lease2["committed_acres_total"] == 160.00

    read_revenue = validate_success(
        api.get_production_revenue(revenue["id"], fixtures.JIB_ACCOUNTANT), 200
    )
    assert read_revenue["gross_revenue_cents"] == 4_000_000
    _, revenue_meta = validate_paginated(
        api.list_production_revenues(
            fixtures.JIB_ACCOUNTANT, params={"well_id": context["well_id"]}
        )
    )
    assert revenue_meta["total_count"] == 1


def test_the_operator_may_not_refuse_to_fund_the_operation_it_proposed(api):
    """An operator that could non-consent its own AFE would be billing its partners for nothing.

    And the operator may not non-consent its own operation: an election of `NON_CONSENT` submitted for the owner whose position on the well carries `is_operator` true is rejected with `ERR_OPERATOR_CANNOT_NON_CONSENT`.

    Design: Corner/errors/the_operator_cannot_file_a_non_consent_election_on_its_own_well
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

    validate_error(
        api.submit_afe_election(
            afe["id"],
            factories.afe_election_payload(context["operator_id"], "NON_CONSENT"),
            fixtures.LAND_ADMIN,
        ),
        "ERR_OPERATOR_CANNOT_NON_CONSENT",
        422,
    )

    _, meta = validate_paginated(
        api.list_afe_elections(fixtures.LAND_ADMIN, params={"afe_id": afe["id"]})
    )
    assert meta["total_count"] == 0

    operator_position = validate_success(
        api.get_well_interest(context["wi_operator_id"], fixtures.LAND_ADMIN), 200
    )
    assert operator_position["non_consent_flag"] is False

    validate_success(
        api.submit_afe_election(
            afe["id"],
            factories.afe_election_payload(context["operator_id"], "CONSENT"),
            fixtures.LAND_ADMIN,
        ),
        201,
    )


def test_an_operation_nobody_agreed_to_fund_cannot_be_closed_at_all(api):
    """With no operator of record and every partner refusing, there is no consenting set.

    If the consenting tally comes out at exactly 0.000000 the closure is rejected with `ERR_NO_CONSENTING_INTEREST`: there is no candidate consenting set and the operation has no one to fund it.

    Design: Corner/errors/closing_elections_with_an_empty_consenting_set_is_rejected
    """
    fixtures.set_clock(api, CLOCK)
    well = _bare_well(api, well_name="Sandstone 4H", api_number="42-123-45684")
    partner_a = _owner(api, "Delta Partners LP", "delta@example.com", 10_000_000)
    partner_b = _owner(api, "Epsilon Resources Inc", "epsilon@example.com", 10_000_000)
    position_a = fixtures.add_interest(
        api, well["id"], partner_a["id"], 0.5, 0.4, is_operator=False
    )
    position_b = fixtures.add_interest(
        api, well["id"], partner_b["id"], 0.5, 0.4, is_operator=False
    )
    afe = fixtures.raise_afe(
        api,
        well["id"],
        afe_number="AFE-003",
        operation_type="DRILL",
        estimated_cost_cents=5_000_000,
        cost_class="CAPITAL",
        election_deadline_date="2026-08-31",
        non_consent_penalty_multiple=3.0,
        minimum_consent_pct=0.5,
    )
    fixtures.submit_election(api, afe["id"], partner_a["id"], "NON_CONSENT")
    fixtures.submit_election(api, afe["id"], partner_b["id"], "NON_CONSENT")

    validate_error(
        api.close_afe_elections(
            afe["id"], factories.election_closure_payload(), fixtures.LAND_ADMIN
        ),
        "ERR_NO_CONSENTING_INTEREST",
        422,
    )

    read_afe = validate_success(api.get_afe(afe["id"], fixtures.LAND_ADMIN), 200)
    assert read_afe["afe_status"] == "ELECTIONS_OPEN"
    assert read_afe["elections_closed_at"] is None

    for position in (position_a, position_b):
        row = validate_success(
            api.get_well_interest(position["id"], fixtures.LAND_ADMIN), 200
        )
        assert row["non_consent_flag"] is False

    read_well = validate_success(api.get_well(well["id"], fixtures.LAND_ADMIN), 200)
    assert read_well["consent_working_interest_pct"] == 1.000000


def test_a_partner_may_contest_its_own_share_and_no_more(api):
    """Contesting the whole well's bill is not a right any single partner holds.

    And `disputed_amount_cents` must not exceed the filing owner's own `total_billed_cents` on that statement's line items, else `ERR_DISPUTE_AMOUNT_EXCEEDS_BILL` — a partner may contest its own share, not the whole well's.

    Design: Corner/errors/a_dispute_larger_than_the_owners_line_item_is_rejected
    """
    context = fixtures.setup_issued_june_statement(api, clock=CLOCK)

    validate_error(
        api.file_dispute(
            context["statement_id"],
            factories.file_dispute_payload(
                context["partner_a_id"],
                900_000,
                basis_note="Disputes more than its own share",
            ),
            context["partner_a_headers"],
        ),
        "ERR_DISPUTE_AMOUNT_EXCEEDS_BILL",
        422,
    )

    statement = validate_success(
        api.get_jib_statement(context["statement_id"], fixtures.JIB_ACCOUNTANT), 200
    )
    assert statement["statement_status"] == "ISSUED"

    _, meta = validate_paginated(
        api.list_disputes(
            fixtures.JIB_ACCOUNTANT, params={"statement_id": context["statement_id"]}
        )
    )
    assert meta["total_count"] == 0

    validate_success(
        api.file_dispute(
            context["statement_id"],
            factories.file_dispute_payload(
                context["partner_a_id"],
                880_200,
                basis_note="Disputes exactly its own share",
            ),
            context["partner_a_headers"],
        ),
        201,
    )


def test_the_logical_clock_refuses_to_run_backwards(api):
    """Deadlines computed against a clock that can retreat are not deadlines.

    The clock is monotonic: if the supplied `current_utc` is earlier than the clock's present value, the request is rejected with `ERR_CLOCK_MOVED_BACKWARD` (HTTP 422).
    Setting the clock is purely a time operation — it mutates no entity, and it does not itself evaluate any deadline, expiry or obligation.

    Design: Corner/errors/setting_the_clock_backwards_is_rejected
    """
    fixtures.set_clock(api, CLOCK)

    validate_error(
        api.set_current_utc(
            factories.set_clock_payload("2026-08-09T00:00:00Z"), fixtures.LAND_ADMIN
        ),
        "ERR_CLOCK_MOVED_BACKWARD",
        422,
    )

    validate_success(
        api.set_current_utc(
            factories.set_clock_payload("2026-08-10T00:00:00Z"), fixtures.LAND_ADMIN
        ),
        200,
    )
    validate_success(
        api.set_current_utc(
            factories.set_clock_payload("2026-08-11T00:00:00Z"), fixtures.LAND_ADMIN
        ),
        200,
    )


def test_a_bill_over_a_period_with_no_charges_in_it_cannot_be_issued(api):
    """A statement carrying nothing is not a bill the partners can be asked to pay.

    And the cost pool selected by the statement's basis and period must not be empty, else `ERR_NO_BILLABLE_COSTS`.
    Those checks fire in the stated order, so a draft on an unpooled well reports the pooling failure rather than the empty pool.

    Design: Corner/errors/issuing_a_statement_whose_period_holds_no_costs_is_rejected
    """
    context = fixtures.setup_pooled_producing_well(api, clock=CLOCK)
    fixtures.book_june_cost_history(api, context["well_id"])
    statement = fixtures.open_statement(
        api,
        context["well_id"],
        statement_number="JIB-2026-05",
        billing_period_start="2026-05-01",
        billing_period_end="2026-05-31",
    )

    validate_error(
        api.issue_jib_statement(statement["id"], fixtures.JIB_ACCOUNTANT),
        "ERR_NO_BILLABLE_COSTS",
        422,
    )

    read_statement = validate_success(
        api.get_jib_statement(statement["id"], fixtures.JIB_ACCOUNTANT), 200
    )
    assert read_statement["statement_status"] == "DRAFT"
    assert read_statement["issued_at"] is None
    # No direct charges fall in May, and overhead is clamped up to its
    # 25000-cent floor, so the provisional total is the floor alone.
    assert read_statement["overhead_cents"] == 25_000
    assert read_statement["direct_cost_cents"] == 0
    assert read_statement["total_billed_cents"] == 25_000

    _, meta = validate_paginated(
        api.list_jib_statement_line_items(statement["id"], fixtures.JIB_ACCOUNTANT)
    )
    assert meta["total_count"] == 0

    well = validate_success(api.get_well(context["well_id"], fixtures.LAND_ADMIN), 200)
    assert well["billed_to_date_cents"] == 0
