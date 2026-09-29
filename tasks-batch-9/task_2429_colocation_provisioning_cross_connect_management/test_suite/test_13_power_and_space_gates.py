"""Power and space gates: the breaker headroom ceiling at approval, the 2N standby
feed requirement, the busway ceiling, the contract over-provisioning cap and the
committed cabinet count.
"""

from test_helpers import assertions as ax, factories as f, fixtures as fx
from test_helpers import ApiErrorId, validate_error, validate_success


def _energize_body(api, row_id):
    """The energization body: nothing but the client's last observed row version."""
    return {"expected_row_version": fx.row_version(api, row_id)}


# ---------------------------------------------------------------------------
# Breaker headroom at approval
# ---------------------------------------------------------------------------


def test_circuit_approval_over_the_breaker_headroom_ceiling_is_refused(
    api, facility_manager_headers
):
    """PRD §3.4: "That breaker test sums `derated_kw` across the cabinet's `PRIMARY` circuits already in `APPROVED` or `ENERGIZED` and adds this circuit's own derated capacity — counted as zero when the circuit being approved is `REDUNDANT` — and the total must not exceed the cabinet's `rated_power_kw` multiplied by the 1.25 headroom ratio the site allows above nameplate."
    PRD §3.4: "A projection strictly greater than that ceiling is refused with `ERR_CABINET_BREAKER_OVERSUBSCRIBED`; equality passes."
    PRD §3.4: "`derated_kw` is the breaker amperage multiplied by the voltage, multiplied by the phase factor — 1.0 for a `SINGLE`-phase supply and 1.732 for a `THREE`-phase supply — divided by 1000 to convert volt-amperes to kilowatts, then multiplied by the 0.80 continuous-load derate that electrical code requires, and finally rounded half-up to three decimal places."
    PRD §3.4: "While a circuit's `status` is `DESIGNED`, `APPROVED`, `BLOCKED`, `DE_ENERGIZED` or `REMOVED`, both `allocated_kw` and `cooling_contribution_kw` are 0.000."

    Design: Corner/validations/circuit_approval_over_the_breaker_headroom_ceiling_is_refused
    """
    # A 5.0 kW enclosure allows 6.25 kW of breaker plate; a 50 A / 240 V single-phase
    # circuit derates to 9.600 kW, which overshoots the headroom on its own.
    scenario = fx.setup_reserved_cabinet(api, cabinet={"rated_power_kw": 5.0})
    circuit = fx.add_designed_circuit(api, scenario)
    ax.assert_power_circuit(circuit)
    ax.assert_circuit_power(circuit, status="DESIGNED", derated_kw=9.600)

    validate_error(
        api.set_circuit_state(
            circuit["id"], f.state_payload("APPROVED"), facility_manager_headers
        ),
        ApiErrorId.ERR_CABINET_BREAKER_OVERSUBSCRIBED,
    )

    stored = fx.read_circuit(api, circuit["id"])
    ax.assert_circuit_power(
        stored,
        status="DESIGNED",
        derated_kw=9.600,
        allocated_kw=0.000,
        cooling_contribution_kw=0.000,
    )
    cabinet = fx.read_cabinet(api, scenario.cabinet_id)
    ax.assert_cabinet_power(cabinet, status="RESERVED", allocated_power_kw=0.000)


# ---------------------------------------------------------------------------
# The 2N standby feed
# ---------------------------------------------------------------------------


def test_two_n_contract_refuses_a_lone_primary_feed(api, provisioning_engineer_headers):
    """PRD §3.4: "If the owning contract's `redundancy_requirement` is `TWO_N` and the circuit being energized is `PRIMARY`, the cabinet must already hold a `REDUNDANT` circuit in `APPROVED` or `ENERGIZED` whose `feed_side` differs from this circuit's, otherwise `ERR_REDUNDANT_FEED_MISSING`; contracts at `N` or `N_PLUS_1` may energize a lone primary feed."
    PRD §3.4: "While a circuit's `status` is `DESIGNED`, `APPROVED`, `BLOCKED`, `DE_ENERGIZED` or `REMOVED`, both `allocated_kw` and `cooling_contribution_kw` are 0.000."

    Design: Corner/validations/two_n_contract_refuses_a_lone_primary_feed_then_admits_it_once_the_standby_exists
    """
    scenario = fx.setup_approved_circuit(api, contract={"redundancy_requirement": "TWO_N"})
    row_version_before = fx.row_version(api, scenario.row_id)

    validate_error(
        api.energize_circuit(
            scenario.circuit_id,
            {"expected_row_version": row_version_before},
            provisioning_engineer_headers,
        ),
        ApiErrorId.ERR_REDUNDANT_FEED_MISSING,
    )

    circuit = fx.read_circuit(api, scenario.circuit_id)
    ax.assert_circuit_power(
        circuit, status="APPROVED", allocated_kw=0.000, cooling_contribution_kw=0.000
    )
    row = fx.read_row(api, scenario.row_id)
    ax.assert_row_capacity_view(row, allocated_power_kw=0.000, cooling_load_kw=0.000)
    ax.assert_version_is(row, row_version_before, "row")


