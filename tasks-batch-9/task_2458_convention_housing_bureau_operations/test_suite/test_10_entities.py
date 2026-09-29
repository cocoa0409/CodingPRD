"""Entity-level contracts: derived fields on creation, defaults, ignored client
input for server-owned fields, malformed payloads, and the carve graph."""

from test_helpers import (
    COORDINATOR,
    NON_EXISTENT_UUID,
    assemble_block,
    assert_no_version_field,
    carve_sub_block,
    carve_sub_block_payload,
    create_attendee_payload,
    create_event_payload,
    create_hotel_block_payload,
    create_hotel_payload,
    create_reservation_payload,
    file_pickup_report,
    import_attendee,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_attendee_headers,
    read_block,
    register_event,
    register_hotel,
    setup_contracted_block,
    setup_open_block,
    validate_error,
    validate_paginated,
    validate_success,
)

WINTER_EXPO = {
    "name": "Winter Expo",
    "code": "WEX26",
    "event_start_date": "2026-11-10",
    "event_end_date": "2026-11-13",
    "cutoff_date": "2026-10-15",
    "attrition_deadline_date": "2026-10-01",
}
RIVERSIDE_INN = {
    "name": "Riverside Inn",
    "distance_to_venue_miles": 1.2,
    "room_tax_pct": 0.12,
    "total_rooms": 150,
}


class TestEventCreation:
    def test_registration_derives_the_night_count_and_zeroes_the_aggregates(self, api):
        """PRD §3.1: "Upon registration the server derives `night_count` from the
        housing window, sets `housing_posture` to `PLANNING`, and initialises three
        running aggregates to zero."
        PRD §2.6: "The event's own `night_count` is derived the same way: it is the
        number of whole days from `event_start_date` to `event_end_date`, and it is
        the number of billable nights in the official housing window."

        Design: Corner/entities/event_creation_returns_computed_night_count_and_planning_posture
        """
        response = api.create_event(create_event_payload(), COORDINATOR)
        event = validate_success(response, 201)

        assert event["night_count"] == 4
        assert event["housing_posture"] == "PLANNING"
        assert event["total_confirmed_room_nights"] == 0
        assert event["total_contracted_room_nights"] == 0
        assert event["commission_collected_cents"] == 0
        assert is_valid_uuid(event["id"])
        assert is_iso8601_timestamp(event["created_at"])


class TestHotelRetrieval:
    def test_reading_a_hotel_returns_exactly_what_was_stored(self, api):
        """PRD §3.1: "Each `Hotel` records a `name`, a `distance_to_venue_miles` of
        at least zero — this is the ranking key of the attendee-facing property
        list, which is returned ordered by that distance ascending and then by
        `name` ascending — a `room_tax_pct` that is at least zero and strictly less
        than one, representing the combined occupancy and city tax charged on top
        of the negotiated rate, and a `total_rooms` count of at least one
        describing the physical inventory of the property."

        Design: Corner/entities/hotel_retrieval_returns_stored_fields
        """
        hotel = register_hotel()

        fetched = validate_success(api.get_hotel(hotel["id"], COORDINATOR))
        assert fetched["id"] == hotel["id"]
        assert fetched["name"] == "Grand Plaza"
        assert fetched["distance_to_venue_miles"] == 0.3
        assert fetched["room_tax_pct"] == 0.1475
        assert fetched["total_rooms"] == 400


class TestHotelBlockListing:
    def test_block_list_honours_the_event_and_status_filters_together(self, api):
        """PRD §3.2: "Blocks can be listed and filtered by `event_id`, `hotel_id`
        and `status`."
        PRD §2.3: "`total_count` is the number of items matching the filters before
        pagination is applied, and `has_more` is true exactly when items remain
        beyond the current window."

        Design: Corner/entities/hotel_block_listing_filters_by_event_and_status
        """
        first_event = register_event()
        second_event = register_event(**WINTER_EXPO)
        hotel_a = register_hotel()
        hotel_b = register_hotel(**RIVERSIDE_INN)

        block_1 = assemble_block(first_event["id"], hotel_a["id"])
        block_2 = assemble_block(
            first_event["id"], hotel_b["id"], contracted_rooms_per_night=5
        )
        block_3 = assemble_block(
            second_event["id"], hotel_a["id"], cutoff_date="2026-10-15"
        )

        rows, meta = validate_paginated(
            api.list_hotel_blocks(
                COORDINATOR, params={"event_id": first_event["id"], "status": "DRAFT"}
            )
        )
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        listed = {row["id"] for row in rows}
        assert listed == {block_1["id"], block_2["id"]}
        assert block_3["id"] not in listed


