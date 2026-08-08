"""The activity and equipment kit: the fulfilment fork, stock conservation and damage fees."""

from test_helpers import (
    ApiErrorId,
    assert_kit_unit_identity,
    assert_money,
    checked_out_loan,
    fulfill_loan,
    new_kit_item,
    read_kit_item,
    read_kit_loan,
    request_loan,
    setup_active_plan,
    validate_error,
    validate_success,
)


def test_a_damaged_return_rounds_only_the_final_product(api):
    """PRD §3.9: "Count the whole calendar months elapsed from the item's
    `in_service_date` to the return date, flooring the count so that a partial month
    does not count and a return landing on the same day of the month completes that
    month."
    PRD §3.9: "The straight-line value is the `replacement_cost` multiplied by one
    minus the ratio of those capped months to `useful_life_months`. The salvage floor
    is the `replacement_cost` multiplied by 0.20. The depreciated value is whichever
    of the two is larger, and both are carried unrounded to this point."
    PRD §3.9: "That depreciated value is then multiplied by the condition multiplier —
    0.00 for a `GOOD` return, 0.25 for `FAIR`, 0.60 for `DAMAGED` and 1.00 for `LOST`
    — and only that final product is rounded half-up to two decimal places into
    `damage_fee_amount`."

    Design: Difficulty/combinatorial_formula/kit_damage_fee_single_final_rounding_mode_b
    """
    scn = setup_active_plan()
    item, loan = checked_out_loan(
        scn,
        name="Vectogram set",
        item_class="LOANABLE_SERIALIZED",
        replacement_cost=275.00,
        useful_life_months=24,
        in_service_date="2025-11-01",
        initial_qty=2,
    )

    returned = validate_success(
        api.return_kit_loan(loan["id"], {"returned_condition": "DAMAGED"}, scn["hdr_front"]),
        200,
    )

    assert_money(returned["damage_fee_amount"], 116.88, "damage_fee_amount")
    assert float(returned["damage_fee_amount"]) != 116.87
    assert returned["status"] == "RETURNED"


def test_a_damaged_return_puts_the_unit_back_on_the_shelf(api):
    """PRD §3.9: "Where the units land depends on the grade: a `GOOD`, `FAIR` or
    `DAMAGED` return moves `quantity` units out of `on_loan_qty` and back into
    `on_hand_qty`, while a `LOST` return moves them out of `on_loan_qty` and into
    `retired_qty`."
    PRD §2.10: "On every `KitItem` row, `initial_qty` equals `on_hand_qty` plus
    `on_loan_qty` plus `dispensed_qty` plus `retired_qty`."

    Design: Difficulty/combinatorial_formula/kit_damage_fee_single_final_rounding_mode_b
    """
    scn = setup_active_plan()
    item, loan = checked_out_loan(
        scn,
        name="Vectogram set",
        item_class="LOANABLE_SERIALIZED",
        replacement_cost=275.00,
        useful_life_months=24,
        in_service_date="2025-11-01",
        initial_qty=2,
    )

    validate_success(
        api.return_kit_loan(loan["id"], {"returned_condition": "DAMAGED"}, scn["hdr_front"]),
        200,
    )

    stock = read_kit_item(item["id"])
    assert stock["on_hand_qty"] == 2
    assert stock["on_loan_qty"] == 0
    assert stock["retired_qty"] == 0
    assert_kit_unit_identity(stock)


def test_checkout_moves_a_unit_from_the_shelf_to_the_loan_column(api):
    """PRD §3.9: "Fulfilling a `LOANABLE_SERIALIZED` item moves the loan
    `REQUESTED → CHECKED_OUT`, moves `quantity` units out of `on_hand_qty` and into
    `on_loan_qty`, and leaves the loan open — an optional `due_at` may be supplied to
    record when the item is expected back."
    PRD §2.10: "On every `KitItem` row, `initial_qty` equals `on_hand_qty` plus
    `on_loan_qty` plus `dispensed_qty` plus `retired_qty`."

    Design: Difficulty/compensating_invariant/kit_stock_conserved_across_checkout_then_lost_return
    """
    scn = setup_active_plan()
    item, loan = checked_out_loan(
        scn,
        name="Brock string kit",
        item_class="LOANABLE_SERIALIZED",
        replacement_cost=300.00,
        useful_life_months=24,
        in_service_date="2025-06-01",
        initial_qty=3,
    )

    assert loan["status"] == "CHECKED_OUT"
    stock = read_kit_item(item["id"])
    assert stock["initial_qty"] == 3
    assert stock["on_hand_qty"] == 2
    assert stock["on_loan_qty"] == 1
    assert stock["dispensed_qty"] == 0
    assert stock["retired_qty"] == 0
    assert_kit_unit_identity(stock)


