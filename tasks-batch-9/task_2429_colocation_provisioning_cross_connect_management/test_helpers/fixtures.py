"""Composite state builders.

Nearly every rule in this PRD sits behind a chain of prerequisites: a circuit can
only be energized after a customer exists, a row has been engineered, a contract has
been raised and driven to `ACTIVE`, a cabinet has been created, reserved to that
contract and installed, and a circuit has been designed and approved against it. The
builders below construct exactly those chains in progressive prefixes, so a test
states only the step it is actually about.

Two identity subtleties are threaded for callers. `CustomerAdmin` acts under the
`Customer.id` it represents, so :attr:`Scenario.admin_headers` builds those headers
from the created customer. And the operator roles carry distinct staff identifiers
wherever the PRD splits duties — the engineer who raises a cross-connect order is not
the manager who approves it, the contact who requests remote hands is not the contact
who authorizes it, and the two decommission steps are recorded by two people.

The harness restarts the server and empties the store before each test, so every
builder starts from nothing and never assumes a leftover record.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import DEFAULT_CLOCK
from .test_users import (
    BILLING_OPERATOR,
    ENGINEER_1,
    ENGINEER_2,
    FACILITY_MANAGER,
    SECURITY_OFFICER,
    make_customer_admin_headers,
)


# ---------------------------------------------------------------------------
# The state carried between steps
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    """Records produced by a setup chain, in the order the chain created them."""

    customer: Optional[Dict[str, Any]] = None
    contracts: List[Dict[str, Any]] = field(default_factory=list)
    contacts: List[Dict[str, Any]] = field(default_factory=list)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    cabinets: List[Dict[str, Any]] = field(default_factory=list)
    circuits: List[Dict[str, Any]] = field(default_factory=list)
    ports: List[Dict[str, Any]] = field(default_factory=list)
    orders: List[Dict[str, Any]] = field(default_factory=list)
    tickets: List[Dict[str, Any]] = field(default_factory=list)
    visits: List[Dict[str, Any]] = field(default_factory=list)
    decommissions: List[Dict[str, Any]] = field(default_factory=list)

    # --- singular accessors for the common one-of-each chains --------------

    @property
    def contract(self) -> Dict[str, Any]:
        return self.contracts[0]

    @property
    def contact(self) -> Dict[str, Any]:
        return self.contacts[0]

    @property
    def row(self) -> Dict[str, Any]:
        return self.rows[0]

    @property
    def cabinet(self) -> Dict[str, Any]:
        return self.cabinets[0]

    @property
    def circuit(self) -> Dict[str, Any]:
        return self.circuits[0]

    @property
    def order(self) -> Dict[str, Any]:
        return self.orders[0]

    @property
    def ticket(self) -> Dict[str, Any]:
        return self.tickets[0]

    @property
    def visit(self) -> Dict[str, Any]:
        return self.visits[0]

    @property
    def decommission(self) -> Dict[str, Any]:
        return self.decommissions[0]

    # --- identifiers -------------------------------------------------------

    @property
    def customer_id(self) -> str:
        assert self.customer is not None, "no customer has been created yet"
        return self.customer["id"]

    @property
    def contract_id(self) -> str:
        return self.contract["id"]

    @property
    def row_id(self) -> str:
        return self.row["id"]

    @property
    def cabinet_id(self) -> str:
        return self.cabinet["id"]

    @property
    def circuit_id(self) -> str:
        return self.circuit["id"]

    @property
    def admin_headers(self) -> Dict[str, str]:
        """Headers for the customer's own administrator: the `CustomerAdmin` role
        carrying the `Customer.id` it acts for."""
        return make_customer_admin_headers(self.customer_id)


# ---------------------------------------------------------------------------
# Tier 1 — the logical clock
# ---------------------------------------------------------------------------


def set_clock(client: ApiClient, current_utc: str = DEFAULT_CLOCK) -> Dict[str, Any]:
    """Move the logical clock; setting it mutates no stored record."""
    return get_success_data(client.set_clock(current_utc, FACILITY_MANAGER))


# ---------------------------------------------------------------------------
# Tier 1 — single-entity builders
# ---------------------------------------------------------------------------


def create_customer(client: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        client.create_customer(f.create_customer_payload(**overrides), FACILITY_MANAGER)
    )


def create_contact(client: ApiClient, customer_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        client.create_contact(f.create_contact_payload(customer_id, **overrides), SECURITY_OFFICER)
    )


def enroll_contact(client: ApiClient, contact_id: str) -> Dict[str, Any]:
    """Move a contact's biometric enrollment to `ENROLLED`, which stamps `enrolled_at`."""
    return get_success_data(
        client.set_contact_biometric_state(
            contact_id, f.state_payload("ENROLLED"), SECURITY_OFFICER
        )
    )


