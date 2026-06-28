"""Sweeping idle cash into investments: the investable-cash calculation, the strict
threshold boundary, unwind conservation, OCC staleness, and the UNWOUND terminal state.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
)
from test_helpers.fixtures import (
    ADMIN, setup_active_account_with_cash, account_version,
)
from test_helpers.api_client import api_client

ADMIN_HDR = ADMIN


# ── investable_cash_sweep_nested_min_floor (Difficulty/combinatorial_formula) ─

def test_sweep_requested_cap_floored_to_increment(api):
    """PRD §3.5: "First it determines the excess cash as the greater of zero and
    `cash_balance_cents` minus `invest_threshold_cents`. Then it caps the move by the
    request: the cap is `requested_amount_cents` if one was supplied, otherwise the full
    excess cash. The sweepable raw amount is the smaller of the excess cash and that cap.
    The actual `swept_amount_cents` is the sweepable raw amount floored down to the
    nearest whole multiple of `sweep_increment_cents`."

    cash 250000, threshold 200000 (excess 50000), increment 10000, requested 23000:
    min(50000, 23000)=23000 -> floor(23000/10000)*10000 = 20000.

    Design: Difficulty/combinatorial_formula/investable_cash_sweep_nested_min_floor
    """
    account, holder, _c = setup_active_account_with_cash(amount_cents=250000,
                                                         clock="2026-02-01T00:00:00Z")
    v = account_version(account["id"])
    res = api.create_sweep(account["id"],
                           {"requested_amount_cents": 23000,
                            "expected_account_version": v}, ADMIN_HDR)
    sweep = validate_success(res, 201)
    assert sweep["swept_amount_cents"] == 20000


def test_sweep_moves_cash_to_invested(api):
    """PRD §3.5: "A successful sweep is recorded with `status` `EXECUTED`; the account's
    `cash_balance_cents` decreases by `swept_amount_cents` while its
    `invested_balance_cents` increases by the same amount, and the account's `version`
    increments by one."

    After a 20000 sweep, cash 250000 -> 230000 and invested 0 -> 20000.

    Design: Difficulty/combinatorial_formula/investable_cash_sweep_nested_min_floor
    """
    account, holder, _c = setup_active_account_with_cash(amount_cents=250000,
                                                         clock="2026-02-01T00:00:00Z")
    v = account_version(account["id"])
    validate_success(
        api.create_sweep(account["id"],
                         {"requested_amount_cents": 23000,
                          "expected_account_version": v}, ADMIN_HDR), 201)
    acct = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert acct["cash_balance_cents"] == 230000
    assert acct["invested_balance_cents"] == 20000


# ── sweep_threshold_strict_greater_boundary (Difficulty/boundary_precision) ──

def test_sweep_at_exact_threshold_rejected(api):
    """PRD §3.5: "The threshold boundary is strict: `cash_balance_cents` must be strictly
    greater than `invest_threshold_cents` to yield anything, and at exactly the threshold
    the swept amount is zero. If the computed `swept_amount_cents` comes out as zero, the
    sweep is rejected with `ERR_NOTHING_TO_SWEEP` and no sweep row is persisted."

    cash exactly 200000 == invest_threshold_cents -> swept 0 -> ERR_NOTHING_TO_SWEEP.

    Design: Difficulty/boundary_precision_check/sweep_threshold_strict_greater_boundary
    """
    account, holder, _c = setup_active_account_with_cash(amount_cents=200000,
                                                         clock="2026-03-01T00:00:00Z")
    v = account_version(account["id"])
    res = api.create_sweep(account["id"], {"expected_account_version": v}, ADMIN_HDR)
    validate_error(res, ApiErrorId.ERR_NOTHING_TO_SWEEP)


def test_sweep_at_exact_threshold_persists_no_sweep(api):
    """PRD §3.5: "If the computed `swept_amount_cents` comes out as zero, the sweep is
    rejected with `ERR_NOTHING_TO_SWEEP` and no sweep row is persisted."

    With cash exactly at the threshold, no InvestmentSweep is persisted and
    invested_balance_cents stays 0.

    Design: Difficulty/boundary_precision_check/sweep_threshold_strict_greater_boundary
    """
    account, holder, _c = setup_active_account_with_cash(amount_cents=200000,
                                                         clock="2026-03-01T00:00:00Z")
    v = account_version(account["id"])
    validate_error(api.create_sweep(account["id"], {"expected_account_version": v},
                                    ADMIN_HDR),
                   ApiErrorId.ERR_NOTHING_TO_SWEEP)
    acct = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert acct["invested_balance_cents"] == 0


# ── sweep_unwind_conserves_cash_plus_invested (Difficulty/compensating_invariant) ─

def test_sweep_unwind_restores_cash_and_zeroes_invested(api):
    """PRD §3.5: "An admin may unwind an `EXECUTED` sweep — permitted only from
    `EXECUTED` (else `ERR_INVALID_STATE`) — which moves it to `UNWOUND` and reverses the
    move: `invested_balance_cents` decreases by `swept_amount_cents` and
    `cash_balance_cents` increases by the same amount, conserving the cash-plus-invested
    total."

    Sweep 300000 of 500000 cash -> cash 200000 / invested 300000. Unwind -> cash 500000
    / invested 0.

    Design: Difficulty/compensating_invariant/sweep_unwind_conserves_cash_plus_invested
    """
    account, holder, _c = setup_active_account_with_cash(amount_cents=500000,
                                                         coverage_tier="FAMILY",
                                                         clock="2026-03-01T00:00:00Z")
    v = account_version(account["id"])
    sweep = validate_success(
        api.create_sweep(account["id"],
                         {"requested_amount_cents": 300000,
                          "expected_account_version": v}, ADMIN_HDR), 201)
    unwound = validate_success(
        api.unwind_sweep(account["id"], sweep["id"], ADMIN_HDR), 200)
    assert unwound["status"] == "UNWOUND"
    acct = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert acct["cash_balance_cents"] == 500000
    assert acct["invested_balance_cents"] == 0


def test_sweep_plus_unwind_conserves_total(api):
    """PRD §3.5: "conserving the cash-plus-invested total."

    cash + invested == 500000 both after the sweep and after the unwind.

    Design: Difficulty/compensating_invariant/sweep_unwind_conserves_cash_plus_invested
    """
    account, holder, _c = setup_active_account_with_cash(amount_cents=500000,
                                                         coverage_tier="FAMILY",
                                                         clock="2026-03-01T00:00:00Z")
    v = account_version(account["id"])
    sweep = validate_success(
        api.create_sweep(account["id"],
                         {"requested_amount_cents": 300000,
                          "expected_account_version": v}, ADMIN_HDR), 201)
    mid = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert mid["cash_balance_cents"] + mid["invested_balance_cents"] == 500000
    validate_success(api.unwind_sweep(account["id"], sweep["id"], ADMIN_HDR), 200)
    after = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert after["cash_balance_cents"] + after["invested_balance_cents"] == 500000


# ── sweep_unwind_twice_terminal_lockdown (Corner/state_machines) ─────────────

def test_unwind_already_unwound_sweep_rejected(api):
    """PRD §3.5: "An admin may unwind an `EXECUTED` sweep — permitted only from
    `EXECUTED` (else `ERR_INVALID_STATE`)".

    A second unwind of an already-UNWOUND sweep is rejected with ERR_INVALID_STATE and
    balances are unchanged.

    Design: Corner/state_machines/sweep_unwind_twice_terminal_lockdown
    """
    account, holder, _c = setup_active_account_with_cash(amount_cents=250000,
                                                         clock="2026-03-01T00:00:00Z")
    v = account_version(account["id"])
    sweep = validate_success(
        api.create_sweep(account["id"], {"expected_account_version": v}, ADMIN_HDR), 201)
    validate_success(api.unwind_sweep(account["id"], sweep["id"], ADMIN_HDR), 200)
    res = api.unwind_sweep(account["id"], sweep["id"], ADMIN_HDR)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    acct = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert acct["cash_balance_cents"] == 250000
    assert acct["invested_balance_cents"] == 0


# ── occ_sweep_stale_version_rejected (Corner/cross_cutting_complexity_layers) ─

def test_sweep_with_stale_expected_version_rejected(api):
    """PRD §2.8: "When a sweep is created against an account, `expected_account_version`
    must equal the account's current `version`. If another writer has advanced the
    account's version since the caller last read it — for instance by posting a
    contribution or clearing a distribution, both of which legitimately move cash and
    bump the version — the caller's view of investable cash is stale and the sweep is
    rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412); no sweep is recorded."

    Design: Corner/cross_cutting_complexity_layers/occ_sweep_stale_version_rejected
    """
    account, holder, _c = setup_active_account_with_cash(amount_cents=250000,
                                                         coverage_tier="FAMILY",
                                                         clock="2026-03-01T00:00:00Z")
    stale_v = account_version(account["id"])
    # Advance the version with a second posted contribution.
    from test_helpers.fixtures import create_and_post_contribution
    create_and_post_contribution(account["id"], "INDIVIDUAL", 10000)
    res = api.create_sweep(account["id"],
                           {"requested_amount_cents": 50000,
                            "expected_account_version": stale_v}, ADMIN_HDR)
    validate_error(res, ApiErrorId.ERR_STALE_ACCOUNT_VERSION)
    acct = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert acct["invested_balance_cents"] == 0
