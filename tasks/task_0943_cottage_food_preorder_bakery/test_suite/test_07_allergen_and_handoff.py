"""The consumer-safety block at confirmation, the two porch consents, the delivery
zone and minimum, route sequencing, rebooking and the pickup grace."""
import pytest
from test_helpers import (
    ApiErrorId,
    CLOCK_AT_HANDOFF,
    CLOCK_AT_PICKUP_FORFEIT,
    add_customer,
    add_line,
    add_menu_item,
    api_client,
    assert_same_instant,
    confirm_order,
    create_route,
    instant_plus,
    make_customer_headers,
    movements_of,
    open_order,
    read_capacity,
    read_label,
    read_line,
    read_order,
    read_window,
    set_clock,
    set_route_status,
    setup_delivery_order,
    setup_ready_pickup_order,
    setup_storefront,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_exactly_eight_kilometres_is_a_tier_one_delivery(api):
    """PRD §3.8: "The **delivery fee** is fixed at confirmation from three zone
    tiers, measured on the order's `delivery_distance_km`, and the tier upper bounds
    are **inclusive**. Up to and including 8.0 kilometres the fee is 500 cents;
    beyond that and up to and including 20.0 kilometres it is 900 cents; beyond that
    and up to and including 40.0 kilometres it is 1400 cents; beyond 40.0 kilometres
    the order is refused with `ERR_OUT_OF_PERMITTED_ZONE`."
    PRD §3.8: "Exactly 8.0 kilometres is therefore a tier-one order at 500 cents
    while 8.01 kilometres is a tier-two order at 900."
    PRD §3.5: "copies `delivery_distance_km` from the customer onto the order when
    the handoff mode is `DELIVERY` (it stays null for the two pickup modes)"

    Design: Difficulty/boundary_precision_check/delivery_zone_tier_upper_bound_is_inclusive
    """
    s = setup_storefront()
    edge = add_customer(
        s, "edge8", display_name="Edge Eight", email="eight@example.com",
        delivery_distance_km=8.0,
    )
    delivery = open_order(edge["id"], s.window_id, handoff_mode="DELIVERY")
    add_line(delivery["id"], s.cookie_id, 13, edge["id"], s.window_id)

    confirmed = confirm_order(delivery["id"], edge["id"])
    assert confirmed["delivery_distance_km"] == pytest.approx(8.0)
    assert confirmed["delivery_fee_cents"] == 500
    assert confirmed["subtotal_cents"] == 4600
    assert confirmed["tax_total_cents"] == 0
    assert confirmed["order_status"] == "CONFIRMED"


def test_eight_point_zero_one_kilometres_falls_into_tier_two(api):
    """PRD §3.8: "Exactly 8.0 kilometres is therefore a tier-one order at 500 cents
    while 8.01 kilometres is a tier-two order at 900."
    PRD §3.8: "The **delivery fee** is fixed at confirmation from three zone tiers,
    measured on the order's `delivery_distance_km`, and the tier upper bounds are
    **inclusive**."

    Design: Difficulty/boundary_precision_check/delivery_zone_tier_upper_bound_is_inclusive
    """
    s = setup_storefront()
    just_over = add_customer(
        s, "edge801", display_name="Edge Eight Oh One",
        email="eight01@example.com", delivery_distance_km=8.01,
    )
    delivery = open_order(just_over["id"], s.window_id, handoff_mode="DELIVERY")
    add_line(delivery["id"], s.cookie_id, 13, just_over["id"], s.window_id)

    confirmed = confirm_order(delivery["id"], just_over["id"])
    assert confirmed["delivery_distance_km"] == pytest.approx(8.01)
    assert confirmed["delivery_fee_cents"] == 900
    assert confirmed["subtotal_cents"] == 4600
    assert confirmed["order_status"] == "CONFIRMED"


def test_an_anaphylactic_avoidance_hard_blocks_despite_the_acknowledgement(api):
    """PRD §2.6: "Rung 29: no allergen in the order's allergen union matches an
    avoidance the acting customer has recorded at `ANAPHYLACTIC` severity, otherwise
    `ERR_ALLERGEN_HARD_BLOCK` (422) on order confirmation."
    PRD §3.5: "Because the hard block sits one rung above the acknowledgement
    requirement, an order matching one avoidance of each severity reports the hard
    block."
    PRD §3.5: "Any allergen in that union which the buyer has recorded as an
    avoidance at `ANAPHYLACTIC` severity is a hard block: the confirm is refused
    with `ERR_ALLERGEN_HARD_BLOCK` and no acknowledgement flag can clear it."

    Design: Corner/validations/anaphylactic_avoidance_hard_blocks_even_with_acknowledgement
    """
    s = setup_storefront()
    buyer = add_customer(
        s, "ana", display_name="Anaphylactic Ada", email="ana@example.com",
        delivery_distance_km=4.0,
        allergen_avoidances=[
            {"allergen": "milk", "severity": "ANAPHYLACTIC"},
            {"allergen": "wheat", "severity": "INTOLERANCE"},
        ],
    )
    order = open_order(buyer["id"], s.window_id)
    line = add_line(order["id"], s.cookie_id, 13, buyer["id"], s.window_id)

    rejected = api.confirm_order(
        order["id"], make_customer_headers(buyer["id"]), {"allergen_ack": True}
    )
    error = validate_error(rejected, ApiErrorId.ERR_ALLERGEN_HARD_BLOCK)
    assert error["error_id"] != "ERR_ALLERGEN_ACK_REQUIRED", (
        "wheat also matches at the INTOLERANCE tier, but rung 29 is lower than 30"
    )
    assert sorted(read_line(line["id"], make_customer_headers(buyer["id"]))[
        "allergen_union"
    ]) == ["milk", "wheat"]
    assert read_order(order["id"], s.bh)["order_status"] == "PENDING_HOLD"
    assert read_window(s.window_id, s.bh)["confirmed_units"] == 0


def test_an_intolerance_avoidance_needs_a_recorded_acknowledgement(api):
    """PRD §2.6: "Rung 30: where an allergen matches an avoidance recorded at
    `INTOLERANCE` severity, the order's `allergen_ack` is true, otherwise
    `ERR_ALLERGEN_ACK_REQUIRED` (422) on order confirmation."
    PRD §3.5: "Any allergen matching an avoidance recorded at `INTOLERANCE` severity
    is instead an acknowledgement requirement: the confirm succeeds provided the
    order's `allergen_ack` is true, and the acknowledgement is recorded on the order
    rather than blocking it; otherwise the refusal is `ERR_ALLERGEN_ACK_REQUIRED`."

    Design: Corner/validations/intolerance_avoidance_requires_a_recorded_acknowledgement
    """
    s = setup_storefront()
    buyer = add_customer(
        s, "int", display_name="Intolerant Ira", email="ira@example.com",
        delivery_distance_km=4.0,
        allergen_avoidances=[{"allergen": "milk", "severity": "INTOLERANCE"}],
    )
    headers = make_customer_headers(buyer["id"])
    order = open_order(buyer["id"], s.window_id)
    add_line(order["id"], s.cookie_id, 13, buyer["id"], s.window_id)

    rejected = api.confirm_order(order["id"], headers, {"allergen_ack": False})
    validate_error(rejected, ApiErrorId.ERR_ALLERGEN_ACK_REQUIRED)

    accepted = validate_success(
        api.confirm_order(order["id"], headers, {"allergen_ack": True})
    )
    assert accepted["order_status"] == "CONFIRMED"
    assert accepted["allergen_ack"] is True
    assert accepted["subtotal_cents"] == 4600
    capacity = read_capacity(s.window_id, s.bh)
    assert capacity["confirmed_units"] == 13
    assert capacity["held_units"] == 0


def test_a_porch_handoff_without_unattended_consent_is_refused(api):
    """PRD §2.6: "Rung 31: when the order's `handoff_mode` is `PORCH_SELF_SERVE`,
    its `unattended_consent` is true, otherwise `ERR_UNATTENDED_CONSENT_REQUIRED`
    (422) on handoff scheduling."
    PRD §3.8: "The request may carry `unattended_consent` and `cooler_provided` to
    satisfy the porch rungs"
    PRD §3.8: "For `PICKUP_COUNTER` and `PORCH_SELF_SERVE` orders the fee is 0 and
    the zone rule is not applied at all — no distance is examined for a pickup."

    Design: Corner/validations/porch_handoff_without_unattended_consent_is_rejected
    """
    s = setup_storefront()
    order = open_order(s.customer_id, s.window_id, handoff_mode="PORCH_SELF_SERVE")
    add_line(order["id"], s.cookie_id, 13, s.customer_id, s.window_id)
    confirm_order(order["id"], s.customer_id)

    rejected = api.schedule_handoff(order["id"], s.ch, {})
    validate_error(rejected, ApiErrorId.ERR_UNATTENDED_CONSENT_REQUIRED)

    scheduled = validate_success(
        api.schedule_handoff(order["id"], s.ch, {"unattended_consent": True})
    )
    assert scheduled["handoff_status"] == "SCHEDULED"
    assert scheduled["unattended_consent"] is True
    assert scheduled["delivery_fee_cents"] == 0


def test_a_temp_sensitive_porch_handoff_needs_a_cooler(api):
    """PRD §2.6: "Rung 32: when the order's `handoff_mode` is `PORCH_SELF_SERVE` and
    any pending line's menu item has `temp_sensitive` true, the order's
    `cooler_provided` is true, otherwise `ERR_COOLER_CONSENT_REQUIRED` (422) on
    handoff scheduling."
    PRD §3.3: "`temp_sensitive` (false by default) marks an item whose porch handoff
    requires a cooler"

    Design: Corner/validations/porch_handoff_of_a_temp_sensitive_item_requires_a_cooler
    """
    s = setup_storefront()
    add_menu_item(
        s, kind="cookie", key="temp", name="Cream Cheese Babka",
        pricing_basis="PER_UNIT", unit_price_cents=900, dozen_price_cents=9600,
        temp_sensitive=True,
    )
    order = open_order(
        s.customer_id, s.window_id, handoff_mode="PORCH_SELF_SERVE",
        unattended_consent=True,
    )
    add_line(order["id"], s.temp_id, 4, s.customer_id, s.window_id)
    confirmed = confirm_order(order["id"], s.customer_id)
    assert confirmed["subtotal_cents"] == 3600

    rejected = api.schedule_handoff(order["id"], s.ch, {})
    error = validate_error(rejected, ApiErrorId.ERR_COOLER_CONSENT_REQUIRED)
    assert error["error_id"] != "ERR_UNATTENDED_CONSENT_REQUIRED", (
        "unattended_consent was already true on the order"
    )

    scheduled = validate_success(
        api.schedule_handoff(order["id"], s.ch, {"cooler_provided": True})
    )
    assert scheduled["handoff_status"] == "SCHEDULED"
    assert scheduled["cooler_provided"] is True


def test_a_delivery_beyond_the_permitted_radius_cannot_confirm(api):
    """PRD §2.6: "Rung 33: when the order's `handoff_mode` is `DELIVERY`, the
    customer's `delivery_distance_km` is at most the operator's `permitted_radius_km`,
    otherwise `ERR_OUT_OF_PERMITTED_ZONE` (422); this rung applies to **both** order
    confirmation and handoff scheduling."
    PRD §2.8: "**Delivery may not leave the permitted radius**, which is recorded
    per operator as `permitted_radius_km` and defaults to 40.0 kilometres."

    Design: Corner/validations/delivery_beyond_the_permitted_radius_is_rejected
    """
    s = setup_storefront()
    far = add_customer(
        s, "far", display_name="Out Of Zone Ozzie", email="ozzie@example.com",
        delivery_distance_km=45.0,
    )
    order = open_order(far["id"], s.window_id, handoff_mode="DELIVERY")
    add_line(order["id"], s.cookie_id, 13, far["id"], s.window_id)

    rejected = api.confirm_order(order["id"], make_customer_headers(far["id"]), {})
    validate_error(rejected, ApiErrorId.ERR_OUT_OF_PERMITTED_ZONE)

    unchanged = read_order(order["id"], s.bh)
    assert unchanged["order_status"] == "PENDING_HOLD"
    assert unchanged["delivery_fee_cents"] == 0
    window = read_window(s.window_id, s.bh)
    assert window["confirmed_units"] == 0
    assert window["held_units"] == 13


def test_a_delivery_below_the_minimum_cannot_be_scheduled(api):
    """PRD §2.6: "Rung 47: when the order's `handoff_mode` is `DELIVERY`, its
    `subtotal_cents` is at least the delivery minimum of 3500 cents, otherwise
    `ERR_DELIVERY_MINIMUM_NOT_MET` (422) on handoff scheduling."
    PRD §3.8: "a `DELIVERY` order instead requires the buyer's
    `delivery_distance_km` to be within the operator's `permitted_radius_km` (rung
    33, `ERR_OUT_OF_PERMITTED_ZONE`) and the order's `subtotal_cents` to be at least
    the **3500-cent delivery minimum** (rung 47, `ERR_DELIVERY_MINIMUM_NOT_MET`)"

    Design: Corner/validations/delivery_minimum_not_met_blocks_scheduling
    """
    s = setup_storefront()
    order = open_order(s.customer_id, s.window_id, handoff_mode="DELIVERY")
    add_line(order["id"], s.cookie_id, 1, s.customer_id, s.window_id)
    confirmed = confirm_order(order["id"], s.customer_id)
    assert confirmed["subtotal_cents"] == 450
    assert confirmed["delivery_fee_cents"] == 500

    rejected = api.schedule_handoff(order["id"], s.ch, {})
    validate_error(rejected, ApiErrorId.ERR_DELIVERY_MINIMUM_NOT_MET)

    unchanged = read_order(order["id"], s.ch)
    assert unchanged["handoff_status"] == "NOT_SCHEDULED"
    assert unchanged["order_status"] == "CONFIRMED"


def test_route_sequencing_orders_by_distance_then_by_order_created_at(api):
    """PRD §3.8: "Sequencing it — the operator naming `to_status` `SEQUENCED` —
    requires at least one order to have been assigned to the route, and assigns
    `stop_sequence` as a 1-based index over exactly those assigned orders whose
    `handoff_status` is `SCHEDULED` and whose `order_status` is `CONFIRMED`,
    `IN_PRODUCTION`, or `READY`"
    PRD §3.8: "The ordering is by `delivery_distance_km` ascending, with the owning
    order's `created_at` ascending as the tie-break — never the identifier."
    PRD §3.8: "Sequencing also sets the route's `stop_count` to the number of
    sequenced orders and its `total_distance_km` to the sum of their distances."

    Design: Corner/calculations/route_stop_sequence_sorts_by_distance_then_created_at
    """
    s = setup_storefront()
    far_first = add_customer(
        s, "far1", display_name="Far First", email="far1@example.com",
        delivery_distance_km=12.0,
    )
    near = add_customer(
        s, "near", display_name="Near", email="near@example.com",
        delivery_distance_km=3.0,
    )
    far_second = add_customer(
        s, "far2", display_name="Far Second", email="far2@example.com",
        delivery_distance_km=12.0,
    )
    create_route(s)
    # The two 12.0 km orders must be separable by the declared tie-break, so the
    # logical clock is advanced between them and their created_at instants differ.
    order_far1 = setup_delivery_order(s, far_first["id"])
    set_clock("2026-05-04T09:01:00Z")
    order_near = setup_delivery_order(s, near["id"])
    set_clock("2026-05-04T09:02:00Z")
    order_far2 = setup_delivery_order(s, far_second["id"])

    sequenced = validate_success(
        api.set_route_status(s.route_id, {"to_status": "SEQUENCED"}, s.bh)
    )
    assert sequenced["route_status"] == "SEQUENCED"
    assert sequenced["stop_count"] == 3
    assert sequenced["total_distance_km"] == pytest.approx(27.0)

    assert read_order(order_near["id"], s.bh)["stop_sequence"] == 1
    assert read_order(order_far1["id"], s.bh)["stop_sequence"] == 2, (
        "the earlier-created 12.0 km order wins the tie"
    )
    assert read_order(order_far2["id"], s.bh)["stop_sequence"] == 3
    assert read_order(order_far1["id"], s.bh)["delivery_fee_cents"] == 900
    assert read_order(order_near["id"], s.bh)["delivery_fee_cents"] == 500


def test_a_second_rebook_after_two_misses_is_refused(api):
    """PRD §2.6: "Rung 45: the order's `rebook_count` is below the rebook maximum of
    1 and its `forfeit_latched` is false, otherwise `ERR_REBOOK_LIMIT_EXCEEDED`
    (409) on handoff scheduling when the order's `handoff_status` is `MISSED`."
    PRD §3.8: "There is a second step inside the same request that matters: when the
    window is `HANDOFF_OPEN` and the order's handoff mode is `PICKUP_COUNTER` or
    `PORCH_SELF_SERVE`, `handoff_status` advances immediately on from `SCHEDULED` to
    `PICKUP_READY`, so the rebooked order is collectable again without any further
    call — and that is precisely what makes a *second* miss, and therefore the
    rebook ceiling itself, reachable."

    Design: Corner/state_machines/second_rebook_after_two_misses_exceeds_the_rebook_limit
    """
    s = setup_ready_pickup_order()
    first_miss = validate_success(
        api.record_handoff_outcome(s.order_id, {"outcome": "MISSED"}, s.bh)
    )
    assert first_miss["handoff_status"] == "MISSED"

    rebooked = validate_success(api.schedule_handoff(s.order_id, s.ch, {}))
    assert rebooked["rebook_count"] == 1
    assert rebooked["handoff_status"] == "PICKUP_READY"

    second_miss = validate_success(
        api.record_handoff_outcome(s.order_id, {"outcome": "MISSED"}, s.bh)
    )
    assert second_miss["handoff_status"] == "MISSED"

    rejected = api.schedule_handoff(s.order_id, s.ch, {})
    validate_error(rejected, ApiErrorId.ERR_REBOOK_LIMIT_EXCEEDED)
    final = read_order(s.order_id, s.bh)
    assert final["rebook_count"] == 1
    assert final["handoff_status"] == "MISSED"


def test_a_pickup_handoff_at_the_grace_instant_is_refused_and_then_forfeits(api):
    """PRD §2.6: "Rung 39: when the order's `handoff_mode` is `PICKUP_COUNTER` or
    `PORCH_SELF_SERVE`, the current instant is strictly before the order's
    `pickup_forfeit_at`, otherwise `ERR_PICKUP_GRACE_EXPIRED` (409) on a handed-off
    outcome; this rung does **not** apply to the delivery pipeline, which has no
    grace check at all."
    PRD §3.8: "Its collection deadline is `pickup_forfeit_at`, set when the window
    opened handoff to the window's `handoff_window_end_at` plus **90 minutes** of
    grace, and null for delivery orders."
    PRD §3.8: "A **forfeited** outcome is available from `MISSED` once the current
    instant has reached `pickup_forfeit_at`; it moves `handoff_status` to
    `FORFEITED`, moves `order_status` from `READY` to `FORFEITED`, sets
    `forfeit_latched` to true **permanently**"
    PRD §3.8: "and refunds **zero percent** of the captured amount, which is to say
    it refunds nothing at all."

    Design: Corner/validations/handing_off_a_pickup_order_after_the_grace_expires_is_rejected
    """
    s = setup_ready_pickup_order()
    ready = read_order(s.order_id, s.bh)
    assert ready["handoff_status"] == "PICKUP_READY"
    assert_same_instant(
        ready["pickup_forfeit_at"],
        instant_plus("2026-05-07T19:00:00Z", minutes=90),
        "pickup_forfeit_at",
    )

    set_clock(CLOCK_AT_PICKUP_FORFEIT)
    rejected = api.record_handoff_outcome(
        s.order_id, {"outcome": "HANDED_OFF"}, s.bh
    )
    validate_error(rejected, ApiErrorId.ERR_PICKUP_GRACE_EXPIRED)

    validate_success(api.record_handoff_outcome(s.order_id, {"outcome": "MISSED"}, s.bh))
    forfeited = validate_success(
        api.record_handoff_outcome(s.order_id, {"outcome": "FORFEITED"}, s.bh)
    )
    assert forfeited["order_status"] == "FORFEITED"
    assert forfeited["handoff_status"] == "FORFEITED"
    assert forfeited["forfeit_latched"] is True
    assert forfeited["fulfilled_at"] is None
    assert read_label(s.label_id, s.bh)["label_status"] == "ISSUED"
    assert movements_of(s.bh, order_id=s.order_id) == []
