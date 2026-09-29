"""Lifecycle conflicts and the not-found map.

Every check here drives an operation at a resource that is already past the state
the operation demands - a second decline, a second release, a second rescind, a
resync of a publication that never drifted, a phase jump, a write against a
flight that has already gone - and pins the identifier the contract answers with,
together with the proof that the refused call moved nothing.
"""

import uuid

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
    REVENUE_ACCOUNTANT,
    assert_field_values,
    assert_segment_counts,
    factories,
    make_channel_partner_headers,
)


def _advance_phases(api, flight_id, *phases):
    """Walk a flight forward one retailing phase at a time."""
    for phase in phases:
        validate_success(
            api.advance_flight_phase(
                flight_id, {"target_phase": phase}, OPERATIONS_CONTROLLER
            )
        )


def test_unknown_catalog_and_inventory_path_ids_answer_their_own_not_found(api):
    """PRD §2.7: "404 by path — every id templated into the URL resolves to a
    stored row, validated **left to right**, so the leftmost unresolvable
    identifier decides the error."
    PRD §2.7: "The mapping is fixed: a flight id yields `ERR_FLIGHT_NOT_FOUND`, a
    fare-family id yields `ERR_FARE_FAMILY_NOT_FOUND`, a family-attribute id
    yields `ERR_FAMILY_ATTRIBUTE_NOT_FOUND`, an ancillary-product id yields
    `ERR_ANCILLARY_PRODUCT_NOT_FOUND`, a seat-segment id yields
    `ERR_SEAT_SEGMENT_NOT_FOUND`, a distribution-channel id yields
    `ERR_DISTRIBUTION_CHANNEL_NOT_FOUND`, a channel-publication id yields
    `ERR_CHANNEL_PUBLICATION_NOT_FOUND`, a booking id yields
    `ERR_BOOKING_NOT_FOUND`, an ancillary-offer id yields
    `ERR_ANCILLARY_OFFER_NOT_FOUND`, a seat-assignment id yields
    `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, and an irops-waiver id yields
    `ERR_IROPS_WAIVER_NOT_FOUND`."

    Design: Corner/errors/unknown_catalog_and_inventory_path_ids_return_their_own_not_found_error
    """
    # Nothing has been created, so every one of these ids is unresolvable.
    product_error = validate_error(
        api.get_ancillary_product(str(uuid.uuid4()), MERCHANDISING_ANALYST),
        ApiErrorId.ANCILLARY_PRODUCT_NOT_FOUND,
    )
    attribute_error = validate_error(
        api.get_family_attribute(str(uuid.uuid4()), MERCHANDISING_ANALYST),
        ApiErrorId.FAMILY_ATTRIBUTE_NOT_FOUND,
    )
    flight_error = validate_error(
        api.get_flight(str(uuid.uuid4()), OPERATIONS_CONTROLLER),
        ApiErrorId.FLIGHT_NOT_FOUND,
    )
    publication_error = validate_error(
        api.get_channel_publication(str(uuid.uuid4()), DISTRIBUTION_MANAGER),
        ApiErrorId.CHANNEL_PUBLICATION_NOT_FOUND,
    )

    # Four collections, four distinct identifiers - never one generic 404.
    reported = {
        product_error["error_id"],
        attribute_error["error_id"],
        flight_error["error_id"],
        publication_error["error_id"],
    }
    assert len(reported) == 4, f"each collection must own its error id, got {reported}"

    # The failure body carries an explanation, never the row that was missing.
    for error_data in (product_error, attribute_error, flight_error, publication_error):
        assert "id" not in error_data, (
            f"an error body must not carry a resource payload: {error_data}"
        )
        assert error_data["message"].strip(), "every failure carries a message"


