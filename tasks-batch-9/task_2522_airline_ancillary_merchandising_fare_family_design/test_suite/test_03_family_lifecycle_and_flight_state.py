"""Lifecycles that revisit a state without returning to its earlier condition.

A rejected family re-enters DRAFT carrying a higher revision number, which is a
fingerprint component, so the second approval cannot re-emit the first
fingerprint.  A flight advances its sales phase and its irregular-operations
state on unrelated triggers, so neither dimension may rewind the other.  A
booking traverses the change cycle twice with two different resolutions, and only
the money and the counter distinguish the laps.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    OPERATIONS_CONTROLLER,
    PRICING_APPROVER,
    PRICING_APPROVER_USER_ID,
    Scenario,
    assert_entry_amounts,
    assert_field_values,
    assert_fingerprint,
    factories,
    find_one_entry,
)

CLOCK = "2026-08-10T09:00:00Z"


def _four_attribute_family(scenario: Scenario):
    """ECO_BUNDLE with four included attributes, submitted once and rejected once.

    Returns the family id and the fingerprint the very first submit produced, so a
    test can compare it against the one the second cycle emits.
    """
    scenario.set_clock(CLOCK)
    bag = scenario.create_product(factories.checked_bag_product_payload())
    seat = scenario.create_product(factories.standard_seat_product_payload())
    boarding = scenario.create_product(factories.priority_boarding_product_payload())
    wifi = scenario.create_product(
        factories.wifi_product_payload(
            name="Full-flight wifi", tax_treatment="EXEMPT", refundable=True
        )
    )
    family = scenario.create_family(
        factories.fare_family_payload(
            code="ECO_BUNDLE",
            name="Economy Bundle",
            cabin_class="ECONOMY",
            base_fare_cents=12000,
            bundle_price_cents=15000,
            refundability="REFUNDABLE_WITH_FEE",
            change_fee_cents=7500,
            boarding_priority_tier=3,
        )
    )
    for product in (bag, seat, boarding, wifi):
        scenario.add_attribute(
            family["id"], product["id"], inclusion="INCLUDED", included_quantity=1
        )

    first_submit = scenario.submit_family(family["id"])
    validate_success(
        scenario.api.review_fare_family(
            family["id"],
            factories.review_decision_payload(
                "REJECT", review_note="boarding tier inconsistent with cabin"
            ),
            PRICING_APPROVER,
        )
    )
    second_submit = scenario.submit_family(family["id"])
    return {
        "family_id": family["id"],
        "first_fingerprint": first_submit["fee_fingerprint"],
        "second_fingerprint": second_submit["fee_fingerprint"],
    }


def test_rejection_cycle_advances_the_revision_and_the_fingerprint(scenario):
    """The second approval publishes at revision 2 with a revision-2 fingerprint.

    The attribute set never changed, yet the rejection lifted revision_no to 2 and
    the revision number is a fingerprint component, so the published fingerprint
    differs byte for byte from the one the first submit produced.

    Design: Difficulty/non_linear_state_machine/fare_family_review_reject_revision_cycle
    """
    world = _four_attribute_family(scenario)

    approved = validate_success(
        scenario.api.review_fare_family(
            world["family_id"],
            factories.review_decision_payload("APPROVE", review_note="second pass approved"),
            PRICING_APPROVER,
        )
    )

    # PRD names review_note only as an optional *input* to the review decision, never
    # as a persisted attribute of the family, so only the stamped fields are asserted.
    assert_field_values(
        approved,
        status="PUBLISHED",
        revision_no=2,
        reviewer_user_id=PRICING_APPROVER_USER_ID,
    )
    assert_fingerprint(
        approved,
        "fee_fingerprint",
        "ECO_BUNDLE|2|BAG_CHECKED_1:INCLUDED:1:3500;PRIORITY_BOARDING:INCLUDED:1:1250;"
        "SEAT_STANDARD:INCLUDED:1:1900;WIFI_FULL_FLIGHT:INCLUDED:1:750",
    )
    assert world["first_fingerprint"].startswith("ECO_BUNDLE|1|"), (
        f"the first submit must fingerprint revision 1, got {world['first_fingerprint']!r}"
    )
    assert approved["fee_fingerprint"] != world["first_fingerprint"], (
        "the loop is not idempotent: the revision bump must change the fingerprint"
    )


def test_rejection_cycle_leaves_the_valuation_untouched(scenario):
    """Only the revision moves: the four-attribute valuation is identical after the loop.

    Design: Difficulty/non_linear_state_machine/fare_family_review_reject_revision_cycle
    """
    world = _four_attribute_family(scenario)

    validate_success(
        scenario.api.review_fare_family(
            world["family_id"],
            factories.review_decision_payload("APPROVE", review_note="second pass approved"),
            PRICING_APPROVER,
        )
    )

    family = scenario.get_family(world["family_id"])
    assert_field_values(
        family,
        unbundled_value_cents=7400,
        a_la_carte_total_cents=19400,
        bundle_discount_bp=2268,
        included_attribute_count=4,
    )


def _two_dimensional_flight(scenario: Scenario):
    """Flight AA600 walked to BOARDING while a 240-minute delay waiver is ACTIVE."""
    scenario.set_clock(CLOCK)
    flight = scenario.create_flight(flight_no="AA600", origin="JFK", destination="LAX")
    waiver = scenario.declare_waiver(flight["id"], "DELAY", 240, ["BOARDING"])
    scenario.advance_phase(flight["id"], "CHECKIN_OPEN")
    scenario.advance_phase(flight["id"], "BOARDING")
    return {"flight_id": flight["id"], "waiver_id": waiver["id"]}


def test_phase_advances_leave_the_irregular_operations_dimension_alone(scenario):
    """Walking the sales phase to BOARDING neither expires nor clears the waiver.

    Design: Difficulty/non_linear_state_machine/flight_parallel_phase_and_irops_dimensions
    """
    world = _two_dimensional_flight(scenario)

    flight = validate_success(
        scenario.api.get_flight(world["flight_id"], OPERATIONS_CONTROLLER)
    )
    assert_field_values(
        flight, sales_phase="BOARDING", irops_state="IRREGULAR", active_waiver_count=1
    )
    waiver = validate_success(
        scenario.api.get_irops_waiver(world["waiver_id"], OPERATIONS_CONTROLLER)
    )
    assert waiver["waiver_state"] == "ACTIVE", (
        f"two phase advances must not expire the waiver, got {waiver['waiver_state']!r}"
    )


def test_rescission_recovers_the_irops_dimension_without_rewinding_the_sales_phase(scenario):
    """The flight ends in BOARDING x RECOVERED, a pair no single ladder can express.

    Rescinding the waiver drops active_waiver_count to 0 and moves the irregular
    dimension to RECOVERED - not back to NORMAL - while the sales phase stays where
    the operations controller left it.

    Design: Difficulty/non_linear_state_machine/flight_parallel_phase_and_irops_dimensions
    """
    world = _two_dimensional_flight(scenario)

    scenario.rescind_waiver(
        world["waiver_id"], "aircraft swap completed, operation recovered"
    )

    flight = validate_success(
        scenario.api.get_flight(world["flight_id"], OPERATIONS_CONTROLLER)
    )
    assert flight["sales_phase"] == "BOARDING", (
        f"the rescission must not rewind the sales phase, got {flight['sales_phase']!r}"
    )
    assert flight["irops_state"] == "RECOVERED", (
        f"a rescinded flight recovers rather than resetting to NORMAL, got {flight['irops_state']!r}"
    )
    assert flight["active_waiver_count"] == 0, (
        f"the rescinded waiver is no longer active, got {flight['active_waiver_count']}"
    )


def test_rescinded_waiver_records_its_reason(scenario):
    """The waiver itself lands in RESCINDED carrying the reason it was given.

    Design: Difficulty/non_linear_state_machine/flight_parallel_phase_and_irops_dimensions
    """
    world = _two_dimensional_flight(scenario)

    rescinded = scenario.rescind_waiver(
        world["waiver_id"], "aircraft swap completed, operation recovered"
    )

    assert_field_values(
        rescinded,
        waiver_state="RESCINDED",
        rescind_reason="aircraft swap completed, operation recovered",
    )


def _change_cycle_world(scenario: Scenario):
    """ECO_CYCLE published to DIRECT_WEB with one TICKETED booking, change already open."""
    scenario.set_clock(CLOCK)
    bag = scenario.create_product(factories.checked_bag_product_payload())
    family = scenario.create_family(
        factories.fare_family_payload(
            code="ECO_CYCLE",
            name="Economy Cycle",
            cabin_class="ECONOMY",
            base_fare_cents=12000,
            bundle_price_cents=15000,
            refundability="REFUNDABLE_WITH_FEE",
            change_fee_cents=7500,
            boarding_priority_tier=3,
        )
    )
    scenario.add_attribute(family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1)
    published = scenario.publish_family(family["id"])

    channel = scenario.create_channel(factories.direct_web_channel_payload())
    scenario.publish_to_channel(family["id"], channel["id"], published["version"])

    flight = scenario.create_flight(flight_no="AA700", origin="JFK", destination="LAX")
    booking = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="CYCLE1"
    )
    scenario.hold_disclose_ack_and_ticket(booking["id"], channel["id"])
    opened = scenario.open_change(booking["id"], channel["id"])
    return {
        "channel_id": channel["id"],
        "booking_id": booking["id"],
        "first_open": opened,
    }


def test_change_cycle_quotes_and_clears_the_fee_on_every_lap(scenario):
    """Both laps quote 7500 while CHANGE_PENDING and null the quote on settling.

    The booking is TICKETED again after each lap, so the status label alone cannot
    distinguish CONFIRM from ABANDON.

    Design: Difficulty/non_linear_state_machine/booking_change_cycle_confirm_then_abandon
    """
    world = _change_cycle_world(scenario)
    booking_id = world["booking_id"]
    channel_id = world["channel_id"]

    assert_field_values(
        world["first_open"],
        booking_status="CHANGE_PENDING",
        pending_change_fee_cents=7500,
    )

    confirmed = scenario.settle_change(booking_id, channel_id, "CONFIRM")
    assert confirmed["booking_status"] == "TICKETED", (
        f"a settled change returns the booking to TICKETED, got {confirmed['booking_status']!r}"
    )
    assert confirmed["pending_change_fee_cents"] is None, (
        f"settling clears the quote, got {confirmed['pending_change_fee_cents']!r}"
    )

    second_open = scenario.open_change(booking_id, channel_id)
    assert_field_values(
        second_open, booking_status="CHANGE_PENDING", pending_change_fee_cents=7500
    )

    abandoned = scenario.settle_change(booking_id, channel_id, "ABANDON")
    assert abandoned["booking_status"] == "TICKETED", (
        f"abandoning also returns the booking to TICKETED, got {abandoned['booking_status']!r}"
    )
    assert abandoned["pending_change_fee_cents"] is None, (
        f"abandoning clears the quote too, got {abandoned['pending_change_fee_cents']!r}"
    )


def test_only_the_confirming_lap_counts_and_charges(scenario):
    """change_count reaches 1 and stays there, and the money reflects a single change fee.

    Design: Difficulty/non_linear_state_machine/booking_change_cycle_confirm_then_abandon
    """
    world = _change_cycle_world(scenario)
    booking_id = world["booking_id"]
    channel_id = world["channel_id"]

    after_confirm = scenario.settle_change(booking_id, channel_id, "CONFIRM")
    assert after_confirm["change_count"] == 1, (
        f"the confirming lap increments the counter, got {after_confirm['change_count']}"
    )

    scenario.open_change(booking_id, channel_id)
    after_abandon = scenario.settle_change(booking_id, channel_id, "ABANDON")

    assert after_abandon["change_count"] == 1, (
        f"the abandoned lap must not increment the counter, got {after_abandon['change_count']}"
    )
    assert_field_values(
        after_abandon,
        fare_component_cents=15000,
        ancillary_gross_cents=7500,
        recognized_ancillary_net_cents=10452,
        commission_cents=0,
        incentive_credit_cents=0,
        channel_settlement_total_cents=22500,
    )


def test_the_abandoned_lap_posts_no_ledger_row(scenario):
    """Three rows survive both laps: two allocations and the single change sale.

    The change sale is booked at 7500 under the settlement sku and traced to the
    booking, and the abandoned lap adds nothing.

    Design: Difficulty/non_linear_state_machine/booking_change_cycle_confirm_then_abandon
    """
    world = _change_cycle_world(scenario)
    booking_id = world["booking_id"]
    channel_id = world["channel_id"]

    scenario.settle_change(booking_id, channel_id, "CONFIRM")
    after_confirm = scenario.booking_ledger(booking_id)
    assert len(after_confirm) == 3, (
        f"two allocations and one change sale, found {len(after_confirm)}"
    )

    scenario.open_change(booking_id, channel_id)
    scenario.settle_change(booking_id, channel_id, "ABANDON")

    entries = scenario.booking_ledger(booking_id)
    assert len(entries) == 3, (
        f"abandoning must not append a row, found {len(entries)}"
    )
    assert_entry_amounts(
        find_one_entry(entries, entry_type="ALLOCATION", category="BAGGAGE"), 3387, 135, 3252
    )
    assert_entry_amounts(
        find_one_entry(entries, entry_type="ALLOCATION", category="AIR_TRANSPORT"),
        11613,
        871,
        10742,
    )
    sale = find_one_entry(entries, entry_type="SALE", category="CHANGE")
    assert_entry_amounts(sale, 7500, 300, 7200)
    assert sale["product_sku"] == "CHANGE_SETTLEMENT", (
        f"the change sale carries the settlement sku, got {sale['product_sku']!r}"
    )
    assert sale["source_ref"] == f"change:{booking_id}", (
        f"the change sale traces to the booking, got {sale['source_ref']!r}"
    )
