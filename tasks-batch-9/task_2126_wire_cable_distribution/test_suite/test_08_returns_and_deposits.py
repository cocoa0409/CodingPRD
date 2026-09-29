"""Reel returns, the deposit credit and the two independent status axes."""


from test_helpers import (
    ApiErrorId,
    PRODUCT_P1,
    build_quote,
    commit_pick,
    convert_quote,
    create_branch,
    create_customer,
    create_product,
    create_truck,
    deliver_order,
    deliver_run,
    dispatch_run,
    issue_quote,
    list_order_lines,
    list_reels,
    make_branch_ops_headers,
    publish_index,
    read_customer,
    read_order,
    read_order_line,
    read_reel,
    receive_reel,
    return_reel,
    return_reel_payload,
    run_allocator,
    allocations_of_order,
    schedule_run,
    set_clock,
    setup_delivered_master_reel_order,
    setup_staged_order_by_cut,
    setup_staged_order_by_pick,
    validate_error,
    validate_success,
)

MASTER_LINE = {"put_up": "MASTER_REEL", "requested_length_ft": 2500}
CUT_LINE = {"put_up": "CUT", "requested_length_ft": 300}


# ══════════════════════════════════════════════════════════════════════════
# The two status axes move independently
# ══════════════════════════════════════════════════════════════════════════

def _delivered_master_order_returned_on_day_four():
    scn = setup_delivered_master_reel_order()
    set_clock("2026-08-05T00:00:00Z")
    return_reel(
        scn["order_lines"][0]["id"], scn["reels"][0]["id"], scn["branch"]["id"],
        condition="GOOD",
    )
    return scn


def test_fulfilment_stays_delivered_while_billing_advances_to_credited(api):
    """PRD §3.5: "The two status axes are genuinely independent:
    `fulfillment_status` moves through `PENDING_ALLOCATION`,
    `PARTIALLY_ALLOCATED`, `ALLOCATED`, `STAGED`, `DELIVERED`, `HELD` and
    `CANCELLED`, while `billing_status` moves through `UNBILLED`, `INVOICED`,
    `CREDITED` and `VOIDED`, and a movement on one axis never implies a
    movement on the other except where this document says so explicitly."
    PRD §3.9: "Separately from the credit cascade, the return also settles the
    money axis when the last reel comes home: if the reel just returned was
    the final reel of that order still `ON_JOBSITE`, the order moves
    `INVOICED → CREDITED` on its `billing_status`."

    Design: Difficulty/non_linear_state_machine/sales_order_parallel_axes_fulfilment_frozen_while_billing_advances
    """
    scn = _delivered_master_order_returned_on_day_four()

    order = read_order(scn["order"]["id"])
    assert order["fulfillment_status"] == "DELIVERED"
    assert order["billing_status"] == "CREDITED"
    assert order["quoted_total_cents"] == 70063
    assert order["invoiced_total_cents"] == 70063
    assert order["metal_variance_cents"] == 0


def test_the_returned_master_reel_credits_the_whole_deposit(api):
    """PRD §3.9: "Inside a sixty-day return window, a reel handed back in
    `GOOD` condition earns the full deposit — a credit rate of 1.00 — and a
    reel handed back `DAMAGED` earns half of it, a rate of 0.50."
    PRD §3.9: "A valid return moves the reel `ON_JOBSITE → IN_STOCK` and
    clears its `delivered_at` back to null."
    PRD §3.9: "The order's `deposit_credited_cents` rises by the credited
    amount. The customer's `deposit_liability_cents` falls by the part's
    *full* `reel_deposit_cents` regardless of the credit rate — the reel is
    back, so the liability is discharged even when the customer is not paid
    for it — while the customer's `open_balance_cents` falls only by the
    credited amount."

    Design: Difficulty/non_linear_state_machine/sales_order_parallel_axes_fulfilment_frozen_while_billing_advances
    """
    scn = _delivered_master_order_returned_on_day_four()

    order = read_order(scn["order"]["id"])
    assert order["deposit_charged_cents"] == 12500
    assert order["deposit_credited_cents"] == 12500

    reel = read_reel(scn["reels"][0]["id"])
    assert reel["status"] == "IN_STOCK"
    assert reel["current_length_ft"] == 2500

    account = read_customer(scn["customer"]["id"])
    assert account["deposit_liability_cents"] == 0
    assert account["open_balance_cents"] == 70063


