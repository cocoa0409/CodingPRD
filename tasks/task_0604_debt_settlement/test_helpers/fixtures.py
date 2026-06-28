"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures surface clearly.
Identity threading: any Client-owned call uses make_client_headers(client_id)
with the real Client.id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_client_payload, create_program_payload, create_debt_payload,
    create_deposit_payload, create_offer_payload, accept_offer_payload,
    create_settlement_payload, create_lawsuit_payload,
)
from .test_users import TEST_USERS, make_client_headers

ADMIN = TEST_USERS["program_admin_headers"]
AGENT = TEST_USERS["negotiation_agent_headers"]


# ─── Clock ────────────────────────────────────────────────────────────────
def set_clock(iso="2026-06-01T00:00:00Z"):
    """Set the logical clock. Returns nothing meaningful (data is empty)."""
    return get_success_data(api_client.set_clock(iso, ADMIN))


# ─── Tier 0: primitives ───────────────────────────────────────────────────
def create_client(**overrides):
    return get_success_data(api_client.create_client(create_client_payload(**overrides), ADMIN))


def create_program(client_id, **overrides):
    return get_success_data(
        api_client.create_program(create_program_payload(client_id, **overrides), ADMIN))


def create_debt(program_id, **overrides):
    return get_success_data(
        api_client.create_debt(create_debt_payload(program_id, **overrides), ADMIN))


def add_cleared_deposit(program_id, client_id, scheduled_for, amount=600):
    return get_success_data(api_client.create_deposit(
        create_deposit_payload(program_id, scheduled_for, amount=amount),
        make_client_headers(client_id)))


def add_missed_deposit(program_id, scheduled_for, amount=600):
    """A MISSED deposit recorded by ProgramAdmin (no ownership needed)."""
    return get_success_data(api_client.create_deposit(
        create_deposit_payload(program_id, scheduled_for, amount=amount, status="MISSED"),
        ADMIN))


def create_offer(program_id, debt_id, **overrides):
    return get_success_data(
        api_client.create_offer(create_offer_payload(program_id, debt_id, **overrides), AGENT))


# ─── Tier 1: state progression ────────────────────────────────────────────
def create_program_with_debt(monthly_deposit_amount=600, original_balance=5000,
                             account_number="A-1", **prog_overrides):
    """Client + Program (ENROLLING) + one ENROLLED debt. Returns
    (client, program, debt)."""
    client = create_client()
    program = create_program(client["id"], monthly_deposit_amount=monthly_deposit_amount,
                            **prog_overrides)
    debt = create_debt(program["id"], original_balance=original_balance,
                       account_number=account_number)
    return client, program, debt


def create_active_program(monthly_deposit_amount=600, original_balance=5000,
                         account_number="A-1", **prog_overrides):
    """Client + Program ACTIVE + one ENROLLED debt. Returns
    (client, program_after_activate, debt). program_after_activate carries the
    post-activation version."""
    client, program, debt = create_program_with_debt(
        monthly_deposit_amount=monthly_deposit_amount, original_balance=original_balance,
        account_number=account_number, **prog_overrides)
    activated = get_success_data(api_client.activate_program(program["id"], ADMIN))
    return client, activated, debt


# ─── Tier 4: account funding / accumulation ───────────────────────────────
def fund_account(program_id, client_id, months, amount=600, year=2026, day=10,
                start_month=1):
    """Record `months` CLEARED deposits in distinct UTC month buckets.
    Returns the list of created deposit dicts."""
    deps = []
    for i in range(months):
        m = start_month + i
        scheduled = f"{year}-{m:02d}-{day:02d}T00:00:00Z"
        deps.append(add_cleared_deposit(program_id, client_id, scheduled, amount=amount))
    return deps


def drive_to_delinquent(program_id, scheduled_for="2026-06-15T00:00:00Z"):
    """Record one MISSED deposit -> missed_deposit_count 1 -> DELINQUENT.
    Returns the deposit."""
    return add_missed_deposit(program_id, scheduled_for)


def drive_to_defaulted(program_id, base_month=6):
    """Record three MISSED deposits in distinct months -> DEFAULTED.
    Returns the list of deposits."""
    deps = []
    for i in range(3):
        m = base_month + i
        deps.append(add_missed_deposit(program_id, f"2026-{m:02d}-02T00:00:00Z"))
    return deps


# ─── Tier 3: offer / settlement lifecycle ─────────────────────────────────
def accept_offer(offer_id, expected_program_version):
    return get_success_data(api_client.accept_offer(
        offer_id, accept_offer_payload(expected_program_version), AGENT))


def fund_settlement(program_id, offer_id):
    return get_success_data(api_client.create_settlement(
        create_settlement_payload(program_id, offer_id), AGENT))


def complete_settlement(settlement_id):
    return get_success_data(api_client.complete_settlement(settlement_id, AGENT))


def setup_funded_settlement(monthly_deposit_amount=600, original_balance=5000,
                           offer_pct=0.40, fund_months=6, account_number="S-1",
                           due_date="2026-12-01T00:00:00Z", lawsuit=False):
    """Active program + funded deposits + one accepted offer + FUNDED settlement.
    Returns dict with client, program, debt, offer, settlement (and lawsuit if any).
    The program's version is the post-activate version captured before accept;
    accept bumps it, so callers needing the current version should re-GET.
    """
    client, program, debt = create_active_program(
        monthly_deposit_amount=monthly_deposit_amount, original_balance=original_balance,
        account_number=account_number)
    v_after_activate = program["version"]
    lawsuit_obj = None
    if lawsuit:
        lawsuit_obj = get_success_data(api_client.create_lawsuit(
            create_lawsuit_payload(program["id"], debt["id"]), ADMIN))
    fund_account(program["id"], client["id"], fund_months, amount=monthly_deposit_amount)
    offer = create_offer(program["id"], debt["id"], offer_pct=offer_pct, due_date=due_date)
    accept_offer(offer["id"], v_after_activate)
    settlement = fund_settlement(program["id"], offer["id"])
    return {
        "client": client, "program": program, "debt": debt,
        "offer": offer, "settlement": settlement, "lawsuit": lawsuit_obj,
        "v_after_activate": v_after_activate,
    }


def setup_completed_settlement(**overrides):
    """As setup_funded_settlement, then COMPLETE the settlement.
    Returns the same dict; debt is now SETTLED."""
    ctx = setup_funded_settlement(**overrides)
    complete_settlement(ctx["settlement"]["id"])
    return ctx


# ─── Helpers to read fresh state ──────────────────────────────────────────
def get_program(program_id, headers=ADMIN):
    return get_success_data(api_client.get_program(program_id, headers))


def get_debt(debt_id, headers=ADMIN):
    return get_success_data(api_client.get_debt(debt_id, headers))


def get_account_for_program(program_id, headers=ADMIN):
    data = get_success_data(api_client.list_accounts(headers, params={"program_id": program_id}))
    return data[0]


def get_tax_events_for_settlement(settlement_id, headers=ADMIN):
    return get_success_data(
        api_client.list_tax_events(headers, params={"source_settlement_id": settlement_id}))