def test_a_lost_return_retires_the_unit_and_still_conserves_the_kit_identity(api):
    """PRD §3.9: "Where the units land depends on the grade: a `GOOD`, `FAIR` or
    `DAMAGED` return moves `quantity` units out of `on_loan_qty` and back into
    `on_hand_qty`, while a `LOST` return moves them out of `on_loan_qty` and into
    `retired_qty`. Either way the kit-unit identity holds."
    PRD §3.9: "A `GOOD` return therefore always yields a fee of exactly `0.00`, and a
    fully depreciated item still bills a fifth of its replacement cost when it is
    lost."
    PRD §2.10: "It holds at catalogue creation, where `on_hand_qty` takes the whole
    `initial_qty` and the other three are 0; after fulfilment on either arm of the
    serialized/consumable fork; and after a return on both the recovered arm and the
    lost arm."

    Design: Difficulty/compensating_invariant/kit_stock_conserved_across_checkout_then_lost_return
    """
    scn = setup_active_plan()
    item, loan = checked_out_loan(
        scn,
        name="Brock string kit",
        item_class="LOANABLE_SERIALIZED",
        replacement_cost=300.00,
        useful_life_months=24,
        in_service_date="2025-06-01",
        initial_qty=3,
    )

    returned = validate_success(
        api.return_kit_loan(loan["id"], {"returned_condition": "LOST"}, scn["hdr_front"]),
        200,
    )

    assert returned["status"] == "RETURNED"
    assert_money(returned["damage_fee_amount"], 150.00, "damage_fee_amount")

    stock = read_kit_item(item["id"])
    assert stock["initial_qty"] == 3
    assert stock["on_hand_qty"] == 2
    assert stock["on_loan_qty"] == 0
    assert stock["dispensed_qty"] == 0
    assert stock["retired_qty"] == 1
    assert_kit_unit_identity(stock)


def test_fulfilling_a_consumable_dispenses_it_rather_than_lending_it(api):
    """PRD §3.9: "Fulfilling a `CONSUMABLE_STOCK` item instead moves the loan
    `REQUESTED → DISPENSED`, which is terminal, and moves `quantity` units out of
    `on_hand_qty` and into `dispensed_qty` where they are never expected back."
    PRD §3.9: "Both arms stamp `checked_out_at` with the clock and `issued_by_user_id`
    with the acting `X-User-ID`, and bump both the loan's and the item's `version`."

    Design: Corner/state_machines/kit_fulfil_forks_to_dispensed_for_a_consumable_item
    """
    scn = setup_active_plan()
    item = new_kit_item(
        name="Anaglyph glasses",
        item_class="CONSUMABLE_STOCK",
        replacement_cost=4.00,
        useful_life_months=12,
        in_service_date="2026-01-01",
        initial_qty=10,
    )
    loan = request_loan(scn, item["id"], quantity=3)

    data = validate_success(api.fulfill_kit_loan(loan["id"], scn["hdr_front"], {}), 200)

    assert data["status"] == "DISPENSED"
    stock = read_kit_item(item["id"])
    assert stock["on_hand_qty"] == 7
    assert stock["on_loan_qty"] == 0
    assert stock["dispensed_qty"] == 3
    assert stock["retired_qty"] == 0
    assert_kit_unit_identity(stock)


def test_the_salvage_floor_still_bills_a_fifth_of_a_fully_depreciated_item(api):
    """PRD §3.9: "Cap that figure at the item's `useful_life_months`."
    PRD §3.9: "The straight-line value is the `replacement_cost` multiplied by one
    minus the ratio of those capped months to `useful_life_months`. The salvage floor
    is the `replacement_cost` multiplied by 0.20. The depreciated value is whichever
    of the two is larger, and both are carried unrounded to this point."
    PRD §3.9: "A `GOOD` return therefore always yields a fee of exactly `0.00`, and a
    fully depreciated item still bills a fifth of its replacement cost when it is
    lost."

    Design: Corner/calculations/kit_damage_fee_salvage_floor_binds_past_useful_life
    """
    scn = setup_active_plan()
    item, loan = checked_out_loan(
        scn,
        name="Legacy stereoscope",
        item_class="LOANABLE_SERIALIZED",
        replacement_cost=300.00,
        useful_life_months=24,
        in_service_date="2023-06-01",
        initial_qty=1,
    )

    returned = validate_success(
        api.return_kit_loan(loan["id"], {"returned_condition": "DAMAGED"}, scn["hdr_front"]),
        200,
    )

    assert_money(returned["damage_fee_amount"], 36.00, "damage_fee_amount")
    assert float(returned["damage_fee_amount"]) != 0.00
    assert returned["status"] == "RETURNED"

    stock = read_kit_item(item["id"])
    assert stock["on_hand_qty"] == 1
    assert stock["on_loan_qty"] == 0
    assert_kit_unit_identity(stock)


def test_fulfilling_more_units_than_are_on_hand_is_refused(api):
    """PRD §2.7 rung 28: "**Stock availability.** The `KitItem`'s `on_hand_qty` is at
    least the loan's `quantity`, and a loan against a `LOANABLE_SERIALIZED` item has a
    `quantity` of exactly 1. Otherwise `ERR_KIT_STOCK_DEPLETED`, HTTP 409. Applies to
    kit-loan fulfilment."
    PRD §3.9: "Either way the loan must still be in `status` `REQUESTED`, the item's
    `on_hand_qty` must be at least the loan's `quantity`, and a `LOANABLE_SERIALIZED`
    item additionally requires a `quantity` of exactly 1; a shortfall on either count
    is refused with `ERR_KIT_STOCK_DEPLETED`."

    Design: Corner/errors/kit_fulfil_beyond_on_hand_quantity_rejected
    """
    scn = setup_active_plan()
    item = new_kit_item(
        name="Red/green flippers",
        item_class="CONSUMABLE_STOCK",
        replacement_cost=6.00,
        useful_life_months=12,
        in_service_date="2026-01-01",
        initial_qty=3,
    )
    loan = request_loan(scn, item["id"], quantity=4)

    response = api.fulfill_kit_loan(loan["id"], scn["hdr_front"], {})

    validate_error(response, ApiErrorId.ERR_KIT_STOCK_DEPLETED.value, 409)
    stock = read_kit_item(item["id"])
    assert stock["on_hand_qty"] == 3
    assert stock["on_loan_qty"] == 0
    assert stock["dispensed_qty"] == 0
    assert_kit_unit_identity(stock)
    assert read_kit_loan(loan["id"])["status"] == "REQUESTED"
