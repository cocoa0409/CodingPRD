"""The design review loop, and the regional gates that decide whether kits may
be drawn for a region at all."""

from test_helpers import (
    allocate_payload,
    allocate_order,
    assert_certification_record,
    assert_instant_equals,
    assert_order_dimensions,
    assert_supply_conservation,
    create_a2l_program,
    create_released_high_a2l_platform,
    create_southeast_standard,
    create_supply_pair,
    file_certification,
    make_headers,
    place_order,
    read_order,
    read_platform,
    read_supply,
    reject_certification,
    setup_platform_returned_to_draft_and_revised,
    setup_two_regions_one_certified,
    submit_certification,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPlatformRevisionLoop:
    """Going round the review loop accumulates revision rounds."""

    def test_second_submission_raises_the_revision_round_to_two(
        self, api, design_engineer_headers
    ):
        """revision_round is not reset, so a design that goes round the
        DRAFT → ENG_REVIEW → DRAFT loop three times and is then resubmitted
        carries a revision_round of 4. On success, revision_round increases by
        one and submitted_by_user_id records the submitting X-User-ID.

        Design: Difficulty/non_linear_state_machine/platform_revision_loop_second_submit_raises_revision_round_to_2
        """
        scenario = setup_platform_returned_to_draft_and_revised(
            revised_max_charge_grams=1650
        )
        platform = scenario["platform"]
        assert platform["status"] == "DRAFT"
        assert platform["revision_round"] == 1, "one trip through review is recorded"
        assert platform["max_charge_grams"] == 1650

        resubmitted = validate_success(
            api.submit_engineering_review(platform["id"], design_engineer_headers)
        )

        assert resubmitted["status"] == "ENG_REVIEW"
        assert resubmitted["revision_round"] == 2, (
            f"the second submission is round 2, got {resubmitted['revision_round']}"
        )
        assert resubmitted["submitted_by_user_id"] == "user-de-1"
        assert (
            resubmitted["last_revision_notes"]
            == "Coil circuit revision required for the A2L charge limit"
        ), "the reviewer's notes survive the resubmission"

    def test_resubmitted_design_cannot_be_released_by_its_own_submitter(
        self, api, design_engineer_headers, reliability_engineer_headers
    ):
        """Releasing a platform, or returning it to draft, is refused when the
        caller's identifier equals the platform's submitted_by_user_id.

        Design: Difficulty/non_linear_state_machine/platform_revision_loop_second_submit_raises_revision_round_to_2
        """
        scenario = setup_platform_returned_to_draft_and_revised()
        platform_id = scenario["platform"]["id"]
        validate_success(
            api.submit_engineering_review(platform_id, design_engineer_headers)
        )

        refused = api.release_platform(
            platform_id, make_headers("user-de-1", "ReliabilityEngineer")
        )
        validate_error(refused, "ERR_SEGREGATION_OF_DUTIES", 409)
        assert read_platform(platform_id)["status"] == "ENG_REVIEW"

        released = validate_success(
            api.release_platform(platform_id, reliability_engineer_headers)
        )
        assert released["status"] == "RELEASED"
        assert_instant_equals(
            released["released_at"], "2026-08-01T00:00:00Z", "released_at"
        )
        assert released["revision_round"] == 2, "release does not disturb the round"

    def test_third_submission_from_review_is_refused_and_the_round_holds(
        self, api, design_engineer_headers
    ):
        """The platform must be in DRAFT, otherwise ERR_INVALID_PLATFORM_STATE,
        and the governing program must still be ACTIVE, otherwise
        ERR_PROGRAM_STATE_INVALID. Editing is refused with
        ERR_INVALID_PLATFORM_STATE from any other state, and a successful edit
        increments the platform's version.

        Design: Difficulty/non_linear_state_machine/platform_revision_loop_second_submit_raises_revision_round_to_2
        """
        scenario = setup_platform_returned_to_draft_and_revised()
        platform_id = scenario["platform"]["id"]
        validate_success(
            api.submit_engineering_review(platform_id, design_engineer_headers)
        )

        again = api.submit_engineering_review(platform_id, design_engineer_headers)
        validate_error(again, "ERR_INVALID_PLATFORM_STATE", 409)

        edit = api.update_product_platform(
            platform_id, {"max_charge_grams": 1700}, design_engineer_headers
        )
        validate_error(edit, "ERR_INVALID_PLATFORM_STATE", 409)

        platform = read_platform(platform_id)
        assert platform["status"] == "ENG_REVIEW"
        assert platform["revision_round"] == 2, "neither refusal advanced the round"
        assert platform["max_charge_grams"] == 1650, "the refused edit stored nothing"


class TestRejectedCertificationBlocksAllocation:
    """A decision two entities away decides whether a draw is allowed."""

    def test_rejected_filing_leaves_the_region_blocked_and_the_platform_unsalable(
        self, api, certification_engineer_headers
    ):
        """The platform's blocked_region_codes and salable_region_count are
        recomputed here too, and with its version incremented — but the region
        stays blocked, because after the rejection no certified record exists for
        it.

        Design: Difficulty/cross_entity_state_dependency/allocate_refused_because_certification_two_entities_away_was_rejected
        """
        create_southeast_standard()
        program = create_a2l_program()
        platform = create_released_high_a2l_platform(program["id"])
        record = file_certification(platform["id"], platform["version"])
        submit_certification(record["id"])
        rejected = reject_certification(record["id"])

        assert_certification_record(rejected)
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "SEER2 test report incomplete"

        blocked = read_platform(platform["id"])
        assert blocked["blocked_region_codes"] == ["SOUTHEAST"]
        assert blocked["salable_region_count"] == 0

        items, meta = validate_paginated(
            api.list_platform_certification_records(
                platform["id"],
                certification_engineer_headers,
                params={"region_code": "SOUTHEAST"},
            )
        )
        assert meta["total_count"] == 1, "the rejected filing is the only one on file"
        assert items[0]["status"] == "REJECTED"

    def test_draw_for_the_rejected_region_is_refused_and_pools_are_untouched(
        self, api, supply_planner_headers
    ):
        """The order's region_code must not appear in the platform's
        blocked_region_codes, otherwise ERR_REGION_NOT_CERTIFIED. For each
        participating standard, that standard's region_code is blocked for this
        platform when any one of four conditions holds: No certification record for
        this platform and that region carries status CERTIFIED.

        Design: Difficulty/cross_entity_state_dependency/allocate_refused_because_certification_two_entities_away_was_rejected
        """
        create_southeast_standard()
        program = create_a2l_program()
        platform = create_released_high_a2l_platform(program["id"])
        record = file_certification(platform["id"], platform["version"])
        submit_certification(record["id"])
        reject_certification(record["id"])

        compressor, control_board = create_supply_pair(
            compressor_units=100, board_units=100
        )
        order = place_order(
            platform["id"],
            requested_units=25,
            priority_score=55,
            distributor_code="DIST-SE-2",
        )

        response = api.allocate_distributor_order(
            order["id"], allocate_payload(compressor["version"]), supply_planner_headers
        )
        validate_error(response, "ERR_REGION_NOT_CERTIFIED", 409)

        stored_order = read_order(order["id"])
        assert_order_dimensions(stored_order, "UNALLOCATED", "PENDING")
        assert stored_order["allocated_units"] == 0

        _, lines_meta = validate_paginated(
            api.list_order_allocation_lines(order["id"], supply_planner_headers)
        )
        assert lines_meta["total_count"] == 0, "a refused draw creates no lines"

        for pool in (read_supply(compressor["id"]), read_supply(control_board["id"])):
            assert pool["version"] == 1, "the refused draw left the pool version alone"
            assert pool["reserved_units"] == 0
            assert pool["available_units"] == 100
            assert_supply_conservation(pool)


class TestStaleGuardPrecedesRegionGate:
    """Both stale and unsalable: the version guard answers first."""

    def test_stale_pool_version_on_an_unsalable_region_returns_the_stale_error(
        self, api, supply_planner_headers
    ):
        """A request that is both stale and aimed at a region the platform may
        not be sold into returns ERR_STALE_SUPPLY_VERSION with 412; the region
        gate is never reached.

        Design: Difficulty/priority_pair_validation_conflict/stale_supply_version_preempts_region_not_certified
        """
        scenario = setup_two_regions_one_certified()
        compressor = scenario["compressor"]
        assert compressor["version"] == 1

        southeast_order = place_order(
            scenario["platform"]["id"], requested_units=30, priority_score=80
        )
        allocate_order(southeast_order["id"], compressor["id"])
        assert read_supply(compressor["id"])["version"] == 2

        northeast_order = place_order(
            scenario["platform"]["id"],
            requested_units=20,
            priority_score=60,
            distributor_code="DIST-NE-1",
            region_code="NORTHEAST",
        )
        response = api.allocate_distributor_order(
            northeast_order["id"], allocate_payload(1), supply_planner_headers
        )
        validate_error(response, "ERR_STALE_SUPPLY_VERSION", 412)

    def test_current_pool_version_on_an_unsalable_region_returns_the_region_error(
        self, api, supply_planner_headers
    ):
        """On an allocation draw, the stale-version guard is checked before the
        regional-salability gate.

        Design: Difficulty/priority_pair_validation_conflict/stale_supply_version_preempts_region_not_certified
        """
        scenario = setup_two_regions_one_certified()
        compressor = scenario["compressor"]
        southeast_order = place_order(
            scenario["platform"]["id"], requested_units=30, priority_score=80
        )
        allocate_order(southeast_order["id"], compressor["id"])

        northeast_order = place_order(
            scenario["platform"]["id"],
            requested_units=20,
            priority_score=60,
            distributor_code="DIST-NE-1",
            region_code="NORTHEAST",
        )
        current_version = read_supply(compressor["id"])["version"]
        assert current_version == 2

        response = api.allocate_distributor_order(
            northeast_order["id"],
            allocate_payload(current_version),
            supply_planner_headers,
        )
        validate_error(response, "ERR_REGION_NOT_CERTIFIED", 409)

        platform = read_platform(scenario["platform"]["id"])
        assert platform["blocked_region_codes"] == ["NORTHEAST"]
        assert platform["salable_region_count"] == 1, (
            "two participating standards less one blocked region leaves one"
        )

    def test_neither_refusal_moves_units_out_of_the_pools(
        self, api, supply_planner_headers
    ):
        """If that row's version has advanced since the planner read it, the
        draw is rejected with ERR_STALE_SUPPLY_VERSION (HTTP 412 Precondition
        Failed).

        Design: Difficulty/priority_pair_validation_conflict/stale_supply_version_preempts_region_not_certified
        """
        scenario = setup_two_regions_one_certified()
        compressor = scenario["compressor"]
        control_board = scenario["control_board"]
        southeast_order = place_order(
            scenario["platform"]["id"], requested_units=30, priority_score=80
        )
        allocate_order(southeast_order["id"], compressor["id"])

        northeast_order = place_order(
            scenario["platform"]["id"],
            requested_units=20,
            priority_score=60,
            distributor_code="DIST-NE-1",
            region_code="NORTHEAST",
        )
        validate_error(
            api.allocate_distributor_order(
                northeast_order["id"], allocate_payload(1), supply_planner_headers
            ),
            "ERR_STALE_SUPPLY_VERSION",
            412,
        )
        validate_error(
            api.allocate_distributor_order(
                northeast_order["id"], allocate_payload(2), supply_planner_headers
            ),
            "ERR_REGION_NOT_CERTIFIED",
            409,
        )

        pool = read_supply(compressor["id"])
        assert pool["version"] == 2, "only the successful southeast draw moved the pool"
        assert pool["reserved_units"] == 30
        assert pool["available_units"] == 70
        assert_supply_conservation(pool)

        board_pool = read_supply(control_board["id"])
        assert board_pool["reserved_units"] == 30
        assert board_pool["available_units"] == 70

        stored = read_order(northeast_order["id"])
        assert_order_dimensions(stored, "UNALLOCATED", "PENDING")
        assert stored["allocated_units"] == 0
