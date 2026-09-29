"""Read-your-writes: nothing a write derives is deferred to a later request.

Every figure a write computes - the pinned fare component, its category split, the
settlement position with the channel, and the parity fallout of a content edit - is
already final in the response that caused it and in the very next read.  No test
here advances the logical clock or retries a read, so a lagging or batched
recomputation cannot pass.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    DISTRIBUTION_MANAGER,
    MERCHANDISING_ANALYST,
    OPERATIONS_CONTROLLER,
    REVENUE_ACCOUNTANT,
    assert_allocation_conserves_fare,
    assert_entry_amounts,
    assert_money_field,
    factories,
    find_one_entry,
    make_channel_partner_headers,
)


def _bag_family_on_direct_web(scenario):
    """A published economy bundle - base 12000, bundle 14000, one 3500 bag included -
    live and in parity on a zero-commission direct channel."""
    bag = scenario.create_product(factories.checked_bag_product_payload())
    family = scenario.create_family(factories.eco_lite_family_payload())
    scenario.add_attribute(family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1)
    scenario.publish_family(family["id"])

    channel = scenario.create_channel(factories.direct_web_channel_payload())
    publication = scenario.publish_to_channel(
        family["id"], channel["id"], scenario.get_family(family["id"])["version"]
    )
    return bag, family, channel, publication


def test_the_ticket_response_already_reports_the_split_and_the_settlement(api, scenario):
    """PRD 3.5: "When all nine hold, ticketing performs six things in order. It pins
    `fare_component_cents` from the family's `bundle_price_cents` at that instant,
    freezing the fare component against later family edits. It runs the ticketing
    allocation described below over that pinned amount, posting one `ALLOCATION`
    revenue entry per weighted category, each with a `source_ref` of `ticket:`
    followed by the booking's id."
    PRD 3.5: "Pass one prorates by **flooring**, never by rounding half up: each
    bucket's gross amount is the pinned `fare_component_cents` multiplied by that
    bucket's weight, divided by the total weight, and truncated downward to a whole
    number of cents. The remainder is the pinned amount minus the sum of the floored
    gross amounts. Pass two distributes that remainder **one cent at a time**, walking
    the buckets in descending order of weight"
    PRD 3.9: "`channel_settlement_total_cents` is the provisional total minus
    `incentive_credit_cents`."

    Design: Corner/consistency_model/the_ticket_response_itself_carries_the_allocated_money_fields
    """
    _, family, channel, _ = _bag_family_on_direct_web(scenario)
    flight = scenario.create_flight(
        flight_no="AC590",
        origin="SFO",
        destination="JFK",
        scheduled_departure_utc="2026-09-01T15:00:00Z",
        cabin_seat_total=120,
    )
    booking = scenario.create_booking(
        flight["id"],
        family["id"],
        channel["id"],
        record_locator="TICK01",
        passenger_name="Ada Lovelace",
    )
    scenario.disclose_and_acknowledge(booking["id"], channel["id"])

    ticketed = validate_success(
        api.ticket_booking(booking["id"], {}, make_channel_partner_headers(channel["id"]))
    )

    assert ticketed["booking_status"] == "TICKETED", (
        f"the sale has closed, so the booking is TICKETED, not {ticketed['booking_status']!r}"
    )
    # The bundle price is pinned into the fare component by this very request.
    assert_money_field(ticketed, "fare_component_cents", 14000)
    # No ancillary was ever sold on top of the bundle, so nothing gross to settle.
    assert_money_field(ticketed, "ancillary_gross_cents", 0)
    # The baggage share of the pinned fare is recognised net of its service tax.
    assert_money_field(ticketed, "recognized_ancillary_net_cents", 3035)
    assert_money_field(ticketed, "commission_cents", 0)
    assert_money_field(ticketed, "incentive_credit_cents", 0)
    assert_money_field(ticketed, "channel_settlement_total_cents", 14000)

    entries, meta = validate_paginated(
        api.list_booking_revenue_entries(booking["id"], REVENUE_ACCOUNTANT)
    )
    assert meta["total_count"] == 2, (
        "the 12000 air weight and the 3500 baggage weight are the only two buckets, "
        f"so two allocation rows are posted, not {meta['total_count']}"
    )

    baggage = find_one_entry(entries, entry_type="ALLOCATION", category="BAGGAGE")
    air = find_one_entry(entries, entry_type="ALLOCATION", category="AIR_TRANSPORT")

    # 14000 * 3500 / 15500 floors to 3161; taxed at 400 bp that is 126.
    assert_entry_amounts(baggage, 3161, 126, 3035)
    # 14000 * 12000 / 15500 floors to 10838 and the single residual cent lands on the
    # heaviest bucket; taxed at 750 bp 10839 attracts 813.
    assert_entry_amounts(air, 10839, 813, 10026)
    assert_allocation_conserves_fare(entries, 14000)

    for entry in (baggage, air):
        assert entry["source_ref"] == f"ticket:{booking['id']}", (
            f"an allocation names the ticketing booking: {entry['source_ref']!r}"
        )

    flown_from = validate_success(api.get_flight(flight["id"], OPERATIONS_CONTROLLER))
    assert flown_from["ticketed_booking_count"] == 1, (
        "the flight already counts its one ticketed booking, "
        f"not {flown_from['ticketed_booking_count']}"
    )


def test_repricing_an_attribute_breaches_parity_within_the_same_request(api, scenario):
    """PRD 3.1: "On a `PUBLISHED` family the very same request is the head of a
    four-way cascade, because the family's content has changed underneath everything
    that pinned it. Every publication of that family whose `parity_state` is
    `IN_PARITY` moves to `OUT_OF_PARITY` with `drift_reason` set to
    `ATTRIBUTE_REPRICED`, each such channel's `parity_breach_count` increases by one,
    and each such channel's `content_parity_status` is re-derived."
    PRD 2.8: "A `ChannelPublication` stores `published_fee_fingerprint` and
    `published_family_version`, captured at publication or at the last
    resynchronisation; parity holds for as long as the pinned string equals the live
    one."
    PRD 3.1: "Its `bundle_discount_bp` - the basis points a passenger saves by buying
    the bundle instead of every component separately - is 0 when
    `unbundled_value_cents` is 0; otherwise it is `a_la_carte_total_cents` minus
    `bundle_price_cents`, multiplied by 10,000, divided by `a_la_carte_total_cents`,
    and rounded half up."

    Design: Corner/consistency_model/a_parity_breach_is_visible_in_the_same_request_that_causes_it
    """
    bag = scenario.create_product(factories.checked_bag_product_payload())
    family = scenario.create_family(
        factories.eco_lite_family_payload(code="ECO_DRIFT", name="Economy Drift")
    )
    attribute = scenario.add_attribute(
        family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1
    )
    scenario.publish_family(family["id"])

    channel = scenario.create_channel(factories.direct_web_channel_payload())
    publication = scenario.publish_to_channel(
        family["id"], channel["id"], scenario.get_family(family["id"])["version"]
    )
    assert publication["parity_state"] == "IN_PARITY", (
        "a live family publishes straight into parity, "
        f"not {publication['parity_state']!r}"
    )
    before = scenario.get_channel(channel["id"])
    assert before["content_parity_status"] == "COMPLIANT", (
        f"nothing has drifted yet: {before['content_parity_status']!r}"
    )
    assert before["parity_breach_count"] == 0, (
        f"nothing has drifted yet: {before['parity_breach_count']}"
    )

    repriced = validate_success(
        api.update_family_attribute(
            attribute["id"], {"override_price_cents": 3000}, MERCHANDISING_ANALYST
        )
    )

    # The negotiated 3000 replaces the 3500 list price; economy adds no cabin uplift.
    assert_money_field(repriced, "effective_unit_cents", 3000)
    assert_money_field(repriced, "attr_value_cents", 3000)

    drifted = validate_success(api.get_fare_family(family["id"], MERCHANDISING_ANALYST))
    assert drifted["fee_fingerprint"] == "ECO_DRIFT|1|BAG_CHECKED_1:INCLUDED:1:3000", (
        f"the live fingerprint carries the new unit price: {drifted['fee_fingerprint']!r}"
    )
    assert_money_field(drifted, "unbundled_value_cents", 3000)
    assert_money_field(drifted, "a_la_carte_total_cents", 15000)
    # (15000 - 14000) * 10000 / 15000 = 666.67, rounded half up.
    assert drifted["bundle_discount_bp"] == 667, (
        f"the bundle now saves 667 basis points, not {drifted['bundle_discount_bp']}"
    )

    breached = scenario.get_publication(publication["id"])
    assert breached["parity_state"] == "OUT_OF_PARITY", (
        "the channel is selling content the airline no longer sells, so the "
        f"publication is OUT_OF_PARITY, not {breached['parity_state']!r}"
    )
    assert breached["drift_reason"] == "ATTRIBUTE_REPRICED", (
        f"the drift is attributed to the reprice: {breached['drift_reason']!r}"
    )
    assert (
        breached["published_fee_fingerprint"] == "ECO_DRIFT|1|BAG_CHECKED_1:INCLUDED:1:3500"
    ), (
        "the pinned string keeps the stale content so the drift stays auditable: "
        f"{breached['published_fee_fingerprint']!r}"
    )

    after = validate_success(api.get_distribution_channel(channel["id"], DISTRIBUTION_MANAGER))
    assert after["content_parity_status"] == "BREACHED", (
        "a parity-required channel with a drifted publication is in breach, "
        f"not {after['content_parity_status']!r}"
    )
    assert after["parity_breach_count"] == 1, (
        f"parity has been lost exactly once, not {after['parity_breach_count']} times"
    )