def test_unknown_booking_offer_assignment_and_waiver_ids_answer_their_own_not_found(
    api, scenario
):
    """PRD §2.7: "The mapping is fixed: a flight id yields `ERR_FLIGHT_NOT_FOUND`, a
    fare-family id yields `ERR_FARE_FAMILY_NOT_FOUND`, a family-attribute id
    yields `ERR_FAMILY_ATTRIBUTE_NOT_FOUND`, an ancillary-product id yields
    `ERR_ANCILLARY_PRODUCT_NOT_FOUND`, a seat-segment id yields
    `ERR_SEAT_SEGMENT_NOT_FOUND`, a distribution-channel id yields
    `ERR_DISTRIBUTION_CHANNEL_NOT_FOUND`, a channel-publication id yields
    `ERR_CHANNEL_PUBLICATION_NOT_FOUND`, a booking id yields
    `ERR_BOOKING_NOT_FOUND`, an ancillary-offer id yields
    `ERR_ANCILLARY_OFFER_NOT_FOUND`, a seat-assignment id yields
    `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, and an irops-waiver id yields
    `ERR_IROPS_WAIVER_NOT_FOUND`."
    PRD §2.7: "404 by body reference — every foreign key supplied in the request
    body resolves to a stored row, validated in the order the operation declares
    its inputs, using the same per-entity not-found error ids as the previous
    step."

    Design: Corner/errors/unknown_booking_offer_assignment_and_waiver_ids_return_their_own_not_found_error
    """
    channel = scenario.create_channel(factories.direct_web_channel_payload())
    partner = make_channel_partner_headers(channel["id"])
    missing_booking = str(uuid.uuid4())

    booking_error = validate_error(
        api.get_booking(missing_booking, partner), ApiErrorId.BOOKING_NOT_FOUND
    )
    offer_error = validate_error(
        api.get_ancillary_offer(str(uuid.uuid4()), partner),
        ApiErrorId.ANCILLARY_OFFER_NOT_FOUND,
    )
    assignment_error = validate_error(
        api.get_seat_assignment(str(uuid.uuid4()), partner),
        ApiErrorId.SEAT_ASSIGNMENT_NOT_FOUND,
    )
    waiver_error = validate_error(
        api.get_irops_waiver(str(uuid.uuid4()), OPERATIONS_CONTROLLER),
        ApiErrorId.IROPS_WAIVER_NOT_FOUND,
    )
    reported = {
        booking_error["error_id"],
        offer_error["error_id"],
        assignment_error["error_id"],
        waiver_error["error_id"],
    }
    assert len(reported) == 4, f"each collection must own its error id, got {reported}"

    # Both the booking in the path and the segment in the body are unknown; the
    # path id is resolved first, so the booking decides the answer.
    nested_error = validate_error(
        api.create_seat_assignment(
            missing_booking,
            factories.seat_assignment_payload(str(uuid.uuid4()), 12, "A"),
            partner,
        ),
        ApiErrorId.BOOKING_NOT_FOUND,
    )
    assert nested_error["error_id"] != ApiErrorId.SEAT_SEGMENT_NOT_FOUND, (
        "the unknown path id must be reported before the unknown body reference"
    )


def test_declining_an_already_declined_offer_is_refused_as_offer_state_invalid(
    api, scenario, clock_at_nine
):
    """PRD §2.7: "`ERR_OFFER_STATE_INVALID` (409) — the offer's `offer_status` is
    `PRESENTED` when it is accepted or declined. This guards offer acceptance and
    offer decline."
    PRD §3.6: "Every one of these transitions increments the offer's `version`,
    and `ACCEPTED`, `DECLINED`, `EXPIRED` and `SUPERSEDED` are all terminal."

    Design: Corner/errors/declining_an_already_declined_offer_returns_offer_state_invalid
    """
    bag = scenario.create_product(factories.checked_bag_product_payload())
    family = scenario.create_family(
        factories.fare_family_payload(code="ECO_BARE", bundle_price_cents=12000)
    )
    channel = scenario.create_channel(factories.direct_web_channel_payload())
    partner = make_channel_partner_headers(channel["id"])
    flight = scenario.create_flight(flight_no="AC550")
    scenario.post_demand(flight["id"], 50, 0)
    booking = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="OFFST1"
    )

    # One checked-bag offer is presented at the booking touchpoint, then declined.
    session = scenario.open_offer_session(
        booking["id"], channel["id"], "BOOKING", [bag["id"]]
    )
    offer_id = session["presented_offer_ids"][0]
    scenario.decline_offer(offer_id, channel["id"])
    booking_before = scenario.get_booking(booking["id"], channel["id"])

    # A declined offer is terminal: neither verb may touch it again.
    validate_error(
        api.decline_offer(offer_id, {}, partner), ApiErrorId.OFFER_STATE_INVALID
    )
    validate_error(
        api.accept_offer(
            offer_id,
            factories.offer_accept_payload(booking_before["version"]),
            partner,
        ),
        ApiErrorId.OFFER_STATE_INVALID,
    )

    offer = validate_success(api.get_ancillary_offer(offer_id, partner))
    assert_field_values(offer, offer_status="DECLINED")

    # No money moved and the refused accept did not consume the booking version.
    booking_after = scenario.get_booking(booking["id"], channel["id"])
    assert_field_values(
        booking_after,
        ancillary_gross_cents=0,
        version=booking_before["version"],
    )
    _, ledger_meta = validate_paginated(
        api.list_booking_revenue_entries(booking["id"], REVENUE_ACCOUNTANT)
    )
    assert ledger_meta["total_count"] == 0, (
        "a declined offer posts no revenue entry: "
        f"{ledger_meta['total_count']} rows on the booking's trail"
    )


