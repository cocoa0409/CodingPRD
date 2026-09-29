"""Endpoint side effects: what one call leaves behind on everything around it.

A reprice rebuilds its parent family, a demand snapshot walks the whole seat map,
a clock move sweeps stale offers, and a resynchronisation re-pins a drifted
publication.  Each test therefore looks past the response body of the call it
makes and reads the neighbouring resources back.
"""

from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CLOCK_9AM,
    DISTRIBUTION_MANAGER,
    MERCHANDISING_ANALYST,
    OPERATIONS_CONTROLLER,
    REVENUE_ACCOUNTANT,
    ApiErrorId,
    assert_entry_amounts,
    assert_field_values,
    assert_money_field,
    assert_segment_counts,
    factories,
    find_one_entry,
    make_channel_partner_headers,
)


# ---------------------------------------------------------------------------
# Catalog, family and channel payloads shared by the cases below
# ---------------------------------------------------------------------------
def _checked_bag():
    """BAG_CHECKED_1: BAGGAGE at 3500 cents, taxed as a service (400 bp)."""
    return factories.ancillary_product_payload(
        sku="BAG_CHECKED_1",
        name="First checked bag",
        category="BAGGAGE",
        list_price_cents=3500,
        tax_treatment="TAXABLE_SERVICE",
        revenue_class="NON_AIR",
        revenue_account_code="4100",
    )


def _priority_boarding():
    """PRIORITY_BOARDING: BOARDING at 1250 cents."""
    return factories.ancillary_product_payload(
        sku="PRIORITY_BOARDING",
        name="Priority boarding",
        category="BOARDING",
        list_price_cents=1250,
        tax_treatment="TAXABLE_SERVICE",
        revenue_class="NON_AIR",
        revenue_account_code="4400",
    )


def _standard_seat():
    """SEAT_STANDARD: SEAT at 1900 cents, refundable."""
    return factories.ancillary_product_payload(
        sku="SEAT_STANDARD",
        name="Standard seat",
        category="SEAT",
        list_price_cents=1900,
        tax_treatment="TAXABLE_SERVICE",
        revenue_class="NON_AIR",
        revenue_account_code="4200",
        refundable=True,
    )


def _extra_legroom_seat():
    """SEAT_EXTRA_LEGROOM: SEAT at 4200 cents, refundable."""
    return factories.ancillary_product_payload(
        sku="SEAT_EXTRA_LEGROOM",
        name="Extra legroom seat",
        category="SEAT",
        list_price_cents=4200,
        tax_treatment="TAXABLE_SERVICE",
        revenue_class="NON_AIR",
        revenue_account_code="4200",
        refundable=True,
    )


def _merch_family():
    """ECO_MERCH: bundles only the flexible-change product.

    Nothing a merchandising session offers is bundled into this family, so the
    rest of the catalog stays eligible at the booking touchpoint.
    """
    return factories.fare_family_payload(
        code="ECO_MERCH",
        name="Economy Merchandisable",
        cabin_class="ECONOMY",
        base_fare_cents=12000,
        bundle_price_cents=14000,
    )


def _direct_web_channel():
    """DIRECT_WEB: no commission, no markup, every category merchandisable."""
    return factories.distribution_channel_payload(
        channel_code="DIRECT_WEB",
        channel_type="DIRECT",
        commission_bp=0,
        markup_bp=0,
        max_ancillary_price_cents=20000,
        supported_categories=["BAGGAGE", "SEAT", "CHANGE", "BOARDING", "ONBOARD"],
        parity_required=True,
    )


def _instant(rendered):
    """Read a rendered UTC instant back into a comparable datetime."""
    text = str(rendered).replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def _offers_by_product(offers):
    return {offer["ancillary_product_id"]: offer for offer in offers}


