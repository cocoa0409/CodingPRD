"""Listing scope, endpoint contracts and the promptness of derived fields.

Every test in this file drives the public API only and builds its own plant from
scratch: the harness restarts the server and empties the database before each
test, so nothing is carried over.

Concerns covered here:

* the tower read and its two nested child collections, scoped by the path id;
* the capacity-policy action, which reprices a posture without touching a
  reservation;
* the tower-decommission fan-out across sectors, reservations and qualifications;
* the two legs of an interference coordination and the filters that see them;
* the account read and the roll-ups it aggregates;
* the reschedule loop out of `RESURVEY_REQUIRED`;
* the rule that a write's own response already carries every value it derived.
"""

import pytest

from test_helpers import (
    SURVEY_PRESETS,
    ApiErrorId,
    activate_sector,
    apply_credit,
    assert_capacity_hold,
    assert_install_work_order,
    assert_interference_coordination,
    assert_no_mutation,
    assert_sector,
    assert_serviceability_request,
    assert_subscriber,
    assert_tower,
    assert_version_advanced_by,
    close_outage,
    complete_work_order,
    create_backhaul_circuit,
    create_coordination_payload,
    create_outage,
    create_sector,
    create_serviceability_request,
    create_serviceability_request_payload,
    create_tower,
    get_capacity_hold,
    get_sector,
    get_serviceability_request,
    get_subscriber,
    get_tower,
    get_work_order,
    hold_for_request,
    ingest_usage,
    prepare_credit,
    reschedule_work_order,
    reserve_bandwidth,
    set_clock,
    setup_active_plant,
    setup_neighbor_sectors,
    setup_planned_plant,
    setup_scheduled_work_order,
    setup_work_order_in_state,
    survey_work_order,
    validate_error,
    validate_paginated,
    validate_success,
)

# --------------------------------------------------------------------------
# Local composite setups, built from the Tier-0 helpers only.
# --------------------------------------------------------------------------


def _setup_two_towers_each_with_a_circuit_and_an_outage():
    """Two independent PLANNED towers, each owning exactly one ordered circuit
    and one outage record. Tower A's outage is `POWER`, tower B's `WEATHER_WIND`.
    """
    tower_a = create_tower()
    tower_b = create_tower(latitude=41.4, longitude=-104.5)
    circuit_a = create_backhaul_circuit(tower_a["id"], carrier_name="Prairie Fiber")
    circuit_b = create_backhaul_circuit(
        tower_b["id"], carrier_name="Meadow Backhaul", committed_mbps=300
    )
    outage_a = create_outage(tower_a["id"], cause="POWER")
    outage_b = create_outage(tower_b["id"], cause="WEATHER_WIND")
    return {
        "tower_a": tower_a,
        "tower_b": tower_b,
        "circuit_a": circuit_a,
        "circuit_b": circuit_b,
        "outage_a": outage_a,
        "outage_b": outage_b,
    }


def _setup_tower_with_two_active_sectors():
    """One ACTIVE tower carrying two ACTIVE sectors, azimuth 90.0 and 270.0,
    both `capacity_mbps` 25 with `max_oversubscription_ratio` 8.0."""
    scenario = setup_active_plant(sector_overrides={"azimuth_deg": 90.0})
    second = create_sector(
        scenario["tower"]["id"], scenario["license"]["id"], azimuth_deg=270.0
    )
    scenario["sector2"] = activate_sector(second["id"])
    scenario["tower"] = get_tower(scenario["tower"]["id"])
    return scenario


def _setup_sector_at_watch_with_two_reservations():
    """The reference sector (25 Mbps, ceiling 8.0) carrying two 50 Mbps
    reservations, so `committed_mbps` is 100 and the air ratio is exactly 4.000 —
    half of the ceiling, which is the watch line."""
    scenario = setup_active_plant()
    reserve_bandwidth(scenario, 50)
    reserve_bandwidth(scenario, 50)
    scenario["sector"] = get_sector(scenario["sector"]["id"])
    return scenario


def _setup_installed_account_with_applied_credit_and_two_metered_days():
    """An installed RENTAL account whose cycle opened on 2026-08-02, one applied
    service-level credit for a 1269-minute `POWER` outage, and two metered days
    inside the cycle window that together cross the plan's 600.0 GB soft cap."""
    scenario = setup_scheduled_work_order()
    work_order_id = scenario["work_order"]["id"]
    survey_work_order(work_order_id, **SURVEY_PRESETS["NON_PEN_ROOF_TRIPOD"])
    set_clock("2026-08-02T00:00:00Z")
    scenario["work_order"] = complete_work_order(work_order_id, installed_mast_height_m=2.5)

    set_clock("2026-08-06T00:00:00Z")
    outage = create_outage(
        scenario["tower"]["id"], cause="POWER", started_at="2026-08-05T00:00:00Z"
    )
    scenario["outage"] = close_outage(outage["id"], ended_at="2026-08-05T21:09:00Z")
    credit = prepare_credit(outage["id"], scenario["subscriber"]["id"])
    scenario["credit"] = apply_credit(credit["id"])

    set_clock("2026-08-12T00:00:00Z")
    ingest_usage(scenario["subscriber"]["id"], "2026-08-03", 300.0, 20.0)
    ingest_usage(scenario["subscriber"]["id"], "2026-08-10", 280.0, 15.0)
    scenario["subscriber"] = get_subscriber(scenario["subscriber"]["id"])
    return scenario


# --------------------------------------------------------------------------
# The tower read and its nested child collections
# --------------------------------------------------------------------------