# ══════════════════════════════════════════════════════════════════════════
# The sixty-day deposit return window
# ══════════════════════════════════════════════════════════════════════════

def _two_delivered_master_orders():
    """Two single-line MASTER_REEL orders, each picked whole and delivered at
    the default clock on adjacent truck windows."""
    branch = create_branch()
    customer = create_customer()
    product = create_product(PRODUCT_P1)
    publish_index("2026-07-30", 450)
    truck = create_truck(
        branch["id"], truck_code="T-BOOM", has_boom_lift=True, max_reel_slots=4
    )
    reels = [
        receive_reel(product["id"], branch["id"], 2500),
        receive_reel(product["id"], branch["id"], 2500),
    ]
    shipments = []
    windows = [
        ("2026-08-02T08:00:00Z", "2026-08-02T10:00:00Z"),
        ("2026-08-02T10:00:00Z", "2026-08-02T12:00:00Z"),
    ]
    for window_start, window_end in windows:
        quote, _ = build_quote(
            customer["id"], branch["id"], product["id"], [MASTER_LINE]
        )
        issue_quote(quote["id"], issuer="rep-2")
        order = convert_quote(quote["id"], issuer="rep-2")
        run_allocator(order["id"], branch["id"], policy="MINIMIZE_REMNANT")
        for allocation in allocations_of_order(order["id"]):
            commit_pick(allocation["id"], branch["id"])
        run = schedule_run(
            order["id"], truck["id"], branch["id"], window_start, window_end
        )
        dispatch_run(run["id"], truck["id"])
        deliver_run(run["id"], truck["id"])
        shipments.append(
            {
                "order": read_order(order["id"]),
                "order_line": list_order_lines(sales_order_id=order["id"])[0],
            }
        )
    return {
        "branch": branch, "customer": customer, "product": product,
        "reels": reels, "shipments": shipments,
    }


def test_return_at_exactly_sixty_elapsed_days_earns_the_full_credit(api):
    """PRD §3.9: "Elapsed days are the whole number of complete 86,400-second
    days between the order's `delivered_at` and the current logical instant,
    with any partial day discarded."
    PRD §3.9: "The window boundary is inclusive: a return at exactly sixty
    elapsed days still earns its full or half credit, and one at sixty-one
    earns nothing."
    PRD §3.9: "The credited amount is the part's `reel_deposit_cents`
    multiplied by that rate and rounded half up to whole cents."

    Design: Difficulty/boundary_precision_check/deposit_return_window_boundary_at_exactly_60_elapsed_days
    """
    world = _two_delivered_master_orders()
    shipment = world["shipments"][0]

    set_clock("2026-09-30T00:00:00Z")
    return_reel(
        shipment["order_line"]["id"], world["reels"][0]["id"],
        world["branch"]["id"], condition="GOOD",
    )

    order = read_order(shipment["order"]["id"])
    assert order["deposit_charged_cents"] == 12500
    assert order["deposit_credited_cents"] == 12500
    assert order["billing_status"] == "CREDITED"
    assert read_reel(world["reels"][0]["id"])["status"] == "IN_STOCK"


def test_return_at_sixty_one_elapsed_days_earns_no_credit_at_all(api):
    """PRD §3.9: "Beyond sixty elapsed days no credit is earned at all,
    whatever the condition, and the rate is 0.00."
    PRD §3.9: "The window boundary is inclusive: a return at exactly sixty
    elapsed days still earns its full or half credit, and one at sixty-one
    earns nothing."
    PRD §3.9: "The customer's `deposit_liability_cents` falls by the part's
    *full* `reel_deposit_cents` regardless of the credit rate — the reel is
    back, so the liability is discharged even when the customer is not paid
    for it — while the customer's `open_balance_cents` falls only by the
    credited amount."

    Design: Difficulty/boundary_precision_check/deposit_return_window_boundary_at_exactly_60_elapsed_days
    """
    world = _two_delivered_master_orders()
    first, second = world["shipments"]

    set_clock("2026-09-30T00:00:00Z")
    return_reel(
        first["order_line"]["id"], world["reels"][0]["id"],
        world["branch"]["id"], condition="GOOD",
    )
    set_clock("2026-10-01T00:00:00Z")
    return_reel(
        second["order_line"]["id"], world["reels"][1]["id"],
        world["branch"]["id"], condition="GOOD",
    )

    late_order = read_order(second["order"]["id"])
    assert late_order["deposit_charged_cents"] == 12500
    assert late_order["deposit_credited_cents"] == 0
    assert late_order["billing_status"] == "CREDITED"

    account = read_customer(world["customer"]["id"])
    assert account["deposit_liability_cents"] == 0
    assert account["open_balance_cents"] == 152626
    assert read_reel(world["reels"][1]["id"])["status"] == "IN_STOCK"


