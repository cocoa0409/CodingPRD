"""Uniqueness collisions and sales-eligibility refusals.

Each test drives one product, family, publication, booking or seat segment into
the exact situation a refusal names, then checks that the refusal carried the
identifier the contract pins for it and that nothing moved behind it.  Where two
refusals could both be true, the test also proves the losing identifier was not
the one reported.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    DISTRIBUTION_MANAGER,
    MERCHANDISING_ANALYST,
    OPERATIONS_CONTROLLER,
    PRICING_APPROVER,
    assert_segment_counts,
    factories,
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


def test_ticketing_a_boarding_flight_is_refused_for_the_closed_sales_phase(api, scenario):
    """PRD §2.7: "the flight's `sales_phase` is `PRESALE` or `CHECKIN_OPEN` when a
    booking is ticketed. This guards ticketing only."
    PRD §3.5: "The flight's `sales_phase` must be `PRESALE` or `CHECKIN_OPEN`
    (`ERR_FLIGHT_SALES_PHASE_CLOSED`)."
    PRD §2.7: "Checks are evaluated in a fixed order and the **first** failure
    determines the response."

    Design: Corner/errors/ticketing_during_boarding_returns_flight_sales_phase_closed
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
        flight_no="AC556",
        origin="SFO",
        destination="JFK",
        scheduled_departure_utc="2026-09-01T15:00:00Z",
        cabin_seat_total=120,
    )
    booking = scenario.create_booking(
        flight["id"],
        family["id"],
        channel["id"],
        record_locator="PHASE1",
        passenger_name="Ada Lovelace",
    )
    partner = make_channel_partner_headers(channel["id"])

    # The retailing timeline walks past the booking, which is still held and has
    # never been fee-disclosed on a family that never left draft.
    scenario.advance_phase(flight["id"], "CHECKIN_OPEN")
    scenario.advance_phase(flight["id"], "BOARDING")

    error = validate_error(
        api.ticket_booking(booking["id"], {}, partner),
        ApiErrorId.FLIGHT_SALES_PHASE_CLOSED,
    )
    assert error["error_id"] != ApiErrorId.FAMILY_NOT_PUBLISHED, (
        "the flight's phase is checked before the family's publication status, so "
        f"the draft family must not decide this refusal: {error}"
    )
    assert error["error_id"] != ApiErrorId.FEE_DISCLOSURE_NOT_ACKNOWLEDGED, (
        "the flight's phase is checked before the disclosure gate, so the missing "
        f"acknowledgement must not decide this refusal: {error}"
    )

    still_held = scenario.get_booking(booking["id"], channel["id"])
    assert still_held["booking_status"] == "HELD", (
        f"a refused ticketing leaves the booking held: {still_held['booking_status']}"
    )
    assert still_held["fare_component_cents"] is None, (
        "fare_component_cents is only pinned by a successful ticketing but reads "
        f"{still_held['fare_component_cents']}"
    )
    assert still_held["channel_settlement_total_cents"] == 0, (
        "settlement stays at 0 until ticketing populates the fare component but reads "
        f"{still_held['channel_settlement_total_cents']}"
    )

    flight_after = validate_success(api.get_flight(flight["id"], OPERATIONS_CONTROLLER))
    assert flight_after["ticketed_booking_count"] == 0, (
        f"no booking was ticketed, so the count stays 0: {flight_after['ticketed_booking_count']}"
    )
    assert scenario.booking_ledger(booking["id"]) == [], (
        "a refused ticketing posts no allocation entries at all"
    )


