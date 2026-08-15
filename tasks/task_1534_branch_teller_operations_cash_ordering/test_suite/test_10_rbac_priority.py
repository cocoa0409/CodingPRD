"""RBAC, identity, validation priority, and cross-branch integrity."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, basic_setup, setup_frozen_branch, deposit, teller_h,
    make_branch, make_teller, make_account, open_drawer, transaction_payload,
    create_branch_payload,
)

MGR = TEST_USERS["manager_headers"]
HT = TEST_USERS["head_teller_headers"]
AUD = TEST_USERS["auditor_headers"]


def test_request_without_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a role string
    the platform does not recognize, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/validations/request_without_auth_headers_unauthenticated
    """
    resp = api.list_branches(None)
    validate_error(resp, "ERR_UNAUTHENTICATED", 401)


def test_auditor_cannot_post_transaction_forbidden(api):
    """PRD §2.1: "If the headers are valid but the role is not permitted to
    invoke the endpoint, the request is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."

    Design: Corner/validations/auditor_cannot_post_transaction_forbidden
    """
    ctx = basic_setup(api)
    resp = api.post_transaction(ctx["drawer"]["id"], {
        "account_id": ctx["account"]["id"], "type": "CASH_DEPOSIT", "amount_cents": 100,
    }, AUD)
    validate_error(resp, "ERR_FORBIDDEN", 403)


def test_teller_acting_on_other_tellers_drawer_forbidden(api):
    """PRD §2.1: "a teller can post transactions, buy or sell vault cash, record
    a count, or raise a request only on the drawer whose `teller_id` equals
    their `X-User-ID`; a mismatch is `ERR_FORBIDDEN`."

    Design: Corner/validations/teller_acting_on_other_tellers_drawer_forbidden
    """
    ctx = basic_setup(api)
    other = make_teller(api, ctx["branch"], "Other")
    resp = api.post_transaction(ctx["drawer"]["id"], {
        "account_id": ctx["account"]["id"], "type": "CASH_DEPOSIT", "amount_cents": 100,
    }, teller_h(other))
    validate_error(resp, "ERR_FORBIDDEN", 403)


def test_void_by_posting_teller_id_rejected_sod(api):
    """PRD §3.10: "only when the manager's `X-User-ID` differs from the posting
    teller's identity, a segregation-of-duties rule whose violation is
    `ERR_SOD_VIOLATION`."

    Design: Corner/validations/void_by_posting_teller_id_rejected_sod
    """
    ctx = basic_setup(api, account_balance=0)
    tx = deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 10_000)
    resp = api.void_transaction(tx["id"],
                                {"X-User-ID": ctx["teller"]["id"], "X-User-Role": "BranchManager"})
    validate_error(resp, "ERR_SOD_VIOLATION", 409)


def test_teller_cannot_create_branch(api):
    """PRD §2.1: `Teller` is "the line role that operates a drawer" — branch
    creation is the `BranchManager`'s; other roles get `ERR_FORBIDDEN`.

    Design: Corner/rbac/teller_cannot_create_branch
    """
    resp = api.create_branch(create_branch_payload(),
                             {"X-User-ID": "t-1", "X-User-Role": "Teller"})
    validate_error(resp, "ERR_FORBIDDEN", 403)


def test_head_teller_cannot_void_transaction(api):
    """PRD §3.10: "A `BranchManager` may void a `POSTED` transaction" — the
    `HeadTeller` role is not granted voids and gets `ERR_FORBIDDEN`.

    Design: Corner/rbac/head_teller_cannot_void_transaction
    """
    ctx = basic_setup(api, account_balance=0)
    tx = deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 10_000)
    resp = api.void_transaction(tx["id"], HT)
    validate_error(resp, "ERR_FORBIDDEN", 403)


def test_teller_cannot_read_ctr_filings(api):
    """PRD §3.6/§4: the filing list is restricted to `BranchManager`,
    `HeadTeller`, and `Auditor` — a `Teller` read is `ERR_FORBIDDEN`.

    Design: Corner/rbac/teller_cannot_read_ctr_filings
    """
    ctx = basic_setup(api)
    resp = api.list_ctr_filings(teller_h(ctx["teller"]),
                                {"branch_id": ctx["branch"]["id"]})
    validate_error(resp, "ERR_FORBIDDEN", 403)


