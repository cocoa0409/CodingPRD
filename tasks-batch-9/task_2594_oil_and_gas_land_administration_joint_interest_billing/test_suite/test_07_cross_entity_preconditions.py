"""Writes that are refused for the state of a neighbouring record, not their own."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories, fixtures


def test_a_draft_cannot_be_issued_once_the_unit_underneath_it_has_terminated(api):
    """The same draft that was billable in July is refused in October because the pooled unit died.

    The well's `pooling_status` must be `POOLED_EFFECTIVE`, because a bill can only be raised against a unit that is in force, else `ERR_WELL_NOT_POOLED`.
    Those checks fire in the stated order, so a draft on an unpooled well reports the pooling failure rather than the empty pool.

    Design: Difficulty/cross_entity_state_dependency/statement_issuance_depends_on_the_wells_pooling_status
    """
    context = fixtures.setup_pooled_producing_well(api, clock="2026-08-10T00:00:00Z")
    well_id = context["well_id"]

    fixtures.book_residual_cost_history(api, well_id)
    fixtures.book_cost(
        api, well_id, "LEASE_OPERATING", "OPERATING", 200_000, "2026-05-10", "2026-05-11"
    )

    june = fixtures.open_statement(api, well_id, statement_number="JIB-2026-06")
    issued_june = fixtures.issue_statement(api, june["id"])
    assert issued_june["total_billed_cents"] == 1_153_008

    may = fixtures.open_statement(
        api,
        well_id,
        statement_number="JIB-2026-05",
        billing_period_start="2026-05-01",
        billing_period_end="2026-05-31",
    )
    assert may["statement_status"] == "DRAFT"
    assert may["total_billed_cents"] == 225_000

    fixtures.change_status(api, well_id, "SHUT_IN", "2026-07-10")
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    fixtures.run_obligation_pass(api)

    lease = validate_success(
        api.get_lease(context["lease1_id"], fixtures.LAND_ADMIN), 200
    )
    assert lease["tenure_status"] == "EXPIRED"
    well = validate_success(api.get_well(well_id, fixtures.LAND_ADMIN), 200)
    assert well["pooling_status"] == "POOLED_TERMINATED"
    assert well["well_status"] == "SHUT_IN"

    validate_error(
        api.issue_jib_statement(may["id"], fixtures.JIB_ACCOUNTANT),
        "ERR_WELL_NOT_POOLED",
        409,
    )

    refused = validate_success(
        api.get_jib_statement(may["id"], fixtures.JIB_ACCOUNTANT), 200
    )
    assert refused["statement_status"] == "DRAFT"
    assert refused["issued_at"] is None
    assert refused["payment_due_date"] is None
    assert fixtures.get_line_items(api, may["id"]) == []

    well = validate_success(api.get_well(well_id, fixtures.LAND_ADMIN), 200)
    assert well["billed_to_date_cents"] == 1_153_008

    settled_june = validate_success(
        api.get_jib_statement(june["id"], fixtures.JIB_ACCOUNTANT), 200
    )
    assert settled_june["statement_status"] == "SETTLED"


def test_acreage_cannot_be_committed_out_of_a_lease_that_has_expired(api):
    """An expired tract is refused for a brand-new unit while a live tract joins it.

    The lease must not have expired — an allocation against a lease whose `tenure_status` is `EXPIRED` is rejected with `ERR_LEASE_NOT_ACTIVE`.
    Each allocation is written with `allocation_status` set to `COMMITTED` and `withdrawn_reason` null, and the first commitment on a well moves its `pooling_status` from `UNPOOLED` to `POOLED_FORMING`.

    Design: Difficulty/cross_entity_state_dependency/allocation_commitment_depends_on_the_leases_tenure_status
    """
    context = fixtures.setup_pooled_producing_well(api, clock="2026-08-10T00:00:00Z")

    lease3 = fixtures.create_lease(
        api,
        lease_number="L-003",
        lessor_name="Zeta Minerals",
        gross_acres=200.0,
        royalty_rate=0.2,
        primary_term_end_date="2026-09-30",
        extension_option_months=12,
        extension_bonus_per_acre_cents=10_000,
        shut_in_royalty_per_acre_cents=450,
        continuous_dev_window_days=180,
    )

    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    run = fixtures.run_obligation_pass(api)
    assert run["leases_expired"] == 1
    assert run["allocations_withdrawn"] == 0

    well2 = fixtures.create_well(
        api,
        well_name="Limestone 2H",
        api_number="42-123-99999",
        product_type="GAS",
        total_depth_ft=8000,
        spud_date="2026-09-01",
    )

    assert (
        validate_success(api.get_lease(lease3["id"], fixtures.LAND_ADMIN), 200)[
            "tenure_status"
        ]
        == "EXPIRED"
    )
    assert (
        validate_success(api.get_lease(context["lease2_id"], fixtures.LAND_ADMIN), 200)[
            "tenure_status"
        ]
        == "PRIMARY_TERM"
    )
    assert (
        validate_success(api.get_lease(context["lease1_id"], fixtures.LAND_ADMIN), 200)[
            "tenure_status"
        ]
        == "HELD_BY_PRODUCTION"
    )
    assert (
        validate_success(api.get_well(well2["id"], fixtures.LAND_ADMIN), 200)[
            "pooling_status"
        ]
        == "UNPOOLED"
    )

    validate_error(
        api.create_lease_allocation(
            well2["id"],
            factories.lease_allocation_payload(lease3["id"], 150.0),
            fixtures.LAND_ADMIN,
        ),
        "ERR_LEASE_NOT_ACTIVE",
        409,
    )

    assert (
        validate_success(api.get_well(well2["id"], fixtures.LAND_ADMIN), 200)[
            "pooling_status"
        ]
        == "UNPOOLED"
    )
    rows, meta = validate_paginated(
        api.list_lease_allocations(fixtures.LAND_ADMIN, params={"well_id": well2["id"]})
    )
    assert meta["total_count"] == 0
    assert (
        validate_success(api.get_lease(lease3["id"], fixtures.LAND_ADMIN), 200)[
            "committed_acres_total"
        ]
        == 0.00
    )

    allocation = validate_success(
        api.create_lease_allocation(
            well2["id"],
            factories.lease_allocation_payload(context["lease2_id"], 100.0),
            fixtures.LAND_ADMIN,
        ),
        201,
    )
    assert allocation["allocation_status"] == "COMMITTED"
    assert allocation["allocation_factor"] == 1.000000

    well = validate_success(api.get_well(well2["id"], fixtures.LAND_ADMIN), 200)
    assert well["pooling_status"] == "POOLED_FORMING"
    assert well["allocation_factor_total"] == 1.000000

    lease2 = validate_success(
        api.get_lease(context["lease2_id"], fixtures.LAND_ADMIN), 200
    )
    assert lease2["committed_acres_total"] == 260.00
    assert lease2["held_acres"] == 260.00


def test_a_well_cannot_be_plugged_while_an_issued_bill_is_still_on_the_ledger(api):
    """Plugging waits for settlement even though every holder is fully bonded.

    First, no bill may be outstanding: if any statement on the well is still `ISSUED` or `DISPUTED`, the move is rejected with `ERR_UNSETTLED_STATEMENTS`, because a well cannot be abandoned while partners still owe or contest a charge.
    Either way `statement_status` becomes `SETTLED`, which remains inside `billed_to_date_cents`, and `SETTLED` is terminal.

    Design: Difficulty/cross_entity_state_dependency/plugging_depends_on_every_statement_being_off_the_billed_ledger
    """
    context = fixtures.setup_issued_residual_statement(
        api, clock="2026-08-10T00:00:00Z"
    )
    well_id = context["well_id"]
    statement_id = context["statement_id"]

    validate_success(
        api.update_owner_compliance(
            context["partner_b_id"],
            factories.compliance_update_payload(bond_posted_cents=4_000_000),
            fixtures.COMPLIANCE_OFFICER,
        ),
        200,
    )
    fixtures.change_status(api, well_id, "TEMPORARILY_ABANDONED", "2026-07-10")

    statement = validate_success(
        api.get_jib_statement(statement_id, fixtures.JIB_ACCOUNTANT), 200
    )
    assert statement["statement_status"] == "ISSUED"
    assert statement["total_billed_cents"] == 1_153_008
    assert (
        validate_success(api.get_well(well_id, fixtures.LAND_ADMIN), 200)["well_status"]
        == "TEMPORARILY_ABANDONED"
    )
    holder = validate_success(
        api.get_interest_owner(context["partner_b_id"], fixtures.LAND_ADMIN), 200
    )
    assert holder["required_bond_cents"] == 3_725_000
    assert holder["bond_posted_cents"] == 4_000_000

    validate_error(
        api.change_well_status(
            well_id,
            factories.well_status_change_payload(
                "PLUGGED", effective_date="2026-07-10"
            ),
            fixtures.LAND_ADMIN,
        ),
        "ERR_UNSETTLED_STATEMENTS",
        409,
    )
    assert (
        validate_success(api.get_well(well_id, fixtures.LAND_ADMIN), 200)["well_status"]
        == "TEMPORARILY_ABANDONED"
    )

    settled = validate_success(
        api.settle_jib_statement(
            statement_id,
            fixtures.JIB_ACCOUNTANT,
            factories.statement_settlement_payload("2026-07-10"),
        ),
        200,
    )
    assert settled["statement_status"] == "SETTLED"

    plugged = validate_success(
        api.change_well_status(
            well_id,
            factories.well_status_change_payload(
                "PLUGGED", effective_date="2026-07-10"
            ),
            fixtures.LAND_ADMIN,
        ),
        200,
    )
    assert plugged["well_status"] == "PLUGGED"
    assert plugged["plugging_liability_cents"] == 14_900_000
    assert plugged["billed_to_date_cents"] == 1_153_008
