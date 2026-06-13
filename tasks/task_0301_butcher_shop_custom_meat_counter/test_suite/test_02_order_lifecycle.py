"""Custom order lifecycle: the FILLED/SHORT_FILLED fork, invalid transitions,
terminal lockdown, and the lot-depletion side effect.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ensure_pricing_policy,
    create_cut_type,
    create_customer,
    receive_lot,
    place_order,
    place_and_confirm_order,
    setup_holiday_window_before_cutoff,
    place_holiday_order,
    get_order_line_ids,
    ApiErrorId,
    TEST_USERS,
)

MGR = TEST_USERS["shift_manager_headers"]
CLERK = TEST_USERS["counter_clerk_headers"]
BUTCHER = TEST_USERS["butcher_headers"]


# ===========================================================================
# Difficulty: non_linear_state_machine / order_fork_filled_vs_short_filled_divergent_side_effects
# ===========================================================================
def test_order_fork_short_filled_excludes_shorted_line(api):
    """PRD §3.5: "If instead at least one line is `SHORTED` and at least one line
    is `DRAWN`, the order advances `CONFIRMED → SHORT_FILLED`: the server recomputes
    `final_total_cents` as the sum of `final_line_cents` over the drawn lines only
    (shorted lines contribute 0)".

    Line0 500g drawn -> floor(500*0.96)=480g*4.0=1920c; line1 2000g shorted -> 0.
    final_total_cents == 1920; order SHORT_FILLED.

    Design: Difficulty/non_linear_state_machine/order_fork_filled_vs_short_filled_divergent_side_effects
    """
    setup = setup_holiday_window_before_cutoff(capacity_g=100000)
    cut, window = setup["cut_type"], setup["window"]
    cust = create_customer(full_name="Holly Holiday", phone="555-0004")
    order = place_holiday_order(cust["id"], window["id"], [(cut["id"], 500), (cut["id"], 2000)])
    assert order["deposit_cents"] == 2500
    line_ids = get_order_line_ids(order["id"])
    get_success_data(api.confirm_order(order["id"], CLERK))

    lot = receive_lot(cut["id"], received_weight_g=2000)
    get_success_data(
        api.draw_line(line_ids[0],
                      {"drawn_lot_id": lot["id"], "catch_weight_g": 500,
                       "expected_inventory_lot_version": lot["version"]}, BUTCHER)
    )
    get_success_data(api.short_line(line_ids[1], BUTCHER))

    filled = validate_success(api.fill_order(order["id"], BUTCHER))
    assert filled["order_status"] == "SHORT_FILLED"
    assert filled["final_total_cents"] == 1920, (
        f"final over drawn lines only expected 1920, got {filled['final_total_cents']}"
    )


def test_order_fork_short_filled_refunds_deposit_overage(api):
    """PRD §3.5: "for a holiday order refunds the difference between the
    `deposit_cents` and that final total to `store_credit_cents` whenever that
    difference is positive."

    Deposit 2500, final 1920 -> refund 580 to store credit.

    Design: Difficulty/non_linear_state_machine/order_fork_filled_vs_short_filled_divergent_side_effects
    """
    setup = setup_holiday_window_before_cutoff(capacity_g=100000)
    cut, window = setup["cut_type"], setup["window"]
    cust = create_customer(full_name="Holly Holiday", phone="555-0044")
    order = place_holiday_order(cust["id"], window["id"], [(cut["id"], 500), (cut["id"], 2000)])
    line_ids = get_order_line_ids(order["id"])
    get_success_data(api.confirm_order(order["id"], CLERK))

    lot = receive_lot(cut["id"], received_weight_g=2000)
    get_success_data(
        api.draw_line(line_ids[0],
                      {"drawn_lot_id": lot["id"], "catch_weight_g": 500,
                       "expected_inventory_lot_version": lot["version"]}, BUTCHER)
    )
    get_success_data(api.short_line(line_ids[1], BUTCHER))
    validate_success(api.fill_order(order["id"], BUTCHER))

    cust_after = get_success_data(api.get_customer(cust["id"], MGR))
    assert cust_after["store_credit_cents"] == 580, (
        f"deposit overage 2500-1920=580 expected, got {cust_after['store_credit_cents']}"
    )


def test_order_fork_filled_branch_all_lines_drawn(api):
    """PRD §3.5: "If **every** order line is `DRAWN`, the order advances
    `CONFIRMED → FILLED`: the server recomputes `final_total_cents` as the sum of
    `final_line_cents` over all lines".

    One STANDARD line catch 1000g, whole-cut shrink 0.04 -> floor(1000*0.96)=960g*
    4.0 = 3840c; order FILLED.

    Design: Difficulty/non_linear_state_machine/order_fork_filled_vs_short_filled_divergent_side_effects
    """
    ensure_pricing_policy()
    cut = create_cut_type(code="RIBEYE", species="BEEF", base_price_cents_per_kg=4000)
    cust = create_customer(full_name="Fred Filled", phone="555-0404")
    order, line_ids = place_and_confirm_order(cust["id"], [(cut["id"], 1000)])
    lot = receive_lot(cut["id"], received_weight_g=2000)
    get_success_data(
        api.draw_line(line_ids[0],
                      {"drawn_lot_id": lot["id"], "catch_weight_g": 1000,
                       "expected_inventory_lot_version": lot["version"]}, BUTCHER)
    )
    filled = validate_success(api.fill_order(order["id"], BUTCHER))
    assert filled["order_status"] == "FILLED"
    assert filled["final_total_cents"] == 3840, (
        f"final over all drawn lines expected 3840, got {filled['final_total_cents']}"
    )


# ===========================================================================
# Corner: state_machines / confirm_already_confirmed_order_invalid_state
# ===========================================================================
def test_confirm_already_confirmed_order_invalid_state(api):
    """PRD §2.10: "Fifth, that the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`)."
    PRD §3.5: "A `CounterClerk` confirms a placed order, advancing
    `PLACED → CONFIRMED`".

    Confirming a CONFIRMED order has no defined transition -> ERR_INVALID_STATE.

    Design: Corner/state_machines/confirm_already_confirmed_order_invalid_state
    """
    ensure_pricing_policy()
    cut = create_cut_type(code="RIBEYE", species="BEEF", base_price_cents_per_kg=4000)
    cust = create_customer(full_name="Ida Invalid", phone="555-1001")
    order, _ = place_and_confirm_order(cust["id"], [(cut["id"], 1000)])
    resp = api.confirm_order(order["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner: state_machines / cancel_filled_order_from_terminal_invalid_state
# ===========================================================================
def test_cancel_filled_order_from_terminal_invalid_state(api):
    """PRD §3.5: "An order is one of `PLACED`, `CONFIRMED`, `FILLED`,
    `SHORT_FILLED`, or `CANCELLED`, with the last three terminal."
    PRD §3.5: "A customer may cancel their own order while it is `PLACED`, and a
    clerk may cancel an order while it is `CONFIRMED` provided no line has yet been
    drawn".

    Cancelling a FILLED (terminal) order -> ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_filled_order_from_terminal_invalid_state
    """
    ensure_pricing_policy()
    cut = create_cut_type(code="RIBEYE", species="BEEF", base_price_cents_per_kg=4000)
    cust = create_customer(full_name="Tom Terminal", phone="555-1002")
    order, line_ids = place_and_confirm_order(cust["id"], [(cut["id"], 1000)])
    lot = receive_lot(cut["id"], received_weight_g=2000)
    get_success_data(
        api.draw_line(line_ids[0],
                      {"drawn_lot_id": lot["id"], "catch_weight_g": 1000,
                       "expected_inventory_lot_version": lot["version"]}, BUTCHER)
    )
    filled = validate_success(api.fill_order(order["id"], BUTCHER))
    assert filled["order_status"] == "FILLED"
    assert filled["final_total_cents"] == 3840

    resp = api.cancel_order(order["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner: state_machines / lot_bubbles_to_depleted_when_remaining_hits_zero
# ===========================================================================
def test_lot_bubbles_to_depleted_when_drawn_to_zero(api):
    """PRD §3.5: "if the lot's `remaining_weight_g` has reached 0 — bubbles the lot
    `AVAILABLE → DEPLETED`."
    PRD §3.3: "A lot that runs to zero remaining weight through draws instead
    bubbles `AVAILABLE → DEPLETED` automatically the moment a committed draw brings
    its `remaining_weight_g` to 0".

    Draw the full 2000g of a 2000g lot -> remaining 0, lot DEPLETED.

    Design: Corner/state_machines/lot_bubbles_to_depleted_when_remaining_hits_zero
    """
    ensure_pricing_policy()
    cut = create_cut_type(code="RIBEYE", species="BEEF", base_price_cents_per_kg=4000)
    cust = create_customer(full_name="Della Deplete", phone="555-1003")
    order, line_ids = place_and_confirm_order(cust["id"], [(cut["id"], 2000)])
    lot = receive_lot(cut["id"], received_weight_g=2000)
    get_success_data(
        api.draw_line(line_ids[0],
                      {"drawn_lot_id": lot["id"], "catch_weight_g": 2000,
                       "expected_inventory_lot_version": lot["version"]}, BUTCHER)
    )
    lot_after = get_success_data(api.get_inventory_lot(lot["id"], BUTCHER))
    assert lot_after["remaining_weight_g"] == 0
    assert lot_after["lot_status"] == "DEPLETED"
