"""Lifecycle gates: the two regulatory transitions, the platform's opening and
terminal states, a lot cancellation that touches only its own space, the
cross-dimension staging guard, and the compensation an effective fix performs."""

import pytest

from test_helpers import (
    assert_build_order,
    assert_instant_equals,
    assert_order_dimensions,
    assert_product_platform,
    assert_refrigerant_program,
    assert_supplier_corrective_action,
    assert_supply_conservation,
    assert_warehouse_reservation,
    cancel_build_order_payload,
    close_corrective_action,
    create_a1_program,
    create_a2l_program,
    create_build_order,
    create_released_standard_a1_platform,
    create_reservation,
    create_standard_a1_draft_platform,
    create_warehouse,
    find_open_corrective_action,
    high_a2l_platform_payload,
    open_corrective_action_via_third_claim,
    read_build_order,
    read_order,
    read_platform,
    read_reservation,
    read_supply,
    release_platform,
    retire_platform_payload,
    set_clock,
    setup_allocated_order,
    setup_platform_two_claims_below_threshold,
    submit_platform,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProgramExpiryTiming:
    """The deadline is a gate, not a formality: one day short is still refused."""

    def test_expiry_one_day_before_the_deadline_is_refused(self, api, plant_admin_headers):
        """The second transition moves the program SELL_THROUGH to EXPIRED. It
        requires the program to be in SELL_THROUGH, otherwise
        ERR_PROGRAM_STATE_INVALID, and the logical clock to have reached or passed
        sell_through_deadline_utc, otherwise ERR_SELL_THROUGH_DEADLINE_NOT_REACHED.

        Design: Corner/state_machines/c_program_expire_before_deadline_rejected
        """
        program = create_a1_program(
            manufacture_cutoff_utc="2026-10-01T00:00:00Z",
            sell_through_deadline_utc="2027-04-01T00:00:00Z",
        )
        set_clock("2026-10-02T00:00:00Z")
        entered = validate_success(
            api.enter_sell_through(program["id"], plant_admin_headers)
        )
        assert entered["status"] == "SELL_THROUGH"
        set_clock("2027-03-31T00:00:00Z")

        response = api.expire_refrigerant_program(program["id"], plant_admin_headers)
        validate_error(response, "ERR_SELL_THROUGH_DEADLINE_NOT_REACHED", 409)

        stored = validate_success(
            api.get_refrigerant_program(program["id"], plant_admin_headers)
        )
        assert_refrigerant_program(stored)
        assert stored["status"] == "SELL_THROUGH", "the refused call moved nothing"
        assert stored["expired_at"] is None
        assert_instant_equals(
            stored["sell_through_entered_at"],
            "2026-10-02T00:00:00Z",
            "sell_through_entered_at",
        )


class TestSellThroughEntryTiming:
    """While manufacturing is still legal the cascade cannot be started."""

    def test_entry_before_the_manufacture_cutoff_leaves_the_platform_released(
        self, api, plant_admin_headers
    ):
        """It requires that the program still be ACTIVE, otherwise
        ERR_PROGRAM_STATE_INVALID, and that the logical clock have reached or
        passed manufacture_cutoff_utc, otherwise ERR_MANUFACTURE_CUTOFF_NOT_REACHED.
        Then the depth-four cascade of §2.9 runs, each hop caused by the hop above
        it.

        Design: Corner/state_machines/c_program_enter_sell_through_before_cutoff_rejected
        """
        program = create_a1_program(
            manufacture_cutoff_utc="2026-10-01T00:00:00Z",
            sell_through_deadline_utc="2027-04-01T00:00:00Z",
        )
        platform = create_released_standard_a1_platform(program["id"])
        assert platform["status"] == "RELEASED"

        response = api.enter_sell_through(program["id"], plant_admin_headers)
        validate_error(response, "ERR_MANUFACTURE_CUTOFF_NOT_REACHED", 409)

        stored = validate_success(
            api.get_refrigerant_program(program["id"], plant_admin_headers)
        )
        assert stored["status"] == "ACTIVE"
        assert stored["sell_through_entered_at"] is None
        assert stored["affected_platform_count"] == 1

        assert read_platform(platform["id"])["status"] == "RELEASED", (
            "the first hop of the cascade did not fire"
        )


class TestPlatformOpeningState:
    """Every counter on a freshly created design reads its declared default."""

    def test_created_platform_is_draft_with_every_counter_at_zero(
        self, api, design_engineer_headers, plant_admin_headers
    ):
        """A new platform opens in DRAFT with revision_round at 0,
        blocked_region_codes empty, salable_region_count at 0, warranty_posture at
        OK, rolling_claim_rate_pct at 0.00, units_built_released at 0,
        units_shipped_total at 0, and submitted_by_user_id, released_at, and
        last_revision_notes all null. The naming program's affected_platform_count
        is recomputed as part of the same write.

        Design: Corner/state_machines/c_platform_starts_in_draft_with_zeroed_counters
        """
        program = create_a2l_program()

        platform = validate_success(
            api.create_product_platform(
                high_a2l_platform_payload(program["id"]), design_engineer_headers
            ),
            201,
        )

        assert_product_platform(platform)
        assert platform["status"] == "DRAFT"
        assert platform["revision_round"] == 0
        assert platform["last_revision_notes"] is None
        assert platform["submitted_by_user_id"] is None
        assert platform["released_at"] is None
        assert platform["blocked_region_codes"] == []
        assert platform["salable_region_count"] == 0
        assert platform["warranty_posture"] == "OK"
        assert float(platform["rolling_claim_rate_pct"]) == pytest.approx(
            0.00, abs=0.005
        )
        assert platform["units_built_released"] == 0
        assert platform["units_shipped_total"] == 0

        stored_program = validate_success(
            api.get_refrigerant_program(program["id"], plant_admin_headers)
        )
        assert stored_program["affected_platform_count"] == 1, (
            "the counter is recomputed inside the same request cycle"
        )


class TestRetiredPlatformIsLockedDown:
    """Neither a fresh submission nor a second retirement is admitted."""

    def test_retired_platform_refuses_a_new_submission_and_a_second_retire(
        self, api, plant_admin_headers, design_engineer_headers
    ):
        """It is admitted from RELEASED or RESTRICTED only — any other state
        yields ERR_INVALID_PLATFORM_STATE. The platform must be in DRAFT, otherwise
        ERR_INVALID_PLATFORM_STATE, and the governing program must still be ACTIVE,
        otherwise ERR_PROGRAM_STATE_INVALID. RETIRED is terminal. A retired
        platform is permanently unsalable everywhere, which condition (4) of the
        salability rule below encodes directly.

        Design: Corner/state_machines/c_retired_platform_rejects_new_submission
        """
        program = create_a1_program()
        platform = create_released_standard_a1_platform(program["id"])
        retired = validate_success(
            api.retire_platform(
                platform["id"],
                retire_platform_payload("Model line discontinued"),
                plant_admin_headers,
            )
        )
        assert retired["status"] == "RETIRED"

        resubmission = api.submit_engineering_review(
            platform["id"], design_engineer_headers
        )
        validate_error(resubmission, "ERR_INVALID_PLATFORM_STATE", 409)

        second_retire = api.retire_platform(
            platform["id"],
            retire_platform_payload("Duplicate retirement attempt"),
            plant_admin_headers,
        )
        validate_error(second_retire, "ERR_INVALID_PLATFORM_STATE", 409)

        stored = read_platform(platform["id"])
        assert stored["status"] == "RETIRED", "neither refused call advanced anything"
        assert stored["revision_round"] == 1
        assert stored["salable_region_count"] == 0


class TestReleaseIsNotIdempotent:
    """Replaying the release is a state error, and released_at keeps its value."""

    def test_second_release_is_refused_and_does_not_restamp_released_at(
        self, api, reliability_engineer_2_headers
    ):
        """Releasing the design advances ENG_REVIEW to RELEASED under the same two
        checks plus one more — the governing program must still be ACTIVE,
        otherwise ERR_PROGRAM_STATE_INVALID — and stamps released_at from the
        logical clock before recomputing blocked_region_codes and
        salable_region_count by the rule in §3.4. Only a RELEASED platform can
        receive new build lots; only a RELEASED or RESTRICTED platform can receive
        new distributor orders or new certification filings.

        Design: Corner/state_machines/c_second_platform_release_returns_state_error
        """
        program = create_a1_program()
        draft = create_standard_a1_draft_platform(program["id"])
        submit_platform(draft["id"])
        released = release_platform(draft["id"])
        assert released["status"] == "RELEASED"
        assert_instant_equals(
            released["released_at"], "2026-08-01T00:00:00Z", "released_at"
        )
        first_version = released["version"]

        set_clock("2026-08-02T00:00:00Z")
        replay = api.release_platform(draft["id"], reliability_engineer_2_headers)
        validate_error(replay, "ERR_INVALID_PLATFORM_STATE", 409)

        stored = read_platform(draft["id"])
        assert stored["status"] == "RELEASED"
        assert_instant_equals(
            stored["released_at"], "2026-08-01T00:00:00Z", "released_at"
        )
        assert stored["version"] == first_version, "the refused replay bumped nothing"


class TestLotCancellationReleasesOnlyItsOwnSpace:
    """One lot's cancellation leaves the neighbouring lot's pallets alone."""

    def test_cancelling_one_lot_leaves_the_second_lots_twelve_pallets_standing(
        self, api, production_planner_headers
    ):
        """An optional reason may accompany the request and is stored in
        closed_reason; when the cancellation instead arrives from the platform
        retirement cascade, closed_reason is set to PLATFORM_RETIRED. Either way
        every ACTIVE warehouse reservation of the lot becomes RELEASED with
        release_reason set to BUILD_CANCELLED, each touched warehouse recomputes
        pallets_reserved_current, and the versions of the lot, of each released
        reservation, and of each touched warehouse all increment.

        Design: Corner/state_machines/c_cancel_draft_preseason_lot_releases_reservation
        """
        program = create_a1_program()
        warehouse = create_warehouse("WH-1", 50)
        platform = create_released_standard_a1_platform(program["id"])
        lot_a = create_build_order(
            platform["id"],
            quantity_units=36,
            scheduled_start_utc="2026-11-02T06:00:00Z",
            is_preseason=True,
        )
        lot_b = create_build_order(
            platform["id"],
            quantity_units=24,
            scheduled_start_utc="2026-11-02T06:00:00Z",
            is_preseason=True,
        )
        reservation_a = create_reservation(
            warehouse["id"], lot_a["id"], "2026-11-02", "2026-11-20", 18
        )
        reservation_b = create_reservation(
            warehouse["id"], lot_b["id"], "2026-11-02", "2026-11-20", 12
        )
        set_clock("2026-11-05T00:00:00Z")

        cancelled = validate_success(
            api.cancel_build_order(
                lot_a["id"],
                cancel_build_order_payload("Pre-season plan trimmed"),
                production_planner_headers,
            )
        )
        assert_build_order(cancelled)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["closed_reason"] == "Pre-season plan trimmed"

        released = read_reservation(reservation_a["id"])
        assert_warehouse_reservation(released)
        assert released["status"] == "RELEASED"
        assert released["release_reason"] == "BUILD_CANCELLED"
        assert_instant_equals(
            released["released_at"], "2026-11-05T00:00:00Z", "released_at"
        )

        survivor = read_reservation(reservation_b["id"])
        assert survivor["status"] == "ACTIVE", "only the cancelled lot's space is given up"
        assert survivor["released_at"] is None

        stored_warehouse = validate_success(
            api.get_warehouse(warehouse["id"], production_planner_headers)
        )
        assert stored_warehouse["pallets_reserved_current"] == 12

        occupancy = validate_success(
            api.get_warehouse_occupancy(
                warehouse["id"],
                production_planner_headers,
                params={"on_date": "2026-11-05"},
            )
        )
        assert occupancy["occupancy_units"] == 12
        assert read_build_order(lot_b["id"])["status"] == "DRAFT"


class TestStagingIsGuardedByAllocation:
    """Logistics may not run ahead of supply, and the refusal changes nothing."""

    def test_partially_allocated_order_cannot_be_staged(
        self, api, production_planner_headers, supply_planner_headers
    ):
        """Staging advances PENDING to STAGED and carries the only cross-dimension
        guard in the system: the order's fulfillment_status must be PENDING and its
        allocation_status must be FULLY_ALLOCATED, and either failure is refused
        with ERR_ORDER_STATE_INVALID. Logistics may not run ahead of supply.
        Success stamps staged_at from the logical clock, increments version, and
        leaves allocation_status exactly where it was.

        Design: Corner/state_machines/c_stage_partially_allocated_order_returns_state_error
        """
        scenario = setup_allocated_order(
            requested_units=40, compressor_units=20, board_units=20, priority_score=70
        )
        order_id = scenario["order"]["id"]
        assert_order_dimensions(scenario["order"], "PARTIALLY_ALLOCATED", "PENDING")
        assert scenario["order"]["allocated_units"] == 20

        response = api.stage_distributor_order(order_id, production_planner_headers)
        validate_error(response, "ERR_ORDER_STATE_INVALID", 409)

        order = read_order(order_id)
        assert_order_dimensions(order, "PARTIALLY_ALLOCATED", "PENDING")
        assert order["allocated_units"] == 20
        assert order["staged_at"] is None

        for pool_id in (scenario["compressor"]["id"], scenario["control_board"]["id"]):
            pool = read_supply(pool_id)
            assert pool["status"] == "EXHAUSTED"
            assert pool["reserved_units"] == 20
            assert pool["available_units"] == 0
            assert_supply_conservation(pool)

        lines, lines_meta = validate_paginated(
            api.list_order_allocation_lines(order_id, supply_planner_headers)
        )
        assert lines_meta["total_count"] == 2
        for line in lines:
            assert line["status"] == "RESERVED"
            assert line["units"] == 20


class TestEffectiveClosureCompensatesEverything:
    """An effective fix restores the pool, closes the claims, and clears the rate."""

    def test_closing_the_action_effective_restores_101_units_and_closes_the_claims(
        self, api, supply_planner_headers, warranty_analyst_headers
    ):
        """A resolution of EFFECTIVE moves the action OPEN to CLOSED_EFFECTIVE.
        Its resolution is stored as EFFECTIVE, closed_by_user_id and closed_at are
        stamped from the caller and the logical clock, and its version increments.
        The governed pool moves DERATED to ACTIVE — permitted only when no other
        corrective action with status OPEN still cites that pool — with derate_pct
        returned to 0, effective_allocatable_units restored to the full
        total_allocatable_units, available_units recomputed, and its version
        incremented. Every cited claim whose status is LINKED_TO_CAPA moves
        LINKED_TO_CAPA to CLOSED with its version incremented, which drops it out
        of the counted claim population.

        Design: Corner/state_machines/c_capa_closed_effective_restores_supply_and_closes_claims
        """
        scenario = setup_platform_two_claims_below_threshold(
            quantity_units=60, compressor_units=101
        )
        platform_id = scenario["platform"]["id"]
        compressor_id = scenario["compressor"]["id"]
        open_corrective_action_via_third_claim(platform_id, 40200)

        derated = read_supply(compressor_id)
        assert derated["status"] == "DERATED"
        assert derated["effective_allocatable_units"] == 75, (
            "a quarter cut of 101 committed units truncates to 75"
        )

        action = find_open_corrective_action(compressor_id)
        closed = close_corrective_action(
            action["id"],
            resolution="EFFECTIVE",
            effectiveness_note=(
                "Supplier replaced the crimp tooling; 30-unit audit lot clean"
            ),
            engineer_id="user-re-2",
        )
        assert_supplier_corrective_action(closed)
        assert closed["status"] == "CLOSED_EFFECTIVE"
        assert closed["resolution"] == "EFFECTIVE"
        assert closed["closed_by_user_id"] == "user-re-2"
        assert_instant_equals(closed["closed_at"], "2026-08-01T00:00:00Z", "closed_at")

        pool = read_supply(compressor_id)
        assert pool["status"] == "ACTIVE"
        assert pool["derate_pct"] == 0
        assert pool["effective_allocatable_units"] == 101
        assert pool["available_units"] == 101
        assert_supply_conservation(pool)

        claims, claims_meta = validate_paginated(
            api.list_warranty_claims(
                warranty_analyst_headers, params={"platform_id": platform_id}
            )
        )
        assert claims_meta["total_count"] == 3
        for claim in claims:
            assert claim["status"] == "CLOSED"

        platform = read_platform(platform_id)
        assert float(platform["rolling_claim_rate_pct"]) == pytest.approx(
            0.00, abs=0.005
        ), "closed claims leave the counted population"
        assert platform["warranty_posture"] == "OK"
        assert platform["units_built_released"] == 60, (
            "the compensation did not disturb the production counter"
        )

        _, open_meta = validate_paginated(
            api.list_supply_corrective_actions(
                compressor_id, supply_planner_headers, params={"status": "OPEN"}
            )
        )
        assert open_meta["total_count"] == 0