def test_cross_branch_account_rejected(api):
    """PRD §3.1: "the account must belong to the same branch as the drawer
    serving the customer; a mismatch is rejected with `ERR_CROSS_BRANCH`
    (HTTP 422)."

    Design: Corner/validations/cross_branch_account_rejected
    """
    ctx = basic_setup(api)
    branch2 = make_branch(api, name="B2")
    foreign = make_account(api, branch2, balance_cents=100_000)
    resp = api.post_transaction(ctx["drawer"]["id"], {
        "account_id": foreign["id"], "type": "CASH_DEPOSIT", "amount_cents": 100,
    }, ctx["teller_h"])
    validate_error(resp, "ERR_CROSS_BRANCH", 422)


def test_frozen_branch_reported_before_insufficient_funds(api):
    """PRD §2.8: "a frozen branch masks an insufficient-funds problem" — safety
    checks precede the fiscal family.

    Design: Difficulty/priority_pair_validation_conflict/frozen_branch_reported_before_insufficient_funds
    """
    ctx, audit = setup_frozen_branch(api, account_balance=100)
    resp = api.post_transaction(ctx["drawer"]["id"], {
        "account_id": ctx["account"]["id"], "type": "CASH_WITHDRAWAL", "amount_cents": 50_000,
    }, ctx["teller_h"])
    validate_error(resp, "ERR_BRANCH_FROZEN", 409)


def test_frozen_branch_blocks_deposits_too(api):
    """PRD §3.9: "while the freeze stands, no cash may move: no postings, no
    buys or sells, no drawer openings, no cash-order placement or delivery,
    and no instrument execution all fail with `ERR_BRANCH_FROZEN`."

    Design: Difficulty/priority_pair_validation_conflict/frozen_branch_reported_before_insufficient_funds
    """
    ctx, audit = setup_frozen_branch(api, account_balance=100)
    resp = api.post_transaction(ctx["drawer"]["id"], {
        "account_id": ctx["account"]["id"], "type": "CASH_DEPOSIT", "amount_cents": 100,
    }, ctx["teller_h"])
    validate_error(resp, "ERR_BRANCH_FROZEN", 409)
    acct = validate_success(api.get_account(ctx["account"]["id"], MGR))
    assert acct["balance_cents"] == 100


def test_state_error_reported_before_transaction_limit(api):
    """PRD §2.8: "a stale state masks an over-limit problem — never the
    reverse."

    Design: Difficulty/priority_pair_validation_conflict/stale_drawer_state_reported_before_transaction_limit
    """
    ctx = basic_setup(api, branch_overrides={"drawer_limit_cents": 1_000_000},
                      account_balance=100_000_000)
    get_success_data(api.buy_from_vault(ctx["drawer"]["id"], 999_999, ctx["teller_h"]))
    validate_success(api.count_drawer(ctx["drawer"]["id"], 999_999, ctx["teller_h"]))
    resp = api.post_transaction(ctx["drawer"]["id"], {
        "account_id": ctx["account"]["id"], "type": "CASH_WITHDRAWAL", "amount_cents": 600_000,
    }, ctx["teller_h"])
    validate_error(resp, "ERR_INVALID_STATE", 409)


def test_counting_drawer_rejection_leaves_no_trace(api):
    """PRD §3.3: "the drawer must be `OPEN` (`ERR_INVALID_STATE`)" — a posting
    rejected for state creates no transaction.

    Design: Difficulty/priority_pair_validation_conflict/stale_drawer_state_reported_before_transaction_limit
    """
    ctx = basic_setup(api, branch_overrides={"drawer_limit_cents": 1_000_000},
                      account_balance=100_000_000)
    get_success_data(api.buy_from_vault(ctx["drawer"]["id"], 999_999, ctx["teller_h"]))
    validate_success(api.count_drawer(ctx["drawer"]["id"], 999_999, ctx["teller_h"]))
    api.post_transaction(ctx["drawer"]["id"], {
        "account_id": ctx["account"]["id"], "type": "CASH_WITHDRAWAL", "amount_cents": 600_000,
    }, ctx["teller_h"])
    txns = get_success_data(api.list_transactions(MGR, {"drawer_id": ctx["drawer"]["id"]}))
    assert txns == []
    acct = validate_success(api.get_account(ctx["account"]["id"], MGR))
    assert acct["balance_cents"] == 100_000_000