class TestTowerScopedListings:
    def test_tower_read_reports_its_own_site_code_status_and_backhaul_rate(
        self, api, network_engineer
    ):
        """PRD 3.1: "Upon registration the site opens in `PLANNED` `status`, with
        `active_sector_count` at zero and `backhaul_accepted_mbps` at zero, and its
        `current_monthly_rent_cents` is derived immediately."
        PRD 3.1: "A tower's `backhaul_accepted_mbps` is the `committed_mbps` of the
        circuit on that tower whose `state` is `ACCEPTED`, and it is zero whenever no
        circuit on the tower is `ACCEPTED`."

        Design: Corner/endpoints/tower_read_and_its_nested_child_lists_are_scoped_to_that_tower
        """
        plant = _setup_two_towers_each_with_a_circuit_and_an_outage()

        data = validate_success(api.get_tower(plant["tower_a"]["id"], network_engineer), 200)

        assert_tower(data)
        assert data["site_code"] == plant["tower_a"]["site_code"]
        assert data["status"] == "PLANNED", (
            f"a registered site opens in PLANNED, got {data['status']}"
        )
        assert data["active_sector_count"] == 0
        assert data["backhaul_accepted_mbps"] == 0, (
            "no circuit on the tower is ACCEPTED, so backhaul_accepted_mbps is zero, "
            f"got {data['backhaul_accepted_mbps']}"
        )

    def test_backhaul_circuit_listing_returns_only_the_addressed_towers_circuits(
        self, api, network_engineer
    ):
        """PRD 4: "List the backhaul circuits ordered for this tower."
        PRD 2.3: "The backhaul-circuit listing for a tower filters on `state`."

        Design: Corner/endpoints/tower_read_and_its_nested_child_lists_are_scoped_to_that_tower
        """
        plant = _setup_two_towers_each_with_a_circuit_and_an_outage()

        rows_a, meta_a = validate_paginated(
            api.list_tower_backhaul_circuits(plant["tower_a"]["id"], network_engineer)
        )
        rows_b, meta_b = validate_paginated(
            api.list_tower_backhaul_circuits(plant["tower_b"]["id"], network_engineer)
        )

        assert meta_a["total_count"] == 1, (
            f"tower A owns exactly one circuit, got total_count {meta_a['total_count']}"
        )
        assert [row["id"] for row in rows_a] == [plant["circuit_a"]["id"]]
        assert meta_b["total_count"] == 1
        assert [row["id"] for row in rows_b] == [plant["circuit_b"]["id"]], (
            "the listing is scoped by the path id, not by insertion order"
        )

    def test_outage_listing_is_scoped_to_the_tower_and_composes_with_the_cause_filter(
        self, api, billing_admin
    ):
        """PRD 4: "List the outage events recorded against this tower."
        PRD 2.3: "The outage-event listing for a tower filters on `status` and on `cause`."
        PRD 2.3: "Beyond `limit` and `offset`, list endpoints accept exact-match filters
        drawn from the listed resource's own fields, and every filter is optional."

        Design: Corner/endpoints/tower_read_and_its_nested_child_lists_are_scoped_to_that_tower
        """
        plant = _setup_two_towers_each_with_a_circuit_and_an_outage()
        tower_a = plant["tower_a"]["id"]

        rows, meta = validate_paginated(api.list_tower_outage_events(tower_a, billing_admin))
        assert meta["total_count"] == 1, (
            f"tower A owns exactly one outage, got total_count {meta['total_count']}"
        )
        assert [row["id"] for row in rows] == [plant["outage_a"]["id"]]

        wind_rows, wind_meta = validate_paginated(
            api.list_tower_outage_events(tower_a, billing_admin, params={"cause": "WEATHER_WIND"})
        )
        assert wind_meta["total_count"] == 0, (
            "the WEATHER_WIND outage belongs to tower B, so the filter must narrow "
            f"within tower A rather than search globally, got {wind_meta['total_count']}"
        )
        assert wind_rows == []

        power_rows, power_meta = validate_paginated(
            api.list_tower_outage_events(tower_a, billing_admin, params={"cause": "POWER"})
        )
        assert power_meta["total_count"] == 1
        assert [row["id"] for row in power_rows] == [plant["outage_a"]["id"]]


# --------------------------------------------------------------------------
# Changing the oversubscription ceiling
# --------------------------------------------------------------------------


