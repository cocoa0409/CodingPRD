"""Cascading side effects and conservation invariants.

Covers:
  Difficulty/transitive_cascade/order_cancel_depth3_cascade
  Difficulty/transitive_cascade/run_complete_bubbles_order_ready_cascade
  Difficulty/compensating_invariant/wallet_escrow_conservation_confirm_cancel
  Difficulty/compensating_invariant/spool_grams_conservation_commit_release
  Corner/calculations/void_line_excluded_from_order_totals (via cancel cascade — see SKIPPED note)
"""
from test_helpers import (
    validate_success, get_success_data, api_client,
    setup_confirmed_order, setup_run_printing, create_run,
    refresh_order, refresh_customer, refresh_spool,
    assert_wallet_conservation, assert_spool_conservation,
    FILE_B, TEST_USERS,
)

OPERATOR = TEST_USERS["operator_headers"]


def test_cancel_confirmed_cascades_to_runs_lines_spool_and_wallet(api):
    """PRD §3.5: "A permitted cancel of a confirmed order moves it to `CANCELLED`,
    sets `payment_status` to `REFUNDED`, fully compensates the customer by reducing
    `escrow_held_cents` by `grand_total_cents` and adding the same amount back to
    `wallet_balance_cents`, cancels all of the order's `QUEUED` print runs (releasing
    their committed spool grams), and voids all active lines."

    Design: Difficulty/transitive_cascade/order_cancel_depth3_cascade
    """
    env = setup_confirmed_order(geometry=FILE_B, layer_height_mm=0.10, quantity=1,
                                spool_grams=30)
    run = create_run(env, start_min=0, duration_min=24)  # QUEUED, commits 4g
    # cancel triggers the cascade.
    cancelled = get_success_data(api.cancel_order(env["order"]["id"], env["cust_headers"]))
    assert cancelled["fulfillment_status"] == "CANCELLED"
    assert cancelled["payment_status"] == "REFUNDED"

    run_after = get_success_data(api.get_print_run(run["id"], OPERATOR))
    assert run_after["status"] == "CANCELLED", run_after["status"]

    line_after = get_success_data(api.get_order_line(env["line"]["id"], env["cust_headers"]))
    assert line_after["status"] == "VOID", line_after["status"]

    spool_after = refresh_spool(env)
    assert spool_after["grams_committed"] == 0, spool_after["grams_committed"]
    assert spool_after["grams_remaining"] == 30, spool_after["grams_remaining"]

    customer = refresh_customer(env)
    assert customer["wallet_balance_cents"] == 5000000, customer["wallet_balance_cents"]
    assert customer["escrow_held_cents"] == 0


def test_void_line_excluded_from_totals_after_cancel(api):
    """PRD §3.3: "A new line is `ACTIVE`; lines may later become `VOID`, in which
    case they are excluded from all order totals."
    PRD §3.5: "A permitted cancel of a confirmed order moves it to `CANCELLED`,
    sets `payment_status` to `REFUNDED`, fully compensates the customer by reducing
    `escrow_held_cents` by `grand_total_cents` and adding the same amount back to
    `wallet_balance_cents`".

    Design: Difficulty/transitive_cascade/order_cancel_depth3_cascade
    """
    env = setup_confirmed_order(geometry=FILE_B, layer_height_mm=0.10, quantity=1,
                                spool_grams=100)
    customer_before = refresh_customer(env)
    assert customer_before["escrow_held_cents"] == 2928
    get_success_data(api.cancel_order(env["order"]["id"], env["cust_headers"]))
    line_after = get_success_data(api.get_order_line(env["line"]["id"], env["cust_headers"]))
    assert line_after["status"] == "VOID"
    # The only line is now VOID, so escrow fully refunds (totals over ACTIVE lines).
    customer_after = refresh_customer(env)
    assert customer_after["escrow_held_cents"] == 0
    assert customer_after["wallet_balance_cents"] == 5000000


def test_run_complete_moves_grams_and_bubbles_order_to_ready(api):
    """PRD §3.6: "Completing a printing run advances it from `PRINTING` to `DONE`:
    the run's grams move from committed to consumed on the spool (`grams_committed`
    decreases and `grams_consumed` increases by `run_grams`), and a completion check
    fires — if every active line of the order now has a terminal `DONE` run, the
    order bubbles to `POST_PROCESSING` when it has any finishing tasks, or straight
    to `READY` when it has none."

    Design: Difficulty/transitive_cascade/run_complete_bubbles_order_ready_cascade
    """
    env = setup_run_printing(geometry=FILE_B, layer_height_mm=0.10, quantity=1,
                             duration_min=24, spool_grams=100)
    run_done = get_success_data(api.complete_print_run(env["run"]["id"], OPERATOR))
    assert run_done["status"] == "DONE"

    spool_after = refresh_spool(env)
    assert spool_after["grams_committed"] == 0, spool_after["grams_committed"]
    assert spool_after["grams_consumed"] == 4, spool_after["grams_consumed"]

    order_after = refresh_order(env)
    assert order_after["fulfillment_status"] == "READY", order_after["fulfillment_status"]


def test_run_done_grams_become_consumed_not_committed(api):
    """PRD §2.6: "`grams_consumed` is the sum of `run_grams` over the spool's print
    runs that are `DONE` or `FAILED` — material that has been physically spent".

    Design: Difficulty/transitive_cascade/run_complete_bubbles_order_ready_cascade
    """
    env = setup_run_printing(geometry=FILE_B, layer_height_mm=0.10, quantity=1,
                             duration_min=24, spool_grams=100)
    get_success_data(api.complete_print_run(env["run"]["id"], OPERATOR))
    spool = refresh_spool(env)
    assert spool["grams_consumed"] == 4
    assert spool["grams_remaining"] == 96
    assert_spool_conservation(spool)


