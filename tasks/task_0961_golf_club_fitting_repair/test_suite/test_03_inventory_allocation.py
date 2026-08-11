"""Component stock: the allocation sweep cascades (receipt and ticket-cancel
triggers), FIFO ordering, the conserved-quantity invariant, and order
discovery."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, api_client,
    set_clock, create_customer, create_specialist, create_technician,
    create_manager, create_bay, create_completed_session, book_session,
    create_component_trio, create_component_item, create_draft_spec,
    quote_spec, approve_spec, mark_ready, get_spec, get_component_item,
    get_order_for_spec, customer_headers, staff_headers,
    create_repair_ticket, pay_ticket, assert_stock_conserved,
)


def _setup_backordered_spec():
    """Spec approved with all three items at initial_stock 0 -> order BACKORDERED."""
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Hal Heath")
    specialist = create_specialist()
    ctx = create_completed_session(customer, specialist)
    items = create_component_trio(head_stock=0, shaft_stock=0, grip_stock=0)
    spec = create_draft_spec(customer, ctx["session"], items, specialist, labor_cents=15_000)
    spec = quote_spec(spec, specialist)
    spec = approve_spec(spec, customer, "EXTERNAL")
    order = get_order_for_spec(spec["id"])
    return {"customer": customer, "specialist": specialist,
            "items": items, "spec": spec, "order": order}


def test_receipt_cascade_partial_receipt_keeps_order_backordered(api):
    """PRD §3.3: "an order with at least one short line becomes `BACKORDERED`
    and keeps its partial allocations, with the remainders pending."

    Design: Difficulty/transitive_cascade/stock_receipt_cascades_order_to_spec
    """
    ctx = _setup_backordered_spec()
    spec, order, items = ctx["spec"], ctx["order"], ctx["items"]
    manager = create_manager()
    mh = staff_headers(manager)

    assert order["status"] == "BACKORDERED"
    assert spec["status"] == "ORDERED", (
        f"spec must be stuck in ORDERED while its order is short, got {spec['status']}"
    )

    # Receiving only the head cannot complete the order.
    get_success_data(api_client.receive_component_item(items["head"]["id"], {"qty": 1}, mh))
    order = get_success_data(api_client.get_component_order(order["id"], mh))
    assert order["status"] == "BACKORDERED", (
        f"sweep cannot complete the order after only one receipt, got {order['status']}"
    )
    spec = get_spec(spec["id"], mh)
    assert spec["status"] == "ORDERED"


def test_receipt_cascade_completes_order_and_advances_spec(api):
    """PRD §3.3: "Later supplier deliveries are recorded by a `ShopManager` as
    a receipt of `qty` units, which adds `qty` to both `stock_on_hand` and
    `received_total`" and "When a later stock event finally satisfies a
    backordered order's remainders, the same per-line stock mutations complete
    and the order flips `BACKORDERED` to `ALLOCATED` with the same
    parent-spec advance."

    Design: Difficulty/transitive_cascade/stock_receipt_cascades_order_to_spec
    """
    ctx = _setup_backordered_spec()
    spec, order, items = ctx["spec"], ctx["order"], ctx["items"]
    manager = create_manager()
    mh = staff_headers(manager)

    for item in (items["head"], items["shaft"], items["grip"]):
        get_success_data(api_client.receive_component_item(item["id"], {"qty": 1}, mh))

    order = get_success_data(api_client.get_component_order(order["id"], mh))
    assert order["status"] == "ALLOCATED", (
        f"expected ALLOCATED after all three receipts, got {order['status']}"
    )
    spec = get_spec(spec["id"], mh)
    assert spec["status"] == "IN_BUILD", (
        f"parent spec must advance ORDERED -> IN_BUILD, got {spec['status']}"
    )
    head = get_component_item(items["head"]["id"], mh)
    assert head["stock_on_hand"] == 0 and head["stock_reserved"] == 1
    assert head["received_total"] == 1
    assert_stock_conserved(head)


def _setup_cancel_release_scenario():
    """RESHAFT ticket IN_PROGRESS holding the only shaft; approved spec whose
    order is BACKORDERED (head+grip allocated, shaft short)."""
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Ivy Iris")
    technician = create_technician()
    specialist = create_specialist()
    ctx = create_completed_session(customer, specialist)
    head = create_component_item("HEAD", 40_000, 55_000, 1)
    shaft = create_component_item("SHAFT", 12_000, 18_000, 1)
    grip = create_component_item("GRIP", 800, 1_500, 1)

    ticket = create_repair_ticket(customer, "RESHAFT", False, shaft,
                                  club_description="driver")
    ticket = get_success_data(
        api_client.approve_repair_ticket(ticket["id"], customer_headers(customer))
    )
    ticket = pay_ticket(ticket, customer, "DEPOSIT")
    ticket = get_success_data(
        api_client.start_work(ticket["id"], staff_headers(technician))
    )

    items = {"head": head, "shaft": shaft, "grip": grip}
    spec = create_draft_spec(customer, ctx["session"], items, specialist, labor_cents=15_000)
    spec = quote_spec(spec, specialist)
    spec = approve_spec(spec, customer, "EXTERNAL")
    order = get_order_for_spec(spec["id"])
    return {"customer": customer, "technician": technician, "specialist": specialist,
            "items": items, "ticket": ticket, "spec": spec, "order": order}


def test_ticket_cancel_release_flips_waiting_order_and_spec(api):
    """PRD §3.5: "A held shaft reservation — a ticket cancelled from
    `IN_PROGRESS` with a `shaft_item_id` — is released: `stock_reserved` drops
    by one, `stock_on_hand` rises by one, and the release triggers the
    allocation sweep over backordered and pending component orders, so a
    cancelled reshaft can unblock a waiting build."

    Design: Difficulty/transitive_cascade/ticket_cancel_shaft_release_cascades_to_spec
    """
    ctx = _setup_cancel_release_scenario()
    manager = create_manager()
    mh = staff_headers(manager)

    shaft = get_component_item(ctx["items"]["shaft"]["id"], mh)
    assert shaft["stock_on_hand"] == 0 and shaft["stock_reserved"] == 1
    assert ctx["order"]["status"] == "BACKORDERED"
    assert ctx["spec"]["status"] == "ORDERED"

    ticket = get_success_data(
        api_client.cancel_ticket(ctx["ticket"]["id"], customer_headers(ctx["customer"]))
    )
    assert ticket["work_status"] == "CANCELLED"

    order = get_success_data(api_client.get_component_order(ctx["order"]["id"], mh))
    assert order["status"] == "ALLOCATED", (
        f"sweep caused by the shaft release must allocate the waiting order, "
        f"got {order['status']}"
    )
    spec = get_spec(ctx["spec"]["id"], mh)
    assert spec["status"] == "IN_BUILD", (
        f"parent spec must advance to IN_BUILD, got {spec['status']}"
    )


def test_ticket_cancel_release_re_reserves_released_unit(api):
    """PRD §2.9: "`stock_on_hand` — the only figure the allocation logic
    consults — is the unreserved physical stock, always equal to
    `received_total` minus `stock_reserved` minus `consumed_total`." and
    "every stock event re-runs the allocation sweep described in Section 3.3."

    Design: Difficulty/transitive_cascade/ticket_cancel_shaft_release_cascades_to_spec
    """
    ctx = _setup_cancel_release_scenario()
    manager = create_manager()
    mh = staff_headers(manager)

    get_success_data(
        api_client.cancel_ticket(ctx["ticket"]["id"], customer_headers(ctx["customer"]))
    )
    shaft = get_component_item(ctx["items"]["shaft"]["id"], mh)
    # The released unit is immediately re-reserved by the sweep for the waiting order.
    assert shaft["stock_on_hand"] == 0, (
        f"released unit must be re-reserved by the sweep, on_hand={shaft['stock_on_hand']}"
    )
    assert shaft["stock_reserved"] == 1
    assert_stock_conserved(shaft)


def test_inventory_conserved_across_reserve_and_release(api):
    """PRD §2.9: "Reservations move units from on-hand to reserved; consumption
    moves them from reserved to consumed; releases move them from reserved
    back to on-hand." and "always equal to `received_total` minus
    `stock_reserved` minus `consumed_total`."

    Design: Difficulty/compensating_invariant/inventory_quantity_conserved_across_reserve_release_consume
    """
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Rae River")
    specialist = create_specialist()
    technician = create_technician()
    ctx = create_completed_session(customer, specialist)
    items = create_component_trio(head_stock=5, shaft_stock=5, grip_stock=5)
    manager = create_manager()
    mh = staff_headers(manager)
    head_id = items["head"]["id"]

    spec_a = quote_spec(
        create_draft_spec(customer, ctx["session"], items, specialist), specialist)
    spec_b = quote_spec(
        create_draft_spec(customer, ctx["session"], items, specialist), specialist)

    approve_spec(spec_a, customer, "EXTERNAL")
    head = get_component_item(head_id, mh)
    assert (head["stock_on_hand"], head["stock_reserved"], head["consumed_total"]) == (4, 1, 0), (
        f"after reserve expected (4,1,0), got {(head['stock_on_hand'], head['stock_reserved'], head['consumed_total'])}"
    )
    assert_stock_conserved(head)

    get_success_data(api_client.cancel_build_spec(spec_a["id"], customer_headers(customer)))
    head = get_component_item(head_id, mh)
    assert (head["stock_on_hand"], head["stock_reserved"], head["consumed_total"]) == (5, 0, 0), (
        "compensating release must leave zero drift"
    )
    assert_stock_conserved(head)


def test_inventory_conserved_across_reserve_and_consume(api):
    """PRD §3.4: "marking the parent spec ready turns an `ALLOCATED` order
    `CLOSED` by consuming its reserved units" (§3.3) and "each line's
    allocated units are consumed, moving from `stock_reserved` into
    `consumed_total`."

    Design: Difficulty/compensating_invariant/inventory_quantity_conserved_across_reserve_release_consume
    """
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Rae River")
    specialist = create_specialist()
    technician = create_technician()
    ctx = create_completed_session(customer, specialist)
    items = create_component_trio(head_stock=5, shaft_stock=5, grip_stock=5)
    manager = create_manager()
    mh = staff_headers(manager)
    head_id = items["head"]["id"]

    spec_b = quote_spec(
        create_draft_spec(customer, ctx["session"], items, specialist), specialist)
    spec_b = approve_spec(spec_b, customer, "EXTERNAL")
    spec_b = mark_ready(spec_b, technician)
    assert spec_b["status"] == "READY"

    head = get_component_item(head_id, mh)
    assert (head["stock_on_hand"], head["stock_reserved"], head["consumed_total"]) == (4, 0, 1), (
        f"after consume expected (4,0,1), got {(head['stock_on_hand'], head['stock_reserved'], head['consumed_total'])}"
    )
    assert head["received_total"] == 5
    assert_stock_conserved(head)


def test_allocation_sweep_fifo_two_backordered_orders(api):
    """PRD §3.3: "The sweep considers only orders in `PENDING_ALLOCATION` or
    `BACKORDERED` — orders that are `ALLOCATED`, `CLOSED`, or `CANCELLED`
    never re-enter — and processes them oldest first by `created_at`, with
    exact timestamp ties broken by `required_units` ascending, never by id."

    Design: Corner/calculations/allocation_sweep_fifo_two_backordered_orders
    """
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Kit Kettle")
    specialist = create_specialist()
    bay = create_bay()
    session = book_session(customer, bay, specialist,
                           starts_at="2026-05-12T10:00:00Z",
                           ends_at="2026-05-12T11:00:00Z")
    set_clock("2026-05-12T10:05:00Z")
    fs = staff_headers(specialist)
    session = get_success_data(api_client.check_in_session(session["id"], fs))
    session = get_success_data(api_client.complete_session(session["id"], fs))

    head = create_component_item("HEAD", 40_000, 55_000, 2)
    shaft = create_component_item("SHAFT", 12_000, 18_000, 0)
    grip = create_component_item("GRIP", 800, 1_500, 2)
    items = {"head": head, "shaft": shaft, "grip": grip}

    spec1 = quote_spec(
        create_draft_spec(customer, session, items, specialist), specialist)
    spec1 = approve_spec(spec1, customer, "EXTERNAL")
    # Advance the clock so order2 is strictly younger than order1.
    set_clock("2026-05-12T10:06:00Z")
    spec2 = quote_spec(
        create_draft_spec(customer, session, items, specialist), specialist)
    spec2 = approve_spec(spec2, customer, "EXTERNAL")

    manager = create_manager()
    mh = staff_headers(manager)
    ord1 = get_order_for_spec(spec1["id"], mh)
    ord2 = get_order_for_spec(spec2["id"], mh)
    assert ord1["status"] == "BACKORDERED" and ord2["status"] == "BACKORDERED"

    get_success_data(api_client.receive_component_item(shaft["id"], {"qty": 1}, mh))

    ord1 = get_success_data(api_client.get_component_order(ord1["id"], mh))
    ord2 = get_success_data(api_client.get_component_order(ord2["id"], mh))
    assert ord1["status"] == "ALLOCATED", (
        f"earlier-created order must win the single shaft, got {ord1['status']}"
    )
    assert ord2["status"] == "BACKORDERED"
    shaft_line = [l for l in ord2["lines"] if l["component_item_id"] == shaft["id"]][0]
    assert shaft_line["allocated_qty"] == 0

    assert get_spec(spec1["id"], mh)["status"] == "IN_BUILD"
    assert get_spec(spec2["id"], mh)["status"] == "ORDERED"
    shaft_now = get_component_item(shaft["id"], mh)
    assert shaft_now["stock_on_hand"] == 0 and shaft_now["stock_reserved"] == 1


def test_component_order_discovery_filtered_list(api):
    """PRD §3.3: "Each one is born as a side effect of a customer approving a
    build spec, carrying the `build_spec_id` of its parent and a `lines` array
    of exactly three entries — one per component slot — each naming a
    `component_item_id`, a `required_qty` of one, and an `allocated_qty` that
    starts at zero; the order's `required_units` is therefore always three."
    and "Managers and specialists discover these cascade-created orders
    through the order read and list endpoints, the latter filterable by
    `build_spec_id` and `status`."

    Design: Corner/endpoints/component_order_discovery_filtered_list
    """
    # Spec approved with all components in stock: order auto-created and swept.
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Ada Aire")
    specialist = create_specialist()
    ctx2 = create_completed_session(customer, specialist)
    items = create_component_trio(head_stock=5, shaft_stock=5, grip_stock=5)
    spec = create_draft_spec(customer, ctx2["session"], items, specialist, labor_cents=15_000)
    spec = quote_spec(spec, specialist)
    spec = approve_spec(spec, customer, "EXTERNAL")

    manager = create_manager()
    mh = staff_headers(manager)
    orders = get_success_data(
        api_client.list_component_orders(mh, params={"build_spec_id": spec["id"]})
    )
    assert isinstance(orders, list) and len(orders) == 1, (
        f"exactly one cascade-created order expected, got {orders}"
    )
    order = orders[0]
    assert order["build_spec_id"] == spec["id"]
    assert order["status"] == "ALLOCATED", (
        f"in-stock order must be fully allocated by the sweep, got {order['status']}"
    )
    assert order["required_units"] == 3
    assert len(order["lines"]) == 3
    for line in order["lines"]:
        assert line["required_qty"] == 1 and line["allocated_qty"] == 1, (
            f"every line fully allocated: {line}"
        )