class TestCapacityPolicyChange:
    def test_tightening_the_ceiling_moves_watch_to_hold_and_shrinks_the_allowance(
        self, api, capacity_planner
    ):
        """PRD 3.3: "A `CapacityPlanner` may retune a sector's oversubscription policy by
        supplying a new `max_oversubscription_ratio` together with a mandatory
        `justification`."
        PRD 3.3: "The new ratio is stored, the `justification` text is recorded on the
        sector as its `capacity_policy_note` — which stays absent until the first such
        override — and `oversubscription_ratio` and `capacity_posture` are recomputed
        immediately against the commitments already on the sector."
        PRD 3.3: "Otherwise a provisional posture is read off the air ratio: `HOLD` when
        `oversubscription_ratio` is at or above three-quarters of
        `max_oversubscription_ratio`, `WATCH` when it is at or above half of
        `max_oversubscription_ratio`, and `OPEN` otherwise."
        PRD 3.3: "It is the product of `capacity_mbps` and `max_oversubscription_ratio`
        with any fractional part discarded downward, less `committed_mbps`, and it is
        never reported below zero."

        Design: Corner/endpoints/capacity_policy_change_reprices_the_posture_without_touching_any_reservation
        """
        scenario = _setup_sector_at_watch_with_two_reservations()
        before = scenario["sector"]
        assert before["committed_mbps"] == 100
        assert before["capacity_posture"] == "WATCH", (
            "an air ratio of exactly 4.000 sits on the watch line of an 8.0 ceiling, "
            f"got {before['capacity_posture']}"
        )
        assert before["remaining_allowance_mbps"] == 100, (
            f"floor(25 * 8.0) - 100, got {before['remaining_allowance_mbps']}"
        )

        after = validate_success(
            api.change_capacity_policy(
                before["id"],
                {
                    "max_oversubscription_ratio": 5.0,
                    "justification": "Transport planning cut the air-interface headroom",
                },
                capacity_planner,
            ),
            200,
        )

        assert_sector(after)
        assert after["max_oversubscription_ratio"] == 5.0
        assert after["oversubscription_ratio"] == pytest.approx(4.000, abs=0.0005), (
            f"committed_mbps did not move, got ratio {after['oversubscription_ratio']}"
        )
        assert after["capacity_posture"] == "HOLD", (
            "three-quarters of the new 5.0 ceiling is 3.75 and the ratio is 4.000, "
            f"got {after['capacity_posture']}"
        )
        assert after["remaining_allowance_mbps"] == 25, (
            f"floor(25 * 5.0) - 100, got {after['remaining_allowance_mbps']}"
        )
        assert_version_advanced_by(before, after, 1, "sector")

    def test_repricing_the_posture_leaves_every_reservation_held(self, api, capacity_planner):
        """PRD 3.6: "A `CapacityPlanner`, and only a `CapacityPlanner`, may hand bandwidth
        back manually, optionally recording a `note`."
        PRD 3.6: "Three further paths reach `RELEASED`, and they are distinguished purely
        by `release_reason`."
        PRD 3.3: "The new ratio is stored, the `justification` text is recorded on the
        sector as its `capacity_policy_note` — which stays absent until the first such
        override — and `oversubscription_ratio` and `capacity_posture` are recomputed
        immediately against the commitments already on the sector."

        Design: Corner/endpoints/capacity_policy_change_reprices_the_posture_without_touching_any_reservation
        """
        scenario = _setup_sector_at_watch_with_two_reservations()
        reservations = scenario["reservations"]
        assert len(reservations) == 2

        validate_success(
            api.change_capacity_policy(
                scenario["sector"]["id"],
                {
                    "max_oversubscription_ratio": 5.0,
                    "justification": "Transport planning cut the air-interface headroom",
                },
                capacity_planner,
            ),
            200,
        )

        for entry in reservations:
            hold_after = get_capacity_hold(entry["hold"]["id"])
            assert_capacity_hold(hold_after)
            assert hold_after["status"] == "HELD", (
                "no declared path to RELEASED was taken, so the reservation stays HELD, "
                f"got {hold_after['status']}"
            )
            assert hold_after["held_mbps"] == 50
            assert hold_after.get("release_reason") is None
            assert_no_mutation(entry["hold"], hold_after, "capacity reservation")

            request_after = get_serviceability_request(entry["request"]["id"])
            assert request_after["status"] == "QUALIFIED", (
                "the enquiry keeps its claim because its reservation never left HELD, "
                f"got {request_after['status']}"
            )


# --------------------------------------------------------------------------
# The decommission fan-out
# --------------------------------------------------------------------------


