"""Entity shape: declared fields, regulatory defaults, seeded ledgers and 404 codes."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    ERR_BOOKING_NOT_FOUND,
    ERR_FLIGHT_SEGMENT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_PASSENGER_NOT_FOUND,
    OFFICER_HEADERS,
    OPS_HEADERS,
    add_ancillary,
    add_checked_bag,
    assert_activity_types,
    assert_booking_ledger,
    assert_cents,
    assert_common_fields,
    assert_hours,
    assert_instant,
    assert_list_meta,
    assert_no_version_fields,
    assert_null,
    assert_segment_state,
    create_booking,
    create_passenger,
    create_policy_profile,
    factories as f,
    file_complaint,
    list_activities,
    make_passenger_headers,
    obligations_with_meta,
    open_report,
    read_bag,
    read_booking,
    read_profile,
)

# ─── Policy profile fields and defaults ───────────────

_TUNED_THRESHOLDS = {
    "domestic_significant_delay_minutes": 120,
    "international_significant_delay_minutes": 300,
    "credit_card_refund_deadline_days": 5,
    "other_method_refund_deadline_days": 14,
    "bag_delay_threshold_hours_domestic": 6,
    "bag_delay_threshold_hours_international": 24,
    "tarmac_deplane_deadline_minutes_domestic": 150,
    "tarmac_deplane_deadline_minutes_international": 210,
    "complaint_ack_deadline_days": 15,
    "complaint_answer_deadline_days_general": 45,
    "complaint_answer_deadline_days_disability": 20,
    "travel_credit_default_permitted": True,
    "travel_credit_election_bonus_pct": 0.25,
}

_REGULATORY_DEFAULTS = {
    "domestic_significant_delay_minutes": 180,
    "international_significant_delay_minutes": 360,
    "credit_card_refund_deadline_days": 7,
    "other_method_refund_deadline_days": 20,
    "bag_delay_threshold_hours_domestic": 12,
    "bag_delay_threshold_hours_international": 30,
    "tarmac_deplane_deadline_minutes_domestic": 180,
    "tarmac_deplane_deadline_minutes_international": 240,
    "complaint_ack_deadline_days": 30,
    "complaint_answer_deadline_days_general": 60,
    "complaint_answer_deadline_days_disability": 30,
}


class TestPolicyProfileShape:
    def test_a_fully_tuned_profile_echoes_every_threshold_it_was_given(self, api):
        """All thirteen tunable thresholds come back exactly as the office set them.

        PRD §2.9: "Thresholds the compliance office is allowed to tune live on a **policy
        profile**, one per carrier, pinned to each booking so that a change of policy never
        retroactively rewrites an itinerary already in flight."

        PRD §2.9: "Both start at 0, and the profile's `version` starts at 1 and advances
        whenever either counter's value changes — which is precisely why report creation is
        guarded by a version check (§2.6)."

        Design: Corner/entities/policy_profile_creation_returns_every_declared_field
        """
        created = validate_success(
            api.create_policy_profile(
                f.policy_profile_payload("ZQ", **_TUNED_THRESHOLDS), ADMIN_HEADERS
            ),
            201,
        )

        assert created["carrier_code"] == "ZQ"
        for field, expected in _TUNED_THRESHOLDS.items():
            assert created[field] == expected, (
                f"expected {field} == {expected}, got {created[field]}"
            )
        assert created["report_count"] == 0
        assert created["open_violation_count"] == 0
        assert_common_fields(created, expected_version=1)

    def test_omitting_every_optional_field_takes_the_regulatory_defaults(self, api):
        """A bare carrier code is enough; the statute supplies the rest.

        PRD §2.9: "Every remaining configuration field is optional at creation and takes a
        regulatory default when omitted: `domestic_significant_delay_minutes` defaults to
        180 (three hours) and `international_significant_delay_minutes` to 360 (six hours);
        `credit_card_refund_deadline_days` defaults to 7 and
        `other_method_refund_deadline_days` to 20; `bag_delay_threshold_hours_domestic`
        defaults to 12 and `bag_delay_threshold_hours_international` to 30;
        `tarmac_deplane_deadline_minutes_domestic` defaults to 180 and
        `tarmac_deplane_deadline_minutes_international` to 240 (three and four hours
        respectively); `complaint_ack_deadline_days` defaults to 30,
        `complaint_answer_deadline_days_general` to 60 and
        `complaint_answer_deadline_days_disability` to 30;
        `travel_credit_default_permitted` defaults to false; and
        `travel_credit_election_bonus_pct` defaults to 0.10."

        Design: Corner/entities/policy_profile_defaults_applied_when_every_optional_field_omitted
        """
        created = validate_success(
            api.create_policy_profile(f.policy_profile_payload("ZQ"), ADMIN_HEADERS), 201
        )

        for field, expected in _REGULATORY_DEFAULTS.items():
            assert created[field] == expected, (
                f"expected the default {field} == {expected}, got {created[field]}"
            )
        assert created["travel_credit_default_permitted"] is False
        assert created["travel_credit_election_bonus_pct"] == 0.10

    def test_a_carrier_code_of_three_characters_is_malformed(self, api):
        """The locator format rules run at request-shape time, before anything is stored.

        PRD §2.5: "Format rules apply here too: `carrier_code` is exactly two uppercase
        alphanumeric characters, `record_locator` is exactly six uppercase alphanumeric
        characters, `tag_number` is exactly ten characters, `sequence_index` is at least 1,
        `origin_iata` and `destination_iata` are each exactly three uppercase letters,
        `flight_number` is between 3 and 7 characters, `email` must be syntactically valid
        and contain an at-sign, `full_name` is between 1 and 120 characters, and a complaint
        `summary` is between 1 and 500 characters."

        Design: Corner/entities/policy_profile_carrier_code_wrong_length_rejected
        """
        refused = api.create_policy_profile(
            f.policy_profile_payload("ZQX"), ADMIN_HEADERS
        )

        validate_error(refused, ERR_INVALID_REQUEST, 400)

    def test_supplying_the_computed_report_count_is_an_unknown_field(self, api):
        """A counter the sweep and report-open own cannot be dictated by the client.

        PRD §2.9: "`report_count` increases by 1 each time a regulator report is opened
        against the profile, and `open_violation_count` is rewritten by the compliance sweep
        (§3.9)."

        PRD §2.5: "**Request shape** — the body must carry every required field for the
        endpoint, must carry no unknown fields, must use the correct JSON type for each
        field, must keep every enum-typed value inside its declared value set, must express
        cent amounts as non-negative integers, and must express every timestamp as an ISO
        8601 UTC instant."

        Design: Corner/entities/policy_profile_computed_report_count_in_payload_rejected
        """
        refused = api.create_policy_profile(
            f.policy_profile_payload("ZQ", report_count=7), ADMIN_HEADERS
        )

        validate_error(refused, ERR_INVALID_REQUEST, 400)
        clean = create_policy_profile(api, "ZQ")
        assert clean["report_count"] == 0, "the refused create left nothing behind"


# ─── Passenger shape ──────────────────────────────────


class TestPassengerShape:
    def test_a_registration_without_the_accommodation_flag_defaults_it_to_false(self, api):
        """Only email and full name are required; the flag and both counters start clean.

        PRD §3.1: "Registering a passenger records an `email`, which doubles as the natural
        key and must be unique across all passengers — a second registration of the same
        address is rejected with `ERR_DUPLICATE_PASSENGER_EMAIL` — a `full_name` as printed
        on the ticket, and optionally `requires_disability_assistance`, which defaults to
        false and marks the traveller as having requested accommodation on file."

        PRD §3.1: "A newly registered passenger starts with `travel_credit_balance_cents` at
        0 and `open_complaint_count` at 0; the latter is maintained as the count of that
        passenger's complaints, across all of their bookings, whose status is `RECEIVED`,
        `ACKNOWLEDGED` or `INFO_REQUESTED`."

        Design: Corner/entities/passenger_default_requires_disability_assistance_is_false
        """
        created = validate_success(
            api.create_passenger(
                f.passenger_payload("pat@example.com", "Pat Rivera"), OFFICER_HEADERS
            ),
            201,
        )

        assert created["email"] == "pat@example.com"
        assert created["full_name"] == "Pat Rivera"
        assert created["requires_disability_assistance"] is False
        assert_cents(created["travel_credit_balance_cents"], 0, "travel_credit_balance_cents")
        assert created["open_complaint_count"] == 0
        assert_common_fields(created, expected_version=1)

    def test_the_read_only_auditor_can_retrieve_the_stored_passenger_row(self, api):
        """The accommodation flag and both counters read back as registered.

        PRD §2.1: "A `RegulatorAuditor` is strictly read-only across the entire surface,
        including filed reports and the complaint activity log, and holds no write capability
        of any kind."

        PRD §2.4: "Every resource is identified by an `id`, which is a server-minted UUID
        carrying no type prefix; clients never supply an `id` for a resource they are
        creating."

        Design: Corner/entities/passenger_retrieval_returns_stored_row
        """
        registered = create_passenger(
            api, "dana@example.com", "Dana Okoye", requires_disability_assistance=True
        )

        fetched = validate_success(
            api.get_passenger(registered["id"], AUDITOR_HEADERS)
        )

        assert fetched["id"] == registered["id"]
        assert fetched["email"] == "dana@example.com"
        assert fetched["full_name"] == "Dana Okoye"
        assert fetched["requires_disability_assistance"] is True
        assert_cents(fetched["travel_credit_balance_cents"], 0, "travel_credit_balance_cents")
        assert fetched["open_complaint_count"] == 0
        assert_common_fields(fetched, expected_version=1)

    def test_an_unknown_passenger_id_answers_with_the_passenger_specific_code(self, api):
        """Each entity resolves its own 404 code rather than a generic one.

        PRD §2.5: "**Path existence** — every id embedded in the request path must resolve
        to a stored row, and path ids are resolved strictly left to right, so the outer
        segment's 404 wins over the inner one's. Each entity has its own code: a policy
        profile yields `ERR_POLICY_PROFILE_NOT_FOUND`, a passenger `ERR_PASSENGER_NOT_FOUND`,
        a booking `ERR_BOOKING_NOT_FOUND`, a flight segment `ERR_FLIGHT_SEGMENT_NOT_FOUND`,
        an ancillary purchase `ERR_ANCILLARY_PURCHASE_NOT_FOUND`, a checked bag
        `ERR_CHECKED_BAG_NOT_FOUND`, a denied boarding record
        `ERR_DENIED_BOARDING_RECORD_NOT_FOUND`, a tarmac delay event
        `ERR_TARMAC_DELAY_EVENT_NOT_FOUND`, a refund obligation
        `ERR_REFUND_OBLIGATION_NOT_FOUND`, a consumer complaint
        `ERR_CONSUMER_COMPLAINT_NOT_FOUND`, and a regulator report
        `ERR_REGULATOR_REPORT_NOT_FOUND`."

        Design: Corner/entities/passenger_not_found_returns_passenger_specific_404
        """
        refused = api.get_passenger("pax_missing_0001", ADMIN_HEADERS)

        validate_error(refused, ERR_PASSENGER_NOT_FOUND, 404)


# ─── Booking shape, ledger seeding and listing ────────


class TestBookingShape:
    def test_a_fresh_booking_seeds_every_derived_ledger_field(self, api):
        """Collected money mirrors the fare; nothing is owed and nothing is suppressed.

        PRD §3.1: "A fresh booking begins with `itinerary_scope` reading `DOMESTIC`,
        `collected_total_cents` equal to its `total_fare_cents`,
        `total_refund_obligated_cents` at 0, `earliest_refund_deadline_utc` null,
        `disruption_posture` reading `NORMAL`, `segment_count` and `unused_segment_count` at
        0, `travel_commenced` false and `suppressed_obligation_count` at 0."

        Design: Corner/entities/booking_computed_ledger_fields_seeded_at_creation
        """
        profile = create_policy_profile(api, "ZQ")
        passenger = create_passenger(api, "pat@example.com", "Pat Rivera")

        booking = validate_success(
            api.create_booking(
                f.booking_payload(
                    passenger["id"], profile["id"], "ABC123", 90000, "CREDIT_CARD"
                ),
                OFFICER_HEADERS,
            ),
            201,
        )

        assert_booking_ledger(
            booking,
            itinerary_scope="DOMESTIC",
            collected_total_cents=90000,
            total_refund_obligated_cents=0,
            earliest_refund_deadline_utc=None,
            disruption_posture="NORMAL",
            segment_count=0,
            unused_segment_count=0,
            travel_commenced=False,
            suppressed_obligation_count=0,
            version=1,
        )
        assert_common_fields(booking, expected_version=1)

    def test_a_booking_without_a_record_locator_is_malformed(self, api):
        """The six-character locator is a required field, not an optional one.

        PRD §3.1: "It carries a `record_locator` — a six-character locator, unique across
        all bookings, with a collision rejected as `ERR_DUPLICATE_RECORD_LOCATOR` — a
        `total_fare_cents` of at least 1 representing the fare actually collected for the
        whole itinerary excluding ancillaries and bag fees, and a `payment_method` drawn from
        `CREDIT_CARD`, `CASH_OR_CHECK`, `TRAVEL_CREDIT` and `MILES`."

        Design: Corner/entities/booking_creation_missing_record_locator_returns_invalid_request
        """
        profile = create_policy_profile(api, "ZQ")
        passenger = create_passenger(api, "pat@example.com", "Pat Rivera")

        refused = api.create_booking(
            f.booking_payload(
                passenger["id"], profile["id"], record_locator=None
            ),
            OFFICER_HEADERS,
        )

        validate_error(refused, ERR_INVALID_REQUEST, 400)
        _, meta = validate_paginated(
            api.list_bookings(OFFICER_HEADERS, passenger_id=passenger["id"])
        )
        assert meta["total_count"] == 0, "a refused create must not persist a booking"

    def test_a_payment_method_outside_the_declared_set_is_malformed(self, api):
        """Only the four named instruments are payment methods.

        PRD §2.5: "**Request shape** — the body must carry every required field for the
        endpoint, must carry no unknown fields, must use the correct JSON type for each
        field, must keep every enum-typed value inside its declared value set, must express
        cent amounts as non-negative integers, and must express every timestamp as an ISO
        8601 UTC instant."

        Design: Corner/entities/booking_payment_method_outside_enum_rejected
        """
        profile = create_policy_profile(api, "ZQ")
        passenger = create_passenger(api, "pat@example.com", "Pat Rivera")

        refused = api.create_booking(
            f.booking_payload(
                passenger["id"], profile["id"], "ABC123", 50000, "VOUCHER"
            ),
            OFFICER_HEADERS,
        )

        validate_error(refused, ERR_INVALID_REQUEST, 400)

    def test_an_unknown_booking_id_answers_with_the_booking_specific_code(self, api):
        """The booking read resolves its own 404, distinct from every other entity's.

        PRD §2.5: "Each entity has its own code: a policy profile yields
        `ERR_POLICY_PROFILE_NOT_FOUND`, a passenger `ERR_PASSENGER_NOT_FOUND`, a booking
        `ERR_BOOKING_NOT_FOUND`, a flight segment `ERR_FLIGHT_SEGMENT_NOT_FOUND`, an
        ancillary purchase `ERR_ANCILLARY_PURCHASE_NOT_FOUND`, a checked bag
        `ERR_CHECKED_BAG_NOT_FOUND`, a denied boarding record
        `ERR_DENIED_BOARDING_RECORD_NOT_FOUND`, a tarmac delay event
        `ERR_TARMAC_DELAY_EVENT_NOT_FOUND`, a refund obligation
        `ERR_REFUND_OBLIGATION_NOT_FOUND`, a consumer complaint
        `ERR_CONSUMER_COMPLAINT_NOT_FOUND`, and a regulator report
        `ERR_REGULATOR_REPORT_NOT_FOUND`."

        Design: Corner/entities/booking_not_found_returns_booking_specific_404
        """
        refused = api.get_booking("bk_missing_0001", OFFICER_HEADERS)

        validate_error(refused, ERR_BOOKING_NOT_FOUND, 404)

    def test_paging_three_bookings_two_at_a_time_reports_the_unwindowed_total(self, api):
        """total_count counts the filtered rows; has_more looks past the window.

        PRD §2.3: "The four pagination fields — `limit`, `offset`, `total_count` and
        `has_more` — appear in the `meta` object of every list response, where `total_count`
        is the number of rows matching the filters before the page window is applied and
        `has_more` indicates whether rows remain beyond the current window."

        PRD §2.3: "Filter query parameters, where an endpoint offers them, narrow the result
        set before pagination is applied. Bookings may be filtered by `passenger_id`,
        `policy_profile_id` and `disruption_posture`."

        Design: Corner/entities/booking_listing_paginated_reports_total_count_and_has_more
        """
        profile = create_policy_profile(api, "ZQ")
        passenger = create_passenger(api, "pat@example.com", "Pat Rivera")
        created = [
            create_booking(api, passenger["id"], profile["id"], "AAA111", 10000,
                           "CREDIT_CARD"),
            create_booking(api, passenger["id"], profile["id"], "BBB222", 20000,
                           "CASH_OR_CHECK"),
            create_booking(api, passenger["id"], profile["id"], "CCC333", 30000, "MILES"),
        ]

        first_page, first_meta = validate_paginated(
            api.list_bookings(
                OFFICER_HEADERS, passenger_id=passenger["id"], limit=2, offset=0
            )
        )
        second_page, second_meta = validate_paginated(
            api.list_bookings(
                OFFICER_HEADERS, passenger_id=passenger["id"], limit=2, offset=2
            )
        )

        assert len(first_page) == 2
        assert_list_meta(first_meta, total_count=3, has_more=True)
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert len(second_page) == 1
        assert_list_meta(second_meta, total_count=3, has_more=False)
        assert {row["id"] for row in first_page + second_page} == {
            row["id"] for row in created
        }, "the two windows together must cover every booking exactly once"


# ─── Flight segment shape ─────────────────────────────


class TestFlightSegmentShape:
    def test_a_new_leg_mints_its_system_fields_and_refreshes_its_booking(self, api):
        """The leg starts undisrupted and the booking's counters pick it up at once.

        PRD §3.1: "A newly added leg's `booking_id` is the booking it was added under, its
        `status` reads `SCHEDULED`, its `disruption_type` reads `NONE`, its `delay_minutes`
        is 0, its `is_significant_delay` is false, and its `cumulative_tarmac_minutes` and
        `exempted_tarmac_event_count` are both 0."

        PRD §3.1: "Adding a leg immediately refreshes the booking's `segment_count`,
        `unused_segment_count` and `itinerary_scope` — one international leg makes the whole
        itinerary international — and advances the booking's `version` by 1."

        Design: Corner/entities/flight_segment_system_fields_minted_at_creation
        """
        profile = create_policy_profile(api, "ZQ")
        passenger = create_passenger(api, "pat@example.com", "Pat Rivera")
        booking = create_booking(
            api, passenger["id"], profile["id"], "ABC123", 90000, "CREDIT_CARD"
        )

        segment = validate_success(
            api.create_flight_segment(
                booking["id"],
                f.flight_segment_payload(
                    sequence_index=1,
                    flight_number="ZQ410",
                    origin_iata="ORD",
                    destination_iata="DFW",
                    scheduled_departure_utc="2026-08-10T12:00:00Z",
                    scheduled_arrival_utc="2026-08-10T14:00:00Z",
                    segment_fare_cents=30000,
                ),
                OPS_HEADERS,
            ),
            201,
        )

        assert segment["booking_id"] == booking["id"]
        assert_common_fields(segment, expected_version=1)
        assert_segment_state(
            segment,
            status="SCHEDULED",
            disruption_type="NONE",
            delay_minutes=0,
            is_significant_delay=False,
            cumulative_tarmac_minutes=0,
            exempted_tarmac_event_count=0,
        )
        assert_booking_ledger(
            read_booking(api, booking["id"]),
            segment_count=1,
            unused_segment_count=1,
            itinerary_scope="DOMESTIC",
            version=2,
        )

    def test_a_sequence_index_of_zero_is_malformed(self, api):
        """Travel order starts at 1, so index 0 never reaches the itinerary.

        PRD §3.1: "Legs are added to the booking one at a time, each at an explicit
        `sequence_index` that is at least 1 and unique within the booking — a repeat index is
        rejected with `ERR_DUPLICATE_SEQUENCE_INDEX`."

        Design: Corner/entities/flight_segment_sequence_index_zero_rejected
        """
        profile = create_policy_profile(api, "ZQ")
        passenger = create_passenger(api, "pat@example.com", "Pat Rivera")
        booking = create_booking(
            api, passenger["id"], profile["id"], "ABC123", 50000, "CREDIT_CARD"
        )

        refused = api.create_flight_segment(
            booking["id"], f.flight_segment_payload(sequence_index=0), OPS_HEADERS
        )

        validate_error(refused, ERR_INVALID_REQUEST, 400)
        assert_booking_ledger(
            read_booking(api, booking["id"]), segment_count=0, version=1
        )

    def test_adding_a_leg_under_an_unknown_booking_resolves_the_path_first(self, api):
        """The path id is checked before the body is looked at at all.

        PRD §2.5: "**Path existence** — every id embedded in the request path must resolve
        to a stored row, and path ids are resolved strictly left to right, so the outer
        segment's 404 wins over the inner one's."

        Design: Corner/entities/flight_segment_creation_under_unknown_booking_returns_not_found
        """
        refused = api.create_flight_segment(
            "bk_missing_0001", f.flight_segment_payload(sequence_index=1), OPS_HEADERS
        )

        validate_error(refused, ERR_BOOKING_NOT_FOUND, 404)


# ─── Checked bag shape ────────────────────────────────


class TestCheckedBagShape:
    def test_a_new_bag_starts_in_transit_and_raises_the_collected_total(self, api):
        """The bag fee joins the collected-money side of the ledger immediately.

        PRD §3.3: "A new bag begins with `status` reading `IN_TRANSIT`,
        `delivery_delay_hours` at 0 and `fee_refund_obligated` false; recording it refreshes
        the booking's `collected_total_cents` and advances the booking's `version` by 1."

        Design: Corner/entities/checked_bag_creation_starts_in_transit_and_raises_collected_total
        """
        profile = create_policy_profile(api, "ZQ")
        passenger = create_passenger(api, "pat@example.com", "Pat Rivera")
        booking = create_booking(
            api, passenger["id"], profile["id"], "ABC123", 50000, "CREDIT_CARD"
        )

        bag = add_checked_bag(
            api,
            booking["id"],
            "BAG0000001",
            4500,
            "2026-08-10T13:00:00Z",
            "2026-08-10T21:00:00Z",
        )

        stored = read_bag(api, bag["id"], booking["id"])
        assert stored["status"] == "IN_TRANSIT"
        assert_hours(stored["delivery_delay_hours"], 0.0)
        assert stored["fee_refund_obligated"] is False
        assert_null(stored["delivered_at_utc"], "delivered_at_utc")
        assert_null(stored["loss_declared_at_utc"], "loss_declared_at_utc")
        assert_booking_ledger(
            read_booking(api, booking["id"]),
            collected_total_cents=54500,
            total_refund_obligated_cents=0,
            version=2,
        )

    def test_a_tag_number_shorter_than_ten_characters_is_malformed(self, api):
        """The bag tag is a fixed-width natural key, and the money stays untouched.

        PRD §3.3: "A bag records its `booking_id`, a `tag_number` of exactly ten characters
        that must be unique across all bags — a collision is `ERR_DUPLICATE_TAG_NUMBER` — a
        `fee_cents` of at least 0 representing the fee collected from the passenger, the
        `checked_at_utc` instant the bag was accepted at the counter, and a
        `scheduled_delivery_utc` that must be strictly after the check-in instant and
        represents the contractual delivery moment, normally the published arrival of the
        final leg."

        Design: Corner/entities/checked_bag_tag_number_wrong_length_rejected
        """
        profile = create_policy_profile(api, "ZQ")
        passenger = create_passenger(api, "pat@example.com", "Pat Rivera")
        booking = create_booking(
            api, passenger["id"], profile["id"], "ABC123", 50000, "CREDIT_CARD"
        )

        refused = api.create_checked_bag(
            f.checked_bag_payload(
                booking["id"],
                "BAG001",
                4500,
                "2026-08-10T13:00:00Z",
                "2026-08-10T21:00:00Z",
            ),
            OFFICER_HEADERS,
        )

        validate_error(refused, ERR_INVALID_REQUEST, 400)
        assert_booking_ledger(
            read_booking(api, booking["id"]), collected_total_cents=50000
        )


# ─── Ancillary purchase referential integrity ─────────


class TestAncillaryPurchaseReferences:
    def test_naming_an_unknown_leg_in_the_body_answers_the_segment_404(self, api):
        """Body foreign keys are resolved before the charge touches the ledger.

        PRD §2.5: "**Body reference existence** — every foreign-key id supplied in the
        request body must resolve to a stored row, checked in the order the fields are listed
        for that endpoint, using the same per-entity codes as the previous step."

        PRD §3.3: "A new purchase begins with `delivery_status` reading `PENDING_DELIVERY`
        and `refund_obligation_created` false, and recording it refreshes the booking's
        `collected_total_cents` and advances the booking's `version` by 1 — the charge enters
        the collected-money side of the ledger the moment it is recorded, whether or not the
        service is ever rendered."

        Design: Corner/entities/ancillary_purchase_unknown_flight_segment_fk_returns_not_found
        """
        profile = create_policy_profile(api, "ZQ")
        passenger = create_passenger(api, "pat@example.com", "Pat Rivera")
        booking = create_booking(
            api, passenger["id"], profile["id"], "ABC123", 50000, "CREDIT_CARD"
        )
        validate_success(
            api.create_flight_segment(
                booking["id"], f.flight_segment_payload(sequence_index=1), OPS_HEADERS
            ),
            201,
        )

        refused = api.create_ancillary_purchase(
            f.ancillary_payload(booking["id"], "seg_missing_0001", "WIFI", 1900),
            OFFICER_HEADERS,
        )

        validate_error(refused, ERR_FLIGHT_SEGMENT_NOT_FOUND, 404)
        assert_booking_ledger(
            read_booking(api, booking["id"]), collected_total_cents=50000
        )


# ─── The immutable complaint activity trail ───────────


class TestComplaintActivityImmutability:
    def test_an_activity_row_carries_no_version_and_no_updated_at(self, api):
        """Filing appends one row, and that row can never be rewritten.

        PRD §2.4: "The complaint activity trail is append-only and immutable: an activity
        row carries only `id` and `created_at` — it has neither `updated_at` nor `version`,
        because nothing ever modifies it."

        PRD §3.8: "Each row names its `complaint_id`, an `activity_type` — `RECEIVED`,
        `ACKNOWLEDGED`, `INFO_REQUESTED`, `ANSWERED`, `REOPENED`, `AUTO_CLOSED`, or
        `DEADLINE_BREACH_FLAGGED` reserved for a sweep-recorded deadline breach — the
        `occurred_at_utc` domain instant of the event taken from the triggering payload
        timestamp, or from the logical clock for rows the sweep generates, the `actor_role` of
        the caller (recorded as the literal `system` for sweep-generated rows), the
        `actor_user_id` of the caller (null for sweep-generated rows), and a short
        machine-readable `detail` such as the disposition, the reopen reason, or the name of
        the breached deadline field."

        Design: Corner/entities/complaint_activity_rows_are_immutable_with_no_version_field
        """
        profile = create_policy_profile(api, "ZQ")
        passenger = create_passenger(api, "pat@example.com", "Pat Rivera")
        booking = create_booking(
            api, passenger["id"], profile["id"], "ABC123", 50000, "CREDIT_CARD"
        )
        passenger_headers = make_passenger_headers(passenger["id"])
        complaint = file_complaint(
            api,
            booking["id"],
            headers=passenger_headers,
            category="REFUND",
            channel="WEB",
            received_at_utc="2026-08-05T09:00:00Z",
            summary="No refund received for my cancelled leg.",
        )

        rows = list_activities(api, complaint["id"])

        assert_activity_types(rows, ["RECEIVED"])
        row = rows[0]
        assert row["complaint_id"] == complaint["id"]
        assert_instant(row["occurred_at_utc"], "2026-08-05T09:00:00Z")
        assert row["actor_role"] == "Passenger"
        assert row["actor_user_id"] == passenger["id"]
        assert_no_version_fields(row)


# ─── Refund obligation listing filters ────────────────


class TestRefundObligationListingFilters:
    def test_filtering_by_basis_and_by_settlement_status_narrows_the_same_two_rows(
        self, api
    ):
        """A late bag and an unprovided service leave one row per basis, both unsettled.

        PRD §2.3: "Refund obligations may be filtered by `booking_id`, by any of the four
        source references `flight_segment_id`, `checked_bag_id`, `ancillary_purchase_id` and
        `denied_boarding_record_id`, and by `basis`, `issuance_mode`, `election_status` and
        `settlement_status`."

        PRD §3.3: "The comparison is at-or-above, so a bag delivered exactly 12.00 hours
        late on a default domestic itinerary is late."

        Design: Corner/entities/refund_obligation_listing_filtered_by_basis_and_settlement_status
        """
        profile = create_policy_profile(api, "ZQ")
        passenger = create_passenger(api, "pat@example.com", "Pat Rivera")
        booking = create_booking(
            api, passenger["id"], profile["id"], "ABC123", 50000, "CREDIT_CARD"
        )
        segment = validate_success(
            api.create_flight_segment(
                booking["id"],
                f.flight_segment_payload(sequence_index=1, segment_fare_cents=50000),
                OPS_HEADERS,
            ),
            201,
        )
        bag = add_checked_bag(
            api,
            booking["id"],
            "BAG0000001",
            4500,
            "2026-08-10T13:00:00Z",
            "2026-08-10T21:00:00Z",
        )
        purchase = add_ancillary(api, booking["id"], segment["id"], "WIFI", 3000)
        validate_success(
            api.resolve_checked_bag(
                bag["id"], f.bag_delivered_payload("2026-08-11T09:00:00Z"), OFFICER_HEADERS
            )
        )
        validate_success(
            api.mark_ancillary_not_provided(
                purchase["id"],
                f.not_provided_payload("SYSTEM_OUTAGE", "2026-08-09T08:00:00Z"),
                OFFICER_HEADERS,
            )
        )

        ancillary_rows, ancillary_meta = obligations_with_meta(
            api, booking["id"], basis="ANCILLARY"
        )
        unsettled_rows, unsettled_meta = obligations_with_meta(
            api, booking["id"], settlement_status="UNSETTLED"
        )

        assert_list_meta(ancillary_meta, total_count=1, has_more=False)
        assert_cents(ancillary_rows[0]["amount_cents"], 3000)
        assert ancillary_rows[0]["ancillary_purchase_id"] == purchase["id"]
        assert_list_meta(unsettled_meta, total_count=2, has_more=False)
        assert {row["amount_cents"] for row in unsettled_rows} == {3000, 4500}
        assert_booking_ledger(
            read_booking(api, booking["id"]),
            collected_total_cents=57500,
            total_refund_obligated_cents=7500,
        )


# ─── Regulator report listing filters ─────────────────


class TestRegulatorReportListingFilters:
    def test_a_freshly_opened_report_lists_under_its_profile_filtered_to_draft(self, api):
        """The draft carries zeroed metrics and an unpinned policy version.

        PRD §3.9: "A new report opens in `DRAFT` with all seven metrics at 0,
        `policy_version_pinned` at 0 and `amendment_count` at 0; opening it also increases the
        profile's `report_count` and advances the profile's `version` by 1, which is why two
        reports cannot be opened back to back against one stale profile version."

        PRD §2.3: "A policy profile's report list accepts `status`."

        Design: Corner/entities/regulator_report_listing_under_policy_profile_filtered_by_status
        """
        profile = create_policy_profile(api, "ZQ")
        report = open_report(
            api, profile["id"], "2026-07-01T00:00:00Z", "2026-07-31T23:59:59Z"
        )

        rows, meta = validate_paginated(
            api.list_policy_profile_reports(
                profile["id"], AUDITOR_HEADERS, status="DRAFT", limit=10, offset=0
            )
        )

        assert_list_meta(meta, total_count=1, has_more=False)
        listed = rows[0]
        assert listed["id"] == report["id"]
        assert listed["status"] == "DRAFT"
        assert listed["complaint_count"] == 0
        assert_cents(
            listed["refund_obligation_cents_total"], 0, "refund_obligation_cents_total"
        )
        assert listed["policy_version_pinned"] == 0
        assert listed["amendment_count"] == 0
        stored_profile = read_profile(api, profile["id"])
        assert stored_profile["report_count"] == 1
        assert stored_profile["version"] == 2
