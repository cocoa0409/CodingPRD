"""Lifecycle transitions: the states each entity opens in, the guards that refuse a
move, and the side effects a successful move leaves behind.

Every test builds its own scenery: the harness empties the store before each test.
"""

from datetime import datetime, timedelta

from test_helpers import assertions as ax, constants as k, factories as f, fixtures as fx
from test_helpers import (
    ApiErrorId,
    validate_error,
    validate_success,
)
from test_helpers import BILLING_OPERATOR, ENGINEER_1, FACILITY_MANAGER, SECURITY_OFFICER


def _instant(value):
    """Parse an ISO 8601 UTC timestamp so two spellings of the same instant compare
    equal regardless of how many fractional digits the server writes."""
    assert value is not None, "expected a timestamp, got null"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Contract lifecycle
# ---------------------------------------------------------------------------


def test_contract_opens_in_draft_with_the_bundle_untouched(api):
    """PRD §3.1: "A newly created contract opens in `DRAFT` with `credit_hold` false, `remote_hands_remaining_minutes` initialised to `remote_hands_included_minutes`, every rollup field (`provisioned_power_kw`, `stranded_commit_kw`, `commit_utilization_pct`, `active_cross_connect_count`, `billed_total_usd`, `cross_connect_billed_usd`) at zero and `last_closed_period_end` unset."
    PRD §2.4: "Customers, contracts, floor rows, cabinets, power circuits, patch-panel ports, cross-connect orders, authorized contacts, access visits, remote-hands tickets and decommission orders additionally carry `updated_at`, refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by one on each mutation of that row."

    Design: Corner/state_machines/contract_starts_in_draft_with_no_bundle_armed
    """
    fx.set_clock(api)
    customer = fx.create_customer(api)

    data = validate_success(
        api.create_contract(
            f.create_contract_payload(customer["id"], remote_hands_included_minutes=120),
            BILLING_OPERATOR,
        ),
        201,
    )

    assert data["status"] == "DRAFT"
    assert data["credit_hold"] is False
    assert data["remote_hands_included_minutes"] == 120
    assert data["remote_hands_remaining_minutes"] == 120
    ax.assert_version_is(data, 1, "contract")


def test_draft_to_pending_activation_arms_the_bundle_and_bumps_the_version(api):
    """PRD §3.1: "Readying a draft for activation is a `FacilityManager` action: the contract must still be in `DRAFT`, its `term_end_date` must be strictly later than its `term_start_date`, and on success the bundled-minutes balance is set from `remote_hands_included_minutes` and the contract's `version` increments."
    PRD §3.1: "Four further commitments are optional and default when omitted: `committed_cage_sqft`, the caged floor area in square feet, defaults to 0 and may not be negative; `redundancy_requirement` defaults to `N` and may also be `N_PLUS_1` or `TWO_N`; `cross_connect_allowance`, the number of active cross-connects waived at each period close, defaults to 0 and may not be negative; and `remote_hands_included_minutes`, the bundle of hands-and-eyes minutes sold with the contract, defaults to 0, may not be negative, and must be a whole multiple of 15 minutes because that is the granularity at which labour is billed."

    Design: Corner/state_machines/draft_to_pending_activation_arms_the_bundled_minutes_and_bumps_version
    """
    fx.set_clock(api)
    customer = fx.create_customer(api)

    payload = f.create_contract_payload(customer["id"])
    payload.pop("remote_hands_included_minutes")
    created = validate_success(api.create_contract(payload, BILLING_OPERATOR), 201)
    assert created["remote_hands_included_minutes"] == 0

    data = validate_success(
        api.set_contract_state(created["id"], f.state_payload("PENDING_ACTIVATION"), FACILITY_MANAGER)
    )

    assert data["status"] == "PENDING_ACTIVATION"
    assert data["remote_hands_included_minutes"] == 0
    assert data["remote_hands_remaining_minutes"] == 0
    ax.assert_version_is(data, 2, "contract")


