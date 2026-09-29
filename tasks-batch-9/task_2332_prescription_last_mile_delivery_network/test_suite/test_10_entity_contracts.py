"""What a stored row looks like: echoes, defaults, derivations and refusals.

Each collection declares which fields the client supplies, which the server
derives, and which it refuses to accept at all. These tests read those contracts
back off the wire on creation, on retrieval, and on a paginated list.
"""

import pytest

from test_helpers import (
    CLOCK_EPOCH,
    OPS_HEADERS,
    UNKNOWN_UUID,
    assert_append_only_record,
    assert_grant_ledger,
    assert_instant,
    assert_versioned_entity,
    assert_window_occupancy,
    build_health_plan,
    build_network,
    build_order,
    build_out_for_delivery,
    build_plan_grant,
    build_queued_delivery,
    build_ready_order,
    build_window,
    build_zone,
    factories,
    ids_of,
    make_pharmacy_headers,
    make_plan_admin_headers,
    read_delivery,
    read_order,
    read_window,
    record_attempt,
    redepart,
    reserve_delivery,
    set_clock,
    utc_ts,
    validate_error,
    validate_paginated,
    validate_success,
)

STANDARD_ORDER = {
    "rx_line_count": 1,
    "cold_chain_required": False,
    "controlled_schedule": "NONE",
    "total_rx_value_cents": 1000,
}
COLD_CII_ORDER = {
    "rx_line_count": 2,
    "cold_chain_required": True,
    "controlled_schedule": "CII",
    "total_rx_value_cents": 31000,
}


class TestHealthPlanCreationEcho:
    """"A payer is registered as a **health plan** with a `name` of 1 to 120
    characters, a `payer_type` that is one of `COMMERCIAL`, `MEDICAID`, or
    `MEDICARE_ADVANTAGE`, and a `member_cost_share_pct`"
    """

    def test_registering_a_payer_echoes_the_three_declared_fields(self, api):
        """The three inputs come back unchanged beside a fresh identity block.

        "`version` (integer) — a counter that increments by one on every
        mutation of the row"

        Design: Corner/entities/create_health_plan_returns_all_declared_fields
        """
        plan = validate_success(
            api.create_health_plan(factories.health_plan_payload(), headers=OPS_HEADERS), 201
        )
        assert plan["name"] == "Meridian Health"
        assert plan["payer_type"] == "COMMERCIAL"
        assert plan["member_cost_share_pct"] == pytest.approx(0.10, abs=0.01)

        assert_versioned_entity(plan)
        assert plan["version"] == 1


class TestOrderReadsBackStoredAndDerivedFields:
    """"From those three handling inputs the system derives the proof
    requirements that will follow the bag to the door."
    """

    def test_retrieving_an_order_returns_the_inputs_beside_the_derivations(self, api):
        """A cold CII bag worth 31000 cents, read back field by field.

        "`required_id_verification` is selected by a strictly ordered cascade: a
        `CII` schedule demands `GOVT_ID_SCAN`; failing that, a `CIII` schedule
        demands `PHOTO_ID`; failing that, a `total_rx_value_cents` of at least
        25000 demands `PHOTO_ID`; and everything else, cold bags included, settles
        at `DOB_MATCH`"

        Design: Corner/entities/get_pharmacy_order_returns_stored_and_computed_fields
        """
        net = build_network(api, clock=CLOCK_EPOCH)
        created = build_order(api, net, **COLD_CII_ORDER)

        order = read_order(api, created["id"], headers=net.pharmacy_headers)
        assert order["pharmacy_id"] == net.pharmacy["id"]
        assert order["patient_id"] == net.patient["id"]
        assert order["health_plan_id"] == net.plan["id"]
        assert order["rx_line_count"] == 2
        assert order["cold_chain_required"] is True
        assert order["controlled_schedule"] == "CII"
        assert order["total_rx_value_cents"] == 31000

        assert order["signature_required"] is True
        assert order["required_id_verification"] == "GOVT_ID_SCAN"
        assert order["status"] == "INTAKE"
        assert order["hold_count"] == 0
        assert order["version"] == 1


