"""Composite setup helpers.

Every test runs against a freshly launched, empty server, so each fixture builds
its full precondition chain from scratch using only PRD-declared endpoints.

All setup calls use get_success_data() (lenient) so a setup misstep surfaces as a
clear "Setup failed" rather than a confusing downstream assertion.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS
from . import factories

PUB = TEST_USERS["publisher_headers"]

# Standard three-tier escalator used by the worked examples:
# [1..5000]=0.10, [5001..10000]=0.125, [10001..]=0.15
STANDARD_TIERS = [
    {"lower_unit": 1, "upper_unit": 5000, "rate": 0.10},
    {"lower_unit": 5001, "upper_unit": 10000, "rate": 0.125},
    {"lower_unit": 10001, "rate": 0.15},
]
# Single open tier [1..]=0.10
SINGLE_TIER = [{"lower_unit": 1, "rate": 0.10}]


def _uniq(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:12]}@x.com"


# --------------------------------------------------------------------------
# Party + contract primitives
# --------------------------------------------------------------------------
def create_author(tax_withholding_pct=None, **overrides):
    payload = factories.create_author_payload(**overrides)
    if tax_withholding_pct is not None:
        payload["tax_withholding_pct"] = tax_withholding_pct
    return get_success_data(api_client.create_author(payload, PUB))


def create_agent(**overrides):
    payload = factories.create_agent_payload(**overrides)
    return get_success_data(api_client.create_agent(payload, PUB))


def create_contract(author_id, **overrides):
    payload = factories.create_contract_payload(author_id, **overrides)
    return get_success_data(api_client.create_contract(payload, PUB))


def add_tiers(contract_id, tiers):
    for t in tiers:
        get_success_data(api_client.create_royalty_tier(contract_id, dict(t), PUB))


def add_title(contract_id, name="Test Book", **overrides):
    payload = factories.create_title_payload(name, **overrides)
    return get_success_data(api_client.create_title(contract_id, payload, PUB))


def add_format(title_id, format_type="HARDCOVER", list_price_cents=3000, **overrides):
    payload = factories.create_format_payload(format_type, list_price_cents, **overrides)
    return get_success_data(api_client.create_format(title_id, payload, PUB))


# --------------------------------------------------------------------------
# Tier 1/2: an active, publishable contract with one title + one format
# --------------------------------------------------------------------------
def setup_active_contract(
    tiers=STANDARD_TIERS,
    advance_cents=0,
    reserve_pct=None,
    reserve_hold_periods=None,
    agent_commission_pct=None,
    with_agent=False,
    tax_withholding_pct=None,
    list_price_cents=3000,
    publish=True,
):
    """Create + activate a contract with one title and one HARDCOVER format.

    Returns dict with keys: author, agent (or None), contract, title, format.
    The contract is ACTIVE; the title is PUBLISHED when publish=True.
    """
    author = create_author(tax_withholding_pct=tax_withholding_pct)
    agent = None
    contract_overrides = {"advance_cents": advance_cents}
    if reserve_pct is not None:
        contract_overrides["reserve_pct"] = reserve_pct
    if reserve_hold_periods is not None:
        contract_overrides["reserve_hold_periods"] = reserve_hold_periods
    if with_agent:
        agent = create_agent()
        contract_overrides["agent_id"] = agent["id"]
    if agent_commission_pct is not None:
        contract_overrides["agent_commission_pct"] = agent_commission_pct

    contract = create_contract(author["id"], **contract_overrides)
    add_tiers(contract["id"], tiers)
    title = add_title(contract["id"], name="Book")
    fmt = add_format(title["id"], list_price_cents=list_price_cents)
    get_success_data(api_client.activate_contract(contract["id"], PUB))
    if publish:
        get_success_data(api_client.publish_title(title["id"], PUB))
    contract = get_success_data(api_client.get_contract(contract["id"], PUB))
    return {
        "author": author,
        "agent": agent,
        "contract": contract,
        "title": title,
        "format": fmt,
    }


# --------------------------------------------------------------------------
# Tier 3/4: period lifecycle shortcuts
# --------------------------------------------------------------------------
def open_period(contract_id, label, sequence):
    payload = factories.create_sales_period_payload(label, sequence)
    return get_success_data(api_client.create_sales_period(contract_id, payload, PUB))


def post_sales(period_id, format_id, units_sold=0, units_returned=0):
    payload = factories.create_sales_record_payload(format_id, units_sold, units_returned)
    return get_success_data(api_client.create_sales_record(period_id, payload, PUB))


def close_period(period_id):
    return get_success_data(api_client.close_sales_period(period_id, PUB))


def generate_statement(period_id):
    return get_success_data(api_client.generate_statement(period_id, PUB))


def current_version(contract_id):
    return get_success_data(api_client.get_contract(contract_id, PUB))["version"]


def finalize_statement(statement_id, contract_id):
    """Finalize reading the live contract version (OCC happy path)."""
    cv = current_version(contract_id)
    return get_success_data(
        api_client.finalize_statement(statement_id, {"expected_contract_version": cv}, PUB)
    )


def pay_statement(statement_id, contract_id):
    cv = current_version(contract_id)
    return get_success_data(
        api_client.pay_statement(statement_id, {"expected_contract_version": cv}, PUB)
    )


def run_period_to_finalize(contract_id, format_id, label, sequence, units_sold, units_returned=0):
    """Open a period, post one record, close, generate, finalize. Returns dict
    {period, statement}."""
    period = open_period(contract_id, label, sequence)
    post_sales(period["id"], format_id, units_sold, units_returned)
    close_period(period["id"])
    stmt = generate_statement(period["id"])
    stmt = finalize_statement(stmt["id"], contract_id)
    return {"period": period, "statement": stmt}


def run_period_to_closed(contract_id, format_id, label, sequence, units_sold, units_returned=0):
    """Open a period, post one record, close. Returns the period (no statement yet)."""
    period = open_period(contract_id, label, sequence)
    post_sales(period["id"], format_id, units_sold, units_returned)
    close_period(period["id"])
    return period


def run_period_to_draft_statement(contract_id, format_id, label, sequence, units_sold, units_returned=0):
    """Open -> post -> close -> generate. Returns dict {period, statement} (statement DRAFT)."""
    period = run_period_to_closed(contract_id, format_id, label, sequence, units_sold, units_returned)
    stmt = generate_statement(period["id"])
    return {"period": period, "statement": stmt}


# --------------------------------------------------------------------------
# Reserve-liquidation scenario builder (used by several difficulty instances)
# --------------------------------------------------------------------------
def setup_reserve_liquidation_scenario(
    advance_cents=0,
    agent_commission_pct=None,
    with_agent=False,
    reserve_pct=0.25,
    reserve_hold_periods=2,
    p1_sold=6000,
    p2_sold=2000,
    p2_returned=400,
    p3_sold=1000,
    p3_returned=200,
):
    """Build the canonical three-period reserve scenario:
      P1 (seq1) net p1_sold FINALIZED -> creates reserve R1 (eligible_seq = 1 + hold).
      P2 (seq2) FINALIZED.
      P3 (seq3) CLOSED with a DRAFT statement ready to finalize (this finalize is
      where R1 liquidates when reserve_hold_periods=2).

    Returns dict: author, agent, contract, title, format, p1, p2, p3, s1, s2, s3
    where s3 is the DRAFT statement (not yet finalized).
    """
    base = setup_active_contract(
        tiers=STANDARD_TIERS,
        advance_cents=advance_cents,
        reserve_pct=reserve_pct,
        reserve_hold_periods=reserve_hold_periods,
        agent_commission_pct=agent_commission_pct,
        with_agent=with_agent,
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    p1 = run_period_to_finalize(cid, fid, "P1", 1, p1_sold, 0)
    p2 = run_period_to_finalize(cid, fid, "P2", 2, p2_sold, p2_returned)
    p3 = run_period_to_draft_statement(cid, fid, "P3", 3, p3_sold, p3_returned)

    return {
        "author": base["author"],
        "agent": base["agent"],
        "contract": get_success_data(api_client.get_contract(cid, PUB)),
        "title": base["title"],
        "format": base["format"],
        "p1": p1["period"],
        "p2": p2["period"],
        "p3": p3["period"],
        "s1": p1["statement"],
        "s2": p2["statement"],
        "s3": p3["statement"],
    }


def find_reserve_from_statement(statement_id):
    """Return the (single) reserve originating from a statement, or None."""
    reserves = get_success_data(api_client.list_statement_reserves(statement_id, PUB))
    if isinstance(reserves, list) and reserves:
        return reserves[0]
    return None
