"""Multi-factor money formulas: tier stacks, rounding order and fee band selection."""

from test_helpers import (
    ANALYST_ONE,
    ApiClient,
    ApiErrorId,
    BALLROOM_B,
    MEETING_ROOM_301,
    VOLT_OPEN_UTILITIES,
    append_line_item,
    approve_service_order,
    assert_fields,
    assert_money_cents,
    assert_settlement_money,
    dispute_settlement,
    issue_settlement,
    make_analyst_headers,
    order_service,
    read_line_items,
    read_service_order,
    read_settlement,
    register_vendor,
    setup_event_lifecycle,
    validate_error,
)

FIVE_ATTESTED_DAYS = (
    ("2027-03-01", "MOVE_IN"),
    ("2027-03-02", "SHOW"),
    ("2027-03-03", "DARK"),
    ("2027-03-04", "DARK"),
    ("2027-03-05", "MOVE_OUT"),
)


def _pending_utilities_order(api: ApiClient):
    """A LATE 500-amp utilities order against an OPEN vendor, awaiting approval."""
    world = setup_event_lifecycle(
        api,
        "in_house",
        space=dict(MEETING_ROOM_301),
        deposit_cents=200000,
    )
    vendor = register_vendor(api, **dict(VOLT_OPEN_UTILITIES))
    order = order_service(api, world["booking"]["id"], vendor["id"], "UTILITIES", 500)
    world["vendor"] = vendor
    world["service_order"] = order
    return world


def test_surcharge_cap_clamps_the_late_open_vendor_product(api: ApiClient):
    """500 amps across all three tiers price at 644000 cents under the 1.40 cap.

    PRD: "Utilities alone are marginally tiered: the first 100 amps bill at 1,200
    cents each, amps from the 101st through the 400th bill at 900 cents each, and
    every amp beyond the 400th bills at 700 cents each; an order for 250 amps
    therefore bills 100 amps at the first rate plus 150 amps at the second, and an
    order for 80 amps bills all 80 at the first rate with the higher tiers
    contributing nothing."
    PRD: "The combined factor is the product of those two, capped at 1.40 — so a
    late order against an open vendor, whose raw product is 1.6875, is charged at
    1.40."

    Design: Difficulty/combinatorial_formula/utilities_service_order_surcharge_cap_binds_over_marginal_tier_stack
    """
    world = _pending_utilities_order(api)

    approve_service_order(api, world["service_order"]["id"])

    order = read_service_order(api, world["service_order"]["id"])
    assert_money_cents(order["estimated_charge_cents"], 644000, "estimated_charge_cents")
    assert order["estimated_charge_cents"] != 776250, (
        "the uncapped 1.6875 product must not be charged"
    )


def test_late_timing_and_both_status_dimensions_advance_on_approval(api: ApiClient):
    """An order placed one day before the show is LATE and approval writes the estimate.

    PRD: "It is `ADVANCE` when the logical clock date falls more than 30 days
    before the booking's `show_start_date`, and `LATE` otherwise — so an order
    placed exactly 30 days out is `LATE`, and one placed 31 days out is `ADVANCE`."
    PRD: "Approval simultaneously drives the billing dimension `UNBILLED →
    ESTIMATED` on the same row and writes `estimated_charge_cents` from the pricing
    calculation over `ordered_quantity`."

    Design: Difficulty/combinatorial_formula/utilities_service_order_surcharge_cap_binds_over_marginal_tier_stack
    """
    world = _pending_utilities_order(api)

    assert_fields(
        read_service_order(api, world["service_order"]["id"]),
        order_timing="LATE",
        approval_status="PENDING_APPROVAL",
        billing_status="UNBILLED",
    )

    approve_service_order(api, world["service_order"]["id"])

    assert_fields(
        read_service_order(api, world["service_order"]["id"]),
        order_timing="LATE",
        approval_status="APPROVED",
        billing_status="ESTIMATED",
    )


def _draft_actual_usage_settlement_with_rental_line(api: ApiClient, rental_cents: int):
    """A CLOSED five-day booking whose DRAFT ACTUAL_USAGE settlement carries one rental line."""
    world = setup_event_lifecycle(
        api,
        "settlement_draft",
        space=dict(MEETING_ROOM_301),
        deposit_cents=200000,
        usage_records=FIVE_ATTESTED_DAYS,
        settlement_basis="ACTUAL_USAGE",
    )
    append_line_item(
        api,
        world["settlement"]["id"],
        "RENTAL",
        rental_cents,
        memo="sum-then-round rental",
    )
    return world


