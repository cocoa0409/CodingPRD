"""A child entity's writeable transitions are gated by the live state of a parent aggregate.

Two dependencies are exercised here. A cross-connect order's approval and activation
each re-read the parent contract's `status` at the moment of the call, so the very same
order is refused while the contract is `SUSPENDED` and accepted once it is reinstated.
And a floor row's `decommission_flag` — a field a manager writes without touching any
cabinet or circuit — closes both the space door and the power door for every child of
that row, and re-opens them when it is cleared.
"""

from datetime import datetime

from test_helpers import assertions as ax, constants as k, factories as f, fixtures as fx
from test_helpers import ApiErrorId, validate_success, validate_error, validate_paginated
from test_helpers import BILLING_OPERATOR, ENGINEER_1, FACILITY_MANAGER, FACILITY_MANAGER_1_ID


def _same_instant(actual, expected_utc: str, label: str) -> None:
    """Compare two UTC instants without pinning a particular fractional-digit rendering."""
    assert actual is not None, f"{label} must be stamped"
    parsed = datetime.fromisoformat(str(actual).replace("Z", "+00:00"))
    expected = datetime.fromisoformat(expected_utc.replace("Z", "+00:00"))
    assert parsed == expected, f"{label}: expected {expected_utc}, got {actual}"


def _suspend(api, contract_id: str) -> dict:
    """Suspension is the `BillingOperator`'s commercial posture switch."""
    return validate_success(
        api.set_contract_state(contract_id, f.state_payload("SUSPENDED"), BILLING_OPERATOR)
    )


def _reinstate(api, contract_id: str) -> dict:
    return validate_success(
        api.set_contract_state(contract_id, f.state_payload("ACTIVE"), BILLING_OPERATOR)
    )