# ══════════════════════════════════════════════════════════════════════════
# The return is gated on the parent order having reached DELIVERED
# ══════════════════════════════════════════════════════════════════════════

def _staged_but_undelivered_master_order():
    return setup_staged_order_by_pick(
        [MASTER_LINE], reels=[{"nominal_length_ft": 2500}]
    )


def test_returning_before_the_order_is_delivered_is_rejected(api):
    """PRD §3.9: "Four checks run in exactly this sequence, and the first
    failure is what the caller sees. The order must have reached `DELIVERED`
    on its fulfilment axis, otherwise `ERR_ORDER_NOT_DELIVERED`."
    PRD §3.5: "and `returnable` is true exactly when `put_up` is
    `MASTER_REEL`, false for a `CUT` line, because cut cable ships on a
    disposable reel that never comes back."

    Design: Difficulty/cross_entity_state_dependency/reel_return_gated_by_sales_order_reaching_delivered
    """
    scn = _staged_but_undelivered_master_order()
    order_line = list_order_lines(sales_order_id=scn["order"]["id"])[0]

    response = api.return_order_line_reel(
        order_line["id"],
        return_reel_payload(scn["reels"][0]["id"], "GOOD"),
        make_branch_ops_headers(scn["branch"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_ORDER_NOT_DELIVERED.value)
    assert read_order_line(order_line["id"])["returnable"] is True
    order = read_order(scn["order"]["id"])
    assert order["fulfillment_status"] == "STAGED"
    assert order["billing_status"] == "UNBILLED"


def test_a_rejected_return_leaves_the_deposit_ledger_untouched(api):
    """PRD §3.9: "The order's `deposit_credited_cents` rises by the credited
    amount."
    PRD §3.8: "Separately, `deposit_charged_cents` is set to the sum of the
    `reel_deposit_cents` of the parts behind every `PICK`-committed allocation
    on the order."
    PRD §3.7: "The reel's `current_length_ft`, `allocated_length_ft` and
    `status` are all left exactly as they are, because the whole reel travels
    intact and stays reserved to this order until it physically leaves."

    Design: Difficulty/cross_entity_state_dependency/reel_return_gated_by_sales_order_reaching_delivered
    """
    scn = _staged_but_undelivered_master_order()
    order_line = list_order_lines(sales_order_id=scn["order"]["id"])[0]

    response = api.return_order_line_reel(
        order_line["id"],
        return_reel_payload(scn["reels"][0]["id"], "GOOD"),
        make_branch_ops_headers(scn["branch"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ORDER_NOT_DELIVERED.value)

    assert read_order(scn["order"]["id"])["deposit_credited_cents"] == 0
    assert read_reel(scn["reels"][0]["id"])["status"] == "ALLOCATED_PARTIAL"
    assert read_customer(scn["customer"]["id"])["deposit_liability_cents"] == 0


# ══════════════════════════════════════════════════════════════════════════
# The deposit liability is conserved across delivery and return
# ══════════════════════════════════════════════════════════════════════════

def _two_reel_shipment_returned_in_full():
    scn = setup_delivered_master_reel_order(
        lines=[{"put_up": "MASTER_REEL", "requested_length_ft": 5000}],
        reels=[{"nominal_length_ft": 2500}, {"nominal_length_ft": 2500}],
    )
    set_clock("2026-08-15T00:00:00Z")
    order_line_id = scn["order_lines"][0]["id"]
    for reel in scn["reels"]:
        return_reel(order_line_id, reel["id"], scn["branch"]["id"], "GOOD")
    return scn


def test_deposit_liability_returns_to_zero_after_both_reels_come_home(api):
    """PRD §3.8: "Because the order was invoiced, the customer's
    `open_balance_cents` rises by `invoiced_total_cents` plus
    `deposit_charged_cents`, and their `deposit_liability_cents` rises by
    `deposit_charged_cents`."
    PRD §3.9: "A customer who has returned every reel therefore sees
    `deposit_liability_cents` back at exactly the value it held before the
    delivery, since that figure is by definition the sum of the
    `reel_deposit_cents` of the parts on every reel still `ON_JOBSITE` against
    that customer's orders."

    Design: Difficulty/compensating_invariant/customer_deposit_liability_conserved_across_deliver_and_return
    """
    scn = _two_reel_shipment_returned_in_full()

    order = read_order(scn["order"]["id"])
    assert order["deposit_charged_cents"] == 25000
    assert order["deposit_credited_cents"] == 25000
    assert order["billing_status"] == "CREDITED"
    assert read_customer(scn["customer"]["id"])["deposit_liability_cents"] == 0


def test_open_balance_settles_back_at_the_invoiced_total(api):
    """PRD §3.9: "The order's `deposit_credited_cents` rises by the credited
    amount. The customer's `deposit_liability_cents` falls by the part's
    *full* `reel_deposit_cents` regardless of the credit rate — the reel is
    back, so the liability is discharged even when the customer is not paid
    for it — while the customer's `open_balance_cents` falls only by the
    credited amount."
    PRD §3.9: "A valid return moves the reel `ON_JOBSITE → IN_STOCK` and
    clears its `delivered_at` back to null. Its `delivered_sales_order_id` is
    deliberately retained: that field is the permanent shipment record, not a
    flag for whether the reel is out, and keeping it is what causes a second
    return of the same reel to be caught by the jobsite-status check rather
    than by the identity check."

    Design: Difficulty/compensating_invariant/customer_deposit_liability_conserved_across_deliver_and_return
    """
    scn = _two_reel_shipment_returned_in_full()

    order = read_order(scn["order"]["id"])
    assert order["quoted_total_cents"] == 131625
    assert order["invoiced_total_cents"] == 131625
    assert read_customer(scn["customer"]["id"])["open_balance_cents"] == 131625

    first = read_reel(scn["reels"][0]["id"])
    assert first["status"] == "IN_STOCK"
    assert first["delivered_sales_order_id"] == scn["order"]["id"]
    assert first["delivered_at"] is None
    second = read_reel(scn["reels"][1]["id"])
    assert second["status"] == "IN_STOCK"
    assert second["current_length_ft"] == 2500


# ══════════════════════════════════════════════════════════════════════════
# Return corners
# ══════════════════════════════════════════════════════════════════════════

def test_a_damaged_reel_earns_half_the_deposit(api):
    """PRD §3.9: "Inside a sixty-day return window, a reel handed back in
    `GOOD` condition earns the full deposit — a credit rate of 1.00 — and a
    reel handed back `DAMAGED` earns half of it, a rate of 0.50."
    PRD §3.9: "The credited amount is the part's `reel_deposit_cents`
    multiplied by that rate and rounded half up to whole cents."
    PRD §3.9: "The customer's `deposit_liability_cents` falls by the part's
    *full* `reel_deposit_cents` regardless of the credit rate — the reel is
    back, so the liability is discharged even when the customer is not paid
    for it — while the customer's `open_balance_cents` falls only by the
    credited amount."

    Design: Corner/calculations/damaged_reel_return_credits_half_the_deposit
    """
    scn = setup_delivered_master_reel_order()
    set_clock("2026-08-05T00:00:00Z")

    response = api.return_order_line_reel(
        scn["order_lines"][0]["id"],
        return_reel_payload(scn["reels"][0]["id"], "DAMAGED"),
        make_branch_ops_headers(scn["branch"]["id"]),
    )
    validate_success(response, 200)

    order = read_order(scn["order"]["id"])
    assert order["deposit_charged_cents"] == 12500
    assert order["deposit_credited_cents"] == 6250
    assert order["billing_status"] == "CREDITED"
    account = read_customer(scn["customer"]["id"])
    assert account["deposit_liability_cents"] == 0
    assert account["open_balance_cents"] == 76313
    assert read_reel(scn["reels"][0]["id"])["status"] == "IN_STOCK"


def test_a_cut_line_is_never_returnable_even_after_delivery(api):
    """PRD §3.9: "The order line must be `returnable`, otherwise
    `ERR_CUT_ITEM_NON_RETURNABLE` — a cut item is never returnable, and this
    check deliberately precedes the identity check because a `CUT` line never
    shipped a returnable reel and would otherwise always fail on identity
    instead."
    PRD §3.5: "and `returnable` is true exactly when `put_up` is
    `MASTER_REEL`, false for a `CUT` line, because cut cable ships on a
    disposable reel that never comes back."

    Design: Corner/validations/cut_line_is_non_returnable_even_after_delivery
    """
    scn = setup_staged_order_by_cut(
        [CUT_LINE], reels=[{"nominal_length_ft": 1000}],
        truck_overrides={"truck_code": "T-1"},
    )
    deliver_order(scn, "2026-08-03T08:00:00Z", "2026-08-03T10:00:00Z")
    order_line = list_order_lines(sales_order_id=scn["order"]["id"])[0]

    response = api.return_order_line_reel(
        order_line["id"],
        return_reel_payload(scn["reels"][0]["id"], "GOOD"),
        make_branch_ops_headers(scn["branch"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_CUT_ITEM_NON_RETURNABLE.value)
    assert read_order_line(order_line["id"])["returnable"] is False
    order = read_order(scn["order"]["id"])
    assert order["fulfillment_status"] == "DELIVERED"
    assert order["billing_status"] == "INVOICED"
    assert order["deposit_charged_cents"] == 0
    assert order["deposit_credited_cents"] == 0

    remnants = list_reels(parent_reel_id=scn["reels"][0]["id"])
    assert len(remnants) == 1
    assert remnants[0]["current_length_ft"] == 700


def test_returning_a_reel_that_never_shipped_on_this_order_is_rejected(api):
    """PRD §3.9: "The reel's `delivered_sales_order_id` must equal the order
    line's `sales_order_id`, otherwise `ERR_REEL_NOT_ON_ORDER_LINE`."
    PRD §3.8: "Each consumed allocation whose `commit_mode` is `PICK` sends
    its reel `ALLOCATED_PARTIAL → ON_JOBSITE`, sets that reel's
    `delivered_sales_order_id` to the order's identifier and its
    `delivered_at` to the current instant, and zeroes its
    `allocated_length_ft`; the reel is now out at the customer's site,
    contributing nothing to branch availability."

    Design: Corner/validations/returning_a_reel_from_another_shipment_returns_reel_not_on_order_line
    """
    scn = setup_delivered_master_reel_order()
    stay_at_home = receive_reel(
        scn["product"]["id"], scn["branch"]["id"], 900, lot_code="L2"
    )

    response = api.return_order_line_reel(
        scn["order_lines"][0]["id"],
        return_reel_payload(stay_at_home["id"], "GOOD"),
        make_branch_ops_headers(scn["branch"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_REEL_NOT_ON_ORDER_LINE.value)
    stranger = read_reel(stay_at_home["id"])
    assert stranger["status"] == "IN_STOCK"
    assert stranger["delivered_sales_order_id"] is None
    assert read_reel(scn["reels"][0]["id"])["status"] == "ON_JOBSITE"
    assert read_customer(scn["customer"]["id"])["deposit_liability_cents"] == 12500
    order = read_order(scn["order"]["id"])
    assert order["deposit_credited_cents"] == 0
    assert order["billing_status"] == "INVOICED"


def test_returning_the_same_reel_twice_is_caught_by_the_jobsite_check(api):
    """PRD §3.9: "And the reel must currently be `ON_JOBSITE`, otherwise
    `ERR_REEL_NOT_ON_JOBSITE`."
    PRD §3.9: "Its `delivered_sales_order_id` is deliberately retained: that
    field is the permanent shipment record, not a flag for whether the reel is
    out, and keeping it is what causes a second return of the same reel to be
    caught by the jobsite-status check rather than by the identity check."

    Design: Corner/validations/second_return_of_the_same_reel_returns_reel_not_on_jobsite
    """
    scn = setup_delivered_master_reel_order()
    set_clock("2026-08-05T00:00:00Z")
    return_reel(
        scn["order_lines"][0]["id"], scn["reels"][0]["id"],
        scn["branch"]["id"], "GOOD",
    )

    response = api.return_order_line_reel(
        scn["order_lines"][0]["id"],
        return_reel_payload(scn["reels"][0]["id"], "GOOD"),
        make_branch_ops_headers(scn["branch"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_REEL_NOT_ON_JOBSITE.value)
    order = read_order(scn["order"]["id"])
    assert order["deposit_credited_cents"] == 12500, (
        "the deposit is credited exactly once"
    )
    account = read_customer(scn["customer"]["id"])
    assert account["deposit_liability_cents"] == 0
    assert account["open_balance_cents"] == 70063
    reel = read_reel(scn["reels"][0]["id"])
    assert reel["status"] == "IN_STOCK"
    assert reel["delivered_sales_order_id"] == scn["order"]["id"]