@pytest.fixture
def three_bags_on_one_window(api):
    """Three reserved deliveries against a single window of capacity 3."""
    net = build_network(api)
    window = build_window(api, net.zone["id"], capacity_slots=3)
    deliveries = []
    for value in (1000, 1100, 1200):
        order = build_ready_order(api, net, **dict(STANDARD_ORDER, total_rx_value_cents=value))
        deliveries.append(reserve_delivery(api, net, order["id"], window["id"]))
    return net, window, deliveries


class TestDeliveryListPagination:
    """"Every list response reports `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."
    """

    def test_two_pages_report_the_same_total_and_opposite_has_more(
        self, api, three_bags_on_one_window
    ):
        """A limit of 2 over three rows splits into a full page and a remainder.

        "The `limit` parameter caps the number of rows returned; it defaults to
        10, may not be lower than 1, and may not exceed 100. The `offset`
        parameter skips rows from the front of the result; it defaults to 0 and
        may not be negative."

        Design: Corner/entities/list_deliveries_paginates_with_total_count_and_has_more
        """
        _net, _window, deliveries = three_bags_on_one_window

        first_rows, first_meta = validate_paginated(
            api.list_deliveries(OPS_HEADERS, limit=2, offset=0)
        )
        assert len(first_rows) == 2
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True

        second_rows, second_meta = validate_paginated(
            api.list_deliveries(OPS_HEADERS, limit=2, offset=2)
        )
        assert len(second_rows) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False

        paged = ids_of(first_rows) + ids_of(second_rows)
        assert sorted(paged) == sorted(row["id"] for row in deliveries)

    def test_the_declared_filters_narrow_the_same_collection(
        self, api, three_bags_on_one_window
    ):
        """Window and custody filters combine, and the window itself is now full.

        "Deliveries filter by `order_id`, `window_id`, `courier_id`,
        `reship_of_delivery_id`, `custody_status`, and `settlement_status`."

        Design: Corner/entities/list_deliveries_paginates_with_total_count_and_has_more
        """
        _net, window, _deliveries = three_bags_on_one_window
        rows, meta = validate_paginated(
            api.list_deliveries(OPS_HEADERS, window_id=window["id"], custody_status="QUEUED")
        )
        assert meta["total_count"] == 3
        assert [row["custody_status"] for row in rows] == ["QUEUED"] * 3

        assert_window_occupancy(
            read_window(api, window["id"]),
            reserved_slots=3,
            available_slots=0,
            status="FULL",
        )


class TestUnknownDeliveryIdentifier:
    """"Every identifier segment in the path resolves to a stored row of the
    addressed collection — otherwise the 404 belonging to that collection"
    """

    def test_a_valid_but_unused_uuid_is_a_delivery_not_found_on_read_and_on_write(
        self, api
    ):
        """The collection's own 404 answers both the read and the state-changing call.

        "Existence is deliberately checked *after* scoping, so probing a real
        identifier belonging to another tenant yields 403 rather than leaking the
        difference between 404 and 200."

        Design: Corner/entities/get_delivery_with_unknown_id_returns_not_found
        """
        read = api.get_delivery(UNKNOWN_UUID, headers=OPS_HEADERS)
        body = validate_error(read, "ERR_DELIVERY_NOT_FOUND", 404)
        assert body["message"]

        # The cancelling caller must be a registered pharmacy operator: §2.1
        # resolves an X-User-ID matching no stored row to NetworkOps, which is
        # not one of the roles the cancel capability admits.
        net = build_network(api)
        cancel = api.cancel_delivery(UNKNOWN_UUID, headers=net.pharmacy_headers)
        validate_error(cancel, "ERR_DELIVERY_NOT_FOUND", 404)