def test_rental_line_one_cent_below_the_per_day_rounded_total_is_refused(api: ApiClient):
    """A rental line of 204525 — the sum-then-round figure — is refused at issue.

    PRD: "Sum those rounded per-day integers, then multiply the sum by one minus
    the class's `rental_discount_pct` and round half up once more."
    PRD: "Summing the unrounded day products and rounding once at the end yields a
    different total and is wrong."
    PRD: "Exactly one line whose `line_kind` is `RENTAL` must exist, and its
    `amount_cents` must equal the rental basis computed for the settlement's own
    `basis`; no rental line, more than one, or a mismatched amount is refused with
    `ERR_RENTAL_LINE_MISMATCH` — which is also what a settlement carrying no lines
    at all reports, since it necessarily has no rental line."

    Design: Difficulty/combinatorial_formula/sum_then_round_actual_usage_rental_line_rejected_at_one_cent_below
    """
    world = _draft_actual_usage_settlement_with_rental_line(api, 204525)

    response = api.issue_settlement(
        world["settlement"]["id"], headers=make_analyst_headers(ANALYST_ONE)
    )
    validate_error(response, ApiErrorId.RENTAL_LINE_MISMATCH, expected_status=422)


def test_refused_issue_leaves_the_settlement_untotalled_in_draft(api: ApiClient):
    """The rejected issue leaves the settlement DRAFT with a zero subtotal and no revision.

    PRD: "The settlement opens in `status` `DRAFT` with `revision_round` 0 and
    every money field at 0: `line_subtotal_cents`, `facility_service_fee_cents`,
    `deposit_applied_cents` and `grand_total_cents`."

    Design: Difficulty/combinatorial_formula/sum_then_round_actual_usage_rental_line_rejected_at_one_cent_below
    """
    world = _draft_actual_usage_settlement_with_rental_line(api, 204525)

    api.issue_settlement(world["settlement"]["id"], headers=make_analyst_headers(ANALYST_ONE))

    settlement = read_settlement(api, world["settlement"]["id"])
    assert_fields(settlement, status="DRAFT", revision_round=0)
    assert_settlement_money(settlement, line_subtotal_cents=0)


def _issued_ballroom_settlement(api: ApiClient):
    """A Ballroom B booking closed and settled with a single 5,400,000 cent rental line."""
    return setup_event_lifecycle(
        api,
        "settlement_issued",
        space=dict(BALLROOM_B),
        deposit_cents=1400000,
        booking={
            "event_name": "Sunbelt Home & Garden Expo",
            "move_in_start_date": "2027-06-08",
            "show_start_date": "2027-06-10",
            "show_end_date": "2027-06-12",
            "move_out_end_date": "2027-06-13",
        },
    )


def test_first_issue_prices_the_middle_fee_band_on_the_full_subtotal(api: ApiClient):
    """A 5,400,000 cent subtotal takes the 7 percent band for a 5,778,000 cent total.

    PRD: "Step two: select the fee percentage from the subtotal."
    PRD: "Both breakpoints are strict less-than comparisons, so a subtotal of
    exactly 5,000,000 cents falls into the middle band at 7 percent, and a subtotal
    of exactly 20,000,000 cents falls into the top band at 5.5 percent."
    PRD: "Step five: `grand_total_cents` is the subtotal plus the facility service
    fee less the deposit applied."

    Design: Difficulty/combinatorial_formula/facility_fee_tier_reselected_on_lower_subtotal_yields_higher_fee
    """
    world = _issued_ballroom_settlement(api)

    settlement = read_settlement(api, world["settlement"]["id"])
    assert_fields(settlement, status="ISSUED", revision_round=0)
    assert_settlement_money(
        settlement,
        line_subtotal_cents=5400000,
        facility_service_fee_cents=378000,
        grand_total_cents=5778000,
    )


def test_credit_adjustment_drops_the_subtotal_a_band_and_raises_the_fee(api: ApiClient):
    """A -600000 cent adjustment lowers the subtotal to 4,800,000 and lifts the fee to 432000.

    PRD: "Step one: `line_subtotal_cents` is the sum of `amount_cents` over every
    line whose `settlement_id` is this settlement, processed in `created_at`
    ascending order, with `ADJUSTMENT` lines added according to their sign."
    PRD: "The fee percentage is never keyed on `grand_total_cents`; recomputing the
    band from the total is wrong."
    PRD: "A re-issue out of `DISPUTED` additionally requires `revision_round` to be
    strictly less than two, else `ERR_SETTLEMENT_REVISION_LIMIT_REACHED`, and it
    increments `revision_round` by 1 and clears `dispute_reason` back to null."

    Design: Difficulty/combinatorial_formula/facility_fee_tier_reselected_on_lower_subtotal_yields_higher_fee
    """
    world = _issued_ballroom_settlement(api)
    settlement_id = world["settlement"]["id"]

    dispute_settlement(
        api,
        settlement_id,
        world["client"]["id"],
        "two exhibit halls were released back to the venue on the dark day",
    )
    append_line_item(
        api, settlement_id, "ADJUSTMENT", -600000, memo="negotiated rent credit"
    )
    issue_settlement(api, settlement_id)

    settlement = read_settlement(api, settlement_id)
    assert_fields(settlement, status="ISSUED", revision_round=1)
    assert_settlement_money(
        settlement,
        line_subtotal_cents=4800000,
        facility_service_fee_cents=432000,
        grand_total_cents=5232000,
    )
    assert settlement["facility_service_fee_cents"] != 336000, (
        "the fee band must not be recomputed from the grand total"
    )
    assert len(read_line_items(api, settlement_id)) == 2
