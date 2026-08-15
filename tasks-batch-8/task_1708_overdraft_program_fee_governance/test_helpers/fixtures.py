"""Composite setup helpers for overdraft-governance tests (PRD §3).

Every test runs against a freshly restarted server (empty database, logical
clock at 2026-08-01T00:00:00Z), so each fixture builds its preconditions from
scratch using only PRD-declared endpoints. Setup calls use the lenient
get_success_data so a setup failure surfaces as a clear "Setup failed" error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import MON, TUE, WED
from .factories import (
    create_account_payload,
    create_batch_payload,
    create_notice_payload,
    create_offer_payload,
    create_program_payload,
    create_report_payload,
    create_transaction_payload,
    create_waiver_request_payload,
)
from .test_users import (
    TEST_USERS,
    make_account_holder_headers,
)

ADMIN = TEST_USERS["admin_headers"]
CLERK = TEST_USERS["clerk_headers"]
TELLER = TEST_USERS["teller_1_headers"]
TELLER_2 = TEST_USERS["teller_2_headers"]
TELLER_3 = TEST_USERS["teller_3_headers"]
SUPERVISOR = TEST_USERS["supervisor_1_headers"]
MANAGER = TEST_USERS["manager_1_headers"]
COMPLIANCE = TEST_USERS["compliance_1_headers"]


# --- Tier 0: logical clock (PRD §2.4) ---

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# --- Tier 1: single-resource creation ---

def make_program(**overrides) -> dict:
    """Create an ACTIVE program at version 1 (PRD §3.1)."""
    resp = api_client.create_program(create_program_payload(**overrides), ADMIN)
    return get_success_data(resp)


def get_program(program_id: str) -> dict:
    return get_success_data(api_client.get_program(program_id, ADMIN))


def make_account(program_id: str, holder_name=None, headers=None) -> dict:
    """Open an ACTIVE account with zero ledger and counters (PRD §3.2)."""
    overrides = {}
    if holder_name is not None:
        overrides["holder_name"] = holder_name
    resp = api_client.create_account(
        create_account_payload(program_id, **overrides), headers or TELLER)
    return get_success_data(resp)


def get_account(account_id: str) -> dict:
    return get_success_data(api_client.get_account(account_id, ADMIN))


def make_election(account_id: str, channel="BRANCH", disclosure_version="D1") -> dict:
    """Create the account's single opt-in election as its holder (PRD §3.2)."""
    resp = api_client.create_opt_in_election(
        account_id,
        {"channel": channel, "disclosure_version": disclosure_version},
        make_account_holder_headers(account_id))
    return get_success_data(resp)


def make_opted_in_account(program_id: str, holder_name=None, channel="BRANCH",
                          disclosure_version="D1"):
    """Account + OPTED_IN election. Returns (account, election)."""
    account = make_account(program_id, holder_name=holder_name)
    election = make_election(account["id"], channel=channel,
                             disclosure_version=disclosure_version)
    return account, election


def get_election(election_id: str) -> dict:
    return get_success_data(api_client.get_opt_in_election(election_id, ADMIN))


def authorize(account_id: str, txn_type: str, amount_cents: int) -> dict:
    """Authorize a transaction as the owning AccountHolder (PRD §3.3)."""
    resp = api_client.create_transaction(
        create_transaction_payload(account_id, type=txn_type,
                                   amount_cents=amount_cents),
        make_account_holder_headers(account_id))
    return get_success_data(resp)


def get_transaction(transaction_id: str) -> dict:
    return get_success_data(api_client.get_transaction(transaction_id, ADMIN))


# --- Tier 2: posting-batch lifecycle (PRD §3.4/§3.5) ---

def open_batch(program_id: str, business_date: str) -> dict:
    resp = api_client.create_batch(
        create_batch_payload(program_id, business_date), CLERK)
    return get_success_data(resp)


def seal_batch(batch_id: str) -> dict:
    return get_success_data(api_client.seal_batch(batch_id, CLERK))


