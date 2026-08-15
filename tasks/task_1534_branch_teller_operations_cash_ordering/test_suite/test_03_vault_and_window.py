"""Window transactions and vault discipline: limits, sufficiency, invariants."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, basic_setup, deposit, withdraw, check_deposit, teller_h,
    make_branch, make_teller, make_account, open_drawer,
)

MGR = TEST_USERS["manager_headers"]
HT = TEST_USERS["head_teller_headers"]


def test_transaction_missing_amount_returns_invalid_request(api):
    """PRD §3.3: "an `amount_cents` that must be a positive whole number of
    cents" — omitting it is `ERR_INVALID_REQUEST` (§2.8 structural constraint).

    Design: Corner/entities/transaction_missing_amount_returns_invalid_request
    """
    ctx = basic_setup(api)
    resp = api.post_transaction(ctx["drawer"]["id"],
                                {"account_id": ctx["account"]["id"], "type": "CASH_DEPOSIT"},
                                ctx["teller_h"])
    validate_error(resp, "ERR_INVALID_REQUEST", 400)


def test_transaction_invalid_type_enum_rejected(api):
    """PRD §3.3 enumerates the transaction types; §2.8: "malformed payloads,
    invalid enum values, or non-positive amounts" are `ERR_INVALID_REQUEST`.

    Design: Corner/entities/transaction_invalid_type_enum_rejected
    """
    ctx = basic_setup(api)
    resp = api.post_transaction(ctx["drawer"]["id"], {
        "account_id": ctx["account"]["id"], "type": "WIRE", "amount_cents": 100,
    }, ctx["teller_h"])
    validate_error(resp, "ERR_INVALID_REQUEST", 400)


def test_buy_exceeding_vault_rejected(api):
    """PRD §3.2: "the branch's `vault_cash_cents` must cover the `amount_cents`
    requested (`ERR_INSUFFICIENT_VAULT_CASH` otherwise)".

    Design: Corner/errors/buy_exceeding_vault_rejected
    """
    ctx = basic_setup(api, branch_overrides={"vault_cash_cents": 100_000,
                                             "drawer_limit_cents": 100_000_000})
    resp = api.buy_from_vault(ctx["drawer"]["id"], 100_001, ctx["teller_h"])
    validate_error(resp, "ERR_INSUFFICIENT_VAULT_CASH", 422)


def test_buy_from_vault_at_limit_rejected(api):
    """PRD §3.2: "the buy is rejected with `ERR_DRAWER_LIMIT` whenever the
    drawer's balance after the buy would be greater than or equal to the
    branch's `drawer_limit_cents`".

    Design: Corner/errors/buy_from_vault_at_limit_rejected
    """
    ctx = basic_setup(api, branch_overrides={"drawer_limit_cents": 100_000})
    resp = api.buy_from_vault(ctx["drawer"]["id"], 100_000, ctx["teller_h"])
    validate_error(resp, "ERR_DRAWER_LIMIT", 422)
    ok = validate_success(api.buy_from_vault(ctx["drawer"]["id"], 99_999, ctx["teller_h"]))
    assert ok["cash_balance_cents"] == 99_999


def test_sell_leaving_drawer_at_limit_rejected(api):
    """PRD §3.2: "the teller may sell only when the drawer's current balance has
    reached or exceeded the cap, and the sale must bring the drawer strictly
    below it. A sell attempted while the drawer sits below the cap, or one
    whose amount leaves the drawer at or above the cap, fails with
    `ERR_DRAWER_LIMIT`."

    Design: Difficulty/boundary_precision_check/sell_to_vault_at_exact_limit_boundary
    """
    ctx = basic_setup(api, branch_overrides={"drawer_limit_cents": 100_000},
                      account_balance=0)
    deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 150_000)
    # selling 50000 would leave exactly 100000 == the limit -> rejected
    resp = api.sell_to_vault(ctx["drawer"]["id"], 50_000, ctx["teller_h"])
    validate_error(resp, "ERR_DRAWER_LIMIT", 422)


def test_sell_one_cent_below_limit_succeeds(api):
    """PRD §3.2: "the sale must bring the drawer strictly below it."

    Design: Difficulty/boundary_precision_check/sell_to_vault_at_exact_limit_boundary
    """
    ctx = basic_setup(api, branch_overrides={"drawer_limit_cents": 100_000},
                      account_balance=0)
    deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 150_000)
    data = validate_success(api.sell_to_vault(ctx["drawer"]["id"], 50_001, ctx["teller_h"]))
    assert data["cash_balance_cents"] == 99_999
    branch = validate_success(api.get_branch(ctx["branch"]["id"], MGR))
    assert branch["vault_cash_cents"] == 50_000_000 + 50_001


def test_withdrawal_exceeding_drawer_cash_rejected(api):
    """PRD §3.3: "the drawer must physically hold at least the amount
    (`ERR_INSUFFICIENT_DRAWER_CASH`)".

    Design: Corner/errors/withdrawal_exceeding_drawer_cash_rejected
    """
    ctx = basic_setup(api, account_balance=100_000_000)
    resp = api.post_transaction(ctx["drawer"]["id"], {
        "account_id": ctx["account"]["id"], "type": "CASH_WITHDRAWAL", "amount_cents": 5_000,
    }, ctx["teller_h"])
    validate_error(resp, "ERR_INSUFFICIENT_DRAWER_CASH", 422)


def test_teller_direct_withdrawal_over_limit_rejected(api):
    """PRD §3.3: "a teller-direct withdrawal may not exceed the per-transaction
    limit of 500000 cents — anything larger is `ERR_TRANSACTION_OVER_LIMIT`".

    Design: Corner/errors/teller_direct_withdrawal_over_limit_rejected
    """
    ctx = basic_setup(api, branch_overrides={"drawer_limit_cents": 100_000_000},
                      account_balance=100_000_000)
    get_success_data(api.buy_from_vault(ctx["drawer"]["id"], 1_500_000, ctx["teller_h"]))
    resp = api.post_transaction(ctx["drawer"]["id"], {
        "account_id": ctx["account"]["id"], "type": "CASH_WITHDRAWAL", "amount_cents": 500_001,
    }, ctx["teller_h"])
    validate_error(resp, "ERR_TRANSACTION_OVER_LIMIT", 422)
    ok = validate_success(api.post_transaction(ctx["drawer"]["id"], {
        "account_id": ctx["account"]["id"], "type": "CASH_WITHDRAWAL", "amount_cents": 500_000,
    }, ctx["teller_h"]), 201)
    assert ok["status"] == "POSTED"


def test_withdrawal_available_balance_net_of_holds(api):
    """PRD §3.3: "the account's available funds must cover the amount, where
    available funds are the account's `balance_cents` minus the amounts of its
    holds still `ACTIVE` (a shortfall is `ERR_INSUFFICIENT_FUNDS`)".

    Design: Corner/complexity_layers/withdrawal_available_balance_net_of_holds
    """
    ctx = basic_setup(api, account_balance=280_000)
    get_success_data(api.buy_from_vault(ctx["drawer"]["id"], 100_000, ctx["teller_h"]))
    check_deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 270_000)
    # ledger 300000; 250000 held -> 50000 available
    resp = api.post_transaction(ctx["drawer"]["id"], {
        "account_id": ctx["account"]["id"], "type": "CASH_WITHDRAWAL", "amount_cents": 60_000,
    }, ctx["teller_h"])
    validate_error(resp, "ERR_INSUFFICIENT_FUNDS", 422)
    ok = validate_success(api.post_transaction(ctx["drawer"]["id"], {
        "account_id": ctx["account"]["id"], "type": "CASH_WITHDRAWAL", "amount_cents": 50_000,
    }, ctx["teller_h"]), 201)
    assert ok["status"] == "POSTED"


def test_withdrawal_blocked_when_account_closed(api):
    """PRD §3.1: "any reference to a `CLOSED` account is `ERR_ACCOUNT_CLOSED`".

    Design: Difficulty/cross_entity_state_dependency/withdrawal_blocked_when_account_closed
    """
    ctx = basic_setup(api, account_balance=0)
    get_success_data(api.close_account(ctx["account"]["id"], MGR))
    resp = api.post_transaction(ctx["drawer"]["id"], {
        "account_id": ctx["account"]["id"], "type": "CASH_DEPOSIT", "amount_cents": 100,
    }, ctx["teller_h"])
    validate_error(resp, "ERR_ACCOUNT_CLOSED", 409)


def test_closed_account_rejection_has_no_side_effects(api):
    """PRD §3.1: "any reference to a `CLOSED` account is `ERR_ACCOUNT_CLOSED`"
    — the rejected call must not move money.

    Design: Difficulty/cross_entity_state_dependency/withdrawal_blocked_when_account_closed
    """
    ctx = basic_setup(api, account_balance=0)
    get_success_data(api.close_account(ctx["account"]["id"], MGR))
    api.post_transaction(ctx["drawer"]["id"], {
        "account_id": ctx["account"]["id"], "type": "CASH_WITHDRAWAL", "amount_cents": 100,
    }, ctx["teller_h"])
    acct = validate_success(api.get_account(ctx["account"]["id"], MGR))
    assert acct["balance_cents"] == 0
    exp = validate_success(api.get_expected_cash(ctx["drawer"]["id"], MGR))
    assert exp["expected_cash_cents"] == 0


# --- Difficulty: buy_sell_movements_conserve_branch_cash_total ---

def _buy_sell_setup(api):
    ctx = basic_setup(api, account_balance=0)
    return ctx


def test_buy_conserves_branch_cash_total(api):
    """PRD §3.2: "Buying moves cash from vault to drawer" — the branch's total
    physical cash (vault plus drawers) is unchanged by the movement.

    Design: Difficulty/compensating_invariant/buy_sell_movements_conserve_branch_cash_total
    """
    ctx = _buy_sell_setup(api)
    drawer = validate_success(api.buy_from_vault(ctx["drawer"]["id"], 120_000, ctx["teller_h"]))
    branch = validate_success(api.get_branch(ctx["branch"]["id"], MGR))
    assert drawer["cash_balance_cents"] == 120_000
    assert branch["vault_cash_cents"] == 49_880_000
    assert branch["vault_cash_cents"] + drawer["cash_balance_cents"] == 50_000_000


def test_sell_conserves_branch_cash_total_after_external_deposit(api):
    """PRD §3.2: "Selling moves cash drawer to vault" — only customer cash
    changes the branch total; the sell itself adds nothing and removes nothing.

    Design: Difficulty/compensating_invariant/buy_sell_movements_conserve_branch_cash_total
    """
    ctx = _buy_sell_setup(api)
    get_success_data(api.buy_from_vault(ctx["drawer"]["id"], 120_000, ctx["teller_h"]))
    deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 900_000)
    drawer = validate_success(api.sell_to_vault(ctx["drawer"]["id"], 60_000, ctx["teller_h"]))
    branch = validate_success(api.get_branch(ctx["branch"]["id"], MGR))
    assert drawer["cash_balance_cents"] == 960_000
    assert branch["vault_cash_cents"] == 49_940_000
    assert branch["vault_cash_cents"] + drawer["cash_balance_cents"] == 50_900_000

# --- Difficulty: drawer_expected_strict_vs_lenient_with_instrument ---
from test_helpers import issue_instrument


def test_expected_cash_strict_includes_instrument_lenient_excludes(api):
    """PRD §3.2: "This is the `STRICT` reading ... A preview reading,
    `LENIENT`, treats instrument-purchase cash as vault-settled and excludes
    it; the two readings diverge precisely when instruments have been purchased
    at the window."

    Design: Difficulty/dual_variant_calc/drawer_expected_strict_vs_lenient_with_instrument
    """
    ctx = basic_setup(api, account_balance=0)
    issue_instrument(api, ctx["drawer"], ctx["account"], ctx["teller"],
                     300_000, "CASHIERS_CHECK")
    strict = validate_success(api.get_expected_cash(ctx["drawer"]["id"], MGR))
    assert strict["expected_cash_cents"] == 300_800  # 300000 face + 800 fee
    lenient = validate_success(api.get_expected_cash(ctx["drawer"]["id"], MGR, variant="LENIENT"))
    assert lenient["expected_cash_cents"] == 0


def test_stored_expected_cash_defaults_to_strict(api):
    """PRD §3.2: "This is the `STRICT` reading, and it is the value the close
    relies on." and "the drawer's `last_close_variant` records which reading
    the most recent close used, and it is always `STRICT`."

    Design: Difficulty/dual_variant_calc/drawer_expected_strict_vs_lenient_with_instrument
    """
    ctx = basic_setup(api, account_balance=0)
    issue_instrument(api, ctx["drawer"], ctx["account"], ctx["teller"],
                     300_000, "CASHIERS_CHECK")
    drawer = validate_success(api.get_drawer(ctx["drawer"]["id"], MGR))
    assert drawer["expected_cash_cents"] == 300_800
    # close ceremony uses STRICT: counting the physical 300800 must balance
    validate_success(api.count_drawer(ctx["drawer"]["id"], 300_800, ctx["teller_h"]))
    attested = validate_success(api.attest_drawer(ctx["drawer"]["id"], MGR))
    assert attested["status"] == "BALANCED"
    assert attested["variance_cents"] == 0
    assert attested["last_close_variant"] == "STRICT"
