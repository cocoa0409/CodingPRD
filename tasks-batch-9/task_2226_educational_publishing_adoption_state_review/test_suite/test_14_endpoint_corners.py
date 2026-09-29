"""Corner cases of the district sales endpoints.

An order is priced twice, commits warehouse stock once and ships once, and the
adopted list decides whether a district in an adoption-list state is allowed to
buy an edition at all. Both tests drive the endpoints from an empty database and
read the money, the stock and the order status back off the resources.
"""

import pytest

from test_helpers import (
    ADOPTION_MODEL_ADOPTION_LIST,
    ApiErrorId,
    ORDER_STATUS_CONFIRMED,
    ORDER_STATUS_FULFILLED,
    ORDER_STATUS_QUOTED,
    assert_print_unit_ledger_balances,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    CONFIRMING_REP,
    EDITOR,
    PRICING,
    QUOTING_REP,
    quote_order,
    seed_adopted_submission,
    seed_confirmed_order,
)


def test_fulfilment_moves_committed_units_into_fulfilled_and_seals_the_order(api):
    """PRD 3.9: "Fulfilment moves a `CONFIRMED` order to `FULFILLED`, its terminal
    state, decreasing the edition's `committed_units` by `allocated_units` and
    increasing its `fulfilled_units` by the same amount." "`allocated_units` itself
    is left as it stands, recording what shipped, and the order becomes
    read-only." "A confirmation writes `contracted_tcv_cents` and
    `freight_surcharge_cents` from the contracted variant, records
    `confirmed_by_user_id`, sets `allocated_units` to `print_units`, and moves the
    stock: the edition's `on_hand_units` decreases by `print_units` and its
    `committed_units` increases by the same amount." "In the quoted variant the
    unit price is the edition's own `list_price_cents`." "In the contracted variant
    the unit price is the attached proposal's `avg_annual_price_cents` when a
    `pricing_proposal_id` is present, and the edition's `list_price_cents` when it
    is not." "The seat price, in both variants, is the attached proposal's
    `digital_seat_price_cents` when a `pricing_proposal_id` is present, and
    otherwise a default open-territory seat price of 1,200 cents — twelve dollars
    per student seat." "From those, the print subtotal is the unit price multiplied
    by `print_units`, the digital subtotal is the seat price multiplied by
    `digital_seats`, and the **pre-freight total** is their sum."
    "`freight_surcharge_cents` is 0 when the pre-freight total is at or above the
    freight waiver threshold of 2,500,000 cents — that is, twenty-five thousand
    dollars — and otherwise is the print subtotal multiplied by a freight rate of
    0.015, rounded half up to a whole cent." "Next, an adopted-list rebate applies
    **only** in the contracted variant and **only** when the state's
    `adoption_model` is `ADOPTION_LIST`: it is the print subtotal multiplied by
    0.02, rounded half up to a whole cent; in every other case the rebate is 0."
    "The stored total is the pre-freight total plus `freight_surcharge_cents` minus
    the rebate, and `freight_surcharge_cents` on the order always reflects the most
    recently computed total." PRD 2.10: "The **print-unit ledger** of a title
    states that `total_received_units` always equals the sum of `on_hand_units`,
    `committed_units`, `sample_reserved_units`, `fulfilled_units` and
    `written_off_units`." PRD 2.6: "28. The addressed order's `status` admits the
    operation, else `ERR_DISTRICT_ORDER_STATE_INVALID` (409) — confirm requires
    `QUOTED`, fulfil requires `CONFIRMED`, cancel requires `QUOTED` or `CONFIRMED`;
    the same code also refuses a revision-plan sunset while any order of the title
    is `CONFIRMED`."

    A Nebraska district buys 120 print copies at the 9,000-cent list price and 25
    digital seats at the default open-territory seat price, with no state price
    filing behind it, so both variants of the total agree: 1,080,000 plus 30,000 in
    seats, plus 16,200 of freight because the pre-freight total sits well below the
    waiver, and no rebate in open territory. Shipping the order walks 120 units
    from committed to fulfilled without touching the shelf, keeps the allocation on
    the record, and closes the order to any further movement.

    Design: Corner/endpoints/fulfill_moves_committed_units_to_fulfilled
    """
    world = seed_confirmed_order(
        api,
        "NE",
        print_units=120,
        digital_seats=25,
        receipt_units=200,
        title_overrides={"list_price_cents": 9000},
    )

    confirmed = validate_success(api.get_district_order(world.order_id, CONFIRMING_REP))
    assert confirmed["status"] == ORDER_STATUS_CONFIRMED
    assert confirmed["allocated_units"] == 120
    assert confirmed["quoted_tcv_cents"] == 1126200
    assert confirmed["contracted_tcv_cents"] == 1126200
    assert confirmed["freight_surcharge_cents"] == 16200

    committed_title = validate_success(api.get_title(world.title_id, EDITOR))
    assert committed_title["on_hand_units"] == 80
    assert committed_title["committed_units"] == 120
    assert committed_title["fulfilled_units"] == 0

    shipped = validate_success(
        api.fulfill_district_order(world.order_id, CONFIRMING_REP)
    )
    assert shipped["status"] == ORDER_STATUS_FULFILLED
    assert shipped["allocated_units"] == 120, "The allocation records what shipped"
    assert shipped["contracted_tcv_cents"] == 1126200

    title = validate_success(api.get_title(world.title_id, EDITOR))
    assert title["committed_units"] == 0
    assert title["fulfilled_units"] == 120
    assert title["on_hand_units"] == 80, "Shipping draws on the commitment, not the shelf"
    assert title["total_received_units"] == 200
    assert_print_unit_ledger_balances(title)

    # A fulfilled order is terminal, so neither a second shipment nor a
    # cancellation may move it again.
    validate_error(
        api.fulfill_district_order(world.order_id, CONFIRMING_REP),
        ApiErrorId.ERR_DISTRICT_ORDER_STATE_INVALID,
        expected_status=409,
    )
    validate_error(
        api.cancel_district_order(
            world.order_id,
            {"reason": "The district asked to unwind the shipment after delivery."},
            CONFIRMING_REP,
        ),
        ApiErrorId.ERR_DISTRICT_ORDER_STATE_INVALID,
        expected_status=409,
    )

    sealed = validate_success(api.get_district_order(world.order_id, CONFIRMING_REP))
    assert sealed["status"] == ORDER_STATUS_FULFILLED
    assert sealed["allocated_units"] == 120