class TestCrossConnectTracksContractState:
    """A routed order whose approval and activation both consult the live contract."""

    def test_approval_refused_while_the_contract_is_suspended(self, api):
        """PRD §3.5: "Approval belongs to a `FacilityManager`. The order must be in `ROUTE_PROPOSED`, its contract must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`) and not on credit hold (`ERR_CREDIT_HOLD_ACTIVE`), and both pinned ports must still be `RESERVED` with `assigned_order_id` naming this order, otherwise `ERR_PORT_UNAVAILABLE`."
        PRD §3.1: "Suspending an `ACTIVE` contract deliberately cascades nothing: cabinets stay where they are, energized circuits keep drawing power, and that power keeps accruing charges, because suspension is a commercial posture and not a power-off switch."

        Design: Difficulty/cross_entity_state_dependency/cross_connect_approval_and_activation_track_contract_state_both_ways
        """
        scenario = fx.setup_routed_order(api, contract={"committed_cabinet_count": 2, "cross_connect_cap": 4})
        order_id = scenario.order["id"]

        _suspend(api, scenario.contract_id)

        refused = api.set_cross_connect_order_state(
            order_id, f.state_payload("APPROVED"), FACILITY_MANAGER
        )
        validate_error(refused, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

        still_proposed = fx.read_order(api, order_id)
        assert still_proposed["status"] == "ROUTE_PROPOSED", (
            f"a refused approval must leave the order in ROUTE_PROPOSED, got {still_proposed['status']}"
        )
        assert still_proposed["approved_by_user_id"] is None, (
            "a refused approval must not pin approved_by_user_id, got "
            f"{still_proposed['approved_by_user_id']!r}"
        )

    def test_the_same_approval_succeeds_after_reinstatement(self, api):
        """PRD §3.5: "Approval belongs to a `FacilityManager`. The order must be in `ROUTE_PROPOSED`, its contract must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`) and not on credit hold (`ERR_CREDIT_HOLD_ACTIVE`), and both pinned ports must still be `RESERVED` with `assigned_order_id` naming this order, otherwise `ERR_PORT_UNAVAILABLE`."
        PRD §3.5: "On success `approved_by_user_id` is pinned from the header and the order's `version` increments."

        Design: Difficulty/cross_entity_state_dependency/cross_connect_approval_and_activation_track_contract_state_both_ways
        """
        scenario = fx.setup_routed_order(api, contract={"committed_cabinet_count": 2, "cross_connect_cap": 4})
        order_id = scenario.order["id"]

        _suspend(api, scenario.contract_id)
        validate_error(
            api.set_cross_connect_order_state(order_id, f.state_payload("APPROVED"), FACILITY_MANAGER),
            ApiErrorId.ERR_CONTRACT_NOT_ACTIVE,
        )
        _reinstate(api, scenario.contract_id)

        approved = validate_success(
            api.set_cross_connect_order_state(order_id, f.state_payload("APPROVED"), FACILITY_MANAGER)
        )
        assert approved["status"] == "APPROVED", (
            f"the same approval must be accepted once the contract is ACTIVE again, got {approved['status']}"
        )
        assert approved["approved_by_user_id"] == FACILITY_MANAGER_1_ID, (
            f"approved_by_user_id must be pinned from the header, got {approved['approved_by_user_id']!r}"
        )

    def test_activation_refused_while_suspended_then_raises_the_active_count(self, api):
        """PRD §3.5: "Bringing the circuit into service, `INSTALLED` → `ACTIVE`, is a `FacilityManager` action that requires the contract to be `ACTIVE`, stamps `activated_at` from the logical clock, raises the contract's `active_cross_connect_count` by one, and increments both the order's and the contract's `version`."
        PRD §3.5: "A `ProvisioningEngineer` then records physical installation, moving `APPROVED` → `INSTALLED` and taking both ports `RESERVED` → `ASSIGNED`."

        Design: Difficulty/cross_entity_state_dependency/cross_connect_approval_and_activation_track_contract_state_both_ways
        """
        scenario = fx.setup_routed_order(api, contract={"committed_cabinet_count": 2, "cross_connect_cap": 4})
        order_id = scenario.order["id"]
        a_port_id = fx.a_ports(scenario)[0]["id"]
        z_port_id = fx.z_ports(scenario)[0]["id"]

        validate_success(
            api.set_cross_connect_order_state(order_id, f.state_payload("APPROVED"), FACILITY_MANAGER)
        )
        installed = validate_success(
            api.set_cross_connect_order_state(order_id, f.state_payload("INSTALLED"), ENGINEER_1)
        )
        assert installed["status"] == "INSTALLED", (
            f"physical installation must move the order to INSTALLED, got {installed['status']}"
        )
        for port_id in (a_port_id, z_port_id):
            port = fx.read_port(api, port_id)
            assert port["status"] == "ASSIGNED", (
                f"installation must take the pinned port to ASSIGNED, got {port['status']}"
            )

        _suspend(api, scenario.contract_id)
        validate_error(
            api.set_cross_connect_order_state(order_id, f.state_payload("ACTIVE"), FACILITY_MANAGER),
            ApiErrorId.ERR_CONTRACT_NOT_ACTIVE,
        )
        held = fx.read_order(api, order_id)
        assert held["status"] == "INSTALLED", (
            f"a refused activation must leave the order INSTALLED, got {held['status']}"
        )
        assert held["activated_at"] is None, (
            f"a refused activation must not stamp activated_at, got {held['activated_at']!r}"
        )
        ax.assert_contract_billing_rollup(
            fx.read_contract(api, scenario.contract_id), active_cross_connect_count=0
        )

        _reinstate(api, scenario.contract_id)
        activated = validate_success(
            api.set_cross_connect_order_state(order_id, f.state_payload("ACTIVE"), FACILITY_MANAGER)
        )
        assert activated["status"] == "ACTIVE", (
            f"activation must be accepted once the contract is ACTIVE again, got {activated['status']}"
        )
        _same_instant(activated["activated_at"], k.DEFAULT_CLOCK, "order.activated_at")

        contract = fx.read_contract(api, scenario.contract_id)
        assert contract["status"] == "ACTIVE", (
            f"the reinstated contract must report ACTIVE, got {contract['status']}"
        )
        ax.assert_contract_billing_rollup(contract, active_cross_connect_count=1)


class TestRowDecommissionFlagGatesSpaceAndPower:
    """One `PATCH` on the parent row closes and re-opens three unrelated child doors."""

    def _scenery(self, api):
        """An installed cabinet with an approved 50 A / 240 V single-phase primary feed,
        plus a second, still `AVAILABLE` cabinet in the same row."""
        scenario = fx.setup_approved_circuit(
            api, contract={"committed_cabinet_count": 2}, cabinet={"cabinet_code": "C01"}
        )
        spare = fx.create_cabinet(api, scenario.row_id, cabinet_code="C02")
        return scenario, spare

    def test_flagging_the_row_refuses_cabinet_creation_and_reservation(self, api):
        """PRD §3.2: "If `decommission_flag` is true the row is `DECOMMISSIONING`."
        PRD §3.2: "Creating a cabinet in a `DENSITY_CAPPED` or `DECOMMISSIONING` row, or reserving or installing space in one, is refused with `ERR_ROW_NOT_ACCEPTING_SPACE`."

        Design: Difficulty/cross_entity_state_dependency/cabinet_space_and_power_both_follow_the_row_decommission_flag
        """
        scenario, spare = self._scenery(api)
        row_id = scenario.row_id

        flagged = validate_success(api.update_row(row_id, {"decommission_flag": True}, FACILITY_MANAGER))
        assert flagged["decommission_flag"] is True, (
            f"the PATCH must write decommission_flag, got {flagged['decommission_flag']!r}"
        )
        assert flagged["row_status"] == "DECOMMISSIONING", (
            f"a flagged row reports DECOMMISSIONING, got {flagged['row_status']}"
        )
        ax.assert_kw_equals(flagged["allocated_power_kw"], 0.000, "row.allocated_power_kw")

        validate_error(
            api.create_cabinet(f.create_cabinet_payload(row_id, cabinet_code="C03"), FACILITY_MANAGER),
            ApiErrorId.ERR_ROW_NOT_ACCEPTING_SPACE,
        )
        validate_error(
            api.set_cabinet_state(
                spare["id"],
                f.state_payload("RESERVED", contract_id=scenario.contract_id),
                FACILITY_MANAGER,
            ),
            ApiErrorId.ERR_ROW_NOT_ACCEPTING_SPACE,
        )

        untouched = fx.read_cabinet(api, spare["id"])
        assert untouched["status"] == "AVAILABLE", (
            f"a refused reservation must leave the cabinet AVAILABLE, got {untouched['status']}"
        )
        assert untouched["contract_id"] is None, (
            f"a refused reservation must not write contract_id, got {untouched['contract_id']!r}"
        )

        cabinets, meta = validate_paginated(api.list_cabinets(FACILITY_MANAGER, params={"row_id": row_id}))
        assert meta["total_count"] == 2, (
            f"the refused creation must persist nothing: expected 2 cabinets in the row, got {meta['total_count']}"
        )
        assert len(cabinets) == 2, f"expected 2 cabinet rows on the page, got {len(cabinets)}"

    def test_flagging_the_row_refuses_energization_of_an_approved_circuit(self, api):
        """PRD §3.4: "The row must not be flagged for decommissioning, otherwise `ERR_ROW_NOT_ACCEPTING_SPACE`."
        PRD §3.4: "While a circuit's `status` is `DESIGNED`, `APPROVED`, `BLOCKED`, `DE_ENERGIZED` or `REMOVED`, both `allocated_kw` and `cooling_contribution_kw` are 0.000."

        Design: Difficulty/cross_entity_state_dependency/cabinet_space_and_power_both_follow_the_row_decommission_flag
        """
        scenario, _spare = self._scenery(api)
        row_id = scenario.row_id
        circuit_id = scenario.circuit_id

        validate_success(api.update_row(row_id, {"decommission_flag": True}, FACILITY_MANAGER))

        refused = api.energize_circuit(
            circuit_id, {"expected_row_version": fx.row_version(api, row_id)}, ENGINEER_1
        )
        validate_error(refused, ApiErrorId.ERR_ROW_NOT_ACCEPTING_SPACE)

        circuit = fx.read_circuit(api, circuit_id)
        ax.assert_circuit_power(
            circuit, status="APPROVED", allocated_kw=0.000, cooling_contribution_kw=0.000
        )

    def test_clearing_the_flag_reopens_both_reservation_and_energization(self, api):
        """PRD §3.2: "Re-limiting recomputes the row's whole capacity picture, which means `row_status` can flip — in either direction — without a single cabinet or circuit having changed, and the row's `version` increments on every such adjustment."
        PRD §3.2: "`density_ceiling_kw` is the design density multiplied by the number of occupied slots, rounded to three decimals — a row engineered at 8 kW per cabinet with five occupied slots carries a ceiling of 40 kW, and that ceiling grows and shrinks with occupancy rather than with the row's physical slot count."
        PRD §3.4: "For a `PRIMARY` circuit, `allocated_kw` is the lesser of its derated capacity and the host cabinet's `rated_power_kw` — the cabinet nameplate clamps what the floor will bill for, and the clamp is applied to the already-rounded derated figure — while `cooling_contribution_kw` is the full derated capacity, because heat is not clamped by a nameplate."

        Design: Difficulty/cross_entity_state_dependency/cabinet_space_and_power_both_follow_the_row_decommission_flag
        """
        scenario, spare = self._scenery(api)
        row_id = scenario.row_id
        circuit_id = scenario.circuit_id

        validate_success(api.update_row(row_id, {"decommission_flag": True}, FACILITY_MANAGER))
        cleared = validate_success(api.update_row(row_id, {"decommission_flag": False}, FACILITY_MANAGER))
        assert cleared["decommission_flag"] is False, (
            f"clearing the flag must write it back to false, got {cleared['decommission_flag']!r}"
        )
        assert cleared["row_status"] == "OPEN", (
            f"clearing the flag must return the row to OPEN, got {cleared['row_status']}"
        )

        reserved = validate_success(
            api.set_cabinet_state(
                spare["id"],
                f.state_payload("RESERVED", contract_id=scenario.contract_id),
                FACILITY_MANAGER,
            )
        )
        assert reserved["status"] == "RESERVED", (
            f"reservation must be accepted once the flag is cleared, got {reserved['status']}"
        )
        ax.assert_row_capacity_view(
            fx.read_row(api, row_id), occupied_slot_count=2, density_ceiling_kw=50.000
        )

        energized = validate_success(
            api.energize_circuit(
                circuit_id, {"expected_row_version": fx.row_version(api, row_id)}, ENGINEER_1
            )
        )
        ax.assert_circuit_power(energized, status="ENERGIZED", allocated_kw=9.600)
        ax.assert_cabinet_power(fx.read_cabinet(api, scenario.cabinet_id), status="ACTIVE")
        ax.assert_row_capacity_view(
            fx.read_row(api, row_id), allocated_power_kw=9.600, row_status="OPEN"
        )
