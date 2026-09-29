"""Resource shapes: declared fields, server-minted identity, defaults and parentage.

Every test here builds the catalog, the ladder and the operational world it needs
from scratch - the harness resets the database before each one - and asserts the
exact integers and strings the requirements document derives, never whatever the
service happens to answer.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    DISTRIBUTION_MANAGER,
    MERCHANDISING_ANALYST,
    OPERATIONS_CONTROLLER,
    PRICING_APPROVER,
    REVENUE_ACCOUNTANT,
    ApiErrorId,
    assert_envelope,
    assert_immutable_common_fields,
    assert_money_field,
    assert_pagination_meta,
    factories,
    make_channel_partner_headers,
)


# ---------------------------------------------------------------------------
# The merchandising catalog
# ---------------------------------------------------------------------------
def test_create_catalog_product_answers_201_with_every_declared_field(api):
    """PRD 3.1: "A product also declares `list_price_cents`, the a-la-carte list
    price in cents and never negative, which is the base of every dynamic-price
    computation the system performs; a `tax_treatment` of `TAXABLE_TRANSPORT`,
    `TAXABLE_SERVICE` or `EXEMPT`; a `revenue_class` of either
    `AIR_TRANSPORT_RELATED` or `NON_AIR`; and a `revenue_account_code`, the
    general-ledger account code that is stamped onto every revenue entry the
    product ever generates."
    PRD 2.4: "Every stored resource carries a server-minted `id` formatted as a
    UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601
    UTC instant with three fractional digits."
    PRD 2.4: "**`version`** - an integer that increments by exactly 1 on every
    mutation of the resource. It starts at 1 when the resource is created."

    Design: Corner/entities/create_ancillary_product_returns_201_with_every_declared_field
    """
    payload = factories.checked_bag_product_payload()

    response = api.create_ancillary_product(payload, MERCHANDISING_ANALYST)
    product = validate_success(response, 201)

    body = response.json()
    assert_envelope(body)
    assert body["response_type"] == "object", (
        f"a single created resource is an object envelope, not {body['response_type']!r}"
    )

    assert product["sku"] == "BAG_CHECKED_1", f"sku should round-trip: {product}"
    assert product["name"] == "First checked bag"
    assert product["category"] == "BAGGAGE", "category is one of the five merchandising buckets"
    assert_money_field(product, "list_price_cents", 3500)
    assert product["tax_treatment"] == "TAXABLE_SERVICE"
    assert product["revenue_class"] == "NON_AIR"
    assert product["revenue_account_code"] == "4100"
    assert product["refundable"] is False
    assert product["disclosable_fee"] is True
    assert product["product_state"] == "ACTIVE"

    assert is_valid_uuid(product["id"]), f"id must be a server-minted UUID: {product['id']!r}"
    assert product["version"] == 1, f"a freshly created product starts at version 1: {product['version']}"
    assert is_iso8601_timestamp(product["created_at"]), product["created_at"]
    assert is_iso8601_timestamp(product["updated_at"]), product["updated_at"]


def test_create_catalog_product_omitting_optional_flags_applies_declared_defaults(api):
    """PRD 3.1: "`refundable` defaults to **false**, and when it is false a booking
    cancellation does *not* reverse that product's sale entries - the passenger has
    bought something non-refundable and the airline keeps the money."
    PRD 3.1: "`disclosable_fee` defaults to **true**, and when it is true a
    chargeable fee for the product must appear in the point-of-sale fee disclosure;
    a family that exposes an active chargeable attribute pointing at a product whose
    `disclosable_fee` is false cannot have a disclosure issued at all, and the
    attempt is refused with `ERR_UNDISCLOSED_FEE_CATEGORY`."
    PRD 3.1: "`product_state` defaults to `ACTIVE` and may also be `WITHDRAWN`; a
    `WITHDRAWN` product is excluded from offer eligibility but remains referenced by
    history, so past sales and past family attributes continue to resolve against
    it."

    Design: Corner/entities/create_ancillary_product_omitting_optional_flags_applies_declared_defaults
    """
    # Only the seven declared inputs; the three flags are left to the server.
    payload = {
        "sku": "PRIORITY_BOARDING",
        "name": "Priority boarding",
        "category": "BOARDING",
        "list_price_cents": 1250,
        "tax_treatment": "TAXABLE_SERVICE",
        "revenue_class": "NON_AIR",
        "revenue_account_code": "4400",
    }

    product = validate_success(api.create_ancillary_product(payload, MERCHANDISING_ANALYST), 201)

    assert product["refundable"] is False, (
        f"refundable defaults to false, not {product['refundable']!r}"
    )
    assert product["disclosable_fee"] is True, (
        f"disclosable_fee defaults to true, not {product['disclosable_fee']!r}"
    )
    assert product["product_state"] == "ACTIVE", (
        f"product_state defaults to ACTIVE, not {product['product_state']!r}"
    )


def test_list_catalog_products_pages_with_total_count_and_has_more(api, scenario):
    """PRD 2.3: "`limit` caps the number of items returned; it defaults to 10 when
    omitted, may not be smaller than 1, and may not be larger than 100. `offset` is
    the number of items to skip; it defaults to 0 and may not be negative."
    PRD 2.3: "`total_count` counts the rows that match the request's filters
    *before* the `limit`/`offset` window is applied; `has_more` is true when rows
    remain beyond the returned window."

    Design: Corner/entities/list_ancillary_products_paginated_with_total_count_and_has_more
    """
    scenario.create_product(factories.checked_bag_product_payload())
    scenario.create_product(factories.standard_seat_product_payload())
    scenario.create_product(factories.wifi_product_payload())

    first_response = api.list_ancillary_products(REVENUE_ACCOUNTANT, {"limit": 2, "offset": 0})
    first_page, first_meta = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array", "a list read is an array envelope"
    assert len(first_page) == 2, f"limit 2 caps the window at two rows, got {len(first_page)}"
    assert_pagination_meta(first_meta, limit=2, offset=0, total_count=3, has_more=True)

    second_response = api.list_ancillary_products(REVENUE_ACCOUNTANT, {"limit": 2, "offset": 2})
    second_page, second_meta = validate_paginated(second_response)
    assert second_response.json()["response_type"] == "array", "a list read is an array envelope"
    assert len(second_page) == 1, f"one row remains beyond offset 2, got {len(second_page)}"
    assert_pagination_meta(second_meta, limit=2, offset=2, total_count=3, has_more=False)

    first_ids = {row["id"] for row in first_page}
    second_ids = {row["id"] for row in second_page}
    assert not (first_ids & second_ids), (
        f"the two windows must be disjoint but share {first_ids & second_ids}"
    )


# ---------------------------------------------------------------------------
# Fare families and their bundled attributes
# ---------------------------------------------------------------------------
def test_read_fare_family_returns_the_stored_valuation_triple(api, scenario):
    """PRD 3.1: "The family's `unbundled_value_cents` is the sum of those
    per-attribute values. Its `a_la_carte_total_cents` is `base_fare_cents` plus
    `unbundled_value_cents`."
    PRD 3.1: "Its `bundle_discount_bp` - the basis points a passenger saves by
    buying the bundle instead of every component separately - is 0 when
    `unbundled_value_cents` is 0; otherwise it is `a_la_carte_total_cents` minus
    `bundle_price_cents`, multiplied by 10,000, divided by `a_la_carte_total_cents`,
    and rounded half up."
    PRD 3.1: "Its `included_attribute_count` is the number of `ACTIVE` attributes
    whose `inclusion` is `INCLUDED`."
    PRD 2.8: "Then form the fingerprint by writing the family's `code`, a vertical
    bar, the family's `revision_no` as a decimal integer, a second vertical bar, and
    finally the parts joined together with a semicolon between consecutive parts."

    Design: Corner/entities/retrieve_fare_family_returns_stored_valuation_fields
    """
    bag = scenario.create_product(factories.checked_bag_product_payload())
    family = scenario.create_family(factories.eco_lite_family_payload())
    scenario.add_attribute(
        family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1, waiver_eligible=True
    )

    # An ECONOMY family carries no cabin uplift, so the attribute values itself at list.
    stored = validate_success(api.get_fare_family(family["id"], PRICING_APPROVER))

    assert_money_field(stored, "unbundled_value_cents", 3500)
    assert_money_field(stored, "a_la_carte_total_cents", 15500)
    assert stored["bundle_discount_bp"] == 968, (
        "(15500 - 14000) * 10000 / 15500 rounds half up to 968 basis points, "
        f"but the family reports {stored['bundle_discount_bp']}"
    )
    assert stored["included_attribute_count"] == 1, (
        f"one ACTIVE INCLUDED attribute means a count of 1, not {stored['included_attribute_count']}"
    )
    assert stored["fee_fingerprint"] == "ECO_LITE|1|BAG_CHECKED_1:INCLUDED:1:3500", (
        f"fee_fingerprint should be ECO_LITE|1|BAG_CHECKED_1:INCLUDED:1:3500 "
        f"but is {stored['fee_fingerprint']!r}"
    )
    assert stored["status"] == "DRAFT", "a newly designed family stays in draft"
    assert stored["revision_no"] == 1, "the first revision of a family is 1"


def test_attribute_override_price_drives_effective_unit_and_extended_value(api, scenario):
    """PRD 3.1: "and two computed money fields: `effective_unit_cents`, which is
    `override_price_cents` when that is not null and otherwise the referenced
    product's `list_price_cents`; and `attr_value_cents`, the attribute's extended
    contribution to the bundle."
    PRD 3.1: "For each attribute in turn, take its effective unit price, multiply it
    by the attribute's `included_quantity`, multiply that by 10,000 plus the cabin
    uplift in basis points for the family's `cabin_class`, divide by 10,000, and
    round the result half up: that single integer is the attribute's
    `attr_value_cents`."
    PRD 3.1: "The cabin uplift is nothing at all for `ECONOMY`, 1,500 basis points -
    a fifteen percent premium - for `PREMIUM`, and 3,000 basis points - a thirty
    percent premium - for `BUSINESS`."

    Design: Corner/entities/family_attribute_computed_effective_unit_and_attr_value_from_override
    """
    legroom = scenario.create_product(factories.extra_legroom_seat_product_payload())
    family = scenario.create_family(
        factories.fare_family_payload(
            code="BIZ_FLEX",
            name="Business Flex",
            cabin_class="BUSINESS",
            base_fare_cents=60000,
            bundle_price_cents=68000,
            refundability="FULLY_REFUNDABLE",
            change_fee_cents=0,
            boarding_priority_tier=1,
        )
    )

    attribute = scenario.add_attribute(
        family["id"],
        legroom["id"],
        inclusion="INCLUDED",
        included_quantity=2,
        override_price_cents=4000,
        waiver_eligible=False,
    )

    # The override replaces the 4200 list price for valuation, and the 3,000 bp
    # business uplift is applied once to the extended 8000 cent value.
    assert_money_field(attribute, "effective_unit_cents", 4000)
    assert_money_field(attribute, "attr_value_cents", 10400)

    valued = validate_success(api.get_fare_family(family["id"], MERCHANDISING_ANALYST))
    assert_money_field(valued, "unbundled_value_cents", 10400)
    assert_money_field(valued, "a_la_carte_total_cents", 70400)
    assert valued["bundle_discount_bp"] == 341, (
        "(70400 - 68000) * 10000 / 70400 rounds half up to 341 basis points, "
        f"but the family reports {valued['bundle_discount_bp']}"
    )
    assert valued["fee_fingerprint"] == "BIZ_FLEX|1|SEAT_EXTRA_LEGROOM:INCLUDED:2:4000", (
        "the fingerprint quotes the override, not the list price, as the effective unit: "
        f"{valued['fee_fingerprint']!r}"
    )


def test_attach_attribute_under_unknown_family_answers_fare_family_not_found(api, scenario):
    """PRD 2.7: "**404 by path** - every id templated into the URL resolves to a
    stored row, validated **left to right**, so the leftmost unresolvable identifier
    decides the error. The mapping is fixed: a flight id yields
    `ERR_FLIGHT_NOT_FOUND`, a fare-family id yields `ERR_FARE_FAMILY_NOT_FOUND`, a
    family-attribute id yields `ERR_FAMILY_ATTRIBUTE_NOT_FOUND`, an
    ancillary-product id yields `ERR_ANCILLARY_PRODUCT_NOT_FOUND`, a seat-segment id
    yields `ERR_SEAT_SEGMENT_NOT_FOUND`, a distribution-channel id yields
    `ERR_DISTRIBUTION_CHANNEL_NOT_FOUND`, a channel-publication id yields
    `ERR_CHANNEL_PUBLICATION_NOT_FOUND`, a booking id yields
    `ERR_BOOKING_NOT_FOUND`, an ancillary-offer id yields
    `ERR_ANCILLARY_OFFER_NOT_FOUND`, a seat-assignment id yields
    `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, and an irops-waiver id yields
    `ERR_IROPS_WAIVER_NOT_FOUND`."
    PRD 2.7: "Checks are evaluated in a fixed order and the **first** failure
    determines the response. The ladder below is exhaustive and its numbering is the
    precedence: a lower number is evaluated earlier and wins."

    Design: Corner/entities/create_attribute_under_unknown_family_returns_not_found
    """
    bag = scenario.create_product(factories.checked_bag_product_payload())

    # The path id resolves to nothing, which is checked before the INCLUDED /
    # quantity-zero pairing rule further down the ladder.
    response = api.add_family_attribute(
        NON_EXISTENT_UUID,
        factories.family_attribute_payload(bag["id"], inclusion="INCLUDED", included_quantity=0),
        MERCHANDISING_ANALYST,
    )
    validate_error(response, ApiErrorId.FARE_FAMILY_NOT_FOUND)

    _, meta = validate_paginated(api.list_family_attributes(MERCHANDISING_ANALYST))
    assert meta["total_count"] == 0, (
        f"a refused attachment stores no attribute, but the register holds {meta['total_count']}"
    )


def test_reparenting_a_draft_family_onto_its_own_child_is_refused_as_a_cycle(api, scenario):
    """PRD 3.2: "The one hard constraint is acyclicity: following
    `upsell_parent_family_id` upward from the family being repositioned must never
    revisit a family already seen on the path, and a request that would close a loop
    is refused with `ERR_UPSELL_CYCLE_DETECTED`."
    PRD 3.1: "An `upsell_parent_family_id` may optionally name the family this one
    upsells from; it defaults to null for the entry-level rung of a ladder."

    Design: Corner/entities/reparenting_draft_family_onto_its_own_child_returns_upsell_cycle_detected
    """
    base = scenario.create_family(
        factories.fare_family_payload(
            code="ECO_BASE",
            name="Economy Base",
            cabin_class="ECONOMY",
            base_fare_cents=12000,
            bundle_price_cents=13000,
            refundability="NON_REFUNDABLE",
            change_fee_cents=7500,
            boarding_priority_tier=4,
        )
    )
    upper = scenario.create_family(
        factories.fare_family_payload(
            code="ECO_UP",
            name="Economy Up",
            cabin_class="ECONOMY",
            base_fare_cents=12000,
            bundle_price_cents=15000,
            refundability="REFUNDABLE_WITH_FEE",
            change_fee_cents=5000,
            boarding_priority_tier=3,
            upsell_parent_family_id=base["id"],
        )
    )
    assert upper["upsell_parent_family_id"] == base["id"], (
        "the upper rung must be created as a child of the entry-level rung"
    )

    # Hanging the entry-level rung beneath its own child would close a two-node loop.
    response = api.update_fare_family(
        base["id"], {"upsell_parent_family_id": upper["id"]}, MERCHANDISING_ANALYST
    )
    validate_error(response, ApiErrorId.UPSELL_CYCLE_DETECTED)

    unchanged = validate_success(api.get_fare_family(base["id"], MERCHANDISING_ANALYST))
    assert unchanged["upsell_parent_family_id"] is None, (
        "the refused reposition must leave the entry-level rung parentless, "
        f"but it now points at {unchanged['upsell_parent_family_id']!r}"
    )
    assert unchanged["version"] == 1, (
        f"a refused reposition mutates nothing, so version stays 1, not {unchanged['version']}"
    )

    children, children_meta = validate_paginated(
        api.list_fare_families(MERCHANDISING_ANALYST, {"upsell_parent_family_id": base["id"]})
    )
    assert children_meta["total_count"] == 1, (
        f"the ladder still has exactly one child of ECO_BASE, not {children_meta['total_count']}"
    )
    assert children[0]["id"] == upper["id"], "the surviving child of ECO_BASE is ECO_UP"


# ---------------------------------------------------------------------------
# Flights and the seat map
# ---------------------------------------------------------------------------
def test_create_flight_with_destination_equal_to_origin_is_refused(api):
    """PRD 3.3: "An `OperationsController` opens the operational side of the system
    by creating a flight with a marketing `flight_no`, an `origin` and a
    `destination` each given as exactly three uppercase letters and required to
    differ from one another, a `scheduled_departure_utc` instant in ISO 8601 UTC, and
    a strictly positive `cabin_seat_total` giving the physical seat count of the
    cabin."
    PRD 2.7: "**`ERR_INVALID_REQUEST`** (400) - the body carries every required field
    of the operation's input, carries no unknown fields, and every value matches its
    declared type, enum member set and numeric range. This covers the
    `record_locator` format, the airport-code format for `origin` and `destination`,
    the character sets of `sku` and `code`, membership of `seat_letters` and
    `seat_letter` in the letters A through F, a non-empty `waiver_scope`,
    `delay_minutes` within 0 to 1440, `booked_load_factor_pct` within 0 to 100,
    `demand_index_bp` within -5000 to 5000, `boarding_priority_tier` within 1 to 4,
    `included_quantity` within 0 to 9, `limit` within 1 to 100 and a non-negative
    `offset`."

    Design: Corner/entities/create_flight_with_destination_equal_to_origin_returns_invalid_request
    """
    # Both codes are individually well formed; it is their equality that is refused.
    payload = factories.flight_payload(
        flight_no="AC502",
        origin="SFO",
        destination="SFO",
        scheduled_departure_utc="2026-09-01T15:00:00Z",
        cabin_seat_total=120,
    )

    validate_error(api.create_flight(payload, OPERATIONS_CONTROLLER), ApiErrorId.INVALID_REQUEST)

    _, meta = validate_paginated(api.list_flights(OPERATIONS_CONTROLLER))
    assert meta["total_count"] == 0, (
        f"a refused flight is never stored, but the schedule holds {meta['total_count']} flights"
    )


def test_read_seat_segment_with_unknown_id_answers_seat_segment_not_found(api):
    """PRD 2.7: "**404 by path** - every id templated into the URL resolves to a
    stored row, validated **left to right**, so the leftmost unresolvable identifier
    decides the error. The mapping is fixed: a flight id yields
    `ERR_FLIGHT_NOT_FOUND`, a fare-family id yields `ERR_FARE_FAMILY_NOT_FOUND`, a
    family-attribute id yields `ERR_FAMILY_ATTRIBUTE_NOT_FOUND`, an
    ancillary-product id yields `ERR_ANCILLARY_PRODUCT_NOT_FOUND`, a seat-segment id
    yields `ERR_SEAT_SEGMENT_NOT_FOUND`, a distribution-channel id yields
    `ERR_DISTRIBUTION_CHANNEL_NOT_FOUND`, a channel-publication id yields
    `ERR_CHANNEL_PUBLICATION_NOT_FOUND`, a booking id yields
    `ERR_BOOKING_NOT_FOUND`, an ancillary-offer id yields
    `ERR_ANCILLARY_OFFER_NOT_FOUND`, a seat-assignment id yields
    `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, and an irops-waiver id yields
    `ERR_IROPS_WAIVER_NOT_FOUND`."
    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/entities/get_seat_segment_with_unknown_id_returns_seat_segment_not_found
    """
    response = api.get_seat_segment(NON_EXISTENT_UUID, OPERATIONS_CONTROLLER)
    error = validate_error(response, ApiErrorId.SEAT_SEGMENT_NOT_FOUND)

    body = response.json()
    assert body["response_type"] == "error", (
        f"a failure answers with the error envelope, not {body['response_type']!r}"
    )
    assert isinstance(error.get("message"), str) and error["message"], (
        f"the error carries a human-readable message: {error!r}"
    )


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------
def _selling_world(scenario, flight_no):
    """A channel, a fare family and a presale flight - the three references a booking needs."""
    channel = scenario.create_channel(factories.direct_web_channel_payload())
    family = scenario.create_family(factories.eco_lite_family_payload())
    flight = scenario.create_flight(
        flight_no=flight_no,
        origin="SFO",
        destination="JFK",
        scheduled_departure_utc="2026-09-01T15:00:00Z",
        cabin_seat_total=120,
    )
    return channel, family, flight


def test_create_booking_without_passenger_name_is_refused_and_stores_nothing(api, scenario):
    """PRD 3.5: "A `ChannelPartner` opens a sale by creating a booking with a
    `record_locator` of exactly six characters drawn from uppercase A-Z and the
    digits, a `flight_id`, a `fare_family_id`, a `distribution_channel_id` and a
    `passenger_name`."
    PRD 2.7: "**`ERR_INVALID_REQUEST`** (400) - the body carries every required field
    of the operation's input, carries no unknown fields, and every value matches its
    declared type, enum member set and numeric range."

    Design: Corner/entities/create_booking_missing_required_passenger_name_returns_invalid_request
    """
    channel, family, flight = _selling_world(scenario, "AC500")
    partner = make_channel_partner_headers(channel["id"])

    payload = factories.booking_payload(
        flight["id"], family["id"], channel["id"], record_locator="REQ001"
    )
    del payload["passenger_name"]

    validate_error(api.create_booking(payload, partner), ApiErrorId.INVALID_REQUEST)

    _, meta = validate_paginated(api.list_bookings(partner))
    assert meta["total_count"] == 0, (
        f"a refused booking is never stored, but the channel shows {meta['total_count']}"
    )


def test_booking_system_fields_are_server_stamped_and_a_seeded_status_is_refused(api, scenario):
    """PRD 3.5: "A new booking starts with `booking_status` `HELD`,
    `disclosure_state` `NOT_ISSUED`, `fare_component_cents` and
    `pending_change_fee_cents` both null, `change_count` at 0,
    `change_fee_waived_cents` at 0, `waiver_applied` false, and every derived money
    field - `ancillary_gross_cents`, `recognized_ancillary_net_cents`,
    `commission_cents`, `incentive_credit_cents` and
    `channel_settlement_total_cents` - at 0."
    PRD 2.9: "Issuance snapshots four fields onto the booking:
    `disclosed_fee_fingerprint`, `disclosed_total_fee_cents`,
    `disclosed_unbundled_list_cents` and `disclosure_issued_at`. Acknowledgement
    stamps `disclosure_acked_at`. All five are null while `disclosure_state` is
    `NOT_ISSUED`."
    PRD 2.7: "**`ERR_INVALID_REQUEST`** (400) - the body carries every required field
    of the operation's input, carries no unknown fields, and every value matches its
    declared type, enum member set and numeric range."

    Design: Corner/entities/booking_system_fields_generated_and_client_supplied_status_rejected
    """
    channel, family, flight = _selling_world(scenario, "AC501")
    partner = make_channel_partner_headers(channel["id"])

    accepted = scenario.create_booking(
        flight["id"],
        family["id"],
        channel["id"],
        record_locator="SYS001",
        passenger_name="Ada Lovelace",
    )

    # The sales dimension is the server's to stamp; naming it in the body is unknown input.
    seeded = factories.booking_payload(
        flight["id"],
        family["id"],
        channel["id"],
        record_locator="SYS002",
        passenger_name="Grace Hopper",
        booking_status="TICKETED",
    )
    validate_error(api.create_booking(seeded, partner), ApiErrorId.INVALID_REQUEST)

    stored = validate_success(api.get_booking(accepted["id"], partner))
    assert stored["booking_status"] == "HELD", (
        f"a new booking is held, not {stored['booking_status']!r}"
    )
    assert stored["disclosure_state"] == "NOT_ISSUED", (
        f"the regulatory dimension starts unissued, not {stored['disclosure_state']!r}"
    )
    assert stored["version"] == 1, f"a new booking is at version 1, not {stored['version']}"
    assert stored["fare_component_cents"] is None, (
        f"nothing is pinned before ticketing: {stored['fare_component_cents']!r}"
    )
    assert stored["disclosed_fee_fingerprint"] is None, (
        f"no disclosure has been issued: {stored['disclosed_fee_fingerprint']!r}"
    )
    assert_money_field(stored, "ancillary_gross_cents", 0)

    _, meta = validate_paginated(api.list_bookings(partner))
    assert meta["total_count"] == 1, (
        f"only the accepted booking exists, but the channel shows {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# Distribution junction and the append-only ledger
# ---------------------------------------------------------------------------
def test_one_family_publishes_to_two_channels_as_two_independent_rows(api, scenario):
    """PRD 3.4: "The new publication's initial `parity_state` depends on the family:
    if the family's `status` is already `PUBLISHED`, the publication is promoted to
    `IN_PARITY` within the same request; otherwise it waits in `PENDING` until the
    family is approved. Either way, `published_fee_fingerprint` and
    `published_family_version` are pinned from the family, the family's
    `publication_count` is recomputed, and the family's `version` increments."
    PRD 3.2: "The family's `publication_count` is recomputed, counting the
    publications of this family whose `parity_state` is `PENDING`, `IN_PARITY` or
    `OUT_OF_PARITY`."

    Design: Corner/entities/publication_junction_links_one_family_to_two_channels_independently
    """
    bag = scenario.create_product(factories.checked_bag_product_payload())
    family = scenario.create_family(factories.eco_lite_family_payload())
    scenario.add_attribute(family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1)

    direct = scenario.create_channel(factories.direct_web_channel_payload())
    ota = scenario.create_channel(
        factories.distribution_channel_payload(
            channel_code="OTA_SKYDEAL",
            channel_type="OTA",
            commission_bp=900,
            markup_bp=500,
            max_ancillary_price_cents=6000,
        )
    )

    expected_fingerprint = "ECO_LITE|1|BAG_CHECKED_1:INCLUDED:1:3500"

    # Each publication is guarded by the family version as the publisher last saw it.
    first_version = scenario.get_family(family["id"])["version"]
    first_publication = scenario.publish_to_channel(family["id"], direct["id"], first_version)

    second_version = scenario.get_family(family["id"])["version"]
    response = api.create_channel_publication(
        factories.channel_publication_payload(family["id"], ota["id"], second_version),
        DISTRIBUTION_MANAGER,
    )
    second_publication = validate_success(response, 201)

    assert second_publication["parity_state"] == "PENDING", (
        "the family is still in draft, so its content waits in PENDING, "
        f"not {second_publication['parity_state']!r}"
    )
    assert second_publication["distribution_channel_id"] == ota["id"]
    assert second_publication["fare_family_id"] == family["id"]

    _, by_family = validate_paginated(
        api.list_channel_publications(DISTRIBUTION_MANAGER, {"fare_family_id": family["id"]})
    )
    assert by_family["total_count"] == 2, (
        f"the family now has two publications, not {by_family['total_count']}"
    )

    _, by_channel = validate_paginated(
        api.list_channel_publications(
            DISTRIBUTION_MANAGER, {"distribution_channel_id": ota["id"]}
        )
    )
    assert by_channel["total_count"] == 1, (
        f"the agency channel carries one of them, not {by_channel['total_count']}"
    )

    counted = scenario.get_family(family["id"])
    assert counted["publication_count"] == 2, (
        f"publication_count counts both PENDING rows, not {counted['publication_count']}"
    )

    for publication in (scenario.get_publication(first_publication["id"]), second_publication):
        assert publication["published_fee_fingerprint"] == expected_fingerprint, (
            "both channels pin the same live family content: "
            f"{publication['published_fee_fingerprint']!r}"
        )


def test_a_posted_revenue_entry_carries_no_version_and_no_updated_at(api, scenario):
    """PRD 2.4: "`RevenueEntry` is the sole exception. Revenue entries are immutable
    accounting events: they carry only `id` and `created_at`. Both `updated_at` and
    `version` are **absent** from a revenue entry. Corrections to the ledger are made
    by posting compensating entries, never by editing an existing one."
    PRD 3.6: "On success, `accepted_price_cents` is frozen from
    `offered_price_cents`; one `SALE` revenue entry is posted whose `category` is the
    product's `category`, whose `gross_cents` is the accepted price, whose tax and
    reporting metadata are snapshotted from the product, and whose `source_ref` is
    `offer:` followed by the offer's id"
    PRD 2.11: "`tax_cents` is the absolute value of `gross_cents` multiplied by that
    rate and divided by 10,000, rounded half up, and then given the same sign as
    `gross_cents`. `net_cents` is `gross_cents` minus `tax_cents`."

    Design: Corner/entities/revenue_entry_is_immutable_with_no_version_field_and_no_write_endpoint
    """
    bag = scenario.create_product(factories.checked_bag_product_payload())
    family = scenario.create_family(factories.eco_lite_family_payload())
    channel = scenario.create_channel(factories.direct_web_channel_payload())
    flight = scenario.create_flight(
        flight_no="AC503",
        origin="SFO",
        destination="JFK",
        scheduled_departure_utc="2026-09-01T15:00:00Z",
        cabin_seat_total=120,
    )
    scenario.post_demand(flight["id"], 50, 0)

    booking = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="IMMUT1"
    )
    partner = make_channel_partner_headers(channel["id"])

    # A neutral demand feed and a zero-markup channel price the bag at its 3500 list.
    get_success_data(
        api.create_offer_session(
            booking["id"], factories.offer_session_payload("BOOKING", [bag["id"]]), partner
        )
    )
    offers, _ = validate_paginated(
        api.list_ancillary_offers(
            DISTRIBUTION_MANAGER, {"booking_id": booking["id"], "offer_status": "PRESENTED"}
        )
    )
    assert len(offers) == 1, f"the session should present the one requested bag offer: {offers}"
    offer = offers[0]

    held = scenario.get_booking(booking["id"], channel["id"])
    scenario.accept_offer(offer["id"], channel["id"], held["version"])

    trail, meta = validate_paginated(
        api.list_booking_revenue_entries(booking["id"], REVENUE_ACCOUNTANT)
    )
    assert meta["total_count"] == 1, (
        f"one accepted offer posts exactly one ledger row, not {meta['total_count']}"
    )
    entry = trail[0]

    assert entry["entry_type"] == "SALE", f"an accepted offer is a sale: {entry['entry_type']!r}"
    assert entry["category"] == "BAGGAGE", f"the category is the product's: {entry['category']!r}"
    assert_money_field(entry, "gross_cents", 3500)
    assert_money_field(entry, "tax_cents", 140)
    assert_money_field(entry, "net_cents", 3360)
    assert entry["source_ref"] == f"offer:{offer['id']}", (
        f"source_ref names the originating offer: {entry['source_ref']!r}"
    )

    assert_immutable_common_fields(entry)

    single = validate_success(api.get_revenue_entry(entry["id"], REVENUE_ACCOUNTANT))
    assert single == entry, (
        "the single-entry read must return the same immutable row as the booking trail: "
        f"{single!r} vs {entry!r}"
    )