class TestReservationNotFound:
    def test_unknown_reservation_id_is_a_404_not_an_empty_body(self, api):
        """PRD §2.10: "The first unresolvable identifier decides the error:
        `ERR_EVENT_NOT_FOUND`, `ERR_HOTEL_NOT_FOUND`, `ERR_HOTEL_BLOCK_NOT_FOUND`,
        `ERR_SUB_BLOCK_NOT_FOUND` (for a path sub-block id, a body `sub_block_id`,
        or a body `parent_sub_block_id`), `ERR_ATTENDEE_NOT_FOUND`,
        `ERR_RESERVATION_NOT_FOUND`, `ERR_REDUCTION_NOT_FOUND`,
        `ERR_VENDOR_NOT_FOUND`, or `ERR_INVOICE_NOT_FOUND` — all 404."

        Design: Corner/entities/reservation_get_with_unknown_id_not_found
        """
        response = api.get_reservation(NON_EXISTENT_UUID, COORDINATOR)
        validate_error(response, "ERR_RESERVATION_NOT_FOUND", 404)

        body = response.json()
        assert body["response_type"] == "error"
        assert "message" in body["data"]


class TestHotelBlockRequiredFields:
    def test_block_assembly_without_commission_pct_persists_nothing(self, api):
        """PRD §2.10: "Every required field present; every enum value inside its
        declared set; constrained integers non-negative; `check_out_date` strictly
        later than `check_in_date`; `occupants` between 1 and 4 inclusive; `limit`
        between 1 and 100 inclusive; `offset` at least 0; and `eligibility_code`
        supplied exactly when `segment` is not `GENERAL` and omitted (or null)
        exactly when it is `GENERAL`. Otherwise `ERR_INVALID_REQUEST` (400)."
        PRD §3.2: "The assembly payload names the `event_id` and the `hotel_id`,
        states the `contracted_rooms_per_night` the bureau intends to hold (at
        least one), and proposes the commercial terms: a
        `negotiated_nightly_rate_cents` of at least one cent, pre-tax, which is the
        figure quoted to attendees; a `commission_pct` greater than zero and at
        most 0.25; a `rebate_per_room_night_cents` of at least zero; a
        `cutoff_date`; and a `reduction_rights_pct` between zero and 0.50
        inclusive, expressing the fraction of the originally contracted
        rooms-per-night the bureau may later strike without penalty."

        Design: Corner/entities/hotel_block_missing_required_commission_pct_rejected
        """
        event = register_event()
        hotel = register_hotel()
        payload = create_hotel_block_payload(event["id"], hotel["id"])
        payload.pop("commission_pct")

        validate_error(
            api.create_hotel_block(payload, COORDINATOR), "ERR_INVALID_REQUEST", 400
        )

        _, meta = validate_paginated(
            api.list_hotel_blocks(COORDINATOR, params={"event_id": event["id"]})
        )
        assert meta["total_count"] == 0


class TestHotelStandingDefault:
    def test_standing_defaults_to_active_when_the_payload_omits_it(self, api):
        """PRD §3.1: "The property's bureau `standing` is an enum with the values
        `ACTIVE` and `SUSPENDED`; it may be supplied at registration and defaults to
        `ACTIVE`."

        Design: Corner/entities/hotel_standing_defaults_to_active_when_omitted
        """
        payload = create_hotel_payload()
        assert "standing" not in payload

        hotel = validate_success(api.create_hotel(payload, COORDINATOR), 201)
        assert hotel["standing"] == "ACTIVE"
        assert hotel["version"] == 1


class TestReservationComputedFields:
    def test_client_supplied_charge_figures_are_ignored_in_favour_of_the_formula(
        self, api
    ):
        """PRD §3.4: "The commercial terms are then **snapshotted and frozen**:
        `quoted_nightly_rate_cents` copies the block's current
        `negotiated_nightly_rate_cents` and `room_tax_pct_snapshot` copies the
        property's current `room_tax_pct`."
        PRD §3.4: "`total_room_charge_cents` is then computed with the rounding
        order pinned: the taxed nightly amount is the `quoted_nightly_rate_cents`
        multiplied by one plus `room_tax_pct_snapshot`, **rounded half up to whole
        cents at that point**, and the stay total is that whole-cent nightly amount
        multiplied by `room_nights`."

        Design: Corner/entities/reservation_computed_charge_fields_input_ignored
        """
        ctx = setup_open_block(general_rooms=6, num_attendees=1)
        guest = ctx["attendees"][0]

        payload = create_reservation_payload(
            ctx["sub_block"]["id"],
            guest["id"],
            total_room_charge_cents=1,
            quoted_nightly_rate_cents=100,
        )
        reservation = validate_success(
            api.create_reservation(payload, make_attendee_headers(guest["id"])), 201
        )

        assert reservation["quoted_nightly_rate_cents"] == 21900
        assert reservation["room_tax_pct_snapshot"] == 0.1475
        assert reservation["room_nights"] == 4
        assert reservation["total_room_charge_cents"] == 100520