def test_adoption_list_confirm_refuses_an_edition_adopted_only_elsewhere(api):
    """PRD 3.9: "In an `ADOPTION_LIST` state three further conditions apply: the
    order must carry a `pricing_proposal_id`, else `ERR_PRICING_PROPOSAL_REQUIRED`;
    that proposal's `status` must be `APPROVED`, else
    `ERR_PRICING_PROPOSAL_STATE_INVALID`; and the edition's `adopted_state_codes`
    must contain the district's own `state_code`, else
    `ERR_TITLE_NOT_ON_ADOPTED_LIST`." "In an `OPEN_TERRITORY` state none of those
    three applies and a district may buy directly." "The new order is `QUOTED` with
    `created_by_user_id` set from the acting `X-User-ID`, `allocated_units` at 0,
    `contracted_tcv_cents` null and `confirmed_by_user_id` null." "In the quoted
    variant the unit price is the edition's own `list_price_cents`." "In the
    contracted variant the unit price is the attached proposal's
    `avg_annual_price_cents` when a `pricing_proposal_id` is present, and the
    edition's `list_price_cents` when it is not." "Next, an adopted-list rebate
    applies **only** in the contracted variant and **only** when the state's
    `adoption_model` is `ADOPTION_LIST`: it is the print subtotal multiplied by
    0.02, rounded half up to a whole cent; in every other case the rebate is 0."
    "The stored total is the pre-freight total plus `freight_surcharge_cents` minus
    the rebate, and `freight_surcharge_cents` on the order always reflects the most
    recently computed total." PRD 2.6: "41. In an `ADOPTION_LIST` state the ordered
    title's `adopted_state_codes` contains the district's state code, else
    `ERR_TITLE_NOT_ON_ADOPTED_LIST` (422), on confirming an order." PRD 3.2: "The
    `adopted_state_codes` array records the `state_code` of every state where a
    submission of this edition reached an adopted status, and it is written only by
    the committee tally of Section 3.8." PRD 3.6: "Finally,
    `avg_annual_price_cents` is `net_state_price_cents` divided by `term_years`,
    rounded half up to a whole cent; this is the contracted per-copy price
    districts will pay."

    Two editions reach adoption: one in Texas, which publishes an adopted list,
    and one in California. A Texas district may quote either of them, but the
    confirmation of the Californian edition is refused because Texas is absent from
    that edition's adopted-state codes — an approved price filing of its own does
    not substitute for a place on the list. The Texan edition confirms, and its
    contracted total draws the state-approved per-copy price and the two-percent
    adopted-list rebate.

    Design: Corner/endpoints/adoption_list_confirm_requires_the_title_on_the_adopted_list
    """
    listed = seed_adopted_submission(
        api,
        "TX",
        subject="MATH",
        grade=5,
        state_overrides={"adoption_model": ADOPTION_MODEL_ADOPTION_LIST},
        title_overrides={"list_price_cents": 10500},
        receipt_units=200,
        proposal_overrides={
            "base_price_cents": 10000,
            "term_years": 3,
            "annual_escalator_bps": 200,
            "projected_adoption_units": 6000,
            "digital_seat_price_cents": 1500,
        },
    )
    elsewhere = seed_adopted_submission(
        api,
        "CA",
        subject="MATH",
        grade=5,
        title_overrides={"list_price_cents": 10500},
        receipt_units=200,
        proposal_overrides={
            "base_price_cents": 10000,
            "term_years": 3,
            "annual_escalator_bps": 200,
            "projected_adoption_units": 6000,
            "digital_seat_price_cents": 1500,
        },
    )

    texan_edition = validate_success(api.get_title(listed.title_id, EDITOR))
    assert texan_edition["adopted_state_codes"] == ["TX"]
    other_edition = validate_success(api.get_title(elsewhere.title_id, EDITOR))
    assert other_edition["adopted_state_codes"] == ["CA"]

    # A 0.07 volume tier plus a 0.03 term tier discounts the 10,000-cent list to
    # 9,000, 9,180 and 9,364 across the three contract years, so the per-copy
    # contracted price is 27,544 over three years, or 9,181.
    proposal = validate_success(api.get_pricing_proposal(listed.proposal_id, PRICING))
    assert proposal["net_state_price_cents"] == 27544
    assert proposal["avg_annual_price_cents"] == 9181

    off_list_order = quote_order(
        api,
        listed,
        print_units=40,
        digital_seats=10,
        title_id=elsewhere.title_id,
        pricing_proposal_id=elsewhere.proposal_id,
    )
    validate_error(
        api.confirm_district_order(off_list_order, CONFIRMING_REP),
        ApiErrorId.ERR_TITLE_NOT_ON_ADOPTED_LIST,
        expected_status=422,
    )

    refused = validate_success(api.get_district_order(off_list_order, QUOTING_REP))
    assert refused["status"] == ORDER_STATUS_QUOTED
    assert refused["allocated_units"] == 0
    assert refused["contracted_tcv_cents"] is None
    assert refused["confirmed_by_user_id"] is None

    untouched = validate_success(api.get_title(elsewhere.title_id, EDITOR))
    assert untouched["committed_units"] == 0
    assert untouched["on_hand_units"] == 200

    listed_order = quote_order(
        api,
        listed,
        print_units=40,
        digital_seats=10,
        title_id=listed.title_id,
        pricing_proposal_id=listed.proposal_id,
    )
    quoted = validate_success(api.get_district_order(listed_order, QUOTING_REP))
    # List price 10,500 on 40 copies plus 10 seats at 1,500, freight 6,300 and no
    # rebate at quote time.
    assert quoted["quoted_tcv_cents"] == 441300

    confirmed = validate_success(
        api.confirm_district_order(listed_order, CONFIRMING_REP)
    )
    # The state-approved 9,181 on 40 copies is 367,240, plus 15,000 in seats,
    # plus 5,509 of freight, less the 7,345 adopted-list rebate.
    assert confirmed["status"] == ORDER_STATUS_CONFIRMED
    assert confirmed["contracted_tcv_cents"] == 380404
    assert confirmed["freight_surcharge_cents"] == 5509
    assert confirmed["allocated_units"] == 40

    committed_edition = validate_success(api.get_title(listed.title_id, EDITOR))
    assert committed_edition["on_hand_units"] == 160
    assert committed_edition["committed_units"] == 40
    assert_print_unit_ledger_balances(committed_edition)