class TestOrderIntakeRequiredAndOptionalFields:
    """"The request body parses, contains every required field, and satisfies
    every declared type, enum, range, and format constraint — otherwise
    `ERR_INVALID_REQUEST`."
    """

    def test_omitting_the_recipient_is_rejected_and_writes_no_order(self, api):
        """A required field cannot be defaulted, and the refusal leaves no row.

        "A `PharmacyOperator` takes a filled bundle into the system by declaring
        the `pharmacy_id` of the dispensing site, the `patient_id` of the
        recipient"

        Design: Corner/entities/create_pharmacy_order_missing_required_patient_id_returns_invalid_request
        """
        net = build_network(api, clock=CLOCK_EPOCH)
        response = api.create_pharmacy_order(
            factories.pharmacy_order_payload(
                net.pharmacy["id"],
                factories.OMIT,
                **STANDARD_ORDER,
            ),
            headers=net.pharmacy_headers,
        )
        validate_error(response, "ERR_INVALID_REQUEST", 400)

        validate_success(
            api.create_pharmacy_order(
                factories.pharmacy_order_payload(
                    net.pharmacy["id"], net.patient["id"], **STANDARD_ORDER
                ),
                headers=net.pharmacy_headers,
            ),
            201,
        )
        _rows, meta = validate_paginated(
            api.list_pharmacy_orders(net.pharmacy_headers, pharmacy_id=net.pharmacy["id"])
        )
        assert meta["total_count"] == 1

    def test_omitting_the_optional_handling_flags_falls_back_to_the_declared_defaults(
        self, api
    ):
        """The two handling options are genuinely optional, unlike the recipient.

        "an optional `cold_chain_required` flag defaulting to false, an optional
        `controlled_schedule` of `NONE`, `CIII`, or `CII` defaulting to `NONE`"

        Design: Corner/entities/create_pharmacy_order_missing_required_patient_id_returns_invalid_request
        """
        net = build_network(api, clock=CLOCK_EPOCH)
        order = validate_success(
            api.create_pharmacy_order(
                factories.pharmacy_order_payload(
                    net.pharmacy["id"],
                    net.patient["id"],
                    rx_line_count=1,
                    total_rx_value_cents=1000,
                    cold_chain_required=factories.OMIT,
                    controlled_schedule=factories.OMIT,
                ),
                headers=net.pharmacy_headers,
            ),
            201,
        )
        assert order["cold_chain_required"] is False
        assert order["controlled_schedule"] == "NONE"


class TestCourierOnboardingDefaults:
    """"A new courier starts `OFFLINE` with `active_delivery_count` at 0,
    `attempt_total_count` and `delivered_count` at 0, and both
    `rolling_reliability_score` and `lifetime_reliability_score` at 100.00."
    """

    def test_a_fresh_courier_carries_zero_counters_and_a_perfect_score(self, api):
        """Nothing has happened yet, so both scores sit at the no-attempt value.

        "optional `cold_chain_equipped` and `controlled_certified` booleans that
        both default to false"

        Design: Corner/entities/create_courier_defaults_to_offline_with_zero_counters
        """
        set_clock(api, CLOCK_EPOCH)
        build_zone(api)
        courier = validate_success(
            api.create_courier(
                factories.courier_payload(
                    display_name="Ida Nunez",
                    mode="ON_DEMAND",
                    cold_chain_equipped=factories.OMIT,
                    controlled_certified=factories.OMIT,
                ),
                headers=OPS_HEADERS,
            ),
            201,
        )
        assert courier["status"] == "OFFLINE"
        assert courier["cold_chain_equipped"] is False
        assert courier["controlled_certified"] is False
        assert courier["active_delivery_count"] == 0
        assert courier["attempt_total_count"] == 0
        assert courier["delivered_count"] == 0
        assert courier["rolling_reliability_score"] == pytest.approx(100.00, abs=0.01)
        assert courier["lifetime_reliability_score"] == pytest.approx(100.00, abs=0.01)

    def test_a_courier_left_offline_is_not_a_selector_candidate(self, api):
        """The initial state is not merely cosmetic: it keeps the pool empty.

        "A courier is a candidate only when every one of the following holds: its
        `status` is `AVAILABLE` or `ON_ROUTE`"

        Design: Corner/entities/create_courier_defaults_to_offline_with_zero_counters
        """
        scn = build_queued_delivery(api, order_kwargs=STANDARD_ORDER)
        validate_success(
            api.create_courier(
                factories.courier_payload(display_name="Ida Nunez"), headers=OPS_HEADERS
            ),
            201,
        )
        set_clock(api, utc_ts(3, 13, 45))

        response = api.dispatch_delivery(
            scn.delivery["id"], headers=OPS_HEADERS, payload=factories.dispatch_payload()
        )
        validate_error(response, "ERR_NO_ELIGIBLE_COURIER", 409)