def test_each_natural_key_collision_answers_with_its_own_duplicate_identifier(api, scenario):
    """PRD §2.7: "each natural key is unique across all stored rows and carries its
    own error id: a duplicate product `sku` yields `ERR_DUPLICATE_SKU`, a duplicate
    family `code` yields `ERR_DUPLICATE_FAMILY_CODE`, and a duplicate `channel_code`
    yields `ERR_DUPLICATE_CHANNEL_CODE`. These guard product creation, family
    creation and channel registration respectively."

    Design: Corner/errors/natural_key_duplicates_each_return_their_own_duplicate_error
    """
    scenario.create_product(factories.ancillary_product_payload(**CHECKED_BAG))
    scenario.create_family(
        factories.fare_family_payload(
            code="ECO_LITE",
            name="Economy Lite",
            base_fare_cents=12000,
            bundle_price_cents=14000,
        )
    )
    scenario.create_channel(channel_code="DIRECT_WEB", channel_type="DIRECT")

    # Each retake reuses only the natural key: everything else about the row differs,
    # so a collision cannot be mistaken for an idempotent replay.
    validate_error(
        api.create_ancillary_product(
            factories.ancillary_product_payload(
                sku="BAG_CHECKED_1",
                name="Second checked bag",
                category="SEAT",
                list_price_cents=9900,
                tax_treatment="EXEMPT",
                revenue_class="AIR_TRANSPORT_RELATED",
                revenue_account_code="4999",
            ),
            MERCHANDISING_ANALYST,
        ),
        ApiErrorId.DUPLICATE_SKU,
    )
    validate_error(
        api.create_fare_family(
            factories.fare_family_payload(
                code="ECO_LITE",
                name="Economy Lite Reprise",
                base_fare_cents=20000,
                bundle_price_cents=19000,
                refundability="FULLY_REFUNDABLE",
                change_fee_cents=0,
                boarding_priority_tier=1,
            ),
            MERCHANDISING_ANALYST,
        ),
        ApiErrorId.DUPLICATE_FAMILY_CODE,
    )
    validate_error(
        api.create_distribution_channel(
            factories.distribution_channel_payload(
                channel_code="DIRECT_WEB",
                channel_type="OTA",
                commission_bp=900,
                markup_bp=500,
                supported_categories=["BAGGAGE"],
            ),
            DISTRIBUTION_MANAGER,
        ),
        ApiErrorId.DUPLICATE_CHANNEL_CODE,
    )

    products, products_meta = validate_paginated(
        api.list_ancillary_products(MERCHANDISING_ANALYST)
    )
    assert products_meta["total_count"] == 1, (
        f"the refused product must not have been stored: {products_meta}"
    )
    assert products[0]["category"] == "BAGGAGE", (
        f"the surviving product is the original baggage row: {products[0]}"
    )
    assert products[0]["list_price_cents"] == 3500, (
        f"the refused payload must not have repriced the original: {products[0]}"
    )

    families, families_meta = validate_paginated(
        api.list_fare_families(MERCHANDISING_ANALYST)
    )
    assert families_meta["total_count"] == 1, (
        f"the refused family must not have been stored: {families_meta}"
    )
    assert families[0]["base_fare_cents"] == 12000, (
        f"the original base fare survives untouched: {families[0]}"
    )
    assert families[0]["bundle_price_cents"] == 14000, (
        f"the original bundle price survives untouched: {families[0]}"
    )

    channels, channels_meta = validate_paginated(
        api.list_distribution_channels(DISTRIBUTION_MANAGER)
    )
    assert channels_meta["total_count"] == 1, (
        f"the refused channel must not have been registered: {channels_meta}"
    )
    assert channels[0]["channel_type"] == "DIRECT", (
        f"the surviving channel is the original direct one: {channels[0]}"
    )
    assert channels[0]["markup_bp"] == 0, (
        f"the refused payload must not have applied its markup: {channels[0]}"
    )