def test_patching_an_attribute_override_rebuilds_its_family(api, scenario):
    """PRD §3.1: "On a `DRAFT` family it is a quiet edit: the attribute's
    `effective_unit_cents` and `attr_value_cents` are recomputed, the parent family's
    valuation outputs and `fee_fingerprint` are rebuilt, and the family's `version`
    increments."
    PRD §2.3: "Optionally the analyst supplies `override_price_cents`, a non-negative
    value that replaces the referenced product's list price for valuation purposes only"
    PRD §2.3: "`effective_unit_cents`, which is `override_price_cents` when that is not
    null and otherwise the referenced product's `list_price_cents`"
    PRD §2.10: "an integer that increments by exactly 1 on every mutation of the
    resource. It starts at 1 when the resource is created."

    Design: Corner/endpoints/patch_family_attribute_updates_the_override_and_recomputes_the_family
    """
    bag = scenario.create_product(_checked_bag())
    family = scenario.create_family(factories.eco_lite_family_payload())
    assert family["version"] == 1, family["version"]

    attribute = scenario.add_attribute(
        family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1
    )
    # With no override the attribute values at the 3500 catalog list price.
    assert_money_field(attribute, "effective_unit_cents", 3500)
    assert_money_field(attribute, "attr_value_cents", 3500)
    assert attribute["version"] == 1, attribute["version"]

    before = scenario.get_family(family["id"])
    # created at 1, then mutated once by the attachment's valuation rebuild
    assert before["version"] == 2, before["version"]
    assert_money_field(before, "unbundled_value_cents", 3500)

    patched = validate_success(
        api.update_family_attribute(
            attribute["id"], {"override_price_cents": 3000}, MERCHANDISING_ANALYST
        )
    )
    assert_field_values(patched, attribute_state="ACTIVE", inclusion="INCLUDED")
    # 3000 override x 1 unit x (10000 + 0bp ECONOMY uplift) / 10000 = 3000
    assert_money_field(patched, "effective_unit_cents", 3000)
    assert_money_field(patched, "attr_value_cents", 3000)
    assert_money_field(patched, "override_price_cents", 3000)
    assert patched["version"] == 2, patched["version"]

    after = scenario.get_family(family["id"])
    assert after["status"] == "DRAFT", after["status"]
    assert_money_field(after, "unbundled_value_cents", 3000)
    # 12000 base fare + 3000 overridden bag = 15000 a la carte
    assert_money_field(after, "a_la_carte_total_cents", 15000)
    # (15000 - 14000) x 10000 / 15000 = 666.67, half up to 667
    assert after["bundle_discount_bp"] == 667, after["bundle_discount_bp"]
    assert after["included_attribute_count"] == 1, after["included_attribute_count"]
    assert after["fee_fingerprint"] == "ECO_LITE|1|BAG_CHECKED_1:INCLUDED:1:3000", after[
        "fee_fingerprint"
    ]
    # one further mutation of the family: 2 before the reprice, 3 after it
    assert after["version"] == 3, after["version"]

    # The override is a valuation device only: the catalog price is untouched.
    product = validate_success(
        api.get_ancillary_product(bag["id"], MERCHANDISING_ANALYST)
    )
    assert_money_field(product, "list_price_cents", 3500)