def test_contract_activation_without_any_assigned_cabinet_is_refused(api):
    """PRD §3.1: "Activation itself is also a `FacilityManager` action and is the point at which the contract stops being a piece of paper: the contract must be in `PENDING_ACTIVATION` and must already hold at least one cabinet in `RESERVED`, `CAPACITY_HELD`, `INSTALLED` or `ACTIVE` — a cabinet the row has put on capacity hold still counts, because it still occupies its slot — and a contract with no space at all is refused with `ERR_NO_CABINET_ASSIGNED`."

    Design: Corner/state_machines/contract_activation_without_any_assigned_cabinet_is_refused
    """
    scenario = fx.setup_contract(api, row={"hall_code": "H2", "row_code": "R1"})
    fx.move_contract(api, scenario.contract_id, "PENDING_ACTIVATION")

    validate_error(
        api.set_contract_state(scenario.contract_id, f.state_payload("ACTIVE"), FACILITY_MANAGER),
        ApiErrorId.ERR_NO_CABINET_ASSIGNED,
    )

    after = fx.read_contract(api, scenario.contract_id)
    assert after["status"] == "PENDING_ACTIVATION", "a refused activation leaves the status alone"
    ax.assert_version_is(after, 2, "contract")


def test_terminated_contract_refuses_every_further_transition(api):
    """PRD §3.1: "Six lifecycle steps are then available, and the `status` field walks them: `DRAFT` → `PENDING_ACTIVATION` → `ACTIVE`, the reinstatement cycle `ACTIVE` ⇄ `SUSPENDED`, and the wind-down path `ACTIVE` → `WIND_DOWN` → `TERMINATED`, with `TERMINATED` accepting nothing further."
    PRD §2.5: "The requested `to_state` is reachable from the entity's current state per §3, otherwise `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/terminated_contract_refuses_every_further_transition
    """
    scenario = fx.setup_active_contract(
        api, row={"hall_code": "H2", "row_code": "R1"}, cabinet={"cabinet_code": "C01"}
    )
    # The space must be genuinely clear before termination is accepted.
    fx.move_cabinet(api, scenario.cabinet_id, "AVAILABLE")
    fx.move_contract(api, scenario.contract_id, "WIND_DOWN")
    terminated = fx.move_contract(api, scenario.contract_id, "TERMINATED")
    assert terminated["status"] == "TERMINATED"
    version_at_terminal = terminated["version"]

    validate_error(
        api.set_contract_state(scenario.contract_id, f.state_payload("ACTIVE"), BILLING_OPERATOR),
        ApiErrorId.ERR_INVALID_STATE,
    )

    after = fx.read_contract(api, scenario.contract_id)
    assert after["status"] == "TERMINATED"
    ax.assert_version_is(after, version_at_terminal, "contract")