def test_a_cancelled_bookings_record_locator_is_still_taken(api, scenario):
    """PRD §2.7: "the supplied `record_locator` is unique across all stored bookings,
    including bookings already `CANCELLED` or `FLOWN`. This guards booking creation
    only."
    PRD §3.5: "The record locator must be unique across every stored booking,
    including bookings that have already reached `CANCELLED` or `FLOWN`; a collision
    is refused with `ERR_DUPLICATE_RECORD_LOCATOR`."

    Design: Corner/errors/reusing_the_record_locator_of_a_cancelled_booking_returns_duplicate_record_locator
    """
    family = scenario.create_family(
        factories.fare_family_payload(
            code="ECO_BARE",
            name="Economy Bare",
            base_fare_cents=12000,
            bundle_price_cents=12000,
        )
    )
    direct = scenario.create_channel(channel_code="DIRECT_WEB", channel_type="DIRECT")
    reseller = scenario.create_channel(
        channel_code="OTA_ONE",
        channel_type="OTA",
        commission_bp=900,
        markup_bp=500,
    )
    flight = scenario.create_flight(
        flight_no="AC557",
        origin="SFO",
        destination="JFK",
        scheduled_departure_utc="2026-09-01T15:00:00Z",
        cabin_seat_total=120,
    )
    booking = scenario.create_booking(
        flight["id"],
        family["id"],
        direct["id"],
        record_locator="DUP001",
        passenger_name="Ada Lovelace",
    )

    cancelled = scenario.cancel(booking["id"], direct["id"], "Passenger request")
    assert cancelled["booking_status"] == "CANCELLED", (
        f"the first booking must really be cancelled: {cancelled['booking_status']}"
    )

    # A different reseller, a different passenger, the same six characters.
    validate_error(
        api.create_booking(
            factories.booking_payload(
                flight["id"],
                family["id"],
                reseller["id"],
                record_locator="DUP001",
                passenger_name="Grace Hopper",
            ),
            make_channel_partner_headers(reseller["id"]),
        ),
        ApiErrorId.DUPLICATE_RECORD_LOCATOR,
    )

    bookings, bookings_meta = validate_paginated(api.list_bookings(DISTRIBUTION_MANAGER))
    assert bookings_meta["total_count"] == 1, (
        f"the locator collision stored nothing: {bookings_meta}"
    )
    assert bookings[0]["id"] == booking["id"], (
        f"the only booking is the cancelled original: {bookings[0]}"
    )
    assert bookings[0]["distribution_channel_id"] == direct["id"], (
        f"the surviving booking still belongs to the direct channel: {bookings[0]}"
    )

    _, reseller_meta = validate_paginated(
        api.list_bookings(
            DISTRIBUTION_MANAGER, {"distribution_channel_id": reseller["id"]}
        )
    )
    assert reseller_meta["total_count"] == 0, (
        f"the reseller ended the exchange with no bookings at all: {reseller_meta}"
    )

    flight_after = validate_success(api.get_flight(flight["id"], OPERATIONS_CONTROLLER))
    assert flight_after["ticketed_booking_count"] == 0, (
        f"neither booking was ever ticketed: {flight_after['ticketed_booking_count']}"
    )


def test_re_adding_a_product_is_refused_until_the_first_attribute_is_withdrawn(api, scenario):
    """PRD §2.7: "at most one attribute per fare-family-and-product pair may have
    `attribute_state` `ACTIVE`. This guards attribute attachment only."
    PRD §3.1: "At most one attribute per family-and-product pair may be `ACTIVE` at a
    time, and a second attempt is refused with `ERR_ATTRIBUTE_DUPLICATE_PRODUCT`."
    PRD §2.8: "Withdrawn attributes are excluded from the fingerprint exactly as they
    are excluded from the valuation."

    Design: Corner/errors/re_adding_an_active_product_is_refused_but_a_withdrawn_one_may_come_back
    """
    product = scenario.create_product(factories.ancillary_product_payload(**CHECKED_BAG))
    family = scenario.create_family(
        factories.fare_family_payload(
            code="ECO_DUP",
            name="Economy Duplicate Probe",
            base_fare_cents=12000,
            bundle_price_cents=12000,
        )
    )
    included = scenario.add_attribute(
        family["id"], product["id"], inclusion="INCLUDED", included_quantity=1
    )

    # Selling the same bag a second time - now as a paid extra - collides with the
    # bundled one while that one is still active.
    validate_error(
        api.add_family_attribute(
            family["id"],
            factories.family_attribute_payload(
                product["id"], inclusion="CHARGEABLE", included_quantity=0
            ),
            MERCHANDISING_ANALYST,
        ),
        ApiErrorId.ATTRIBUTE_DUPLICATE_PRODUCT,
    )

    # Retire the bundled row and the paid row is welcome: the constraint counts only
    # the attributes that are still active.
    validate_success(
        api.update_family_attribute(
            included["id"], {"attribute_state": "WITHDRAWN"}, MERCHANDISING_ANALYST
        )
    )
    chargeable = validate_success(
        api.add_family_attribute(
            family["id"],
            factories.family_attribute_payload(
                product["id"], inclusion="CHARGEABLE", included_quantity=0
            ),
            MERCHANDISING_ANALYST,
        ),
        201,
    )

    rows, rows_meta = validate_paginated(
        api.list_family_attributes_of_family(family["id"], MERCHANDISING_ANALYST)
    )
    assert rows_meta["total_count"] == 2, (
        f"the withdrawn row is history, not deleted, so two rows survive: {rows_meta}"
    )
    states = {row["id"]: row["attribute_state"] for row in rows}
    assert states[included["id"]] == "WITHDRAWN", (
        f"the bundled row is withdrawn: {states}"
    )
    assert states[chargeable["id"]] == "ACTIVE", (
        f"the paid row is the live one: {states}"
    )

    refreshed = scenario.get_family(family["id"])
    assert refreshed["unbundled_value_cents"] == 0, (
        "a chargeable bag adds nothing to the bundled value, and the withdrawn row is "
        f"out of the valuation entirely: {refreshed['unbundled_value_cents']}"
    )
    assert refreshed["a_la_carte_total_cents"] == 12000, (
        "with no bundled value the a-la-carte total is just the base fare: "
        f"{refreshed['a_la_carte_total_cents']}"
    )
    assert refreshed["fee_fingerprint"] == "ECO_DUP|1|BAG_CHECKED_1:CHARGEABLE:0:3500", (
        f"only the active chargeable row fingerprints: {refreshed['fee_fingerprint']}"
    )
    assert refreshed["revision_no"] == 1, (
        f"reshaping the attribute set is not a rejection, so the revision holds at 1: {refreshed['revision_no']}"
    )