def test_releasing_an_already_released_seat_is_refused_as_assignment_state_invalid(
    api, scenario
):
    """PRD §2.7: "`ERR_SEAT_ASSIGNMENT_STATE_INVALID` (409) — the assignment's
    `assignment_state` is either `HELD` or `CONFIRMED` when it is released; an
    assignment already `RELEASED` cannot be released again. This guards seat
    release only."
    PRD §3.7: "Releasing from `HELD` decreases the segment's `held_seats` by one
    and increases its `available_seats` by one, and posts and reverses
    **nothing**, because a held seat was never sold."

    Design: Corner/errors/releasing_an_already_released_seat_returns_seat_assignment_state_invalid
    """
    seat_product = scenario.create_product(factories.standard_seat_product_payload())
    family = scenario.create_family(
        factories.fare_family_payload(code="ECO_BARE", bundle_price_cents=12000)
    )
    channel = scenario.create_channel(factories.direct_web_channel_payload())
    partner = make_channel_partner_headers(channel["id"])
    flight = scenario.create_flight(flight_no="AC551")
    # Row 20 sits above the row-band adjustment, MID is a neutral zone and the
    # flight is still at the LOW demand tier, so the seat prices at 2000 cents.
    segment = scenario.create_segment(
        flight["id"],
        seat_product["id"],
        zone="MID",
        row_start=20,
        row_end=20,
        seat_letters=["A", "B", "C"],
        base_price_cents=2000,
    )
    booking = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="SEATST"
    )
    assignment = scenario.assign_seat(
        booking["id"], channel["id"], segment["id"], 20, "A"
    )
    released = validate_success(
        api.release_seat_assignment(
            assignment["id"],
            factories.seat_release_payload("PASSENGER_RELEASE"),
            partner,
        )
    )
    version_after_release = released["version"]

    validate_error(
        api.release_seat_assignment(
            assignment["id"],
            factories.seat_release_payload("PASSENGER_RELEASE"),
            partner,
        ),
        ApiErrorId.SEAT_ASSIGNMENT_STATE_INVALID,
    )

    settled = validate_success(api.get_seat_assignment(assignment["id"], partner))
    assert_field_values(
        settled,
        assignment_state="RELEASED",
        released_reason="PASSENGER_RELEASE",
        price_charged_cents=2000,
        version=version_after_release,
    )

    # The refused release credited nothing back to the cabin a second time.
    segment_after = scenario.get_segment(segment["id"])
    assert_segment_counts(
        segment_after, total_seats=3, held_seats=0, sold_seats=0, available_seats=3
    )


