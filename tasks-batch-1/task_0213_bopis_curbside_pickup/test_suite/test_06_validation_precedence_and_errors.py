"""Validation precedence pairs and single-failure business-rule errors.

Difficulty queue A (priority_pair_validation_conflict) plus corner validation claims.
The PRD §2.12 states the precedence order verbatim, so the dual-failure ordering tests
are PRD-derivable.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_customer_headers, make_manager_headers,
    factories as f, fixtures as fx,
)


def test_blocked_customer_beats_insufficient_availability(api):
    """PRD §2.12: "This ordering matters: for instance, on a submission, a stale slot
    version surfaces before the slot-store match, which surfaces before the cutoff
    check, the blocked-customer gate, the capacity check, and the availability check."
    PRD §3.3: "the acting customer's `pickup_standing` is not `BLOCKED` (otherwise
    `ERR_CUSTOMER_BLOCKED`)"

    Design: Difficulty/priority_pair_validation_conflict/customer_blocked_safety_beats_insufficient_availability_fiscal
    """
    # Drive the customer to 4 strikes (BLOCKED), then make availability insufficient too.
    setup = fx.raise_customer_to_strikes(4, hold_window_minutes=60)
    customer, store, product, inv, slot = (
        setup["customer"], setup["store"], setup["product"], setup["inventory"], setup["slot"])
    assert customer["no_show_strikes"] == 4 and customer["pickup_standing"] == "BLOCKED", customer

    # inventory on_hand is back to 1 after the last expiry; drop it to 0 so availability fails too.
    inv_v = fx.get_inventory_version(inv["id"])
    validate_success(api.restock_inventory(inv["id"], f.restock_payload(-1, inv_v), make_manager_headers()))

    fx.set_clock("2026-06-05T00:00:00Z")
    slot_v = fx.get_slot_version(slot["id"])
    order = fx.create_draft_order(customer["id"], store["id"])
    fx.add_line(order["id"], customer["id"], product["id"], 5)  # qty 5 > available 0
    resp = api.submit_order(order["id"], f.submit_order_payload(slot["id"], slot_v),
                            make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_BLOCKED.value)


def test_blocked_customer_standing_reflected_on_fetch(api):
    """PRD §2.9: "The boundary cases are exact: at exactly 2 strikes the standing is
    `WATCH`, and at exactly 4 strikes the standing is `BLOCKED`."
    PRD §2.9: "A `BLOCKED` customer cannot submit new orders; a `WATCH` customer is
    permitted to submit but is flagged with the distinct posture."

    Design: Difficulty/priority_pair_validation_conflict/customer_blocked_safety_beats_insufficient_availability_fiscal
    """
    setup = fx.raise_customer_to_strikes(4, hold_window_minutes=60)
    customer = validate_success(api.get_customer(setup["customer"]["id"], make_manager_headers()))
    assert customer["no_show_strikes"] == 4, customer
    assert customer["pickup_standing"] == "BLOCKED", customer


def test_slot_cutoff_passed_beats_slot_full(api):
    """PRD §2.12: "This ordering matters: for instance, on a submission, a stale slot
    version surfaces before the slot-store match, which surfaces before the cutoff
    check, the blocked-customer gate, the capacity check, and the availability check."
    PRD §3.3: "the booking is before the slot's cutoff, meaning the clock is strictly
    earlier than `window_start` minus `cutoff_offset_minutes` (otherwise
    `ERR_SLOT_CUTOFF_PASSED`)"

    Design: Difficulty/priority_pair_validation_conflict/slot_cutoff_temporal_beats_slot_full_fiscal
    """
    # Slot capacity 1, window_start 10:00, cutoff 30 -> cutoff at 09:30. O1 books (FULL)
    # at 09:00; O2 attempts after clock advances to 09:45 (past cutoff AND slot full).
    base = fx.seed_base_scenario(products=[{"price": 1000, "on_hand": 10}], capacity=1,
                                 clock="2026-06-01T09:00:00Z",
                                 window_start="2026-06-01T10:00:00Z",
                                 window_end="2026-06-01T11:00:00Z",
                                 cutoff_offset_minutes=30)
    store_id, slot_id, product_id = base["store"]["id"], base["slot"]["id"], base["products"][0]["id"]
    c1 = base["customer"]
    o1 = fx.create_draft_order(c1["id"], store_id)
    fx.add_line(o1["id"], c1["id"], product_id, 1)
    fx.submit_order(o1["id"], c1["id"], slot_id, fx.get_slot_version(slot_id))  # slot FULL

    c2 = fx.create_customer()
    o2 = fx.create_draft_order(c2["id"], store_id)
    fx.add_line(o2["id"], c2["id"], product_id, 1)
    slot_v = fx.get_slot_version(slot_id)
    fx.set_clock("2026-06-01T09:45:00Z")  # past cutoff 09:30
    resp = api.submit_order(o2["id"], f.submit_order_payload(slot_id, slot_v),
                            make_customer_headers(c2["id"]))
    validate_error(resp, ApiErrorId.ERR_SLOT_CUTOFF_PASSED.value)


def test_slot_full_before_cutoff_pair_setup_slot_is_full(api):
    """PRD §2.7: "when `booked_count` equals capacity the slot is `FULL` and further
    booking is refused."

    Design: Difficulty/priority_pair_validation_conflict/slot_cutoff_temporal_beats_slot_full_fiscal
    """
    base = fx.seed_base_scenario(products=[{"price": 1000, "on_hand": 10}], capacity=1,
                                 clock="2026-06-01T09:00:00Z",
                                 window_start="2026-06-01T10:00:00Z",
                                 window_end="2026-06-01T11:00:00Z",
                                 cutoff_offset_minutes=30)
    store_id, slot_id, product_id = base["store"]["id"], base["slot"]["id"], base["products"][0]["id"]
    c1 = base["customer"]
    o1 = fx.create_draft_order(c1["id"], store_id)
    fx.add_line(o1["id"], c1["id"], product_id, 1)
    fx.submit_order(o1["id"], c1["id"], slot_id, fx.get_slot_version(slot_id))
    slot_state = validate_success(api.get_pickup_slot(slot_id, make_manager_headers()))
    assert slot_state["fill_status"] == "FULL", slot_state
    assert slot_state["booked_count"] == 1 == slot_state["capacity"], slot_state


# --- Corner: single-failure business-rule errors ---------------------------

def test_substitution_group_mismatch_rejected(api):
    """PRD §3.5: "The proposal is allowed only when the original line is `SHORT_PICKED`,
    the original product's `substitution_group` is non-null, and the substitute product
    shares that exact same group key; a mismatched or null group is rejected with
    `ERR_SUBSTITUTION_GROUP_MISMATCH`."

    Design: Corner/validations/substitution_group_mismatch_rejected
    """
    # original group BREAD, substitute group MILK
    base = fx.seed_base_scenario(products=[
        {"price": 1500, "substitution_group": "BREAD", "on_hand": 5},
        {"price": 1500, "substitution_group": "MILK", "on_hand": 5},
    ])
    customer = base["customer"]
    order, lines = fx.create_order_with_lines(
        customer["id"], base["store"]["id"], base["slot"]["id"], base["slot_version"],
        [(base["products"][0]["id"], 2)])
    fx.start_picking(order["id"])
    fx.pick_line(lines[0]["id"], 0)
    resp = api.create_substitution(
        f.create_substitution_payload(lines[0]["id"], base["products"][1]["id"], 2),
        fx.make_picker_headers())
    validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_GROUP_MISMATCH.value)


def test_slot_store_mismatch_rejected(api):
    """PRD §3.3: "the supplied slot exists and its `store_id` equals the order's
    `store_id` (otherwise `ERR_SLOT_STORE_MISMATCH`)"

    Design: Corner/validations/slot_store_mismatch_rejected
    """
    s1 = fx.create_store()
    s2 = fx.create_store()
    product = fx.create_product()
    fx.create_inventory(s1["id"], product["id"], on_hand=5)
    fx.set_clock("2026-06-01T00:00:00Z")
    slot2 = fx.create_slot(s2["id"])  # slot belongs to S2
    customer = fx.create_customer()
    order = fx.create_draft_order(customer["id"], s1["id"])  # order at S1
    fx.add_line(order["id"], customer["id"], product["id"], 1)
    resp = api.submit_order(order["id"], f.submit_order_payload(slot2["id"], slot2["version"]),
                            make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_SLOT_STORE_MISMATCH.value)


def test_over_handover_exceeds_qty_picked_rejected(api):
    """PRD §3.6: "for each requested line the handed-over quantity must not exceed that
    line's `qty_picked` (otherwise `ERR_OVER_HANDOVER`)."

    Design: Corner/validations/over_handover_exceeds_qty_picked_rejected
    """
    s = fx.setup_awaiting_pickup_order([{"price": 1000, "qty": 2}])
    order, lines = s["order"], s["lines"]
    resp = api.pickup_order(order["id"], f.pickup_payload([f.handover(lines[0]["id"], 3)]),
                            fx.make_associate_headers())
    validate_error(resp, ApiErrorId.ERR_OVER_HANDOVER.value)


def test_insufficient_on_hand_at_pick_rejected(api):
    """PRD §3.4: "A physical pick whose `qty_picked` exceeds the inventory's `on_hand`
    is rejected with `ERR_INSUFFICIENT_ON_HAND`."

    Design: Corner/validations/insufficient_on_hand_at_pick_rejected
    """
    # reserve 2 against on_hand 2, then restock -1 to on_hand 1, then pick 2.
    base = fx.seed_base_scenario(products=[{"price": 1000, "on_hand": 2}])
    inv = base["inventories"][0]
    customer = base["customer"]
    order, lines = fx.create_order_with_lines(
        customer["id"], base["store"]["id"], base["slot"]["id"], base["slot_version"],
        [(base["products"][0]["id"], 2)])
    fx.start_picking(order["id"])
    inv_v = fx.get_inventory_version(inv["id"])
    validate_success(api.restock_inventory(inv["id"], f.restock_payload(-1, inv_v), make_manager_headers()))
    resp = api.pick_line(lines[0]["id"], {"qty_picked": 2}, fx.make_picker_headers())
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ON_HAND.value)


def test_insufficient_availability_at_submit_rejected(api):
    """PRD §3.3: "for every order line, the `available` quantity of the store-and-product
    inventory row is at least that line's `qty_ordered` (otherwise
    `ERR_INSUFFICIENT_AVAILABILITY`)."

    Design: Corner/validations/insufficient_availability_at_submit
    """
    base = fx.seed_base_scenario(products=[{"price": 1000, "on_hand": 1}])
    customer = base["customer"]
    order = fx.create_draft_order(customer["id"], base["store"]["id"])
    fx.add_line(order["id"], customer["id"], base["products"][0]["id"], 3)  # qty 3 > available 1
    resp = api.submit_order(order["id"], f.submit_order_payload(base["slot"]["id"], base["slot_version"]),
                            make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_AVAILABILITY.value)