def test_republishing_the_same_family_and_channel_is_refused(api, scenario):
    """PRD §2.7: "at most one publication per fare-family-and-channel pair may have a
    `parity_state` of `PENDING`, `IN_PARITY` or `OUT_OF_PARITY`. A `WITHDRAWN`
    publication does not block a new one. This guards publication creation only."
    PRD §3.4: "At most one publication per family-and-channel pair may be in
    `PENDING`, `IN_PARITY` or `OUT_OF_PARITY`; a duplicate is refused with
    `ERR_DUPLICATE_PUBLICATION`, though a pair whose only prior publication is
    `WITHDRAWN` may be published again."
    PRD §2.7: "Checks are evaluated in a fixed order and the **first** failure
    determines the response."

    Design: Corner/errors/republishing_the_same_family_channel_pair_returns_duplicate_publication
    """
    product = scenario.create_product(factories.ancillary_product_payload(**CHECKED_BAG))
    family = scenario.create_family(
        factories.fare_family_payload(
            code="ECO_PUB",
            name="Economy Published",
            base_fare_cents=12000,
            bundle_price_cents=14000,
        )
    )
    scenario.add_attribute(
        family["id"], product["id"], inclusion="INCLUDED", included_quantity=1
    )
    approved = scenario.publish_family(family["id"])
    channel = scenario.create_channel(channel_code="DIRECT_WEB", channel_type="DIRECT")

    first = scenario.publish_to_channel(family["id"], channel["id"], approved["version"])

    # Re-read the family so the concurrency token in the retake is current: the pair
    # collision, not a stale version, must be what refuses this request.
    live = scenario.get_family(family["id"])
    error = validate_error(
        api.create_channel_publication(
            factories.channel_publication_payload(
                family["id"], channel["id"], live["version"]
            ),
            DISTRIBUTION_MANAGER,
        ),
        ApiErrorId.DUPLICATE_PUBLICATION,
    )
    assert error["error_id"] != ApiErrorId.STALE_FAMILY_VERSION, (
        "the retake carried the family's current version, so the concurrency token "
        f"must not be what refused it: {error}"
    )

    publications, publications_meta = validate_paginated(
        api.list_channel_publications(
            DISTRIBUTION_MANAGER, {"fare_family_id": family["id"]}
        )
    )
    assert publications_meta["total_count"] == 1, (
        f"the pair still has exactly one publication row: {publications_meta}"
    )
    assert publications[0]["id"] == first["id"], (
        f"the surviving publication is the original one: {publications[0]}"
    )
    assert publications[0]["parity_state"] == "IN_PARITY", (
        f"the original publication is undisturbed: {publications[0]['parity_state']}"
    )

    after = scenario.get_family(family["id"])
    assert after["publication_count"] == 1, (
        f"the refused publication did not raise the count: {after['publication_count']}"
    )
    assert after["version"] == live["version"], (
        "a refused publication must not bump the family: expected version "
        f"{live['version']} but read {after['version']}"
    )


