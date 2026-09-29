"""Request-level refusals: the two leak-payload rules, the regional efficiency
floor, the priority contest at the certification decision, the shipping cap, the
closed manufacturing window, and the two reservation gates."""

from test_helpers import (
    assert_certification_record,
    assert_order_dimensions,
    create_a1_program,
    create_a2l_program,
    create_build_order,
    create_build_order_payload,
    create_high_a2l_draft_platform,
    create_northeast_standard,
    create_southeast_standard,
    create_standard_a1_draft_platform,
    create_warehouse,
    create_warehouse_reservation_payload,
    decide_certification_payload,
    file_certification,
    helium_leak_test_payload,
    make_headers,
    pressure_decay_leak_test_payload,
    read_build_order,
    read_order,
    read_platform,
    read_supply,
    release_platform,
    set_clock,
    setup_brazed_standard_a1_lot,
    setup_staged_order,
    ship_payload,
    submit_certification,
    submit_platform,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestShortPressureHoldIsNotScored:
    """A 14-minute hold is refused outright rather than pro-rated."""

    def test_fourteen_minute_hold_is_refused_and_costs_the_lot_nothing(
        self, api, quality_technician_headers, production_planner_headers
    ):
        """A pressure-decay test must also hold pressure for at least 15 minutes; a
        shorter hold_minutes is refused with ERR_LEAK_TEST_HOLD_TOO_SHORT. Under
        PRESSURE_DECAY, the applied_limit is the plant's allowance of 2.00
        kilopascals for every 15 minutes of hold — that is, 2.00 multiplied by
        hold_minutes divided by 15 — multiplied by the strictness factor and
        rounded to two decimal places.

        Design: Corner/validations/c_leak_test_pressure_decay_hold_below_15_minutes_rejected
        """
        scenario = setup_brazed_standard_a1_lot(quantity_units=10)
        lot_id = scenario["build_order"]["id"]

        response = api.create_leak_test(
            pressure_decay_leak_test_payload(lot_id, decay_kpa=0.10, hold_minutes=14),
            quality_technician_headers,
        )
        validate_error(response, "ERR_LEAK_TEST_HOLD_TOO_SHORT", 422)

        lot = read_build_order(lot_id)
        assert lot["status"] == "BRAZED"
        assert lot["rework_count"] == 0
        assert lot["latest_leak_verdict"] is None

        _, meta = validate_paginated(
            api.list_build_order_leak_tests(lot_id, production_planner_headers)
        )
        assert meta["total_count"] == 0, "a short hold is not scored at all"


class TestMethodDecidesWhichFieldsAreLegal:
    """A helium request that also carries decay fields is a shape failure."""

    def test_helium_payload_carrying_decay_fields_is_an_invalid_request(
        self, api, quality_technician_headers
    ):
        """Helium mass spectrometry requires measured_leak_rate_g_per_year, the
        tracer leak rate in grams per year, at zero or above to two decimals, and
        forbids both decay_kpa and hold_minutes. A payload that omits a field its
        method requires, or that carries a field its method forbids, is refused
        with ERR_INVALID_REQUEST — a request offering both measurement styles is
        rejected outright rather than having one silently ignored.

        Design: Corner/validations/c_leak_test_helium_payload_with_decay_fields_rejected
        """
        scenario = setup_brazed_standard_a1_lot(quantity_units=10)
        lot_id = scenario["build_order"]["id"]
        payload = helium_leak_test_payload(lot_id, measured_leak_rate_g_per_year=1.20)
        payload["decay_kpa"] = 0.90
        payload["hold_minutes"] = 12

        response = api.create_leak_test(payload, quality_technician_headers)
        validate_error(response, "ERR_INVALID_REQUEST", 422)

        lot = read_build_order(lot_id)
        assert lot["status"] == "BRAZED"
        assert lot["rework_count"] == 0

        _, meta = validate_paginated(
            api.list_leak_tests(
                quality_technician_headers, params={"build_order_id": lot_id}
            )
        )
        assert meta["total_count"] == 0


class TestEfficiencyFloorFiresAtSubmission:
    """A filing below the regional minimum is stored, then refused on submission."""

    def test_filing_at_fourteen_seer2_is_refused_against_a_fourteen_thirty_minimum(
        self, api, certification_engineer_headers
    ):
        """The record must be in DRAFT, otherwise ERR_CERTIFICATION_STATE_INVALID;
        the platform must be RELEASED — a restricted platform may hold a draft
        filing but may not submit it — otherwise ERR_INVALID_PLATFORM_STATE; a
        governing standard must exist for the record's region_code, otherwise
        ERR_REGIONAL_STANDARD_NOT_FOUND; and rated_seer2_submitted must be at least
        the governing standard's minimum for the platform's efficiency_tier,
        otherwise ERR_EFFICIENCY_BELOW_REGIONAL_MINIMUM. The tier selects which
        minimum applies: a STANDARD platform is measured against
        min_seer2_standard, a HIGH platform against min_seer2_high, and a PREMIUM
        platform against min_seer2_premium.

        Design: Corner/validations/c_certification_submit_below_regional_minimum_rejected
        """
        create_southeast_standard()
        program = create_a1_program()
        draft = create_standard_a1_draft_platform(
            program["id"], rated_eer=11.20, rated_seer2=14.00
        )
        submit_platform(draft["id"])
        platform = release_platform(draft["id"])
        record = file_certification(
            platform["id"],
            platform["version"],
            region_code="SOUTHEAST",
            rated_seer2_submitted=14.00,
        )
        assert record["status"] == "DRAFT", "the filing itself is accepted at 14.00"

        response = api.submit_certification_record(
            record["id"], certification_engineer_headers
        )
        validate_error(response, "ERR_EFFICIENCY_BELOW_REGIONAL_MINIMUM", 422)

        stored = validate_success(
            api.get_certification_record(record["id"], certification_engineer_headers)
        )
        assert_certification_record(stored)
        assert stored["status"] == "DRAFT"
        assert stored["governing_standard_id"] is None, (
            "the standard is pinned only on a successful submission"
        )
        assert stored["submitted_at"] is None

        stored_platform = read_platform(platform["id"])
        assert stored_platform["salable_region_count"] == 0
        assert stored_platform["blocked_region_codes"] == ["SOUTHEAST"]


class TestDecisionPriorityContest:
    """Who the caller is decides which of two rules is reported."""

    def test_the_submitter_hears_segregation_of_duties_and_the_auditor_the_prohibition(
        self, api, regulatory_auditor_headers, certification_engineer_headers
    ):
        """Both branches require status to be SUBMITTED, otherwise
        ERR_CERTIFICATION_STATE_INVALID, and both require the caller's X-User-ID to
        differ from submitted_by_user_id, otherwise ERR_SEGREGATION_OF_DUTIES.
        Before it can, one regulatory gate applies: if the pinned governing
        standard has prohibits_flammable_refrigerant set to true and the platform's
        program carries flammability_class A2L, the certification is refused with
        ERR_FLAMMABLE_REFRIGERANT_PROHIBITED. When a single request violates more
        than one rule, the error_id returned is the one belonging to the
        highest-priority band of §2.11, and no partial write is left behind.

        Design: Corner/validations/c_decide_sod_preempts_flammable_refrigerant_prohibition
        """
        standard = create_northeast_standard()
        program = create_a2l_program()
        draft = create_high_a2l_draft_platform(program["id"], rated_seer2=16.20)
        submit_platform(draft["id"])
        platform = release_platform(draft["id"])
        record = file_certification(
            platform["id"],
            platform["version"],
            region_code="NORTHEAST",
            rated_seer2_submitted=16.20,
        )
        submit_certification(record["id"])

        by_the_submitter = api.decide_certification_record(
            record["id"],
            decide_certification_payload("CERTIFIED"),
            make_headers("user-ce-1", "RegulatoryAuditor"),
        )
        validate_error(by_the_submitter, "ERR_SEGREGATION_OF_DUTIES", 409)

        by_another_auditor = api.decide_certification_record(
            record["id"],
            decide_certification_payload("CERTIFIED"),
            regulatory_auditor_headers,
        )
        validate_error(by_another_auditor, "ERR_FLAMMABLE_REFRIGERANT_PROHIBITED", 422)

        stored = validate_success(
            api.get_certification_record(record["id"], certification_engineer_headers)
        )
        assert stored["status"] == "SUBMITTED", "neither refusal advanced the filing"
        assert stored["decided_by_user_id"] is None
        assert stored["decided_at"] is None
        assert stored["submitted_by_user_id"] == "user-ce-1"
        assert stored["governing_standard_id"] == standard["id"]

        stored_platform = read_platform(platform["id"])
        assert stored_platform["blocked_region_codes"] == ["NORTHEAST"]
        assert stored_platform["salable_region_count"] == 0


class TestShipUnitsMustMatchTheAllocation:
    """One unit more than the allocation commits nothing at all."""

    def test_shipping_forty_one_units_against_forty_allocated_is_refused(
        self, api, production_planner_headers
    ):
        """The shipped_units supplied on the request must equal the order's
        allocated_units exactly — neither more nor fewer — otherwise the request is
        refused with ERR_SHIP_UNITS_EXCEED_ALLOCATION. Then every allocation line
        of the order whose status is RESERVED becomes COMMITTED, processed oldest
        first, with each touched pool moving those units from reserved_units into
        committed_units and incrementing its own version.

        Design: Corner/validations/c_order_ship_units_exceeding_allocation_rejected
        """
        scenario = setup_staged_order(requested_units=40, pool_units=40)
        order_id = scenario["order"]["id"]
        assert_order_dimensions(scenario["order"], "FULLY_ALLOCATED", "STAGED")

        response = api.ship_distributor_order(
            order_id, ship_payload(41), production_planner_headers
        )
        validate_error(response, "ERR_SHIP_UNITS_EXCEED_ALLOCATION", 422)

        order = read_order(order_id)
        assert_order_dimensions(order, "FULLY_ALLOCATED", "STAGED")
        assert order["allocated_units"] == 40
        assert order["shipped_units"] == 0
        assert order["shipped_at"] is None

        pool = read_supply(scenario["compressor"]["id"])
        assert pool["reserved_units"] == 40
        assert pool["committed_units"] == 0, "nothing was committed"

        assert read_platform(scenario["platform"]["id"])["units_shipped_total"] == 0


class TestManufactureWindowClosesOnTheClock:
    """The cutoff bites even though nothing about the program has moved."""

    def test_a_new_lot_after_the_cutoff_is_refused_on_an_active_program(
        self, api, plant_admin_headers, production_planner_headers
    ):
        """And the logical clock must be strictly before the governing refrigerant
        program's manufacture_cutoff_utc; at or after that instant the lot is
        refused with ERR_MANUFACTURE_WINDOW_CLOSED. A program advances through
        exactly two transitions, both driven by a PlantAdmin.

        Design: Corner/validations/c_build_order_creation_after_manufacture_cutoff_rejected
        """
        program = create_a1_program(
            manufacture_cutoff_utc="2026-09-01T00:00:00Z",
            sell_through_deadline_utc="2027-03-01T00:00:00Z",
        )
        draft = create_standard_a1_draft_platform(program["id"])
        submit_platform(draft["id"])
        platform = release_platform(draft["id"])
        set_clock("2026-09-02T00:00:00Z")

        response = api.create_build_order(
            create_build_order_payload(
                platform["id"],
                quantity_units=10,
                scheduled_start_utc="2026-09-03T06:00:00Z",
            ),
            production_planner_headers,
        )
        validate_error(response, "ERR_MANUFACTURE_WINDOW_CLOSED", 409)

        stored_program = validate_success(
            api.get_refrigerant_program(program["id"], plant_admin_headers)
        )
        assert stored_program["status"] == "ACTIVE", (
            "the cutoff passing does not itself move the program"
        )
        assert read_platform(platform["id"])["status"] == "RELEASED"

        _, meta = validate_paginated(
            api.list_build_orders(
                production_planner_headers, params={"platform_id": platform["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestOnlyPreseasonLotsMayHoldPallets:
    """A lot created without the flag cannot book space in an empty warehouse."""

    def test_reservation_for_a_lot_that_is_not_preseason_is_refused(
        self, api, production_planner_headers
    ):
        """Only a pre-season lot may hold pallet space, and only while it is still
        in production. A reservation is refused with
        ERR_RESERVATION_NOT_ALLOWED_FOR_BUILD when the named lot's is_preseason is
        false, or when its status is any of LEAK_PASSED, CHARGED, RUN_PASSED,
        RELEASED_TO_STOCK, SCRAPPED, CANCELLED, or HOLD_REGULATORY — which leaves
        DRAFT, COIL_FAB, BRAZED, and REWORK as the four stages at which space may
        be booked. A ProductionPlanner opens it against a platform by naming the
        platform_id, the quantity_units in the lot (at least 1), and the
        scheduled_start_utc at which coil fabrication is planned to begin, and by
        flagging is_preseason when the lot is a pre-season levelling build; the flag
        defaults to false when omitted.

        Design: Corner/validations/c_reservation_for_non_preseason_build_rejected
        """
        warehouse = create_warehouse("WH-1", 50)
        program = create_a1_program()
        draft = create_standard_a1_draft_platform(program["id"])
        submit_platform(draft["id"])
        platform = release_platform(draft["id"])
        lot = create_build_order(
            platform["id"], quantity_units=20, scheduled_start_utc="2026-11-02T06:00:00Z"
        )
        assert lot["is_preseason"] is False, "the omitted flag took its default"

        response = api.create_warehouse_reservation(
            create_warehouse_reservation_payload(
                warehouse["id"],
                lot["id"],
                start_date="2026-11-02",
                end_date="2026-11-20",
                pallet_units=10,
            ),
            production_planner_headers,
        )
        validate_error(response, "ERR_RESERVATION_NOT_ALLOWED_FOR_BUILD", 409)

        assert read_build_order(lot["id"])["status"] == "DRAFT"
        stored_warehouse = validate_success(
            api.get_warehouse(warehouse["id"], production_planner_headers)
        )
        assert stored_warehouse["pallets_reserved_current"] == 0

        _, meta = validate_paginated(
            api.list_warehouse_reservations(warehouse["id"], production_planner_headers)
        )
        assert meta["total_count"] == 0


class TestReservationIntervalMustBeOrdered:
    """A window describing zero occupied days is malformed."""

    def test_end_date_equal_to_start_date_is_an_invalid_interval(
        self, api, production_planner_headers
    ):
        """The warehouse must resolve, otherwise ERR_WAREHOUSE_NOT_FOUND; the build
        lot must resolve, otherwise ERR_BUILD_ORDER_NOT_FOUND; and end_date must
        fall strictly after start_date, otherwise ERR_INVALID_INTERVAL. A
        reservation occupies day D when its start_date is at or before D and its
        end_date is strictly after D, so a reservation that ends on the day another
        begins does not overlap it and the two may share the last pallet of
        capacity.

        Design: Corner/validations/c_reservation_end_date_not_after_start_rejected
        """
        warehouse = create_warehouse("WH-1", 50)
        program = create_a1_program()
        draft = create_standard_a1_draft_platform(program["id"])
        submit_platform(draft["id"])
        platform = release_platform(draft["id"])
        lot = create_build_order(
            platform["id"],
            quantity_units=20,
            scheduled_start_utc="2026-11-02T06:00:00Z",
            is_preseason=True,
        )

        response = api.create_warehouse_reservation(
            create_warehouse_reservation_payload(
                warehouse["id"],
                lot["id"],
                start_date="2026-11-02",
                end_date="2026-11-02",
                pallet_units=10,
            ),
            production_planner_headers,
        )
        validate_error(response, "ERR_INVALID_INTERVAL", 422)

        stored_warehouse = validate_success(
            api.get_warehouse(warehouse["id"], production_planner_headers)
        )
        assert stored_warehouse["pallets_reserved_current"] == 0

        _, meta = validate_paginated(
            api.list_warehouse_reservations(warehouse["id"], production_planner_headers)
        )
        assert meta["total_count"] == 0
        assert read_build_order(lot["id"])["is_preseason"] is True, (
            "the lot was eligible; only the interval was malformed"
        )