def test_a_demand_snapshot_reprices_every_segment_of_its_flight(api, scenario):
    """PRD §3.3: "Publishing a snapshot re-derives the flight's `demand_tier` — `HIGH`
    when `booked_load_factor_pct` is at least 80, `MID` when it is at least 60 but below
    80, and `LOW` otherwise — and then reprices every seat segment on the flight,
    including segments already `CLOSED`, since a closed segment is still repriced even
    though it accepts no assignments."
    PRD §3.3: "These two fields are settable **only** through that snapshot; nothing else
    in the system writes them."
    PRD §3.3: "First, a row-band adjustment is chosen from the segment's `row_start`:
    1,500 cents when `row_start` is 5 or lower, 500 cents when `row_start` is between 6
    and 15 inclusive, and nothing at all when `row_start` is 16 or higher."
    PRD §3.3: "Third — and this is the pinned part — the exact integer zone base is
    multiplied by both multipliers, the product is divided by one hundred million (that
    is, by 10,000 twice, once for each basis-point factor), and only that final quotient
    is rounded half up."
    PRD §2.10: "an integer that increments by exactly 1 on every mutation of the
    resource."

    Design: Corner/endpoints/demand_snapshot_reprices_every_segment_of_the_flight
    """
    seat = scenario.create_product(_standard_seat())
    flight = scenario.create_flight()
    assert flight["demand_tier"] == "LOW", flight["demand_tier"]

    rear = scenario.create_segment(
        flight["id"],
        seat["id"],
        zone="MID",
        row_start=16,
        row_end=16,
        seat_letters=["A", "B"],
        base_price_cents=2000,
    )
    exit_row = scenario.create_segment(
        flight["id"],
        seat["id"],
        zone="EXIT_ROW",
        row_start=12,
        row_end=12,
        seat_letters=["A", "B"],
        base_price_cents=2000,
    )
    # 2000 x 10000 MID x 10000 LOW / 100,000,000 = 2000
    assert_money_field(rear, "effective_price_cents", 2000)
    # (2000 + 500 band) x 16000 EXIT_ROW x 10000 LOW / 100,000,000 = 4000
    assert_money_field(exit_row, "effective_price_cents", 4000)

    before = validate_success(api.get_flight(flight["id"], OPERATIONS_CONTROLLER))

    snapshot = scenario.post_demand(flight["id"], 60, 1200)
    assert_field_values(
        snapshot, booked_load_factor_pct=60, demand_index_bp=1200, demand_tier="MID"
    )
    assert snapshot["version"] == before["version"] + 1, (
        f"the snapshot mutates the flight once: {before['version']} -> "
        f"{snapshot['version']}"
    )

    # Both segments follow the flight's tier, each keeping its own zone and band.
    repriced_rear = scenario.get_segment(rear["id"])
    # 2000 x 10000 MID x 11000 MID demand / 100,000,000 = 2200
    assert_money_field(repriced_rear, "effective_price_cents", 2200)
    assert repriced_rear["zone_multiplier_bp"] == 10000, repriced_rear
    assert_segment_counts(repriced_rear, total_seats=2, available_seats=2)

    repriced_exit = scenario.get_segment(exit_row["id"])
    # 2500 x 16000 EXIT_ROW x 11000 MID demand / 100,000,000 = 4400
    assert_money_field(repriced_exit, "effective_price_cents", 4400)
    assert repriced_exit["zone_multiplier_bp"] == 16000, repriced_exit
    assert_segment_counts(repriced_exit, total_seats=2, available_seats=2)


