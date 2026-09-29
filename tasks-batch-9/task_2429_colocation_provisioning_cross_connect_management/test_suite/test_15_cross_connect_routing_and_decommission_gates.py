"""Cross-connect ordering, routing and decommission gates: the contract cap, each
routing guard in isolation, port stewardship across two orders, the quarantine
cool-down and its boundary instant, and the once-only decommission step.
"""

from datetime import datetime

from test_helpers import assertions as ax, factories as f, fixtures as fx
from test_helpers import (
    ENGINEER_1,
    ENGINEER_1_ID,
    ENGINEER_2,
    ApiErrorId,
    validate_error,
    validate_paginated,
    validate_success,
)


def _instant(value):
    """Parse an ISO 8601 UTC timestamp into a comparable datetime."""
    assert isinstance(value, str), f"expected an ISO 8601 UTC timestamp, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_same_instant(actual, expected, label):
    assert _instant(actual) == _instant(expected), f"{label}: expected {expected}, got {actual}"


def _add_meet_me_cabinet(api, scenario, cabinet_code="M01"):
    """A carrier meet-me panel on the same row, left `AVAILABLE`: a legal far side for
    a cross-connect, since only the A end is scoped to the contract."""
    cabinet = fx.create_cabinet(
        api,
        scenario.row_id,
        cabinet_code=cabinet_code,
        footprint_type="MEET_ME",
        rated_power_kw=5.0,
    )
    scenario.cabinets.append(cabinet)
    return cabinet


# ---------------------------------------------------------------------------
# The contract cross-connect cap
# ---------------------------------------------------------------------------


def test_second_cross_connect_order_beyond_the_contract_cap_is_refused(
    api, provisioning_engineer_headers
):
    """PRD §2.5: "The count of the contract's cross-connect orders that are neither `ABORTED` nor `DECOMMISSIONED`, including the one being created, is less than or equal to `cross_connect_cap`, otherwise `ERR_CROSS_CONNECT_CAP_EXCEEDED` (422)."
    PRD §3.5: "A created order opens in `SUBMITTED` with `revision_count` at 0, no route pinned, and `mrc_usd` fixed from the media it will use: 300.00 USD for `SMF`, 250.00 USD for `MMF`, 175.00 USD for `CAT6A`, 225.00 USD for `COAX`."
    PRD §2.6: "A successful create is itself a mutation of the contract and increments the contract's `version` by one, which is what makes a second create carrying the same token fail."

    Design: Corner/validations/second_cross_connect_order_beyond_the_contract_cap_is_refused
    """
    scenario = fx.setup_installed_cabinet(
        api, contract={"cross_connect_cap": 1}, cabinet={"cabinet_code": "C01"}
    )
    far_side = _add_meet_me_cabinet(api, scenario)
    scenario.contacts.append(fx.create_contact(api, scenario.customer_id))

    first = fx.raise_cross_connect_order(api, scenario, cable_type="SMF")
    assert first["status"] == "SUBMITTED"

    version_after_first = fx.contract_version(api, scenario.contract_id)
    validate_error(
        api.create_cross_connect_order(
            f.create_cross_connect_order_payload(
                scenario.contract_id,
                scenario.contact["id"],
                scenario.cabinet_id,
                far_side["id"],
                version_after_first,
                cable_type="MMF",
            ),
            provisioning_engineer_headers,
        ),
        ApiErrorId.ERR_CROSS_CONNECT_CAP_EXCEEDED,
    )

    orders, meta = validate_paginated(
        api.list_cross_connect_orders(
            provisioning_engineer_headers, params={"contract_id": scenario.contract_id}
        )
    )
    assert meta["total_count"] == 1, f"the cap holds the pool at one order, got {orders}"
    assert orders[0]["status"] == "SUBMITTED"
    assert orders[0]["cable_type"] == "SMF"
    ax.assert_amount_equals(orders[0]["mrc_usd"], 300.00, "order.mrc_usd")

    contract = fx.read_contract(api, scenario.contract_id)
    ax.assert_version_is(contract, version_after_first, "contract")


# ---------------------------------------------------------------------------
# The routing guards, one at a time
# ---------------------------------------------------------------------------


