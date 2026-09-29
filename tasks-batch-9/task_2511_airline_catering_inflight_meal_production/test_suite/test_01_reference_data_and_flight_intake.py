"""Reference-data registration, flight intake and the shapes both return."""

import pytest

from test_helpers import (
    AIRLINE_AN,
    CLOCK_PRODUCTION,
    CLOCK_QA,
    CLOCK_SETUP,
    DEFAULT_LATE_DELIVERY_GRACE_MINUTES,
    DEFAULT_LOAD_FACTOR_PCT,
    DEFAULT_MAX_CONCURRENT_RUNS,
    DEFAULT_SPECIAL_MEAL_CUTOFF_MINUTES,
    DEFAULT_SPEC_DEVIATION_TOLERANCE_PCT,
    DEFAULT_TRUCK_BUFFER_MINUTES,
    DEFAULT_UNUSED_RECOVERY_RATE_PCT,
    ApiErrorId,
    ADMIN,
    FEED,
    LM_ALICE,
    QA,
    SUPERVISOR,
    assert_common_fields,
    assert_decimal_equals,
    assert_flight_ledger,
    assert_immutable_record_fields,
    assert_instant_equals,
    assert_total_count,
    blended_cost_per_pax_cents,
    cabin_cost_per_pax_cents,
    factories as f,
    is_iso8601_timestamp,
    is_valid_uuid,
    item_gross_cents,
    load_item,
    read_cart,
    read_flight,
    record_check,
    register_cart,
    set_clock,
    start_batch,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAirlineAndReferenceCreation:
    """Creates of the four `PlatformAdmin` reference entities."""

    def test_airline_create_returns_the_whole_persisted_row_in_the_envelope(self, api):
        """A create answers 201 with the persisted row inside the success envelope.

        PRD §3.1: "A newly registered airline opens in `ACTIVE` with `open_finding_count` at 0, `penalty_accrued_cents` at 0 and `version` at 1."

        Design: Corner/entities/airline_creation_returns_the_persisted_row_in_the_success_envelope
        """
        set_clock(api, CLOCK_SETUP)
        response = api.create_airline(f.airline_payload(iata_code="AN"), ADMIN)
        assert response.status_code == 201
        body = response.json()
        assert set(body.keys()) == {"meta", "response_type", "data"}
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)

        airline = body["data"]
        assert airline["name"] == AIRLINE_AN["name"]
        assert airline["iata_code"] == "AN"
        assert airline["waste_regime"] == AIRLINE_AN["waste_regime"]
        assert airline["cost_cap_per_pax_cents"] == AIRLINE_AN["cost_cap_per_pax_cents"]
        assert airline["status"] == "ACTIVE"
        assert airline["open_finding_count"] == 0
        assert airline["penalty_accrued_cents"] == 0
        assert_common_fields(airline, expected_version=1)
        assert is_valid_uuid(airline["id"])

    def test_omitted_optional_fields_take_their_declared_defaults(self, api):
        """Four entities each fall back to the default the contract declares.

        PRD §3.1: "`special_meal_cutoff_minutes` is how long before departure special meal capture closes, defaulting to twelve hours and accepted anywhere from zero minutes up to three days."

        Design: Corner/entities/omitted_optional_reference_fields_fall_back_to_their_declared_defaults
        """
        set_clock(api, CLOCK_SETUP)
        airline = validate_success(
            api.create_airline(f.airline_payload(iata_code="AN"), ADMIN), 201
        )
        assert (
            airline["special_meal_cutoff_minutes"]
            == DEFAULT_SPECIAL_MEAL_CUTOFF_MINUTES
        )
        assert (
            airline["late_delivery_grace_minutes"]
            == DEFAULT_LATE_DELIVERY_GRACE_MINUTES
        )
        assert_decimal_equals(
            airline["unused_recovery_rate_pct"], DEFAULT_UNUSED_RECOVERY_RATE_PCT
        )
        assert_decimal_equals(
            airline["spec_deviation_tolerance_pct"],
            DEFAULT_SPEC_DEVIATION_TOLERANCE_PCT,
        )
        assert airline["status"] == "ACTIVE"

        spec_body = f.without(
            f.spec_economy_payload(airline["id"], spec_code="AN-Y-DEF"),
            "load_factor_pct",
        )
        spec = validate_success(api.create_meal_specification(spec_body, ADMIN), 201)
        assert_decimal_equals(spec["load_factor_pct"], DEFAULT_LOAD_FACTOR_PCT)
        assert spec["status"] == "ACTIVE"

        truck = validate_success(
            api.create_truck(f.truck_payload(registration="HL-900"), ADMIN), 201
        )
        assert truck["buffer_minutes"] == DEFAULT_TRUCK_BUFFER_MINUTES
        assert truck["status"] == "ACTIVE"

        stand = validate_success(
            api.create_stand(f.stand_payload(stand_code="B01"), ADMIN), 201
        )
        assert stand["max_concurrent_runs"] == DEFAULT_MAX_CONCURRENT_RUNS
        assert stand["status"] == "ACTIVE"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"spec_code": "AN-P-STD", "cabin": "PREMIUM"},
            {"spec_code": "AN-Y-HI", "load_factor_pct": 25.01},
            {"spec_code": "AN-Y-EMPTY", "required_haccp_steps": []},
            {
                "spec_code": "AN-Y-DUP",
                "required_haccp_steps": ["HOLD_TEMP", "HOLD_TEMP"],
            },
        ],
        ids=["undeclared-cabin", "load-factor-above-ceiling", "empty-steps", "duplicate-steps"],
    )
    def test_specification_shape_failures_persist_nothing(self, api, overrides):
        """Enum closure, the load-factor ceiling and the step-list constraints are all shape checks.

        PRD §3.1: "`required_haccp_steps` is a non-empty list, without duplicates, of the step codes that must each carry a passing latest reading before release; each element is one of `COOK_TEMP`, `CHILL_DOWN`, `HOLD_TEMP` or `BLAST_CHILL`."

        Design: Corner/entities/meal_specification_rejects_undeclared_enums_and_out_of_range_numbers
        """
        set_clock(api, CLOCK_SETUP)
        airline = validate_success(
            api.create_airline(f.airline_payload(iata_code="AN"), ADMIN), 201
        )
        payload = f.spec_economy_payload(airline["id"], **overrides)
        validate_error(
            api.create_meal_specification(payload, ADMIN),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )
        _, meta = validate_paginated(
            api.list_meal_specifications(ADMIN, {"airline_id": airline["id"]})
        )
        assert_total_count(meta, 0)

    def test_specification_naming_an_unknown_airline_is_a_body_reference_miss(self, api):
        """`airline_id` arrives in the body, so a miss is a body-reference failure.

        PRD §2.6: "**Priority 60 — body reference existence.** Every identifier carried in the request body resolves to an existing row, checked in the field order the endpoint declares."

        Design: Corner/entities/meal_specification_naming_an_unknown_airline_is_rejected_with_resource_not_found
        """
        set_clock(api, CLOCK_SETUP)
        airline = validate_success(
            api.create_airline(f.airline_payload(iata_code="AN"), ADMIN), 201
        )
        payload = f.spec_economy_payload("11111111-1111-4111-8111-111111111111")
        validate_error(
            api.create_meal_specification(payload, ADMIN),
            ApiErrorId.ERR_RESOURCE_NOT_FOUND.value,
            404,
        )
        _, meta = validate_paginated(
            api.list_meal_specifications(ADMIN, {"airline_id": airline["id"]})
        )
        assert_total_count(meta, 0)


