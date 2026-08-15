"""The drawer day: open/carry-forward, count, expected-cash preview, suspend."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, basic_setup, deposit, teller_h, make_branch, make_teller,
    open_drawer,
)

MGR = TEST_USERS["manager_headers"]
HT = TEST_USERS["head_teller_headers"]


def test_second_drawer_same_day_rejected(api):
    """PRD §3.2: "One teller, one drawer, one day: a second open call while any
    session for that teller is unclosed — or a new session on a business date
    the teller has already used — is refused with `ERR_DRAWER_ALREADY_OPEN`."

    Design: Corner/errors/second_drawer_same_day_rejected
    """
    ctx = basic_setup(api)
    resp = api.open_drawer(ctx["teller"]["id"], HT)
    validate_error(resp, "ERR_DRAWER_ALREADY_OPEN", 409)


def test_suspended_teller_cannot_open_drawer_then_reinstated(api):
    """PRD §3.2: "A `SUSPENDED` teller's drawer cannot be opened at all
    (`ERR_TELLER_SUSPENDED`)".

    Design: Corner/state_machines/suspended_teller_cannot_open_drawer_then_reinstated
    """
    branch = make_branch(api)
    teller = make_teller(api, branch)
    get_success_data(api.suspend_teller(teller["id"], MGR))
    resp = api.open_drawer(teller["id"], HT)
    validate_error(resp, "ERR_TELLER_SUSPENDED", 409)
    data = validate_success(api.reinstate_teller(teller["id"], MGR))
    assert data["status"] == "ACTIVE"
    drawer = validate_success(api.open_drawer(teller["id"], HT), 201)
    assert drawer["status"] == "OPEN"


def test_drawer_count_from_counting_rejected(api):
    """PRD §3.8: "A drawer can only be counted from `OPEN` — a second count, or
    a count after close, is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/drawer_count_from_counting_rejected
    """
    ctx = basic_setup(api)
    validate_success(api.count_drawer(ctx["drawer"]["id"], 0, ctx["teller_h"]))
    resp = api.count_drawer(ctx["drawer"]["id"], 0, ctx["teller_h"])
    validate_error(resp, "ERR_INVALID_STATE", 409)


def test_attest_from_open_rejected(api):
    """PRD §3.8: "Then a second person — a `BranchManager` or an `Auditor` ...
    attests." The drawer must first be `COUNTING`; attesting an `OPEN` drawer
    is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/attest_from_open_rejected
    """
    ctx = basic_setup(api)
    resp = api.attest_drawer(ctx["drawer"]["id"], MGR)
    validate_error(resp, "ERR_INVALID_STATE", 409)


def test_expected_cash_read_endpoint_defaults_strict(api):
    """PRD §3.2: "Both readings are available through the drawer's expected-cash
    preview, which accepts an optional `variant` selector defaulting to `STRICT`
    and rejects any other value with `ERR_INVALID_REQUEST`."

    Design: Corner/endpoints/expected_cash_read_endpoint_defaults_strict
    """
    ctx = basic_setup(api, account_balance=0)
    deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 50_000)
    data = validate_success(api.get_expected_cash(ctx["drawer"]["id"], ctx["teller_h"]))
    assert data["variant"] == "STRICT"
    assert data["expected_cash_cents"] == 50_000
    resp = api.get_expected_cash(ctx["drawer"]["id"], ctx["teller_h"], variant="BOGUS")
    validate_error(resp, "ERR_INVALID_REQUEST", 400)


def test_posted_transaction_immediately_visible(api):
    """PRD §3.3: "All changes are visible immediately: a posted transaction is
    fully readable, with its computed fields, in the same instant, and the
    drawer's expected cash already reflects it."

    Design: Corner/consistency_model/posted_transaction_immediately_visible
    """
    ctx = basic_setup(api, account_balance=0)
    resp = api.post_transaction(ctx["drawer"]["id"], {
        "account_id": ctx["account"]["id"], "type": "CASH_DEPOSIT", "amount_cents": 12_345,
    }, ctx["teller_h"])
    txn = validate_success(resp, 201)
    assert txn["status"] == "POSTED"
    assert txn["fee_cents"] == 0
    reread = validate_success(api.get_transaction(txn["id"], ctx["teller_h"]))
    assert reread["amount_cents"] == 12_345
    exp = validate_success(api.get_expected_cash(ctx["drawer"]["id"], ctx["teller_h"]))
    assert exp["expected_cash_cents"] == 12_345


# --- Difficulty: drawer_close_reopen_cycle_carries_cash ---

def _close_first_day_with_50000(api):
    """Day 1: drawer with one 50000 deposit, counted 50000, BALANCED, CLOSED;
    clock advanced to the next calendar date."""
    ctx = basic_setup(api, account_balance=0)
    deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 50_000)
    validate_success(api.count_drawer(ctx["drawer"]["id"], 50_000, ctx["teller_h"]))
    attested = validate_success(api.attest_drawer(ctx["drawer"]["id"], MGR))
    closed = validate_success(api.close_drawer(ctx["drawer"]["id"], attested["version"], MGR))
    assert closed["status"] == "CLOSED"
    get_success_data(api.set_clock("2026-08-02T00:00:00Z", MGR))
    return ctx


def test_drawer_reopen_carries_counted_cash_forward(api):
    """PRD §3.2: "Opening a drawer carries forward cash: the new session's
    `cash_balance_cents` is initialized to the teller's previous `CLOSED`
    drawer's `counted_cash_cents` — the physically attested amount from the
    prior session — or to zero when no prior session exists."

    Design: Difficulty/non_linear_state_machine/drawer_close_reopen_cycle_carries_cash
    """
    ctx = _close_first_day_with_50000(api)
    d2 = validate_success(api.open_drawer(ctx["teller"]["id"], HT), 201)
    assert d2["status"] == "OPEN"
    assert d2["cash_balance_cents"] == 50_000
    assert d2["business_date"] == "2026-08-02"


def test_drawer_cycle_preserves_prior_closed_session(api):
    """PRD §3.8: "the drawer lifecycle is a cycle rather than a pipeline, the
    same teller's next business date opens a fresh `OPEN` drawer on top of the
    carried-forward count, exactly as §3.2 describes."

    Design: Difficulty/non_linear_state_machine/drawer_close_reopen_cycle_carries_cash
    """
    ctx = _close_first_day_with_50000(api)
    d1_id = ctx["drawer"]["id"]
    d2 = validate_success(api.open_drawer(ctx["teller"]["id"], HT), 201)
    assert d2["id"] != d1_id
    d1 = validate_success(api.get_drawer(d1_id, MGR))
    assert d1["status"] == "CLOSED"
    assert d1["counted_cash_cents"] == 50_000


def test_version_increments_on_every_mutation(api):
    """PRD §2.4: "`version` (an integer starting at 1 that increments by
    exactly one on every mutation)".

    Design: Corner/complexity_layers/version_increments_on_every_mutation
    """
    ctx = basic_setup(api)
    assert ctx["drawer"]["version"] == 1
    counted = validate_success(api.count_drawer(ctx["drawer"]["id"], 0, ctx["teller_h"]))
    assert counted["version"] == 2
    attested = validate_success(api.attest_drawer(ctx["drawer"]["id"], MGR))
    assert attested["version"] == 3
