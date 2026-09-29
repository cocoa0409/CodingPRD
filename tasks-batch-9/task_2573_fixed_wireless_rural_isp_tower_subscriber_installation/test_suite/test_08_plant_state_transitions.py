"""State machines of the radio-frequency plant.

Tower site lifecycle, backhaul transport circuits, sector activation and
interference coordination: the declared moves, the transitions that are not
declared, the terminal states, and the cascades a declared move fires.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_no_mutation,
    change_circuit_state,
    change_tower_status,
    create_accepted_circuit,
    create_backhaul_circuit,
    create_coordination,
    create_outage,
    create_sector,
    create_spectrum_license,
    create_tower,
    create_work_order,
    get_capacity_hold,
    get_sector,
    get_serviceability_request,
    get_tower,
    is_iso8601_timestamp,
    make_network_engineer_headers,
    respond_to_coordination,
    setup_active_plant,
    setup_held_reservation,
    setup_pending_install_subscriber,
    validate_error,
    validate_success,
)

CLOCK_AT_STARTUP = "2026-08-01T00:00:00"


def _two_tower_sectors():
    """Two towers sharing one licence, each carrying one sector that has never
    been activated, so a coordination between them crosses a tower boundary.

    Sector A boresights 90.0 degrees on 3555.0/10.0 MHz at 25.0 dBm conducted
    with 17.0 dBi of gain; sector B boresights 100.0 degrees on 3620.0/10.0 MHz,
    so the circular separation is 10 degrees and the guard-band test bites.
    """
    tower_a = create_tower()
    tower_b = create_tower(latitude=41.27, longitude=-104.73)
    license_ = create_spectrum_license(channel_center_mhz=3600.0, channel_width_mhz=100.0)
    sector_a = create_sector(
        tower_a["id"],
        license_["id"],
        azimuth_deg=90.0,
        channel_center_mhz=3555.0,
        channel_width_mhz=10.0,
        tx_power_dbm=25.0,
        antenna_gain_dbi=17.0,
    )
    sector_b = create_sector(
        tower_b["id"],
        license_["id"],
        azimuth_deg=100.0,
        channel_center_mhz=3620.0,
        channel_width_mhz=10.0,
        tx_power_dbm=25.0,
        antenna_gain_dbi=17.0,
    )
    return {
        "tower_a": tower_a,
        "tower_b": tower_b,
        "license": license_,
        "sector_a": sector_a,
        "sector_b": sector_b,
    }


class TestTowerSiteLifecycle:
    def test_planned_to_active_recomputes_backhaul_accepted_mbps(self, api, network_engineer):
        """PRD 3.1: "Bringing a `PLANNED` site to `ACTIVE` requires that at least one
        circuit on the tower be in `ACCEPTED` state; if none is, the request is refused
        with `ERR_BACKHAUL_NOT_ACCEPTED`."
        PRD 3.1: "Activation recomputes `backhaul_accepted_mbps` and recomputes
        `capacity_posture` on every sector of the tower."
        PRD 3.1: "A tower's `backhaul_accepted_mbps` is the `committed_mbps` of the
        circuit on that tower whose `state` is `ACCEPTED`, and it is zero whenever no
        circuit on the tower is `ACCEPTED`."
        PRD 3.1: "A tower's `active_sector_count` is at all times the number of its
        sectors whose `status` is `ACTIVE`, so decommissioning drives it to zero."

        Design: Corner/state_machines/tower_planned_to_active_recomputes_backhaul_rate_and_bumps_only_the_tower_version
        """
        tower = create_tower()
        assert tower["status"] == "PLANNED", "a freshly registered site opens in PLANNED"
        create_accepted_circuit(tower["id"], measured_mbps=505.0, committed_mbps=500)

        response = api.change_tower_status(
            tower["id"],
            {"to_status": "ACTIVE", "reason": "acceptance testing complete"},
            network_engineer,
        )
        activated = validate_success(response, 200)

        assert activated["status"] == "ACTIVE", (
            f"PLANNED -> ACTIVE is a declared move, got {activated['status']!r}"
        )
        assert activated["backhaul_accepted_mbps"] == 500, (
            "backhaul_accepted_mbps is the ACCEPTED circuit's committed_mbps of 500, "
            f"not its measured 505.0, got {activated['backhaul_accepted_mbps']}"
        )
        assert activated["active_sector_count"] == 0, (
            "the tower carries no sector at all, so active_sector_count stays 0, got "
            f"{activated['active_sector_count']}"
        )

    def test_activation_without_an_accepted_circuit_is_refused(self, api, network_engineer):
        """PRD 3.1: "Bringing a `PLANNED` site to `ACTIVE` requires that at least one
        circuit on the tower be in `ACCEPTED` state; if none is, the request is refused
        with `ERR_BACKHAUL_NOT_ACCEPTED`."
        PRD 3.1: "A tower's `backhaul_accepted_mbps` is the `committed_mbps` of the
        circuit on that tower whose `state` is `ACCEPTED`, and it is zero whenever no
        circuit on the tower is `ACCEPTED`."

        Design: Corner/state_machines/tower_activation_without_an_accepted_circuit_is_rejected
        """
        tower = create_tower()
        circuit = create_backhaul_circuit(tower["id"], committed_mbps=500)
        installed = change_circuit_state(circuit["id"], "INSTALLED")
        assert installed["state"] == "INSTALLED", "setup drives the circuit only as far as INSTALLED"

        response = api.change_tower_status(
            tower["id"],
            {"to_status": "ACTIVE", "reason": "premature activation"},
            network_engineer,
        )
        validate_error(response, ApiErrorId.ERR_BACKHAUL_NOT_ACCEPTED)

        after = get_tower(tower["id"])
        assert after["status"] == "PLANNED", (
            f"the refused activation must leave the site PLANNED, got {after['status']!r}"
        )
        assert after["backhaul_accepted_mbps"] == 0, (
            "no circuit on the tower is ACCEPTED, so backhaul_accepted_mbps is zero, got "
            f"{after['backhaul_accepted_mbps']}"
        )

    @pytest.mark.parametrize("to_status", ["MAINTENANCE", "DECOMMISSIONED"])
    def test_undeclared_move_out_of_planned_is_refused(self, api, network_engineer, to_status):
        """PRD 3.1: "`ACTIVE → MAINTENANCE` carries no additional precondition beyond the
        site currently being `ACTIVE`; maintenance does **not** freeze sectors and does not
        disturb capacity — it is an operational marker used by outage reporting."
        PRD 3.1: "Decommissioning is reachable from either `ACTIVE` or `MAINTENANCE`, and
        it is guarded commercially rather than technically: no account served by any sector
        of the tower may still be in `PENDING_INSTALL`, `ACTIVE` or `SUSPENDED`
        `service_status`."
        PRD 3.1: "`DECOMMISSIONED` is terminal, and any requested `to_status` that is not a
        declared move out of the tower's current `status` — including any attempt to leave
        `DECOMMISSIONED` — is refused with `ERR_INVALID_TOWER_STATE`."

        Design: Corner/state_machines/tower_planned_to_maintenance_is_not_a_declared_transition
        """
        tower = create_tower()

        response = api.change_tower_status(
            tower["id"], {"to_status": to_status, "reason": "undeclared jump"}, network_engineer
        )
        validate_error(response, ApiErrorId.ERR_INVALID_TOWER_STATE)

        after = get_tower(tower["id"])
        assert after["status"] == "PLANNED", (
            f"the refused move must leave the site PLANNED, got {after['status']!r}"
        )

    def test_decommissioned_tower_cannot_be_left(self, api, network_engineer):
        """PRD 3.1: "`DECOMMISSIONED` is terminal, and any requested `to_status` that is not
        a declared move out of the tower's current `status` — including any attempt to leave
        `DECOMMISSIONED` — is refused with `ERR_INVALID_TOWER_STATE`."

        Design: Corner/state_machines/tower_planned_to_maintenance_is_not_a_declared_transition
        """
        plant = setup_active_plant(activate_the_sector=False)
        decommissioned = change_tower_status(
            plant["tower"]["id"], "DECOMMISSIONED", reason="site lease terminated"
        )
        assert decommissioned["status"] == "DECOMMISSIONED", "setup must reach the terminal status"

        response = api.change_tower_status(
            plant["tower"]["id"], {"to_status": "ACTIVE", "reason": "revive the site"}, network_engineer
        )
        validate_error(response, ApiErrorId.ERR_INVALID_TOWER_STATE)

        after = get_tower(plant["tower"]["id"])
        assert after["status"] == "DECOMMISSIONED", (
            f"DECOMMISSIONED is terminal, got {after['status']!r}"
        )

    def test_decommission_disables_sectors_releases_holds_and_expires_qualifications(
        self, api, network_engineer
    ):
        """PRD 3.1: "When the guard passes, the decommission cascade runs in full: every
        sector on the tower whose `status` is `PLANNED` or `ACTIVE` transitions to
        `DISABLED`; because each of those sectors has left `ACTIVE`, every reservation on
        them in `HELD` status transitions to `RELEASED` with a `release_reason` of
        `SECTOR_DISABLED`; and because each of those reservations has left `HELD`, every
        qualification they referenced in `QUALIFIED` or `CAPACITY_DEFERRED` transitions to
        `EXPIRED`."
        PRD 3.2: "A sector leaving `ACTIVE` for `DISABLED` recomputes the tower's
        `active_sector_count`, sets its own `capacity_posture` to `FROZEN`, records
        `capacity_policy_note` as an explanation that the sector was disabled with its
        tower, and releases every reservation still `HELD` on it with a `release_reason` of
        `SECTOR_DISABLED`."
        PRD 3.5: "`QUALIFIED` does move to `EXPIRED`, but only as a consequence of its
        reservation leaving `HELD` without being consumed, and that transition clears
        `qualified_sector_id` so the enquiry no longer points at a sector it has no claim
        on."

        Design: Corner/state_machines/tower_decommission_disables_sectors_releases_holds_and_expires_requests
        """
        scenario = setup_held_reservation()
        assert scenario["hold"]["status"] == "HELD", "setup must leave the reservation HELD"
        assert scenario["request"]["status"] == "QUALIFIED", "setup must leave the enquiry QUALIFIED"

        response = api.change_tower_status(
            scenario["tower"]["id"],
            {"to_status": "DECOMMISSIONED", "reason": "site lease terminated"},
            network_engineer,
        )
        tower = validate_success(response, 200)

        assert tower["status"] == "DECOMMISSIONED", f"got {tower['status']!r}"
        assert tower["active_sector_count"] == 0, (
            "decommissioning drives active_sector_count to zero, got "
            f"{tower['active_sector_count']}"
        )

        sector = get_sector(scenario["sector"]["id"])
        assert sector["status"] == "DISABLED", (
            f"an ACTIVE sector on a decommissioned tower is DISABLED, got {sector['status']!r}"
        )
        assert sector["capacity_posture"] == "FROZEN", (
            f"a DISABLED sector's posture is FROZEN, got {sector['capacity_posture']!r}"
        )
        assert sector.get("capacity_policy_note") is not None, (
            "the disabling records capacity_policy_note as an explanation that the sector "
            "was disabled with its tower"
        )
        assert sector["held_mbps"] == 0, (
            f"the released reservation gives its bandwidth back, got held_mbps {sector['held_mbps']}"
        )
        assert sector["sold_mbps"] == 0, "no account was ever opened on this sector"
        assert sector["committed_mbps"] == 0, (
            f"committed_mbps is sold plus held, got {sector['committed_mbps']}"
        )
        assert sector["oversubscription_ratio"] == pytest.approx(0.0, abs=0.0005), (
            f"an empty ledger carries a ratio of 0.000, got {sector['oversubscription_ratio']}"
        )

        hold = get_capacity_hold(scenario["hold"]["id"])
        assert hold["status"] == "RELEASED", (
            f"the reservation on a disabled sector is RELEASED, got {hold['status']!r}"
        )
        assert hold["release_reason"] == "SECTOR_DISABLED", (
            "the release_reason distinguishes this path from BACKHAUL_DEGRADED and LAPSED, got "
            f"{hold['release_reason']!r}"
        )

        request = get_serviceability_request(scenario["request"]["id"])
        assert request["status"] == "EXPIRED", (
            f"the qualification behind a lost reservation EXPIRES, got {request['status']!r}"
        )
        assert request.get("qualified_sector_id") is None, (
            "the transition clears qualified_sector_id, got "
            f"{request.get('qualified_sector_id')!r}"
        )

    def test_decommission_with_a_pending_install_account_is_refused(self, api, network_engineer):
        """PRD 3.1: "Decommissioning is reachable from either `ACTIVE` or `MAINTENANCE`, and
        it is guarded commercially rather than technically: no account served by any sector
        of the tower may still be in `PENDING_INSTALL`, `ACTIVE` or `SUSPENDED`
        `service_status`."
        PRD 3.1: "If one is, the request is refused with `ERR_TOWER_HAS_ACTIVE_SUBSCRIBERS`."
        PRD 3.3: "`sold_mbps` is the sum, over every account whose `sector_id` is this
        sector and whose `service_status` is `PENDING_INSTALL`, `ACTIVE` or `SUSPENDED`, of
        the `downstream_mbps` of that account's **current** plan."

        Design: Corner/state_machines/tower_decommission_with_a_pending_install_subscriber_returns_409
        """
        scenario = setup_pending_install_subscriber()
        assert scenario["subscriber"]["service_status"] == "PENDING_INSTALL", (
            "setup must leave the account short of activation"
        )

        response = api.change_tower_status(
            scenario["tower"]["id"],
            {"to_status": "DECOMMISSIONED", "reason": "attempt with a live account"},
            network_engineer,
        )
        validate_error(response, ApiErrorId.ERR_TOWER_HAS_ACTIVE_SUBSCRIBERS)

        tower = get_tower(scenario["tower"]["id"])
        assert tower["status"] == "ACTIVE", (
            f"the refused decommission leaves the site ACTIVE, got {tower['status']!r}"
        )

        sector = get_sector(scenario["sector"]["id"])
        assert sector["status"] == "ACTIVE", (
            f"the refused cascade wrote nothing, got sector status {sector['status']!r}"
        )
        assert sector["sold_mbps"] == 50, (
            "the PENDING_INSTALL account still contributes its plan's 50 downstream Mbps, got "
            f"{sector['sold_mbps']}"
        )


class TestBackhaulCircuitMachine:
    @pytest.mark.parametrize(
        "to_state,extra",
        [
            ("ACCEPTED", {"measured_mbps": 505.0}),
            ("DEGRADED", {}),
        ],
    )
    def test_ordered_circuit_cannot_skip_installation(
        self, api, network_engineer, to_state, extra
    ):
        """PRD 3.1: "Circuits move through a small cyclic machine, driven by a
        `NetworkEngineer` who names the target `to_state` and may attach a free-text `note`.
        `ORDERED → INSTALLED` records that the carrier has delivered."
        PRD 3.1: "Any target state that is not a declared move out of the circuit's current
        `state` is refused with `ERR_INVALID_CIRCUIT_STATE`."
        PRD 3.1: "Acceptance stores the supplied `measured_mbps`, stamps `accepted_at` with
        the current logical clock, clears `degraded_since`, recomputes the parent tower's
        `backhaul_accepted_mbps`, and recomputes the capacity posture of every sector on
        that tower."

        Design: Corner/state_machines/backhaul_circuit_ordered_to_accepted_skips_a_state_and_is_rejected
        """
        tower = create_tower()
        circuit = create_backhaul_circuit(tower["id"], committed_mbps=500)
        assert circuit["state"] == "ORDERED", "a newly ordered circuit opens in ORDERED"

        payload = {"to_state": to_state}
        payload.update(extra)
        response = api.change_circuit_state(circuit["id"], payload, network_engineer)
        validate_error(response, ApiErrorId.ERR_INVALID_CIRCUIT_STATE)

        after = validate_success(api.get_backhaul_circuit(circuit["id"], network_engineer), 200)
        assert after["state"] == "ORDERED", (
            f"the refused move leaves the circuit ORDERED, got {after['state']!r}"
        )
        assert after.get("measured_mbps") is None, (
            "a refused acceptance stores no measured_mbps, got "
            f"{after.get('measured_mbps')!r}"
        )
        assert after.get("accepted_at") is None, (
            f"a refused acceptance stamps no accepted_at, got {after.get('accepted_at')!r}"
        )
        assert after.get("degraded_since") is None, (
            f"a refused degradation stamps no degraded_since, got {after.get('degraded_since')!r}"
        )

        parent = get_tower(tower["id"])
        assert parent["backhaul_accepted_mbps"] == 0, (
            "no acceptance happened, so the tower's accepted rate stays zero, got "
            f"{parent['backhaul_accepted_mbps']}"
        )

    @pytest.mark.parametrize("from_state", ["ORDERED", "INSTALLED"])
    @pytest.mark.parametrize("to_state", ["INSTALLED", "ACCEPTED", "ORDERED"])
    def test_cancelled_circuit_is_terminal(self, api, network_engineer, from_state, to_state):
        """PRD 3.1: "Both `ORDERED` and `INSTALLED` may go straight to `CANCELLED`, which is
        terminal."
        PRD 3.1: "Any target state that is not a declared move out of the circuit's current
        `state` is refused with `ERR_INVALID_CIRCUIT_STATE`."

        Design: Corner/state_machines/cancelled_circuit_is_terminal_and_further_state_changes_are_refused_with_409
        """
        tower = create_tower()
        circuit = create_backhaul_circuit(tower["id"], committed_mbps=500)
        if from_state == "INSTALLED":
            circuit = change_circuit_state(circuit["id"], "INSTALLED")
        cancelled = change_circuit_state(circuit["id"], "CANCELLED", note="carrier order withdrawn")
        assert cancelled["state"] == "CANCELLED", (
            f"{from_state} may go straight to CANCELLED, got {cancelled['state']!r}"
        )

        payload = {"to_state": to_state}
        if to_state == "ACCEPTED":
            payload["measured_mbps"] = 505.0
        response = api.change_circuit_state(circuit["id"], payload, network_engineer)
        validate_error(response, ApiErrorId.ERR_INVALID_CIRCUIT_STATE)

        after = validate_success(api.get_backhaul_circuit(circuit["id"], network_engineer), 200)
        assert after["state"] == "CANCELLED", (
            f"CANCELLED is terminal, got {after['state']!r}"
        )
        assert_no_mutation(cancelled, after, entity="cancelled circuit")

        parent = get_tower(tower["id"])
        assert parent["backhaul_accepted_mbps"] == 0, (
            "a cancelled circuit never contributes an accepted rate, got "
            f"{parent['backhaul_accepted_mbps']}"
        )


def test_new_rows_open_in_their_declared_initial_states(api, network_engineer):
    """PRD 3.1: "A newly ordered circuit opens in `ORDERED` `state` with `measured_mbps`,
    `accepted_at` and `degraded_since` all absent."
    PRD 3.9: "The outage opens in `OPEN` `status` with `ended_at`, `peak_wind_mph` and
    `duration_minutes` all absent, `sla_excluded` false and `total_credited_cents` zero."
    PRD 3.4: "A newly opened coordination sits in `REQUESTED` `status` with `round_number`
    at 1 and `decision_note`, `decided_by_user_id` and `last_response_at` all absent."
    PRD 3.7: "The work order opens in `SCHEDULED` `status` with `resurvey_count` at zero and
    every survey and completion field absent."

    Design: Corner/state_machines/new_rows_start_in_their_declared_initial_states
    """
    pair = _two_tower_sectors()

    circuit = create_backhaul_circuit(pair["tower_a"]["id"], committed_mbps=500)
    assert circuit["state"] == "ORDERED", f"got circuit state {circuit['state']!r}"
    assert circuit.get("measured_mbps") is None, f"got {circuit.get('measured_mbps')!r}"
    assert circuit.get("accepted_at") is None, f"got {circuit.get('accepted_at')!r}"
    assert circuit.get("degraded_since") is None, f"got {circuit.get('degraded_since')!r}"
    assert circuit["version"] == 1, f"a freshly created row is at version 1, got {circuit['version']}"

    outage = create_outage(pair["tower_a"]["id"])
    assert outage["status"] == "OPEN", f"got outage status {outage['status']!r}"
    assert outage.get("ended_at") is None, f"got {outage.get('ended_at')!r}"
    assert outage.get("peak_wind_mph") is None, f"got {outage.get('peak_wind_mph')!r}"
    assert outage.get("duration_minutes") is None, f"got {outage.get('duration_minutes')!r}"
    assert outage["sla_excluded"] is False, (
        f"a fresh outage opens with sla_excluded false, got {outage['sla_excluded']!r}"
    )
    assert outage["total_credited_cents"] == 0, f"got {outage['total_credited_cents']}"

    coordination = create_coordination(pair["sector_a"]["id"], pair["sector_b"]["id"])
    assert coordination["status"] == "REQUESTED", f"got status {coordination['status']!r}"
    assert coordination["round_number"] == 1, (
        f"a fresh negotiation sits at round 1, got {coordination['round_number']}"
    )
    assert coordination.get("decision_note") is None, f"got {coordination.get('decision_note')!r}"
    assert coordination.get("decided_by_user_id") is None, (
        f"got {coordination.get('decided_by_user_id')!r}"
    )
    assert coordination.get("last_response_at") is None, (
        f"got {coordination.get('last_response_at')!r}"
    )

    scenario = setup_pending_install_subscriber()
    work_order = create_work_order(scenario["subscriber"]["id"])
    assert work_order["status"] == "SCHEDULED", f"got work order status {work_order['status']!r}"
    assert work_order["resurvey_count"] == 0, f"got {work_order['resurvey_count']}"
    for absent in (
        "field_los_margin_m",
        "recommended_mast_height_m",
        "recommended_mounting_type",
        "approved_mounting_type",
        "surveyed_by_user_id",
        "exception_approved_by_user_id",
        "installed_mast_height_m",
        "radio_serial",
        "installed_at",
        "install_invoice_total_cents",
    ):
        assert work_order.get(absent) is None, (
            f"every survey and completion field opens absent, got {absent}="
            f"{work_order.get(absent)!r}"
        )


class TestSectorActivation:
    def test_activating_an_already_active_sector_is_refused(self, api, network_engineer):
        """PRD 3.2: "Bringing a sector on air moves it `PLANNED → ACTIVE`. Three
        preconditions apply, and each has its own code: the sector's `status` must be
        `PLANNED`, and activating a sector in any other status is refused with
        `ERR_INVALID_SECTOR_STATE`; the parent tower's `status` must be `ACTIVE`, and a
        tower in any other status is refused with `ERR_INVALID_TOWER_STATE`; and the bound
        licence's clock-derived `status` must be `ACTIVE` at the current logical clock, a
        `PENDING` or `EXPIRED` licence being refused with `ERR_LICENSE_NOT_EFFECTIVE`."
        PRD 3.2: "Activation recomputes the parent tower's `active_sector_count` and the
        sector's own `capacity_posture`."

        Design: Corner/state_machines/repeated_sector_activation_is_refused_with_invalid_sector_state
        """
        plant = setup_active_plant()
        sector = plant["sector"]
        assert sector["status"] == "ACTIVE", "setup must leave the sector on air"

        tower_before = get_tower(plant["tower"]["id"])
        assert tower_before["active_sector_count"] == 1, (
            f"the first activation counted the sector, got {tower_before['active_sector_count']}"
        )

        response = api.activate_sector(sector["id"], network_engineer)
        validate_error(response, ApiErrorId.ERR_INVALID_SECTOR_STATE)

        after = get_sector(sector["id"])
        assert after["status"] == "ACTIVE", (
            f"the refused second activation leaves the sector ACTIVE, got {after['status']!r}"
        )
        assert_no_mutation(sector, after, entity="already-active sector")

        tower_after = get_tower(plant["tower"]["id"])
        assert tower_after["active_sector_count"] == 1, (
            "a refused activation must not count the sector twice, got "
            f"{tower_after['active_sector_count']}"
        )
        assert_no_mutation(tower_before, tower_after, entity="parent tower")

    def test_activating_a_disabled_sector_is_refused(self, api, network_engineer):
        """PRD 3.2: "Sectors are never disabled by direct request; `DISABLED` is reached only
        as a consequence of the parent tower being decommissioned, and it is terminal."
        PRD 3.2: "Once a sector is `DISABLED`, any capacity operation addressed to it is
        refused with `ERR_INVALID_SECTOR_STATE`."

        Design: Corner/state_machines/repeated_sector_activation_is_refused_with_invalid_sector_state
        """
        plant = setup_active_plant(activate_the_sector=False)
        change_tower_status(plant["tower"]["id"], "DECOMMISSIONED", reason="site retired")
        disabled = get_sector(plant["sector"]["id"])
        assert disabled["status"] == "DISABLED", (
            f"the decommission cascade disables a PLANNED sector, got {disabled['status']!r}"
        )
        assert disabled["capacity_posture"] == "FROZEN", (
            f"a sector leaving PLANNED for DISABLED is FROZEN, got {disabled['capacity_posture']!r}"
        )

        response = api.activate_sector(plant["sector"]["id"], network_engineer)
        validate_error(response, ApiErrorId.ERR_INVALID_SECTOR_STATE)

        after = get_sector(plant["sector"]["id"])
        assert after["status"] == "DISABLED", f"DISABLED is terminal, got {after['status']!r}"
        assert_no_mutation(disabled, after, entity="disabled sector")


class TestCoordinationMachine:
    def test_accepting_applies_the_negotiated_plan_to_the_requesting_sector(
        self, api, network_engineer
    ):
        """PRD 3.4: "Accepting moves the coordination `REQUESTED → ACCEPTED`, which is
        terminal, and **applies the proposal to the requesting sector**: its
        `channel_center_mhz` becomes `proposed_channel_center_mhz`, its `channel_width_mhz`
        becomes `proposed_channel_width_mhz`, and its `tx_power_dbm` becomes
        `proposed_eirp_dbm` less that sector's own `antenna_gain_dbi` — the negotiation is
        conducted in radiated terms but the radio is configured in conducted terms."
        PRD 3.4: "The sector's `lower_edge_mhz`, `upper_edge_mhz` and `eirp_dbm` are then
        recomputed from the new channel and power, and the record `version` of both the
        coordination and the requesting sector is incremented."
        PRD 3.4: "Note that the derived `eirp_dbm` after application therefore equals the
        agreed `proposed_eirp_dbm`."
        PRD 3.4: "Every response, whatever its outcome, stamps `last_response_at` with the
        current logical clock and records `decided_by_user_id` as the responding operator's
        identifier."

        Design: Corner/state_machines/coordination_accept_applies_the_negotiated_plan_to_the_requesting_sector
        """
        pair = _two_tower_sectors()
        coordination = create_coordination(
            pair["sector_a"]["id"],
            pair["sector_b"]["id"],
            proposed_channel_center_mhz=3565.0,
            proposed_channel_width_mhz=10.0,
            proposed_eirp_dbm=44.0,
            guard_band_mhz=2.0,
        )
        assert coordination["status"] == "REQUESTED", f"got {coordination['status']!r}"

        responder = make_network_engineer_headers("op-neteng-neighbor")
        response = api.respond_to_coordination(
            coordination["id"],
            {"decision": "ACCEPT", "note": "Agreed, shift away from our block"},
            responder,
        )
        accepted = validate_success(response, 200)

        assert accepted["status"] == "ACCEPTED", (
            f"REQUESTED -> ACCEPTED on an accept, got {accepted['status']!r}"
        )
        assert accepted["decided_by_user_id"] == "op-neteng-neighbor", (
            "decided_by_user_id is the responding operator's identifier, got "
            f"{accepted.get('decided_by_user_id')!r}"
        )
        assert is_iso8601_timestamp(accepted.get("last_response_at", "")), (
            f"last_response_at must be an ISO 8601 stamp, got {accepted.get('last_response_at')!r}"
        )
        assert accepted["last_response_at"].startswith(CLOCK_AT_STARTUP), (
            "last_response_at is the current logical clock, still at its startup reading, got "
            f"{accepted['last_response_at']!r}"
        )
        assert accepted["version"] == coordination["version"] + 1, (
            f"the coordination's version is incremented, got {accepted['version']}"
        )

        requester = get_sector(pair["sector_a"]["id"])
        assert requester["channel_center_mhz"] == 3565.0, (
            f"channel_center_mhz becomes the proposal's 3565.0, got {requester['channel_center_mhz']}"
        )
        assert requester["channel_width_mhz"] == 10.0, (
            f"channel_width_mhz becomes the proposal's 10.0, got {requester['channel_width_mhz']}"
        )
        assert requester["tx_power_dbm"] == 27.0, (
            "tx_power_dbm is the agreed 44.0 dBm radiated less the sector's own 17.0 dBi of "
            f"gain, got {requester['tx_power_dbm']}"
        )
        assert requester["eirp_dbm"] == 44.0, (
            "the recomputed eirp_dbm equals the agreed proposed_eirp_dbm of 44.0, got "
            f"{requester['eirp_dbm']}"
        )
        assert requester["lower_edge_mhz"] == 3560.0, (
            f"lower_edge_mhz is 3565.0 less half of 10.0, got {requester['lower_edge_mhz']}"
        )
        assert requester["upper_edge_mhz"] == 3570.0, (
            f"upper_edge_mhz is 3565.0 plus half of 10.0, got {requester['upper_edge_mhz']}"
        )
        assert requester["version"] == pair["sector_a"]["version"] + 1, (
            f"the requesting sector's version is incremented, got {requester['version']}"
        )

        neighbor = get_sector(pair["sector_b"]["id"])
        for field in ("channel_center_mhz", "channel_width_mhz", "tx_power_dbm", "eirp_dbm"):
            assert neighbor[field] == pair["sector_b"][field], (
                f"the proposal is applied to the requesting sector only, but the neighbour's "
                f"{field} moved to {neighbor[field]}"
            )

    def test_second_response_to_a_rejected_coordination_is_refused(self, api, network_engineer):
        """PRD 3.4: "Rejecting moves the coordination `REQUESTED → REJECTED`, and `REJECTED`
        is likewise terminal. It records the response text as the `decision_note`, and leaves
        the requesting sector's channel and power completely untouched — no edge, no power
        and no version on the sector changes."
        PRD 3.4: "The coordination must be in `REQUESTED` status for any response to be
        entertained; a response addressed to a coordination in any other status is refused
        with `ERR_COORDINATION_NOT_OPEN`."

        Design: Corner/state_machines/second_response_to_a_rejected_coordination_returns_coordination_not_open
        """
        pair = _two_tower_sectors()
        coordination = create_coordination(pair["sector_a"]["id"], pair["sector_b"]["id"])

        rejected = respond_to_coordination(
            coordination["id"], "REJECT", note="Too close to our downlink"
        )
        assert rejected["status"] == "REJECTED", f"got {rejected['status']!r}"
        assert rejected.get("decision_note") is not None, (
            "the response text is recorded as the decision_note"
        )

        sector_after_rejection = get_sector(pair["sector_a"]["id"])
        assert_no_mutation(
            pair["sector_a"], sector_after_rejection, entity="requesting sector after a rejection"
        )
        for field in ("channel_center_mhz", "channel_width_mhz", "tx_power_dbm", "eirp_dbm",
                      "lower_edge_mhz", "upper_edge_mhz"):
            assert sector_after_rejection[field] == pair["sector_a"][field], (
                f"a rejection leaves the requesting sector untouched, but {field} moved to "
                f"{sector_after_rejection[field]}"
            )

        response = api.respond_to_coordination(
            coordination["id"], {"decision": "ACCEPT", "note": "Changed our mind"}, network_engineer
        )
        validate_error(response, ApiErrorId.ERR_COORDINATION_NOT_OPEN)

        after = validate_success(api.get_coordination(coordination["id"], network_engineer), 200)
        assert after["status"] == "REJECTED", f"REJECTED is terminal, got {after['status']!r}"
        assert_no_mutation(rejected, after, entity="rejected coordination")

        sector_final = get_sector(pair["sector_a"]["id"])
        assert_no_mutation(
            pair["sector_a"], sector_final, entity="requesting sector after a refused response"
        )

    @pytest.mark.parametrize("decision", ["ACCEPT", "REJECT", "REQUEST_REVISION", "WITHDRAW"])
    def test_no_response_is_entertained_once_the_negotiation_is_terminal(
        self, api, network_engineer, decision
    ):
        """PRD 3.4: "Withdrawing moves the coordination to `WITHDRAWN`, which is terminal, and
        is reachable from `REQUESTED` and from `REVISION_REQUESTED`. It stamps
        `last_response_at` and leaves both sectors untouched."
        PRD 3.4: "The coordination must be in `REQUESTED` status for any response to be
        entertained; a response addressed to a coordination in any other status is refused
        with `ERR_COORDINATION_NOT_OPEN`."

        Design: Corner/state_machines/second_response_to_a_rejected_coordination_returns_coordination_not_open
        """
        pair = _two_tower_sectors()
        coordination = create_coordination(pair["sector_a"]["id"], pair["sector_b"]["id"])
        withdrawn = respond_to_coordination(coordination["id"], "WITHDRAW", note="No longer needed")
        assert withdrawn["status"] == "WITHDRAWN", f"got {withdrawn['status']!r}"

        response = api.respond_to_coordination(
            coordination["id"], {"decision": decision, "note": "Second bite"}, network_engineer
        )
        validate_error(response, ApiErrorId.ERR_COORDINATION_NOT_OPEN)

        after = validate_success(api.get_coordination(coordination["id"], network_engineer), 200)
        assert after["status"] == "WITHDRAWN", f"WITHDRAWN is terminal, got {after['status']!r}"
        assert_no_mutation(withdrawn, after, entity="withdrawn coordination")

        for key in ("sector_a", "sector_b"):
            sector = get_sector(pair[key]["id"])
            assert_no_mutation(pair[key], sector, entity=f"{key} after a refused response")