class TestOrderProofLadderIsComputed:
    """"`signature_required` is true when the bag is cold, or controlled, or its
    `total_rx_value_cents` is at least 25000 cents — that is, at least 250
    dollars, with a bag valued at exactly 250 dollars already requiring a
    signature."
    """

    def test_the_value_threshold_is_inclusive_at_25000_cents(self, api):
        """One cent decides both the signature flag and the identity rung.

        "failing that, a `total_rx_value_cents` of at least 25000 demands
        `PHOTO_ID`; and everything else, cold bags included, settles at
        `DOB_MATCH`"

        Design: Corner/entities/order_signature_and_id_ladder_are_computed_from_value_threshold
        """
        net = build_network(api, clock=CLOCK_EPOCH)
        at_threshold = build_order(
            api, net, **dict(STANDARD_ORDER, total_rx_value_cents=25000)
        )
        below = build_order(api, net, **dict(STANDARD_ORDER, total_rx_value_cents=24999))

        assert at_threshold["signature_required"] is True
        assert at_threshold["required_id_verification"] == "PHOTO_ID"
        assert below["signature_required"] is False
        assert below["required_id_verification"] == "DOB_MATCH"

    def test_a_controlled_schedule_outranks_a_trivial_bag_value(self, api):
        """A 500-cent CIII bag still demands a photograph and a signature.

        "The order lands at `status` `INTAKE` with `hold_count` at 0."

        Design: Corner/entities/order_signature_and_id_ladder_are_computed_from_value_threshold
        """
        net = build_network(api, clock=CLOCK_EPOCH)
        cheap_controlled = build_order(
            api,
            net,
            **dict(STANDARD_ORDER, controlled_schedule="CIII", total_rx_value_cents=500),
        )
        assert cheap_controlled["signature_required"] is True
        assert cheap_controlled["required_id_verification"] == "PHOTO_ID"
        assert cheap_controlled["status"] == "INTAKE"
        assert cheap_controlled["hold_count"] == 0


class TestPatientMaskedNameProjection:
    """"The system derives `masked_name` at registration for the courier-facing
    projection."
    """

    def test_the_mask_keeps_one_leading_character_of_each_token(self, api):
        """The stored name is untouched; the derived one carries far less.

        "`masked_name` is derived from `full_name` by splitting it on whitespace
        and, in each resulting token, keeping the first character and replacing
        every remaining character with an asterisk"

        Design: Corner/entities/patient_masked_name_is_a_computed_projection_of_full_name
        """
        set_clock(api, CLOCK_EPOCH)
        build_zone(api)
        pharmacy = validate_success(
            api.create_pharmacy(factories.pharmacy_payload(), headers=OPS_HEADERS), 201
        )
        patient = validate_success(
            api.create_patient(
                factories.patient_payload(),
                headers=make_pharmacy_headers(pharmacy["id"]),
            ),
            201,
        )
        assert patient["full_name"] == "Dana Reyes"
        assert patient["masked_name"] == "D*** R****"
        assert patient["masked_name"] != patient["full_name"]
        assert patient["hipaa_consent_status"] == "GRANTED"
        assert patient["version"] == 1