class TestAttendeeSystemFields:
    def test_supplied_id_and_counters_do_not_survive_the_import(self, api):
        """PRD §3.1: "Three counters start at their zero values and are only ever
        moved by the workflows in §3.5 and §3.8: `warning_count` at 0,
        `housing_risk_flag` at false, and `no_show_strikes` at 0."
        PRD §2.4: "Every resource the API creates carries a server-minted `id`
        formatted as a UUID with no type prefix, and a `created_at` timestamp
        rendered as an ISO 8601 UTC instant with three fractional digits (for
        example `2026-08-01T00:00:00.000Z`)."
        PRD §2.4: "`version` — an integer that starts at 1 on creation and
        increases by exactly 1 on every mutation of the resource, including
        mutations the server performs on its own initiative as part of a cascade."

        Design: Corner/entities/attendee_system_fields_generated_input_ignored
        """
        event = register_event()
        payload = create_attendee_payload(
            event["id"],
            id="00000000-0000-0000-0000-000000000042",
            warning_count=9,
            housing_risk_flag=True,
        )

        attendee = validate_success(api.create_attendee(payload, COORDINATOR), 201)
        assert attendee["id"] != "00000000-0000-0000-0000-000000000042"
        assert is_valid_uuid(attendee["id"])
        assert attendee["warning_count"] == 0
        assert attendee["housing_risk_flag"] is False
        assert attendee["no_show_strikes"] == 0
        assert attendee["version"] == 1
        assert is_iso8601_timestamp(attendee["created_at"])
        assert is_iso8601_timestamp(attendee["updated_at"])


class TestSubBlockSegmentEnum:
    def test_carve_with_a_segment_outside_the_enum_touches_no_inventory(self, api):
        """PRD §3.3: "The carve payload states the `segment`, one of `GENERAL`,
        `VIP`, `STAFF` and `EXHIBITOR`; the `allotted_rooms` to set aside per night,
        at least one on creation; an `eligibility_code` that a delegate must carry
        in order to book there; an optional `parent_sub_block_id`; and the mandatory
        `expected_hotel_block_version` from §2.8."
        PRD §2.10: "Every required field present; every enum value inside its
        declared set; constrained integers non-negative; `check_out_date` strictly
        later than `check_in_date`; `occupants` between 1 and 4 inclusive; `limit`
        between 1 and 100 inclusive; `offset` at least 0; and `eligibility_code`
        supplied exactly when `segment` is not `GENERAL` and omitted (or null)
        exactly when it is `GENERAL`. Otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/sub_block_invalid_segment_enum_rejects_invalid_request
        """
        ctx = setup_contracted_block()
        block = ctx["block"]

        response = api.carve_sub_block(
            block["id"],
            carve_sub_block_payload(
                "PRESS", 2, block["version"], eligibility_code="PRESS-GOLD"
            ),
            COORDINATOR,
        )
        validate_error(response, "ERR_INVALID_REQUEST", 400)

        after = read_block(block["id"])
        assert after["unassigned_rooms_per_night"] == 10
        assert after["version"] == block["version"]


class TestEventDateOrdering:
    def test_end_date_before_start_date_leaves_the_code_free_to_reuse(self, api):
        """PRD §3.1: "The official housing window is delimited by
        `event_start_date` and `event_end_date`, both ISO calendar dates, with the
        end date required to be strictly later than the start date."
        PRD §3.1: "a bureau-facing `code` of between 3 and 16 uppercase characters
        that must be unique across all registered events — a collision is rejected
        with `ERR_EVENT_CODE_DUPLICATE`."

        Design: Corner/entities/event_end_date_before_start_date_rejects_invalid_request
        """
        broken = create_event_payload(
            name="Broken Summit",
            code="BRK26",
            event_start_date="2026-09-14",
            event_end_date="2026-09-10",
        )
        validate_error(
            api.create_event(broken, COORDINATOR), "ERR_INVALID_REQUEST", 400
        )

        # Nothing was persisted, so the same code is still available.
        retry = create_event_payload(name="Broken Summit", code="BRK26")
        event = validate_success(api.create_event(retry, COORDINATOR), 201)
        assert event["code"] == "BRK26"
        assert event["night_count"] == 4