def _route_scenery(api):
    """One installed cabinet and a meet-me far side on row RE, a second row RF, and
    four ports: `PA`/`PB` `SMF` and `PC` `MMF` on RE, `PD` `SMF` on RF."""
    scenario = fx.setup_installed_cabinet(
        api, contract={"cross_connect_cap": 1}, cabinet={"cabinet_code": "C01"}
    )
    _add_meet_me_cabinet(api, scenario)
    scenario.contacts.append(fx.create_contact(api, scenario.customer_id))

    other_row = fx.create_row(api)
    scenario.rows.append(other_row)

    scenario.ports.append(fx.create_port(api, scenario.row_id, "PA", 1, "SMF"))
    scenario.ports.append(fx.create_port(api, scenario.row_id, "PB", 1, "SMF"))
    scenario.ports.append(fx.create_port(api, scenario.row_id, "PC", 1, "MMF"))
    scenario.ports.append(fx.create_port(api, other_row["id"], "PD", 1, "SMF"))

    fx.raise_cross_connect_order(api, scenario, cable_type="SMF")
    return scenario


def test_route_with_a_port_of_the_wrong_media_is_refused(api, provisioning_engineer_headers):
    """PRD §3.5: "Both ports' `media_type` must equal the order's `cable_type`, otherwise `ERR_MEDIA_TYPE_MISMATCH`."

    Design: Corner/validations/route_gates_fire_in_priority_order_before_the_corrected_route_is_accepted
    """
    scenario = _route_scenery(api)
    pa, _pb, pc, _pd = scenario.ports

    # Same row, well-formed hop list: only the media test can bite.
    validate_error(
        api.propose_route(
            scenario.order["id"],
            f.propose_route_payload(pa["id"], pc["id"], ["PA", "PC"]),
            provisioning_engineer_headers,
        ),
        ApiErrorId.ERR_MEDIA_TYPE_MISMATCH,
    )

    order = fx.read_order(api, scenario.order["id"])
    assert order["status"] == "SUBMITTED", (
        f"a refused proposal leaves the order SUBMITTED, got {order['status']}"
    )
    assert fx.read_port(api, pa["id"])["status"] == "FREE", (
        "a refused proposal reserves nothing"
    )


def test_route_whose_hop_list_repeats_a_panel_is_refused(api, provisioning_engineer_headers):
    """PRD §3.5: "Finally, `path_hops` must be non-empty, must begin with the A-side port's `panel_code`, must end with the Z-side port's `panel_code`, and must not repeat any panel code, otherwise `ERR_PATH_ROUTE_INVALID`; that single rule rejects disconnected, reversed and looping routes alike."

    Design: Corner/validations/route_gates_fire_in_priority_order_before_the_corrected_route_is_accepted
    """
    scenario = _route_scenery(api)
    pa, pb, _pc, _pd = scenario.ports

    # Both ports are SMF and both sit in the A-end row: only the hop list is wrong.
    validate_error(
        api.propose_route(
            scenario.order["id"],
            f.propose_route_payload(pa["id"], pb["id"], ["PA", "PA"]),
            provisioning_engineer_headers,
        ),
        ApiErrorId.ERR_PATH_ROUTE_INVALID,
    )

    order = fx.read_order(api, scenario.order["id"])
    assert order["status"] == "SUBMITTED"
    assert fx.read_port(api, pb["id"])["status"] == "FREE"


def test_route_whose_z_port_sits_in_another_row_is_refused(api, provisioning_engineer_headers):
    """PRD §3.5: "Each port must sit in the same row as the cabinet it terminates: the A-side port's `row_id` must equal the A-end cabinet's `row_id` and the Z-side port's `row_id` must equal the Z-end cabinet's `row_id`, otherwise `ERR_PORT_ROW_MISMATCH`."

    Design: Corner/validations/route_gates_fire_in_priority_order_before_the_corrected_route_is_accepted
    """
    scenario = _route_scenery(api)
    pa, _pb, _pc, pd = scenario.ports

    # Both ports are SMF and the hop list is well-formed: only the row test bites.
    validate_error(
        api.propose_route(
            scenario.order["id"],
            f.propose_route_payload(pa["id"], pd["id"], ["PA", "PD"]),
            provisioning_engineer_headers,
        ),
        ApiErrorId.ERR_PORT_ROW_MISMATCH,
    )

    order = fx.read_order(api, scenario.order["id"])
    assert order["status"] == "SUBMITTED"
    assert fx.read_port(api, pd["id"])["status"] == "FREE"


