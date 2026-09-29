"""Endpoint breadth: round trips, action endpoints and computed reads.

A plain create-read-list triple on traffic rights, an action endpoint whose
effect is immediately visible to a downstream gate, a bulk action that rewrites
a whole manifest in one call, a link-writing action that must land on both sides
of a reference, and a read-only projection whose seven fields are all derived.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_route_authority,
    assert_score_matches_counters,
    assert_slot_holding,
    assert_timestamp_equals,
    assign_aircraft,
    create_carrier,
    create_flight_leg,
    create_flight_leg_payload,
    create_route_authority,
    create_route_authority_payload,
    create_schedule_version,
    create_slot_holding,
    read_aircraft,
    read_holding,
    read_leg,
    read_rotation,
    read_route_authority,
    read_version,
    setup_domestic_rotation_base,
    setup_monday_series_schedule,
    setup_reference_data,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_version,
    TEST_USERS,
)

ADMIN = TEST_USERS["system_admin_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


# ─── Endpoint 1: the traffic-rights CRUD triple ───────────────────────────

def _authority_payload(carrier_id, dest_country_code, freedom_type, cap):
    return create_route_authority_payload(
        carrier_id,
        "DE",
        dest_country_code,
        freedom_type=freedom_type,
        weekly_frequency_cap=cap,
        granted_from_utc="2026-01-01T00:00:00.000Z",
        granted_until_utc="2027-12-31T23:59:59.000Z",
    )


def _two_granted_authorities():
    """One carrier holding a Portuguese and an American right."""
    carrier = create_carrier()
    return {
        "carrier": carrier,
        "pt": create_route_authority(
            carrier["id"],
            "DE",
            "PT",
            freedom_type="THIRD_FOURTH",
            weekly_frequency_cap=7,
            granted_from_utc="2026-01-01T00:00:00.000Z",
            granted_until_utc="2027-12-31T23:59:59.000Z",
        ),
        "us": create_route_authority(
            carrier["id"],
            "DE",
            "US",
            freedom_type="FIFTH",
            weekly_frequency_cap=3,
            granted_from_utc="2026-01-01T00:00:00.000Z",
            granted_until_utc="2027-12-31T23:59:59.000Z",
        ),
    }


class TestRouteAuthorityRoundTripsThroughCreateReadAndList:
    """Two grants for one carrier, read back one at a time and then filtered."""

    def test_each_grant_is_created_active_and_reads_back_unmodified(self):
        """Every declared input survives the round trip to the read endpoint.

        PRD §3.2: "The authority sets a `weekly_frequency_cap` of at least 1,
        being the maximum number of non-cancelled legs a single schedule version
        may place on that country pair inside one ISO week, and a validity window
        from `granted_from_utc` through `granted_until_utc`, where the end instant
        must be strictly later than the start."

        PRD §3.2: "Every authority is created `ACTIVE` with `suspension_reason`
        null."

        Design: Corner/endpoints/route_authority_create_read_and_filtered_list_round_trip
        """
        carrier = create_carrier()

        for dest, freedom_type, cap in (("PT", "THIRD_FOURTH", 7), ("US", "FIFTH", 3)):
            created = validate_success(
                api_client.create_route_authority(
                    _authority_payload(carrier["id"], dest, freedom_type, cap), ADMIN
                ),
                expected_status=201,
            )
            assert_route_authority(created)
            assert created["status"] == "ACTIVE"
            assert created["suspension_reason"] is None
            assert created["version"] == 1

        rows, meta = validate_paginated(
            api_client.list_route_authorities(
                OFFICER, params={"dest_country_code": "US"}
            )
        )
        assert meta["total_count"] == 1

        american = read_route_authority(rows[0]["id"], OFFICER)
        assert american["freedom_type"] == "FIFTH"
        assert american["weekly_frequency_cap"] == 3
        assert american["origin_country_code"] == "DE"
        assert american["dest_country_code"] == "US"

    def test_each_declared_filter_narrows_the_list(self):
        """A list endpoint that ignores its filters answers 2 to the narrow
        query.

        PRD §4: "List route authorities, filterable by carrier, either country,
        freedom type and status."

        Design: Corner/endpoints/route_authority_create_read_and_filtered_list_round_trip
        """
        world = _two_granted_authorities()

        both, both_meta = validate_paginated(
            api_client.list_route_authorities(
                OFFICER,
                params={
                    "carrier_id": world["carrier"]["id"],
                    "status": "ACTIVE",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert both_meta["total_count"] == 2
        assert {row["id"] for row in both} == {world["pt"]["id"], world["us"]["id"]}

        narrow, narrow_meta = validate_paginated(
            api_client.list_route_authorities(
                OFFICER,
                params={"dest_country_code": "PT", "limit": 10, "offset": 0},
            )
        )
        assert narrow_meta["total_count"] == 1
        assert narrow[0]["id"] == world["pt"]["id"]

        assert_timestamp_equals(
            read_route_authority(world["pt"]["id"], OFFICER)["granted_until_utc"],
            "2027-12-31T23:59:59Z",
            "granted_until_utc",
        )


# ─── Endpoint 2: suspension as a forward-looking guard ────────────────────

def _granted_pair_and_an_empty_plan():
    """A live DE-PT right, an empty version and the leg that would use it."""
    ref = setup_reference_data(("FRA", "LIS"))
    ref["authority"] = create_route_authority(
        ref["carrier"]["id"], "DE", "PT", weekly_frequency_cap=7
    )
    ref["version"] = create_schedule_version(
        ref["carrier"]["id"], ref["season"]["id"], version_label="W26-A1"
    )
    ref["leg_payload"] = create_flight_leg_payload(
        ref["version"]["id"],
        ref["stations"]["FRA"]["id"],
        ref["stations"]["LIS"]["id"],
        "2026-11-02T08:00:00.000Z",
        "2026-11-02T11:00:00.000Z",
        flight_number="HX600",
    )
    return ref


class TestSuspendingARouteAuthorityBarsTheNextLegOnThatPair:
    """One suspend call, then the same leg the right used to authorise."""

    def test_suspension_records_its_reason_and_bumps_the_version(self):
        """The reason travels from the request body onto the stored row.

        PRD §3.2: "A `SystemAdmin` may suspend it with a `reason`, moving
        `status` from `ACTIVE` to `SUSPENDED` and recording that reason on
        `suspension_reason`."

        Design: Corner/endpoints/suspending_a_route_authority_immediately_blocks_new_legs_on_that_pair
        """
        world = _granted_pair_and_an_empty_plan()

        suspended = validate_success(
            api_client.suspend_route_authority(
                world["authority"]["id"], {"reason": "BILATERAL_RENEGOTIATION"}, ADMIN
            )
        )
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "BILATERAL_RENEGOTIATION"
        assert suspended["version"] == 2

        assert read_route_authority(world["authority"]["id"], OFFICER)["status"] == (
            "SUSPENDED"
        )

    def test_the_next_leg_on_that_country_pair_is_refused_as_inactive(self):
        """A suspended right is present but unusable, so the refusal names
        `ERR_ROUTE_AUTHORITY_INACTIVE` rather than a missing-authority error.

        PRD §3.2: "It is a forward-looking guard - every *subsequent* leg
        creation on that country pair is refused with
        `ERR_ROUTE_AUTHORITY_INACTIVE`, while legs already in the plan stay
        exactly as they are."

        Design: Corner/endpoints/suspending_a_route_authority_immediately_blocks_new_legs_on_that_pair
        """
        world = _granted_pair_and_an_empty_plan()
        validate_success(
            api_client.suspend_route_authority(
                world["authority"]["id"], {"reason": "BILATERAL_RENEGOTIATION"}, ADMIN
            )
        )

        validate_error(
            api_client.create_flight_leg(world["leg_payload"], world["planner"]),
            ApiErrorId.ERR_ROUTE_AUTHORITY_INACTIVE,
            expected_status=422,
        )

        version = read_version(world["version"]["id"], OFFICER)
        assert version["leg_count"] == 0
        assert version["schedule_compliance_score"] == 100.00
        assert version["compliance_state"] == "CLEAN"

        _, meta = validate_paginated(
            api_client.list_route_authorities(
                OFFICER,
                params={"carrier_id": world["carrier"]["id"], "status": "ACTIVE"},
            )
        )
        assert meta["total_count"] == 0


# ─── Endpoint 3: withdrawal as a one-call manifest rewrite ────────────────

def _plan_with_one_attached_and_one_bare_leg():
    """Two Monday legs against a five-week series, only the first slotted."""
    return setup_monday_series_schedule(
        leg_count=2,
        series_weeks=5,
        attach_count=1,
        assign=False,
        version_label="W26-B1",
    )


class TestWithdrawingAVersionCancelsEveryLegAndReleasesEverySlot:
    """One withdraw call seen from the version, the legs and the series."""

    def test_the_blocked_starting_point_is_what_the_withdrawal_dismantles(self):
        """Before the call: one bare leg and an under-used series, so the plan
        is already blocked on both counts.

        PRD §3.5: "`at_risk_of_loss` is true exactly when the series is still
        `HELD`, `attached_operations` is at least 1, and
        `utilization_pct_as_filed` is strictly below 80.00."

        PRD §3.4: "`at_risk_slot_count` is the number of **distinct** slot
        series referenced by this version's non-cancelled legs, through either
        `departure_slot_holding_id` or `arrival_slot_holding_id`, whose
        `at_risk_of_loss` is true."

        Design: Corner/endpoints/withdrawing_a_version_cancels_every_leg_and_releases_every_slot_in_one_call
        """
        world = _plan_with_one_attached_and_one_bare_leg()

        holding = read_holding(world["holding"]["id"], OFFICER)
        assert_slot_holding(holding)
        assert holding["planned_operations"] == 5
        assert holding["attached_operations"] == 1
        assert holding["utilization_pct_as_filed"] == 20.00
        assert holding["at_risk_of_loss"] is True

        version = read_version(world["version"]["id"], OFFICER)
        assert version["leg_count"] == 2
        assert version["unslotted_leg_count"] == 1
        assert version["at_risk_slot_count"] == 1
        assert version["schedule_compliance_score"] == 77.00
        assert version["compliance_state"] == "BLOCKED"
        assert_score_matches_counters(version)

    def test_every_leg_lands_in_cancelled_with_the_literal_reason(self):
        """The cascade rewrites both legs, including the one that never held a
        slot, and nulls the slot reference on the one that did.

        PRD §3.4: "Withdrawal drives `filing_status` to `WITHDRAWN`, which is
        terminal, and cascades in two steps: every non-cancelled leg of the
        version moves to `CANCELLED` with `cancellation_reason` set to the
        literal `SCHEDULE_WITHDRAWN`, and each of those legs detaches from both
        `departure_slot_holding_id` and `arrival_slot_holding_id`"

        Design: Corner/endpoints/withdrawing_a_version_cancels_every_leg_and_releases_every_slot_in_one_call
        """
        world = _plan_with_one_attached_and_one_bare_leg()

        withdrawn = validate_success(
            api_client.withdraw_schedule_version(
                world["version"]["id"],
                {"reason": "COMMERCIAL_WITHDRAWAL"},
                world["planner"],
            )
        )
        assert withdrawn["filing_status"] == "WITHDRAWN"
        assert withdrawn["version"] == world["version"]["version"] + 1

        for leg in world["legs"]:
            after = read_leg(leg["id"], OFFICER)
            assert after["status"] == "CANCELLED"
            assert after["cancellation_reason"] == "SCHEDULE_WITHDRAWN"
            assert after["departure_slot_holding_id"] is None
            assert after["arrival_slot_holding_id"] is None

    def test_the_released_series_is_still_held_but_no_longer_at_risk(self):
        """Detaching every operation returns the series to zero utilisation
        without taking it away from the carrier, and the emptied manifest
        scores a clean 100.00.

        PRD §3.4: "each of those legs detaches from both
        `departure_slot_holding_id` and `arrival_slot_holding_id`, which in turn
        recomputes each affected series' `attached_operations`,
        `utilization_pct_as_filed` and `at_risk_of_loss`."

        PRD §3.4: "`leg_count` is the number of legs whose
        `schedule_version_id` is this version **including cancelled ones**"

        Design: Corner/endpoints/withdrawing_a_version_cancels_every_leg_and_releases_every_slot_in_one_call
        """
        world = _plan_with_one_attached_and_one_bare_leg()
        withdraw_version(world["carrier"]["id"], world["version"]["id"])

        holding = read_holding(world["holding"]["id"], OFFICER)
        assert holding["holding_status"] == "HELD"
        assert holding["attached_operations"] == 0
        assert holding["utilization_pct_as_filed"] == 0.00
        assert holding["at_risk_of_loss"] is False

        version = read_version(world["version"]["id"], OFFICER)
        assert version["leg_count"] == 2
        assert version["unslotted_leg_count"] == 0
        assert version["at_risk_slot_count"] == 0
        assert version["schedule_compliance_score"] == 100.00
        assert version["compliance_state"] == "CLEAN"
        assert_score_matches_counters(version)

    def test_a_second_withdrawal_is_refused_on_the_terminal_state(self):
        """`WITHDRAWN` is terminal, and the refusal is the target-state error
        rather than anything about the legs it already cancelled.

        PRD §3.4: "It is permitted from `DRAFT` and from `VALIDATED` only"

        PRD §2.9: "**Target-resource state.** `ERR_SCHEDULE_VERSION_STATE_INVALID`,
        then `ERR_SCHEDULE_VERSION_NOT_READY`, then `ERR_SCHEDULE_BLOCKED`, then
        `ERR_FLIGHT_LEG_STATE_INVALID`"

        Design: Corner/endpoints/withdrawing_a_version_cancels_every_leg_and_releases_every_slot_in_one_call
        """
        world = _plan_with_one_attached_and_one_bare_leg()
        withdraw_version(world["carrier"]["id"], world["version"]["id"])

        validate_error(
            api_client.withdraw_schedule_version(
                world["version"]["id"],
                {"reason": "COMMERCIAL_WITHDRAWAL"},
                world["planner"],
            ),
            ApiErrorId.ERR_SCHEDULE_VERSION_STATE_INVALID,
            expected_status=409,
        )

        assert read_version(world["version"]["id"], OFFICER)["filing_status"] == (
            "WITHDRAWN"
        )


# ─── Endpoint 4: attach-slot writes the link on both sides ────────────────

def _monday_series_with_a_monday_and_a_tuesday_leg():
    """One Monday-only 08:00Z series and two legs, only one of them a Monday."""
    ref = setup_reference_data(("FRA", "MUC"))
    ref["holding"] = create_slot_holding(
        ref["stations"]["FRA"]["id"],
        ref["season"]["id"],
        ref["carrier"]["id"],
        movement_type="DEPARTURE",
        slot_time_utc="2026-11-02T08:00:00.000Z",
        days_of_week="1",
        series_weeks=5,
    )
    ref["version"] = create_schedule_version(
        ref["carrier"]["id"], ref["season"]["id"], version_label="W26-L1"
    )
    ref["monday"] = create_flight_leg(
        ref["carrier"]["id"],
        ref["version"]["id"],
        ref["stations"]["FRA"]["id"],
        ref["stations"]["MUC"]["id"],
        "2026-11-02T08:00:00.000Z",
        "2026-11-02T09:00:00.000Z",
        flight_number="HX101",
    )
    ref["tuesday"] = create_flight_leg(
        ref["carrier"]["id"],
        ref["version"]["id"],
        ref["stations"]["FRA"]["id"],
        ref["stations"]["MUC"]["id"],
        "2026-11-03T08:00:00.000Z",
        "2026-11-03T09:00:00.000Z",
        flight_number="HX105",
    )
    return ref


class TestAttachingASlotLinksTheLegAndTheSeriesOnBothSides:
    """The same series offered to the wrong weekday and then to the right one."""

    def test_the_weekday_half_of_the_time_match_refuses_the_tuesday_leg(self):
        """Matching times of day are not enough - the ISO weekday of the leg
        must appear in the series mask, and nothing is written when it does not.

        PRD §3.5: "the UTC time-of-day of `slot_time_utc` must equal the UTC
        time-of-day of the leg's `dep_utc` for a `DEPARTURE` or its `arr_utc`
        for an `ARRIVAL`, and the ISO weekday of that same instant, numbered 1
        for Monday through 7 for Sunday, must be one of the digits in
        `days_of_week`; a failure on either half is `ERR_SLOT_TIME_MISMATCH`."

        Design: Corner/endpoints/attaching_a_slot_links_the_leg_and_the_holding_on_both_sides
        """
        world = _monday_series_with_a_monday_and_a_tuesday_leg()

        validate_error(
            api_client.attach_slot(
                world["tuesday"]["id"],
                {
                    "slot_holding_id": world["holding"]["id"],
                    "movement_type": "DEPARTURE",
                },
                world["planner"],
            ),
            ApiErrorId.ERR_SLOT_TIME_MISMATCH,
            expected_status=422,
        )

        assert read_leg(world["tuesday"]["id"], OFFICER)[
            "departure_slot_holding_id"
        ] is None
        assert read_holding(world["holding"]["id"], OFFICER)["attached_operations"] == 0

    def test_the_accepted_attach_is_visible_from_the_leg_and_from_the_series(self):
        """One call writes `departure_slot_holding_id` on the leg and moves the
        series' three derived figures, while the tail-less leg stays `DRAFT`.

        PRD §3.5: "A `NetworkPlanner` names the `slot_holding_id` and the
        `movement_type` the holding is to back, and on success either
        `departure_slot_holding_id` or `arrival_slot_holding_id` is written on
        the leg."

        PRD §3.5: "a leg in `DRAFT` with no aircraft yet stays `DRAFT` however
        many slots are attached to it"

        Design: Corner/endpoints/attaching_a_slot_links_the_leg_and_the_holding_on_both_sides
        """
        world = _monday_series_with_a_monday_and_a_tuesday_leg()

        attached = validate_success(
            api_client.attach_slot(
                world["monday"]["id"],
                {
                    "slot_holding_id": world["holding"]["id"],
                    "movement_type": "DEPARTURE",
                },
                world["planner"],
            )
        )
        assert attached["departure_slot_holding_id"] == world["holding"]["id"]
        assert attached["arrival_slot_holding_id"] is None
        assert attached["status"] == "DRAFT"
        assert attached["assigned_aircraft_id"] is None
        assert attached["version"] == world["monday"]["version"] + 1

        holding = read_holding(world["holding"]["id"], OFFICER)
        assert holding["attached_operations"] == 1
        assert holding["utilization_pct_as_filed"] == 20.00
        assert holding["at_risk_of_loss"] is True
        assert holding["credited_operations"] == 0
        assert holding["utilization_pct"] == 0.00

        rows, meta = validate_paginated(
            api_client.list_flight_legs(
                OFFICER,
                params={"departure_slot_holding_id": world["holding"]["id"]},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == world["monday"]["id"]

    def test_the_still_unslotted_sibling_keeps_the_version_blocked(self):
        """The accepted attach re-derives the version, but the Tuesday leg is
        still bare and the newly at-risk series now costs 15.00 as well.

        PRD §3.5: "A successful attach recomputes the series'
        `attached_operations`, `utilization_pct_as_filed` and `at_risk_of_loss`,
        and then the owning version's `unslotted_leg_count`,
        `at_risk_slot_count`, `schedule_compliance_score` and
        `compliance_state`."

        Design: Corner/endpoints/attaching_a_slot_links_the_leg_and_the_holding_on_both_sides
        """
        world = _monday_series_with_a_monday_and_a_tuesday_leg()
        validate_success(
            api_client.attach_slot(
                world["monday"]["id"],
                {
                    "slot_holding_id": world["holding"]["id"],
                    "movement_type": "DEPARTURE",
                },
                world["planner"],
            )
        )

        version = read_version(world["version"]["id"], OFFICER)
        assert version["leg_count"] == 2
        assert version["unslotted_leg_count"] == 1
        assert version["at_risk_slot_count"] == 1
        assert version["schedule_compliance_score"] == 77.00
        assert version["compliance_state"] == "BLOCKED"
        assert_score_matches_counters(version)


# ─── Endpoint 5: the read-only rotation projection ────────────────────────

def _out_and_back_on_one_tail():
    """One tail flying MUC-TXL-MUC on a single UTC date, an hour on the ground."""
    ref = setup_domestic_rotation_base(version_label="W26-G1")
    outbound = create_flight_leg(
        ref["carrier"]["id"],
        ref["version"]["id"],
        ref["stations"]["MUC"]["id"],
        ref["stations"]["TXL"]["id"],
        "2026-11-03T08:00:00.000Z",
        "2026-11-03T09:00:00.000Z",
        flight_number="HX320",
    )
    inbound = create_flight_leg(
        ref["carrier"]["id"],
        ref["version"]["id"],
        ref["stations"]["TXL"]["id"],
        ref["stations"]["MUC"]["id"],
        "2026-11-03T10:00:00.000Z",
        "2026-11-03T11:00:00.000Z",
        flight_number="HX321",
    )
    ref["outbound"] = assign_aircraft(
        ref["carrier"]["id"], outbound["id"], ref["aircraft"]["id"]
    )
    ref["inbound"] = assign_aircraft(
        ref["carrier"]["id"], inbound["id"], ref["aircraft"]["id"]
    )
    return ref


class TestRotationFeasibilityReadReportsTheOrderedChainAndTheWindows:
    """The seven-field projection read off a two-leg out-and-back."""

    def test_the_projection_reports_the_pinned_order_and_the_cleared_verdict(self):
        """The chain is returned in departure order with no offending leg, and
        both scalar figures are the ones the walk computed - the required turn
        from the single consecutive pair and the summed block of both sectors.

        PRD §3.3: "Here `ordered_leg_ids` is the pinned leg order described
        above, `first_violation_leg_id` is the offending leg when the verdict is
        infeasible and null when it is not, `required_turn_minutes` is the
        required turn computed at the first consecutive pair, and
        `total_block_minutes` is the summed block time of the tail's
        non-cancelled legs."

        PRD §3.3: "Sort that set by `dep_utc` ascending, breaking ties by
        `created_at` ascending - never by identifier."

        Design: Corner/endpoints/rotation_feasibility_read_reports_the_ordered_chain_and_the_maintenance_windows
        """
        world = _out_and_back_on_one_tail()

        rotation = read_rotation(world["aircraft"]["id"], OFFICER)
        assert rotation["rotation_feasibility_status"] == "FEASIBLE"
        assert rotation["first_violation_leg_id"] is None
        assert rotation["ordered_leg_ids"] == [
            world["outbound"]["id"],
            world["inbound"]["id"],
        ]
        assert rotation["required_turn_minutes"] == 45
        assert rotation["total_block_minutes"] == 120

    def test_an_hour_on_a_non_capable_apron_earns_no_maintenance_credit(self):
        """The one ground interval sits at `TXL`, which is not maintenance
        capable, so it is discarded outright and both variants report 0 - and
        the tail row carries the same verdict as the projection.

        PRD §3.3: "Keep that interval only when the station where the aircraft
        is actually sitting - the earlier leg's `dest_station_id` - has
        `maintenance_capable` true; discard it otherwise."

        PRD §3.3: "a tail whose entire ground time is spent at stations that are
        not maintenance-capable reports 0 for both even though it sat for hours."

        PRD §3.3: "`assigned_leg_count` is always the number of legs whose
        `assigned_aircraft_id` is this tail and whose `status` is not
        `CANCELLED`."

        Design: Corner/endpoints/rotation_feasibility_read_reports_the_ordered_chain_and_the_maintenance_windows
        """
        world = _out_and_back_on_one_tail()

        rotation = read_rotation(world["aircraft"]["id"], OFFICER)
        assert rotation["maintenance_opportunity_minutes"] == 0
        assert rotation["cumulative_ground_minutes"] == 0

        tail = read_aircraft(world["aircraft"]["id"], OFFICER)
        assert tail["assigned_leg_count"] == 2
        assert tail["rotation_feasibility_status"] == "FEASIBLE"
        assert tail["maintenance_opportunity_minutes"] == 0
        assert tail["cumulative_ground_minutes"] == 0