def test_setting_the_clock_expires_presented_offers_and_spares_accepted_ones(
    api, scenario
):
    """PRD §3.6: "Advancing the logical clock to a value at or after an offer's
    `valid_until` sweeps that offer to `EXPIRED` deterministically as part of the
    clock-setting call, so no test ever needs to wait on real time; the call reports how
    many offers it swept as `expired_offer_count`."
    PRD §2.4: "A test-driving capability, available to every role, sets the clock to a
    supplied `to_iso8601` instant and answers with the resulting `current_utc` together
    with `expired_offer_count`, the number of presented offers the call swept into
    expiry."
    PRD §3.6: "a `valid_from` equal to the logical clock, and a `valid_until` exactly one
    hour later"
    PRD §3.6: "Expiry posts no revenue, makes the offer terminal, and frees the session
    slot it occupied."
    PRD §3.6: "`ACCEPTED`, `DECLINED`, `EXPIRED` and `SUPERSEDED` are all terminal."

    Design: Corner/endpoints/clock_set_sweeps_presented_offers_to_expired_and_spares_accepted_ones
    """
    scenario.set_clock(CLOCK_9AM)
    bag = scenario.create_product(_checked_bag())
    boarding = scenario.create_product(_priority_boarding())
    change = scenario.create_product(factories.change_flex_product_payload())

    family = scenario.create_family(_merch_family())
    scenario.add_attribute(
        family["id"], change["id"], inclusion="INCLUDED", included_quantity=1
    )
    published = scenario.publish_family(family["id"])
    channel = scenario.create_channel(_direct_web_channel())
    scenario.publish_to_channel(family["id"], channel["id"], published["version"])

    flight = scenario.create_flight()
    scenario.post_demand(flight["id"], 50, 0)
    booking = scenario.create_booking(flight["id"], family["id"], channel["id"])

    session = scenario.open_offer_session(booking["id"], channel["id"], "BOOKING")
    assert session["candidate_count"] == 2, session
    offers = _offers_by_product(
        scenario.offers_for_booking(booking["id"], channel["id"])
    )
    bag_offer = offers[bag["id"]]
    boarding_offer = offers[boarding["id"]]

    # The window opens on the logical clock and closes exactly an hour later.
    assert _instant(bag_offer["valid_from"]) == _instant(CLOCK_9AM), bag_offer
    assert _instant(bag_offer["valid_until"]) == _instant(CLOCK_9AM) + timedelta(
        hours=1
    ), bag_offer

    held = scenario.get_booking(booking["id"], channel["id"])
    accepted = scenario.accept_offer(
        boarding_offer["id"], channel["id"], held["version"]
    )
    assert accepted["offer_status"] == "ACCEPTED", accepted
    # 1250 list x 10000bp score x 10000bp BOOKING x markup-free channel = 1250
    assert_money_field(accepted, "accepted_price_cents", 1250)

    swept = scenario.set_clock(boarding_offer["valid_until"])
    assert _instant(swept["current_utc"]) == _instant(boarding_offer["valid_until"])
    # only the untouched bag offer was still on the table
    assert swept["expired_offer_count"] == 1, swept

    bag_after = validate_success(
        api.get_ancillary_offer(
            bag_offer["id"], make_channel_partner_headers(channel["id"])
        )
    )
    assert bag_after["offer_status"] == "EXPIRED", bag_after

    boarding_after = validate_success(
        api.get_ancillary_offer(
            boarding_offer["id"], make_channel_partner_headers(channel["id"])
        )
    )
    assert boarding_after["offer_status"] == "ACCEPTED", boarding_after
    assert_money_field(boarding_after, "accepted_price_cents", 1250)

    entries, meta = validate_paginated(
        api.list_booking_revenue_entries(booking["id"], REVENUE_ACCOUNTANT)
    )
    assert meta["total_count"] == 1, f"expiry posts no revenue of its own: {entries}"
    sale = find_one_entry(entries, entry_type="SALE", category="BOARDING")
    # 1250 x 400bp service tax = 50, so 1200 nets through
    assert_entry_amounts(sale, gross_cents=1250, tax_cents=50, net_cents=1200)

    settled = scenario.get_booking(booking["id"], channel["id"])
    assert_money_field(settled, "ancillary_gross_cents", 1250)
    assert_money_field(settled, "recognized_ancillary_net_cents", 1200)


def test_publishing_to_an_unknown_channel_reports_the_channel_not_found(api, scenario):
    """PRD §2.7: "**404 by body reference** — every foreign key supplied in the request
    body resolves to a stored row, validated in the order the operation declares its
    inputs, using the same per-entity not-found error ids as the previous step."
    PRD §2.7: "a distribution-channel id yields `ERR_DISTRIBUTION_CHANNEL_NOT_FOUND`"
    PRD §3.4: "Either way, `published_fee_fingerprint` and `published_family_version` are
    pinned from the family, the family's `publication_count` is recomputed, and the
    family's `version` increments."

    Design: Corner/endpoints/publication_with_an_unknown_channel_returns_channel_not_found
    """
    bag = scenario.create_product(_checked_bag())
    family = scenario.create_family(factories.eco_lite_family_payload())
    scenario.add_attribute(
        family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1
    )
    published = scenario.publish_family(family["id"])
    assert published["status"] == "PUBLISHED", published["status"]
    assert published["publication_count"] == 0, published["publication_count"]

    # The family resolves; only the channel reference is a stranger.
    response = api.create_channel_publication(
        factories.channel_publication_payload(
            family["id"], NON_EXISTENT_UUID, published["version"]
        ),
        DISTRIBUTION_MANAGER,
    )
    validate_error(response, ApiErrorId.DISTRIBUTION_CHANNEL_NOT_FOUND)

    publications, meta = validate_paginated(
        api.list_channel_publications(
            DISTRIBUTION_MANAGER, {"fare_family_id": family["id"]}
        )
    )
    assert meta["total_count"] == 0, f"the refused call stored nothing: {publications}"

    after = scenario.get_family(family["id"])
    assert after["publication_count"] == 0, after["publication_count"]
    assert after["version"] == published["version"], (
        "a refused publication must not bump the family: "
        f"{published['version']} -> {after['version']}"
    )