def test_an_undisclosable_chargeable_fee_blocks_the_whole_disclosure(api, scenario):
    """PRD §2.7: "every attribute of the family whose `attribute_state` is `ACTIVE` and
    whose `inclusion` is `CHARGEABLE` references a product whose `disclosable_fee` is
    true. An undisclosable chargeable fee may not be sold at the point of sale. This
    guards disclosure issuance only."
    PRD §3.1: "a family that exposes an active chargeable attribute pointing at a
    product whose `disclosable_fee` is false cannot have a disclosure issued at all,
    and the attempt is refused with `ERR_UNDISCLOSED_FEE_CATEGORY`."
    PRD §2.9: "All five are null while `disclosure_state` is `NOT_ISSUED`."

    Design: Corner/errors/disclosing_a_family_with_an_undisclosable_chargeable_fee_returns_undisclosed_fee_category
    """
    wifi = scenario.create_product(
        factories.ancillary_product_payload(
            sku="WIFI_FULL_FLIGHT",
            name="Full flight wifi",
            category="ONBOARD",
            list_price_cents=750,
            tax_treatment="EXEMPT",
            revenue_class="NON_AIR",
            revenue_account_code="4500",
            refundable=True,
            disclosable_fee=False,
        )
    )
    family = scenario.create_family(
        factories.fare_family_payload(
            code="ECO_HIDE",
            name="Economy Hidden Fee",
            base_fare_cents=12000,
            bundle_price_cents=12000,
        )
    )
    attribute = scenario.add_attribute(
        family["id"], wifi["id"], inclusion="CHARGEABLE", included_quantity=0
    )
    channel = scenario.create_channel(channel_code="DIRECT_WEB", channel_type="DIRECT")
    flight = scenario.create_flight(
        flight_no="AC558",
        origin="SFO",
        destination="JFK",
        scheduled_departure_utc="2026-09-01T15:00:00Z",
        cabin_seat_total=120,
    )
    booking = scenario.create_booking(
        flight["id"],
        family["id"],
        channel["id"],
        record_locator="HIDE01",
        passenger_name="Ada Lovelace",
    )
    partner = make_channel_partner_headers(channel["id"])

    priced = scenario.get_family(family["id"])
    assert priced["fee_fingerprint"] == "ECO_HIDE|1|WIFI_FULL_FLIGHT:CHARGEABLE:0:750", (
        f"the undisclosable wifi fee is nevertheless part of the family: {priced['fee_fingerprint']}"
    )

    validate_error(
        api.issue_disclosure(booking["id"], {}, partner),
        ApiErrorId.UNDISCLOSED_FEE_CATEGORY,
    )

    blocked = scenario.get_booking(booking["id"], channel["id"])
    assert blocked["disclosure_state"] == "NOT_ISSUED", (
        f"a refused issuance leaves the disclosure unissued: {blocked['disclosure_state']}"
    )
    assert blocked["disclosed_fee_fingerprint"] is None, (
        f"nothing was snapshotted: {blocked['disclosed_fee_fingerprint']}"
    )
    assert blocked["disclosure_issued_at"] is None, (
        f"no issuance instant was stamped: {blocked['disclosure_issued_at']}"
    )

    # Pull the undisclosable fee out of the shelf and the same request goes through.
    validate_success(
        api.update_family_attribute(
            attribute["id"], {"attribute_state": "WITHDRAWN"}, MERCHANDISING_ANALYST
        )
    )
    disclosed = validate_success(api.issue_disclosure(booking["id"], {}, partner))
    assert disclosed["disclosure_state"] == "PENDING_ACK", (
        f"the retry issues the disclosure: {disclosed['disclosure_state']}"
    )
    assert disclosed["disclosed_fee_fingerprint"] == "ECO_HIDE|1|", (
        "with the only attribute withdrawn the family fingerprints as code, bar, "
        f"revision, bar: {disclosed['disclosed_fee_fingerprint']}"
    )
    assert disclosed["disclosure_issued_at"] is not None, (
        "a successful issuance stamps the instant it happened"
    )