def test_suspended_reinstatement_is_refused_while_the_credit_hold_stands(api):
    """PRD §3.1: "Reinstating a `SUSPENDED` contract to `ACTIVE` is refused with `ERR_CREDIT_HOLD_ACTIVE` while `credit_hold` is true, and the `ACTIVE` ⇄ `SUSPENDED` cycle may repeat without bound."
    PRD §3.1: "Setting or clearing the hold is a separate `BillingOperator` capability that writes the `credit_hold` flag from the request body and nothing else: existing orders, tickets and visits are never retro-actively cancelled when a hold goes on."

    Design: Corner/state_machines/suspended_reinstatement_is_refused_while_the_credit_hold_stands
    """
    scenario = fx.setup_active_contract(
        api, row={"hall_code": "H2", "row_code": "R1"}, cabinet={"cabinet_code": "C01"}
    )
    suspended = validate_success(
        api.set_contract_state(scenario.contract_id, f.state_payload("SUSPENDED"), BILLING_OPERATOR)
    )
    assert suspended["status"] == "SUSPENDED"
    validate_success(
        api.set_credit_hold(scenario.contract_id, {"credit_hold": True}, BILLING_OPERATOR)
    )

    validate_error(
        api.set_contract_state(scenario.contract_id, f.state_payload("ACTIVE"), BILLING_OPERATOR),
        ApiErrorId.ERR_CREDIT_HOLD_ACTIVE,
    )
    assert fx.read_contract(api, scenario.contract_id)["status"] == "SUSPENDED"

    cleared = validate_success(
        api.set_credit_hold(scenario.contract_id, {"credit_hold": False}, BILLING_OPERATOR)
    )
    assert cleared["credit_hold"] is False
    assert cleared["status"] == "SUSPENDED", "clearing the hold writes the flag and nothing else"

    reinstated = validate_success(
        api.set_contract_state(scenario.contract_id, f.state_payload("ACTIVE"), BILLING_OPERATOR)
    )
    assert reinstated["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Cabinet lifecycle
# ---------------------------------------------------------------------------


def test_cabinet_release_returns_the_row_slot_and_clears_the_contract_link(api):
    """PRD §3.3: "A successful release clears `contract_id` back to unset, lowers `occupied_slot_count` by one, recomputes the row's density ceiling, effective ceiling, both stranded views and posture, and increments both versions."
    PRD §3.2: "`density_ceiling_kw` is the design density multiplied by the number of occupied slots, rounded to three decimals — a row engineered at 8 kW per cabinet with five occupied slots carries a ceiling of 40 kW, and that ceiling grows and shrinks with occupancy rather than with the row's physical slot count."
    PRD §3.2: "`effective_ceiling_kw` is the smallest of three numbers: the busway limit `max_row_power_kw`, the density ceiling just derived, and the cooling capacity."

    Design: Corner/state_machines/cabinet_release_returns_the_row_slot_and_clears_the_contract_link
    """
    scenario = fx.setup_active_contract(
        api,
        row={"hall_code": "H2", "row_code": "R1", "design_density_kw_per_cabinet": 25.0},
        cabinet={"cabinet_code": "C01"},
    )
    row_while_reserved = fx.read_row(api, scenario.row_id)
    ax.assert_row_capacity_view(
        row_while_reserved, occupied_slot_count=1, density_ceiling_kw=25.000
    )
    version_while_reserved = row_while_reserved["version"]

    released = validate_success(
        api.set_cabinet_state(scenario.cabinet_id, f.state_payload("AVAILABLE"), FACILITY_MANAGER)
    )

    assert released["status"] == "AVAILABLE"
    assert released["contract_id"] is None, "a release clears contract_id back to unset"

    row_after = fx.read_row(api, scenario.row_id)
    ax.assert_row_capacity_view(
        row_after,
        occupied_slot_count=0,
        density_ceiling_kw=0.000,
        effective_ceiling_kw=0.000,
        row_status="OPEN",
    )
    ax.assert_version_is(row_after, version_while_reserved + 1, "row")


def test_cabinet_install_before_the_contract_is_active_is_refused(api):
    """PRD §3.3: "Installing a reserved cabinet — the step that says the enclosure is physically in place — requires the cabinet to be `RESERVED` and its contract to be `ACTIVE`, reporting `ERR_CONTRACT_NOT_ACTIVE` if it is not, and increments the cabinet's `version` only."
    PRD §2.5: "On cabinet state transitions the accepted set widens as described in §3.3: moving a cabinet from `AVAILABLE` to `RESERVED` accepts a contract in `PENDING_ACTIVATION` or `ACTIVE`, while moving it from `RESERVED` to `INSTALLED` requires `ACTIVE`."

    Design: Corner/state_machines/cabinet_install_before_the_contract_is_active_is_refused
    """
    scenario = fx.setup_reserved_cabinet(
        api, row={"hall_code": "H2", "row_code": "R1"}, cabinet={"cabinet_code": "C01"}
    )
    assert fx.read_contract(api, scenario.contract_id)["status"] == "PENDING_ACTIVATION"

    validate_error(
        api.set_cabinet_state(scenario.cabinet_id, f.state_payload("INSTALLED"), FACILITY_MANAGER),
        ApiErrorId.ERR_CONTRACT_NOT_ACTIVE,
    )
    assert fx.read_cabinet(api, scenario.cabinet_id)["status"] == "RESERVED"

    activated = validate_success(
        api.set_contract_state(scenario.contract_id, f.state_payload("ACTIVE"), FACILITY_MANAGER)
    )
    assert activated["status"] == "ACTIVE"

    installed = validate_success(
        api.set_cabinet_state(scenario.cabinet_id, f.state_payload("INSTALLED"), FACILITY_MANAGER)
    )
    assert installed["status"] == "INSTALLED"


# ---------------------------------------------------------------------------
# Power circuit lifecycle
# ---------------------------------------------------------------------------


def test_circuit_approval_against_an_available_cabinet_is_refused(api):
    """PRD §3.4: "The circuit must be `DESIGNED`; its cabinet must be in `RESERVED`, `INSTALLED` or `ACTIVE`, otherwise `ERR_CABINET_NOT_OPERATIONAL`; and the cabinet's breaker sizing must survive the addition."
    PRD §3.4: "`derated_kw` is the breaker amperage multiplied by the voltage, multiplied by the phase factor — 1.0 for a `SINGLE`-phase supply and 1.732 for a `THREE`-phase supply — divided by 1000 to convert volt-amperes to kilowatts, then multiplied by the 0.80 continuous-load derate that electrical code requires, and finally rounded half-up to three decimal places."

    Design: Corner/state_machines/circuit_approval_against_an_available_cabinet_is_refused
    """
    fx.set_clock(api)
    row = fx.create_row(
        api,
        hall_code="H2",
        row_code="R1",
        design_density_kw_per_cabinet=40.0,
        cooling_capacity_kw=80.0,
    )
    cabinet = fx.create_cabinet(api, row["id"], cabinet_code="C01", rated_power_kw=40.0)
    assert cabinet["status"] == "AVAILABLE"
    circuit = fx.create_circuit(
        api, cabinet["id"], circuit_code="A-1", breaker_amps=50, volts=240, phase="SINGLE"
    )

    validate_error(
        api.set_circuit_state(circuit["id"], f.state_payload("APPROVED"), FACILITY_MANAGER),
        ApiErrorId.ERR_CABINET_NOT_OPERATIONAL,
    )

    after = fx.read_circuit(api, circuit["id"])
    ax.assert_circuit_power(after, status="DESIGNED", derated_kw=9.600, allocated_kw=0.000)


def test_repeated_energize_on_an_already_energized_circuit_is_refused(api):
    """PRD §3.4: "The circuit must be in `APPROVED` or in `DE_ENERGIZED` — a circuit may be cycled between `DE_ENERGIZED` and `ENERGIZED` any number of times as long as its cabinet is not decommissioning — and the identical set of guards applies to both entry paths."
    PRD §2.5: "The requested `to_state` is reachable from the entity's current state per §3, otherwise `ERR_INVALID_STATE` (409). This includes terminal-state lockdown — `TERMINATED`, `RELEASED`, `REMOVED`, `DECOMMISSIONED`, `ABORTED`, `CLOSED`, `CANCELLED` and `CHECKED_OUT` accept no further transitions — and the rejection of a replayed trigger."

    Design: Corner/state_machines/repeated_energize_on_an_already_energized_circuit_is_refused
    """
    scenario = fx.setup_approved_circuit(
        api,
        row={"hall_code": "H2", "row_code": "R1"},
        contract={"power_commit_kw": 20.0, "redundancy_requirement": "N"},
        cabinet={"cabinet_code": "C01", "rated_power_kw": 20.0},
        circuit={"circuit_code": "A-1", "breaker_amps": 50, "volts": 240, "phase": "SINGLE"},
    )

    energized = validate_success(
        api.energize_circuit(
            scenario.circuit_id,
            {"expected_row_version": fx.row_version(api, scenario.row_id)},
            ENGINEER_1,
        )
    )
    ax.assert_circuit_power(
        energized, status="ENERGIZED", allocated_kw=9.600, cooling_contribution_kw=9.600
    )
    row_after_first = fx.read_row(api, scenario.row_id)

    validate_error(
        api.energize_circuit(
            scenario.circuit_id,
            {"expected_row_version": row_after_first["version"]},
            ENGINEER_1,
        ),
        ApiErrorId.ERR_INVALID_STATE,
    )

    row_after_replay = fx.read_row(api, scenario.row_id)
    ax.assert_row_capacity_view(
        row_after_replay, allocated_power_kw=9.600, cooling_load_kw=9.600
    )
    ax.assert_version_is(row_after_replay, row_after_first["version"], "row")
    ax.assert_contract_power_rollup(
        fx.read_contract(api, scenario.contract_id), provisioned_power_kw=9.600
    )


# ---------------------------------------------------------------------------
# Cross-connect order lifecycle
# ---------------------------------------------------------------------------


def test_aborting_a_routed_order_returns_both_ports_to_the_free_pool(api):
    """PRD §3.5: "Abandonment is available from any of `SUBMITTED`, `ROUTE_PROPOSED`, `CHANGES_REQUESTED` and `APPROVED`, and moves the order to `ABORTED`, which is terminal."
    PRD §3.5: "Every port whose `assigned_order_id` names this order and whose status is `RESERVED` or `ASSIGNED` returns to `FREE` with `assigned_order_id` cleared, and the order's `version` increments."

    Design: Corner/state_machines/aborting_a_routed_order_returns_both_ports_to_the_free_pool
    """
    scenario = fx.setup_routed_order(
        api,
        row={"hall_code": "H2", "row_code": "R1"},
        contract={"committed_cabinet_count": 2, "cross_connect_cap": 4},
        port_pairs=1,
        media_type="SMF",
    )
    a_port = fx.a_ports(scenario)[0]
    z_port = fx.z_ports(scenario)[0]
    for port in (a_port, z_port):
        held = fx.read_port(api, port["id"])
        assert held["status"] == "RESERVED"
        assert held["assigned_order_id"] == scenario.order["id"]

    aborted = validate_success(
        api.set_cross_connect_order_state(
            scenario.order["id"], f.state_payload("ABORTED"), FACILITY_MANAGER
        )
    )
    assert aborted["status"] == "ABORTED"

    for port in (a_port, z_port):
        freed = fx.read_port(api, port["id"])
        assert freed["status"] == "FREE", (
            f"port {freed['panel_code']}/{freed['port_number']} must return to FREE, "
            f"got {freed['status']}"
        )
        assert freed["assigned_order_id"] is None
        assert freed["quarantine_until"] is None, "abandonment frees a port without a cool-down"

    ax.assert_contract_billing_rollup(
        fx.read_contract(api, scenario.contract_id), active_cross_connect_count=0
    )
    assert fx.invoice_lines(api, scenario.contract_id) == [], (
        "abandoning an order bills nothing and credits nothing"
    )


# ---------------------------------------------------------------------------
# Access visit lifecycle
# ---------------------------------------------------------------------------


def test_check_out_directly_from_scheduled_is_refused(api):
    """PRD §3.7: "New visits open in `SCHEDULED`, and the lifecycle is `SCHEDULED` → `CHECKED_IN` → `CHECKED_OUT`, with `SCHEDULED` → `CANCELLED` as the abandonment path; `CHECKED_OUT` and `CANCELLED` are both terminal."
    PRD §3.7: "It is true when any one of three conditions holds: the contact's `access_level` is `ESCORTED_ONLY`, or the visit's `purpose` is `CARRIER_INSTALL`, or the target cabinet's `footprint_type` is `MEET_ME`."

    Design: Corner/state_machines/check_out_directly_from_scheduled_is_refused
    """
    scenario = fx.setup_visit_scenery(
        api,
        row={"hall_code": "H2", "row_code": "R1"},
        cabinet={"cabinet_code": "C01"},
        access_level="UNESCORTED",
        enrolled=False,
    )
    visit = fx.schedule_visit(
        api, scenario, "2026-08-01T09:00:00Z", "2026-08-01T11:00:00Z", purpose="MAINTENANCE"
    )
    assert visit["status"] == "SCHEDULED"

    validate_error(
        api.set_access_visit_state(visit["id"], f.state_payload("CHECKED_OUT"), SECURITY_OFFICER),
        ApiErrorId.ERR_INVALID_STATE,
    )

    after = fx.read_visit(api, visit["id"])
    assert after["status"] == "SCHEDULED"
    assert after["checked_in_at"] is None
    assert after["checked_out_at"] is None
    assert after["escort_required"] is False


# ---------------------------------------------------------------------------
# Decommission order lifecycle
# ---------------------------------------------------------------------------


def test_cancelling_a_requested_decommission_leaves_the_cabinet_untouched(api):
    """PRD §3.8: "Cancelling a still-`REQUESTED` order cascades nothing at all — the cabinet keeps whatever status it had — and increments only the order's `version`."
    PRD §3.8: "On acceptance the cabinet moves from `INSTALLED` or `ACTIVE` to `DECOMMISSIONING`; every `ENERGIZED` circuit on it moves to `DE_ENERGIZED` with `allocated_kw` and `cooling_contribution_kw` zeroed; `released_power_kw` records the total allocated kilowatts thereby de-energized, rounded to three decimals, and is 0.000 when the cabinet was merely `INSTALLED` and carried no energized load; the row's `allocated_power_kw`, `cooling_load_kw`, both stranded views and `row_status` are recomputed, which may return a `DENSITY_CAPPED` row to `OPEN` and thereby lift capacity holds elsewhere in the row; the contract's `provisioned_power_kw`, `stranded_commit_kw` and `commit_utilization_pct` are refreshed; and the order's, the cabinet's and the row's `version` all increment."

    Design: Corner/state_machines/cancelling_a_requested_decommission_leaves_the_cabinet_untouched
    """
    scenario = fx.setup_energized_cabinet(
        api,
        row={"hall_code": "H2", "row_code": "R1"},
        contract={"power_commit_kw": 20.0},
        cabinet={"cabinet_code": "C01", "rated_power_kw": 20.0},
        circuit={"circuit_code": "A-1", "breaker_amps": 50, "volts": 240, "phase": "SINGLE"},
    )
    scenario.contacts.append(
        fx.create_contact(api, scenario.customer_id, authorization_scopes=["REMOTE_HANDS"])
    )
    order = fx.raise_decommission_order(api, scenario)
    assert order["status"] == "REQUESTED"

    cancelled = validate_success(
        api.set_decommission_order_state(
            order["id"], f.state_payload("CANCELLED"), FACILITY_MANAGER
        )
    )
    assert cancelled["status"] == "CANCELLED"
    ax.assert_kw_equals(
        cancelled["released_power_kw"], 0.000, "decommission order.released_power_kw"
    )

    ax.assert_cabinet_power(
        fx.read_cabinet(api, scenario.cabinet_id),
        status="ACTIVE",
        allocated_power_kw=9.600,
        energized_primary_circuit_count=1,
    )
    ax.assert_circuit_power(
        fx.read_circuit(api, scenario.circuit_id), status="ENERGIZED", allocated_kw=9.600
    )
    ax.assert_contract_power_rollup(
        fx.read_contract(api, scenario.contract_id), provisioned_power_kw=9.600
    )


# ---------------------------------------------------------------------------
# Biometric revocation
# ---------------------------------------------------------------------------


def test_biometric_revocation_cancels_the_scheduled_visit_and_revokes_the_open_ticket(api):
    """PRD §3.7: "Revocation is deliberately blunt and cascades beyond the contact record: every non-terminal remote-hands ticket raised by that contact has its `authorization_state` forced to `REVOKED`, and every `SCHEDULED` access visit for that contact is moved to `CANCELLED`, releasing the cabinet window and escort slot each of those visits was holding."
    PRD §3.6: "Revoking an already `AUTHORIZED` ticket is refused with `ERR_INVALID_STATE` once execution has reached `COMPLETED`; otherwise it forces `execution_state` to `CANCELLED` from whichever of `QUEUED`, `DISPATCHED` or `IN_PROGRESS` it currently holds."
    PRD §3.6: "`response_deadline_at` is `authorized_at` advanced by 30 minutes for a `CRITICAL` ticket, by 120 minutes for a `HIGH` ticket, and by 480 minutes — eight hours — for a `STANDARD` ticket."

    Design: Corner/state_machines/biometric_revocation_cancels_the_scheduled_visit_and_revokes_the_open_ticket
    """
    scenario = fx.setup_installed_cabinet(
        api, row={"hall_code": "H2", "row_code": "R1"}, cabinet={"cabinet_code": "C01"}
    )
    requester = fx.create_contact(
        api,
        scenario.customer_id,
        authorization_scopes=["SITE_ACCESS", "REMOTE_HANDS"],
        access_level="UNESCORTED",
    )
    requester = fx.enroll_contact(api, requester["id"])
    assert requester["biometric_state"] == "ENROLLED"
    enrolled_at = requester["enrolled_at"]
    assert _instant(enrolled_at) == _instant(k.DEFAULT_CLOCK)

    authorizer = fx.create_contact(
        api, scenario.customer_id, authorization_scopes=["REMOTE_HANDS"]
    )
    scenario.contacts.extend([requester, authorizer])

    visit = fx.schedule_visit(
        api,
        scenario,
        "2026-08-01T09:00:00Z",
        "2026-08-01T11:00:00Z",
        contact_id=requester["id"],
        purpose="MAINTENANCE",
    )
    ticket = fx.raise_ticket(api, scenario, severity="STANDARD")
    authorized = fx.authorize_ticket(api, ticket["id"], authorizer["id"])
    assert authorized["authorization_state"] == "AUTHORIZED"
    assert authorized["execution_state"] == "QUEUED"
    assert _instant(authorized["response_deadline_at"]) == _instant(
        authorized["authorized_at"]
    ) + timedelta(minutes=480)

    revoked = validate_success(
        api.set_contact_biometric_state(
            requester["id"], f.state_payload("REVOKED"), SECURITY_OFFICER
        )
    )

    assert revoked["biometric_state"] == "REVOKED"
    assert _instant(revoked["enrolled_at"]) == _instant(enrolled_at), (
        "revocation does not rewrite the enrollment stamp"
    )

    visit_after = fx.read_visit(api, visit["id"])
    assert visit_after["status"] == "CANCELLED", (
        f"the SCHEDULED visit must be cancelled, got {visit_after['status']}"
    )

    ticket_after = fx.read_ticket(api, ticket["id"])
    assert ticket_after["authorization_state"] == "REVOKED"
    # PRD §3.7 enumerates the biometric-revocation cascade as forcing the
    # ticket's `authorization_state` to `REVOKED` (and cancelling SCHEDULED
    # visits); it does not state that the cascade also drives the independent
    # `execution_state` dimension. §3.6's execution-cancelling clause is scoped
    # to the explicit revoke action on the ticket itself, so no assertion on
    # `execution_state` is made here.
    assert _instant(ticket_after["response_deadline_at"]) == _instant(
        authorized["response_deadline_at"]
    ), "the response commitment is not re-derived by a revocation"