def test_rescinding_an_already_rescinded_waiver_is_refused_as_waiver_state_invalid(
    api, scenario
):
    """PRD §2.7: "`ERR_WAIVER_STATE_INVALID` (409) — the waiver's `waiver_state` is
    `ACTIVE` when it is rescinded. This guards waiver rescission only."
    PRD §3.8: "It requires that the waiver's `waiver_state` is `ACTIVE`
    (`ERR_WAIVER_STATE_INVALID`) and that the flight has not departed
    (`ERR_FLIGHT_ALREADY_DEPARTED`), takes a `rescind_reason` which is recorded on
    the waiver, and drives `waiver_state` from `ACTIVE` to `RESCINDED`."
    PRD §3.8: "The flight's `active_waiver_count` is recomputed and, when it falls
    to 0, the flight's `irops_state` moves `IRREGULAR` → `RECOVERED`."

    Design: Corner/errors/rescinding_an_already_rescinded_waiver_returns_waiver_state_invalid
    """
    flight = scenario.create_flight(flight_no="AC552")
    waiver = scenario.declare_waiver(flight["id"], "DELAY", 240, ["CHANGE"])
    rescinded = scenario.rescind_waiver(waiver["id"], "delay retracted")
    version_after_rescind = rescinded["version"]

    validate_error(
        api.rescind_irops_waiver(
            waiver["id"],
            factories.waiver_rescind_payload("second attempt"),
            OPERATIONS_CONTROLLER,
        ),
        ApiErrorId.WAIVER_STATE_INVALID,
    )

    # RESCINDED is terminal, so the second reason never reaches the waiver.
    settled = validate_success(api.get_irops_waiver(waiver["id"], OPERATIONS_CONTROLLER))
    assert_field_values(
        settled,
        waiver_state="RESCINDED",
        rescind_reason="delay retracted",
        credited_bookings_count=0,
        credited_amount_cents=0,
        version=version_after_rescind,
    )

    # No compensation was re-run against the flight either.
    flight_after = validate_success(api.get_flight(flight["id"], OPERATIONS_CONTROLLER))
    assert_field_values(flight_after, irops_state="RECOVERED", active_waiver_count=0)


def test_resyncing_an_in_parity_publication_is_refused_as_publication_state_invalid(
    api, scenario
):
    """PRD §2.7: "`ERR_PUBLICATION_STATE_INVALID` (409) — the publication's
    `parity_state` is `OUT_OF_PARITY` when it is resynchronised. This guards
    publication resynchronisation only."
    PRD §3.4: "A resynchronisation moves the publication `OUT_OF_PARITY` →
    `IN_PARITY`, and requires both that the publication is currently
    `OUT_OF_PARITY` — otherwise `ERR_PUBLICATION_STATE_INVALID` — and that the
    family's `status` is `PUBLISHED` — otherwise `ERR_FAMILY_NOT_PUBLISHED`."
    PRD §3.4: "A new channel starts `COMPLIANT` with a `parity_breach_count` of 0."

    Design: Corner/errors/resyncing_an_in_parity_publication_returns_publication_state_invalid
    """
    bag = scenario.create_product(factories.checked_bag_product_payload())
    family = scenario.create_family(
        factories.fare_family_payload(code="ECO_PUB", name="Economy Published")
    )
    scenario.add_attribute(
        family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1
    )
    published = scenario.publish_family(family["id"])
    channel = scenario.create_channel(factories.direct_web_channel_payload())
    publication = scenario.publish_to_channel(
        family["id"], channel["id"], published["version"]
    )
    assert_field_values(publication, parity_state="IN_PARITY")
    version_at_publication = publication["version"]

    validate_error(
        api.resync_channel_publication(publication["id"], {}, DISTRIBUTION_MANAGER),
        ApiErrorId.PUBLICATION_STATE_INVALID,
    )

    # Nothing was silently re-pinned: the content still matches what was approved.
    settled = scenario.get_publication(publication["id"])
    assert_field_values(
        settled,
        parity_state="IN_PARITY",
        published_fee_fingerprint="ECO_PUB|1|BAG_CHECKED_1:INCLUDED:1:3500",
        version=version_at_publication,
    )
    channel_after = scenario.get_channel(channel["id"])
    assert_field_values(
        channel_after, content_parity_status="COMPLIANT", parity_breach_count=0
    )