class TestDecommissionFanOut:
    def test_one_decommission_call_disables_every_sector_and_unwinds_both_ledgers(
        self, api, network_engineer
    ):
        """PRD 3.1: "When the guard passes, the decommission cascade runs in full: every
        sector on the tower whose `status` is `PLANNED` or `ACTIVE` transitions to
        `DISABLED`; because each of those sectors has left `ACTIVE`, every reservation on
        them in `HELD` status transitions to `RELEASED` with a `release_reason` of
        `SECTOR_DISABLED`; and because each of those reservations has left `HELD`, every
        qualification they referenced in `QUALIFIED` or `CAPACITY_DEFERRED` transitions to
        `EXPIRED`."
        PRD 3.1: "A tower's `active_sector_count` is at all times the number of its sectors
        whose `status` is `ACTIVE`, so decommissioning drives it to zero."
        PRD 3.2: "A sector leaving `ACTIVE` for `DISABLED` recomputes the tower's
        `active_sector_count`, sets its own `capacity_posture` to `FROZEN`, records
        `capacity_policy_note` as an explanation that the sector was disabled with its
        tower, and releases every reservation still `HELD` on it with a `release_reason` of
        `SECTOR_DISABLED`."
        PRD 2.10: "Cascades are **immediate and synchronous**: by the time a response is
        returned, every downstream record has already reached its new state, and any
        derived roll-up has already been recomputed."

        Design: Corner/endpoints/decommission_fans_out_across_six_rows_in_one_call_with_no_partial_update
        """
        scenario = _setup_tower_with_two_active_sectors()
        tower_id = scenario["tower"]["id"]

        request_a = create_serviceability_request(tower_id, scenario["plan"]["id"])
        hold_a = hold_for_request(request_a["id"])
        request_b = create_serviceability_request(tower_id, scenario["plan"]["id"])
        hold_b = hold_for_request(request_b["id"])

        sector_ids = {scenario["sector"]["id"], scenario["sector2"]["id"]}
        assert {hold_a["sector_id"], hold_b["sector_id"]} == sector_ids, (
            "the two reservations must land on different sectors so the cascade has to "
            f"visit both, got {hold_a['sector_id']} and {hold_b['sector_id']}"
        )

        tower_before = get_tower(tower_id)
        sectors_before = {sid: get_sector(sid) for sid in sector_ids}
        assert tower_before["active_sector_count"] == 2

        tower_after = validate_success(
            api.change_tower_status(
                tower_id,
                {"to_status": "DECOMMISSIONED", "reason": "Landowner terminated the ground lease"},
                network_engineer,
            ),
            200,
        )

        assert_tower(tower_after)
        assert tower_after["status"] == "DECOMMISSIONED"
        assert tower_after["active_sector_count"] == 0, (
            "the response already carries the recomputed roll-up, got "
            f"{tower_after['active_sector_count']}"
        )
        assert_version_advanced_by(tower_before, tower_after, 1, "tower")

        for sector_id, before in sectors_before.items():
            after = get_sector(sector_id)
            assert_sector(after)
            assert after["status"] == "DISABLED", (
                f"every PLANNED or ACTIVE sector transitions to DISABLED, got {after['status']}"
            )
            assert after["capacity_posture"] == "FROZEN", (
                f"a sector leaving ACTIVE sets its posture to FROZEN, got {after['capacity_posture']}"
            )
            assert after["held_mbps"] == 0, (
                f"the released reservation unwinds held_mbps, got {after['held_mbps']}"
            )
            assert after["sold_mbps"] == 0
            assert after["committed_mbps"] == 0
            assert after["version"] > before["version"], (
                "a record touched by the cascade has its version incremented in its own right, "
                f"stayed at {after['version']}"
            )

        for hold in (hold_a, hold_b):
            hold_after = get_capacity_hold(hold["id"])
            assert hold_after["status"] == "RELEASED", (
                f"a reservation on a disabled sector is RELEASED, got {hold_after['status']}"
            )
            assert hold_after["release_reason"] == "SECTOR_DISABLED", (
                f"got release_reason {hold_after.get('release_reason')!r}"
            )

        for request in (request_a, request_b):
            request_after = get_serviceability_request(request["id"])
            assert request_after["status"] == "EXPIRED", (
                "a qualification whose reservation left HELD is EXPIRED, got "
                f"{request_after['status']}"
            )

    def test_after_the_cascade_no_held_reservation_or_qualified_enquiry_remains_listed(
        self, api, capacity_planner, network_engineer
    ):
        """PRD 2.10: "Cascades are **immediate and synchronous**: by the time a response is
        returned, every downstream record has already reached its new state, and any
        derived roll-up has already been recomputed."
        PRD 2.3: "`total_count` is the number of records matching the filter before
        pagination is applied, and `has_more` is true when records remain beyond the
        returned page."
        PRD 3.1: "When the guard passes, the decommission cascade runs in full: every
        sector on the tower whose `status` is `PLANNED` or `ACTIVE` transitions to
        `DISABLED`; because each of those sectors has left `ACTIVE`, every reservation on
        them in `HELD` status transitions to `RELEASED` with a `release_reason` of
        `SECTOR_DISABLED`; and because each of those reservations has left `HELD`, every
        qualification they referenced in `QUALIFIED` or `CAPACITY_DEFERRED` transitions to
        `EXPIRED`."

        Design: Corner/endpoints/decommission_fans_out_across_six_rows_in_one_call_with_no_partial_update
        """
        scenario = _setup_tower_with_two_active_sectors()
        tower_id = scenario["tower"]["id"]
        request_a = create_serviceability_request(tower_id, scenario["plan"]["id"])
        hold_for_request(request_a["id"])
        request_b = create_serviceability_request(tower_id, scenario["plan"]["id"])
        hold_for_request(request_b["id"])

        _, held_before = validate_paginated(
            api.list_capacity_holds(capacity_planner, params={"status": "HELD"})
        )
        assert held_before["total_count"] == 2

        validate_success(
            api.change_tower_status(
                tower_id,
                {"to_status": "DECOMMISSIONED", "reason": "Landowner terminated the ground lease"},
                network_engineer,
            ),
            200,
        )

        held_rows, held_meta = validate_paginated(
            api.list_capacity_holds(capacity_planner, params={"status": "HELD"})
        )
        assert held_meta["total_count"] == 0, (
            "no reservation may still be listed as HELD once the cascade has run, got "
            f"{held_meta['total_count']}"
        )
        assert held_rows == []
        assert held_meta["has_more"] is False

        released_rows, released_meta = validate_paginated(
            api.list_capacity_holds(capacity_planner, params={"status": "RELEASED"})
        )
        assert released_meta["total_count"] == 2, (
            f"both reservations must appear as RELEASED, got {released_meta['total_count']}"
        )
        assert all(row["release_reason"] == "SECTOR_DISABLED" for row in released_rows)

        _, qualified_meta = validate_paginated(
            api.list_serviceability_requests(capacity_planner, params={"status": "QUALIFIED"})
        )
        assert qualified_meta["total_count"] == 0, (
            f"no enquiry may remain QUALIFIED, got {qualified_meta['total_count']}"
        )

        _, expired_meta = validate_paginated(
            api.list_serviceability_requests(capacity_planner, params={"status": "EXPIRED"})
        )
        assert expired_meta["total_count"] == 2, (
            f"both enquiries must have expired, got {expired_meta['total_count']}"
        )


# --------------------------------------------------------------------------
# The two legs of an interference coordination
# --------------------------------------------------------------------------


