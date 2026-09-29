"""Validation ordering and the conditions that guard each write.

The contract fixes one global order in which checks run, so a request that
breaks several rules at once always gets the same answer: the earliest broken
rule wins and every later one stays silent.  These tests deliberately break two
rules per request and pin which answer comes back, and they also pin the happy
path for the checks that are easiest to over-enforce - a seat inside its
rectangle, a touchpoint that matches the sales phase, a delay threshold that
only bites when change fees are in scope.
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
    REVENUE_ACCOUNTANT,
    ROLE_CHANNEL_PARTNER,
    assert_fingerprint,
    assert_money_field,
    assert_segment_counts,
    factories,
    make_channel_partner_headers,
)

# The fingerprint of a family holding one included checked bag at list price.
LITE_FINGERPRINT = "ECO_LITE|1|BAG_CHECKED_1:INCLUDED:1:3500"


def assert_ladder_winner(response, winning_error_id: str, losing_error_id: str) -> dict:
    """The earliest broken rule decides the answer.

    ``losing_error_id`` names a condition the request also breaks but which is
    checked later, so it must never be the one reported.
    """
    reported = (response.json().get("data") or {}).get("error_id")
    assert reported != losing_error_id, (
        f"{losing_error_id} was reported, but {winning_error_id} is checked earlier "
        "and must decide the response"
    )
    return validate_error(response, winning_error_id)


def lite_family_payload(**overrides):
    """ECO_LITE: ECONOMY, base fare 12000, bundle 14000, change fee 7500."""
    return factories.fare_family_payload(
        code="ECO_LITE",
        name="Economy Lite",
        cabin_class="ECONOMY",
        base_fare_cents=12000,
        bundle_price_cents=14000,
        refundability="NON_REFUNDABLE",
        change_fee_cents=7500,
        boarding_priority_tier=4,
        **overrides,
    )


def bare_family_payload(**overrides):
    """ECO_BARE: an unbundled ECONOMY shell, base fare and bundle both 12000."""
    return factories.fare_family_payload(
        code="ECO_BARE",
        name="Economy Bare",
        cabin_class="ECONOMY",
        base_fare_cents=12000,
        bundle_price_cents=12000,
        refundability="NON_REFUNDABLE",
        change_fee_cents=7500,
        boarding_priority_tier=4,
        **overrides,
    )


def ota_channel_payload(**overrides):
    """OTA_SKYDEAL: an online travel agency taking 900 bp of commission."""
    return factories.distribution_channel_payload(
        channel_code="OTA_SKYDEAL",
        channel_type="OTA",
        commission_bp=900,
        markup_bp=500,
        max_ancillary_price_cents=6000,
        supported_categories=["BAGGAGE", "SEAT", "CHANGE", "BOARDING", "ONBOARD"],
        parity_required=True,
        **overrides,
    )


# ---------------------------------------------------------------------------
# The point-of-sale fee disclosure
# ---------------------------------------------------------------------------
def test_acknowledging_with_a_wrong_fingerprint_is_refused(api, scenario):
    """PRD §3.5: "the supplied fingerprint must equal the booking's
    `disclosed_fee_fingerprint` byte for byte, or the request is refused with
    `ERR_DISCLOSURE_FINGERPRINT_MISMATCH`."
    PRD §3.5: "On success `disclosure_acked_at` is stamped from the logical clock
    and the booking's `version` increments."

    Design: Corner/validations/disclosure_ack_with_a_wrong_fingerprint_returns_fingerprint_mismatch
    """
    bag = scenario.create_product(factories.checked_bag_product_payload())
    family = scenario.create_family(lite_family_payload())
    scenario.add_attribute(
        family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1
    )
    channel = scenario.create_channel(factories.direct_web_channel_payload())
    flight = scenario.create_flight(flight_no="AC530", origin="SFO", destination="JFK")
    booking = scenario.create_booking(
        flight["id"],
        family["id"],
        channel["id"],
        record_locator="DISCL1",
        passenger_name="Ada Lovelace",
    )

    disclosed = scenario.disclose(booking["id"], channel["id"])
    assert disclosed["disclosure_state"] == "PENDING_ACK", (
        f"issuance moves the booking to PENDING_ACK, not {disclosed['disclosure_state']!r}"
    )
    assert_fingerprint(disclosed, "disclosed_fee_fingerprint", LITE_FINGERPRINT)
    assert disclosed["version"] == 2, (
        f"the hold plus the issuance put the booking at version 2, not "
        f"{disclosed['version']}"
    )

    # One cent off in the trailing effective unit price: the comparison is byte
    # for byte, so this is not the disclosure the passenger was shown.
    response = api.acknowledge_disclosure(
        booking["id"],
        factories.disclosure_ack_payload("ECO_LITE|1|BAG_CHECKED_1:INCLUDED:1:3501"),
        make_channel_partner_headers(channel["id"]),
    )
    validate_error(response, ApiErrorId.DISCLOSURE_FINGERPRINT_MISMATCH)

    unchanged = scenario.get_booking(booking["id"], channel["id"])
    assert unchanged["disclosure_state"] == "PENDING_ACK", (
        "a refused acknowledgement leaves the booking awaiting one, but it reads "
        f"{unchanged['disclosure_state']!r}"
    )
    assert unchanged.get("disclosure_acked_at") is None, (
        "nothing was acknowledged, so disclosure_acked_at stays null but is "
        f"{unchanged.get('disclosure_acked_at')!r}"
    )
    assert_fingerprint(unchanged, "disclosed_fee_fingerprint", LITE_FINGERPRINT)
    assert unchanged["version"] == 2, (
        f"the refusal is not a mutation, so version stays 2 but is {unchanged['version']}"
    )

    # The very same booking accepts the acknowledgement once the passenger echoes
    # what was actually disclosed.
    acked = scenario.acknowledge(
        booking["id"], channel["id"], unchanged["disclosed_fee_fingerprint"]
    )
    assert acked["disclosure_state"] == "ACKNOWLEDGED", (
        f"the matching fingerprint must be accepted, got {acked['disclosure_state']!r}"
    )
    assert acked.get("disclosure_acked_at") is not None, (
        "a successful acknowledgement stamps disclosure_acked_at from the clock"
    )
    assert acked["version"] == 3, (
        f"the acknowledgement is the third mutation of this booking, not version "
        f"{acked['version']}"
    )


def test_a_second_acknowledgement_reports_the_state_not_the_fingerprint(api, scenario):
    """PRD §2.7 item 10: "the booking's `disclosure_state` is `PENDING_ACK` when a
    disclosure is acknowledged. This guards disclosure acknowledgement only."
    PRD §2.7: "Checks are evaluated in a fixed order and the **first** failure
    determines the response. The ladder below is exhaustive and its numbering is
    the precedence: a lower number is evaluated earlier and wins."
    PRD §2.7 item 27: "the supplied `acknowledged_fee_fingerprint` equals the
    booking's `disclosed_fee_fingerprint` byte for byte."

    Design: Corner/validations/disclosure_ack_state_is_checked_before_the_fingerprint
    """
    bag = scenario.create_product(factories.checked_bag_product_payload())
    family = scenario.create_family(lite_family_payload())
    scenario.add_attribute(
        family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1
    )
    channel = scenario.create_channel(factories.direct_web_channel_payload())
    flight = scenario.create_flight(flight_no="AC536", origin="SFO", destination="JFK")
    booking = scenario.create_booking(
        flight["id"],
        family["id"],
        channel["id"],
        record_locator="DISCL2",
        passenger_name="Ada Lovelace",
    )
    scenario.disclose(booking["id"], channel["id"])
    acked = scenario.acknowledge(booking["id"], channel["id"], LITE_FINGERPRINT)
    assert acked["disclosure_state"] == "ACKNOWLEDGED", (
        f"the setup must reach ACKNOWLEDGED, got {acked['disclosure_state']!r}"
    )
    acked_version = acked["version"]

    # This request breaks two rules at once: the disclosure has already been
    # acknowledged, and the fingerprint it carries is wrong anyway.
    response = api.acknowledge_disclosure(
        booking["id"],
        factories.disclosure_ack_payload("ECO_LITE|1|BAG_CHECKED_1:INCLUDED:1:9999"),
        make_channel_partner_headers(channel["id"]),
    )
    assert_ladder_winner(
        response,
        ApiErrorId.DISCLOSURE_STATE_INVALID,
        ApiErrorId.DISCLOSURE_FINGERPRINT_MISMATCH,
    )

    unchanged = scenario.get_booking(booking["id"], channel["id"])
    assert unchanged["disclosure_state"] == "ACKNOWLEDGED", (
        "the booking keeps the acknowledgement it already has, but reads "
        f"{unchanged['disclosure_state']!r}"
    )
    assert unchanged.get("disclosure_acked_at") is not None, (
        "the original acknowledgement timestamp survives the refusal"
    )
    assert unchanged["version"] == acked_version, (
        f"the refusal is not a mutation, so version stays {acked_version} but is "
        f"{unchanged['version']}"
    )
    assert_fingerprint(unchanged, "disclosed_fee_fingerprint", LITE_FINGERPRINT)


# ---------------------------------------------------------------------------
# Identity before authorisation
# ---------------------------------------------------------------------------
def test_missing_user_id_header_is_reported_before_the_role_check(api, scenario):
    """PRD §2.1: "If either header is absent or empty, the request is rejected
    with `ERR_MISSING_AUTH_HEADERS` (HTTP 401) before anything else is examined.
    If the supplied role is not one of the six roles below, or is a recognised
    role that is not authorised for the endpoint being called, the request is
    rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.7 item 1: "`X-User-Role` and `X-User-ID` are both present and
    non-empty. Applies to every endpoint."

    Design: Corner/validations/missing_x_user_id_header_beats_the_role_check
    """
    # A selling channel may not design fare families, and this caller has not
    # even identified itself: the missing identity is the earlier failure.
    response = api.create_fare_family(
        factories.fare_family_payload(code="ECO_NOPE", name="Economy Nope"),
        {"X-User-Role": ROLE_CHANNEL_PARTNER},
    )
    assert_ladder_winner(
        response, ApiErrorId.MISSING_AUTH_HEADERS, ApiErrorId.ROLE_NOT_PERMITTED
    )
    assert response.status_code == 401, (
        f"an unidentified caller is answered with 401, not {response.status_code}"
    )

    # Nothing was created: the request never reached the catalog.
    families, meta = validate_paginated(api.list_fare_families(MERCHANDISING_ANALYST))
    assert meta["total_count"] == 0, (
        f"no family may exist after the refusal, but total_count is {meta['total_count']}"
    )
    assert families == [], f"the family list should be empty but holds {families}"


# ---------------------------------------------------------------------------
# Channel scope and channel-specific content
# ---------------------------------------------------------------------------
def test_a_foreign_partner_is_told_about_scope_not_about_booking_state(api, scenario):
    """PRD §2.7 item 6: "when the acting role is `ChannelPartner`, `X-User-ID`
    equals the `distribution_channel_id` of the booking the request targets, or
    of the booking that owns the targeted offer or seat assignment."
    PRD §2.7: "The ladder below is exhaustive and its numbering is the
    precedence: a lower number is evaluated earlier and wins."
    PRD §2.7 item 9: "`HELD`, `TICKETED` or `CHANGE_PENDING` for cancelling and
    for assigning a seat"

    Design: Corner/validations/channel_scope_violation_beats_booking_state_on_a_foreign_cancel
    """
    family = scenario.create_family(bare_family_payload())
    direct = scenario.create_channel(factories.direct_web_channel_payload())
    agency = scenario.create_channel(ota_channel_payload())
    flight = scenario.create_flight(flight_no="AC532", origin="SFO", destination="JFK")
    booking = scenario.create_booking(
        flight["id"],
        family["id"],
        direct["id"],
        record_locator="SCOPE1",
        passenger_name="Ada Lovelace",
    )
    scenario.cancel(booking["id"], direct["id"], "passenger withdrew")

    # The agency owns neither this booking nor any right to learn its state.
    response = api.cancel_booking(
        booking["id"],
        factories.cancel_payload("foreign partner tries again"),
        make_channel_partner_headers(agency["id"]),
    )
    assert_ladder_winner(
        response, ApiErrorId.CHANNEL_SCOPE_VIOLATION, ApiErrorId.BOOKING_STATE_INVALID
    )
    assert response.status_code == 403, (
        f"a foreign partner is answered with 403, not {response.status_code}"
    )

    # Read it back through a role with no channel scoping to prove nothing moved.
    unchanged = validate_success(api.get_booking(booking["id"], DISTRIBUTION_MANAGER))
    assert unchanged["booking_status"] == "CANCELLED", (
        f"the booking must stay CANCELLED, got {unchanged['booking_status']!r}"
    )
    assert unchanged["version"] == 2, (
        f"the hold plus the one legitimate cancellation leave version at 2, not "
        f"{unchanged['version']}"
    )


def test_ticketing_needs_a_publication_on_the_selling_channel(api, scenario):
    """PRD §2.7 item 29: "a publication exists for the booking's `fare_family_id`
    and `distribution_channel_id` pair whose `parity_state` is `IN_PARITY`. This
    guards ticketing only."
    PRD §3.4: "The new publication's initial `parity_state` depends on the family:
    if the family's `status` is already `PUBLISHED`, the publication is promoted
    to `IN_PARITY` within the same request; otherwise it waits in `PENDING` until
    the family is approved."
    PRD §3.5: "It pins `fare_component_cents` from the family's
    `bundle_price_cents` at that instant, freezing the fare component against
    later family edits."

    Design: Corner/validations/ticket_requires_an_in_parity_publication_for_its_own_channel
    """
    bag = scenario.create_product(factories.checked_bag_product_payload())
    family = scenario.create_family(lite_family_payload())
    scenario.add_attribute(
        family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1
    )
    published = scenario.publish_family(family["id"])
    assert published["status"] == "PUBLISHED", (
        f"the family must be PUBLISHED before ticketing is attempted, got "
        f"{published['status']!r}"
    )

    direct = scenario.create_channel(factories.direct_web_channel_payload())
    agency = scenario.create_channel(ota_channel_payload())
    # The content is live on the airline's own site and nowhere else.
    publication = scenario.publish_to_channel(
        family["id"], direct["id"], published["version"]
    )
    assert publication["parity_state"] == "IN_PARITY", (
        "publishing an already published family lands IN_PARITY at once, but the "
        f"publication reads {publication['parity_state']!r}"
    )

    flight = scenario.create_flight(flight_no="AC533", origin="SFO", destination="JFK")
    booking = scenario.create_booking(
        flight["id"],
        family["id"],
        agency["id"],
        record_locator="PARCH1",
        passenger_name="Ada Lovelace",
    )
    acked = scenario.disclose_and_acknowledge(booking["id"], agency["id"])
    assert acked["booking_status"] == "HELD", (
        f"the booking must still be HELD, got {acked['booking_status']!r}"
    )
    assert acked["disclosure_state"] == "ACKNOWLEDGED", (
        "every earlier ticketing condition is satisfied, including the "
        f"acknowledgement, but disclosure_state is {acked['disclosure_state']!r}"
    )

    # The publication lookup is on the family-and-channel pair, not the family.
    response = api.ticket_booking(
        booking["id"], {}, make_channel_partner_headers(agency["id"])
    )
    validate_error(response, ApiErrorId.FAMILY_NOT_PUBLISHED_TO_CHANNEL)

    _, meta = validate_paginated(
        api.list_channel_publications(
            DISTRIBUTION_MANAGER,
            {"fare_family_id": family["id"], "distribution_channel_id": agency["id"]},
        )
    )
    assert meta["total_count"] == 0, (
        "the agency was never given this content, so it has no publication, but "
        f"total_count is {meta['total_count']}"
    )

    unticketed = scenario.get_booking(booking["id"], agency["id"])
    assert unticketed["booking_status"] == "HELD", (
        f"the refused ticket leaves the booking HELD, got {unticketed['booking_status']!r}"
    )
    assert unticketed.get("fare_component_cents") is None, (
        "only ticketing pins the fare component, so it stays null but reads "
        f"{unticketed.get('fare_component_cents')!r}"
    )
    assert_money_field(unticketed, "channel_settlement_total_cents", 0)


# ---------------------------------------------------------------------------
# The seat map: the rectangle and the cabin aggregate
# ---------------------------------------------------------------------------
def test_a_seat_inside_the_segment_rectangle_is_accepted(api, scenario):
    """PRD §2.7 item 41: "the requested `row` is at least the segment's
    `row_start` and at most its `row_end`, and the requested `seat_letter` is a
    member of the segment's `seat_letters`. This guards seat assignment only."
    PRD §3.7: "The assignment's `price_charged_cents` is normally the segment's
    `effective_price_cents`, pinned at the instant the seat is taken so that a
    later demand snapshot cannot retroactively change what the passenger was
    charged."
    PRD §3.7: "On a `HELD` booking the seat is taken as `HELD` and the segment's
    `held_seats` increases by one."

    Design: Corner/validations/seat_assignment_inside_the_segment_rectangle_succeeds
    """
    seat_product = scenario.create_product(factories.standard_seat_product_payload())
    family = scenario.create_family(bare_family_payload())
    channel = scenario.create_channel(factories.direct_web_channel_payload())
    flight = scenario.create_flight(flight_no="AC531", origin="SFO", destination="JFK")
    # Rows 16 to 18 by letters A, B and C: nine seats, no row-band premium at row
    # 16 or beyond, and a mid-cabin zone at par, so the seat prices at 2000.
    segment = scenario.create_segment(flight["id"], seat_product["id"])
    assert_segment_counts(
        segment, total_seats=9, held_seats=0, sold_seats=0, available_seats=9
    )
    assert_money_field(segment, "effective_price_cents", 2000)

    booking = scenario.create_booking(
        flight["id"],
        family["id"],
        channel["id"],
        record_locator="SEATC1",
        passenger_name="Ada Lovelace",
    )

    # Row 17 letter B sits strictly inside the rectangle on both axes.
    assignment = validate_success(
        api.create_seat_assignment(
            booking["id"],
            factories.seat_assignment_payload(segment["id"], 17, "B"),
            make_channel_partner_headers(channel["id"]),
        ),
        201,
    )
    assert assignment["assignment_state"] == "HELD", (
        "a seat taken on a held booking is held, not confirmed, but reads "
        f"{assignment['assignment_state']!r}"
    )
    assert assignment["row"] == 17, f"row should be 17 but is {assignment['row']}"
    assert assignment["seat_letter"] == "B", (
        f"seat_letter should be B but is {assignment['seat_letter']!r}"
    )
    assert assignment.get("released_reason") is None, (
        "the seat has not been given back, so released_reason is null but is "
        f"{assignment.get('released_reason')!r}"
    )
    assert_money_field(assignment, "price_charged_cents", 2000)

    assert_segment_counts(
        scenario.get_segment(segment["id"]),
        total_seats=9,
        held_seats=1,
        sold_seats=0,
        available_seats=8,
    )

    # A held seat is inventory, not revenue.
    _, meta = validate_paginated(
        api.list_booking_revenue_entries(booking["id"], REVENUE_ACCOUNTANT)
    )
    assert meta["total_count"] == 0, (
        "holding a seat posts nothing to the ledger, but the booking already has "
        f"{meta['total_count']} entries"
    )


def test_two_individually_legal_segments_may_not_together_exceed_the_cabin(api, scenario):
    """PRD §2.7 item 40: "the sum of `total_seats` over every segment of the
    flight, including the one being created, is at most the flight's
    `cabin_seat_total`. This guards seat-segment creation only."
    PRD §3.3: "The segment's `total_seats` is therefore `row_end` minus
    `row_start` plus one, multiplied by the number of entries in `seat_letters`."
    PRD §2.7 item 39: "the new segment's rectangle of rows crossed with letters
    shares no individual seat with any existing segment on the same flight whose
    `segment_state` is `OPEN`."

    Design: Corner/validations/two_individually_valid_segments_together_exceed_the_cabin
    """
    seat_product = scenario.create_product(factories.standard_seat_product_payload())
    flight = scenario.create_flight(
        flight_no="AC534", origin="SFO", destination="JFK", cabin_seat_total=10
    )
    first = scenario.create_segment(
        flight["id"],
        seat_product["id"],
        zone="MID",
        row_start=16,
        row_end=18,
        seat_letters=["A", "B"],
    )
    assert_segment_counts(
        first, total_seats=6, held_seats=0, sold_seats=0, available_seats=6
    )

    # Rows 20 to 22 by letters A and B is six more seats. It overlaps nothing -
    # rows 20 to 22 share no seat with rows 16 to 18 - but six plus six is twelve
    # in a ten-seat cabin.
    response = api.create_seat_segment(
        factories.seat_segment_payload(
            flight["id"],
            seat_product["id"],
            zone="AFT",
            row_start=20,
            row_end=22,
            seat_letters=["A", "B"],
        ),
        OPERATIONS_CONTROLLER,
    )
    validate_error(response, ApiErrorId.SEGMENT_EXCEEDS_CABIN)

    segments, meta = validate_paginated(
        api.list_seat_segments(OPERATIONS_CONTROLLER, {"flight_id": flight["id"]})
    )
    assert meta["total_count"] == 1, (
        "the refused segment must not have been stored, so the flight still has "
        f"one segment, not {meta['total_count']}"
    )
    assert segments[0]["total_seats"] == 6, (
        f"the surviving segment still holds six seats, not {segments[0]['total_seats']}"
    )

    # Four more seats bring the cabin to exactly ten, and the rule allows the
    # cabin to be filled completely.
    third = scenario.create_segment(
        flight["id"],
        seat_product["id"],
        zone="AFT",
        row_start=20,
        row_end=21,
        seat_letters=["A", "B"],
    )
    assert_segment_counts(
        third, total_seats=4, held_seats=0, sold_seats=0, available_seats=4
    )
    _, meta_after = validate_paginated(
        api.list_seat_segments(OPERATIONS_CONTROLLER, {"flight_id": flight["id"]})
    )
    assert meta_after["total_count"] == 2, (
        "the flight now carries two segments totalling exactly the cabin, not "
        f"{meta_after['total_count']}"
    )


# ---------------------------------------------------------------------------
# Conditional and phase-sensitive checks
# ---------------------------------------------------------------------------
def test_the_delay_floor_bites_only_when_change_fees_are_waived(api, scenario):
    """PRD §3.8: "Where `CHANGE` is in scope and the `event_type` is `DELAY`,
    `delay_minutes` must be at least 180 — a delay of three hours or more — or
    the declaration is refused with `ERR_DELAY_THRESHOLD_NOT_MET`."
    PRD §2.7 item 44: "when `event_type` is `DELAY` and `CHANGE` is a member of
    `waiver_scope`, `delay_minutes` is at least the three-hour
    irregular-operations change-waiver threshold. This guards waiver declaration
    only."
    PRD §3.8: "The waiver is stamped `declared_at` from the logical clock, starts
    in `waiver_state` `ACTIVE`, and drives the flight's `irops_state` to
    `IRREGULAR` from either `NORMAL` or `RECOVERED`, recomputing the flight's
    `active_waiver_count` and incrementing the flight's `version`."

    Design: Corner/validations/delay_waiver_threshold_applies_only_when_change_is_in_scope
    """
    flight = scenario.create_flight(flight_no="AC535", origin="SFO", destination="JFK")

    # Two hours of delay is enough to credit baggage fees: no change fee is in
    # scope, so the three-hour floor never applies.
    bag_waiver = scenario.declare_waiver(flight["id"], "DELAY", 120, ["BAGGAGE"])
    assert bag_waiver["waiver_state"] == "ACTIVE", (
        f"a declared waiver starts ACTIVE, not {bag_waiver['waiver_state']!r}"
    )
    assert bag_waiver["delay_minutes"] == 120, (
        f"delay_minutes should be 120 but is {bag_waiver['delay_minutes']}"
    )
    irregular = validate_success(api.get_flight(flight["id"], OPERATIONS_CONTROLLER))
    assert irregular["irops_state"] == "IRREGULAR", (
        f"the declaration drives the flight IRREGULAR, not {irregular['irops_state']!r}"
    )
    assert irregular["active_waiver_count"] == 1, (
        f"one active waiver should be counted, not {irregular['active_waiver_count']}"
    )

    # The very same two hours, now also asking for change fees to be waived.
    response = api.declare_irops_waiver(
        flight["id"],
        factories.irops_waiver_payload("DELAY", 120, ["BAGGAGE", "CHANGE"]),
        OPERATIONS_CONTROLLER,
    )
    validate_error(response, ApiErrorId.DELAY_THRESHOLD_NOT_MET)

    survivor = validate_success(
        api.get_irops_waiver(bag_waiver["id"], OPERATIONS_CONTROLLER)
    )
    assert survivor["waiver_state"] == "ACTIVE", (
        "the earlier baggage waiver is untouched by the refusal but reads "
        f"{survivor['waiver_state']!r}"
    )
    assert survivor["delay_minutes"] == 120, (
        "the same 120 minutes was legal without change fees in scope, so it must "
        f"still be recorded, but delay_minutes is {survivor['delay_minutes']}"
    )
    unchanged_flight = validate_success(
        api.get_flight(flight["id"], OPERATIONS_CONTROLLER)
    )
    assert unchanged_flight["irops_state"] == "IRREGULAR", (
        f"the flight stays IRREGULAR, got {unchanged_flight['irops_state']!r}"
    )
    assert unchanged_flight["active_waiver_count"] == 1, (
        "the refused declaration created nothing, so the count stays 1 but is "
        f"{unchanged_flight['active_waiver_count']}"
    )

    # Three hours exactly clears the floor: the boundary is inclusive.
    change_waiver = scenario.declare_waiver(
        flight["id"], "DELAY", 180, ["BAGGAGE", "CHANGE"]
    )
    assert change_waiver["waiver_state"] == "ACTIVE", (
        f"a 180-minute change waiver is legal, but it reads "
        f"{change_waiver['waiver_state']!r}"
    )
    assert change_waiver["delay_minutes"] == 180, (
        f"delay_minutes should be 180 but is {change_waiver['delay_minutes']}"
    )
    both = validate_success(api.get_flight(flight["id"], OPERATIONS_CONTROLLER))
    assert both["active_waiver_count"] == 2, (
        f"two waivers are now active, not {both['active_waiver_count']}"
    )


def test_a_checkin_session_is_allowed_once_the_flight_reaches_checkin_open(api, scenario):
    """PRD §2.7 item 18: "the requested `touchpoint` matches the flight's
    `sales_phase` exactly: `BOOKING` requires `PRESALE`, `CHECKIN` requires
    `CHECKIN_OPEN`, and `INFLIGHT` requires `BOARDING`. This guards offer sessions
    only."
    PRD §3.6: "Second, multiply that result by the touchpoint multiplier — 10,000
    basis points at `BOOKING`, 11,000 at `CHECKIN`, and 12,500 at `INFLIGHT`, so
    an in-flight impulse buy carries a twenty-five percent uplift over the same
    product at booking — divide by 10,000, and round half up again."
    PRD §3.6: "Finally, `expected_value_cents` is `offered_price_cents`
    multiplied by `wtp_score_bp`, divided by 10,000 and rounded half up; this is
    the ranking key."

    Design: Corner/validations/offer_session_touchpoint_matching_the_sales_phase_succeeds
    """
    bag = scenario.create_product(factories.checked_bag_product_payload())
    family = scenario.create_family(bare_family_payload())
    channel = scenario.create_channel(factories.direct_web_channel_payload())
    flight = scenario.create_flight(flight_no="AC537", origin="SFO", destination="JFK")
    # A load factor of exactly 50 with a flat demand index leaves the elastic
    # score at par, so only the touchpoint moves the price.
    scenario.post_demand(flight["id"], 50, 0)
    booking = scenario.create_booking(
        flight["id"],
        family["id"],
        channel["id"],
        record_locator="TOUCH1",
        passenger_name="Ada Lovelace",
    )
    advanced = scenario.advance_phase(flight["id"], "CHECKIN_OPEN")
    assert advanced["sales_phase"] == "CHECKIN_OPEN", (
        f"the flight should be at CHECKIN_OPEN but is {advanced['sales_phase']!r}"
    )

    session = validate_success(
        api.create_offer_session(
            booking["id"],
            factories.offer_session_payload("CHECKIN", [bag["id"]]),
            make_channel_partner_headers(channel["id"]),
        ),
        201,
    )
    assert session["touchpoint"] == "CHECKIN", (
        f"the session ran at CHECKIN, not {session['touchpoint']!r}"
    )
    assert session["candidate_count"] == 1, (
        "the checked bag is the only requested product and it is eligible, so "
        f"candidate_count is 1 but is {session['candidate_count']}"
    )
    assert len(session["presented_offer_ids"]) == 1, (
        f"one offer should be presented but got {len(session['presented_offer_ids'])}"
    )

    offer = validate_success(
        api.get_ancillary_offer(
            session["presented_offer_ids"][0],
            make_channel_partner_headers(channel["id"]),
        )
    )
    assert offer["touchpoint"] == "CHECKIN", (
        f"the offer records the touchpoint it was priced at: {offer['touchpoint']!r}"
    )
    assert offer["wtp_score_bp"] == 10000, (
        "a load factor of exactly 50 and a flat demand index leave the score at "
        f"par, so wtp_score_bp is 10000 but is {offer['wtp_score_bp']}"
    )
    # 3500 at par, lifted by the 11,000 bp check-in multiplier, is 3850 cents.
    assert_money_field(offer, "offered_price_cents", 3850)
    assert_money_field(offer, "expected_value_cents", 3850)
    # Seventy percent of the 3500 list price is 2450; one hundred and eighty
    # percent is 6300. The chained price never touched either bound.
    assert 2450 <= offer["offered_price_cents"] <= 6300, (
        f"the offered price {offer['offered_price_cents']} must sit inside the "
        "2450 floor and the 6300 cap without being clamped to either"
    )
    assert offer["offer_status"] == "PRESENTED", (
        f"a freshly presented offer reads PRESENTED, not {offer['offer_status']!r}"
    )

    # The phase that has passed is no longer merchandisable.
    response = api.create_offer_session(
        booking["id"],
        factories.offer_session_payload("BOOKING", [bag["id"]]),
        make_channel_partner_headers(channel["id"]),
    )
    validate_error(response, ApiErrorId.TOUCHPOINT_PHASE_MISMATCH)