class TestDeliveryTakesItsSystemFieldsFromTheServer:
    """"A `PharmacyOperator` reserves capacity for a `READY` order by naming the
    `order_id`, the `window_id` of the promised interval, and the
    `expected_window_version` proving which view of that window's occupancy the
    client is acting on (§2.7)."
    """

    def test_the_clean_reservation_takes_its_state_and_stamp_from_the_server(self, api):
        """Every value the rejected body tried to supply is chosen server-side.

        "On success a `Delivery` row appears with `custody_status` `QUEUED` and
        `settlement_status` `PROVISIONAL`, carrying `order_id` and `window_id`, a
        null `courier_id`, a null `reship_of_delivery_id`, an `attempt_count` of
        0"

        Design: Corner/entities/delivery_rejects_client_supplied_system_fields_returns_invalid_request
        """
        net = build_network(api)
        order = build_ready_order(api, net, **STANDARD_ORDER)
        window = build_window(api, net.zone["id"], capacity_slots=1)

        delivery = validate_success(
            api.create_delivery(
                factories.delivery_payload(order["id"], window["id"], window["version"]),
                headers=net.pharmacy_headers,
            ),
            201,
        )
        assert delivery["custody_status"] == "QUEUED"
        assert delivery["settlement_status"] == "PROVISIONAL"
        assert delivery["courier_id"] is None
        assert delivery["attempt_count"] == 0
        assert delivery["version"] == 1
        assert delivery["reship_of_delivery_id"] is None
        assert delivery["order_id"] == order["id"]
        assert delivery["window_id"] == window["id"]


class TestZoneRangeAndEnumConstraints:
    """"its `distance_band_miles` is the billable distance band, one decimal
    place, between 0.1 and 60.0 inclusive"
    """

    def test_the_distance_band_is_refused_above_and_below_its_declared_range(self, api):
        """60.1 and 0.0 are both outside an inclusive 0.1 to 60.0 band.

        "`DeliveryZone.distance_band_miles` is likewise a decimal — between 0.1
        and 60.0 inclusive with one decimal place — but it is rounded **up to a
        whole mile before** it is multiplied by the per-mile rate, never after."

        Design: Corner/entities/delivery_zone_distance_band_out_of_range_returns_invalid_request
        """
        set_clock(api, CLOCK_EPOCH)
        above = api.create_delivery_zone(
            factories.delivery_zone_payload(zone_code="ZX", distance_band_miles=60.1),
            headers=OPS_HEADERS,
        )
        validate_error(above, "ERR_INVALID_REQUEST", 400)

        below = api.create_delivery_zone(
            factories.delivery_zone_payload(zone_code="ZY", distance_band_miles=0.0),
            headers=OPS_HEADERS,
        )
        validate_error(below, "ERR_INVALID_REQUEST", 400)

        at_bound = validate_success(
            api.create_delivery_zone(
                factories.delivery_zone_payload(
                    zone_code="ZMAX",
                    distance_band_miles=60.0,
                    cold_chain_supported=factories.OMIT,
                    controlled_delivery_allowed=factories.OMIT,
                ),
                headers=OPS_HEADERS,
            ),
            201,
        )
        assert at_bound["distance_band_miles"] == pytest.approx(60.0, abs=0.01)
        assert at_bound["cold_chain_supported"] is True
        assert at_bound["controlled_delivery_allowed"] is True

        _rows, meta = validate_paginated(
            api.list_delivery_windows(OPS_HEADERS, zone_id=at_bound["id"])
        )
        assert meta["total_count"] == 0

    def test_a_payer_type_outside_the_enum_is_the_same_malformed_body(self, api):
        """An unknown enum member is a body-shape failure like any other.

        "This rung also covers pagination bounds, two-decimal percentage checks,
        ISO 8601 shape, and unknown enum members."

        Design: Corner/entities/delivery_zone_distance_band_out_of_range_returns_invalid_request
        """
        set_clock(api, CLOCK_EPOCH)
        response = api.create_health_plan(
            factories.health_plan_payload(name="Bad Payer", payer_type="SELF_PAY"),
            headers=OPS_HEADERS,
        )
        validate_error(response, "ERR_INVALID_REQUEST", 400)


@pytest.fixture
def bag_standing_at_the_door(api):
    """A standard bag out for delivery on a 14:00Z to 22:00Z window."""
    return build_out_for_delivery(
        api, order_kwargs=STANDARD_ORDER, window_kwargs={"window_end": utc_ts(3, 22)}
    )