def test_two_n_contract_admits_the_primary_feed_once_the_standby_exists(
    api, provisioning_engineer_headers
):
    """PRD §3.4: "If the owning contract's `redundancy_requirement` is `TWO_N` and the circuit being energized is `PRIMARY`, the cabinet must already hold a `REDUNDANT` circuit in `APPROVED` or `ENERGIZED` whose `feed_side` differs from this circuit's, otherwise `ERR_REDUNDANT_FEED_MISSING`; contracts at `N` or `N_PLUS_1` may energize a lone primary feed."
    PRD §3.4: "For a `PRIMARY` circuit, `allocated_kw` is the lesser of its derated capacity and the host cabinet's `rated_power_kw` — the cabinet nameplate clamps what the floor will bill for, and the clamp is applied to the already-rounded derated figure — while `cooling_contribution_kw` is the full derated capacity, because heat is not clamped by a nameplate."
    PRD §3.2: "`allocated_power_kw` is the sum of `allocated_kw` over the energized circuits of the row's cabinets, rounded to three decimals, and `cooling_load_kw` is the sum of `cooling_contribution_kw` over the same set, likewise rounded to three decimals."

    Design: Corner/validations/two_n_contract_refuses_a_lone_primary_feed_then_admits_it_once_the_standby_exists
    """
    scenario = fx.setup_approved_circuit(api, contract={"redundancy_requirement": "TWO_N"})

    standby = fx.add_approved_circuit(
        api,
        scenario,
        circuit_code="B-1",
        feed_side="B",
        redundancy_role="REDUNDANT",
    )
    ax.assert_circuit_power(standby, derated_kw=9.600, allocated_kw=0.000)

    energized = validate_success(
        api.energize_circuit(
            scenario.circuit_id,
            _energize_body(api, scenario.row_id),
            provisioning_engineer_headers,
        )
    )
    ax.assert_circuit_power(
        energized, status="ENERGIZED", allocated_kw=9.600, cooling_contribution_kw=9.600
    )

    row = fx.read_row(api, scenario.row_id)
    ax.assert_row_capacity_view(row, allocated_power_kw=9.600, cooling_load_kw=9.600)


# ---------------------------------------------------------------------------
# The busway ceiling
# ---------------------------------------------------------------------------


def test_energization_over_the_row_power_ceiling_is_refused(api, provisioning_engineer_headers):
    """PRD §3.4: "They are evaluated in a fixed order so that a request violating several of them always reports the same code: first the row's projected `cooling_load_kw` against `cooling_capacity_kw`, reported as `ERR_COOLING_CAPACITY_EXCEEDED`; then the cabinet breaker projection against `rated_power_kw` multiplied by 1.25, reported as `ERR_CABINET_BREAKER_OVERSUBSCRIBED`; then the redundant-feed requirement above; then the row's projected `allocated_power_kw` against `density_ceiling_kw` multiplied by the 1.10 density tolerance, reported as `ERR_ROW_DENSITY_LIMIT_EXCEEDED`; then the same projection against the absolute busway limit `max_row_power_kw`, reported as `ERR_ROW_POWER_LIMIT_EXCEEDED`."
    PRD §3.4: "Four numeric projections follow, each computed as though this circuit were already energized, and each permitting equality — only a strictly greater projection is refused."

    Design: Corner/validations/energization_over_the_row_power_ceiling_is_refused
    """
    # A 5.0 kW busway under a row engineered at 25.0 kW per cabinet: the density
    # tolerance is generous, so only the absolute busway limit can bind.
    scenario = fx.setup_approved_circuit(api, row={"max_row_power_kw": 5.0})
    row_version_before = fx.row_version(api, scenario.row_id)

    validate_error(
        api.energize_circuit(
            scenario.circuit_id,
            {"expected_row_version": row_version_before},
            provisioning_engineer_headers,
        ),
        ApiErrorId.ERR_ROW_POWER_LIMIT_EXCEEDED,
    )

    circuit = fx.read_circuit(api, scenario.circuit_id)
    ax.assert_circuit_power(circuit, status="APPROVED", allocated_kw=0.000)
    row = fx.read_row(api, scenario.row_id)
    ax.assert_row_capacity_view(row, allocated_power_kw=0.000, cooling_load_kw=0.000)
    ax.assert_version_is(row, row_version_before, "row")