def test_the_corrected_route_is_accepted_and_reserves_only_its_own_ports(
    api, provisioning_engineer_headers
):
    """PRD §3.5: "On acceptance both ports move `FREE` → `RESERVED` with `assigned_order_id` set to this order, the two port references and the hop list are pinned onto the order, `proposed_by_user_id` records the acting `X-User-ID`, and the order's `version` increments."
    PRD §3.5: "Routing is exclusive to a `ProvisioningEngineer` and moves the order `SUBMITTED` → `ROUTE_PROPOSED` or, on a second attempt, `CHANGES_REQUESTED` → `ROUTE_PROPOSED`; both entry paths apply identical guards."

    Design: Corner/validations/route_gates_fire_in_priority_order_before_the_corrected_route_is_accepted
    """
    scenario = _route_scenery(api)
    pa, pb, pc, pd = scenario.ports
    order_id = scenario.order["id"]

    routed = validate_success(
        api.propose_route(
            order_id,
            f.propose_route_payload(pa["id"], pb["id"], ["PA", "PB"]),
            provisioning_engineer_headers,
        )
    )
    ax.assert_cross_connect_order(routed)
    assert routed["status"] == "ROUTE_PROPOSED", (
        f"a clean route advances the order, got {routed['status']}"
    )
    assert routed["path_hops"] == ["PA", "PB"], (
        f"the hop list is pinned as supplied, got {routed['path_hops']}"
    )
    assert routed["a_end_port_id"] == pa["id"]
    assert routed["z_end_port_id"] == pb["id"]
    assert routed["proposed_by_user_id"] == ENGINEER_1_ID, (
        f"proposed_by_user_id records the acting engineer, got {routed['proposed_by_user_id']}"
    )
    assert routed["revision_count"] == 0, "a first proposal consumes no revision"

    for port_id, label in ((pa["id"], "A-side"), (pb["id"], "Z-side")):
        held = fx.read_port(api, port_id)
        ax.assert_patch_panel_port(held)
        assert held["status"] == "RESERVED", (
            f"the {label} port is pinned by the proposal, got {held['status']}"
        )
        assert held["assigned_order_id"] == order_id, (
            f"the {label} port names the holding order"
        )

    for port_id, label in ((pc["id"], "wrong-media"), (pd["id"], "other-row")):
        spare = fx.read_port(api, port_id)
        assert spare["status"] == "FREE", (
            f"the {label} port was never reserved, got {spare['status']}"
        )
        assert spare["assigned_order_id"] is None, f"the {label} port names no order"


# ---------------------------------------------------------------------------
# A port already held by another order
# ---------------------------------------------------------------------------


