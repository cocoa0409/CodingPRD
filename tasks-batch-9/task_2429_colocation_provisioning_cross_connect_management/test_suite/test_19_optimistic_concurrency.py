"""Optimistic concurrency on the two arbitrated pools, and the cooling boundary.

Both guarded writes are exercised as a refuse-then-retry pair, because the token's
whole purpose is that a client which re-reads the parent may proceed: a test that only
showed the refusal could be passed by an endpoint that never accepts anything.
"""

from test_helpers import assertions as ax, factories as f, fixtures as fx
from test_helpers import (
    ApiErrorId,
    ENGINEER_1,
    FACILITY_MANAGER,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_superseded_contract_token_refuses_the_order_and_a_fresh_one_carries_it(
    api, provisioning_engineer_headers
):
    """PRD §2.6: "Raising a cross-connect order — `POST /colocation/cross-connect-orders` — requires `expected_contract_version` as a mandatory body field carrying the client's last observed `version` of the parent `Contract`."
    PRD §2.6: "If that value does not equal the contract's current `version`, the create is rejected with `ERR_STALE_CONTRACT_VERSION` and HTTP 412."
    PRD §2.6: "A successful create is itself a mutation of the contract and increments the contract's `version` by one, which is what makes a second create carrying the same token fail."
    PRD §3.5: "A created order opens in `SUBMITTED` with `revision_count` at 0, no route pinned, and `mrc_usd` fixed from the media it will use: 300.00 USD for `SMF`, 250.00 USD for `MMF`, 175.00 USD for `CAT6A`, 225.00 USD for `COAX`."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_contract_version_refuses_the_order_then_the_fresh_one_is_accepted
    """
    fx.set_clock(api)
    customer = fx.create_customer(api)
    contact = fx.create_contact(api, customer["id"])
    row = fx.create_row(api)
    contract = fx.create_contract(
        api,
        customer["id"],
        cross_connect_cap=2,
        committed_cabinet_count=1,
        power_commit_kw=20.0,
    )

    # The client's view of the contract is taken here and then deliberately outrun.
    pending = fx.move_contract(api, contract["id"], "PENDING_ACTIVATION")
    stale_version = pending["version"]

    near_end = fx.create_cabinet(api, row["id"], cabinet_code="C01")
    fx.reserve_cabinet(api, near_end["id"], contract["id"])
    fx.move_contract(api, contract["id"], "ACTIVE")
    fx.move_cabinet(api, near_end["id"], "INSTALLED")
    far_end = fx.create_cabinet(
        api, row["id"], cabinet_code="M01", footprint_type="MEET_ME", rated_power_kw=5.0
    )

    def order_payload(expected_version: int) -> dict:
        return f.create_cross_connect_order_payload(
            contract["id"],
            contact["id"],
            near_end["id"],
            far_end["id"],
            expected_version,
            cable_type="SMF",
        )

    validate_error(
        api.create_cross_connect_order(
            order_payload(stale_version), provisioning_engineer_headers
        ),
        ApiErrorId.ERR_STALE_CONTRACT_VERSION,
    )
    orders, meta = validate_paginated(
        api.list_cross_connect_orders(
            provisioning_engineer_headers, params={"contract_id": contract["id"]}
        )
    )
    assert orders == [], f"the refused create must have stored nothing, found {orders}"
    assert meta["total_count"] == 0, (
        f"the refused create must have stored nothing, total_count is {meta['total_count']}"
    )

    fresh_version = fx.contract_version(api, contract["id"])
    assert fresh_version > stale_version, (
        f"the reservation and activation must have moved the contract past {stale_version}, "
        f"but it still reads {fresh_version}"
    )

    order = validate_success(
        api.create_cross_connect_order(
            order_payload(fresh_version), provisioning_engineer_headers
        ),
        expected_status=201,
    )
    ax.assert_cross_connect_order(order)
    assert order["status"] == "SUBMITTED", f"status: expected SUBMITTED, got {order['status']}"
    assert order["revision_count"] == 0, (
        f"revision_count: expected 0, got {order['revision_count']}"
    )
    ax.assert_amount_equals(order["mrc_usd"], 300.00, "order.mrc_usd")

    assert fx.contract_version(api, contract["id"]) == fresh_version + 1, (
        "a successful create is itself a mutation of the contract, so its version must "
        f"have reached {fresh_version + 1}"
    )


def test_a_superseded_row_token_refuses_the_energization_and_a_fresh_one_carries_it(api):
    """PRD §2.6: "Energizing a power circuit — `POST /colocation/power-circuits/{circuit_id}/energize` — requires `expected_row_version` as a mandatory body field carrying the client's last observed `version` of the parent `FloorRow`."
    PRD §2.6: "A value that does not equal the row's current `version` is rejected with `ERR_STALE_ROW_VERSION` and HTTP 412."
    PRD §3.3: "On success the cabinet's `contract_id` is written, the row's `occupied_slot_count` rises by one, and the row's `density_ceiling_kw`, `effective_ceiling_kw`, both stranded views and `row_status` are recomputed; both the cabinet's and the row's `version` increment."
    PRD §3.4: "The cabinet's `allocated_power_kw`, `cooling_load_kw` and `energized_primary_circuit_count` are recomputed, and the cabinet advances `INSTALLED` → `ACTIVE` when its primary count moved from zero to one."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_row_version_refuses_the_energization_then_the_fresh_one_is_accepted
    """
    scenario = fx.setup_approved_circuit(
        api,
        row={"design_density_kw_per_cabinet": 25.0, "max_row_power_kw": 200.0, "cooling_capacity_kw": 60.0},
        contract={"committed_cabinet_count": 2, "power_commit_kw": 40.0},
        cabinet={"cabinet_code": "C01", "rated_power_kw": 20.0},
        circuit={"circuit_code": "A-1", "breaker_amps": 50, "volts": 240, "phase": "SINGLE"},
    )
    second = fx.create_cabinet(api, scenario.row_id, cabinet_code="C02")

    # The row view the client is about to act on.
    stale_version = fx.row_version(api, scenario.row_id)

    # A neighbour claims a slot, which supersedes that view.
    fx.reserve_cabinet(api, second["id"], scenario.contract_id)

    validate_error(
        api.energize_circuit(
            scenario.circuit_id, {"expected_row_version": stale_version}, ENGINEER_1
        ),
        ApiErrorId.ERR_STALE_ROW_VERSION,
    )
    ax.assert_circuit_power(fx.read_circuit(api, scenario.circuit_id), status="APPROVED")

    reread = fx.read_row(api, scenario.row_id)
    assert reread["version"] == stale_version + 1, (
        f"the reservation must have moved the row to {stale_version + 1}, "
        f"but it reads {reread['version']}"
    )
    ax.assert_row_capacity_view(
        reread, occupied_slot_count=2, density_ceiling_kw=50.000, allocated_power_kw=0.000
    )
    fresh_version = reread["version"]

    energized = validate_success(
        api.energize_circuit(
            scenario.circuit_id, {"expected_row_version": fresh_version}, ENGINEER_1
        )
    )
    ax.assert_circuit_power(
        energized, status="ENERGIZED", allocated_kw=9.600, cooling_contribution_kw=9.600
    )

    after = fx.read_row(api, scenario.row_id)
    assert after["version"] == fresh_version + 1, (
        f"the accepted energization must have moved the row to {fresh_version + 1}, "
        f"but it reads {after['version']}"
    )
    ax.assert_row_capacity_view(after, allocated_power_kw=9.600, cooling_load_kw=9.600)
    ax.assert_cabinet_power(fx.read_cabinet(api, scenario.cabinet_id), status="ACTIVE")


def test_cooling_posture_flips_exactly_at_ninety_percent_of_capacity(api):
    """PRD §3.2: "Otherwise, if `cooling_load_kw` has reached or passed 90 percent of `cooling_capacity_kw` the row is `COOLING_CONSTRAINED`."
    PRD §3.2: "Re-limiting recomputes the row's whole capacity picture, which means `row_status` can flip — in either direction — without a single cabinet or circuit having changed, and the row's `version` increments on every such adjustment."
    PRD §3.2: "The ordering is load-bearing: a row that is both thermally tight and at its density ceiling reports `COOLING_CONSTRAINED`, and the consequences of the two postures differ sharply — a `DENSITY_CAPPED` row holds its reserved cabinets, as §3.3 describes, while a `COOLING_CONSTRAINED` row holds nothing and merely stops accepting new space."
    PRD §3.2: "New space is accepted only by rows in `OPEN` or `COOLING_CONSTRAINED` posture."

    Design: Corner/cross_cutting_complexity_layers/row_cooling_posture_flips_at_exactly_ninety_percent_of_capacity
    """
    scenario = fx.setup_approved_circuit(
        api,
        row={"design_density_kw_per_cabinet": 25.0, "max_row_power_kw": 200.0, "cooling_capacity_kw": 20.0},
        contract={"committed_cabinet_count": 2, "power_commit_kw": 20.0},
        cabinet={"cabinet_code": "C01", "rated_power_kw": 20.0},
        circuit={"circuit_code": "A-1", "breaker_amps": 45, "volts": 250, "phase": "SINGLE"},
    )
    spare = fx.create_cabinet(api, scenario.row_id, cabinet_code="C02")
    fx.energize_circuit(api, scenario.circuit_id, scenario.row_id)

    # 9.000 kW against a 20.0 kW plant: the alert line sits at 18.000.
    ax.assert_row_capacity_view(
        fx.read_row(api, scenario.row_id),
        allocated_power_kw=9.000,
        cooling_load_kw=9.000,
        row_status="OPEN",
    )

    # 90 percent of 10.1 is 9.090, which the load has not reached.
    just_above = validate_success(
        api.update_row(
            scenario.row_id, f.update_row_payload(cooling_capacity_kw=10.1), FACILITY_MANAGER
        )
    )
    ax.assert_row_capacity_view(just_above, cooling_load_kw=9.000, row_status="OPEN")

    # 90 percent of 10.0 is exactly 9.000, and equality is enough.
    at_the_line = validate_success(
        api.update_row(
            scenario.row_id, f.update_row_payload(cooling_capacity_kw=10.0), FACILITY_MANAGER
        )
    )
    ax.assert_row_capacity_view(
        at_the_line,
        cooling_load_kw=9.000,
        effective_ceiling_kw=10.000,
        stranded_nameplate_kw=1.000,
        row_status="COOLING_CONSTRAINED",
    )

    # A thermally tight row still accepts new space, unlike a capped one.
    reserved = validate_success(
        api.set_cabinet_state(
            spare["id"],
            f.state_payload("RESERVED", contract_id=scenario.contract_id),
            FACILITY_MANAGER,
        )
    )
    assert reserved["status"] == "RESERVED", (
        f"a COOLING_CONSTRAINED row accepts new space; the reservation gave {reserved['status']}"
    )

    # And it holds nothing that was already energized.
    ax.assert_cabinet_power(fx.read_cabinet(api, scenario.cabinet_id), status="ACTIVE")
    ax.assert_circuit_power(fx.read_circuit(api, scenario.circuit_id), status="ENERGIZED")
