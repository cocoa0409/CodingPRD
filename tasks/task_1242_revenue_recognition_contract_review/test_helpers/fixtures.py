"""Composite setup helpers.

Encapsulate the multi-step setup sequences (clock, periods, SSP master data,
customer, contract lifecycle walk) so tests can focus on assertions. All
helpers build preconditions from scratch using only PRD-declared endpoints and
use get_success_data() so setup failures surface as clear "Setup failed"
errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_customer_payload, create_contract_payload, create_pob_payload,
    create_ssp_price_payload, create_accounting_period_payload,
)
from .test_users import TEST_USERS

ACCT = TEST_USERS["accountant_headers"]
MGR = TEST_USERS["manager_headers"]
REV = TEST_USERS["reviewer_headers"]
CTRL = TEST_USERS["controller_headers"]
ADMIN = TEST_USERS["admin_headers"]

# Full-year SSP window covering every signed_date used in tests.
FULL_YEAR_FROM = "2026-01-01"
FULL_YEAR_TO = "2026-12-31"


def set_clock(to_iso8601="2026-06-15T00:00:00Z"):
    """Move the logical clock (PRD §2.5). Returns the clock payload."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(resp)


def create_customer(**overrides):
    """Register a customer (PRD §3.1)."""
    resp = api_client.create_customer(create_customer_payload(**overrides), ACCT)
    return get_success_data(resp)


def create_contract(customer_id, **overrides):
    """Open a contract in DRAFT (PRD §3.1)."""
    resp = api_client.create_contract(create_contract_payload(customer_id, **overrides), ACCT)
    return get_success_data(resp)


def create_ssp(product_code, region="US", ssp_cents=100000,
               effective_from=FULL_YEAR_FROM, effective_to=FULL_YEAR_TO):
    """Create an ACTIVE price-book record (PRD §3.3)."""
    payload = create_ssp_price_payload(
        product_code=product_code, region=region, ssp_cents=ssp_cents,
        effective_from=effective_from, effective_to=effective_to,
    )
    resp = api_client.create_ssp_price(payload, MGR)
    return get_success_data(resp)


def create_period(period_code="2026-06", start_date="2026-06-01", end_date="2026-07-01"):
    """Create an OPEN accounting period (PRD §3.9)."""
    payload = create_accounting_period_payload(
        period_code=period_code, start_date=start_date, end_date=end_date
    )
    resp = api_client.create_accounting_period(payload, CTRL)
    return get_success_data(resp)


def add_pob(contract_id, **overrides):
    """Add a performance obligation to a DRAFT/CHANGES_REQUESTED contract (PRD §3.3)."""
    resp = api_client.create_pob(contract_id, create_pob_payload(**overrides), ACCT)
    return get_success_data(resp)


def add_clause(contract_id, **overrides):
    from .factories import create_clause_payload
    resp = api_client.create_clause(contract_id, create_clause_payload(**overrides), ACCT)
    return get_success_data(resp)


def get_contract(contract_id):
    resp = api_client.get_contract(contract_id, ACCT)
    return get_success_data(resp)


def get_pob(pob_id):
    resp = api_client.get_pob(pob_id, ACCT)
    return get_success_data(resp)


def get_period(period_id):
    resp = api_client.get_accounting_period(period_id, CTRL)
    return get_success_data(resp)


def submit_contract(contract_id):
    resp = api_client.submit_contract(contract_id, ACCT)
    return get_success_data(resp)


def approve_contract(contract_id, headers=None):
    resp = api_client.approve_contract(contract_id, headers or MGR)
    return get_success_data(resp)


def activate_contract(contract_id, headers=None):
    resp = api_client.activate_contract(contract_id, headers or MGR)
    return get_success_data(resp)


def walk_contract_to_active(contract_id):
    """submit -> approve -> activate. Returns the ACTIVE contract."""
    submit_contract(contract_id)
    approve_contract(contract_id)
    return activate_contract(contract_id)


# ---------------------------------------------------------------------------
# Tier 2/3: composite scenario builders
# ---------------------------------------------------------------------------