def test_skipping_a_sales_phase_is_refused_as_phase_transition_invalid(api, scenario):
    """PRD §2.7: "`ERR_PHASE_TRANSITION_INVALID` (409) — the requested
    `target_phase` is exactly the next phase along `PRESALE` → `CHECKIN_OPEN` →
    `BOARDING` → `DEPARTED`. Skipping a phase or moving backwards is rejected.
    This guards phase advance only."
    PRD §3.3: "Advancing the retailing phase takes a `target_phase` and moves the
    flight exactly one step; anything else is refused with
    `ERR_PHASE_TRANSITION_INVALID`."

    Design: Corner/errors/skipping_a_sales_phase_returns_phase_transition_invalid
    """
    flight = scenario.create_flight(flight_no="AC553")
    assert_field_values(flight, sales_phase="PRESALE", version=1)

    # Two steps at once, and standing still, are both refused.
    validate_error(
        api.advance_flight_phase(
            flight["id"], {"target_phase": "BOARDING"}, OPERATIONS_CONTROLLER
        ),
        ApiErrorId.PHASE_TRANSITION_INVALID,
    )
    validate_error(
        api.advance_flight_phase(
            flight["id"], {"target_phase": "PRESALE"}, OPERATIONS_CONTROLLER
        ),
        ApiErrorId.PHASE_TRANSITION_INVALID,
    )

    still_presale = validate_success(api.get_flight(flight["id"], OPERATIONS_CONTROLLER))
    assert_field_values(still_presale, sales_phase="PRESALE", version=1)

    # The immediate successor is accepted, which proves only the step size failed.
    advanced = validate_success(
        api.advance_flight_phase(
            flight["id"], {"target_phase": "CHECKIN_OPEN"}, OPERATIONS_CONTROLLER
        )
    )
    assert_field_values(advanced, sales_phase="CHECKIN_OPEN")


def test_writes_touching_a_departed_flight_are_refused_as_flight_already_departed(
    api, scenario
):
    """PRD §2.7: "`ERR_FLIGHT_ALREADY_DEPARTED` (409) — the flight's `sales_phase`
    is not `DEPARTED` for a write that touches the flight's inventory, waivers,
    bookings or seats. This guards seat-segment creation, demand snapshots, waiver
    declaration, waiver rescission, booking creation, change-open and seat release."
    PRD §3.3: "`sales_phase` walks the retailing timeline `PRESALE` →
    `CHECKIN_OPEN` → `BOARDING` → `DEPARTED` and is terminal at `DEPARTED`."
    PRD §3.3: "A new flight starts with `sales_phase` `PRESALE`, `irops_state`
    `NORMAL`, `booked_load_factor_pct` at 0, `demand_index_bp` at 0, `demand_tier`
    `LOW`, and both `active_waiver_count` and `ticketed_booking_count` at 0."

    Design: Corner/errors/writes_touching_a_departed_flight_return_flight_already_departed
    """
    seat = scenario.create_product(factories.standard_seat_product_payload())
    family = scenario.create_family(
        factories.fare_family_payload(
            code="ECO_BARE", name="Economy Bare", bundle_price_cents=12000
        )
    )
    channel = scenario.create_channel(factories.direct_web_channel_payload())
    flight = scenario.create_flight(flight_no="AC554", origin="SFO", destination="JFK")
    _advance_phases(api, flight["id"], "CHECKIN_OPEN", "BOARDING", "DEPARTED")
    departed = validate_success(api.get_flight(flight["id"], OPERATIONS_CONTROLLER))
    version_at_departure = departed["version"]

    # New inventory, a new sale, a new waiver and a fresh demand read all bounce.
    validate_error(
        api.create_seat_segment(
            factories.seat_segment_payload(
                flight["id"], seat["id"], row_start=20, row_end=20, seat_letters=["A"]
            ),
            OPERATIONS_CONTROLLER,
        ),
        ApiErrorId.FLIGHT_ALREADY_DEPARTED,
    )
    validate_error(
        api.create_booking(
            factories.booking_payload(
                flight["id"], family["id"], channel["id"], record_locator="DEPRT1"
            ),
            make_channel_partner_headers(channel["id"]),
        ),
        ApiErrorId.FLIGHT_ALREADY_DEPARTED,
    )
    validate_error(
        api.declare_irops_waiver(
            flight["id"],
            factories.irops_waiver_payload("DELAY", 240, ["CHANGE"]),
            OPERATIONS_CONTROLLER,
        ),
        ApiErrorId.FLIGHT_ALREADY_DEPARTED,
    )
    validate_error(
        api.post_demand_snapshot(
            flight["id"],
            factories.demand_snapshot_payload(90, 3000),
            OPERATIONS_CONTROLLER,
        ),
        ApiErrorId.FLIGHT_ALREADY_DEPARTED,
    )

    # The flight is exactly as departure left it: no demand, no waiver, no version bump.
    settled = validate_success(api.get_flight(flight["id"], OPERATIONS_CONTROLLER))
    assert_field_values(
        settled,
        sales_phase="DEPARTED",
        demand_tier="LOW",
        booked_load_factor_pct=0,
        demand_index_bp=0,
        active_waiver_count=0,
        version=version_at_departure,
    )

    segments, segments_meta = validate_paginated(
        api.list_seat_segments(OPERATIONS_CONTROLLER, {"flight_id": flight["id"]})
    )
    assert segments == [], f"a departed flight gained inventory: {segments}"
    assert segments_meta["total_count"] == 0, (
        f"no segment may exist on the departed flight: {segments_meta}"
    )

    bookings, bookings_meta = validate_paginated(
        api.list_bookings(
            make_channel_partner_headers(channel["id"]), {"flight_id": flight["id"]}
        )
    )
    assert bookings == [], f"a departed flight gained a booking: {bookings}"
    assert bookings_meta["total_count"] == 0, (
        f"no booking may exist on the departed flight: {bookings_meta}"
    )


