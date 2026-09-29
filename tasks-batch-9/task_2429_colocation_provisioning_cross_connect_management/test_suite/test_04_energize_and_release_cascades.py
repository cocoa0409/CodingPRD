"""Cascades that run to completion inside one request.

Two calls in this API touch four or five entities at once. Energizing a circuit walks
the circuit, its cabinet, the cabinet's row, whatever the row's new posture does to
its *other* cabinets and their circuits, and finally the contract's rollups. Releasing
ports walks the decommission order, the cabinet's cross-connects, those cross-connects'
ports, the ledger, the cabinet, its circuits, the row and the contract. Both are
exercised end to end here, hop by hop.
"""

from datetime import datetime
from typing import Any, Dict

from test_helpers import (
    ApiErrorId,
    ENGINEER_1,
    ENGINEER_2,
    FACILITY_MANAGER,
    validate_error,
    validate_success,
)
from test_helpers import assertions as ax, constants as k, factories as f, fixtures as fx


# ---------------------------------------------------------------------------
# module-local helpers
# ---------------------------------------------------------------------------


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating the `Z` suffix and any number of
    fractional digits, so an assertion compares instants and not spellings."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 timestamp, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_same_instant(actual: Any, expected: str, label: str) -> None:
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def _energize(api, circuit_id: str, row_id: str):
    """Energize carrying the row version the client has just observed."""
    return api.energize_circuit(
        circuit_id, {"expected_row_version": fx.row_version(api, row_id)}, ENGINEER_1
    )


# --- scenery for the energization cascade ----------------------------------

ROW_H8 = {
    "hall_code": "H8",
    "row_code": "R1",
    "cabinet_slot_count": 8,
    "design_density_kw_per_cabinet": 8.0,
    "max_row_power_kw": 200.0,
    "cooling_capacity_kw": 60.0,
    "escort_slot_count": 1,
    "decommission_flag": False,
}

CONTRACT_TWO_CABINETS = {
    "billing_mode": "COMMITTED_ONLY",
    "committed_cabinet_count": 2,
    "power_commit_kw": 20.0,
    "committed_bandwidth_mbps": 1000,
    "cross_connect_cap": 4,
    "term_start_date": "2026-07-01T00:00:00Z",
    "term_end_date": "2027-06-30T00:00:00Z",
    "committed_cage_sqft": 0,
    "redundancy_requirement": "N",
    "cross_connect_allowance": 0,
    "remote_hands_included_minutes": 0,
}


def _setup_row_one_step_from_its_density_cap(api) -> Dict[str, Any]:
    """An 8 kW-per-cabinet row holding two occupied slots, so its density ceiling is
    16.000 kW and its 1.10 rejection ceiling is 17.600 kW. Cabinet C01 is `INSTALLED`
    with an `APPROVED` 90 A / 240 V single-phase primary feed derated to 17.280 kW —
    admissible, and enough to cap the row. Cabinet C02 is a neighbour left `RESERVED`
    carrying a 25 A feed that never leaves `DESIGNED`.
    """
    scenario = fx.setup_installed_cabinet(
        api,
        row=ROW_H8,
        contract=CONTRACT_TWO_CABINETS,
        cabinet={"cabinet_code": "C01", "rated_power_kw": 18.0},
    )
    neighbour = fx.add_reserved_cabinet(
        api, scenario, cabinet_code="C02", rated_power_kw=10.0
    )
    primary = fx.add_approved_circuit(
        api,
        scenario,
        cabinet_id=scenario.cabinets[0]["id"],
        circuit_code="A-1",
        feed_side="A",
        redundancy_role="PRIMARY",
        breaker_amps=90,
        volts=240,
        phase="SINGLE",
    )
    neighbour_circuit = fx.add_designed_circuit(
        api,
        scenario,
        cabinet_id=neighbour["id"],
        circuit_code="A-2",
        feed_side="A",
        redundancy_role="PRIMARY",
        breaker_amps=25,
        volts=240,
        phase="SINGLE",
    )
    return {
        "scenario": scenario,
        "cabinet": scenario.cabinets[0],
        "neighbour": neighbour,
        "primary": primary,
        "neighbour_circuit": neighbour_circuit,
    }


# --- scenery for the port-release cascade ---------------------------------

