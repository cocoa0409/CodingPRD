"""Composite setup helpers (PRD §3 workflows).

Every fixture builds its preconditions from an empty store via the public API
(the harness reboots the server before every test). Setup calls use the
lenient get_success_data() so a setup failure surfaces as a clear error.
"""
from prd_bench_local_runner.testing import get_success_data

from .constants import BRANCH_DEFAULTS
from .factories import (
    create_branch_payload, create_teller_payload, create_account_payload,
    transaction_payload, instrument_params,
)
from .test_users import TEST_USERS, make_teller_headers

MGR = TEST_USERS["manager_headers"]
MGR2 = TEST_USERS["manager2_headers"]
HT = TEST_USERS["head_teller_headers"]
AUD = TEST_USERS["auditor_headers"]


def make_branch(api, **overrides):
    """Create a branch. Returns branch dict."""
    return get_success_data(api.create_branch(create_branch_payload(**overrides), MGR))


def make_teller(api, branch, display_name="Teller One"):
    return get_success_data(api.create_teller(branch["id"], create_teller_payload(display_name), MGR))


def make_account(api, branch, balance_cents=0, owner_name="Acct Owner"):
    return get_success_data(api.create_account(
        branch["id"], create_account_payload(owner_name, balance_cents), MGR))


def open_drawer(api, teller):
    """Open the teller's drawer for the current business date."""
    return get_success_data(api.open_drawer(teller["id"], HT))


def teller_h(teller):
    return make_teller_headers(teller["id"])


def basic_setup(api, branch_overrides=None, account_balance=100_000):
    """Branch + teller + account + OPEN drawer. Returns a context dict."""
    branch = make_branch(api, **(branch_overrides or {}))
    teller = make_teller(api, branch)
    account = make_account(api, branch, balance_cents=account_balance)
    drawer = open_drawer(api, teller)
    return {
        "branch": branch, "teller": teller, "account": account, "drawer": drawer,
        "mgr": MGR, "mgr2": MGR2, "ht": HT, "aud": AUD, "teller_h": teller_h(teller),
    }


def deposit(api, drawer, account, teller, amount_cents, exempt=False):
    return get_success_data(api.post_transaction(
        drawer["id"], transaction_payload(account["id"], "CASH_DEPOSIT", amount_cents,
                                          is_ctr_exempt=exempt), teller_h(teller)))


def withdraw(api, drawer, account, teller, amount_cents):
    return get_success_data(api.post_transaction(
        drawer["id"], transaction_payload(account["id"], "CASH_WITHDRAWAL", amount_cents),
        teller_h(teller)))


def check_deposit(api, drawer, account, teller, amount_cents):
    return get_success_data(api.post_transaction(
        drawer["id"], transaction_payload(account["id"], "CHECK_DEPOSIT", amount_cents),
        teller_h(teller)))


def issue_instrument(api, drawer, account, teller, amount_cents,
                     instrument_type="MONEY_ORDER", fee_waived=False, approver=None):
    """Full dual-control instrument issuance. Returns the POSTED transaction."""
    req = get_success_data(api.create_teller_request(
        drawer["id"], {"type": "ISSUE_INSTRUMENT",
                       "params": instrument_params(account["id"], instrument_type,
                                                   amount_cents, fee_waived)},
        teller_h(teller)))
    get_success_data(api.approve_teller_request(req["id"], approver or MGR))
    txns = get_success_data(api.list_transactions(MGR, {"drawer_id": drawer["id"]}))
    matches = [t for t in txns
               if t["type"] == ("CASHIERS_CHECK_PURCHASE" if instrument_type == "CASHIERS_CHECK"
                                else "MONEY_ORDER_PURCHASE")
               and t["amount_cents"] == amount_cents]
    assert matches, "instrument transaction should exist after approval"
    return matches[-1]


def setup_counting_drawer(api, counted_cash_cents=0, **kwargs):
    """basic_setup + teller counts the drawer. Returns ctx (drawer COUNTING)."""
    ctx = basic_setup(api, **kwargs)
    get_success_data(api.count_drawer(ctx["drawer"]["id"], counted_cash_cents, ctx["teller_h"]))
    ctx["drawer"] = get_success_data(api.get_drawer(ctx["drawer"]["id"], MGR))
    return ctx


def setup_out_of_balance(api, deposit_amount=50_000, counted_cash_cents=49_000):
    """Drawer with one deposit, counted short, attested OUT_OF_BALANCE.

    Returns (ctx, case-or-None). Default variance -1000 hits the default
    1000-cent investigation threshold exactly, so a case exists; the teller
    is NOT auto-suspended (severity needs twice the threshold).
    """
    ctx = basic_setup(api, account_balance=0)
    deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], deposit_amount)
    get_success_data(api.count_drawer(ctx["drawer"]["id"], counted_cash_cents, ctx["teller_h"]))
    ctx["drawer"] = get_success_data(api.attest_drawer(ctx["drawer"]["id"], MGR))
    cases = get_success_data(api.list_over_short_cases(MGR, {"drawer_id": ctx["drawer"]["id"]}))
    return ctx, (cases[0] if cases else None)


def setup_frozen_branch(api, account_balance=100):
    """basic_setup + SURPRISE audit freezing the branch. Returns (ctx, audit)."""
    ctx = basic_setup(api, account_balance=account_balance)
    audit = get_success_data(api.create_audit(ctx["branch"]["id"], {"type": "SURPRISE"}, AUD))
    ctx["branch"] = get_success_data(api.get_branch(ctx["branch"]["id"], MGR))
    return ctx, audit


def setup_forecast_history(api, days, vault_cash_cents=50_000_000,
                           drawer_limit_cents=2_000_000, fund_amount=1_900_000):
    """Branch + teller + drawer + account; posts one CASH_WITHDRAWAL per (date, net)
    in `days` (list of (iso_date, amount)); drawer pre-funded from the vault.
    Returns ctx with clock left at the last listed date."""
    branch = make_branch(api, vault_cash_cents=vault_cash_cents,
                         drawer_limit_cents=drawer_limit_cents)
    teller = make_teller(api, branch)
    account = make_account(api, branch, balance_cents=100_000_000)
    drawer = open_drawer(api, teller)
    th = teller_h(teller)
    if fund_amount:
        get_success_data(api.buy_from_vault(drawer["id"], fund_amount, th))
    for day, amount in days:
        get_success_data(api.set_clock(f"{day}T00:00:00Z", MGR))
        get_success_data(api.post_transaction(
            drawer["id"], transaction_payload(account["id"], "CASH_WITHDRAWAL", amount), th))
    return {"branch": branch, "teller": teller, "account": account, "drawer": drawer,
            "mgr": MGR, "ht": HT, "aud": AUD, "teller_h": th}