def test_seat_segment_read_reports_its_derived_counts_and_price(api, scenario):
    """PRD §3.3: "The row interval is **closed** at both ends: a segment with `row_start`
    10 and `row_end` 12 covers rows 10, 11 and 12. The segment's `total_seats` is
    therefore `row_end` minus `row_start` plus one, multiplied by the number of entries in
    `seat_letters`."
    PRD §3.3: "At creation `available_seats` equals `total_seats`, `held_seats` and
    `sold_seats` are 0, and `segment_state` is `OPEN`."
    PRD §3.3: "the zone multiplier stored on the segment as `zone_multiplier_bp`, which is
    13,000 basis points for `FWD`, 10,000 for `MID`, 9,000 for `AFT`, 16,000 for
    `EXIT_ROW` and 14,000 for `BULKHEAD`"
    PRD §3.3: "Segments are readable singly and as a paginated list filterable by
    `flight_id`, by `ancillary_product_id`, by `zone` and by `segment_state`."
    PRD §2.1: "Every role may read every resource except the revenue ledger, and every
    role may drive the logical clock."

    Design: Corner/endpoints/seat_segment_read_reports_its_derived_counts_and_price
    """
    seat = scenario.create_product(_standard_seat())
    flight = scenario.create_flight()
    segment = scenario.create_segment(
        flight["id"],
        seat["id"],
        zone="MID",
        row_start=10,
        row_end=12,
        seat_letters=["A", "B", "C"],
        base_price_cents=1000,
    )

    # An accountant has no write powers here but may still read the seat map.
    read = validate_success(api.get_seat_segment(segment["id"], REVENUE_ACCOUNTANT))
    assert_field_values(
        read,
        flight_id=flight["id"],
        ancillary_product_id=seat["id"],
        zone="MID",
        row_start=10,
        row_end=12,
        segment_state="OPEN",
    )
    # rows 10, 11 and 12 crossed with three letters = 9 seats, all free
    assert_segment_counts(
        read, total_seats=9, held_seats=0, sold_seats=0, available_seats=9
    )
    assert read["zone_multiplier_bp"] == 10000, read["zone_multiplier_bp"]
    assert_money_field(read, "base_price_cents", 1000)
    # (1000 + 500 band for row 10) x 10000 MID x 10000 LOW / 100,000,000 = 1500
    assert_money_field(read, "effective_price_cents", 1500)

    listed, meta = validate_paginated(
        api.list_seat_segments(REVENUE_ACCOUNTANT, {"flight_id": flight["id"]})
    )
    assert meta["total_count"] == 1, listed
    assert listed[0]["id"] == segment["id"], listed