ROW_H9_A = {
    "hall_code": "H9",
    "row_code": "R1",
    "cabinet_slot_count": 8,
    "design_density_kw_per_cabinet": 25.0,
    "max_row_power_kw": 200.0,
    "cooling_capacity_kw": 60.0,
    "escort_slot_count": 1,
    "decommission_flag": False,
}

ROW_H9_Z = dict(ROW_H9_A, row_code="R2")

CONTRACT_ONE_CABINET = {
    "billing_mode": "METERED_PLUS_COMMIT",
    "committed_cabinet_count": 1,
    "power_commit_kw": 20.0,
    "committed_bandwidth_mbps": 1000,
    "cross_connect_cap": 4,
    "term_start_date": "2026-07-01T00:00:00Z",
    "term_end_date": "2027-06-30T00:00:00Z",
    "committed_cage_sqft": 0,
    "redundancy_requirement": "N",
    "cross_connect_allowance": 0,
    "remote_hands_included_minutes": 0,
}


def _setup_decommission_ready_for_release(api) -> Dict[str, Any]:
    """Cabinet C01 in row H9/R1 is `ACTIVE` on a 50 A feed allocating 9.600 kW and
    carries one `ACTIVE` SMF cross-connect whose two ports — one in each row — are
    `ASSIGNED`. Its decommission order has been approved by a second operator and both
    physical steps recorded by two different engineers, so it waits at
    `READY_FOR_RELEASE`.
    """
    scenario = fx.setup_installed_cabinet(
        api,
        row=ROW_H9_A,
        contract=CONTRACT_ONE_CABINET,
        cabinet={"cabinet_code": "C01", "rated_power_kw": 20.0},
    )
    far_row = fx.create_row(api, **ROW_H9_Z)
    scenario.rows.append(far_row)
    far_cabinet = fx.create_cabinet(
        api, far_row["id"], cabinet_code="Z01", rated_power_kw=10.0, footprint_type="MEET_ME"
    )
    scenario.cabinets.append(far_cabinet)
    scenario.contacts.append(fx.create_contact(api, scenario.customer_id))

    circuit = fx.add_approved_circuit(
        api,
        scenario,
        cabinet_id=scenario.cabinets[0]["id"],
        circuit_code="A-1",
        feed_side="A",
        redundancy_role="PRIMARY",
        breaker_amps=50,
        volts=240,
        phase="SINGLE",
    )
    fx.energize_circuit(api, circuit["id"], scenario.row_id)

    a_port = fx.create_port(api, scenario.row_id, "PP-A", 1, "SMF")
    z_port = fx.create_port(api, far_row["id"], "PP-Z", 1, "SMF")
    scenario.ports.extend([a_port, z_port])

    order = fx.raise_cross_connect_order(api, scenario, cable_type="SMF")
    fx.propose_route(api, order["id"], a_port["id"], z_port["id"], ["PP-A", "PP-Z"])
    fx.move_order(api, order["id"], "APPROVED", FACILITY_MANAGER)
    fx.move_order(api, order["id"], "INSTALLED", ENGINEER_1)
    fx.move_order(api, order["id"], "ACTIVE", FACILITY_MANAGER)

    decommission = fx.raise_decommission_order(
        api, scenario, cabinet_id=scenario.cabinets[0]["id"]
    )
    fx.move_decommission(api, decommission["id"], "APPROVED")
    fx.record_step(api, decommission["id"], "EQUIPMENT_REMOVAL", ENGINEER_1)
    fx.record_step(api, decommission["id"], "CABLE_RECLAMATION", ENGINEER_2)

    return {
        "scenario": scenario,
        "cabinet": scenario.cabinets[0],
        "far_row": far_row,
        "circuit": circuit,
        "a_port": a_port,
        "z_port": z_port,
        "cross_connect": order,
        "decommission": decommission,
    }


# ---------------------------------------------------------------------------
# The energization cascade
# ---------------------------------------------------------------------------