def enrolled_contact(client: ApiClient, customer_id: str, **overrides) -> Dict[str, Any]:
    contact = create_contact(client, customer_id, **overrides)
    return enroll_contact(client, contact["id"])


def create_row(client: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(client.create_row(f.create_row_payload(**overrides), FACILITY_MANAGER))


def relimit_row(client: ApiClient, row_id: str, **fields) -> Dict[str, Any]:
    """Adjust a live row's limits, which recomputes its whole capacity picture."""
    return get_success_data(
        client.update_row(row_id, f.update_row_payload(**fields), FACILITY_MANAGER)
    )


def create_contract(client: ApiClient, customer_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        client.create_contract(f.create_contract_payload(customer_id, **overrides), BILLING_OPERATOR)
    )


def move_contract(client: ApiClient, contract_id: str, to_state: str) -> Dict[str, Any]:
    return get_success_data(
        client.set_contract_state(contract_id, f.state_payload(to_state), FACILITY_MANAGER)
    )


def set_credit_hold(client: ApiClient, contract_id: str, credit_hold: bool) -> Dict[str, Any]:
    return get_success_data(
        client.set_credit_hold(contract_id, {"credit_hold": credit_hold}, BILLING_OPERATOR)
    )


def create_cabinet(client: ApiClient, row_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        client.create_cabinet(f.create_cabinet_payload(row_id, **overrides), FACILITY_MANAGER)
    )


def reserve_cabinet(client: ApiClient, cabinet_id: str, contract_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.set_cabinet_state(
            cabinet_id, f.state_payload("RESERVED", contract_id=contract_id), FACILITY_MANAGER
        )
    )


def move_cabinet(client: ApiClient, cabinet_id: str, to_state: str, **extra) -> Dict[str, Any]:
    return get_success_data(
        client.set_cabinet_state(cabinet_id, f.state_payload(to_state, **extra), FACILITY_MANAGER)
    )


def create_circuit(client: ApiClient, cabinet_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        client.create_power_circuit(
            f.create_power_circuit_payload(cabinet_id, **overrides), ENGINEER_1
        )
    )


def move_circuit(client: ApiClient, circuit_id: str, to_state: str) -> Dict[str, Any]:
    return get_success_data(
        client.set_circuit_state(circuit_id, f.state_payload(to_state), FACILITY_MANAGER)
    )


def approve_circuit(client: ApiClient, circuit_id: str) -> Dict[str, Any]:
    return move_circuit(client, circuit_id, "APPROVED")


def row_version(client: ApiClient, row_id: str) -> int:
    """The row's current `version`, which every energization must carry."""
    return get_success_data(client.get_row(row_id, FACILITY_MANAGER))["version"]


def contract_version(client: ApiClient, contract_id: str) -> int:
    """The contract's current `version`, which every cross-connect create must carry."""
    return get_success_data(client.get_contract(contract_id, BILLING_OPERATOR))["version"]


def energize_circuit(client: ApiClient, circuit_id: str, row_id: str) -> Dict[str, Any]:
    """Energize a circuit, re-reading the row so the version token is fresh."""
    return get_success_data(
        client.energize_circuit(
            circuit_id, {"expected_row_version": row_version(client, row_id)}, ENGINEER_1
        )
    )


def append_reading(
    client: ApiClient, circuit_id: str, interval_start: str, interval_end: str, kwh: float, peak_kw: float
) -> Dict[str, Any]:
    return get_success_data(
        client.append_meter_reading(
            circuit_id,
            f.meter_reading_payload(interval_start, interval_end, kwh, peak_kw),
            BILLING_OPERATOR,
        )
    )


def create_port(
    client: ApiClient, row_id: str, panel_code: str = "PP-A", port_number: int = 1, media_type: str = "SMF"
) -> Dict[str, Any]:
    return get_success_data(
        client.create_patch_panel_port(
            f.create_patch_panel_port_payload(
                row_id, panel_code=panel_code, port_number=port_number, media_type=media_type
            ),
            FACILITY_MANAGER,
        )
    )


def close_period(
    client: ApiClient, contract_id: str, period_start: str, period_end: str
) -> Dict[str, Any]:
    return get_success_data(
        client.close_billing_period(
            contract_id, f.billing_close_payload(period_start, period_end), BILLING_OPERATOR
        )
    )


def invoice_lines(client: ApiClient, contract_id: str, **params) -> List[Dict[str, Any]]:
    """Every ledger row raised against a contract, newest listing semantics aside."""
    query = {"contract_id": contract_id, "limit": 100}
    query.update(params)
    response = client.list_invoice_lines(BILLING_OPERATOR, params=query)
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Tier 2 — space: a contract with cabinets reserved and installed
# ---------------------------------------------------------------------------


def setup_customer_and_row(client: ApiClient, *, row: Optional[Dict] = None) -> Scenario:
    """A customer and one engineered row, with the clock pinned at its default."""
    set_clock(client)
    scenario = Scenario(customer=create_customer(client))
    scenario.rows.append(create_row(client, **(row or {})))
    return scenario


def setup_contract(
    client: ApiClient, *, row: Optional[Dict] = None, contract: Optional[Dict] = None
) -> Scenario:
    """A `DRAFT` contract under a customer, alongside one engineered row."""
    scenario = setup_customer_and_row(client, row=row)
    scenario.contracts.append(
        create_contract(client, scenario.customer_id, **(contract or {}))
    )
    return scenario


def setup_reserved_cabinet(
    client: ApiClient,
    *,
    row: Optional[Dict] = None,
    contract: Optional[Dict] = None,
    cabinet: Optional[Dict] = None,
) -> Scenario:
    """A `PENDING_ACTIVATION` contract holding one `RESERVED` cabinet.

    Reservation is what lets the contract activate at all, since activation requires
    at least one cabinet already bound to it.
    """
    scenario = setup_contract(client, row=row, contract=contract)
    move_contract(client, scenario.contract_id, "PENDING_ACTIVATION")
    cab = create_cabinet(client, scenario.row_id, **(cabinet or {}))
    reserve_cabinet(client, cab["id"], scenario.contract_id)
    scenario.cabinets.append(cab)
    return scenario


def setup_active_contract(
    client: ApiClient,
    *,
    row: Optional[Dict] = None,
    contract: Optional[Dict] = None,
    cabinet: Optional[Dict] = None,
) -> Scenario:
    """An `ACTIVE` contract whose single cabinet is still `RESERVED`."""
    scenario = setup_reserved_cabinet(client, row=row, contract=contract, cabinet=cabinet)
    move_contract(client, scenario.contract_id, "ACTIVE")
    return scenario


def setup_installed_cabinet(
    client: ApiClient,
    *,
    row: Optional[Dict] = None,
    contract: Optional[Dict] = None,
    cabinet: Optional[Dict] = None,
) -> Scenario:
    """An `ACTIVE` contract whose cabinet has reached `INSTALLED` — the state from
    which power may be energized."""
    scenario = setup_active_contract(client, row=row, contract=contract, cabinet=cabinet)
    move_cabinet(client, scenario.cabinet_id, "INSTALLED")
    return scenario


def add_installed_cabinet(
    client: ApiClient, scenario: Scenario, *, row_id: Optional[str] = None, **cabinet_overrides
) -> Dict[str, Any]:
    """A second (or third) cabinet reserved and installed against the same contract."""
    cab = create_cabinet(client, row_id or scenario.row_id, **cabinet_overrides)
    reserve_cabinet(client, cab["id"], scenario.contract_id)
    move_cabinet(client, cab["id"], "INSTALLED")
    scenario.cabinets.append(cab)
    return cab


def add_reserved_cabinet(
    client: ApiClient, scenario: Scenario, *, row_id: Optional[str] = None, **cabinet_overrides
) -> Dict[str, Any]:
    """A further cabinet left at `RESERVED`, which is the state a density cap holds."""
    cab = create_cabinet(client, row_id or scenario.row_id, **cabinet_overrides)
    reserve_cabinet(client, cab["id"], scenario.contract_id)
    scenario.cabinets.append(cab)
    return cab


# ---------------------------------------------------------------------------
# Tier 3 — power: approved and energized circuits
# ---------------------------------------------------------------------------


def add_approved_circuit(
    client: ApiClient, scenario: Scenario, *, cabinet_id: Optional[str] = None, **circuit_overrides
) -> Dict[str, Any]:
    circuit = create_circuit(client, cabinet_id or scenario.cabinet_id, **circuit_overrides)
    approve_circuit(client, circuit["id"])
    scenario.circuits.append(circuit)
    return circuit


def add_designed_circuit(
    client: ApiClient, scenario: Scenario, *, cabinet_id: Optional[str] = None, **circuit_overrides
) -> Dict[str, Any]:
    circuit = create_circuit(client, cabinet_id or scenario.cabinet_id, **circuit_overrides)
    scenario.circuits.append(circuit)
    return circuit


def setup_approved_circuit(
    client: ApiClient,
    *,
    row: Optional[Dict] = None,
    contract: Optional[Dict] = None,
    cabinet: Optional[Dict] = None,
    circuit: Optional[Dict] = None,
) -> Scenario:
    """An installed cabinet carrying one `APPROVED` circuit, ready to energize."""
    scenario = setup_installed_cabinet(client, row=row, contract=contract, cabinet=cabinet)
    add_approved_circuit(client, scenario, **(circuit or {}))
    return scenario


def setup_energized_cabinet(
    client: ApiClient,
    *,
    row: Optional[Dict] = None,
    contract: Optional[Dict] = None,
    cabinet: Optional[Dict] = None,
    circuit: Optional[Dict] = None,
) -> Scenario:
    """A cabinet driven all the way to `ACTIVE` by its first energized primary feed."""
    scenario = setup_approved_circuit(client, row=row, contract=contract, cabinet=cabinet, circuit=circuit)
    energize_circuit(client, scenario.circuit_id, scenario.row_id)
    return scenario


# ---------------------------------------------------------------------------
# Tier 3 — cross-connects
# ---------------------------------------------------------------------------


def setup_cross_connect_scenery(
    client: ApiClient,
    *,
    row: Optional[Dict] = None,
    contract: Optional[Dict] = None,
    port_pairs: int = 1,
    media_type: str = "SMF",
) -> Scenario:
    """Two installed cabinets on one row plus `port_pairs` free A-side and Z-side
    ports, and a contact holding the customer's authorization scopes.

    Because this chain reserves *two* cabinets against the one contract, the
    contract it raises must commit to at least two of them: PRD §3.3 caps the
    count of a contract's `RESERVED`/`CAPACITY_HELD`/`INSTALLED`/`ACTIVE`
    cabinets at `committed_cabinet_count` and refuses the excess with
    `ERR_CABINET_COMMIT_EXCEEDED`. The default contract commits to one, so the
    default is lifted here; an explicit caller override still wins."""
    contract = {"committed_cabinet_count": 2, **(contract or {})}
    scenario = setup_installed_cabinet(client, row=row, contract=contract, cabinet={"cabinet_code": "C01"})
    add_installed_cabinet(client, scenario, cabinet_code="C02")
    scenario.contacts.append(create_contact(client, scenario.customer_id))
    for number in range(1, port_pairs + 1):
        scenario.ports.append(
            create_port(client, scenario.row_id, "PP-A", number, media_type)
        )
    for number in range(1, port_pairs + 1):
        scenario.ports.append(
            create_port(client, scenario.row_id, "PP-Z", number, media_type)
        )
    return scenario


def a_ports(scenario: Scenario) -> List[Dict[str, Any]]:
    return [p for p in scenario.ports if p["panel_code"] == "PP-A"]


def z_ports(scenario: Scenario) -> List[Dict[str, Any]]:
    return [p for p in scenario.ports if p["panel_code"] == "PP-Z"]


def raise_cross_connect_order(
    client: ApiClient, scenario: Scenario, **overrides
) -> Dict[str, Any]:
    """A `SUBMITTED` cross-connect order, carrying a freshly read contract version."""
    payload = f.create_cross_connect_order_payload(
        scenario.contract_id,
        scenario.contact["id"],
        scenario.cabinets[0]["id"],
        scenario.cabinets[1]["id"],
        contract_version(client, scenario.contract_id),
        **overrides,
    )
    order = get_success_data(client.create_cross_connect_order(payload, ENGINEER_1))
    scenario.orders.append(order)
    return order


def propose_route(
    client: ApiClient,
    order_id: str,
    a_end_port_id: str,
    z_end_port_id: str,
    path_hops: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.propose_route(
            order_id, f.propose_route_payload(a_end_port_id, z_end_port_id, path_hops), ENGINEER_1
        )
    )


def setup_routed_order(
    client: ApiClient,
    *,
    row: Optional[Dict] = None,
    contract: Optional[Dict] = None,
    port_pairs: int = 1,
    media_type: str = "SMF",
) -> Scenario:
    """A cross-connect order in `ROUTE_PROPOSED` with its first port pair reserved."""
    scenario = setup_cross_connect_scenery(
        client, row=row, contract=contract, port_pairs=port_pairs, media_type=media_type
    )
    order = raise_cross_connect_order(client, scenario, cable_type=media_type)
    propose_route(client, order["id"], a_ports(scenario)[0]["id"], z_ports(scenario)[0]["id"])
    return scenario


def move_order(client: ApiClient, order_id: str, to_state: str, headers=None) -> Dict[str, Any]:
    """Drive a cross-connect order's lifecycle. Approval is performed by a manager,
    never by the engineer who raised the order."""
    return get_success_data(
        client.set_cross_connect_order_state(
            order_id, f.state_payload(to_state), headers or FACILITY_MANAGER
        )
    )


def setup_active_cross_connect(
    client: ApiClient,
    *,
    row: Optional[Dict] = None,
    contract: Optional[Dict] = None,
    port_pairs: int = 1,
    media_type: str = "SMF",
) -> Scenario:
    """A cross-connect carried all the way to `ACTIVE`, which is what a monthly
    close bills for and what a decommission later tears down."""
    scenario = setup_routed_order(
        client, row=row, contract=contract, port_pairs=port_pairs, media_type=media_type
    )
    order_id = scenario.order["id"]
    move_order(client, order_id, "APPROVED")
    move_order(client, order_id, "INSTALLED")
    move_order(client, order_id, "ACTIVE")
    return scenario


def add_active_cross_connect(
    client: ApiClient, scenario: Scenario, *, a_port: Dict[str, Any], z_port: Dict[str, Any], media_type: str = "SMF"
) -> Dict[str, Any]:
    """A further cross-connect on the same contract, driven to `ACTIVE`."""
    order = raise_cross_connect_order(client, scenario, cable_type=media_type)
    propose_route(client, order["id"], a_port["id"], z_port["id"])
    move_order(client, order["id"], "APPROVED")
    move_order(client, order["id"], "INSTALLED")
    move_order(client, order["id"], "ACTIVE")
    return order


# ---------------------------------------------------------------------------
# Tier 3 — remote hands
# ---------------------------------------------------------------------------


def setup_ticket_scenery(
    client: ApiClient,
    *,
    row: Optional[Dict] = None,
    contract: Optional[Dict] = None,
    cabinet: Optional[Dict] = None,
) -> Scenario:
    """An installed cabinet plus two contacts holding `REMOTE_HANDS`: one to request
    the work and a second, different one to authorize it."""
    scenario = setup_installed_cabinet(client, row=row, contract=contract, cabinet=cabinet)
    scenario.contacts.append(
        create_contact(client, scenario.customer_id, authorization_scopes=["REMOTE_HANDS"])
    )
    scenario.contacts.append(
        create_contact(client, scenario.customer_id, authorization_scopes=["REMOTE_HANDS"])
    )
    return scenario


def raise_ticket(client: ApiClient, scenario: Scenario, **overrides) -> Dict[str, Any]:
    payload = f.create_remote_hands_ticket_payload(
        scenario.contract_id, scenario.contacts[0]["id"], scenario.cabinet_id, **overrides
    )
    ticket = get_success_data(client.create_remote_hands_ticket(payload, ENGINEER_1))
    scenario.tickets.append(ticket)
    return ticket


def authorize_ticket(
    client: ApiClient, ticket_id: str, authorizing_contact_id: str, to_state: str = "AUTHORIZED"
) -> Dict[str, Any]:
    return get_success_data(
        client.set_ticket_authorization(
            ticket_id,
            f.state_payload(to_state, authorizing_contact_id=authorizing_contact_id),
            SECURITY_OFFICER,
        )
    )


def dispatch_ticket(client: ApiClient, ticket_id: str) -> Dict[str, Any]:
    return get_success_data(client.dispatch_ticket(ticket_id, ENGINEER_2))


def complete_ticket(client: ApiClient, ticket_id: str, *segments: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(
        client.complete_ticket(ticket_id, f.complete_ticket_payload(*segments), ENGINEER_2)
    )


def setup_authorized_ticket(
    client: ApiClient,
    *,
    row: Optional[Dict] = None,
    contract: Optional[Dict] = None,
    cabinet: Optional[Dict] = None,
    **ticket_overrides,
) -> Scenario:
    """A ticket whose authorization dimension has reached `AUTHORIZED`, authorized by
    a contact other than the one that requested it."""
    scenario = setup_ticket_scenery(client, row=row, contract=contract, cabinet=cabinet)
    ticket = raise_ticket(client, scenario, **ticket_overrides)
    authorize_ticket(client, ticket["id"], scenario.contacts[1]["id"])
    return scenario


def setup_dispatched_ticket(
    client: ApiClient,
    *,
    row: Optional[Dict] = None,
    contract: Optional[Dict] = None,
    cabinet: Optional[Dict] = None,
    **ticket_overrides,
) -> Scenario:
    """An authorized ticket whose execution dimension has reached `DISPATCHED`."""
    scenario = setup_authorized_ticket(
        client, row=row, contract=contract, cabinet=cabinet, **ticket_overrides
    )
    dispatch_ticket(client, scenario.ticket["id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 3 — site access
# ---------------------------------------------------------------------------


def setup_visit_scenery(
    client: ApiClient,
    *,
    row: Optional[Dict] = None,
    contract: Optional[Dict] = None,
    cabinet: Optional[Dict] = None,
    access_level: str = "UNESCORTED",
    enrolled: bool = True,
) -> Scenario:
    """An installed cabinet plus a contact holding `SITE_ACCESS`, enrolled by default
    because entering the hall requires enrollment even though scheduling does not."""
    scenario = setup_installed_cabinet(client, row=row, contract=contract, cabinet=cabinet)
    contact = create_contact(
        client,
        scenario.customer_id,
        authorization_scopes=["SITE_ACCESS"],
        access_level=access_level,
    )
    if enrolled:
        contact = enroll_contact(client, contact["id"])
    scenario.contacts.append(contact)
    return scenario


def schedule_visit(
    client: ApiClient,
    scenario: Scenario,
    window_start: str,
    window_end: str,
    *,
    cabinet_id: Optional[str] = None,
    contact_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload = f.create_access_visit_payload(
        scenario.contract_id,
        contact_id or scenario.contacts[0]["id"],
        cabinet_id or scenario.cabinet_id,
        window_start,
        window_end,
        **overrides,
    )
    visit = get_success_data(client.create_access_visit(payload, SECURITY_OFFICER))
    scenario.visits.append(visit)
    return visit


def move_visit(client: ApiClient, visit_id: str, to_state: str, **extra) -> Dict[str, Any]:
    return get_success_data(
        client.set_access_visit_state(visit_id, f.state_payload(to_state, **extra), SECURITY_OFFICER)
    )


# ---------------------------------------------------------------------------
# Tier 4 — decommissioning
# ---------------------------------------------------------------------------


def raise_decommission_order(
    client: ApiClient, scenario: Scenario, *, cabinet_id: Optional[str] = None, contact_id: Optional[str] = None
) -> Dict[str, Any]:
    payload = f.create_decommission_order_payload(
        scenario.contract_id,
        cabinet_id or scenario.cabinet_id,
        contact_id or scenario.contacts[0]["id"],
    )
    order = get_success_data(client.create_decommission_order(payload, ENGINEER_1))
    scenario.decommissions.append(order)
    return order


def move_decommission(client: ApiClient, order_id: str, to_state: str) -> Dict[str, Any]:
    """Approval is a manager's act and must not be performed by the order's creator."""
    return get_success_data(
        client.set_decommission_order_state(order_id, f.state_payload(to_state), FACILITY_MANAGER)
    )


def record_step(client: ApiClient, order_id: str, step_code: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        client.record_decommission_step(order_id, {"step_code": step_code}, headers or ENGINEER_1)
    )


def setup_decommission_ready_for_release(
    client: ApiClient,
    *,
    row: Optional[Dict] = None,
    contract: Optional[Dict] = None,
    media_type: str = "SMF",
) -> Scenario:
    """A cabinet carrying an `ACTIVE` cross-connect and an energized circuit, with its
    decommission order joined at `READY_FOR_RELEASE`: both physical steps recorded by
    two different engineers, awaiting only port release."""
    scenario = setup_active_cross_connect(client, row=row, contract=contract, media_type=media_type)
    add_approved_circuit(client, scenario, cabinet_id=scenario.cabinets[0]["id"])
    energize_circuit(client, scenario.circuit_id, scenario.row_id)
    order = raise_decommission_order(client, scenario, cabinet_id=scenario.cabinets[0]["id"])
    move_decommission(client, order["id"], "APPROVED")
    record_step(client, order["id"], "EQUIPMENT_REMOVAL", ENGINEER_1)
    record_step(client, order["id"], "CABLE_RECLAMATION", ENGINEER_2)
    return scenario


def release_ports(client: ApiClient, order_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(client.release_ports(order_id, headers or ENGINEER_1))


# ---------------------------------------------------------------------------
# Re-reads
# ---------------------------------------------------------------------------


def read_row(client: ApiClient, row_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_row(row_id, FACILITY_MANAGER))


def read_cabinet(client: ApiClient, cabinet_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_cabinet(cabinet_id, FACILITY_MANAGER))


def read_circuit(client: ApiClient, circuit_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_power_circuit(circuit_id, ENGINEER_1))


def read_contract(client: ApiClient, contract_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_contract(contract_id, BILLING_OPERATOR))


def read_port(client: ApiClient, port_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_patch_panel_port(port_id, FACILITY_MANAGER))


def read_order(client: ApiClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_cross_connect_order(order_id, ENGINEER_1))


def read_ticket(client: ApiClient, ticket_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_remote_hands_ticket(ticket_id, ENGINEER_1))


def read_visit(client: ApiClient, visit_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_access_visit(visit_id, SECURITY_OFFICER))


def read_contact(client: ApiClient, contact_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_contact(contact_id, SECURITY_OFFICER))


def read_decommission(client: ApiClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_decommission_order(order_id, ENGINEER_1))