def test_a_seat_is_free_when_an_accepted_offer_already_covers_its_product(api, scenario):
    """PRD §3.7: "The assignment's `price_charged_cents` is normally the segment's
    `effective_price_cents`, pinned at the instant the seat is taken so that a later
    demand snapshot cannot retroactively change what the passenger was charged."
    PRD §3.7: "But when the booking already holds an offer with `offer_status` `ACCEPTED`
    for the very product the segment references, the seat is priced at **0** — the
    passenger has already paid for seat selection through the ancillary offer and must not
    be billed a second time."
    PRD §3.7: "On a `HELD` booking the seat is taken as `HELD` and the segment's
    `held_seats` increases by one."
    PRD §3.6: "The `RESIDUAL_INVENTORY` variant applies when — and only when — the
    product's `category` is `SEAT` **and** at least one seat segment on the booking's
    flight referencing that product has `segment_state` `OPEN`."

    Design: Corner/endpoints/seat_assignment_is_priced_zero_when_an_accepted_offer_covers_that_product
    """
    legroom = scenario.create_product(_extra_legroom_seat())
    standard = scenario.create_product(_standard_seat())
    change = scenario.create_product(factories.change_flex_product_payload())

    family = scenario.create_family(_merch_family())
    scenario.add_attribute(
        family["id"], change["id"], inclusion="INCLUDED", included_quantity=1
    )
    published = scenario.publish_family(family["id"])
    channel = scenario.create_channel(_direct_web_channel())
    scenario.publish_to_channel(family["id"], channel["id"], published["version"])

    flight = scenario.create_flight()
    scenario.post_demand(flight["id"], 50, 0)
    legroom_segment = scenario.create_segment(
        flight["id"],
        legroom["id"],
        zone="MID",
        row_start=16,
        row_end=16,
        seat_letters=["A", "B", "C"],
        base_price_cents=2000,
    )
    standard_segment = scenario.create_segment(
        flight["id"],
        standard["id"],
        zone="MID",
        row_start=20,
        row_end=20,
        seat_letters=["A", "B", "C"],
        base_price_cents=2000,
    )
    # Both rectangles sit at row 16 or beyond, so neither draws a band adjustment.
    assert_money_field(legroom_segment, "effective_price_cents", 2000)
    assert_money_field(standard_segment, "effective_price_cents", 2000)

    booking = scenario.create_booking(flight["id"], family["id"], channel["id"])
    scenario.open_offer_session(
        booking["id"], channel["id"], "BOOKING", requested_product_ids=[legroom["id"]]
    )
    offers = scenario.offers_for_booking(booking["id"], channel["id"])
    assert len(offers) == 1, offers
    legroom_offer = offers[0]
    # an untouched 3-seat rectangle is 0 percent sold: 10000 + 60 x (0 - 50) = 7000bp,
    # and 4200 x 7000 / 10000 = 2940 sits exactly on the 70-percent-of-list floor
    assert legroom_offer["pricing_variant"] == "RESIDUAL_INVENTORY", legroom_offer
    assert_money_field(legroom_offer, "offered_price_cents", 2940)

    held = scenario.get_booking(booking["id"], channel["id"])
    accepted = scenario.accept_offer(
        legroom_offer["id"], channel["id"], held["version"]
    )
    assert_money_field(accepted, "accepted_price_cents", 2940)

    # A seat from the uncovered segment is charged at the segment's own price.
    standard_assignment = scenario.assign_seat(
        booking["id"], channel["id"], standard_segment["id"], 20, "A"
    )
    assert standard_assignment["assignment_state"] == "HELD", standard_assignment
    assert_money_field(standard_assignment, "price_charged_cents", 2000)

    # A seat from the segment the accepted offer covers costs nothing further.
    legroom_assignment = scenario.assign_seat(
        booking["id"], channel["id"], legroom_segment["id"], 16, "A"
    )
    assert legroom_assignment["assignment_state"] == "HELD", legroom_assignment
    assert_money_field(legroom_assignment, "price_charged_cents", 0)

    # The segment price itself is untouched: only this passenger's charge is zero.
    assert_money_field(
        scenario.get_segment(legroom_segment["id"]), "effective_price_cents", 2000
    )
    assert_segment_counts(
        scenario.get_segment(legroom_segment["id"]),
        total_seats=3,
        held_seats=1,
        sold_seats=0,
        available_seats=2,
    )
    assert_segment_counts(
        scenario.get_segment(standard_segment["id"]),
        total_seats=3,
        held_seats=1,
        sold_seats=0,
        available_seats=2,
    )

    entries, meta = validate_paginated(
        api.list_booking_revenue_entries(booking["id"], REVENUE_ACCOUNTANT)
    )
    assert meta["total_count"] == 1, f"held seats sell nothing yet: {entries}"
    sale = find_one_entry(entries, entry_type="SALE", category="SEAT")
    # 2940 x 400bp service tax = 117.6, half up to 118
    assert_entry_amounts(sale, gross_cents=2940, tax_cents=118, net_cents=2822)

    settled = scenario.get_booking(booking["id"], channel["id"])
    assert_money_field(settled, "ancillary_gross_cents", 2940)
    assert_money_field(settled, "recognized_ancillary_net_cents", 2822)