class TestEnergizationCascade:
    def test_energize_allocates_clamped_power_and_advances_its_cabinet(self, api):
        """PRD §3.4: "`derated_kw` is the breaker amperage multiplied by the voltage, multiplied by the phase factor — 1.0 for a `SINGLE`-phase supply and 1.732 for a `THREE`-phase supply — divided by 1000 to convert volt-amperes to kilowatts, then multiplied by the 0.80 continuous-load derate that electrical code requires, and finally rounded half-up to three decimal places."
        PRD §3.4: "For a `PRIMARY` circuit, `allocated_kw` is the lesser of its derated capacity and the host cabinet's `rated_power_kw` — the cabinet nameplate clamps what the floor will bill for, and the clamp is applied to the already-rounded derated figure — while `cooling_contribution_kw` is the full derated capacity, because heat is not clamped by a nameplate."
        PRD §3.3: "When the first `PRIMARY` circuit on an `INSTALLED` cabinet reaches `ENERGIZED` — that is, when `energized_primary_circuit_count` moves from zero to one — the cabinet advances `INSTALLED` → `ACTIVE`, the row's `energized_cabinet_count` rises by one and the row's `allocated_power_kw`, `cooling_load_kw`, stranded views and posture are recomputed."

        Design: Difficulty/transitive_cascade/energize_cascade_depth_five_density_capped_blocks_neighbour_circuit
        """
        scenery = _setup_row_one_step_from_its_density_cap(api)
        scenario = scenery["scenario"]

        validate_success(_energize(api, scenery["primary"]["id"], scenario.row_id))

        circuit = fx.read_circuit(api, scenery["primary"]["id"])
        ax.assert_power_circuit(circuit)
        ax.assert_circuit_power(
            circuit,
            status="ENERGIZED",
            derated_kw=17.280,
            allocated_kw=17.280,
            cooling_contribution_kw=17.280,
        )
        assert_same_instant(circuit["energized_at"], k.DEFAULT_CLOCK, "circuit.energized_at")

        cabinet = fx.read_cabinet(api, scenery["cabinet"]["id"])
        ax.assert_cabinet_power(
            cabinet,
            status="ACTIVE",
            allocated_power_kw=17.280,
            cooling_load_kw=17.280,
            energized_primary_circuit_count=1,
        )

    def test_energize_flips_the_row_to_density_capped_and_recomputes_both_stranded_views(
        self, api
    ):
        """PRD §3.2: "`density_ceiling_kw` is the design density multiplied by the number of occupied slots, rounded to three decimals — a row engineered at 8 kW per cabinet with five occupied slots carries a ceiling of 40 kW, and that ceiling grows and shrinks with occupancy rather than with the row's physical slot count."
        PRD §3.2: "`effective_ceiling_kw` is the smallest of three numbers: the busway limit `max_row_power_kw`, the density ceiling just derived, and the cooling capacity."
        PRD §3.2: "The **nameplate view**, `stranded_nameplate_kw`, is the effective ceiling minus `allocated_power_kw`, rounded to three decimals: it charges the row for every breaker plate that has been energized, so a lightly loaded cabinet with a large breaker strands nothing at all."
        PRD §3.2: "Otherwise, if at least one slot is occupied and `allocated_power_kw` has reached or passed `density_ceiling_kw` the row is `DENSITY_CAPPED`."

        Design: Difficulty/transitive_cascade/energize_cascade_depth_five_density_capped_blocks_neighbour_circuit
        """
        scenery = _setup_row_one_step_from_its_density_cap(api)
        scenario = scenery["scenario"]

        validate_success(_energize(api, scenery["primary"]["id"], scenario.row_id))

        row = fx.read_row(api, scenario.row_id)
        ax.assert_floor_row(row)
        ax.assert_row_capacity_view(
            row,
            occupied_slot_count=2,
            density_ceiling_kw=16.000,
            effective_ceiling_kw=16.000,
            allocated_power_kw=17.280,
            cooling_load_kw=17.280,
            energized_cabinet_count=1,
            stranded_nameplate_kw=-1.280,
            stranded_measured_kw=16.000,
            row_status="DENSITY_CAPPED",
        )

    def test_density_cap_holds_the_neighbour_cabinet_and_blocks_its_designed_circuit(
        self, api
    ):
        """PRD §3.3: "When a row flips to `DENSITY_CAPPED`, every cabinet in that row that is `RESERVED` at that instant is placed on `CAPACITY_HELD`, and every circuit on those cabinets sitting in `DESIGNED` moves to `BLOCKED`; the held cabinet stays inside `occupied_slot_count`, so the density ceiling does not move underneath the row while the hold is in force."
        PRD §3.4: "While a circuit's `status` is `DESIGNED`, `APPROVED`, `BLOCKED`, `DE_ENERGIZED` or `REMOVED`, both `allocated_kw` and `cooling_contribution_kw` are 0.000."

        Design: Difficulty/transitive_cascade/energize_cascade_depth_five_density_capped_blocks_neighbour_circuit
        """
        scenery = _setup_row_one_step_from_its_density_cap(api)
        scenario = scenery["scenario"]

        validate_success(_energize(api, scenery["primary"]["id"], scenario.row_id))

        neighbour = fx.read_cabinet(api, scenery["neighbour"]["id"])
        assert neighbour["status"] == "CAPACITY_HELD", (
            f"the neighbouring RESERVED cabinet must be held once the row caps, "
            f"got {neighbour['status']}"
        )
        assert neighbour["contract_id"] == scenario.contract_id, (
            "a capacity hold keeps the cabinet bound to its contract"
        )

        blocked = fx.read_circuit(api, scenery["neighbour_circuit"]["id"])
        ax.assert_circuit_power(
            blocked, status="BLOCKED", allocated_kw=0.000, cooling_contribution_kw=0.000
        )

    def test_capped_row_refuses_new_cabinet_creation(self, api):
        """PRD §3.2: "Creating a cabinet in a `DENSITY_CAPPED` or `DECOMMISSIONING` row, or reserving or installing space in one, is refused with `ERR_ROW_NOT_ACCEPTING_SPACE`."

        Design: Difficulty/transitive_cascade/energize_cascade_depth_five_density_capped_blocks_neighbour_circuit
        """
        scenery = _setup_row_one_step_from_its_density_cap(api)
        scenario = scenery["scenario"]

        validate_success(_energize(api, scenery["primary"]["id"], scenario.row_id))
        assert fx.read_row(api, scenario.row_id)["row_status"] == "DENSITY_CAPPED"

        refused = api.create_cabinet(
            f.create_cabinet_payload(scenario.row_id, cabinet_code="C03"), FACILITY_MANAGER
        )
        validate_error(refused, ApiErrorId.ERR_ROW_NOT_ACCEPTING_SPACE)

    def test_energize_refreshes_the_contract_provisioning_rollup(self, api):
        """PRD §3.4: "`provisioned_power_kw` is the sum of `allocated_kw` over circuits that are both `ENERGIZED` and `PRIMARY` on cabinets whose `contract_id` is this contract, rounded to three decimals."
        PRD §3.4: "`stranded_commit_kw` is the contracted commitment minus that provisioned figure, floored at zero so an over-provisioned contract reports 0.000 rather than a negative number, rounded to three decimals."
        PRD §3.4: "`commit_utilization_pct` is the provisioned figure divided by `power_commit_kw`, multiplied by 100 and rounded to one decimal place."

        Design: Difficulty/transitive_cascade/energize_cascade_depth_five_density_capped_blocks_neighbour_circuit
        """
        scenery = _setup_row_one_step_from_its_density_cap(api)
        scenario = scenery["scenario"]

        validate_success(_energize(api, scenery["primary"]["id"], scenario.row_id))

        contract = fx.read_contract(api, scenario.contract_id)
        ax.assert_contract(contract)
        ax.assert_contract_power_rollup(
            contract,
            provisioned_power_kw=17.280,
            stranded_commit_kw=2.720,
            commit_utilization_pct=86.4,
        )