def test_propose_route_refuses_a_port_already_reserved_by_another_order(
    api, provisioning_engineer_headers
):
    """PRD §3.5: "Neither endpoint port may currently be `RESERVED` or `ASSIGNED`, otherwise `ERR_PORT_UNAVAILABLE`; a `FREE` port and a `QUARANTINED` port both survive this test, so that a reclaimed port falls through to the cool-down check and reports the more specific error."
    PRD §3.5: "A created order opens in `SUBMITTED` with `revision_count` at 0, no route pinned, and `mrc_usd` fixed from the media it will use: 300.00 USD for `SMF`, 250.00 USD for `MMF`, 175.00 USD for `CAT6A`, 225.00 USD for `COAX`."
    PRD §3.5: "Over its life a port moves between `FREE`, `RESERVED` (pinned by a route proposal), `ASSIGNED` (physically patched) and `QUARANTINED` (reclaimed and cooling down), and `assigned_order_id` names the order holding it while it is reserved or assigned."

    Design: Corner/validations/propose_route_refuses_a_port_already_reserved_by_another_order
    """
    scenario = fx.setup_cross_connect_scenery(
        api,
        contract={
            "committed_cabinet_count": 2,
            "power_commit_kw": 40.0,
            "cross_connect_cap": 2,
        },
        port_pairs=1,
    )
    a_port = fx.a_ports(scenario)[0]
    z_port = fx.z_ports(scenario)[0]

    first = fx.raise_cross_connect_order(api, scenario, cable_type="SMF")
    fx.propose_route(api, first["id"], a_port["id"], z_port["id"])

    # A second order on the same contract, rooted at the other installed cabinet.
    second = validate_success(
        api.create_cross_connect_order(
            f.create_cross_connect_order_payload(
                scenario.contract_id,
                scenario.contact["id"],
                scenario.cabinets[1]["id"],
                scenario.cabinets[0]["id"],
                fx.contract_version(api, scenario.contract_id),
                cable_type="SMF",
            ),
            provisioning_engineer_headers,
        ),
        expected_status=201,
    )

    validate_error(
        api.propose_route(
            second["id"],
            f.propose_route_payload(a_port["id"], z_port["id"], ["PP-A", "PP-Z"]),
            provisioning_engineer_headers,
        ),
        ApiErrorId.ERR_PORT_UNAVAILABLE,
    )

    stored = fx.read_order(api, second["id"])
    assert stored["status"] == "SUBMITTED", (
        f"the second order keeps its unrouted status, got {stored['status']}"
    )
    assert stored["a_end_port_id"] is None, "no route may be pinned by a refused proposal"
    assert stored["path_hops"] == [], "an unrouted order carries an empty hop list"

    port = fx.read_port(api, a_port["id"])
    assert port["status"] == "RESERVED", f"the port stays with its holder, got {port['status']}"
    assert port["assigned_order_id"] == first["id"], (
        "assigned_order_id still names the first order"
    )


# ---------------------------------------------------------------------------
# The quarantine cool-down and its boundary
# ---------------------------------------------------------------------------


def test_port_quarantine_window_refuses_reuse_before_expiry_and_admits_it_at_the_boundary(
    api, provisioning_engineer_headers
):
    """PRD §3.8: "Third, the `ASSIGNED` ports of each such cross-connect become `QUARANTINED` with `quarantine_until` set to 24 hours after the logical clock and `assigned_order_id` cleared, which is the cool-down that §3.5's routing gates test against."
    PRD §3.5: "Neither port may be inside its quarantine window — that is, no port may carry a `quarantine_until` strictly later than the logical clock — otherwise `ERR_PORT_IN_QUARANTINE`; the boundary instant itself is accepted."
    PRD §3.5: "Over its life a port moves between `FREE`, `RESERVED` (pinned by a route proposal), `ASSIGNED` (physically patched) and `QUARANTINED` (reclaimed and cooling down), and `assigned_order_id` names the order holding it while it is reserved or assigned."

    Design: Corner/validations/port_quarantine_window_refuses_reuse_before_expiry_and_admits_it_at_the_boundary
    """
    scenario = fx.setup_cross_connect_scenery(
        api,
        contract={
            "committed_cabinet_count": 2,
            "power_commit_kw": 40.0,
            "cross_connect_cap": 2,
        },
        port_pairs=1,
    )
    far_side = _add_meet_me_cabinet(api, scenario)
    a_port = fx.a_ports(scenario)[0]
    z_port = fx.z_ports(scenario)[0]

    # A cross-connect on the first cabinet, carried all the way to ACTIVE so that its
    # ports are ASSIGNED when the cabinet is torn down.
    first = fx.raise_cross_connect_order(api, scenario, cable_type="SMF")
    fx.propose_route(api, first["id"], a_port["id"], z_port["id"])
    fx.move_order(api, first["id"], "APPROVED")
    fx.move_order(api, first["id"], "INSTALLED", ENGINEER_1)
    fx.move_order(api, first["id"], "ACTIVE")

    decommission = fx.raise_decommission_order(
        api, scenario, cabinet_id=scenario.cabinets[0]["id"]
    )
    fx.move_decommission(api, decommission["id"], "APPROVED")
    fx.record_step(api, decommission["id"], "EQUIPMENT_REMOVAL")
    fx.record_step(api, decommission["id"], "CABLE_RECLAMATION", ENGINEER_2)
    fx.release_ports(api, decommission["id"])

    quarantined = fx.read_port(api, a_port["id"])
    ax.assert_patch_panel_port(quarantined)
    assert quarantined["status"] == "QUARANTINED", (
        f"a reclaimed port cools down rather than freeing, got {quarantined['status']}"
    )
    _assert_same_instant(
        quarantined["quarantine_until"], "2026-08-02T00:00:00Z", "port.quarantine_until"
    )
    assert quarantined["assigned_order_id"] is None, (
        "the reclaimed port no longer names an order"
    )

    # A fresh order on the surviving cabinet wants the same pair back.
    reuse = validate_success(
        api.create_cross_connect_order(
            f.create_cross_connect_order_payload(
                scenario.contract_id,
                scenario.contact["id"],
                scenario.cabinets[1]["id"],
                far_side["id"],
                fx.contract_version(api, scenario.contract_id),
                cable_type="SMF",
            ),
            provisioning_engineer_headers,
        ),
        expected_status=201,
    )

    validate_error(
        api.propose_route(
            reuse["id"],
            f.propose_route_payload(a_port["id"], z_port["id"], ["PP-A", "PP-Z"]),
            provisioning_engineer_headers,
        ),
        ApiErrorId.ERR_PORT_IN_QUARANTINE,
    )

    # The boundary instant itself is accepted.
    fx.set_clock(api, "2026-08-02T00:00:00Z")
    routed = validate_success(
        api.propose_route(
            reuse["id"],
            f.propose_route_payload(a_port["id"], z_port["id"], ["PP-A", "PP-Z"]),
            provisioning_engineer_headers,
        )
    )
    assert routed["status"] == "ROUTE_PROPOSED", (
        f"the cool-down has expired, got {routed['status']}"
    )

    reclaimed = fx.read_port(api, a_port["id"])
    assert reclaimed["status"] == "RESERVED", (
        f"the port is pinned by the new proposal, got {reclaimed['status']}"
    )
    assert reclaimed["assigned_order_id"] == reuse["id"], (
        "assigned_order_id names the order now holding the port"
    )


