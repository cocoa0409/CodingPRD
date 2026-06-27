"""Composite setup helpers for the ATM Cash Logistics API.

Every fixture builds its preconditions from scratch via PRD-declared endpoints, using
get_success_data() (lenient) so setup failures surface as clear "Setup failed" errors.
The database is empty at the start of every test (the runner restarts the server per test),
so fixtures never assume pre-existing entities.

All five roles are opaque. The only X-User-ID that re-enters business logic is the FieldTech's
on service-ticket ownership, so ticket fixtures thread explicit tech ids.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_site_merchant_payload,
    create_vault_payload,
    create_route_payload,
    create_location_payload,
    create_atm_payload,
    create_cassette_payload,
    create_transaction_payload,
    create_replenishment_order_payload,
    create_cash_count_payload,
    create_service_ticket_payload,
    create_fee_disclosure_payload,
    create_settlement_run_payload,
    unique_serial,
)
from .test_users import (
    make_platform_admin_headers,
    make_vault_controller_headers,
    make_field_tech_headers,
    make_settlement_officer_headers,
    make_compliance_officer_headers,
    TECH_T1,
)

ADMIN = make_platform_admin_headers()
VAULT = make_vault_controller_headers()
TECH = make_field_tech_headers()
SETTLE = make_settlement_officer_headers()
COMPLIANCE = make_compliance_officer_headers()


# --- Tier 0: logical clock + seeders ---

def set_clock(to_iso8601: str):
    """Advance the server logical clock (PRD §3.12). PlatformAdmin-only."""
    return get_success_data(api_client.set_clock(to_iso8601, headers=ADMIN))


def seed_monthly_wd_count(atm_id: str, monthly_wd_count: int):
    """Seed an ATM's current-month withdrawal count (PRD §3.12). The next WITHDRAWAL gets
    monthly_seq = monthly_wd_count + 1."""
    return get_success_data(
        api_client.inject_monthly_wd_count(atm_id, monthly_wd_count, headers=ADMIN))


# --- Tier 1: provisioning primitives ---

def create_vault(provisioned_cents=100_000_000, **overrides) -> dict:
    """Create a vault. Returns the vault dict (balance_cents == provisioned_cents, version 1)."""
    payload = create_vault_payload(provisioned_cents=provisioned_cents, **overrides)
    return get_success_data(api_client.create_vault(payload, headers=ADMIN))


def create_route(vault_id, **overrides) -> dict:
    """Create an ACTIVE armored route bound to a vault."""
    return get_success_data(
        api_client.create_route(create_route_payload(vault_id, **overrides), headers=ADMIN))


def create_site_merchant(**overrides) -> dict:
    """Create a site-merchant commission contract (defaults ACTIVE / GREATER_OF)."""
    return get_success_data(
        api_client.create_site_merchant(create_site_merchant_payload(**overrides), headers=ADMIN))


def create_location(site_merchant_id, route_id, **overrides) -> dict:
    """Create a host location bound to a merchant and route."""
    return get_success_data(api_client.create_location(
        create_location_payload(site_merchant_id, route_id, **overrides), headers=ADMIN))


def create_atm(location_id, **overrides) -> dict:
    """Provision an ATM at a location (IN_SERVICE / EMPTY)."""
    return get_success_data(
        api_client.create_atm(create_atm_payload(location_id, **overrides), headers=ADMIN))


def create_cassette(atm_id, position="C1", **overrides) -> dict:
    """Add a cassette slot to an ATM."""
    return get_success_data(api_client.create_cassette(
        atm_id, create_cassette_payload(position=position, **overrides), headers=ADMIN))


# --- Tier 2: base network scenario (the dominant shared prefix) ---

def provision_network(
    *,
    provisioned_cents=100_000_000,
    jurisdiction_code="CA",
    surcharge_cents=250,
    note_denomination_cents=2000,
    merchant_overrides=None,
    atm_overrides=None,
):
    """Vault + route + merchant + location + one ATM. The shared prefix of almost every chain.

    Returns a dict with keys: vault, route, merchant, location, atm.
    The vault dict carries the live version (1) for the first dispatch's expected_vault_version.
    """
    vault = create_vault(provisioned_cents=provisioned_cents)
    route = create_route(vault["id"])
    merchant = create_site_merchant(**(merchant_overrides or {}))
    location = create_location(merchant["id"], route["id"], jurisdiction_code=jurisdiction_code)
    atm_kwargs = {"surcharge_cents": surcharge_cents,
                  "note_denomination_cents": note_denomination_cents}
    atm_kwargs.update(atm_overrides or {})
    atm = create_atm(location["id"], **atm_kwargs)
    return {
        "vault": vault,
        "route": route,
        "merchant": merchant,
        "location": location,
        "atm": atm,
    }


# --- Tier 3: fee-disclosure / compliance gate ---

def draft_fee_disclosure(atm_id, disclosed_surcharge_cents, ack_text_present=True, **overrides) -> dict:
    """Draft a fee disclosure for an ATM (DRAFT)."""
    return get_success_data(api_client.create_fee_disclosure(
        atm_id,
        create_fee_disclosure_payload(
            disclosed_surcharge_cents, ack_text_present=ack_text_present, **overrides),
        headers=COMPLIANCE))


def approve_fee_disclosure_for_atm(atm_id, surcharge_cents) -> dict:
    """Draft + approve a matching fee disclosure, arming the ATM. Returns the APPROVED disclosure."""
    fd = draft_fee_disclosure(atm_id, surcharge_cents, ack_text_present=True)
    return get_success_data(api_client.approve_fee_disclosure(fd["id"], headers=COMPLIANCE))


def provision_armed_atm(
    *,
    surcharge_cents=295,
    jurisdiction_code="CA",
    note_denomination_cents=2000,
    provisioned_cents=100_000_000,
    merchant_overrides=None,
):
    """Base network + an APPROVED fee disclosure on the ATM (machine armed for live revenue).

    Returns the base-network dict plus key 'fee_disclosure'.
    """
    net = provision_network(
        provisioned_cents=provisioned_cents,
        jurisdiction_code=jurisdiction_code,
        surcharge_cents=surcharge_cents,
        note_denomination_cents=note_denomination_cents,
        merchant_overrides=merchant_overrides,
    )
    net["fee_disclosure"] = approve_fee_disclosure_for_atm(net["atm"]["id"], surcharge_cents)
    return net


# --- Tier 4: replenishment lifecycle ---

def schedule_order(atm_id, route_id, **overrides) -> dict:
    """Create a SCHEDULED replenishment order."""
    return get_success_data(api_client.create_replenishment_order(
        create_replenishment_order_payload(atm_id, route_id, **overrides), headers=VAULT))


def dispatch_order(order_id, expected_vault_version) -> dict:
    """Dispatch a SCHEDULED order with the given OCC token. Returns the DISPATCHED order."""
    return get_success_data(api_client.dispatch_order(
        order_id, {"expected_vault_version": expected_vault_version}, headers=VAULT))


def schedule_and_dispatch_order(atm_id, route_id, vault_id, **overrides) -> dict:
    """Schedule then dispatch an order. Reads the vault for the live version. Returns DISPATCHED order."""
    order = schedule_order(atm_id, route_id, **overrides)
    vault = get_success_data(api_client.get_vault(vault_id, headers=VAULT))
    return dispatch_order(order["id"], vault["version"])


def confirm_load_order(order_id) -> dict:
    """Confirm-load a DISPATCHED order (DISPATCHED -> LOADED). Returns the LOADED order."""
    return get_success_data(api_client.confirm_load(order_id, headers=TECH))


def setup_loaded_atm(
    *,
    order_amount_cents=200_000,
    surcharge_cents=250,
    jurisdiction_code="CA",
    note_denomination_cents=2000,
    with_fee_disclosure=False,
    cassette_positions=("C1",),
):
    """Base network + cassettes + a dispatched+loaded replenishment order.

    Returns base-network dict plus keys 'order' (LOADED) and 'cassettes' (list).
    The ATM ends in cash_status LOADED with order_amount_cents resident.
    """
    if with_fee_disclosure:
        net = provision_armed_atm(
            surcharge_cents=surcharge_cents,
            jurisdiction_code=jurisdiction_code,
            note_denomination_cents=note_denomination_cents,
        )
    else:
        net = provision_network(
            jurisdiction_code=jurisdiction_code,
            surcharge_cents=surcharge_cents,
            note_denomination_cents=note_denomination_cents,
        )
    cassettes = [create_cassette(net["atm"]["id"], position=p) for p in cassette_positions]
    order = schedule_and_dispatch_order(
        net["atm"]["id"], net["route"]["id"], net["vault"]["id"],
        order_amount_cents=order_amount_cents)
    order = confirm_load_order(order["id"])
    net["order"] = order
    net["cassettes"] = cassettes
    return net


# --- Tier 5: transactions ---

def post_withdrawal(atm_id, amount_cents=2000) -> dict:
    """Post a WITHDRAWAL transaction. Returns the transaction dict."""
    return get_success_data(api_client.create_transaction(
        atm_id, create_transaction_payload("WITHDRAWAL", amount_cents=amount_cents), headers=TECH))


def post_balance_inquiry(atm_id) -> dict:
    """Post a BALANCE_INQUIRY transaction. Returns the transaction dict."""
    return get_success_data(api_client.create_transaction(
        atm_id, create_transaction_payload("BALANCE_INQUIRY"), headers=TECH))


def post_n_withdrawals(atm_id, n, amount_cents=2000):
    """Post n WITHDRAWAL transactions. Returns the list of transaction dicts."""
    return [post_withdrawal(atm_id, amount_cents) for _ in range(n)]


def setup_armed_atm_with_withdrawals(
    *,
    surcharge_cents=295,
    jurisdiction_code="CA",
    seed_count=None,
    num_withdrawals=5,
    num_balance_inquiries=0,
    withdrawal_amount=2000,
    clock=None,
    merchant_overrides=None,
):
    """Armed ATM (approved fee disclosure) + optional monthly_wd_count seed + N withdrawals.

    The seeder is applied before posting so the first withdrawal's monthly_seq is seed_count+1.
    Returns base-network dict (with 'fee_disclosure') plus 'withdrawals' and 'balance_inquiries'.
    """
    net = provision_armed_atm(
        surcharge_cents=surcharge_cents,
        jurisdiction_code=jurisdiction_code,
        merchant_overrides=merchant_overrides,
    )
    if seed_count is not None:
        seed_monthly_wd_count(net["atm"]["id"], seed_count)
    if clock is not None:
        set_clock(clock)
    net["withdrawals"] = post_n_withdrawals(
        net["atm"]["id"], num_withdrawals, amount_cents=withdrawal_amount)
    net["balance_inquiries"] = [post_balance_inquiry(net["atm"]["id"])
                                for _ in range(num_balance_inquiries)]
    return net


# --- Tier 6: settlement / commission ---

def create_settlement_run(atm_id, **overrides) -> dict:
    """Create a DRAFT settlement run over the given window (defaults the whole of Jan 2026)."""
    return get_success_data(api_client.create_settlement_run(
        create_settlement_run_payload(atm_id, **overrides), headers=SETTLE))


def settle_run(run_id) -> dict:
    """Settle a DRAFT run (DRAFT -> SETTLED). Returns the settled run with computed revenue."""
    return get_success_data(api_client.settle_run(run_id, headers=SETTLE))


def get_commission_statement_for_run(run_id) -> dict:
    """Fetch the single commission statement generated by a settled run."""
    data, _ = _list_data(api_client.list_commission_statements(
        headers=SETTLE, params={"settlement_run_id": run_id}))
    assert data, f"Setup failed: no commission statement for run {run_id}"
    return data[0]


def settle_atm_window(atm_id, **window_overrides):
    """Create + settle a run for an ATM. Returns (settled_run, commission_statement)."""
    run = create_settlement_run(atm_id, **window_overrides)
    settled = settle_run(run["id"])
    statement = get_commission_statement_for_run(run["id"])
    return settled, statement


# --- Tier 7: service tickets ---

def open_ticket(atm_id, fault_kind="CASH_JAM", severity="MINOR") -> dict:
    """Open a service ticket (OPEN). Severity drives ATM operational_status."""
    return get_success_data(api_client.create_service_ticket(
        create_service_ticket_payload(atm_id, fault_kind=fault_kind, severity=severity),
        headers=TECH))


def acknowledge_ticket_as(ticket_id, tech_id=TECH_T1) -> dict:
    """Acknowledge a ticket as a specific FieldTech (records assigned_tech_id)."""
    return get_success_data(api_client.acknowledge_ticket(
        ticket_id, headers=make_field_tech_headers(tech_id)))


def resolve_ticket_as(ticket_id, tech_id=TECH_T1) -> dict:
    """Resolve a ticket as a specific FieldTech."""
    return get_success_data(api_client.resolve_ticket(
        ticket_id, headers=make_field_tech_headers(tech_id)))


def setup_resolved_ticket(atm_id=None, fault_kind="CASH_JAM", severity="MINOR", tech_id=TECH_T1):
    """An ATM with one ticket acknowledged + resolved by tech_id (ATM back to IN_SERVICE).

    If atm_id is None a fresh base network is provisioned. Returns (atm_id, ticket_dict).
    """
    if atm_id is None:
        atm_id = provision_network()["atm"]["id"]
    ticket = open_ticket(atm_id, fault_kind=fault_kind, severity=severity)
    acknowledge_ticket_as(ticket["id"], tech_id)
    ticket = resolve_ticket_as(ticket["id"], tech_id)
    return atm_id, ticket


# --- helpers ---

def _list_data(response):
    """Return (data_list, meta) from a list response without strict envelope checks (setup-only)."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})


def read_vault(vault_id) -> dict:
    return get_success_data(api_client.get_vault(vault_id, headers=VAULT))


def read_atm(atm_id) -> dict:
    return get_success_data(api_client.get_atm(atm_id, headers=ADMIN))


def read_order(order_id) -> dict:
    return get_success_data(api_client.get_replenishment_order(order_id, headers=VAULT))