class TestCoordinationReachability:
    def test_a_new_coordination_names_both_sectors_and_opens_at_round_one(
        self, api, network_engineer
    ):
        """PRD 3.4: "A newly opened coordination sits in `REQUESTED` `status` with
        `round_number` at 1 and `decision_note`, `decided_by_user_id` and
        `last_response_at` all absent."
        PRD 3.4: "When the circular separation is **60 degrees or more** the beams are
        considered to be pointing away from each other and no spectrum disjointness is
        required at all — the proposal passes this test regardless of channel."

        Design: Corner/endpoints/a_coordination_is_reachable_from_both_of_the_sectors_it_joins
        """
        pair = setup_neighbor_sectors(
            sector_overrides={"azimuth_deg": 90.0}, neighbor_overrides={"azimuth_deg": 270.0}
        )
        local = pair["local"]["sector"]
        neighbor = pair["neighbor"]["sector"]

        data = validate_success(
            api.create_coordination(
                create_coordination_payload(local["id"], neighbor["id"]), network_engineer
            ),
            201,
        )

        assert_interference_coordination(data)
        assert data["requesting_sector_id"] == local["id"]
        assert data["neighbor_sector_id"] == neighbor["id"], (
            "the record names the far end as well as the near end, got "
            f"{data['neighbor_sector_id']}"
        )
        assert data["status"] == "REQUESTED", f"got {data['status']}"
        assert data["round_number"] == 1, f"got round_number {data['round_number']}"
        assert data.get("decision_note") is None
        assert data.get("decided_by_user_id") is None
        assert data.get("last_response_at") is None
        assert data["version"] == 1

    def test_the_sector_scoped_listing_shows_the_requester_leg_and_the_global_filters_show_both(
        self, api, network_engineer, capacity_planner
    ):
        """PRD 4: "List the coordination records in which this sector is the requester."
        PRD 2.3: "The coordination listing for a sector filters on `status`, and the global
        coordination listing filters on `requesting_sector_id`, `neighbor_sector_id`, and
        `status`."
        PRD 2.3: "Beyond `limit` and `offset`, list endpoints accept exact-match filters
        drawn from the listed resource's own fields, and every filter is optional."

        Design: Corner/endpoints/a_coordination_is_reachable_from_both_of_the_sectors_it_joins
        """
        pair = setup_neighbor_sectors(
            sector_overrides={"azimuth_deg": 90.0}, neighbor_overrides={"azimuth_deg": 270.0}
        )
        local = pair["local"]["sector"]
        neighbor = pair["neighbor"]["sector"]
        coordination = validate_success(
            api.create_coordination(
                create_coordination_payload(local["id"], neighbor["id"]), network_engineer
            ),
            201,
        )

        near_rows, near_meta = validate_paginated(
            api.list_sector_coordinations(local["id"], network_engineer)
        )
        assert near_meta["total_count"] == 1, (
            f"the requesting sector sees its own record, got {near_meta['total_count']}"
        )
        assert [row["id"] for row in near_rows] == [coordination["id"]]

        far_rows, far_meta = validate_paginated(
            api.list_sector_coordinations(neighbor["id"], network_engineer)
        )
        assert far_meta["total_count"] == 0, (
            "the sector-scoped listing is the requester leg only, so the neighbour's own "
            f"listing is empty, got {far_meta['total_count']}"
        )
        assert far_rows == []

        by_requester, requester_meta = validate_paginated(
            api.list_coordinations(capacity_planner, params={"requesting_sector_id": local["id"]})
        )
        assert requester_meta["total_count"] == 1
        assert [row["id"] for row in by_requester] == [coordination["id"]]

        by_neighbor, neighbor_meta = validate_paginated(
            api.list_coordinations(capacity_planner, params={"neighbor_sector_id": neighbor["id"]})
        )
        assert neighbor_meta["total_count"] == 1, (
            "the far end is reachable through the global neighbor_sector_id filter, got "
            f"{neighbor_meta['total_count']}"
        )
        assert [row["id"] for row in by_neighbor] == [coordination["id"]]

        _, swapped_meta = validate_paginated(
            api.list_coordinations(
                capacity_planner, params={"requesting_sector_id": neighbor["id"]}
            )
        )
        assert swapped_meta["total_count"] == 0, (
            "the neighbour is not the requester, so the requester filter must not match it, "
            f"got {swapped_meta['total_count']}"
        )

        _, accepted_meta = validate_paginated(
            api.list_coordinations(capacity_planner, params={"status": "ACCEPTED"})
        )
        assert accepted_meta["total_count"] == 0, (
            f"the record is still REQUESTED, got {accepted_meta['total_count']} accepted"
        )


# --------------------------------------------------------------------------
# The account read and its roll-ups
# --------------------------------------------------------------------------