def settle_batch(batch_id: str) -> dict:
    return get_success_data(api_client.settle_batch(batch_id, CLERK))


def get_batch(batch_id: str) -> dict:
    return get_success_data(api_client.get_batch(batch_id, ADMIN))


def run_posting_day(program_id: str, business_date: str, account_id=None,
                    items=(), settle=True, clock_times=None):
    """Open a batch for business_date, authorize the given items
    ((type, amount_cents) pairs) on account_id — optionally advancing the
    clock to clock_times[i] before item i — seal, and optionally settle.
    Returns {"batch_id", "batch", "seal", "settle", "transactions"}.
    """
    batch = open_batch(program_id, business_date)
    txns = []
    for i, (ttype, amount) in enumerate(items):
        if clock_times:
            set_clock(clock_times[i])
        txns.append(authorize(account_id, ttype, amount))
    seal_data = seal_batch(batch["id"])
    settle_data = settle_batch(batch["id"]) if settle else None
    final = settle_data if settle_data is not None else seal_data
    return {
        "batch_id": batch["id"],
        "batch": final,
        "seal": seal_data,
        "settle": settle_data,
        "transactions": txns,
    }


def fund_account(program_id: str, account_id: str, amount_cents: int,
                 business_date=MON, settle=True):
    """Post a single CREDIT_DEPOSIT through its own batch (PRD §3.4:
    credits post first inside a seal)."""
    return run_posting_day(program_id, business_date, account_id,
                           [("CREDIT_DEPOSIT", amount_cents)], settle=settle)


# --- Tier 2: read helpers ---

def list_fees(headers=None, **params) -> list:
    return get_success_data(api_client.list_fees(headers or ADMIN, params=params))


def get_fee(fee_id: str) -> dict:
    return get_success_data(api_client.get_fee(fee_id, ADMIN))


def list_offers(account_id=None, headers=None, **params) -> list:
    if account_id is not None:
        params["account_id"] = account_id
    return get_success_data(
        api_client.list_education_offers(headers or ADMIN, params=params))


def get_offer(offer_id: str) -> dict:
    return get_success_data(api_client.get_education_offer(offer_id, ADMIN))


def list_waiver_items(headers=None, **params) -> list:
    return get_success_data(
        api_client.list_waiver_items(headers or ADMIN, params=params))


def get_waiver_request(request_id: str) -> dict:
    return get_success_data(api_client.get_fee_waiver_request(request_id, ADMIN))


def get_notice(notice_id: str) -> dict:
    return get_success_data(api_client.get_notice(notice_id, ADMIN))


def get_report(report_id: str) -> dict:
    return get_success_data(api_client.get_report(report_id, ADMIN))


# --- Tier 3: fee-producing scenarios ---

def make_posted_fee_scenario(program_overrides=None, debit_amount_cents=2000,
                             business_date=MON, holder_name=None):
    """Program + opted-in account + one batch whose debit overdraws the
    account, sealed AND settled, producing a single POSTED OVERDRAFT fee.
    Returns {"program", "account", "election", "fee", "batch_id"}.
    """
    program = make_program(**(program_overrides or {}))
    account, election = make_opted_in_account(program["id"],
                                              holder_name=holder_name)
    run_posting_day(program["id"], business_date, account["id"],
                    [("DEBIT_ONE_TIME", debit_amount_cents)], settle=True)
    fee = list_fees(account_id=account["id"], fee_type="OVERDRAFT")[0]
    return {
        "program": program,
        "account": account,
        "election": election,
        "fee": fee,
        "batch_id": fee["batch_id"],
    }


