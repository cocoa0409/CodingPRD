"""Operations that move value around and must leave the totals exactly where they were."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories, fixtures

CLOCK_AUGUST = "2026-08-05T00:00:00Z"


def test_a_conveyance_of_an_entire_position_leaves_both_interest_totals_untouched(api):
    """The seller leaves the well outright and the buyer arrives holding exactly what was sold.

    The one exception is a **full** conveyance: when the assignor's `working_interest_pct` less `transfer_wi_pct` would be exactly 0, its position becomes `TERMINATED` rather than `SUPERSEDED` and **no** replacement row is created — and its `non_consent_recoverable_balance_cents` is carried onto the grantee's new `ACTIVE` row, conserved and never dropped, because an outstanding non-consent receivable runs with the interest rather than with the person.
    Two conserved quantities are the point of all this bookkeeping, and both hold identically on both branches: the sum of `working_interest_pct` over the well's `ACTIVE` positions remains exactly 1.000000, and the sum of `net_revenue_interest_pct` over those positions is unchanged by the conveyance.

    Design: Difficulty/compensating_invariant/full_conveyance_conserves_both_interest_totals_on_the_well
    """
    context = fixtures.setup_assignment_notice(
        api,
        clock=CLOCK_AUGUST,
        assignor="partner_b_id",
        assignee="partner_c_id",
        transfer_wi_pct=0.2,
        transfer_nri_pct=0.15,
        sale_price_cents=9_000_000,
        notice_date="2026-08-01",
        effective_date="2026-08-05",
    )
    well_id = context["well_id"]
    transfer_id = context["transfer_id"]

    assert context["transfer"]["ppr_eligible_count"] == 2
    assert context["transfer"]["bond_check_required_cents"] == 3_725_000

    before = fixtures.active_interests(api, well_id)
    assert len(before) == 3
    assert sum(row["working_interest_pct"] for row in before) == 1.000000
    assert sum(row["net_revenue_interest_pct"] for row in before) == 0.802500

    fixtures.submit_ppr(api, transfer_id, context["operator_headers"], "WAIVE")
    waived = fixtures.submit_ppr(
        api, transfer_id, context["partner_a_headers"], "WAIVE"
    )
    assert waived["ppr_waiver_count"] == 2
    assert waived["transfer_status"] == "PPR_WAIVED"

    closed = validate_success(
        api.close_assignment_transfer(
            transfer_id,
            factories.transfer_closing_payload("2026-08-05"),
            fixtures.LAND_ADMIN,
        ),
        200,
    )
    assert closed["transfer_status"] == "CLOSED"
    assert closed["effective_date"] == "2026-08-05"

    after = fixtures.active_interests(api, well_id)
    assert len(after) == 3
    assert sum(row["working_interest_pct"] for row in after) == 1.000000
    assert sum(row["net_revenue_interest_pct"] for row in after) == 0.802500

    seller_row = validate_success(
        api.get_well_interest(context["wi_partner_b_id"], fixtures.LAND_ADMIN), 200
    )
    assert seller_row["interest_status"] == "TERMINATED"
    assert seller_row["effective_to"] == "2026-08-05"

    rows, meta = validate_paginated(
        api.list_well_interests(
            fixtures.LAND_ADMIN,
            params={
                "well_id": well_id,
                "owner_id": context["partner_b_id"],
                "interest_status": "ACTIVE",
            },
        )
    )
    assert meta["total_count"] == 0

    buyer_rows = [
        row for row in after if row["owner_id"] == context["partner_c_id"]
    ]
    assert len(buyer_rows) == 1
    buyer = buyer_rows[0]
    assert buyer["working_interest_pct"] == 0.200000
    assert buyer["net_revenue_interest_pct"] == 0.150000
    assert buyer["effective_from"] == "2026-08-05"
    assert buyer["is_operator"] is False
    assert buyer["preferential_right"] is False

    untouched = {row["owner_id"]: row for row in after}
    assert untouched[context["operator_id"]]["working_interest_pct"] == 0.500000
    assert untouched[context["partner_a_id"]]["working_interest_pct"] == 0.300000

    seller = validate_success(
        api.get_interest_owner(context["partner_b_id"], fixtures.LAND_ADMIN), 200
    )
    buyer_owner = validate_success(
        api.get_interest_owner(context["partner_c_id"], fixtures.LAND_ADMIN), 200
    )
    assert seller["required_bond_cents"] == 0
    assert buyer_owner["required_bond_cents"] == 3_725_000

    well = validate_success(api.get_well(well_id, fixtures.LAND_ADMIN), 200)
    assert well["consent_working_interest_pct"] == 1.000000


def test_replacing_a_bill_charges_the_same_amount_once_and_not_twice(api):
    """A revision reverses the original before the replacement re-adds it, so nothing doubles.

    The ledger consequences depend on where the addressed statement was: revising an `ISSUED` statement decreases the well's `billed_to_date_cents` by its `total_billed_cents`, increments the well's `version` by 1, and applies a compensating reversal to every owner it had charged — for each line item with a `penalty_accrued_cents` above zero, that owner's `non_consent_recoverable_balance_cents` decreases by that line item's `non_consent_withheld_cents` plus its `penalty_accrued_cents`, exactly undoing what issuance added.
    The addressed statement moves to `ADJUSTED` and a fresh statement is created in `DRAFT` with `superseded_statement_id` pointing at it and the same billing period, so the replacement must be issued in its own right.

    Design: Difficulty/compensating_invariant/statement_revision_reverses_the_billed_ledger_without_drift
    """
    context = fixtures.setup_issued_non_consent_statement(
        api, clock="2026-08-10T00:00:00Z"
    )
    well_id = context["well_id"]
    statement_id = context["statement_id"]

    original = validate_success(
        api.get_jib_statement(statement_id, fixtures.JIB_ACCOUNTANT), 200
    )
    assert original["statement_status"] == "ISSUED"
    assert original["total_billed_cents"] == 2_934_000
    assert (
        validate_success(api.get_well(well_id, fixtures.LAND_ADMIN), 200)[
            "billed_to_date_cents"
        ]
        == 2_934_000
    )
    carried = validate_success(
        api.get_well_interest(context["wi_partner_b_id"], fixtures.LAND_ADMIN), 200
    )
    assert carried["non_consent_recoverable_balance_cents"] == 1_600_000

    revision = validate_success(
        api.revise_jib_statement(
            statement_id,
            factories.statement_revision_payload(
                "JIB-2026-06R1", original["version"]
            ),
            fixtures.JIB_ACCOUNTANT,
        ),
        201,
    )

    reversed_original = validate_success(
        api.get_jib_statement(statement_id, fixtures.JIB_ACCOUNTANT), 200
    )
    assert reversed_original["statement_status"] == "ADJUSTED"
    assert (
        validate_success(api.get_well(well_id, fixtures.LAND_ADMIN), 200)[
            "billed_to_date_cents"
        ]
        == 0
    )
    carried = validate_success(
        api.get_well_interest(context["wi_partner_b_id"], fixtures.LAND_ADMIN), 200
    )
    assert carried["non_consent_recoverable_balance_cents"] == 0

    assert revision["statement_status"] == "DRAFT"
    assert revision["superseded_statement_id"] == statement_id
    assert revision["billing_period_start"] == "2026-06-01"
    assert revision["billing_period_end"] == "2026-06-30"
    assert revision["cost_basis"] == "ACCRUAL"
    assert revision["overhead_rate_class"] == "PERCENTAGE_BASIS"
    assert revision["total_billed_cents"] == 2_934_000
    assert (
        validate_success(api.get_well(well_id, fixtures.LAND_ADMIN), 200)[
            "billed_to_date_cents"
        ]
        == 0
    )

    rows, meta = validate_paginated(
        api.list_jib_statement_line_items(statement_id, fixtures.JIB_ACCOUNTANT)
    )
    assert meta["total_count"] == 3

    reissued = validate_success(
        api.issue_jib_statement(revision["id"], fixtures.JIB_ACCOUNTANT), 200
    )
    assert reissued["statement_status"] == "ISSUED"

    well = validate_success(api.get_well(well_id, fixtures.LAND_ADMIN), 200)
    assert well["billed_to_date_cents"] == 2_934_000

    carried = validate_success(
        api.get_well_interest(context["wi_partner_b_id"], fixtures.LAND_ADMIN), 200
    )
    assert carried["non_consent_recoverable_balance_cents"] == 1_600_000

    refused_line = fixtures.line_item_for(
        api, revision["id"], context["partner_b_id"]
    )
    assert refused_line["non_consent_withheld_cents"] == 400_000
    assert refused_line["penalty_accrued_cents"] == 1_200_000
    assert refused_line["total_billed_cents"] == 167_657

    assert (
        validate_success(
            api.get_jib_statement(statement_id, fixtures.JIB_ACCOUNTANT), 200
        )["statement_status"]
        == "ADJUSTED"
    )