def test_assigning_a_seat_after_departure_is_refused_as_segment_closed(api, scenario):
    """PRD §2.7: "Seat *assignment* is deliberately **not** in this scope: departure
    closes every segment of the flight, so an assignment attempt after departure is
    refused by the more specific segment-closed check at step 17 instead."
    PRD §2.7: "`ERR_SEGMENT_CLOSED` (409) — the target segment's `segment_state` is
    `OPEN` when a seat on it is assigned. This guards seat assignment only."
    PRD §3.3: "`BOARDING` → `DEPARTED` ... moves every segment of the flight whose
    `segment_state` is `OPEN` to `CLOSED`; ... it moves every booking on the flight
    whose `booking_status` is `TICKETED` to `FLOWN`."
    PRD §3.7: "Note also that a departed flight does not surface here as a departure
    error — departure closes every segment, so the closed-segment check answers first."

    Design: Corner/errors/assigning_a_seat_after_departure_returns_segment_closed_not_flight_departed
    """
    seat = scenario.create_product(factories.standard_seat_product_payload())
    family = scenario.create_family(
        factories.fare_family_payload(
            code="ECO_BARE", name="Economy Bare", bundle_price_cents=12000
        )
    )
    channel = scenario.create_channel(factories.direct_web_channel_payload())
    flight = scenario.create_flight(flight_no="AC555", origin="SFO", destination="JFK")
    segment = scenario.create_segment(
        flight["id"], seat["id"], zone="MID", row_start=20, row_end=20
    )
    booking = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="CLOSED"
    )
    _advance_phases(api, flight["id"], "CHECKIN_OPEN", "BOARDING", "DEPARTED")

    error_data = validate_error(
        api.create_seat_assignment(
            booking["id"],
            factories.seat_assignment_payload(segment["id"], 20, "A"),
            make_channel_partner_headers(channel["id"]),
        ),
        ApiErrorId.SEGMENT_CLOSED,
    )
    # The departure barrier is the losing candidate here, not the answer.
    assert error_data["error_id"] != ApiErrorId.FLIGHT_ALREADY_DEPARTED, (
        "a post-departure seat request must answer with the specific closed-segment "
        f"refusal, not the flight-level one: {error_data}"
    )

    # Departure closed the rectangle without selling or holding any of it.
    closed = scenario.get_segment(segment["id"])
    assert_field_values(closed, segment_state="CLOSED")
    assert_segment_counts(
        closed, total_seats=3, held_seats=0, sold_seats=0, available_seats=3
    )

    # Only ticketed bookings fly, so this one is still held and still seatless.
    still_held = scenario.get_booking(booking["id"], channel["id"])
    assert_field_values(still_held, booking_status="HELD")
    assignments, assignments_meta = validate_paginated(
        api.list_seat_assignments(
            make_channel_partner_headers(channel["id"]), {"booking_id": booking["id"]}
        )
    )
    assert assignments == [], f"the refused assignment was persisted: {assignments}"
    assert assignments_meta["total_count"] == 0, (
        f"a refused seat request must leave no assignment behind: {assignments_meta}"
    )
