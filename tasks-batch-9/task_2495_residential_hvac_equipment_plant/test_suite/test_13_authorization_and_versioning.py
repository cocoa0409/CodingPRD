"""Who may act and with which token: the release restricted to the independent
judge, the witness rule on performance testing, order ownership, the two version
guards, and a production counter that is a live sum."""

import pytest

from test_helpers import (
    allocate_payload,
    assert_order_dimensions,
    assert_supply_conservation,
    braze_lot,
    cancel_order_payload,
    certify_certification,
    charge_lot,
    create_a1_program,
    create_a2l_program,
    create_build_order,
    create_certification_record_payload,
    create_northeast_standard,
    create_released_high_a2l_platform,
    create_released_standard_a1_platform,
    create_run_test_payload,
    create_southeast_standard,
    create_standard_a1_draft_platform,
    create_test_cell,
    file_certification,
    make_headers,
    place_order,
    read_build_order,
    read_order,
    read_platform,
    read_supply,
    record_helium_leak_test,
    record_run_test,
    setup_certified_platform_with_pools,
    submit_certification,
    submit_platform,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestReleaseIsTheReliabilityEngineersAlone:
    """A role trusted on the line is refused at the design gate."""

    def test_a_production_technician_cannot_release_a_platform_in_review(
        self, api, production_technician_headers
    ):
        """Review is decided by a ReliabilityEngineer, and never by the submitter.
        If X-User-Role is absent, is not one of those eleven strings, or is not among
        the roles authorized for the requested operation, the request is rejected
        with ERR_UNAUTHORIZED (403 Forbidden). On success, revision_round increases
        by one and submitted_by_user_id records the submitting X-User-ID.

        Design: Corner/rbac/c_production_technician_cannot_release_platform
        """
        program = create_a1_program()
        draft = create_standard_a1_draft_platform(program["id"])
        reviewed = submit_platform(draft["id"])
        assert reviewed["status"] == "ENG_REVIEW"

        response = api.release_platform(draft["id"], production_technician_headers)
        validate_error(response, "ERR_UNAUTHORIZED", 403)

        stored = read_platform(draft["id"])
        assert stored["status"] == "ENG_REVIEW", "the state gate never ran"
        assert stored["released_at"] is None
        assert stored["revision_round"] == 1


class TestPerformanceTestNeedsASecondWitness:
    """The same role passes on the leak test and fails on the run test."""

    def test_the_leak_technician_cannot_also_record_the_run_test(
        self, api, quality_technician_headers, plant_admin_headers
    ):
        """Separation of duties applies here: the acting X-User-ID must differ from
        the performed_by_user_id of this lot's most recent passing leak test,
        otherwise ERR_SEGREGATION_OF_DUTIES. Every run test previously recorded
        against the cell participates in the check regardless of its own verdict,
        because a failing run still occupied the cell.

        Design: Corner/rbac/c_run_test_by_the_leak_test_technician_rejected
        """
        program = create_a1_program()
        cell = create_test_cell("CELL-1")
        platform = create_released_standard_a1_platform(program["id"])
        lot = create_build_order(
            platform["id"], quantity_units=10, scheduled_start_utc="2026-08-05T06:00:00Z"
        )
        braze_lot(lot["id"])
        leak_test = record_helium_leak_test(
            lot["id"], 1.10, technician_id="user-qt-1"
        )
        assert leak_test["verdict"] == "PASS"
        assert leak_test["performed_by_user_id"] == "user-qt-1"
        charge_lot(lot["id"], 1600)

        response = api.create_run_test(
            create_run_test_payload(
                lot["id"],
                cell["id"],
                window_start_utc="2026-08-05T08:00:00Z",
                window_end_utc="2026-08-05T09:00:00Z",
                measured_capacity_btuh=24000,
                measured_power_w=2020,
                measured_ambient_c=35.0,
            ),
            quality_technician_headers,
        )
        validate_error(response, "ERR_SEGREGATION_OF_DUTIES", 409)

        stored = read_build_order(lot["id"])
        assert stored["status"] == "CHARGED"
        assert stored["latest_run_verdict"] is None
        assert stored["rework_count"] == 0
        assert stored["charge_grams"] == 1600

        _, meta = validate_paginated(
            api.list_test_cell_run_tests(cell["id"], plant_admin_headers)
        )
        assert meta["total_count"] == 0, "the cell was never occupied"


class TestOrderCancellationIsOwnerOnly:
    """Ownership is the recorded identifier, not the role or the distributor."""

    def test_a_second_rep_cannot_cancel_and_the_owner_still_can(
        self, api, distributor_rep_2_headers, distributor_rep_headers
    ):
        """Cancellation advances PENDING to CANCELLED and is reserved to the
        DistributorRep who placed the order: the acting X-User-ID must equal the
        order's created_by_user_id, otherwise ERR_ORDER_NOT_OWNED. On success
        fulfillment_status becomes CANCELLED, cancelled_at is stamped from the
        logical clock, and version increments.

        Design: Corner/rbac/c_order_cancel_by_a_different_distributor_user_rejected
        """
        program = create_a2l_program()
        platform = create_released_high_a2l_platform(program["id"])
        order = place_order(
            platform["id"],
            requested_units=30,
            priority_score=70,
            distributor_code="DIST-SE-1",
            rep_id="user-dr-1",
        )
        assert order["created_by_user_id"] == "user-dr-1"

        response = api.cancel_distributor_order(
            order["id"],
            cancel_order_payload("Cancelled by a rep who does not own the order"),
            distributor_rep_2_headers,
        )
        validate_error(response, "ERR_ORDER_NOT_OWNED", 403)

        stored = read_order(order["id"])
        assert_order_dimensions(stored, "UNALLOCATED", "PENDING")
        assert stored["cancelled_at"] is None
        assert stored["created_by_user_id"] == "user-dr-1"

        cancelled = validate_success(
            api.cancel_distributor_order(
                order["id"],
                cancel_order_payload("Cancelled by a rep who does not own the order"),
                distributor_rep_headers,
            )
        )
        assert cancelled["fulfillment_status"] == "CANCELLED", (
            "the same request from the real owner is admitted"
        )


class TestCertificationCreateGuardsThePlatformToken:
    """A decision in one region invalidates a filing held for another."""

    def test_a_southeast_filing_on_the_release_time_token_is_a_precondition_failure(
        self, api, plant_admin_headers
    ):
        """If expected_platform_version does not equal the stored platform's current
        version — because the platform has since been re-certified, restricted,
        retired, or filed against again — the request is rejected with
        ERR_STALE_PLATFORM_VERSION (HTTP 412 Precondition Failed), and no record is
        created. The platform's own version increases by one as well, which is
        precisely what makes any other engineer's held expected_platform_version
        stale on their next write.

        Design: Corner/cross_cutting_complexity_layers/c_certification_create_with_stale_platform_version_returns_412
        """
        create_northeast_standard(
            min_seer2_standard=14.30,
            min_seer2_high=15.20,
            min_seer2_premium=16.00,
            prohibits_flammable_refrigerant=False,
        )
        create_southeast_standard()
        program = create_a1_program()
        platform = create_released_standard_a1_platform(program["id"])
        release_time_version = platform["version"]
        northeast = file_certification(
            platform["id"],
            release_time_version,
            region_code="NORTHEAST",
            rated_seer2_submitted=14.60,
        )
        submit_certification(northeast["id"])
        certify_certification(northeast["id"])

        response = api.create_certification_record(
            create_certification_record_payload(
                platform["id"],
                release_time_version,
                region_code="SOUTHEAST",
                rated_seer2_submitted=14.60,
            ),
            make_headers("user-ce-2", "CertificationEngineer"),
        )
        validate_error(response, "ERR_STALE_PLATFORM_VERSION", 412)

        records, meta = validate_paginated(
            api.list_certification_records(
                plant_admin_headers, params={"platform_id": platform["id"]}
            )
        )
        assert meta["total_count"] == 1, "only the northeast record exists"
        assert records[0]["id"] == northeast["id"]
        assert records[0]["status"] == "CERTIFIED"

        stored_platform = read_platform(platform["id"])
        assert stored_platform["blocked_region_codes"] == ["SOUTHEAST"]
        assert stored_platform["salable_region_count"] == 1
        assert stored_platform["version"] > release_time_version, (
            "the certification walk advanced the token the filing was holding"
        )


class TestSuccessfulDrawAdvancesThePoolToken:
    """The positive half of the supply version contract."""

    def test_a_draw_on_version_one_leaves_the_pool_at_version_two(
        self, api, supply_planner_headers
    ):
        """The expected_component_supply_version of §2.8 must match, otherwise
        ERR_STALE_SUPPLY_VERSION at 412. Each drawn pool then recomputes
        reserved_units and available_units, may move ACTIVE to EXHAUSTED, and has its
        version incremented. For a component supply, effective_allocatable_units
        equals available_units plus reserved_units plus committed_units.

        Design: Corner/cross_cutting_complexity_layers/c_allocate_with_current_supply_version_bumps_pool_to_version_2
        """
        scenario = setup_certified_platform_with_pools(
            compressor_units=50, board_units=50
        )
        compressor_id = scenario["compressor"]["id"]
        board_id = scenario["control_board"]["id"]
        order = place_order(
            scenario["platform"]["id"], requested_units=30, priority_score=70
        )
        assert scenario["compressor"]["version"] == 1

        drawn = validate_success(
            api.allocate_distributor_order(
                order["id"], allocate_payload(1), supply_planner_headers
            )
        )
        assert_order_dimensions(drawn, "FULLY_ALLOCATED", "PENDING")
        assert drawn["allocated_units"] == 30

        compressor = read_supply(compressor_id)
        assert compressor["version"] == 2, (
            "the successful draw advanced the token exactly once, got "
            f"version {compressor['version']}"
        )
        assert compressor["reserved_units"] == 30
        assert compressor["available_units"] == 20
        assert compressor["status"] == "ACTIVE"
        assert_supply_conservation(compressor)

        board = read_supply(board_id)
        assert board["reserved_units"] == 30
        assert board["available_units"] == 20
        assert_supply_conservation(board)


class TestBuiltUnitsAreALiveSum:
    """Two closed lots add up; the third, still in test, contributes nothing."""

    def test_twelve_and_eight_released_units_read_twenty_while_fourteen_wait(
        self, api, production_planner_headers, plant_admin_headers
    ):
        """On success released_to_stock_at is stamped from the logical clock and the
        lot's version increments; the platform then recomputes units_built_released
        as the summed quantity_units of its lots whose status is RELEASED_TO_STOCK,
        recomputes rolling_claim_rate_pct and warranty_posture per §3.9, and
        increments its own version. Run tests are listable and filterable by
        build_order_id, by test_cell_id, and by verdict, and like leak tests they are
        append-only.

        Design: Corner/cross_cutting_complexity_layers/c_platform_units_built_released_reconciles_across_two_lots
        """
        program = create_a1_program()
        cell = create_test_cell("CELL-1")
        platform = create_released_standard_a1_platform(program["id"])
        windows = (
            ("2026-08-05T08:00:00Z", "2026-08-05T09:00:00Z"),
            ("2026-08-05T09:30:00Z", "2026-08-05T10:30:00Z"),
            ("2026-08-05T11:00:00Z", "2026-08-05T12:00:00Z"),
        )
        lots = []
        for index, (quantity, leak_rate) in enumerate(((12, 1.10), (8, 1.30), (14, 1.40))):
            lot = create_build_order(
                platform["id"],
                quantity_units=quantity,
                scheduled_start_utc=f"2026-08-0{5 + index}T06:00:00Z",
            )
            braze_lot(lot["id"])
            record_helium_leak_test(lot["id"], leak_rate, technician_id="user-qt-1")
            charge_lot(lot["id"], 1600)
            run_test = record_run_test(
                lot["id"],
                cell["id"],
                window_start_utc=windows[index][0],
                window_end_utc=windows[index][1],
                measured_capacity_btuh=24000,
                measured_power_w=2020,
                measured_ambient_c=35.0,
                technician_id="user-qt-2",
            )
            assert run_test["verdict"] == "PASS"
            lots.append(lot)

        validate_success(
            api.release_to_stock(lots[0]["id"], production_planner_headers)
        )
        assert read_platform(platform["id"])["units_built_released"] == 12

        second = validate_success(
            api.release_to_stock(lots[1]["id"], production_planner_headers)
        )
        assert second["status"] == "RELEASED_TO_STOCK"

        stored_platform = read_platform(platform["id"])
        assert stored_platform["units_built_released"] == 20, (
            "the sum is over released lots only, not 34, got "
            f"{stored_platform['units_built_released']}"
        )
        assert stored_platform["units_shipped_total"] == 0
        assert float(stored_platform["rolling_claim_rate_pct"]) == pytest.approx(
            0.00, abs=0.005
        )

        third = read_build_order(lots[2]["id"])
        assert third["status"] == "RUN_PASSED"
        assert third["latest_run_verdict"] == "PASS"

        cell_tests, cell_meta = validate_paginated(
            api.list_test_cell_run_tests(cell["id"], plant_admin_headers)
        )
        assert cell_meta["total_count"] == 3
        for record in cell_tests:
            assert record["verdict"] == "PASS"