# ---------------------------------------------------------------------------
# The contract over-provisioning cap
# ---------------------------------------------------------------------------


def test_energization_above_the_contract_overprovision_cap_is_refused(
    api, provisioning_engineer_headers
):
    """PRD §3.4: "Finally the contract's projected `provisioned_power_kw` must stay within `power_commit_kw` multiplied by 1.10 — a customer may provision up to 110 percent of contracted power before the floor refuses — otherwise `ERR_POWER_COMMIT_EXCEEDED`."
    PRD §3.1: "`provisioned_power_kw` is the sum of `allocated_kw` over circuits that are both `ENERGIZED` and `PRIMARY` on cabinets whose `contract_id` is this contract, rounded to three decimals."

    Design: Corner/validations/energization_above_the_contract_overprovision_cap_is_refused
    """
    # 5.0 kW of commitment tolerates 5.500 kW of provisioning; the circuit asks 9.600.
    scenario = fx.setup_approved_circuit(api, contract={"power_commit_kw": 5.0})

    validate_error(
        api.energize_circuit(
            scenario.circuit_id,
            _energize_body(api, scenario.row_id),
            provisioning_engineer_headers,
        ),
        ApiErrorId.ERR_POWER_COMMIT_EXCEEDED,
    )

    contract = fx.read_contract(api, scenario.contract_id)
    ax.assert_contract_power_rollup(contract, provisioned_power_kw=0.000)
    cabinet = fx.read_cabinet(api, scenario.cabinet_id)
    ax.assert_cabinet_power(
        cabinet,
        status="INSTALLED",
        allocated_power_kw=0.000,
        energized_primary_circuit_count=0,
    )


# ---------------------------------------------------------------------------
# The committed cabinet count
# ---------------------------------------------------------------------------


def test_reserving_one_cabinet_beyond_the_committed_count_is_refused(
    api, provisioning_engineer_headers
):
    """PRD §3.3: "Four conditions must hold: the cabinet is `AVAILABLE`; the named contract is in `PENDING_ACTIVATION` or `ACTIVE`, otherwise `ERR_CONTRACT_NOT_ACTIVE`; the row is in `OPEN` or `COOLING_CONSTRAINED` posture, otherwise `ERR_ROW_NOT_ACCEPTING_SPACE`; and the count of the contract's cabinets already in `RESERVED`, `CAPACITY_HELD`, `INSTALLED` or `ACTIVE`, together with this one, stays within `committed_cabinet_count`, otherwise `ERR_CABINET_COMMIT_EXCEEDED`."
    PRD §3.3: "New cabinets open with `status` `AVAILABLE` and no `contract_id`; because an `AVAILABLE` cabinet occupies no slot, creating one does not move the row's density ceiling, though the row's capacity picture is recomputed anyway."
    PRD §3.2: "`occupied_slot_count` counts the cabinets in the row whose `status` is `RESERVED`, `CAPACITY_HELD`, `INSTALLED`, `ACTIVE` or `DECOMMISSIONING`; an `AVAILABLE` or `RELEASED` cabinet occupies nothing."

    Design: Corner/validations/reserving_one_cabinet_beyond_the_committed_count_is_refused
    """
    scenario = fx.setup_reserved_cabinet(
        api, contract={"committed_cabinet_count": 1}, cabinet={"cabinet_code": "C01"}
    )
    second = fx.create_cabinet(api, scenario.row_id, cabinet_code="C02")
    assert second["status"] == "AVAILABLE", "a new cabinet opens AVAILABLE"

    validate_error(
        api.set_cabinet_state(
            second["id"],
            f.state_payload("RESERVED", contract_id=scenario.contract_id),
            provisioning_engineer_headers,
        ),
        ApiErrorId.ERR_CABINET_COMMIT_EXCEEDED,
    )

    stored = fx.read_cabinet(api, second["id"])
    ax.assert_cabinet(stored)
    assert stored["status"] == "AVAILABLE", (
        f"the refused reservation must leave the cabinet AVAILABLE, got {stored['status']}"
    )
    assert stored["contract_id"] is None, (
        "a refused reservation must not bind the cabinet to the contract"
    )

    row = fx.read_row(api, scenario.row_id)
    ax.assert_row_capacity_view(row, occupied_slot_count=1, density_ceiling_kw=25.000)