def test_an_unsupported_category_is_refused_at_the_offer_session(api, scenario):
    """PRD §2.7: "every category the request would merchandise or disclose is a member
    of the channel's `supported_categories`: the categories of the `CHARGEABLE`
    attributes at disclosure, the category of every product named in
    `requested_product_ids` at an offer session, and the offered product's category at
    acceptance."
    PRD §3.6: "Every category named through `requested_product_ids` must be a member
    of the channel's `supported_categories`, or the session is refused with
    `ERR_CHANNEL_CATEGORY_UNSUPPORTED`."
    PRD §3.6: "Third, multiply that result by 10,000 plus the channel's `markup_bp`,
    divide by 10,000, and round half up a third time."

    Design: Corner/errors/merchandising_a_category_the_channel_does_not_support_returns_channel_category_unsupported
    """
    bag = scenario.create_product(factories.ancillary_product_payload(**CHECKED_BAG))
    seat = scenario.create_product(factories.ancillary_product_payload(**STANDARD_SEAT))
    family = scenario.create_family(
        factories.fare_family_payload(
            code="ECO_BARE",
            name="Economy Bare",
            base_fare_cents=12000,
            bundle_price_cents=12000,
        )
    )
    # A bags-only reseller: it may merchandise baggage and nothing else.
    channel = scenario.create_channel(
        channel_code="OTA_BAGONLY",
        channel_type="OTA",
        commission_bp=900,
        markup_bp=500,
        supported_categories=["BAGGAGE"],
    )
    flight = scenario.create_flight(
        flight_no="AC559",
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
        record_locator="CATG01",
        passenger_name="Ada Lovelace",
    )
    partner = make_channel_partner_headers(channel["id"])

    validate_error(
        api.create_offer_session(
            booking["id"],
            factories.offer_session_payload("BOOKING", [seat["id"]]),
            partner,
        ),
        ApiErrorId.CHANNEL_CATEGORY_UNSUPPORTED,
    )
    _, offers_meta = validate_paginated(
        api.list_ancillary_offers(partner, {"booking_id": booking["id"]})
    )
    assert offers_meta["total_count"] == 0, (
        f"a refused session leaves no offers behind at all: {offers_meta}"
    )

    session = validate_success(
        api.create_offer_session(
            booking["id"],
            factories.offer_session_payload("BOOKING", [bag["id"]]),
            partner,
        ),
        201,
    )
    assert session["candidate_count"] == 1, (
        f"only the bag was requested, so only the bag was considered: {session}"
    )
    assert len(session["presented_offer_ids"]) == 1, (
        f"the one candidate priced within the cap and was presented: {session}"
    )

    offer = validate_success(
        api.get_ancillary_offer(session["presented_offer_ids"][0], partner)
    )
    assert offer["ancillary_product_id"] == bag["id"], (
        f"the presented offer is the baggage one: {offer}"
    )
    assert offer["offered_price_cents"] == 3675, (
        "3500 at a neutral willingness-to-pay and a neutral touchpoint, then the "
        f"reseller's 500 bp markup: {offer['offered_price_cents']}"
    )
    assert offer["expected_value_cents"] == 3675, (
        f"a neutral 10000 bp willingness-to-pay leaves the offered price alone: {offer['expected_value_cents']}"
    )

    quiet = scenario.get_booking(booking["id"], channel["id"])
    assert quiet["ancillary_gross_cents"] == 0, (
        f"presenting an offer sells nothing: {quiet['ancillary_gross_cents']}"
    )