class TestPickupReportImmutability:
    def test_pickup_reports_carry_neither_version_nor_updated_at(self, api):
        """PRD §2.4: "Two record types are append-only ledgers of fact rather than
        mutable resources, and they therefore carry **only** `id` and `created_at`:
        a rooming-list transmission batch and a hotel pickup report. Neither
        `updated_at` nor `version` exists on those two record types at all."
        PRD §3.6: "Reports are append-only and immutable, so like transmissions they
        carry only `id` and `created_at`."

        Design: Corner/entities/pickup_report_is_immutable_and_versionless
        """
        ctx = setup_contracted_block()
        report = file_pickup_report(
            ctx["block"]["id"], ctx["hotel"]["id"], "2026-08-05", 3, 6, 131400
        )

        assert_no_version_field(report)
        assert is_valid_uuid(report["id"])
        assert is_iso8601_timestamp(report["created_at"])

        rows, meta = validate_paginated(
            api.list_pickup_reports(ctx["block"]["id"], COORDINATOR)
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == report["id"]
        assert rows[0]["reported_room_nights"] == 6
        assert_no_version_field(rows[0])


class TestReservationParentResolution:
    def test_booking_into_an_unknown_sub_block_is_a_404(self, api):
        """PRD §2.10: "**Resource existence**, validated left-to-right with path
        identifiers resolved before body identifiers. The first unresolvable
        identifier decides the error: `ERR_EVENT_NOT_FOUND`,
        `ERR_HOTEL_NOT_FOUND`, `ERR_HOTEL_BLOCK_NOT_FOUND`,
        `ERR_SUB_BLOCK_NOT_FOUND` (for a path sub-block id, a body `sub_block_id`,
        or a body `parent_sub_block_id`), `ERR_ATTENDEE_NOT_FOUND`,
        `ERR_RESERVATION_NOT_FOUND`, `ERR_REDUCTION_NOT_FOUND`,
        `ERR_VENDOR_NOT_FOUND`, or `ERR_INVOICE_NOT_FOUND` — all 404."

        Design: Corner/entities/reservation_with_unknown_sub_block_parent_not_found
        """
        event = register_event()
        guest = import_attendee(event["id"])

        response = api.create_reservation(
            create_reservation_payload(NON_EXISTENT_UUID, guest["id"]),
            make_attendee_headers(guest["id"]),
        )
        validate_error(response, "ERR_SUB_BLOCK_NOT_FOUND", 404)

        _, meta = validate_paginated(
            api.list_reservations(COORDINATOR, params={"attendee_id": guest["id"]})
        )
        assert meta["total_count"] == 0


class TestNestedCarveGraph:
    def test_a_nested_carve_draws_from_its_parent_and_is_listable_by_parent(
        self, api
    ):
        """PRD §3.3: "A **nested carve**, with a parent named — the mechanism by
        which a VIP allotment is cut out of the staff allotment — draws from the
        parent sub-block's own allotment and succeeds only when `allotted_rooms` is
        less than or equal to the parent's `available_rooms`."
        PRD §3.3: "on success the rooms are debited from the source:
        `unassigned_rooms_per_night` falls by `allotted_rooms` on a direct carve,
        and the parent's `allotted_rooms` falls by the same amount on a nested
        one."
        PRD §3.3: "Sub-blocks can be listed and filtered by `hotel_block_id`,
        `parent_sub_block_id`, `segment` and `approval_status`."

        Design: Corner/entities/nested_carve_graph_is_navigable_from_parent_sub_block
        """
        ctx = setup_contracted_block()
        general = carve_sub_block(ctx["block"]["id"], "GENERAL", 6)
        assert read_block(ctx["block"]["id"])["unassigned_rooms_per_night"] == 4

        nested = carve_sub_block(
            ctx["block"]["id"],
            "EXHIBITOR",
            2,
            eligibility_code="EXPO-2026",
            parent_sub_block_id=general["id"],
        )
        assert nested["parent_sub_block_id"] == general["id"]
        assert nested["approval_status"] == "PENDING_APPROVAL"

        parent_after = validate_success(api.get_sub_block(general["id"], COORDINATOR))
        assert parent_after["allotted_rooms"] == 4
        # The nested carve took rooms from the parent, not from the block pool.
        assert read_block(ctx["block"]["id"])["unassigned_rooms_per_night"] == 4

        rows, meta = validate_paginated(
            api.list_sub_blocks(
                COORDINATOR, params={"parent_sub_block_id": general["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == nested["id"]
