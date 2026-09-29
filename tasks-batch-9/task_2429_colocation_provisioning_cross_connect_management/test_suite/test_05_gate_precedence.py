"""Which gate speaks when two gates are broken at once.

The PRD numbers its rejection rules and declares the ordering normative, so a request
that breaks several of them has exactly one correct answer. Two pairs are pinned here
as truth tables: contract lifecycle against credit hold on cross-connect intake, where
the PRD names the pair explicitly, and thermal safety against row density on
energization, where the PRD says outright that cooling outranks density. Each table
walks the neighbouring cells too, so a passing implementation cannot be one that simply
returns the same code for everything.
"""

from typing import Any, Dict

from test_helpers import (
    ApiErrorId,
    BILLING_OPERATOR,
    ENGINEER_1,
    FACILITY_MANAGER,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as ax, factories as f, fixtures as fx


# ---------------------------------------------------------------------------
# module-local helpers
# ---------------------------------------------------------------------------


def _suspend(api, contract_id: str) -> None:
    """Suspension is the `BillingOperator`'s act and cascades nothing."""
    validate_success(
        api.set_contract_state(contract_id, f.state_payload("SUSPENDED"), BILLING_OPERATOR)
    )


def _reinstate(api, contract_id: str) -> None:
    validate_success(
        api.set_contract_state(contract_id, f.state_payload("ACTIVE"), BILLING_OPERATOR)
    )


def _attempt_intake(api, scenario):
    """Raise a cross-connect order carrying a freshly read contract version, so the
    only thing under examination is the gate ordering."""
    payload = f.create_cross_connect_order_payload(
        scenario.contract_id,
        scenario.contacts[0]["id"],
        scenario.cabinets[0]["id"],
        scenario.cabinets[1]["id"],
        fx.contract_version(api, scenario.contract_id),
        cable_type="SMF",
    )
    return api.create_cross_connect_order(payload, ENGINEER_1)


def _order_count(api, contract_id: str) -> int:
    data, meta = validate_paginated(
        api.list_cross_connect_orders(FACILITY_MANAGER, params={"contract_id": contract_id})
    )
    assert meta["total_count"] == len(data), (
        f"listing meta disagrees with its page: total_count {meta['total_count']} vs {len(data)}"
    )
    return len(data)


CONTRACT_INTAKE = {
    "billing_mode": "COMMITTED_ONLY",
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


def _setup_intake_scenery(api):
    """An `ACTIVE` contract with one `INSTALLED` A-end cabinet, a `REMOTE_HANDS`-and-
    `SITE_ACCESS` contact, and a far-side meet-me cabinet in a second row that is
    deliberately not on the contract."""
    scenario = fx.setup_installed_cabinet(
        api,
        row={"hall_code": "HA", "row_code": "R1"},
        contract=CONTRACT_INTAKE,
        cabinet={"cabinet_code": "C01"},
    )
    far_row = fx.create_row(api, hall_code="HA", row_code="R2")
    scenario.rows.append(far_row)
    scenario.cabinets.append(
        fx.create_cabinet(
            api, far_row["id"], cabinet_code="Z01", rated_power_kw=10.0, footprint_type="MEET_ME"
        )
    )
    scenario.contacts.append(fx.create_contact(api, scenario.customer_id))
    return scenario


ROW_SQUEEZED = {
    "hall_code": "HB",
    "row_code": "R1",
    "cabinet_slot_count": 8,
    "design_density_kw_per_cabinet": 4.0,
    "max_row_power_kw": 200.0,
    "cooling_capacity_kw": 10.0,
    "escort_slot_count": 1,
    "decommission_flag": False,
}

CONTRACT_SQUEEZED = dict(CONTRACT_INTAKE)


def _setup_squeezed_row(api) -> Dict[str, Any]:
    """One `INSTALLED` cabinet rated 20.0 kW carrying an `APPROVED` 90 A / 240 V
    single-phase primary feed derated to 17.280 kW, in a row engineered at 4 kW per
    cabinet and cooled for only 10 kW. Energizing that feed breaks the cooling ceiling
    (17.280 against 10.0) and the density ceiling (17.280 against 4.000 × 1.10) at the
    same time.
    """
    scenario = fx.setup_installed_cabinet(
        api,
        row=ROW_SQUEEZED,
        contract=CONTRACT_SQUEEZED,
        cabinet={"cabinet_code": "C01", "rated_power_kw": 20.0},
    )
    circuit = fx.add_approved_circuit(
        api,
        scenario,
        circuit_code="A-1",
        feed_side="A",
        redundancy_role="PRIMARY",
        breaker_amps=90,
        volts=240,
        phase="SINGLE",
    )
    return {"scenario": scenario, "circuit": circuit}


def _attempt_energize(api, circuit_id: str, row_id: str):
    return api.energize_circuit(
        circuit_id, {"expected_row_version": fx.row_version(api, row_id)}, ENGINEER_1
    )


# ---------------------------------------------------------------------------
# Contract lifecycle against credit hold, on cross-connect intake
# ---------------------------------------------------------------------------


class TestIntakeGatePrecedence:
    def test_credit_hold_alone_refuses_intake_with_the_fiscal_error(self, api):
        """PRD §2.5: "The contract's `credit_hold` is false, otherwise `ERR_CREDIT_HOLD_ACTIVE` (402)."
        PRD §3.5: "Creation gates read in the order of §2.5: the contract must be `ACTIVE`, otherwise `ERR_CONTRACT_NOT_ACTIVE`; the A-end cabinet must be `INSTALLED` or `ACTIVE`, otherwise `ERR_CABINET_NOT_OPERATIONAL`, and only the A end is examined — the far side is deliberately exempt from both the operational test and contract scoping; the A-end cabinet's `contract_id` must equal the named contract, otherwise `ERR_CABINET_NOT_ON_CONTRACT`; the contract must not be on credit hold, otherwise `ERR_CREDIT_HOLD_ACTIVE`; and the count of the contract's orders that are neither `ABORTED` nor `DECOMMISSIONED`, this one included, must stay within `cross_connect_cap`, otherwise `ERR_CROSS_CONNECT_CAP_EXCEEDED` — aborted and decommissioned orders free a slot for re-use."

        Design: Difficulty/priority_pair_validation_conflict/contract_lifecycle_gate_outranks_credit_hold_gate_on_order_intake
        """
        scenario = _setup_intake_scenery(api)
        fx.set_credit_hold(api, scenario.contract_id, True)

        validate_error(_attempt_intake(api, scenario), ApiErrorId.ERR_CREDIT_HOLD_ACTIVE)
        assert _order_count(api, scenario.contract_id) == 0, (
            "a refused intake must leave no cross-connect order behind"
        )

    def test_suspended_contract_on_credit_hold_reports_the_lifecycle_error_not_the_fiscal_one(
        self, api
    ):
        """PRD §2.5: "The order below is normative: rules are evaluated in ascending order and the **first** violated rule determines both the returned `error_id` and the HTTP status."
        PRD §2.5: "A lower position always wins the conflict, which is why, for example, a contract that is simultaneously `SUSPENDED` and on credit hold reports `ERR_CONTRACT_NOT_ACTIVE` and never `ERR_CREDIT_HOLD_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/contract_lifecycle_gate_outranks_credit_hold_gate_on_order_intake
        """
        scenario = _setup_intake_scenery(api)
        fx.set_credit_hold(api, scenario.contract_id, True)
        _suspend(api, scenario.contract_id)

        held_and_suspended = fx.read_contract(api, scenario.contract_id)
        assert held_and_suspended["status"] == "SUSPENDED"
        assert held_and_suspended["credit_hold"] is True, (
            "both violations must be live for the precedence to mean anything"
        )

        validate_error(_attempt_intake(api, scenario), ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)
        assert _order_count(api, scenario.contract_id) == 0

    def test_suspension_alone_refuses_intake_with_the_lifecycle_error(self, api):
        """PRD §2.5: "The contract's `status` is `ACTIVE`, otherwise `ERR_CONTRACT_NOT_ACTIVE` (409)."
        PRD §3.1: "Suspending an `ACTIVE` contract deliberately cascades nothing: cabinets stay where they are, energized circuits keep drawing power, and that power keeps accruing charges, because suspension is a commercial posture and not a power-off switch."

        Design: Difficulty/priority_pair_validation_conflict/contract_lifecycle_gate_outranks_credit_hold_gate_on_order_intake
        """
        scenario = _setup_intake_scenery(api)
        _suspend(api, scenario.contract_id)

        clean = fx.read_contract(api, scenario.contract_id)
        assert clean["credit_hold"] is False, "this cell isolates the lifecycle violation"

        validate_error(_attempt_intake(api, scenario), ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)
        assert _order_count(api, scenario.contract_id) == 0

    def test_intake_is_admitted_once_both_gates_are_clear(self, api):
        """PRD §3.5: "A created order opens in `SUBMITTED` with `revision_count` at 0, no route pinned, and `mrc_usd` fixed from the media it will use: 300.00 USD for `SMF`, 250.00 USD for `MMF`, 175.00 USD for `CAT6A`, 225.00 USD for `COAX`."
        PRD §3.1: "Reinstating a `SUSPENDED` contract to `ACTIVE` is refused with `ERR_CREDIT_HOLD_ACTIVE` while `credit_hold` is true, and the `ACTIVE` ⇄ `SUSPENDED` cycle may repeat without bound."

        Design: Difficulty/priority_pair_validation_conflict/contract_lifecycle_gate_outranks_credit_hold_gate_on_order_intake
        """
        scenario = _setup_intake_scenery(api)
        fx.set_credit_hold(api, scenario.contract_id, True)
        _suspend(api, scenario.contract_id)
        fx.set_credit_hold(api, scenario.contract_id, False)
        _reinstate(api, scenario.contract_id)

        order = validate_success(_attempt_intake(api, scenario), 201)
        ax.assert_cross_connect_order(order)
        assert order["status"] == "SUBMITTED", (
            f"a created order opens in SUBMITTED, got {order['status']}"
        )
        assert order["revision_count"] == 0, (
            f"a created order opens with revision_count 0, got {order['revision_count']}"
        )
        assert order["a_end_port_id"] is None and order["z_end_port_id"] is None, (
            "a created order pins no route"
        )
        ax.assert_amount_equals(order["mrc_usd"], 300.00, "order.mrc_usd for SMF")

        assert _order_count(api, scenario.contract_id) == 1, (
            "exactly one order exists: the three refused attempts wrote nothing"
        )
        contract = fx.read_contract(api, scenario.contract_id)
        assert contract["status"] == "ACTIVE" and contract["credit_hold"] is False


# ---------------------------------------------------------------------------
# Thermal safety against row density, on energization
# ---------------------------------------------------------------------------


class TestEnergizeGatePrecedence:
    def test_breaching_cooling_and_density_together_reports_the_cooling_error(self, api):
        """PRD §2.5: "This thermal gate sits deliberately above the density gate, so a request that violates both reports the cooling error."
        PRD §3.4: "Thermal safety outranks density, so a request that breaches both cooling and density reports the cooling error."

        Design: Difficulty/priority_pair_validation_conflict/cooling_safety_gate_outranks_row_density_gate_on_energize
        """
        scenery = _setup_squeezed_row(api)
        scenario = scenery["scenario"]

        row_before = fx.read_row(api, scenario.row_id)
        ax.assert_row_capacity_view(
            row_before,
            occupied_slot_count=1,
            density_ceiling_kw=4.000,
            cooling_load_kw=0.000,
            allocated_power_kw=0.000,
        )
        approved = fx.read_circuit(api, scenery["circuit"]["id"])
        ax.assert_circuit_power(approved, status="APPROVED", derated_kw=17.280)

        refused = _attempt_energize(api, scenery["circuit"]["id"], scenario.row_id)
        validate_error(refused, ApiErrorId.ERR_COOLING_CAPACITY_EXCEEDED)

    def test_the_refused_energization_leaves_the_circuit_and_row_untouched(self, api):
        """PRD §2.5: "The projected row `cooling_load_kw` after the energization is less than or equal to the row's `cooling_capacity_kw`, otherwise `ERR_COOLING_CAPACITY_EXCEEDED` (422)."
        PRD §3.4: "While a circuit's `status` is `DESIGNED`, `APPROVED`, `BLOCKED`, `DE_ENERGIZED` or `REMOVED`, both `allocated_kw` and `cooling_contribution_kw` are 0.000."

        Design: Difficulty/priority_pair_validation_conflict/cooling_safety_gate_outranks_row_density_gate_on_energize
        """
        scenery = _setup_squeezed_row(api)
        scenario = scenery["scenario"]

        validate_error(
            _attempt_energize(api, scenery["circuit"]["id"], scenario.row_id),
            ApiErrorId.ERR_COOLING_CAPACITY_EXCEEDED,
        )

        circuit = fx.read_circuit(api, scenery["circuit"]["id"])
        ax.assert_circuit_power(
            circuit, status="APPROVED", allocated_kw=0.000, cooling_contribution_kw=0.000
        )
        row = fx.read_row(api, scenario.row_id)
        ax.assert_row_capacity_view(
            row, allocated_power_kw=0.000, cooling_load_kw=0.000, energized_cabinet_count=0
        )

    def test_with_cooling_relieved_the_same_request_reports_the_density_error(self, api):
        """PRD §2.5: "The projected row `allocated_power_kw` after the energization is less than or equal to the row's `density_ceiling_kw` multiplied by 1.10, otherwise `ERR_ROW_DENSITY_LIMIT_EXCEEDED` (422)."
        PRD §3.2: "Re-limiting recomputes the row's whole capacity picture, which means `row_status` can flip — in either direction — without a single cabinet or circuit having changed, and the row's `version` increments on every such adjustment."

        Design: Difficulty/priority_pair_validation_conflict/cooling_safety_gate_outranks_row_density_gate_on_energize
        """
        scenery = _setup_squeezed_row(api)
        scenario = scenery["scenario"]

        validate_error(
            _attempt_energize(api, scenery["circuit"]["id"], scenario.row_id),
            ApiErrorId.ERR_COOLING_CAPACITY_EXCEEDED,
        )

        fx.relimit_row(api, scenario.row_id, cooling_capacity_kw=20.0)

        validate_error(
            _attempt_energize(api, scenery["circuit"]["id"], scenario.row_id),
            ApiErrorId.ERR_ROW_DENSITY_LIMIT_EXCEEDED,
        )

        circuit = fx.read_circuit(api, scenery["circuit"]["id"])
        ax.assert_circuit_power(
            circuit, status="APPROVED", allocated_kw=0.000, cooling_contribution_kw=0.000
        )

    def test_energization_is_admitted_once_both_ceilings_are_raised(self, api):
        """PRD §3.4: "They are evaluated in a fixed order so that a request violating several of them always reports the same code: first the row's projected `cooling_load_kw` against `cooling_capacity_kw`, reported as `ERR_COOLING_CAPACITY_EXCEEDED`; then the cabinet breaker projection against `rated_power_kw` multiplied by 1.25, reported as `ERR_CABINET_BREAKER_OVERSUBSCRIBED`; then the redundant-feed requirement above; then the row's projected `allocated_power_kw` against `density_ceiling_kw` multiplied by the 1.10 density tolerance, reported as `ERR_ROW_DENSITY_LIMIT_EXCEEDED`; then the same projection against the absolute busway limit `max_row_power_kw`, reported as `ERR_ROW_POWER_LIMIT_EXCEEDED`."
        PRD §3.2: "The same manager may later re-limit a live row, adjusting any of `cooling_capacity_kw`, `max_row_power_kw`, `design_density_kw_per_cabinet`, `escort_slot_count` or `decommission_flag`."

        Design: Difficulty/priority_pair_validation_conflict/cooling_safety_gate_outranks_row_density_gate_on_energize
        """
        scenery = _setup_squeezed_row(api)
        scenario = scenery["scenario"]

        fx.relimit_row(api, scenario.row_id, cooling_capacity_kw=20.0)
        fx.relimit_row(api, scenario.row_id, design_density_kw_per_cabinet=20.0)

        validate_success(_attempt_energize(api, scenery["circuit"]["id"], scenario.row_id))

        circuit = fx.read_circuit(api, scenery["circuit"]["id"])
        ax.assert_circuit_power(
            circuit,
            status="ENERGIZED",
            derated_kw=17.280,
            allocated_kw=17.280,
            cooling_contribution_kw=17.280,
        )
        row = fx.read_row(api, scenario.row_id)
        ax.assert_row_capacity_view(
            row,
            density_ceiling_kw=20.000,
            allocated_power_kw=17.280,
            cooling_load_kw=17.280,
            energized_cabinet_count=1,
            row_status="OPEN",
        )
        contract = fx.read_contract(api, scenario.contract_id)
        ax.assert_contract_power_rollup(
            contract, provisioned_power_kw=17.280, commit_utilization_pct=86.4
        )