def test_resync_repins_a_drifted_publication_to_the_live_family(api, scenario):
    """PRD §3.4: "On success `published_fee_fingerprint` and `published_family_version`
    are re-pinned to the family's live values, `drift_reason` is cleared to null,
    `last_resync_at` is stamped from the logical clock, and the channel's
    `content_parity_status` is re-derived, returning to `COMPLIANT` once no publication of
    that channel remains `OUT_OF_PARITY`."
    PRD §3.4: "`parity_breach_count` is deliberately untouched: it is monotonic and never
    decreases."
    PRD §3.4: "Parity is lost — `IN_PARITY` → `OUT_OF_PARITY` — by exactly three upstream
    events, and the `drift_reason` recorded tells them apart: repricing or withdrawing one
    of the family's attributes stamps `ATTRIBUTE_REPRICED`"
    PRD §2.8: "it increases by one each time one of the channel's publications moves from
    `IN_PARITY` to `OUT_OF_PARITY`, and it never decreases, not even when the publication
    is resynchronised."
    PRD §2.10: "an integer that increments by exactly 1 on every mutation of the
    resource. It starts at 1 when the resource is created."

    Design: Corner/endpoints/resync_repins_a_drifted_publication_to_the_live_family_content
    """
    scenario.set_clock(CLOCK_9AM)
    bag = scenario.create_product(_checked_bag())
    family = scenario.create_family(factories.eco_lite_family_payload())
    attribute = scenario.add_attribute(
        family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1
    )
    approved = scenario.publish_family(family["id"])
    # created 1, attached 2, submitted 3, approved 4
    assert approved["version"] == 4, approved["version"]

    channel = scenario.create_channel(_direct_web_channel())
    publication = scenario.publish_to_channel(
        family["id"], channel["id"], approved["version"]
    )
    assert publication["parity_state"] == "IN_PARITY", publication
    assert publication["published_fee_fingerprint"] == (
        "ECO_LITE|1|BAG_CHECKED_1:INCLUDED:1:3500"
    ), publication["published_fee_fingerprint"]
    pinned_at_publication = publication["published_family_version"]
    assert publication["version"] == 1, publication["version"]

    # Repricing the attribute drifts the published content underneath the channel.
    validate_success(
        api.update_family_attribute(
            attribute["id"], {"override_price_cents": 3000}, MERCHANDISING_ANALYST
        )
    )

    drifted = scenario.get_publication(publication["id"])
    assert drifted["parity_state"] == "OUT_OF_PARITY", drifted
    assert drifted["drift_reason"] == "ATTRIBUTE_REPRICED", drifted
    # the pins still quote the pre-reprice content, which is what makes it drift
    assert drifted["published_fee_fingerprint"] == (
        "ECO_LITE|1|BAG_CHECKED_1:INCLUDED:1:3500"
    ), drifted["published_fee_fingerprint"]
    assert drifted["published_family_version"] == pinned_at_publication, drifted
    assert drifted["version"] == 2, drifted["version"]

    breached = scenario.get_channel(channel["id"])
    assert breached["content_parity_status"] == "BREACHED", breached
    assert breached["parity_breach_count"] == 1, breached

    resynced = validate_success(
        api.resync_channel_publication(publication["id"], {}, DISTRIBUTION_MANAGER)
    )
    assert resynced["parity_state"] == "IN_PARITY", resynced
    assert resynced["drift_reason"] is None, resynced["drift_reason"]
    # the live fingerprint now quotes the 3000 override, revision 1 as approval never
    # touches revision_no
    assert resynced["published_fee_fingerprint"] == (
        "ECO_LITE|1|BAG_CHECKED_1:INCLUDED:1:3000"
    ), resynced["published_fee_fingerprint"]
    # the pin has moved off the version it was published against
    assert resynced["published_family_version"] != pinned_at_publication, resynced
    assert _instant(resynced["last_resync_at"]) == _instant(CLOCK_9AM), resynced
    # created 1, drifted 2, resynced 3
    assert resynced["version"] == 3, resynced["version"]

    live_family = scenario.get_family(family["id"])
    assert live_family["version"] == 6, live_family["version"]
    assert_money_field(live_family, "unbundled_value_cents", 3000)
    assert resynced["published_fee_fingerprint"] == live_family["fee_fingerprint"]
    assert resynced["published_family_version"] == live_family["version"]

    restored = scenario.get_channel(channel["id"])
    assert restored["content_parity_status"] == "COMPLIANT", restored
    # the audit counter records that parity was lost once and stays there
    assert restored["parity_breach_count"] == 1, restored
