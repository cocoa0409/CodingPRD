"""Concurrency tokens, version movement and counter reconciliation.

The two concurrency tokens in this contract guard exactly two writes: accepting an
ancillary offer and publishing a family to a channel.  These tests replay a stale
token against both, then follow the version counters and the derived seat and
publication counters through a whole sequence of writes to prove they always
recompute rather than drift.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    DISTRIBUTION_MANAGER,
    OPERATIONS_CONTROLLER,
    assert_entry_amounts,
    assert_recognized_net_matches_ledger,
    assert_segment_counts,
    factories,
    find_one_entry,
    make_channel_partner_headers,
)

CHECKED_BAG = dict(
    sku="BAG_CHECKED_1",
    name="First checked bag",
    category="BAGGAGE",
    list_price_cents=3500,
    tax_treatment="TAXABLE_SERVICE",
    revenue_class="NON_AIR",
    revenue_account_code="4100",
)

PRIORITY_BOARDING = dict(
    sku="PRIORITY_BOARDING",
    name="Priority boarding",
    category="BOARDING",
    list_price_cents=1250,
    tax_treatment="TAXABLE_SERVICE",
    revenue_class="NON_AIR",
    revenue_account_code="4400",
)

STANDARD_SEAT = dict(
    sku="SEAT_STANDARD",
    name="Standard seat",
    category="SEAT",
    list_price_cents=1900,
    tax_treatment="TAXABLE_SERVICE",
    revenue_class="NON_AIR",
    revenue_account_code="4200",
    refundable=True,
)


def test_replaying_a_stale_expected_booking_version_on_accept_is_refused(api, scenario):
    """PRD §2.6: "The accept request must carry `expected_booking_version`, a
    non-optional integer field holding the client's last observed `version` of the
    offer's parent `Booking`. If it does not equal that booking's current `version`,
    the request is rejected with `ERR_STALE_BOOKING_VERSION` (HTTP 412)."
    PRD §2.4: "an integer that increments by exactly 1 on every mutation of the
    resource. It starts at 1 when the resource is created."
    PRD §2.10: "a booking's `recognized_ancillary_net_cents` always equals the signed
    sum of `net_cents` over that booking's revenue entries whose `category` is
    anything other than `AIR_TRANSPORT`; correspondingly, `ancillary_gross_cents`
    always equals the signed sum of `gross_cents` over that booking's entries whose
    `entry_type` is `SALE`, `REFUND`, `WAIVER_CREDIT` or `WAIVER_REVERSAL`."

    Design: Corner/cross_cutting_complexity_layers/offer_accept_with_a_stale_expected_booking_version_returns_412
    """
    bag = scenario.create_product(factories.ancillary_product_payload(**CHECKED_BAG))
    boarding = scenario.create_product(
        factories.ancillary_product_payload(**PRIORITY_BOARDING)
    )
    family = scenario.create_family(
        factories.fare_family_payload(
            code="ECO_BARE",
            name="Economy Bare",
            base_fare_cents=12000,
            bundle_price_cents=12000,
        )
    )
    channel = scenario.create_channel(channel_code="DIRECT_WEB", channel_type="DIRECT")
    flight = scenario.create_flight(
        flight_no="AC580",
        origin="SFO",
        destination="JFK",
        scheduled_departure_utc="2026-09-01T15:00:00Z",
        cabin_seat_total=120,
    )
    scenario.post_demand(flight["id"], 50, 0)
    booking = scenario.create_booking(
        flight["id"],
        family["id"],
        channel["id"],
        record_locator="OCC001",
        passenger_name="Ada Lovelace",
    )
    partner = make_channel_partner_headers(channel["id"])

    scenario.open_offer_session(
        booking["id"], channel["id"], "BOOKING", [bag["id"], boarding["id"]]
    )
    offers = scenario.offers_for_booking(booking["id"], channel["id"])
    assert len(offers) == 2, f"both requested products were offered: {offers}"
    by_product = {offer["ancillary_product_id"]: offer for offer in offers}

    # The channel reads the booking once and then tries to bank both offers against
    # that one reading.
    stale_version = scenario.get_booking(booking["id"], channel["id"])["version"]
    first = scenario.accept_offer(
        by_product[bag["id"]]["id"], channel["id"], stale_version
    )
    assert first["accepted_price_cents"] == 3500, (
        f"a direct channel adds no markup to the bag: {first['accepted_price_cents']}"
    )

    validate_error(
        api.accept_offer(
            by_product[boarding["id"]]["id"],
            factories.offer_accept_payload(stale_version),
            partner,
        ),
        ApiErrorId.STALE_BOOKING_VERSION,
    )

    untouched = validate_success(
        api.get_ancillary_offer(by_product[boarding["id"]]["id"], partner)
    )
    assert untouched["offer_status"] == "PRESENTED", (
        f"a refused acceptance leaves the offer on the table: {untouched['offer_status']}"
    )
    assert untouched["accepted_price_cents"] is None, (
        f"and freezes no price: {untouched['accepted_price_cents']}"
    )

    midway = scenario.get_booking(booking["id"], channel["id"])
    assert midway["ancillary_gross_cents"] == 3500, (
        f"only the bag was sold: {midway['ancillary_gross_cents']}"
    )
    assert midway["recognized_ancillary_net_cents"] == 3360, (
        "3500 less 400 basis points of service tax: "
        f"{midway['recognized_ancillary_net_cents']}"
    )
    assert len(scenario.booking_ledger(booking["id"])) == 1, (
        "a refused acceptance posts nothing to the append-only ledger"
    )
    assert midway["version"] == stale_version + 1, (
        "exactly one write landed, so the booking sits one version past the reading "
        f"the channel held: expected {stale_version + 1} but read {midway['version']}"
    )

    # Re-read, retry, and the second offer banks too.
    second = scenario.accept_offer(
        by_product[boarding["id"]]["id"], channel["id"], midway["version"]
    )
    assert second["offer_status"] == "ACCEPTED", (
        f"the retry with the current version succeeds: {second['offer_status']}"
    )
    assert second["accepted_price_cents"] == 1250, (
        f"priority boarding banks at its list price: {second['accepted_price_cents']}"
    )

    final = scenario.get_booking(booking["id"], channel["id"])
    assert final["ancillary_gross_cents"] == 4750, (
        f"3500 for the bag plus 1250 for boarding: {final['ancillary_gross_cents']}"
    )
    assert final["recognized_ancillary_net_cents"] == 4560, (
        f"3360 plus 1200 net of service tax: {final['recognized_ancillary_net_cents']}"
    )
    entries = scenario.booking_ledger(booking["id"])
    assert len(entries) == 2, f"one sale row per accepted offer: {entries}"
    assert_recognized_net_matches_ledger(final, entries)
    assert_entry_amounts(
        find_one_entry(entries, entry_type="SALE", product_sku="PRIORITY_BOARDING"),
        gross_cents=1250,
        tax_cents=50,
        net_cents=1200,
    )
    assert final["version"] == stale_version + 2, (
        "two acceptances, two version steps: expected "
        f"{stale_version + 2} but read {final['version']}"
    )


def test_replaying_a_stale_expected_family_version_on_publication_is_refused(api, scenario):
    """PRD §2.6: "The publication-create request must carry
    `expected_fare_family_version`, a non-optional integer field holding the client's
    last observed `version` of the target `FareFamily`. If it does not equal that
    family's current `version`, the request is rejected with
    `ERR_STALE_FAMILY_VERSION` (HTTP 412)."
    PRD §3.4: "Either way, `published_fee_fingerprint` and `published_family_version`
    are pinned from the family, the family's `publication_count` is recomputed, and
    the family's `version` increments."

    Design: Corner/cross_cutting_complexity_layers/publication_create_with_a_stale_expected_family_version_returns_412
    """
    bag = scenario.create_product(factories.ancillary_product_payload(**CHECKED_BAG))
    family = scenario.create_family(
        factories.fare_family_payload(
            code="ECO_OCC",
            name="Economy Concurrency",
            base_fare_cents=12000,
            bundle_price_cents=14000,
        )
    )
    scenario.add_attribute(
        family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1
    )
    approved = scenario.publish_family(family["id"])
    first_channel = scenario.create_channel(
        channel_code="OTA_ONE", channel_type="OTA", commission_bp=900, markup_bp=500
    )
    second_channel = scenario.create_channel(
        channel_code="OTA_TWO", channel_type="OTA", commission_bp=800, markup_bp=300
    )

    version_at_approval = approved["version"]
    first_publication = scenario.publish_to_channel(
        family["id"], first_channel["id"], version_at_approval
    )

    # Publishing to the first reseller already moved the family, so the same reading
    # is no longer good enough for the second.
    validate_error(
        api.create_channel_publication(
            factories.channel_publication_payload(
                family["id"], second_channel["id"], version_at_approval
            ),
            DISTRIBUTION_MANAGER,
        ),
        ApiErrorId.STALE_FAMILY_VERSION,
    )

    midway = scenario.get_family(family["id"])
    assert midway["publication_count"] == 1, (
        f"the refused publication did not reach the shelf: {midway['publication_count']}"
    )
    assert midway["version"] == version_at_approval + 1, (
        "one publication landed and the refusal changed nothing, so the family sits "
        f"one version past approval: expected {version_at_approval + 1} but read {midway['version']}"
    )

    second_publication = scenario.publish_to_channel(
        family["id"], second_channel["id"], midway["version"]
    )

    expected_fingerprint = "ECO_OCC|1|BAG_CHECKED_1:INCLUDED:1:3500"
    for publication in (first_publication, second_publication):
        stored = scenario.get_publication(publication["id"])
        assert stored["parity_state"] == "IN_PARITY", (
            "a publication of an already published family is in parity from the "
            f"moment it is created: {stored['parity_state']}"
        )
        assert stored["published_fee_fingerprint"] == expected_fingerprint, (
            f"each publication pinned the family's live fingerprint: {stored['published_fee_fingerprint']}"
        )

    publications, publications_meta = validate_paginated(
        api.list_channel_publications(
            DISTRIBUTION_MANAGER, {"fare_family_id": family["id"]}
        )
    )
    assert publications_meta["total_count"] == 2, (
        f"exactly the two accepted publications exist: {publications_meta}"
    )
    assert {row["distribution_channel_id"] for row in publications} == {
        first_channel["id"],
        second_channel["id"],
    }, f"one publication per reseller: {publications}"

    final = scenario.get_family(family["id"])
    assert final["publication_count"] == 2, (
        f"the count is recomputed from the rows, not incremented blindly: {final['publication_count']}"
    )
    assert final["fee_fingerprint"] == expected_fingerprint, (
        f"publishing to channels never reshapes the family itself: {final['fee_fingerprint']}"
    )
    assert final["revision_no"] == 1, (
        f"no rejection ever happened, so the revision holds at 1: {final['revision_no']}"
    )


def test_the_booking_version_moves_on_writes_and_stands_still_on_reads(api, scenario):
    """PRD §2.4: "an integer that increments by exactly 1 on every mutation of the
    resource. It starts at 1 when the resource is created."
    PRD §3.5: "Both paths increment the booking's `version`."
    PRD §3.5: "On success `disclosure_acked_at` is stamped from the logical clock and
    the booking's `version` increments."

    Design: Corner/cross_cutting_complexity_layers/booking_version_advances_on_writes_and_stands_still_on_reads
    """
    family = scenario.create_family(
        factories.fare_family_payload(
            code="ECO_BARE",
            name="Economy Bare",
            base_fare_cents=12000,
            bundle_price_cents=12000,
        )
    )
    channel = scenario.create_channel(channel_code="DIRECT_WEB", channel_type="DIRECT")
    flight = scenario.create_flight(
        flight_no="AC581",
        origin="SFO",
        destination="JFK",
        scheduled_departure_utc="2026-09-01T15:00:00Z",
        cabin_seat_total=120,
    )
    partner = make_channel_partner_headers(channel["id"])

    booking = scenario.create_booking(
        flight["id"],
        family["id"],
        channel["id"],
        record_locator="VERS01",
        passenger_name="Ada Lovelace",
    )
    assert booking["version"] == 1, (
        f"a freshly held booking is at version 1: {booking['version']}"
    )

    disclosed = validate_success(api.issue_disclosure(booking["id"], {}, partner))
    assert disclosed["version"] == 2, (
        f"issuing the fee disclosure is the first write after creation: {disclosed['version']}"
    )
    assert disclosed["disclosure_state"] == "PENDING_ACK", (
        f"the disclosure is out and waiting: {disclosed['disclosure_state']}"
    )
    assert disclosed["disclosed_fee_fingerprint"] == "ECO_BARE|1|", (
        "a family with no attributes snapshots as code, bar, revision, bar: "
        f"{disclosed['disclosed_fee_fingerprint']}"
    )

    assert scenario.get_booking(booking["id"], channel["id"])["version"] == 2, (
        "reading a booking is not a mutation"
    )

    acked = validate_success(
        api.acknowledge_disclosure(
            booking["id"], factories.disclosure_ack_payload("ECO_BARE|1|"), partner
        )
    )
    assert acked["version"] == 3, (
        f"the acknowledgement is the second write: {acked['version']}"
    )
    assert acked["disclosure_state"] == "ACKNOWLEDGED", (
        f"the passenger has seen the fees: {acked['disclosure_state']}"
    )
    assert acked["disclosure_acked_at"] is not None, (
        "the acknowledgement instant is stamped from the logical clock"
    )

    assert scenario.get_booking(booking["id"], channel["id"])["version"] == 3, (
        "reading a booking twice does not move it either"
    )

    cancelled = validate_success(
        api.cancel_booking(booking["id"], factories.cancel_payload("Passenger request"), partner)
    )
    assert cancelled["version"] == 4, (
        f"cancelling is the third and last write: {cancelled['version']}"
    )
    assert cancelled["booking_status"] == "CANCELLED", (
        f"and it really cancelled: {cancelled['booking_status']}"
    )
    assert scenario.booking_ledger(booking["id"]) == [], (
        "a booking cancelled before it was ever ticketed has nothing to reverse"
    )


def test_segment_counters_reconcile_through_a_hold_a_release_and_a_cancel(api, scenario):
    """PRD §2.10: "a segment's `available_seats` always equals its `total_seats` minus
    its `held_seats` minus its `sold_seats`."
    PRD §3.7: "Releasing from `HELD` decreases the segment's `held_seats` by one and
    increases its `available_seats` by one, and posts and reverses **nothing**,
    because a held seat was never sold."
    PRD §3.7: "An explicit release stamps `PASSENGER_RELEASE`."
    PRD §3.7: "A release cascaded from a booking cancellation stamps
    `BOOKING_CANCELLED`."

    Design: Corner/cross_cutting_complexity_layers/available_seats_reconciles_after_a_hold_a_release_and_a_cancel
    """
    seat = scenario.create_product(factories.ancillary_product_payload(**STANDARD_SEAT))
    family = scenario.create_family(
        factories.fare_family_payload(
            code="ECO_BARE",
            name="Economy Bare",
            base_fare_cents=12000,
            bundle_price_cents=12000,
        )
    )
    channel = scenario.create_channel(channel_code="DIRECT_WEB", channel_type="DIRECT")
    flight = scenario.create_flight(
        flight_no="AC582",
        origin="SFO",
        destination="JFK",
        scheduled_departure_utc="2026-09-01T15:00:00Z",
        cabin_seat_total=120,
    )
    segment = scenario.create_segment(
        flight["id"],
        seat["id"],
        zone="MID",
        row_start=20,
        row_end=20,
        seat_letters=["A", "B", "C"],
        base_price_cents=2000,
    )
    scenario.post_demand(flight["id"], 50, 0)
    booking = scenario.create_booking(
        flight["id"],
        family["id"],
        channel["id"],
        record_locator="RECON1",
        passenger_name="Ada Lovelace",
    )

    assert_segment_counts(
        scenario.get_segment(segment["id"]),
        total_seats=3,
        held_seats=0,
        sold_seats=0,
        available_seats=3,
    )

    # Hold 20A.
    first = scenario.assign_seat(booking["id"], channel["id"], segment["id"], 20, "A")
    assert first["assignment_state"] == "HELD", (
        f"a held booking can only hold a seat: {first['assignment_state']}"
    )
    assert first["price_charged_cents"] == 2000, (
        f"the assignment records the segment's effective price: {first['price_charged_cents']}"
    )
    assert_segment_counts(
        scenario.get_segment(segment["id"]),
        total_seats=3,
        held_seats=1,
        sold_seats=0,
        available_seats=2,
    )

    # Give 20A back.
    released = scenario.release_seat(first["id"], channel["id"], "PASSENGER_RELEASE")
    assert released["assignment_state"] == "RELEASED", (
        f"the explicit release lands: {released['assignment_state']}"
    )
    assert released["released_reason"] == "PASSENGER_RELEASE", (
        f"and is recorded as the passenger's own: {released['released_reason']}"
    )
    assert_segment_counts(
        scenario.get_segment(segment["id"]),
        total_seats=3,
        held_seats=0,
        sold_seats=0,
        available_seats=3,
    )
    assert scenario.booking_ledger(booking["id"]) == [], (
        "releasing a held seat reverses nothing, because a held seat was never sold"
    )

    # Hold 20B instead.
    second = scenario.assign_seat(booking["id"], channel["id"], segment["id"], 20, "B")
    assert second["assignment_state"] == "HELD", (
        f"the second seat is held in turn: {second['assignment_state']}"
    )
    assert_segment_counts(
        scenario.get_segment(segment["id"]),
        total_seats=3,
        held_seats=1,
        sold_seats=0,
        available_seats=2,
    )

    # Cancelling the booking sweeps the held seat back into inventory.
    scenario.cancel(booking["id"], channel["id"], "Passenger request")
    assert_segment_counts(
        scenario.get_segment(segment["id"]),
        total_seats=3,
        held_seats=0,
        sold_seats=0,
        available_seats=3,
    )

    swept = validate_success(api.get_seat_assignment(second["id"], OPERATIONS_CONTROLLER))
    assert swept["assignment_state"] == "RELEASED", (
        f"the cancellation released the held seat: {swept['assignment_state']}"
    )
    assert swept["released_reason"] == "BOOKING_CANCELLED", (
        f"and recorded the cancellation as the cause: {swept['released_reason']}"
    )
    kept = validate_success(api.get_seat_assignment(first["id"], OPERATIONS_CONTROLLER))
    assert kept["released_reason"] == "PASSENGER_RELEASE", (
        "the earlier release keeps its own reason: the cascade must not rewrite "
        f"history: {kept['released_reason']}"
    )

    assignments, assignments_meta = validate_paginated(
        api.list_seat_assignments(
            OPERATIONS_CONTROLLER, {"seat_inventory_segment_id": segment["id"]}
        )
    )
    assert assignments_meta["total_count"] == 2, (
        f"both assignments survive as history: {assignments_meta}"
    )
    assert all(row["assignment_state"] == "RELEASED" for row in assignments), (
        f"neither seat is held or confirmed any more: {assignments}"
    )
    assert scenario.booking_ledger(booking["id"]) == [], (
        "no seat was ever sold on this booking, so the ledger stayed empty throughout"
    )


def test_publication_count_reconciles_after_two_publications_and_a_retirement(api, scenario):
    """PRD §3.4: "The family's `publication_count` is recomputed, counting the
    publications of this family whose `parity_state` is `PENDING`, `IN_PARITY` or
    `OUT_OF_PARITY`."
    PRD §3.2: "`PUBLISHED` → `RETIRED` and `SUSPENDED` → `RETIRED` both require that
    no booking on the family has a `booking_status` of `HELD`, `TICKETED` or
    `CHANGE_PENDING`, or the retirement is refused with
    `ERR_FAMILY_HAS_LIVE_BOOKINGS`; both then move every publication of the family
    whose `parity_state` is `PENDING`, `IN_PARITY` or `OUT_OF_PARITY` to `WITHDRAWN`
    and recompute `publication_count`, which consequently falls to 0."
    PRD §2.8: "it reads `BREACHED` when the channel's `parity_required` is true and at
    least one of that channel's publications is `OUT_OF_PARITY`, and `COMPLIANT`
    otherwise."

    Design: Corner/cross_cutting_complexity_layers/publication_count_reconciles_after_two_publications_and_a_retirement
    """
    bag = scenario.create_product(factories.ancillary_product_payload(**CHECKED_BAG))
    family = scenario.create_family(
        factories.fare_family_payload(
            code="ECO_MULTI",
            name="Economy Multi Channel",
            base_fare_cents=12000,
            bundle_price_cents=14000,
        )
    )
    scenario.add_attribute(
        family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1
    )
    approved = scenario.publish_family(family["id"])
    assert approved["publication_count"] == 0, (
        f"nothing is on any shelf yet: {approved['publication_count']}"
    )
    direct = scenario.create_channel(channel_code="DIRECT_WEB", channel_type="DIRECT")
    reseller = scenario.create_channel(
        channel_code="OTA_ONE", channel_type="OTA", commission_bp=900, markup_bp=500
    )

    first = scenario.publish_to_channel(family["id"], direct["id"], approved["version"])
    assert first["parity_state"] == "IN_PARITY", (
        f"the family is already published, so the shelf is in parity at once: {first['parity_state']}"
    )
    after_first = scenario.get_family(family["id"])
    assert after_first["publication_count"] == 1, (
        f"one shelf, one count: {after_first['publication_count']}"
    )

    second = scenario.publish_to_channel(
        family["id"], reseller["id"], after_first["version"]
    )
    assert second["parity_state"] == "IN_PARITY", (
        f"the second shelf is in parity at once too: {second['parity_state']}"
    )
    after_second = scenario.get_family(family["id"])
    assert after_second["publication_count"] == 2, (
        f"two shelves, two count: {after_second['publication_count']}"
    )

    for channel in (direct, reseller):
        stored = scenario.get_channel(channel["id"])
        assert stored["content_parity_status"] == "COMPLIANT", (
            f"nothing has drifted out of parity: {stored['content_parity_status']}"
        )
        assert stored["parity_breach_count"] == 0, (
            f"and no breach has ever been counted: {stored['parity_breach_count']}"
        )

    retired = scenario.change_family_status(family["id"], "RETIRED", "Season ended")
    assert retired["status"] == "RETIRED", (
        f"with no bookings at all the family retires freely: {retired['status']}"
    )
    assert retired["publication_count"] == 0, (
        "retirement withdraws both shelves, and the recomputed count falls to 0 rather "
        f"than to 1: {retired['publication_count']}"
    )

    publications, publications_meta = validate_paginated(
        api.list_channel_publications(
            DISTRIBUTION_MANAGER, {"fare_family_id": family["id"]}
        )
    )
    assert publications_meta["total_count"] == 2, (
        f"both publication rows survive the retirement as history: {publications_meta}"
    )
    assert all(row["parity_state"] == "WITHDRAWN" for row in publications), (
        f"every one of them is withdrawn: {publications}"
    )

    for channel in (direct, reseller):
        stored = scenario.get_channel(channel["id"])
        assert stored["content_parity_status"] == "COMPLIANT", (
            "a withdrawn publication is not an out-of-parity one: "
            f"{stored['content_parity_status']}"
        )
        assert stored["parity_breach_count"] == 0, (
            f"withdrawal is not a breach: {stored['parity_breach_count']}"
        )