# ---------------------------------------------------------------------------
# The port-release cascade
# ---------------------------------------------------------------------------


class TestPortReleaseCascade:
    def test_decommission_approval_leaves_the_order_ready_for_release(self, api):
        """PRD §3.8: "On acceptance the cabinet moves from `INSTALLED` or `ACTIVE` to `DECOMMISSIONING`; every `ENERGIZED` circuit on it moves to `DE_ENERGIZED` with `allocated_kw` and `cooling_contribution_kw` zeroed; `released_power_kw` records the total allocated kilowatts thereby de-energized, rounded to three decimals, and is 0.000 when the cabinet was merely `INSTALLED` and carried no energized load; the row's `allocated_power_kw`, `cooling_load_kw`, both stranded views and `row_status` are recomputed, which may return a `DENSITY_CAPPED` row to `OPEN` and thereby lift capacity holds elsewhere in the row; the contract's `provisioned_power_kw`, `stranded_commit_kw` and `commit_utilization_pct` are refreshed; and the order's, the cabinet's and the row's `version` all increment."
        PRD §3.8: "Recording the first of them moves the order `APPROVED` → `IN_PROGRESS` and writes either `equipment_removed_at` and `equipment_removed_by_user_id` or `cables_reclaimed_at` and `cables_reclaimed_by_user_id`, taking the timestamp from the logical clock and the operator from `X-User-ID`."
        PRD §3.8: "Once both steps carry timestamps the order auto-advances to `READY_FOR_RELEASE` within that same request — the join is not a separate call — and the order's `version` increments."

        Design: Difficulty/transitive_cascade/release_ports_cascade_depth_four_quarantine_and_credit
        """
        scenery = _setup_decommission_ready_for_release(api)

        order = fx.read_decommission(api, scenery["decommission"]["id"])
        ax.assert_decommission_order(order)
        assert order["status"] == "READY_FOR_RELEASE", (
            f"both recorded steps must join the order at READY_FOR_RELEASE, got {order['status']}"
        )
        ax.assert_kw_equals(
            order["released_power_kw"], 9.600, "decommission order.released_power_kw"
        )
        assert order["equipment_removed_by_user_id"] == "eng-1"
        assert order["cables_reclaimed_by_user_id"] == "eng-2"

    def test_release_ports_closes_the_order_and_counts_the_ports_it_reclaimed(self, api):
        """PRD §3.8: "Port release is the final `ProvisioningEngineer` action and closes the order, `READY_FOR_RELEASE` → `CLOSED`."
        PRD §3.8: "First, `released_port_count` records how many ports the release moved out of `ASSIGNED`."

        Design: Difficulty/transitive_cascade/release_ports_cascade_depth_four_quarantine_and_credit
        """
        scenery = _setup_decommission_ready_for_release(api)

        released = validate_success(api.release_ports(scenery["decommission"]["id"], ENGINEER_1))
        assert released["status"] == "CLOSED", (
            f"port release closes the decommission order, got {released['status']}"
        )
        assert released["released_port_count"] == 2, (
            f"both assigned ports were reclaimed, got released_port_count "
            f"{released['released_port_count']}"
        )

    def test_release_ports_decommissions_the_cross_connect_and_quarantines_its_ports(
        self, api
    ):
        """PRD §3.8: "Second, every cross-connect order in `ACTIVE` whose `a_end_cabinet_id` is this order's cabinet moves to `DECOMMISSIONED`."
        PRD §3.8: "Third, the `ASSIGNED` ports of each such cross-connect become `QUARANTINED` with `quarantine_until` set to 24 hours after the logical clock and `assigned_order_id` cleared, which is the cool-down that §3.5's routing gates test against."

        Design: Difficulty/transitive_cascade/release_ports_cascade_depth_four_quarantine_and_credit
        """
        scenery = _setup_decommission_ready_for_release(api)

        validate_success(api.release_ports(scenery["decommission"]["id"], ENGINEER_1))

        order = fx.read_order(api, scenery["cross_connect"]["id"])
        assert order["status"] == "DECOMMISSIONED", (
            f"the reclaimed cross-connect must be DECOMMISSIONED, got {order['status']}"
        )

        for port in (scenery["a_port"], scenery["z_port"]):
            reclaimed = fx.read_port(api, port["id"])
            ax.assert_patch_panel_port(reclaimed)
            assert reclaimed["status"] == "QUARANTINED", (
                f"port {reclaimed['panel_code']}/{reclaimed['port_number']} must cool down "
                f"in QUARANTINED, got {reclaimed['status']}"
            )
            assert_same_instant(
                reclaimed["quarantine_until"], "2026-08-02T00:00:00Z", "port.quarantine_until"
            )
            assert reclaimed["assigned_order_id"] is None, (
                "a quarantined port no longer names a holding order"
            )

    def test_release_ports_issues_the_decommission_credit_and_refreshes_contract_money(
        self, api
    ):
        """PRD §3.8: "Fourth, for each decommissioned cross-connect the contract's `active_cross_connect_count` falls by one and an invoice line of `line_type` `CROSS_CONNECT_CREDIT` is appended for the negative of 50 percent of that order's `mrc_usd`, rounded to two decimals, after which the contract's `billed_total_usd` and `cross_connect_billed_usd` are refreshed."
        PRD §3.4: "The same rollup pass also refreshes `active_cross_connect_count`, the count of the contract's cross-connect orders in `ACTIVE`; `billed_total_usd`, the sum of `amount_usd` across every invoice line ever appended to the contract, credits and reversals included, rounded to two decimals; and `cross_connect_billed_usd`, the same sum restricted to lines whose `line_type` is `CROSS_CONNECT_MRC` or `CROSS_CONNECT_SURCHARGE`, likewise rounded to two decimals."
        PRD §3.9: "`source_ref_id` is a polymorphic back-reference resolved by `line_type` — the cross-connect order, the remote-hands ticket, or the reversed line — and it is deliberately never consulted in any ordering or selection decision."

        Design: Difficulty/transitive_cascade/release_ports_cascade_depth_four_quarantine_and_credit
        """
        scenery = _setup_decommission_ready_for_release(api)
        scenario = scenery["scenario"]

        validate_success(api.release_ports(scenery["decommission"]["id"], ENGINEER_1))

        lines = fx.invoice_lines(api, scenario.contract_id)
        assert len(lines) == 1, (
            f"the release appends exactly one ledger row, got {[l['line_type'] for l in lines]}"
        )
        credit = ax.one_line(lines, "CROSS_CONNECT_CREDIT")
        ax.assert_invoice_line(credit)
        ax.assert_invoice_line_values(
            credit,
            line_type="CROSS_CONNECT_CREDIT",
            amount_usd=-150.00,
            source_ref_id=scenery["cross_connect"]["id"],
        )

        contract = fx.read_contract(api, scenario.contract_id)
        ax.assert_contract_billing_rollup(
            contract,
            active_cross_connect_count=0,
            billed_total_usd=-150.00,
            cross_connect_billed_usd=0.00,
        )

    def test_release_ports_frees_the_cabinet_its_circuits_and_the_row_slot(self, api):
        """PRD §3.8: "Fifth, the cabinet itself moves `DECOMMISSIONING` → `RELEASED`, each of its `DE_ENERGIZED` circuits moves to `REMOVED`, its `contract_id` is cleared, and the row's `occupied_slot_count` falls by one with the density ceiling, effective ceiling, both stranded views and `row_status` recomputed."
        PRD §3.4: "While a circuit's `status` is `DESIGNED`, `APPROVED`, `BLOCKED`, `DE_ENERGIZED` or `REMOVED`, both `allocated_kw` and `cooling_contribution_kw` are 0.000."

        Design: Difficulty/transitive_cascade/release_ports_cascade_depth_four_quarantine_and_credit
        """
        scenery = _setup_decommission_ready_for_release(api)
        scenario = scenery["scenario"]

        validate_success(api.release_ports(scenery["decommission"]["id"], ENGINEER_1))

        cabinet = fx.read_cabinet(api, scenery["cabinet"]["id"])
        assert cabinet["status"] == "RELEASED", (
            f"the emptied cabinet is RELEASED, got {cabinet['status']}"
        )
        assert cabinet["contract_id"] is None, "a released cabinet carries no contract"

        circuit = fx.read_circuit(api, scenery["circuit"]["id"])
        ax.assert_circuit_power(
            circuit, status="REMOVED", allocated_kw=0.000, cooling_contribution_kw=0.000
        )

        row = fx.read_row(api, scenario.row_id)
        ax.assert_row_capacity_view(
            row,
            occupied_slot_count=0,
            density_ceiling_kw=0.000,
            allocated_power_kw=0.000,
            cooling_load_kw=0.000,
            row_status="OPEN",
        )

    def test_release_ports_zeroes_the_contract_provisioning_rollup(self, api):
        """PRD §3.4: "`provisioned_power_kw` is the sum of `allocated_kw` over circuits that are both `ENERGIZED` and `PRIMARY` on cabinets whose `contract_id` is this contract, rounded to three decimals."
        PRD §3.4: "`stranded_commit_kw` is the contracted commitment minus that provisioned figure, floored at zero so an over-provisioned contract reports 0.000 rather than a negative number, rounded to three decimals."
        PRD §3.4: "This rollup is recomputed on every circuit energization and de-energization, on every cabinet reservation, release, decommission and port release, on every cross-connect activation and decommission, and on every invoice line appended."

        Design: Difficulty/transitive_cascade/release_ports_cascade_depth_four_quarantine_and_credit
        """
        scenery = _setup_decommission_ready_for_release(api)
        scenario = scenery["scenario"]

        validate_success(api.release_ports(scenery["decommission"]["id"], ENGINEER_1))

        contract = fx.read_contract(api, scenario.contract_id)
        ax.assert_contract_power_rollup(
            contract,
            provisioned_power_kw=0.000,
            stranded_commit_kw=20.000,
            commit_utilization_pct=0.0,
        )