# ---------------------------------------------------------------------------
# Recording a decommission step exactly once
# ---------------------------------------------------------------------------


def test_re_recording_a_completed_decommission_step_is_refused(
    api, provisioning_engineer_2_headers
):
    """PRD §3.8: "A `step_code` that already carries a timestamp on this order is refused with `ERR_DECOMMISSION_STEP_ALREADY_RECORDED` rather than being silently ignored, so each step is recorded exactly once."
    PRD §3.8: "Recording the first of them moves the order `APPROVED` → `IN_PROGRESS` and writes either `equipment_removed_at` and `equipment_removed_by_user_id` or `cables_reclaimed_at` and `cables_reclaimed_by_user_id`, taking the timestamp from the logical clock and the operator from `X-User-ID`."
    PRD §3.8: "Once both steps carry timestamps the order auto-advances to `READY_FOR_RELEASE` within that same request — the join is not a separate call — and the order's `version` increments."

    Design: Corner/validations/re_recording_a_completed_decommission_step_is_refused
    """
    scenario = fx.setup_installed_cabinet(api)
    scenario.contacts.append(fx.create_contact(api, scenario.customer_id))

    order = fx.raise_decommission_order(api, scenario)
    fx.move_decommission(api, order["id"], "APPROVED")
    first = fx.record_step(api, order["id"], "EQUIPMENT_REMOVAL")
    assert first["status"] == "IN_PROGRESS"

    # A different engineer, so segregation of duties is satisfied: the only thing
    # wrong with this call is that the step is already on the record.
    validate_error(
        api.record_decommission_step(
            order["id"], {"step_code": "EQUIPMENT_REMOVAL"}, provisioning_engineer_2_headers
        ),
        ApiErrorId.ERR_DECOMMISSION_STEP_ALREADY_RECORDED,
    )

    stored = fx.read_decommission(api, order["id"])
    ax.assert_decommission_order(stored)
    assert stored["status"] == "IN_PROGRESS", (
        f"the order must not join early, got {stored['status']}"
    )
    assert stored["equipment_removed_by_user_id"] == ENGINEER_1_ID, (
        "the original operator keeps the step"
    )
    assert stored["cables_reclaimed_at"] is None, "the second step is still outstanding"
