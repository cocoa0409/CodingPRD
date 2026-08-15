"""Funds availability: hold capture, business-day release, waiver, void interplay."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, basic_setup, check_deposit,
)

MGR = TEST_USERS["manager_headers"]


def _hold_of(api, txn_id):
    holds = get_success_data(api.list_holds(MGR, {"transaction_id": txn_id}))
    assert len(holds) == 1
    return holds[0]


def test_hold_standard_vs_large_check_boundary(api):
    """PRD §3.7: "A face of 500000 cents or less produces a hold whose
    `hold_type` is `STANDARD`, with a `release_day_offset` of 2 ... A face even
    one cent larger produces a `hold_type` of `LARGE_CHECK` with a
    `release_day_offset` of 7."

    Design: Corner/calculations/hold_standard_vs_large_check_boundary
    """
    ctx = basic_setup(api, account_balance=0)
    tx1 = check_deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 500_000)
    tx2 = check_deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 500_001)
    h1 = _hold_of(api, tx1["id"])
    h2 = _hold_of(api, tx2["id"])
    assert h1["hold_type"] == "STANDARD" and h1["amount_cents"] == 480_000
    assert h1["release_day_offset"] == 2
    assert h2["hold_type"] == "LARGE_CHECK" and h2["amount_cents"] == 480_001
    assert h2["release_day_offset"] == 7


def test_hold_release_skips_weekend(api):
    """PRD §3.7: "the held funds release on the second business day after the
    deposit's business date" and §2.5: "adding *n* business days to a date
    walks forward over that many weekdays, never counting the starting date
    itself, and skips Saturdays and Sundays."

    Design: Corner/calculations/hold_release_skips_weekend
    """
    ctx = basic_setup(api, account_balance=0)
    get_success_data(api.set_clock("2026-08-06T00:00:00Z", MGR))  # Thursday
    tx = check_deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 100_000)
    get_success_data(api.set_clock("2026-08-08T00:00:00Z", MGR))  # Saturday
    assert _hold_of(api, tx["id"])["status"] == "ACTIVE"
    get_success_data(api.set_clock("2026-08-10T00:00:00Z", MGR))  # Monday
    assert _hold_of(api, tx["id"])["status"] == "RELEASED"
    acct = validate_success(api.get_account(ctx["account"]["id"], MGR))
    assert acct["balance_cents"] == 100_000


def test_hold_waiver_shortens_release_to_one_day(api):
    """PRD §3.7: "A `BranchManager` may waive an `ACTIVE` hold for a known-good
    customer, moving it to `WAIVED` and shortening its `release_day_offset` to
    1 — the funds then release one business day after the deposit date, through
    the same automatic path, and the waiver is memorialized as an `Approval`
    with `action_type` `HOLD_WAIVER`."

    Design: Corner/calculations/hold_waiver_shortens_release_to_one_day
    """
    ctx = basic_setup(api, account_balance=0)
    get_success_data(api.set_clock("2026-08-03T00:00:00Z", MGR))  # Monday
    tx = check_deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 700_000)
    hold = _hold_of(api, tx["id"])
    assert hold["release_day_offset"] == 7
    waived = validate_success(api.waive_hold(hold["id"], MGR))
    assert waived["status"] == "WAIVED"
    assert waived["release_day_offset"] == 1
    get_success_data(api.set_clock("2026-08-04T00:00:00Z", MGR))  # Tuesday
    final = validate_success(api.get_hold(hold["id"], MGR))
    assert final["status"] == "RELEASED"
    acct = validate_success(api.get_account(ctx["account"]["id"], MGR))
    assert acct["balance_cents"] == 700_000
    approvals = get_success_data(api.list_approvals(MGR, {"branch_id": ctx["branch"]["id"]}))
    assert approvals[0]["action_type"] == "HOLD_WAIVER"
    assert approvals[0]["status"] == "APPROVED"


def test_void_after_hold_release_rejected(api):
    """PRD §3.10: "a check deposit whose hold has already released on schedule
    (or was waived and released) cannot be voided at all: the attempt is
    `ERR_HOLD_ALREADY_RELEASED`, because the customer may already have spent
    those funds."

    Design: Corner/errors/void_after_hold_release_rejected
    """
    ctx = basic_setup(api, account_balance=0)
    get_success_data(api.set_clock("2026-08-03T00:00:00Z", MGR))  # Monday
    tx = check_deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 100_000)
    get_success_data(api.set_clock("2026-08-05T00:00:00Z", MGR))  # Wednesday: released
    resp = api.void_transaction(tx["id"], MGR)
    validate_error(resp, "ERR_HOLD_ALREADY_RELEASED", 409)
    acct = validate_success(api.get_account(ctx["account"]["id"], MGR))
    assert acct["balance_cents"] == 100_000


def test_check_deposit_post_splits_credit_and_hold(api):
    """PRD §3.7: "the account is credited immediately only with the first 20000
    cents of the check's face — the next-day availability portion — or with the
    full face when the check is smaller than that. The remainder is captured
    into a `Hold` on the account".

    Design: Difficulty/compensating_invariant/check_deposit_post_then_void_conserves_account_balance
    """
    ctx = basic_setup(api, account_balance=100_000)
    tx = check_deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 700_000)
    acct = validate_success(api.get_account(ctx["account"]["id"], MGR))
    assert acct["balance_cents"] == 120_000
    hold = _hold_of(api, tx["id"])
    assert hold["amount_cents"] == 680_000
    assert hold["hold_type"] == "LARGE_CHECK"
    assert hold["release_day_offset"] == 7
    assert hold["status"] == "ACTIVE"
    # 20000 immediate + 680000 held == 700000 face: nothing created, nothing lost
    assert (acct["balance_cents"] - 100_000) + hold["amount_cents"] == 700_000


def test_void_check_deposit_conserves_account_balance(api):
    """PRD §3.10: "The account's balance is restored — a deposit's credit is
    subtracted back ... a check deposit's immediately-credited portion is
    subtracted back" and "the hold moves to `RELEASED` but, unlike a scheduled
    release, credits nothing".

    Design: Difficulty/compensating_invariant/check_deposit_post_then_void_conserves_account_balance
    """
    ctx = basic_setup(api, account_balance=100_000)
    tx = check_deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 700_000)
    validate_success(api.void_transaction(tx["id"], MGR))
    acct = validate_success(api.get_account(ctx["account"]["id"], MGR))
    assert acct["balance_cents"] == 100_000
    hold = _hold_of(api, tx["id"])
    assert hold["status"] == "RELEASED"