class TestFlightIntake:
    """What the schedule feed derives the moment a flight lands."""

    def test_flight_creation_without_std_utc_is_a_shape_failure(self, base_env):
        """`std_utc` carries no default, so its absence is refused before anything derives.

        PRD §3.2: "Ingesting a flight requires the operating carrier's `airline_id`, the carrier's `flight_number` designator, the local `service_date` in year-month-day form, the scheduled departure `std_utc`, the aircraft registration `tail_number` the equipment build will be sized for, and the three-letter catering `station_code` — the station that trucks and stands must share for a delivery slot to be reservable."

        Design: Corner/entities/flight_creation_without_std_utc_returns_invalid_request
        """
        api = base_env.api
        payload = f.without(
            f.flight_payload(base_env.airline_id, pax_economy=180), "std_utc"
        )
        validate_error(
            api.create_flight(payload, FEED),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )
        _, meta = validate_paginated(
            api.list_flights(FEED, {"airline_id": base_env.airline_id})
        )
        assert_total_count(meta, 0)

    def test_intake_derives_total_pax_cutoff_and_the_provisional_requirement(
        self, base_env
    ):
        """Intake computes the cutoff and the provisional requirement in the create response itself.

        PRD §3.2: "`special_meal_cutoff_utc` is `revised_std_utc` pulled back by the airline's `special_meal_cutoff_minutes`."

        Design: Corner/entities/flight_creation_derives_total_pax_cutoff_and_provisional_units
        """
        api = base_env.api
        flight = validate_success(
            api.create_flight(
                f.flight_payload(base_env.airline_id, pax_economy=180), FEED
            ),
            201,
        )
        assert flight["total_pax"] == 180
        assert flight["status"] == "SCHEDULED"
        assert_instant_equals(flight["revised_std_utc"], "2026-09-15T10:00:00Z")
        assert flight["delay_minutes"] == 0
        assert_instant_equals(
            flight["special_meal_cutoff_utc"], "2026-09-14T22:00:00Z"
        )
        # 180 economy passengers at the 2.50 percent spoilage uplift, rounded up.
        assert flight["units_planned_provisional"] == 185
        assert flight["units_planned"] == 0
        assert_flight_ledger(
            flight, units_produced=0, units_loaded=0, units_scrapped=0, unit_balance=0
        )
        assert flight["cost_per_pax_cents"] == 0
        assert flight["counts_locked_at"] is None
        assert flight["production_hold"] is False
        assert_common_fields(flight, expected_version=1)

    def test_seeding_the_flight_status_field_is_rejected(self, base_env):
        """An unknown body key is refused rather than dropped, so `status` cannot be seeded.

        PRD §2.6: "Unknown fields are rejected rather than ignored."

        Design: Corner/entities/undeclared_status_field_on_flight_creation_is_rejected
        """
        api = base_env.api
        seeded = f.flight_payload(
            base_env.airline_id, pax_economy=180, status="DEPARTED"
        )
        validate_error(
            api.create_flight(seeded, FEED),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        clean = validate_success(
            api.create_flight(
                f.flight_payload(base_env.airline_id, pax_economy=180), FEED
            ),
            201,
        )
        assert clean["status"] == "SCHEDULED"
        assert_common_fields(clean, expected_version=1)
        assert is_valid_uuid(clean["id"])
        assert is_iso8601_timestamp(clean["created_at"])
        assert is_iso8601_timestamp(clean["updated_at"])

        _, meta = validate_paginated(
            api.list_flights(FEED, {"airline_id": base_env.airline_id})
        )
        assert_total_count(meta, 1)

    def test_reading_a_flight_back_returns_the_stored_row_unchanged(self, flight_env):
        """A read straight after the create observes exactly the created values.

        PRD §2.9: "Cascades are immediate and fully applied before the response is emitted — there is no deferred or eventual settlement anywhere in the service, so a read issued immediately after a cascading write observes every consequence of it."

        Design: Corner/entities/flight_retrieval_returns_the_stored_row_unchanged
        """
        api = flight_env.api
        created_row = flight_env.flight
        response = api.get_flight(flight_env.flight_id, FEED)
        body = response.json()
        assert body["response_type"] == "object"
        flight = validate_success(response, 200)
        assert flight["id"] == created_row["id"]
        assert flight["total_pax"] == 180
        assert flight["units_planned_provisional"] == 185
        assert flight["version"] == 1
        assert_instant_equals(
            flight["special_meal_cutoff_utc"], "2026-09-14T22:00:00Z"
        )
        assert flight["updated_at"] == created_row["updated_at"]

    def test_flight_listing_pages_with_total_count_and_has_more(self, flight_env):
        """`total_count` counts the filtered set and `has_more` falls false on the last page.

        PRD §2.3: "List responses populate `limit`, `offset`, `total_count` and `has_more` in the `meta` object, where `total_count` counts every row matching the supplied filters before paging and `has_more` is true exactly when rows remain beyond the current page."

        Design: Corner/entities/flight_listing_paginates_with_total_count_and_has_more
        """
        api = flight_env.api
        airline_id = flight_env.airline_id
        validate_success(
            api.create_flight(
                f.flight_payload(
                    airline_id,
                    flight_number="AN412",
                    std_utc="2026-09-15T12:00:00Z",
                    tail_number="LN-BBB",
                    pax_economy=120,
                ),
                FEED,
            ),
            201,
        )
        validate_success(
            api.create_flight(
                f.flight_payload(
                    airline_id,
                    flight_number="AN413",
                    std_utc="2026-09-15T14:00:00Z",
                    tail_number="LN-CCC",
                    pax_economy=90,
                ),
                FEED,
            ),
            201,
        )

        page1, meta1 = validate_paginated(
            api.list_flights(FEED, {"airline_id": airline_id, "limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0
        assert_total_count(meta1, 3)
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_flights(FEED, {"airline_id": airline_id, "limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["offset"] == 2
        assert_total_count(meta2, 3)
        assert meta2["has_more"] is False

        numbers = [row["flight_number"] for row in page1 + page2]
        assert sorted(numbers) == ["AN411", "AN412", "AN413"]

        _, meta3 = validate_paginated(
            api.list_flights(
                FEED, {"airline_id": airline_id, "status": "COUNTS_LOCKED"}
            )
        )
        assert_total_count(meta3, 0)


class TestTypedNotFoundResolution:
    """Priority 40 does not collapse the four 404 codes into one."""

    @pytest.mark.parametrize(
        "path_suffix,error_id",
        [
            ("flights", ApiErrorId.ERR_FLIGHT_NOT_FOUND.value),
            ("production-batches", ApiErrorId.ERR_BATCH_NOT_FOUND.value),
            ("carts", ApiErrorId.ERR_CART_NOT_FOUND.value),
            ("loading-manifests", ApiErrorId.ERR_RESOURCE_NOT_FOUND.value),
        ],
        ids=["flight", "batch", "cart", "manifest"],
    )
    def test_unknown_ids_report_the_entity_specific_code(
        self, api, path_suffix, error_id
    ):
        """Each entity family reports its own 404 identifier.

        PRD §2.6: "Identifier resolution failures are typed by the entity: a missing `Flight` reports `ERR_FLIGHT_NOT_FOUND`, a missing `ProductionBatch` reports `ERR_BATCH_NOT_FOUND`, a missing `Cart` reports `ERR_CART_NOT_FOUND`, and a missing `Airline`, `MealSpecification`, `SpecialMealOrder`, `HaccpCheck`, `CartItem`, `LoadingManifest`, `Truck`, `Stand`, `DeliveryRun`, `UpliftRecord`, `WasteManifest` or `AuditFinding` reports `ERR_RESOURCE_NOT_FOUND`."

        Design: Corner/entities/unknown_ids_return_the_entity_specific_not_found_errors
        """
        set_clock(api, CLOCK_SETUP)
        missing = "00000000-0000-4000-8000-000000000000"
        response = api._request("GET", "/%s/%s" % (path_suffix, missing), headers=FEED)
        validate_error(response, error_id, 404)


class TestCartItemJunctionAndImmutableChecks:
    """The many-to-many junction and the one immutable record."""

    def test_one_released_batch_supplies_two_carts_of_the_same_flight(
        self, released_env
    ):
        """A cart item is a junction row, reverse-reachable from the batch it draws on.

        PRD §3.6: "A flight's `units_loaded` is the sum of `qty_units` over `ACTIVE` items across all its carts, and its `unit_balance` is `units_produced` minus `units_loaded`."

        Design: Corner/entities/one_released_batch_feeds_two_carts_through_the_cart_item_junction
        """
        env = released_env
        api = env.api
        set_clock(api, "2026-09-15T06:10:00Z")
        cart_one = register_cart(
            api,
            env.flight_id,
            cart_code="CHL-01",
            cart_type="STD_FULL",
            storage_class="CHILL",
            capacity_units=200,
            galley_position="G1",
        )
        cart_two = register_cart(
            api,
            env.flight_id,
            cart_code="CHL-02",
            cart_type="STD_HALF",
            storage_class="CHILL",
            capacity_units=100,
            galley_position="G2",
        )

        item_one = load_item(api, cart_one["id"], env.batch["id"], 100)
        item_two = load_item(api, cart_two["id"], env.batch["id"], 80)
        assert item_one["status"] == "ACTIVE"
        assert item_two["status"] == "ACTIVE"
        assert item_one["meal_code"] == "STANDARD"
        assert item_two["meal_code"] == "STANDARD"

        assert read_cart(api, cart_one["id"])["loaded_units"] == 100
        assert read_cart(api, cart_one["id"])["build_status"] == "BUILDING"
        assert read_cart(api, cart_two["id"])["loaded_units"] == 80
        assert read_cart(api, cart_two["id"])["build_status"] == "BUILDING"

        _, meta = validate_paginated(
            api.list_cart_items(
                LM_ALICE, {"production_batch_id": env.batch["id"]}
            )
        )
        assert_total_count(meta, 2)

        flight = read_flight(api, env.flight_id)
        assert_flight_ledger(
            flight, units_produced=180, units_loaded=180, unit_balance=0
        )
        economy_cost = item_gross_cents(100, 1450) + item_gross_cents(80, 1450)
        expected = blended_cost_per_pax_cents(
            [(cabin_cost_per_pax_cents(economy_cost, 180), 180)], 180
        )
        assert expected == 1624
        assert flight["cost_per_pax_cents"] == 1624

    def test_a_haccp_check_carries_no_version_and_corrections_are_new_rows(
        self, planned_env
    ):
        """The one immutable record: no `version`, no `updated_at`, no update operation.

        PRD §2.5: "A HACCP check is an immutable food-safety record: it carries only `id` and `created_at`, and both `updated_at` and `version` are absent from it entirely."

        Design: Corner/entities/haccp_check_is_immutable_and_carries_no_version_field
        """
        env = planned_env
        api = env.api
        set_clock(api, CLOCK_PRODUCTION)
        start_batch(api, env.batch["id"])
        set_clock(api, CLOCK_QA)
        first = record_check(api, env.batch["id"], "CHILL_DOWN", 6.0)

        stored = validate_success(api.get_haccp_check(first["id"], QA), 200)
        for key in (
            "id",
            "created_at",
            "production_batch_id",
            "step_code",
            "measured_temp_c",
            "measured_at_utc",
            "verdict",
            "sequence_no",
            "recorded_by_user_id",
        ):
            assert key in stored, "missing %s on the check row" % key
        assert_immutable_record_fields(stored)
        assert stored["verdict"] == "PASS"
        assert stored["sequence_no"] == 1
        assert_instant_equals(stored["measured_at_utc"], CLOCK_QA)

        second = record_check(api, env.batch["id"], "CHILL_DOWN", 7.0)
        assert second["sequence_no"] == 2
        assert second["verdict"] == "PASS"
        assert second["id"] != first["id"]

        reread = validate_success(api.get_haccp_check(first["id"], QA), 200)
        assert reread == stored

        _, meta = validate_paginated(
            api.list_haccp_checks(SUPERVISOR, {"production_batch_id": env.batch["id"]})
        )
        assert_total_count(meta, 2)