class TestAttemptIsAnAppendOnlyRecord:
    """"Two collections are append-only records of something that already
    happened and therefore carry only `id` and `created_at`: a `DeliveryAttempt`
    and a `CourierDataDisclosure` have **no** `updated_at` and **no** `version`."
    """

    def test_a_recorded_run_exposes_no_version_and_reads_back_identically(
        self, api, bag_standing_at_the_door
    ):
        """There is nothing to bump, because there is nothing to edit.

        "Both are recorded to two decimal places, rounded half up, and both read
        a `reliability_credit` of 1.0 for a `DELIVERED` outcome, 0.5 for
        `NO_ANSWER`, `REFUSED`, `ADDRESS_INVALID`, or `ID_MISMATCH`, and 0.0 for
        `COLD_BREACH`"

        Design: Corner/entities/delivery_attempt_is_immutable_with_no_version_field
        """
        scn = bag_standing_at_the_door
        attempt = record_attempt(api, scn, "NO_ANSWER", id_verification_method="NONE")

        assert_append_only_record(attempt)
        assert attempt["attempt_no"] == 1
        assert attempt["outcome"] == "NO_ANSWER"
        assert_instant(attempt["attempted_at"], utc_ts(3, 14))
        assert attempt["reliability_credit"] == pytest.approx(0.5, abs=0.01)

        reread = validate_success(
            api.get_delivery_attempt(attempt["id"], headers=scn.courier_headers)
        )
        assert reread == attempt

    def test_a_correction_is_a_second_row_rather_than_an_edit_of_the_first(
        self, api, bag_standing_at_the_door
    ):
        """The ladder appends, so attempt_no rises and the first row stands.

        "an `attempt_no` equal to the delivery's `attempt_count` after this run is
        counted (so the first run is 1), an `attempted_at` stamped from the clock"

        Design: Corner/entities/delivery_attempt_is_immutable_with_no_version_field
        """
        scn = bag_standing_at_the_door
        first = record_attempt(api, scn, "NO_ANSWER", id_verification_method="NONE")
        redepart(api, scn, utc_ts(3, 15))
        second = record_attempt(
            api,
            scn,
            "DELIVERED",
            id_verification_method="DOB_MATCH",
            recipient_relationship="SELF",
        )

        assert second["attempt_no"] == 2
        assert second["outcome"] == "DELIVERED"
        unchanged = validate_success(
            api.get_delivery_attempt(first["id"], headers=scn.courier_headers)
        )
        assert unchanged["outcome"] == "NO_ANSWER"

        _rows, meta = validate_paginated(
            api.list_delivery_attempts(OPS_HEADERS, delivery_id=scn.delivery["id"])
        )
        assert meta["total_count"] == 2
        assert read_delivery(api, scn.delivery["id"])["custody_status"] == "DELIVERED"


class TestGrantPoolForeignKeyIsValidated:
    """"Every foreign key supplied in the request body resolves to a stored row —
    otherwise `ERR_ORDER_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`,
    `ERR_COURIER_NOT_FOUND`, `ERR_PLAN_GRANT_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`,
    or `ERR_REFERENCE_NOT_FOUND` for a referenced health plan, pharmacy, or
    delivery zone that has no dedicated code of its own."
    """

    def test_funding_a_pool_against_no_plan_is_a_reference_not_found(self, api):
        """A health plan has no 404 of its own, so it borrows the generic one.

        "A freshly funded pool starts with `committed_cents` and `consumed_cents`
        at 0, `remaining_cents` equal to `grant_budget_cents`, and `status`
        `ACTIVE`."

        Design: Corner/entities/create_plan_grant_with_unknown_health_plan_returns_not_found
        """
        set_clock(api, CLOCK_EPOCH)
        response = api.create_plan_grant(
            factories.plan_grant_payload(UNKNOWN_UUID), headers=OPS_HEADERS
        )
        validate_error(response, "ERR_REFERENCE_NOT_FOUND", 404)

        plan = build_health_plan(api)
        grant = build_plan_grant(api, plan["id"])
        assert_grant_ledger(
            grant,
            remaining_cents=100_000,
            committed_cents=0,
            consumed_cents=0,
            status="ACTIVE",
        )

        _rows, meta = validate_paginated(
            api.list_plan_grants(
                make_plan_admin_headers(plan["id"]), health_plan_id=plan["id"]
            )
        )
        assert meta["total_count"] == 1