class TestSubscriberRollUpRead:
    def test_account_read_reports_usage_shaping_credit_and_equipment_roll_ups_together(
        self, api, billing_admin
    ):
        """PRD 3.8: "Starting from zero, for each record in turn add that record's
        `downstream_gb` and `upstream_gb` to the running total and round the running total
        half up to one decimal place **before moving to the next record**."
        PRD 3.8: "The cycle is breached when `cycle_usage_gb` is **strictly greater** than
        the plan's `soft_cap_gb`; usage landing exactly on the cap is not a breach."
        PRD 3.8: "`usage_priority` is then `DEPRIORITIZED` when either the current cycle is
        breached or `sticky_deprioritization_active` is true, and `STANDARD` otherwise."
        PRD 3.8: "The transition stamps `deprioritized_at` with the current logical clock
        and recomputes `effective_downstream_mbps`."
        PRD 3.9: "`credit_balance_cents` is at all times the sum of `credit_cents` over the
        account's credits in `APPLIED` status, and an outage's `total_credited_cents` is the
        sum over its own `APPLIED` credits; both therefore exclude `PENDING`, `DENIED` and
        `REVERSED` rows."
        PRD 3.8: "The account's `settlement_balance_cents` is the sum of `settlement_cents`
        over its equipment records whose `status` is `RETURNED`, `UNRETURNED_BILLED` or
        `VOIDED`."
        PRD 3.7: "The account's `equipment_monthly_charge_cents` is then recomputed and
        becomes the equipment record's `monthly_rental_cents` — 1000 cents for a rental,
        zero for a purchase — because the recurring charge only begins once the radio is
        deployed."

        Design: Corner/endpoints/subscriber_read_exposes_five_roll_ups_computed_from_four_different_tables
        """
        scenario = _setup_installed_account_with_applied_credit_and_two_metered_days()

        data = validate_success(
            api.get_subscriber(scenario["subscriber"]["id"], billing_admin), 200
        )

        assert_subscriber(data)
        assert data["service_status"] == "ACTIVE", f"got {data['service_status']}"
        assert data["cycle_usage_gb"] == pytest.approx(615.0, abs=0.05), (
            "320.0 GB on 2026-08-03 plus 295.0 GB on 2026-08-10, both inside the cycle "
            f"window, got {data['cycle_usage_gb']}"
        )
        assert data["usage_priority"] == "DEPRIORITIZED", (
            "615.0 GB is strictly greater than the plan's 600.0 GB soft cap, got "
            f"{data['usage_priority']}"
        )
        assert data.get("deprioritized_at") is not None, (
            "the transition into DEPRIORITIZED stamps deprioritized_at"
        )
        assert data["effective_downstream_mbps"] == pytest.approx(12.5, abs=0.005), (
            "50 Mbps shaped by a deprioritization factor of 0.25, got "
            f"{data['effective_downstream_mbps']}"
        )
        assert data["consecutive_breach_cycles"] == 0, (
            "the counter only moves when the cycle is closed, got "
            f"{data['consecutive_breach_cycles']}"
        )
        assert data["sticky_deprioritization_active"] is False
        assert data["credit_balance_cents"] == 1706, (
            "one applied credit of 1706 cents for the 1269-minute POWER outage, got "
            f"{data['credit_balance_cents']}"
        )
        assert data["settlement_balance_cents"] == 0, (
            "the deployed radio has not been concluded, so no settlement is counted, got "
            f"{data['settlement_balance_cents']}"
        )
        assert data["equipment_monthly_charge_cents"] == 1000, (
            f"a deployed rental radio bills 1000 cents a month, got "
            f"{data['equipment_monthly_charge_cents']}"
        )

    def test_the_applied_credit_shows_on_the_outage_and_on_the_account_alike(
        self, api, billing_admin
    ):
        """PRD 3.9: "`credit_balance_cents` is at all times the sum of `credit_cents` over
        the account's credits in `APPLIED` status, and an outage's `total_credited_cents` is
        the sum over its own `APPLIED` credits; both therefore exclude `PENDING`, `DENIED`
        and `REVERSED` rows."
        PRD 2.3: "`total_count` is the number of records matching the filter before
        pagination is applied, and `has_more` is true when records remain beyond the
        returned page."

        Design: Corner/endpoints/subscriber_read_exposes_five_roll_ups_computed_from_four_different_tables
        """
        scenario = _setup_installed_account_with_applied_credit_and_two_metered_days()
        subscriber_id = scenario["subscriber"]["id"]

        account = validate_success(api.get_subscriber(subscriber_id, billing_admin), 200)
        outage = validate_success(
            api.get_outage_event(scenario["outage"]["id"], billing_admin), 200
        )

        assert account["credit_balance_cents"] == scenario["credit"]["credit_cents"]
        assert outage["total_credited_cents"] == scenario["credit"]["credit_cents"], (
            "the same applied amount rolls up on the outage, got "
            f"{outage['total_credited_cents']}"
        )

        rows, meta = validate_paginated(
            api.list_outage_credits(billing_admin, params={"subscriber_id": subscriber_id})
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "APPLIED"

        usage_rows, usage_meta = validate_paginated(
            api.list_usage_records(subscriber_id, billing_admin)
        )
        assert usage_meta["total_count"] == 2, (
            f"the two metered days are addressable in their own right, got "
            f"{usage_meta['total_count']}"
        )
        assert all(row["in_current_cycle"] is True for row in usage_rows)


# --------------------------------------------------------------------------
# The reschedule loop
# --------------------------------------------------------------------------


class TestRescheduleLoop:
    def test_reschedule_out_of_resurvey_required_keeps_the_measurements_and_the_count(
        self, api, field_tech
    ):
        """PRD 3.7: "From `RESURVEY_REQUIRED`, a `FieldTech` supplies a fresh
        `scheduled_at` and the work order returns `RESURVEY_REQUIRED → SCHEDULED`, ready
        for another survey — the loop that lets a difficult premise be visited more than
        once."
        PRD 3.7: "On success `resurvey_count` is increased by one and the three survey
        outputs — `field_los_margin_m`, `recommended_mast_height_m` and
        `recommended_mounting_type` — are cleared, because the engineer has judged the
        measurements themselves unreliable and the next visit must produce fresh ones."
        PRD 3.7: "The count is incremented when the resurvey is ordered, not when the visit
        is booked, so a work order that has just been sent back for its second resurvey
        sits at exactly 2 and may still be re-booked once."

        Design: Corner/endpoints/reschedule_is_legal_only_out_of_resurvey_required_and_preserves_the_measurements
        """
        scenario = setup_work_order_in_state("RESURVEY_REQUIRED")
        before = scenario["work_order"]
        assert before["status"] == "RESURVEY_REQUIRED"
        assert before["recommended_mast_height_m"] == pytest.approx(5.0, abs=0.005)
        assert before["recommended_mounting_type"] == "ROOF_MAST_GUYED"
        assert before["resurvey_count"] == 1

        after = validate_success(
            api.reschedule_work_order(
                before["id"], {"scheduled_at": "2026-08-09T15:00:00Z"}, field_tech
            ),
            200,
        )

        assert_install_work_order(after)
        assert after["status"] == "SCHEDULED", (
            f"the work order returns to SCHEDULED, got {after['status']}"
        )
        assert after["scheduled_at"].startswith("2026-08-09"), (
            f"the fresh scheduled_at is stored, got {after['scheduled_at']!r}"
        )
        assert after["resurvey_count"] == 1, (
            "booking the visit does not order another resurvey, got "
            f"{after['resurvey_count']}"
        )
        assert after["recommended_mast_height_m"] == pytest.approx(5.0, abs=0.005), (
            "only the exception decision clears the survey outputs, got "
            f"{after['recommended_mast_height_m']}"
        )
        assert after["recommended_mounting_type"] == "ROOF_MAST_GUYED"
        assert after["field_los_margin_m"] == pytest.approx(
            before["field_los_margin_m"], abs=0.005
        )
        assert_version_advanced_by(before, after, 1, "work order")

    def test_a_second_reschedule_from_scheduled_is_refused_and_changes_nothing(
        self, api, field_tech
    ):
        """PRD 3.7: "The work order must be in `RESURVEY_REQUIRED`, else
        `ERR_WORK_ORDER_STATE_INVALID`, and `resurvey_count` must be at or below the
        resurvey limit of 2, else `ERR_RESURVEY_LIMIT_REACHED`."

        Design: Corner/endpoints/reschedule_is_legal_only_out_of_resurvey_required_and_preserves_the_measurements
        """
        scenario = setup_work_order_in_state("RESURVEY_REQUIRED")
        work_order_id = scenario["work_order"]["id"]
        rescheduled = validate_success(
            api.reschedule_work_order(
                work_order_id, {"scheduled_at": "2026-08-09T15:00:00Z"}, field_tech
            ),
            200,
        )
        assert rescheduled["status"] == "SCHEDULED"

        validate_error(
            api.reschedule_work_order(
                work_order_id, {"scheduled_at": "2026-08-10T15:00:00Z"}, field_tech
            ),
            ApiErrorId.ERR_WORK_ORDER_STATE_INVALID,
        )

        after = get_work_order(work_order_id)
        assert_no_mutation(rescheduled, after, "work order")
        assert after["scheduled_at"] == rescheduled["scheduled_at"], (
            f"the refused call must not move the booking, got {after['scheduled_at']!r}"
        )

    def test_the_rebooked_visit_can_be_surveyed_again_into_an_exception(self):
        """PRD 3.7: "From `RESURVEY_REQUIRED`, a `FieldTech` supplies a fresh
        `scheduled_at` and the work order returns `RESURVEY_REQUIRED → SCHEDULED`, ready
        for another survey — the loop that lets a difficult premise be visited more than
        once."
        PRD 3.7: "When `field_los_margin_m` is at or above zero, `recommended_mast_height_m`
        is at or below 12.0, and `recommended_mounting_type` is `ROOF_MAST_GUYED` or
        `GROUND_POLE_MAST` — with the additional requirement that
        `structure_penetration_allowed` is true when the band is `ROOF_MAST_GUYED` — the
        work order moves `SCHEDULED → EXCEPTION_PENDING` and `approved_mounting_type` is
        deliberately left absent."

        Design: Corner/endpoints/reschedule_is_legal_only_out_of_resurvey_required_and_preserves_the_measurements
        """
        scenario = setup_work_order_in_state("RESURVEY_REQUIRED")
        work_order_id = scenario["work_order"]["id"]
        reschedule_work_order(work_order_id, scheduled_at="2026-08-09T15:00:00Z")

        resurveyed = survey_work_order(work_order_id, **SURVEY_PRESETS["ROOF_MAST_GUYED"])

        assert_install_work_order(resurveyed)
        assert resurveyed["status"] == "EXCEPTION_PENDING", (
            "the same premise now allows a structure penetration, so the second visit "
            f"reaches the engineering exception, got {resurveyed['status']}"
        )
        assert resurveyed["recommended_mounting_type"] == "ROOF_MAST_GUYED"
        assert resurveyed.get("approved_mounting_type") is None
        assert resurveyed["resurvey_count"] == 1, (
            f"no further resurvey was ordered, got {resurveyed['resurvey_count']}"
        )


# --------------------------------------------------------------------------
# Every write already carries what it derived
# --------------------------------------------------------------------------


class TestWritesReturnTheirOwnDerivedFields:
    def test_plant_activations_return_the_roll_ups_they_recomputed(
        self, api, network_engineer
    ):
        """PRD 2.10: "Cascades are **immediate and synchronous**: by the time a response is
        returned, every downstream record has already reached its new state, and any
        derived roll-up has already been recomputed."
        PRD 3.1: "Activation recomputes `backhaul_accepted_mbps` and recomputes
        `capacity_posture` on every sector of the tower."
        PRD 3.1: "A tower's `backhaul_accepted_mbps` is the `committed_mbps` of the circuit
        on that tower whose `state` is `ACCEPTED`, and it is zero whenever no circuit on the
        tower is `ACCEPTED`."
        PRD 3.2: "Activation recomputes the parent tower's `active_sector_count` and the
        sector's own `capacity_posture`."
        PRD 3.3: "It is the product of `capacity_mbps` and `max_oversubscription_ratio` with
        any fractional part discarded downward, less `committed_mbps`, and it is never
        reported below zero."

        Design: Corner/consistency_model/every_write_returns_its_own_recomputed_derived_fields_with_no_second_read
        """
        scenario = setup_planned_plant()
        tower_id = scenario["tower"]["id"]
        sector_id = scenario["sector"]["id"]

        activated_tower = validate_success(
            api.change_tower_status(tower_id, {"to_status": "ACTIVE"}, network_engineer), 200
        )
        assert_tower(activated_tower)
        assert activated_tower["status"] == "ACTIVE"
        assert activated_tower["backhaul_accepted_mbps"] == 500, (
            "the accepted circuit's committed_mbps is already on the activation response, "
            f"got {activated_tower['backhaul_accepted_mbps']}"
        )
        assert activated_tower["active_sector_count"] == 0, (
            f"the sector is still PLANNED, got {activated_tower['active_sector_count']}"
        )

        reread_tower = validate_success(api.get_tower(tower_id, network_engineer), 200)
        assert reread_tower["backhaul_accepted_mbps"] == activated_tower["backhaul_accepted_mbps"]
        assert reread_tower["version"] == activated_tower["version"], (
            "a follow-up read adds nothing: the write already returned the settled record"
        )

        activated_sector = validate_success(
            api.activate_sector(sector_id, network_engineer), 200
        )
        assert_sector(activated_sector)
        assert activated_sector["status"] == "ACTIVE"
        assert activated_sector["capacity_posture"] == "OPEN", (
            f"an empty sector on accepted transport is OPEN, got {activated_sector['capacity_posture']}"
        )
        assert activated_sector["committed_mbps"] == 0
        assert activated_sector["remaining_allowance_mbps"] == 200, (
            f"floor(25 * 8.0) less nothing committed, got {activated_sector['remaining_allowance_mbps']}"
        )
        assert activated_sector["oversubscription_ratio"] == pytest.approx(0.0, abs=0.0005)

        tower_after_sector = validate_success(api.get_tower(tower_id, network_engineer), 200)
        assert tower_after_sector["active_sector_count"] == 1, (
            "activating the sector recomputed the parent's count, got "
            f"{tower_after_sector['active_sector_count']}"
        )
        assert tower_after_sector["backhaul_accepted_mbps"] == 500

    def test_the_commercial_chain_returns_each_recomputed_ledger_as_it_writes_it(
        self, api, sales_agent, network_engineer
    ):
        """PRD 3.5: "When at least one sector is eligible, the top-ranked one becomes the
        enquiry's `qualified_sector_id`, the enquiry moves `EVALUATING → QUALIFIED`, and
        `qualification_expires_at` is set to the current logical clock advanced by the
        qualification validity of 30 days."
        PRD 3.5: "The desktop study writes its findings onto the enquiry as
        `desktop_los_margin_m`, `desktop_required_mast_height_m` and `desktop_mounting_type`;
        a denial reached at step 1 or step 2 records no geometry, and a denial for mast limit
        records the margin and the mast requirement while leaving `desktop_mounting_type`
        absent."
        PRD 3.6: "A successful reservation opens in `HELD` `status` with `origin` `DIRECT`,
        no `release_reason`, and an `expires_at` set to the current logical clock advanced by
        `hold_days` days."
        PRD 3.6: "Its side effects on the sector are immediate: `held_mbps` rises by the
        reserved amount, `committed_mbps`, `oversubscription_ratio`,
        `remaining_allowance_mbps` and `capacity_posture` are all recomputed, and the
        sector's `version` is incremented — which invalidates any other caller's
        `expected_sector_version` and forces them to re-read."
        PRD 3.6: "On the sector, `held_mbps` falls by the reservation's amount and
        `sold_mbps` rises by exactly the same amount, so `committed_mbps` and hence
        `oversubscription_ratio`, `remaining_allowance_mbps` and `capacity_posture` are
        **unchanged** by the conversion — the reservation was always a stand-in for this
        account, and the ledger simply reclassifies the bandwidth from reserved to sold."
        PRD 3.6: "It opens with `service_status` `PENDING_INSTALL` and `usage_priority`
        `STANDARD`."

        Design: Corner/consistency_model/every_write_returns_its_own_recomputed_derived_fields_with_no_second_read
        """
        scenario = setup_active_plant()
        tower_id = scenario["tower"]["id"]
        plan = scenario["plan"]
        sector_id = scenario["sector"]["id"]

        request = validate_success(
            api.create_serviceability_request(
                create_serviceability_request_payload(tower_id, plan["id"]), sales_agent
            ),
            201,
        )
        assert_serviceability_request(request)
        assert request["status"] == "QUALIFIED", f"got {request['status']}"
        assert request["qualified_sector_id"] == sector_id
        assert request["desktop_los_margin_m"] == pytest.approx(28.5, abs=0.005), (
            "1245.0 m antenna against a 1213.0 m obstruction top, 3.0 m clearance and the "
            f"0.5 m safety margin, got {request['desktop_los_margin_m']}"
        )
        assert request["desktop_required_mast_height_m"] == pytest.approx(2.5, abs=0.005)
        assert request["desktop_mounting_type"] == "NON_PEN_ROOF_TRIPOD"
        assert request["intake_sequence"] == 1, (
            f"the first enquiry of the system, got {request['intake_sequence']}"
        )
        assert request["qualification_expires_at"].startswith("2026-08-31T00:00:00"), (
            "the clock sits at 2026-08-01T00:00:00Z and the validity is 30 days, got "
            f"{request['qualification_expires_at']!r}"
        )

        sector_now = validate_success(api.get_sector(sector_id, network_engineer), 200)
        hold = validate_success(
            api.create_capacity_hold(
                {
                    "serviceability_request_id": request["id"],
                    "expected_sector_version": sector_now["version"],
                },
                sales_agent,
            ),
            201,
        )
        assert_capacity_hold(hold)
        assert hold["status"] == "HELD"
        assert hold["sector_id"] == sector_id
        assert hold["held_mbps"] == 50, (
            f"the reservation is always plan-sized, got {hold['held_mbps']}"
        )
        assert hold["origin"] == "DIRECT"
        assert hold.get("release_reason") is None
        assert hold["hold_days"] == 14, f"the window defaults to 14, got {hold['hold_days']}"
        assert hold["expires_at"].startswith("2026-08-15T00:00:00"), (
            f"the clock advanced by 14 days, got {hold['expires_at']!r}"
        )

        held_sector = validate_success(api.get_sector(sector_id, network_engineer), 200)
        assert held_sector["held_mbps"] == 50
        assert held_sector["sold_mbps"] == 0
        assert held_sector["committed_mbps"] == 50
        assert held_sector["oversubscription_ratio"] == pytest.approx(2.000, abs=0.0005)
        assert held_sector["capacity_posture"] == "OPEN", (
            f"2.000 is below half of the 8.0 ceiling, got {held_sector['capacity_posture']}"
        )
        assert held_sector["version"] > sector_now["version"], (
            "the reservation incremented the sector's version"
        )

        subscriber = validate_success(
            api.create_subscriber(
                {
                    "serviceability_request_id": request["id"],
                    "service_plan_id": plan["id"],
                    "billing_email": "dana.reyes@example.com",
                    "equipment_mode": "RENTAL",
                },
                sales_agent,
            ),
            201,
        )
        assert_subscriber(subscriber)
        assert subscriber["service_status"] == "PENDING_INSTALL"
        assert subscriber["usage_priority"] == "STANDARD"
        assert subscriber["account_number"] == "RB-000001", (
            f"the first account of the series, got {subscriber['account_number']!r}"
        )
        assert subscriber["sector_id"] == sector_id
        assert subscriber["equipment_monthly_charge_cents"] == 0, (
            "the radio is merely assigned, so no recurring charge has begun, got "
            f"{subscriber['equipment_monthly_charge_cents']}"
        )
        assert subscriber["effective_downstream_mbps"] == pytest.approx(50.0, abs=0.005)

        sold_sector = validate_success(api.get_sector(sector_id, network_engineer), 200)
        assert sold_sector["held_mbps"] == 0, (
            f"the reservation was reclassified, not doubled, got {sold_sector['held_mbps']}"
        )
        assert sold_sector["sold_mbps"] == 50
        assert sold_sector["committed_mbps"] == 50, (
            "committed_mbps is unchanged by the conversion, got "
            f"{sold_sector['committed_mbps']}"
        )
        assert sold_sector["oversubscription_ratio"] == pytest.approx(2.000, abs=0.0005)
        assert sold_sector["remaining_allowance_mbps"] == 150

        _, held_meta = validate_paginated(
            api.list_capacity_holds(sales_agent, params={"status": "HELD"})
        )
        assert held_meta["total_count"] == 0
        consumed_rows, consumed_meta = validate_paginated(
            api.list_capacity_holds(sales_agent, params={"status": "CONSUMED"})
        )
        assert consumed_meta["total_count"] == 1
        assert consumed_rows[0]["id"] == hold["id"]
