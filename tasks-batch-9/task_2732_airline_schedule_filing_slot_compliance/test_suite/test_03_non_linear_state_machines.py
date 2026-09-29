"""Three non-linear state machines on three different entities.

A leg cycles back into states it has already occupied; a schedule version moves
its two state dimensions independently; a slot transaction forks into two
branches that rejoin at the same terminal status with divergent side effects.
"""

import pytest

from test_helpers import (
    api_client,
    assert_slot_holding,
    attach_slot,
    cancel_leg,
    create_carrier,
    create_open_season,
    create_partner_carrier,
    create_slot_holding,
    create_station,
    make_network_planner_headers,
    make_partner_carrier_headers,
    propose_transaction,
    read_holding,
    read_leg,
    read_submission,
    read_version,
    retime_leg,
    setup_monday_series_schedule,
    transmit_submission,
    queue_submission,
    validate_paginated,
    validate_success,
    validate_version,
    TEST_USERS,
)

COORDINATOR = TEST_USERS["slot_coordinator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


class TestFlightLegCycle:
    """SLOT_BACKED -> FILED -> REFILE_REQUIRED -> SLOT_BACKED -> FILED, twice
    round."""

    def test_leg_returns_to_slot_backed_and_files_a_second_time(self):
        """The loop is traversable more than once on the same leg.

        PRD §3.5: "the whole `SLOT_BACKED` -> `FILED` -> `REFILE_REQUIRED` ->
        `SLOT_BACKED` loop may be traversed any number of times within a single
        season as slots move around."

        Design: Difficulty/non_linear_state_machine/flight_leg_slot_backed_filed_refile_cycle_completes_two_full_laps
        """
        world = setup_monday_series_schedule(
            leg_count=4,
            series_weeks=5,
            validate=True,
            submission={"change_window": "EXPEDITED"},
            transmit=True,
        )
        carrier_id = world["carrier"]["id"]
        planner = world["planner"]
        leg4 = world["legs"][3]
        holding_id = world["holding"]["id"]

        # Lap 1 finished at FILED.
        assert read_leg(leg4["id"], planner)["status"] == "FILED"

        # FILED -> REFILE_REQUIRED, slot identifiers nulled.
        retimed = retime_leg(
            carrier_id,
            leg4["id"],
            "2026-11-23T10:00:00.000Z",
            "2026-11-23T11:00:00.000Z",
        )
        assert retimed["status"] == "REFILE_REQUIRED"
        assert retimed["departure_slot_holding_id"] is None

        # REFILE_REQUIRED -> REFILE_REQUIRED, the self-loop.
        restored = retime_leg(
            carrier_id,
            leg4["id"],
            "2026-11-23T08:00:00.000Z",
            "2026-11-23T09:00:00.000Z",
        )
        assert restored["status"] == "REFILE_REQUIRED"

        # REFILE_REQUIRED -> SLOT_BACKED: a state the leg already occupied.
        reslotted = attach_slot(carrier_id, leg4["id"], holding_id, "DEPARTURE")
        assert reslotted["status"] == "SLOT_BACKED"
        assert reslotted["departure_slot_holding_id"] == holding_id

        # Lap 2 back to FILED.
        second = queue_submission(
            world["version"]["id"], change_window="EXPEDITED"
        )
        transmit_submission(second["id"])
        assert read_leg(leg4["id"], planner)["status"] == "FILED"

    def test_second_lap_leaves_the_ledger_holding_only_the_live_submission(self):
        """The first submission's accrual is reversed and only the second one
        counts.

        PRD §3.8: "The invariant that ties the whole ledger together is simple
        to state and must hold after every one of these writes: a version's
        `filing_charge_accrued_cents` always equals the sum of
        `total_charge_cents` over its submissions whose `status` is
        `TRANSMITTED` or `ACKNOWLEDGED`, and no other."

        Design: Difficulty/non_linear_state_machine/flight_leg_slot_backed_filed_refile_cycle_completes_two_full_laps
        """
        world = setup_monday_series_schedule(
            leg_count=4,
            series_weeks=5,
            validate=True,
            submission={"change_window": "EXPEDITED"},
            transmit=True,
        )
        carrier_id = world["carrier"]["id"]
        planner = world["planner"]
        leg4 = world["legs"][3]
        first_submission_id = world["submission"]["id"]

        retime_leg(
            carrier_id,
            leg4["id"],
            "2026-11-23T10:00:00.000Z",
            "2026-11-23T11:00:00.000Z",
        )
        retime_leg(
            carrier_id,
            leg4["id"],
            "2026-11-23T08:00:00.000Z",
            "2026-11-23T09:00:00.000Z",
        )
        attach_slot(carrier_id, leg4["id"], world["holding"]["id"], "DEPARTURE")

        second = queue_submission(world["version"]["id"], change_window="EXPEDITED")
        second = transmit_submission(second["id"])

        first = read_submission(first_submission_id, planner)
        assert first["status"] == "REJECTED"
        assert first["rejection_reason"] == "SCHEDULE_BLOCKED"
        assert second["status"] == "TRANSMITTED"

        version = read_version(world["version"]["id"], planner)
        assert version["filing_charge_accrued_cents"] == 22815
        assert version["filing_status"] == "FILED"

    def test_the_reattached_series_is_back_to_four_attached_operations(self):
        """Detaching and reattaching returns the series exactly to where it
        was.

        PRD §2.6: "`attached_operations` on a slot series always equals the
        number of flight legs whose `status` is not `CANCELLED` and which
        reference that series through either `departure_slot_holding_id` or
        `arrival_slot_holding_id`."

        Design: Difficulty/non_linear_state_machine/flight_leg_slot_backed_filed_refile_cycle_completes_two_full_laps
        """
        world = setup_monday_series_schedule(
            leg_count=4,
            series_weeks=5,
            validate=True,
            submission={"change_window": "EXPEDITED"},
            transmit=True,
        )
        carrier_id = world["carrier"]["id"]
        leg4 = world["legs"][3]

        retime_leg(
            carrier_id,
            leg4["id"],
            "2026-11-23T10:00:00.000Z",
            "2026-11-23T11:00:00.000Z",
        )
        retime_leg(
            carrier_id,
            leg4["id"],
            "2026-11-23T08:00:00.000Z",
            "2026-11-23T09:00:00.000Z",
        )
        attach_slot(carrier_id, leg4["id"], world["holding"]["id"], "DEPARTURE")

        holding = read_holding(world["holding"]["id"], COORDINATOR)
        assert_slot_holding(holding)
        assert holding["attached_operations"] == 4
        assert holding["utilization_pct_as_filed"] == pytest.approx(80.00, abs=0.01)
        assert holding["at_risk_of_loss"] is False

        version = read_version(world["version"]["id"], world["planner"])
        assert version["compliance_state"] == "CLEAN"
        assert version["schedule_compliance_score"] == pytest.approx(100.00, abs=0.01)
        assert version["unslotted_leg_count"] == 0


def _warned_but_draft_version():
    """Four legs on one UTC date, two of them under a night-curfew waiver.

    Neither station is fully coordinated, so every leg auto-advances to
    `SLOT_BACKED` on assignment and the only penalty in play is the pair of
    curfew waivers.
    """
    from test_helpers import assign_aircraft, create_aircraft, create_flight_leg
    from test_helpers import create_schedule_version

    carrier = create_carrier()
    muc = create_station("MUC")
    txl = create_station("TXL", maintenance_capable=False)
    season = create_open_season()
    aircraft = create_aircraft(
        carrier["id"], muc["id"], registration="D-AHXD", maintenance_check_required=False
    )
    version = create_schedule_version(
        carrier["id"], season["id"], version_label="W26-P1"
    )

    plan = (
        ("HX501", muc, txl, "06:00", "07:00", None),
        ("HX502", txl, muc, "07:45", "08:45", None),
        ("HX503", muc, txl, "20:00", "21:00", "NIGHT-01"),
        ("HX504", txl, muc, "21:45", "22:45", "NIGHT-02"),
    )
    legs = []
    for flight_number, origin, dest, dep, arr, waiver in plan:
        overrides = {"flight_number": flight_number}
        if waiver is not None:
            overrides["curfew_waiver_reference"] = waiver
        leg = create_flight_leg(
            carrier["id"],
            version["id"],
            origin["id"],
            dest["id"],
            f"2026-11-03T{dep}:00.000Z",
            f"2026-11-03T{arr}:00.000Z",
            **overrides,
        )
        legs.append(assign_aircraft(carrier["id"], leg["id"], aircraft["id"]))

    return {
        "carrier": carrier,
        "planner": make_network_planner_headers(carrier["id"]),
        "aircraft": aircraft,
        "version": version,
        "legs": legs,
    }


class TestVersionDimensionsMoveIndependently:
    """`filing_status` and `compliance_state` are two state machines on one
    row."""

    def test_two_waivers_warn_a_version_that_is_still_draft(self):
        """The compliance dimension is already WARNED while the filing
        dimension has not moved.

        PRD §3.7: "A version with one curfew violation and two unslotted legs
        has a raw penalty of 12.00 plus 16.00, so 28.00, and scores 72.00."

        Design: Difficulty/non_linear_state_machine/schedule_version_filing_status_and_compliance_state_move_independently
        """
        world = _warned_but_draft_version()

        version = read_version(world["version"]["id"], OFFICER)
        assert version["filing_status"] == "DRAFT"
        assert version["curfew_violation_count"] == 2
        assert version["at_risk_slot_count"] == 0
        assert version["schedule_compliance_score"] == pytest.approx(76.00, abs=0.01)
        assert version["compliance_state"] == "WARNED"

    def test_validation_moves_the_filing_dimension_and_leaves_the_other_frozen(self):
        """A WARNED version validates, and stays WARNED.

        PRD §3.7: "Last of all, the version's `compliance_state` must not be
        `BLOCKED`, or validation fails with `ERR_SCHEDULE_BLOCKED`; a `WARNED`
        version validates perfectly well, which is the practical difference
        between a warning and a block."

        Design: Difficulty/non_linear_state_machine/schedule_version_filing_status_and_compliance_state_move_independently
        """
        world = _warned_but_draft_version()

        validated = validate_version(world["version"]["id"])
        assert validated["filing_status"] == "VALIDATED"
        assert validated["compliance_state"] == "WARNED"
        assert validated["schedule_compliance_score"] == pytest.approx(76.00, abs=0.01)

    def test_cancelling_a_waivered_leg_moves_the_compliance_dimension_alone(self):
        """The score climbs to CLEAN with `filing_status` provably still
        VALIDATED.

        PRD §3.7: "`compliance_state` is a **second, independent state
        dimension** on the same row as `filing_status`."

        Design: Difficulty/non_linear_state_machine/schedule_version_filing_status_and_compliance_state_move_independently
        """
        world = _warned_but_draft_version()
        validate_version(world["version"]["id"])

        cancelled = cancel_leg(
            world["carrier"]["id"], world["legs"][3]["id"], "NIGHT_WAIVER_WITHDRAWN"
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["open_obligation_count"] == 0

        version = read_version(world["version"]["id"], world["planner"])
        assert version["curfew_violation_count"] == 1
        assert version["schedule_compliance_score"] == pytest.approx(88.00, abs=0.01)
        assert version["compliance_state"] == "CLEAN"
        assert version["filing_status"] == "VALIDATED"

        from test_helpers import read_aircraft

        assert (
            read_aircraft(world["aircraft"]["id"], world["planner"])[
                "rotation_feasibility_status"
            ]
            == "FEASIBLE"
        )


def _three_series_at_the_hub():
    """Two home-carrier series and one counterparty series at three different
    slot times, so no two of them conflict."""
    carrier = create_carrier()
    partner = create_partner_carrier(iata_code="PT", icao_code="PTA")
    fra = create_station("FRA")
    season = create_open_season()

    def series(owner_id, time_of_day):
        return create_slot_holding(
            fra["id"],
            season["id"],
            owner_id,
            movement_type="DEPARTURE",
            slot_time_utc=f"2026-11-02T{time_of_day}:00:00.000Z",
            days_of_week="1",
            series_weeks=5,
            historic_precedence=False,
        )

    return {
        "carrier": carrier,
        "partner": partner,
        "station": fra,
        "season": season,
        "planner": make_network_planner_headers(carrier["id"]),
        "counterparty": make_partner_carrier_headers(partner["id"]),
        "offered_transfer": series(carrier["id"], "08"),
        "offered_exchange": series(carrier["id"], "09"),
        "counter": series(partner["id"], "10"),
    }


def _execute(world, kind, offered, counter=None):
    transaction = propose_transaction(
        carrier_id=world["carrier"]["id"],
        counterparty_carrier_id=world["partner"]["id"],
        offered_slot_holding_id=offered["id"],
        expected_slot_holding_version=offered["version"],
        kind=kind,
        counter_slot_holding_id=None if counter is None else counter["id"],
        response_deadline_utc="2026-08-20T23:59:59.000Z",
    )
    validate_success(
        api_client.respond_slot_transaction(
            transaction["id"], {"decision": "ACCEPT"}, world["counterparty"]
        )
    )
    return validate_success(
        api_client.approve_slot_transaction(
            transaction["id"], {"decision": "APPROVE"}, COORDINATOR
        )
    )


class TestTransactionBranchesJoinAtExecuted:
    """Both kinds reach EXECUTED; only one mints a successor."""

    def test_transfer_branch_transfers_out_and_mints_a_successor(self):
        """The transferor leaves HELD and the successor inherits the series.

        PRD §3.6: "On a `TRANSFER`, the offered holding moves `HELD ->
        TRANSFERRED_OUT` with its `retains_historic_precedence` set to false -
        the transferor loses the grandfather claim, which moves to the successor
        - and a **new** slot holding is minted for `counterparty_carrier_id`
        carrying the same `station_id`, `season_id`, `slot_time_utc`,
        `days_of_week` and `series_weeks` as the original"

        Design: Difficulty/non_linear_state_machine/slot_transaction_transfer_and_exchange_branches_join_at_executed_with_divergent_effects
        """
        world = _three_series_at_the_hub()
        offered = world["offered_transfer"]

        transaction = _execute(world, "TRANSFER", offered)
        assert transaction["status"] == "EXECUTED"
        assert transaction["successor_slot_holding_id"] is not None

        original = read_holding(offered["id"], COORDINATOR)
        assert original["holding_status"] == "TRANSFERRED_OUT"
        assert original["retains_historic_precedence"] is False
        assert original["pending_transaction_id"] is None

        successor = read_holding(
            transaction["successor_slot_holding_id"], COORDINATOR
        )
        assert successor["carrier_id"] == world["partner"]["id"]
        assert successor["holding_status"] == "HELD"
        assert successor["historic_predecessor_holding_id"] == offered["id"]
        assert successor["days_of_week"] == "1"
        assert successor["series_weeks"] == 5
        assert successor["planned_operations"] == 5
        assert successor["attached_operations"] == 0

    def test_exchange_branch_swaps_carriers_in_place_with_no_successor(self):
        """Both rows stay HELD, keep their own times and change hands.

        PRD §3.6: "On an `EXCHANGE`, no successor holding is minted and
        `successor_slot_holding_id` stays null. Instead the offered and counter
        holdings **swap** their `carrier_id` values in place; each row keeps its
        own `slot_time_utc` and `days_of_week`, and both remain `HELD`."

        Design: Difficulty/non_linear_state_machine/slot_transaction_transfer_and_exchange_branches_join_at_executed_with_divergent_effects
        """
        world = _three_series_at_the_hub()
        offered = world["offered_exchange"]
        counter = world["counter"]

        transaction = _execute(world, "EXCHANGE", offered, counter)
        assert transaction["status"] == "EXECUTED"
        assert transaction["successor_slot_holding_id"] is None

        offered_now = read_holding(offered["id"], COORDINATOR)
        counter_now = read_holding(counter["id"], COORDINATOR)
        assert offered_now["holding_status"] == "HELD"
        assert offered_now["carrier_id"] == world["partner"]["id"]
        assert counter_now["holding_status"] == "HELD"
        assert counter_now["carrier_id"] == world["carrier"]["id"]

        from test_helpers import canonical_iso8601

        assert canonical_iso8601(offered_now["slot_time_utc"]) == canonical_iso8601(
            "2026-11-02T09:00:00Z"
        )
        assert canonical_iso8601(counter_now["slot_time_utc"]) == canonical_iso8601(
            "2026-11-02T10:00:00Z"
        )

    def test_only_the_transfer_branch_is_reachable_by_predecessor_filter(self):
        """The successor is discoverable only by listing on the predecessor.

        PRD §3.6: "The successor holding that a transfer mints is discoverable
        only by listing - either by filtering slot holdings on
        `historic_predecessor_holding_id` or by filtering transactions on
        `successor_slot_holding_id`."

        Design: Difficulty/non_linear_state_machine/slot_transaction_transfer_and_exchange_branches_join_at_executed_with_divergent_effects
        """
        world = _three_series_at_the_hub()
        transferred = _execute(world, "TRANSFER", world["offered_transfer"])
        exchanged = _execute(
            world, "EXCHANGE", world["offered_exchange"], world["counter"]
        )
        assert transferred["status"] == "EXECUTED"
        assert exchanged["status"] == "EXECUTED"

        rows, meta = validate_paginated(
            api_client.list_slot_holdings(
                COORDINATOR,
                params={
                    "historic_predecessor_holding_id": world["offered_transfer"]["id"]
                },
            )
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["carrier_id"] == world["partner"]["id"]

        empty, empty_meta = validate_paginated(
            api_client.list_slot_holdings(
                COORDINATOR,
                params={
                    "historic_predecessor_holding_id": world["offered_exchange"]["id"]
                },
            )
        )
        assert empty_meta["total_count"] == 0
        assert empty == []