def test_wallet_conservation_holds_across_confirm_then_cancel(api):
    """PRD §2.8: "The governing invariant is that `lifetime_deposits_cents` always
    equals `wallet_balance_cents` plus `escrow_held_cents` plus
    `captured_revenue_cents`."
    PRD §3.5: "On success, ... the customer's `wallet_balance_cents` is reduced by
    `grand_total_cents` and `escrow_held_cents` is raised by the same amount".

    Design: Difficulty/compensating_invariant/wallet_escrow_conservation_confirm_cancel
    """
    env = setup_confirmed_order(geometry=FILE_B, layer_height_mm=0.10, quantity=1,
                                spool_grams=100)
    mid = refresh_customer(env)
    # After confirm (escrow 2928): wallet 4997072 + escrow 2928 + captured 0 == 5000000
    assert mid["wallet_balance_cents"] == 4997072
    assert mid["escrow_held_cents"] == 2928
    assert mid["captured_revenue_cents"] == 0
    assert mid["lifetime_deposits_cents"] == 5000000
    assert_wallet_conservation(mid)

    get_success_data(api.cancel_order(env["order"]["id"], env["cust_headers"]))
    end = refresh_customer(env)
    # After compensating cancel (refund): wallet 5000000 + escrow 0 + captured 0 == 5000000
    assert end["wallet_balance_cents"] == 5000000
    assert end["escrow_held_cents"] == 0
    assert end["captured_revenue_cents"] == 0
    assert end["lifetime_deposits_cents"] == 5000000
    assert_wallet_conservation(end)


def test_wallet_conservation_holds_through_ship_capture(api):
    """PRD §2.8: "The governing invariant is that `lifetime_deposits_cents` always
    equals `wallet_balance_cents` plus `escrow_held_cents` plus
    `captured_revenue_cents`."
    PRD §3.8: "the customer's `escrow_held_cents` is reduced by `grand_total_cents`
    and `captured_revenue_cents` is raised by the same amount".

    Design: Difficulty/compensating_invariant/wallet_escrow_conservation_confirm_cancel
    """
    from test_helpers import setup_ready_order_with_shipment
    env = setup_ready_order_with_shipment(geometry=FILE_B, layer_height_mm=0.10,
                                          quantity=1, duration_min=24, spool_grams=100)
    order = env["order"]
    get_success_data(api.ship_order(order["id"], {"expected_order_version": order["version"]},
                                    OPERATOR))
    end = refresh_customer(env)
    # After capture: wallet 4997072 + escrow 0 + captured 2928 == 5000000 (no drift)
    assert end["wallet_balance_cents"] == 4997072
    assert end["escrow_held_cents"] == 0
    assert end["captured_revenue_cents"] == 2928
    assert end["lifetime_deposits_cents"] == 5000000
    assert_wallet_conservation(end)


def test_spool_grams_conservation_holds_across_commit_then_consume(api):
    """PRD §2.6: "The invariant that `grams_remaining` plus `grams_committed` plus
    `grams_consumed` always equals `grams_total` holds after every operation."
    PRD §3.6: "the run's grams move from committed to consumed on the spool
    (`grams_committed` decreases and `grams_consumed` increases by `run_grams`)".

    Design: Difficulty/compensating_invariant/spool_grams_conservation_commit_release
    """
    env = setup_run_printing(geometry=FILE_B, layer_height_mm=0.10, quantity=1,
                             duration_min=24, spool_grams=100)
    mid = refresh_spool(env)
    # PRINTING run holds the commit: 96 + 4 + 0 == 100
    assert mid["grams_remaining"] == 96
    assert mid["grams_committed"] == 4
    assert mid["grams_consumed"] == 0
    assert_spool_conservation(mid)

    get_success_data(api.complete_print_run(env["run"]["id"], OPERATOR))
    end = refresh_spool(env)
    # After consume: 96 + 0 + 4 == 100 (mass conserved, moved committed->consumed)
    assert end["grams_remaining"] == 96
    assert end["grams_committed"] == 0
    assert end["grams_consumed"] == 4
    assert_spool_conservation(end)


def test_spool_grams_conservation_holds_across_commit_then_release(api):
    """PRD §2.6: "The invariant that `grams_remaining` plus `grams_committed` plus
    `grams_consumed` always equals `grams_total` holds after every operation."
    PRD §3.6: "An operator may cancel a queued run, moving it from `QUEUED` to
    `CANCELLED` and releasing its committed grams back to the spool
    (`grams_committed` decreases by `run_grams`, and because the run never printed,
    nothing is added to `grams_consumed`)."

    Design: Difficulty/compensating_invariant/spool_grams_conservation_commit_release
    """
    env = setup_confirmed_order(geometry=FILE_B, layer_height_mm=0.10, quantity=1,
                                spool_grams=100)
    run = create_run(env, start_min=0, duration_min=24)  # commits 4g
    mid = refresh_spool(env)
    # After commit of 4g: 96 + 4 + 0 == 100
    assert mid["grams_remaining"] == 96
    assert mid["grams_committed"] == 4
    assert mid["grams_consumed"] == 0
    assert_spool_conservation(mid)

    get_success_data(api.cancel_print_run(run["id"], OPERATOR))
    end = refresh_spool(env)
    # After release: 100 + 0 + 0 == 100; not consumed
    assert end["grams_remaining"] == 100
    assert end["grams_committed"] == 0
    assert end["grams_consumed"] == 0
    assert_spool_conservation(end)