def setup_ssp_and_customer(product_code="WIDGET", region="US", ssp_cents=100000):
    """One ACTIVE price-book record + one customer. Returns (ssp, customer)."""
    ssp = create_ssp(product_code, region=region, ssp_cents=ssp_cents)
    customer = create_customer()
    return ssp, customer


def setup_active_contract_with_pob(product_code="WIDGET", region="US",
                                   ssp_cents=100000, fixed=100000,
                                   signed_date="2026-05-20",
                                   risk_tier="STANDARD",
                                   pob_overrides=None, with_period=True,
                                   clock="2026-06-15T00:00:00Z"):
    """ACTIVE contract with a single POB.

    Steps: clock, June period, SSP, customer, contract, POB, submit, approve,
    activate. Returns dict with contract, pob, period, customer, ssp.
    """
    if clock:
        set_clock(clock)
    period = create_period() if with_period else None
    ssp = create_ssp(product_code, region=region, ssp_cents=ssp_cents)
    customer = create_customer()
    contract = create_contract(
        customer["id"], fixed_consideration_cents=fixed,
        signed_date=signed_date, risk_tier=risk_tier,
    )
    pob_kwargs = {"product_code": product_code, "region": region}
    if pob_overrides:
        pob_kwargs.update(pob_overrides)
    pob = add_pob(contract["id"], **pob_kwargs)
    contract = walk_contract_to_active(contract["id"])
    return {
        "contract": contract, "pob": pob, "period": period,
        "customer": customer, "ssp": ssp,
    }


def setup_active_contract_with_pobs(products, fixed, signed_date="2026-05-20",
                                    risk_tier="STANDARD",
                                    with_period=True,
                                    clock="2026-06-15T00:00:00Z"):
    """ACTIVE contract with several POBs, one SSP per product.

    `products` is a list of dicts: {product_code, region, ssp_cents, pob: {...}}.
    Returns dict with contract, pobs (list, creation order), period, customer.
    """
    if clock:
        set_clock(clock)
    period = create_period() if with_period else None
    for spec in products:
        create_ssp(spec["product_code"], region=spec.get("region", "US"),
                   ssp_cents=spec["ssp_cents"])
    customer = create_customer()
    contract = create_contract(
        customer["id"], fixed_consideration_cents=fixed,
        signed_date=signed_date, risk_tier=risk_tier,
    )
    pobs = []
    for spec in products:
        pob_kwargs = {"product_code": spec["product_code"],
                      "region": spec.get("region", "US")}
        pob_kwargs.update(spec.get("pob", {}))
        pobs.append(add_pob(contract["id"], **pob_kwargs))
    contract = walk_contract_to_active(contract["id"])
    return {"contract": contract, "pobs": pobs, "period": period,
            "customer": customer}


def get_contract_version(contract_id):
    """Current OCC pivot value for modification proposals (PRD §2.7)."""
    return get_contract(contract_id)["version"]


def propose_modification(contract_id, proposer_headers=None, **overrides):
    """Propose a modification at the contract's current version."""
    version = get_contract_version(contract_id)
    from .factories import create_modification_payload
    payload = create_modification_payload(version, **overrides)
    resp = api_client.create_modification(contract_id, payload,
                                          proposer_headers or ACCT)
    return get_success_data(resp)


def list_review_tasks_for_contract(contract_id):
    resp = api_client.list_review_tasks(REV, params={"contract_id": contract_id})
    return get_success_data(resp)


def setup_contract_in_review_with_clause(clause_overrides=None):
    """IN_REVIEW contract with one non-standard clause and one ASSIGNED task.

    Returns dict with contract, clause, task, customer.
    """
    create_ssp("WIDGET", region="US", ssp_cents=100000)
    customer = create_customer()
    contract = create_contract(customer["id"], fixed_consideration_cents=100000)
    add_pob(contract["id"], product_code="WIDGET", region="US")
    clause_kwargs = {"is_non_standard": True}
    if clause_overrides:
        clause_kwargs.update(clause_overrides)
    clause = add_clause(contract["id"], **clause_kwargs)
    contract = submit_contract(contract["id"])
    tasks = list_review_tasks_for_contract(contract["id"])
    assert len(tasks) == 1, f"Setup failed: expected 1 review task, got {len(tasks)}"
    return {"contract": contract, "clause": clause, "task": tasks[0],
            "customer": customer}
