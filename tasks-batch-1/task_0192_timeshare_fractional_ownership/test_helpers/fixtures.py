"""Composite setup helpers.

These encapsulate the multi-step preambles that most test claims require so the
tests themselves can focus on assertions. Every helper builds its preconditions
from scratch using only PRD-declared endpoints (the database is empty before
each test). Setup calls use get_success_data() so setup failures surface clearly.

Identity threading: the Owner role is entity_backed, so any ownership-gated call
uses make_owner_headers(owner["id"]) with the real Owner.id, never the shared
fallback constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_owner_headers
from .factories import (
    create_resort_payload,
    create_owner_payload,
    create_inventory_unit_payload,
    create_contract_payload,
    create_reservation_payload,
    create_invoice_payload,
    set_clock_payload,
)

_RM = TEST_USERS["resort_manager_headers"]
_RA = TEST_USERS["resale_agent_headers"]
_CO = TEST_USERS["compliance_officer_headers"]

# Canonical clock anchors used across fixtures.
CLOCK_SIGN = "2026-01-01T00:00:00Z"      # contract signed here
CLOCK_AFTER_RESCISSION = "2026-01-08T00:00:00Z"  # 7 days later -> window elapsed
CLOCK_PAST_GRACE = "2026-03-10T00:00:00Z"        # past due_date(2026-02-01)+30d grace
DEFAULT_DUE_DATE = "2026-02-01T00:00:00Z"


# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #
def set_clock(resort_id, to_iso8601):
    return get_success_data(api_client.set_clock(set_clock_payload(resort_id, to_iso8601), _RM))


def create_resort(**overrides):
    """Create a resort and anchor its clock at CLOCK_SIGN (2026-01-01)."""
    resort = get_success_data(api_client.create_resort(create_resort_payload(**overrides), _RM))
    set_clock(resort["id"], CLOCK_SIGN)
    return resort


def create_owner(resort_id, **overrides):
    return get_success_data(api_client.create_owner(create_owner_payload(resort_id, **overrides), _RM))


def create_inventory_unit(resort_id, **overrides):
    return get_success_data(
        api_client.create_inventory_unit(create_inventory_unit_payload(resort_id, **overrides), _RM)
    )


def create_contract(resort_id, owner_id, **overrides):
    """Create a PENDING_RESCISSION contract (signed at the resort clock)."""
    return get_success_data(
        api_client.create_contract(create_contract_payload(resort_id, owner_id, **overrides), _RM)
    )


def get_points_account(contract_id, use_year, owner_id):
    """Read the contract's PointsAccount for use_year as its owning Owner."""
    headers = make_owner_headers(owner_id)
    data, _meta = _list(api_client.list_points_accounts(
        headers, params={"contract_id": contract_id, "use_year": use_year}))
    assert data, f"no PointsAccount for contract {contract_id} use_year {use_year}"
    return data[0]


def _list(response):
    """Return (data_list, meta) from a list response, lenient on 2xx."""
    body = response.json()
    return body["data"], body.get("meta", {})


# --------------------------------------------------------------------------- #
# Tier 1 — State progression
# --------------------------------------------------------------------------- #
def create_active_contract(resort_id, owner_id, **contract_overrides):
    """Create a contract then activate it (advancing the clock past the 7-day
    rescission window). Returns the activated Contract.

    Re-anchors the resort clock to CLOCK_SIGN *before* creating the contract so
    that the contract's `signed_at` is deterministically CLOCK_SIGN even when this
    helper is called more than once on the same resort (a prior call leaves the
    clock at CLOCK_AFTER_RESCISSION, which would otherwise stamp the next
    contract's `signed_at` at that later instant and make activation fail with
    ERR_RESCISSION_WINDOW_OPEN). The clock is left at CLOCK_AFTER_RESCISSION on
    return, matching the post-condition every caller relies on."""
    set_clock(resort_id, CLOCK_SIGN)
    contract = create_contract(resort_id, owner_id, **contract_overrides)
    set_clock(resort_id, CLOCK_AFTER_RESCISSION)
    activated = get_success_data(api_client.activate_contract(contract["id"], _RM))
    return activated


# --------------------------------------------------------------------------- #
# Tier 2 — Entity hierarchy
# --------------------------------------------------------------------------- #
def setup_resort_owner_active_contract(contract_overrides=None, resort_overrides=None):
    """Resort + Owner + one ACTIVE DEEDED POINTS contract.

    Returns (resort, owner, contract). Clock left at CLOCK_AFTER_RESCISSION."""
    resort = create_resort(**(resort_overrides or {}))
    owner = create_owner(resort["id"])
    contract = create_active_contract(resort["id"], owner["id"], **(contract_overrides or {}))
    return resort, owner, contract


def setup_active_contract_with_unit(season="GOLD", week_number=10,
                                    contract_overrides=None, resort_overrides=None):
    """Resort + Owner + ACTIVE contract + one AVAILABLE InventoryUnit.

    Returns (resort, owner, contract, unit)."""
    resort = create_resort(**(resort_overrides or {}))
    owner = create_owner(resort["id"])
    unit = create_inventory_unit(resort["id"], season=season, week_number=week_number)
    contract = create_active_contract(resort["id"], owner["id"], **(contract_overrides or {}))
    return resort, owner, contract, unit