def make_restricted_scenario(program_overrides=None, debit_amount_cents=5000,
                             business_date=MON):
    """Drive an account to RESTRICTED in one settled batch: program with
    sustained-day threshold 1; the overdraw yields an OVERDRAFT fee and the
    settle's day count reaches the threshold, assessing the SUSTAINED fee and
    auto-creating a SUSTAINED_OD offer (PRD §3.5).
    Returns {"program", "account", "election", "batch_id"}.
    """
    overrides = {
        "sustained_overdraft_days_threshold": 1,
        "steering_fee_count_threshold": 99,
    }
    overrides.update(program_overrides or {})
    program = make_program(**overrides)
    account, election = make_opted_in_account(program["id"])
    run_posting_day(program["id"], business_date, account["id"],
                    [("DEBIT_ONE_TIME", debit_amount_cents)], settle=True)
    return {
        "program": program,
        "account": account,
        "election": election,
        "batch_id": None,
    }


def make_charged_off_scenario(program_overrides=None):
    """Drive an account through RESTRICTED to CLOSED_CHARGEOFF (PRD §3.5):
    threshold 1, grace 2 — batch Mon (debit 5000: OVERDRAFT fee 3500, settle
    restricts and assesses SUSTAINED 3000, ledger -11500), empty batches Tue
    and Wed push restricted_business_days to 2, charging off 11500.
    Returns {"program", "account", "election"} with the account re-read.
    """
    overrides = {
        "sustained_overdraft_days_threshold": 1,
        "charge_off_grace_business_days": 2,
        "steering_fee_count_threshold": 99,
    }
    overrides.update(program_overrides or {})
    program = make_program(**overrides)
    account, election = make_opted_in_account(program["id"])
    run_posting_day(program["id"], MON, account["id"],
                    [("DEBIT_ONE_TIME", 5000)], settle=True)
    run_posting_day(program["id"], TUE, account["id"], [], settle=True)
    run_posting_day(program["id"], WED, account["id"], [], settle=True)
    return {
        "program": program,
        "account": get_account(account["id"]),
        "election": election,
    }


# --- Tier 3: waiver helpers (PRD §3.6) ---

def submit_waiver(account_id, fee_ids, kind="FULL", headers=None,
                  as_holder=False, **overrides) -> dict:
    """Submit a fee waiver request. Staff callers pass their role headers;
    as_holder=True submits as the owning AccountHolder (never auto-applies)."""
    hdrs = headers
    if hdrs is None:
        hdrs = (make_account_holder_headers(account_id) if as_holder else TELLER)
    resp = api_client.create_fee_waiver_request(
        create_waiver_request_payload(account_id, fee_ids, kind=kind, **overrides),
        hdrs)
    return get_success_data(resp)


# --- Tier 3: notice helpers (PRD §3.7) ---

def create_notice(program_id, parameter="FEE_AMOUNT", new_value="3600") -> dict:
    """Create a DRAFT notice with a fresh OCC expected_program_version."""
    program = get_program(program_id)
    resp = api_client.create_notice(
        create_notice_payload(program_id, program["version"],
                              parameter=parameter, new_value=new_value),
        ADMIN)
    return get_success_data(resp)


def make_issued_notice(program_id, issue_clock, parameter="FEE_AMOUNT",
                       new_value="3600") -> dict:
    """Create a notice and issue it at issue_clock: sent_at=clock,
    effective_at=clock+notice_window_days (PRD §3.7)."""
    notice = create_notice(program_id, parameter=parameter, new_value=new_value)
    set_clock(issue_clock)
    return get_success_data(api_client.issue_notice(notice["id"], ADMIN))


# --- Tier 3: offer helpers (PRD §3.8) ---

def create_offer(account_id, offer_type="COUNSELING") -> dict:
    """Banker-created offer with a fresh OCC expected_account_version."""
    account = get_account(account_id)
    resp = api_client.create_education_offer(
        create_offer_payload(account_id, account["version"],
                             offer_type=offer_type),
        TELLER)
    return get_success_data(resp)


# --- Tier 3: report helpers (PRD §3.9) ---

def create_report(program_id, period_start, period_end, headers=None) -> dict:
    resp = api_client.create_report(
        create_report_payload(program_id, period_start, period_end),
        headers or ADMIN)
    return get_success_data(resp)
