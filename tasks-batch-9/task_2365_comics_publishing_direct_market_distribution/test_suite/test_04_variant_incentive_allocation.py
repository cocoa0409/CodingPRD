"""Variant incentive allocation: ratio floors, exclusive eligibility and order compensation."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_allocation_entries,
    assert_invoice_figures,
    assert_issue_unit_ledgers,
    assert_retailer_ledgers,
    factories,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

FOUR_COVER_SPECS = fixtures.DEFAULT_COVER_SPECS + (fixtures.EXCLUSIVE_COVER_SPEC,)

FOC_INSTANT = "2026-09-23T00:00:00Z"


def test_eligible_retailer_earns_the_nested_minimum_of_request_floor_and_cap():
    """A retailer at the 10,000-unit gate earns min(5 requested, 2 by 1:50, 2 by cap) copies.

    PRD: "An eligible retailer earns the smaller of two figures: the `exclusive_variant_qty` it requested, and its `standard_qty` divided by 50 and floored to a whole copy."

    Design: Difficulty/combinatorial_formula/variant_incentive_allocation_nested_min_with_eligibility_branch_mode_a
    """
    state = fixtures.setup_solicited_issue_in_scripting(cover_specs=FOUR_COVER_SPECS)
    issue_id = state["issue"]["id"]
    covers = state["covers"]

    eligible = fixtures.open_retailer(
        name="Vault Variants", opening_units_ytd=10000
    )
    order = fixtures.draft_and_submit_order(
        eligible["id"], issue_id, standard_qty=100, exclusive_variant_qty=5
    )

    fixtures.set_clock(FOC_INSTANT)
    locked_issue = validate_success(
        api_client.foc_lock_issue(issue_id, TEST_USERS["sales_director_headers"])
    )
    assert locked_issue["commercial_status"] == "FOC_LOCKED"

    locked_order = fixtures.read_order(order["id"])
    assert locked_order["status"] == "FOC_LOCKED"
    # Ratio covers walk first by ascending ratio, then the exclusive; standard earns nothing.
    assert_allocation_entries(
        locked_order,
        [
            (covers["B"]["id"], 10),
            (covers["C"]["id"], 4),
            (covers["D"]["id"], 2),
        ],
    )
    assert locked_order["total_units"] == 116


def test_retailer_one_unit_below_the_exclusive_gate_earns_no_exclusive_copies():
    """9,999 pre-lock units earn nothing from the exclusive cover the identical order shape earns.

    PRD: "A `RETAILER_EXCLUSIVE` cover earns nothing at all unless the ordering retailer is eligible, and eligibility means the retailer's `cumulative_units_ytd` — measured as it stands before this cut-off adds this order's own units — is at least 10,000 units."

    Design: Difficulty/combinatorial_formula/variant_incentive_allocation_nested_min_with_eligibility_branch_mode_a
    """
    state = fixtures.setup_locked_order_book(
        cover_specs=FOUR_COVER_SPECS,
        retailer_overrides={"name": "Vault Variants", "opening_units_ytd": 10000},
        order_overrides={"standard_qty": 100, "exclusive_variant_qty": 5},
        extra_orders=[
            (
                {"name": "Longbox Ltd", "opening_units_ytd": 9999},
                {"standard_qty": 100, "exclusive_variant_qty": 5},
            )
        ],
    )
    covers = state["covers"]
    eligible_order, short_order = state["orders"]

    assert_allocation_entries(
        short_order,
        [
            (covers["B"]["id"], 10),
            (covers["C"]["id"], 4),
        ],
    )
    earned_ids = [
        entry["variant_cover_id"] for entry in short_order["earned_variant_allocations"]
    ]
    assert covers["D"]["id"] not in earned_ids
    assert short_order["total_units"] == 114
    assert eligible_order["total_units"] == 116
    # One unit of pre-lock history is worth the two capped exclusive copies.
    assert eligible_order["total_units"] - short_order["total_units"] == 2


def test_the_cut_off_lock_rolls_both_variant_order_books_into_the_core_tier():
    """The lock refreshes each retailer's units and tier, and the issue's ordered total.

    PRD: "Downstream in the same request, each affected retailer's `cumulative_units_ytd` is refreshed and its `discount_tier` re-derived, and the issue's `total_ordered_units` is refreshed."

    Design: Difficulty/combinatorial_formula/variant_incentive_allocation_nested_min_with_eligibility_branch_mode_a
    """
    state = fixtures.setup_locked_order_book(
        cover_specs=FOUR_COVER_SPECS,
        retailer_overrides={"name": "Vault Variants", "opening_units_ytd": 10000},
        order_overrides={"standard_qty": 100, "exclusive_variant_qty": 5},
        extra_orders=[
            (
                {"name": "Longbox Ltd", "opening_units_ytd": 9999},
                {"standard_qty": 100, "exclusive_variant_qty": 5},
            )
        ],
    )
    eligible, short = state["retailers"]

    assert_retailer_ledgers(
        fixtures.read_retailer(eligible["id"]),
        cumulative_units_ytd=10116,
        discount_tier="CORE",
    )
    assert_retailer_ledgers(
        fixtures.read_retailer(short["id"]),
        cumulative_units_ytd=10113,
        discount_tier="CORE",
    )
    assert_issue_unit_ledgers(
        fixtures.read_issue(state["issue"]["id"]), total_ordered_units=230
    )


def test_ninety_nine_standard_copies_floor_both_ratio_covers_down_a_step():
    """99 copies earn 9 of the 1-in-10 cover and 3 of the 1-in-25, for 111 units.

    PRD: "A `RATIO_INCENTIVE` cover earns the order's `standard_qty` divided by that cover's `incentive_ratio`, with the division floored to a whole copy, and the result then capped at the cover's `allocation_cap` when one is present."

    Design: Difficulty/boundary_precision_check/incentive_ratio_floor_boundary_99_versus_100_standard_copies
    """
    state = fixtures.setup_locked_order_book(
        retailer_overrides={"name": "Edge Case Comics"},
        order_overrides={"standard_qty": 99},
    )
    covers = state["covers"]
    order = state["orders"][0]

    # 99/10 floors to 9 and 99/25 floors to 3; the cap of 4 never binds here.
    assert_allocation_entries(
        order,
        [
            (covers["B"]["id"], 9),
            (covers["C"]["id"], 3),
        ],
    )
    assert order["total_units"] == 111


def test_one_hundred_standard_copies_earn_three_more_variants_than_ninety_nine():
    """A single extra standard copy steps both ratio floors up, adding three units.

    PRD: "Because the division floors, a ratio only pays on exact multiples: 60 standard copies earn 6 copies of a 1-in-10 cover, while 9 standard copies earn none."

    Design: Difficulty/boundary_precision_check/incentive_ratio_floor_boundary_99_versus_100_standard_copies
    """
    state = fixtures.setup_locked_order_book(
        retailer_overrides={"name": "Edge Case Comics"},
        order_overrides={"standard_qty": 99},
        extra_orders=[({"name": "Round Number Books"}, {"standard_qty": 100})],
    )
    covers = state["covers"]
    order_99, order_100 = state["orders"]

    assert_allocation_entries(
        order_100,
        [
            (covers["B"]["id"], 10),
            (covers["C"]["id"], 4),
        ],
    )
    assert order_99["total_units"] == 111
    assert order_100["total_units"] == 114
    assert order_100["total_units"] - order_99["total_units"] == 3


def test_neither_boundary_order_book_leaves_the_entry_discount_tier():
    """111 and 114 cumulative units both sit below the 2,500-unit `BASIC` threshold.

    PRD: "Volume earns discount, and the tier is a pure function of `cumulative_units_ytd` with inclusive thresholds: from 25,000 cumulative units upwards the account is `PREMIER`; from 10,000 up to but not reaching 25,000 it is `CORE`; from 2,500 up to but not reaching 10,000 it is `BASIC`; and below 2,500 it is `ENTRY`."

    Design: Difficulty/boundary_precision_check/incentive_ratio_floor_boundary_99_versus_100_standard_copies
    """
    state = fixtures.setup_locked_order_book(
        retailer_overrides={"name": "Edge Case Comics"},
        order_overrides={"standard_qty": 99},
        extra_orders=[({"name": "Round Number Books"}, {"standard_qty": 100})],
    )
    retailer_99, retailer_100 = state["retailers"]

    assert_retailer_ledgers(
        fixtures.read_retailer(retailer_99["id"]),
        cumulative_units_ytd=111,
        discount_tier="ENTRY",
    )
    assert_retailer_ledgers(
        fixtures.read_retailer(retailer_100["id"]),
        cumulative_units_ytd=114,
        discount_tier="ENTRY",
    )
    assert_issue_unit_ledgers(
        fixtures.read_issue(state["issue"]["id"]), total_ordered_units=225
    )


def _setup_invoiced_and_locked_pair() -> dict:
    """Two locked orders on one issue, the first of them invoiced at `BASIC`."""
    state = fixtures.setup_locked_order_book(
        retailer_overrides={"name": "Panel Palace", "opening_units_ytd": 2440},
        order_overrides={"standard_qty": 100},
        extra_orders=[
            ({"name": "Splash Page", "opening_units_ytd": 0}, {"standard_qty": 200})
        ],
    )
    state["invoiced_order"] = fixtures.invoice_order(state["orders"][0]["id"])
    return state


def test_cancelling_an_invoiced_order_restores_the_opening_units_and_zero_balance():
    """The cancel recomputes 2554 units back to 2440, demotes `BASIC` to `ENTRY` and clears 26453.

    PRD: "Such a cancellation captures the `reason`, then refreshes the retailer's `cumulative_units_ytd` (the order's units leave the count), re-derives the retailer's `discount_tier` from that refreshed figure — which may demote the account — refreshes the retailer's `open_balance_cents` (the invoice, if there was one, leaves the balance), and refreshes the issue's `total_ordered_units`."

    Design: Difficulty/compensating_invariant/order_cancel_restores_the_retailer_units_and_balance_ledger_exactly
    """
    state = _setup_invoiced_and_locked_pair()
    retailer_a = state["retailers"][0]
    issue_id = state["issue"]["id"]

    # 100 x 399 -> 21945, 10 x 399 -> 2195, 4 x 599 -> 1318 at the 45% BASIC discount.
    assert_invoice_figures(
        state["invoiced_order"],
        discount_tier_applied="BASIC",
        merchandise_net_cents=25458,
        handling_fee_cents=995,
        invoice_total_cents=26453,
    )
    assert_retailer_ledgers(
        fixtures.read_retailer(retailer_a["id"]),
        cumulative_units_ytd=2554,
        open_balance_cents=26453,
        discount_tier="BASIC",
    )
    assert_issue_unit_ledgers(fixtures.read_issue(issue_id), total_ordered_units=338)

    cancelled = validate_success(
        api_client.cancel_retailer_order(
            state["orders"][0]["id"],
            factories.order_cancel_payload(reason="store closed"),
            TEST_USERS["sales_director_headers"],
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "store closed"

    assert_retailer_ledgers(
        fixtures.read_retailer(retailer_a["id"]),
        cumulative_units_ytd=2440,
        open_balance_cents=0,
        discount_tier="ENTRY",
    )
    assert_issue_unit_ledgers(fixtures.read_issue(issue_id), total_ordered_units=224)


def test_the_second_retailers_locked_order_survives_the_cancellation_untouched():
    """Recomputing the ledgers leaves the still-locked 224-unit order and its account alone.

    PRD: "A large part of this system's state is not written by clients at all but derived from child rows, and the derivation is always a **full recompute over the qualifying child set**, never an incremental delta."

    Design: Difficulty/compensating_invariant/order_cancel_restores_the_retailer_units_and_balance_ledger_exactly
    """
    state = _setup_invoiced_and_locked_pair()
    retailer_b = state["retailers"][1]
    order_b = state["orders"][1]

    fixtures.cancel_order(state["orders"][0]["id"], reason="store closed")

    surviving = fixtures.read_order(order_b["id"])
    assert surviving["status"] == "FOC_LOCKED"
    assert surviving["total_units"] == 224
    assert_retailer_ledgers(
        fixtures.read_retailer(retailer_b["id"]),
        cumulative_units_ytd=224,
        open_balance_cents=0,
        discount_tier="ENTRY",
    )


def test_the_cancelled_order_keeps_its_frozen_units_and_invoice_total():
    """The row that left every ledger still carries its 114 units and its 26453 invoice.

    PRD: "The computed invoice figures stay on the cancelled row for the audit trail even though they no longer participate in any ledger."

    Design: Difficulty/compensating_invariant/order_cancel_restores_the_retailer_units_and_balance_ledger_exactly
    """
    state = _setup_invoiced_and_locked_pair()
    covers = state["covers"]

    fixtures.cancel_order(state["orders"][0]["id"], reason="store closed")

    stored = fixtures.read_order(state["orders"][0]["id"])
    assert stored["total_units"] == 114
    assert_allocation_entries(
        stored,
        [
            (covers["B"]["id"], 10),
            (covers["C"]["id"], 4),
        ],
    )
    assert_invoice_figures(
        stored,
        discount_tier_applied="BASIC",
        merchandise_net_cents=25458,
        handling_fee_cents=995,
        invoice_total_cents=26453,
    )
    assert_retailer_ledgers(
        fixtures.read_retailer(state["retailers"][0]["id"]),
        cumulative_units_ytd=2440,
        open_balance_cents=0,
    )


def test_a_second_cancellation_of_the_same_order_is_refused_and_changes_nothing():
    """`CANCELLED` is terminal, so the compensation cannot be applied a second time.

    PRD: "The target resource is in a state from which the requested transition exists, including terminal-state lockdown and rejection of a repeated trigger, otherwise `ERR_INVALID_STATE` (409)."

    Design: Difficulty/compensating_invariant/order_cancel_restores_the_retailer_units_and_balance_ledger_exactly
    """
    state = _setup_invoiced_and_locked_pair()
    order_id = state["orders"][0]["id"]

    fixtures.cancel_order(order_id, reason="store closed")

    response = api_client.cancel_retailer_order(
        order_id,
        factories.order_cancel_payload(reason="store closed again"),
        TEST_USERS["sales_director_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    assert fixtures.read_order(order_id)["cancel_reason"] == "store closed"
    assert_retailer_ledgers(
        fixtures.read_retailer(state["retailers"][0]["id"]),
        cumulative_units_ytd=2440,
        open_balance_cents=0,
        discount_tier="ENTRY",
    )
    assert_issue_unit_ledgers(
        fixtures.read_issue(state["issue"]["id"]), total_ordered_units=224
    )