def test_a_seat_segment_must_sit_over_a_seat_category_product(api, scenario):
    """PRD §2.7: "the product a seat segment references has `category` equal to `SEAT`.
    This guards seat-segment creation only."
    PRD §3.3: "The segment's `total_seats` is therefore `row_end` minus `row_start`
    plus one, multiplied by the number of entries in `seat_letters`."

    Design: Corner/errors/a_seat_segment_over_a_non_seat_product_returns_seat_product_category_invalid
    """
    bag = scenario.create_product(factories.ancillary_product_payload(**CHECKED_BAG))
    seat = scenario.create_product(factories.ancillary_product_payload(**STANDARD_SEAT))
    flight = scenario.create_flight(
        flight_no="AC560",
        origin="SFO",
        destination="JFK",
        scheduled_departure_utc="2026-09-01T15:00:00Z",
        cabin_seat_total=120,
    )

    # Row 20 A/B/C, mid cabin: a perfectly ordinary block of seats hung on a bag.
    validate_error(
        api.create_seat_segment(
            factories.seat_segment_payload(
                flight["id"],
                bag["id"],
                zone="MID",
                row_start=20,
                row_end=20,
                seat_letters=["A", "B", "C"],
                base_price_cents=2000,
            ),
            OPERATIONS_CONTROLLER,
        ),
        ApiErrorId.SEAT_PRODUCT_CATEGORY_INVALID,
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
    assert_segment_counts(
        segment, total_seats=3, held_seats=0, sold_seats=0, available_seats=3
    )
    assert segment["effective_price_cents"] == 2000, (
        "a mid-cabin row past row 15 at low demand leaves the base price alone: "
        f"{segment['effective_price_cents']}"
    )

    segments, segments_meta = validate_paginated(
        api.list_seat_segments(OPERATIONS_CONTROLLER, {"flight_id": flight["id"]})
    )
    assert segments_meta["total_count"] == 1, (
        f"the refused segment was never stored: {segments_meta}"
    )
    assert segments[0]["id"] == segment["id"], (
        f"the only segment on the flight is the seat one: {segments[0]}"
    )

    _, bag_meta = validate_paginated(
        api.list_product_family_attributes(bag["id"], MERCHANDISING_ANALYST)
    )
    assert bag_meta["total_count"] == 0, (
        f"the bag was never merchandised into a family either: {bag_meta}"
    )


def test_retiring_a_family_with_a_held_booking_is_refused(api, scenario):
    """PRD §2.7: "no booking on the family has a `booking_status` of `HELD`,
    `TICKETED` or `CHANGE_PENDING` when the family is retired. This guards
    status-change only."
    PRD §3.2: "`PUBLISHED` → `RETIRED` and `SUSPENDED` → `RETIRED` both require that
    no booking on the family has a `booking_status` of `HELD`, `TICKETED` or
    `CHANGE_PENDING`, or the retirement is refused with
    `ERR_FAMILY_HAS_LIVE_BOOKINGS`; both then move every publication of the family
    whose `parity_state` is `PENDING`, `IN_PARITY` or `OUT_OF_PARITY` to `WITHDRAWN`
    and recompute `publication_count`, which consequently falls to 0."

    Design: Corner/errors/retiring_a_family_with_a_held_booking_returns_family_has_live_bookings
    """
    product = scenario.create_product(factories.ancillary_product_payload(**CHECKED_BAG))
    family = scenario.create_family(
        factories.fare_family_payload(
            code="ECO_RETIRE",
            name="Economy Retiring",
            base_fare_cents=12000,
            bundle_price_cents=14000,
        )
    )
    scenario.add_attribute(
        family["id"], product["id"], inclusion="INCLUDED", included_quantity=1
    )
    approved = scenario.publish_family(family["id"])
    channel = scenario.create_channel(channel_code="DIRECT_WEB", channel_type="DIRECT")
    publication = scenario.publish_to_channel(
        family["id"], channel["id"], approved["version"]
    )
    flight = scenario.create_flight(
        flight_no="AC561",
        origin="SFO",
        destination="JFK",
        scheduled_departure_utc="2026-09-01T15:00:00Z",
        cabin_seat_total=120,
    )
    booking = scenario.create_booking(
        flight["id"],
        family["id"],
        channel["id"],
        record_locator="LIVE01",
        passenger_name="Ada Lovelace",
    )

    validate_error(
        api.change_fare_family_status(
            family["id"],
            factories.status_change_payload("RETIRED", "Season ended"),
            PRICING_APPROVER,
        ),
        ApiErrorId.FAMILY_HAS_LIVE_BOOKINGS,
    )
    guarded = scenario.get_family(family["id"])
    assert guarded["status"] == "PUBLISHED", (
        f"a refused retirement leaves the family selling: {guarded['status']}"
    )
    assert guarded["publication_count"] == 1, (
        f"and leaves its shelf space intact: {guarded['publication_count']}"
    )
    assert scenario.get_publication(publication["id"])["parity_state"] == "IN_PARITY", (
        "a refused retirement withdraws nothing"
    )

    # Once the last live booking is gone the retirement goes through and takes the
    # channel publication with it.
    scenario.cancel(booking["id"], channel["id"], "Passenger request")
    retired = scenario.change_family_status(family["id"], "RETIRED", "Season ended")
    assert retired["status"] == "RETIRED", (
        f"with no live bookings the family retires: {retired['status']}"
    )
    assert retired["publication_count"] == 0, (
        f"retirement withdraws every publication, so the count falls to 0: {retired['publication_count']}"
    )
    assert retired["unbundled_value_cents"] == 3500, (
        "retirement is not a repricing: the bundled bag is still worth its list price "
        f"but reads {retired['unbundled_value_cents']}"
    )
    assert scenario.get_publication(publication["id"])["parity_state"] == "WITHDRAWN", (
        "the publication row survives as history in the withdrawn state"
    )