# --------------------------------------------------------------------------- #
# Tier 3 — Reservation lifecycle shortcuts
# --------------------------------------------------------------------------- #
def create_held_reservation(resort, owner, contract, unit, use_year=2026, **resv_overrides):
    """Create a HELD reservation on `unit` funded by the contract's use_year
    account. Reads the account version fresh for OCC. Returns the Reservation."""
    acct = get_points_account(contract["id"], use_year, owner["id"])
    headers = make_owner_headers(owner["id"])
    payload = create_reservation_payload(
        contract["id"], unit["id"], use_year, acct["version"], **resv_overrides)
    return get_success_data(api_client.create_reservation(payload, headers))


def create_confirmed_reservation(resort, owner, contract, unit, use_year=2026):
    """Create + confirm a reservation. Returns the CONFIRMED Reservation."""
    resv = create_held_reservation(resort, owner, contract, unit, use_year=use_year)
    headers = make_owner_headers(owner["id"])
    return get_success_data(api_client.confirm_reservation(resv["id"], headers))


def create_deposited_reservation(resort, owner, contract, unit, exchange_network="RCI",
                                 use_year=2026):
    """Create + confirm + deposit-exchange. Returns (reservation, deposit)."""
    resv = create_confirmed_reservation(resort, owner, contract, unit, use_year=use_year)
    headers = make_owner_headers(owner["id"])
    deposit = get_success_data(
        api_client.deposit_exchange(resv["id"], {"exchange_network": exchange_network}, headers)
    )
    return resv, deposit


# --------------------------------------------------------------------------- #
# Tier 4 — Billing / delinquency progression
# --------------------------------------------------------------------------- #
def create_issued_invoice(resort, contract, use_year=2026, due_date=DEFAULT_DUE_DATE,
                          **invoice_overrides):
    """Create a DRAFT ANNUAL invoice and issue it. Returns the ISSUED invoice."""
    inv = get_success_data(api_client.create_invoice(
        create_invoice_payload(contract["id"], use_year, due_date, **invoice_overrides), _RM))
    return get_success_data(api_client.issue_invoice(inv["id"], _RM))


def setup_delinquent_case(resort_overrides=None, contract_overrides=None,
                          invoice_use_year=2026):
    """Full chain to an open DelinquencyCase in NOTICE.

    Resort + Owner + ACTIVE contract + ISSUED ANNUAL invoice (200000 cents on a
    10000-pt allotment) -> advance clock past grace -> mark-delinquent (opens a
    NOTICE case). Returns (resort, owner, contract, invoice, case)."""
    overrides = {"annual_points_allotment": 10000}
    overrides.update(contract_overrides or {})
    resort, owner, contract = setup_resort_owner_active_contract(
        contract_overrides=overrides, resort_overrides=resort_overrides)
    invoice = create_issued_invoice(resort, contract, use_year=invoice_use_year)
    set_clock(resort["id"], CLOCK_PAST_GRACE)
    get_success_data(api_client.mark_invoice_delinquent(invoice["id"], _RM))
    case = _get_case_for_contract(contract["id"])
    return resort, owner, contract, invoice, case


def setup_lien_case(escalations=1, resort_overrides=None, contract_overrides=None):
    """setup_delinquent_case then escalate `escalations` times -> case in LIEN,
    contract SUSPENDED. Returns (resort, owner, contract, invoice, case)."""
    resort, owner, contract, invoice, case = setup_delinquent_case(
        resort_overrides=resort_overrides, contract_overrides=contract_overrides)
    for _ in range(escalations):
        get_success_data(api_client.escalate_delinquency_case(case["id"], _CO))
    case = get_success_data(api_client.get_delinquency_case(case["id"], _CO))
    return resort, owner, contract, invoice, case


def _get_case_for_contract(contract_id):
    data, _meta = _list(api_client.list_delinquency_cases(_CO, params={"contract_id": contract_id}))
    assert data, f"no DelinquencyCase for contract {contract_id}"
    return data[0]


def get_special_assessment_invoice(contract_id, assessment_id):
    """Fetch the SPECIAL_ASSESSMENT invoice a levy spawned for a contract."""
    data, _meta = _list(api_client.list_invoices(
        _RM, params={"contract_id": contract_id, "special_assessment_id": assessment_id}))
    assert data, f"no SPECIAL_ASSESSMENT invoice for contract {contract_id}"
    return data[0]


def get_annual_invoice(contract_id, use_year):
    """Fetch a contract's ANNUAL invoice for a use_year (first match)."""
    data, _meta = _list(api_client.list_invoices(
        _RM, params={"contract_id": contract_id, "use_year": use_year}))
    annuals = [i for i in data if i["source_type"] == "ANNUAL"]
    assert annuals, f"no ANNUAL invoice for contract {contract_id} use_year {use_year}"
    return annuals[0]


# --------------------------------------------------------------------------- #
# Convenience role headers re-export for tests
# --------------------------------------------------------------------------- #
RESORT_MANAGER = _RM
RESALE_AGENT = _RA
COMPLIANCE_OFFICER = _CO
