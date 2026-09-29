"""
Compensating moves on the transfer desk, and the money they must leave untouched.

Two operations on the desk exist purely to undo an earlier one: rolling back the
custodial sweep on a servicing transfer, and clawing back a holdback release on
a purchase agreement. Both are judged on conservation rather than on their own
success code. The custodial rollback has to put borrower escrow and suspense
back on the individual loans it took them from — the per-loan split, not merely
the pooled total — and demote the data work stream a step. The holdback clawback
has to put the released cash back into the retained bucket, leave the sized
holdback itself alone, rewind the agreement's state, and make the rewind visible
to the concurrency guard that governs the next release.

This module pins both cycles: the conserved quantity before the forward move,
after it and after the compensation; the state demotion each compensation
causes; the refusals that guard a compensation taken from the wrong state or for
more than was moved; and the fact that either cycle can be taken repeatedly with
no drift.
"""

from test_helpers import (
    C, F, U,
    ApiClient, JsonDict,
    ERR_AGREEMENT_INVALID_STATE,
    ERR_CLAWBACK_EXCEEDS_RELEASED,
    ERR_ESCROW_NOT_MAPPED,
    ERR_STALE_AGREEMENT_VERSION,
    ERR_TRANSFER_INVALID_STATE,
    assert_custodial_funds,
    assert_dimensions,
    assert_holdback_split,
    assert_readiness,
    build_completed_transfer,
    build_settled_trade,
    loan_custodial_total,
    refresh_agreement,
    validate_error,
)

# Pool T carries four loans, each holding 100000 cents of borrower escrow and
# 25000 cents of unapplied suspense, so the pool's custodial cash is 500000.
ESCROW_PER_LOAN_CENTS = 100000
SUSPENSE_PER_LOAN_CENTS = 25000
POOL_LOAN_NUMBERS = ["T-0001", "T-0002", "T-0003", "T-0004"]
SWEPT_ESCROW_CENTS = 400000
SWEPT_SUSPENSE_CENTS = 100000

# The awarded pool prices at 118 bps over four state strata, so the purchase
# price is 472004 cents and the 6 percent holdback is sized at 28320 cents.
HOLDBACK_TOTAL_CENTS = 28320

# The transfer completes on 2026-09-01; representations run 30 days, so holdback
# release becomes eligible on 2026-10-01, while indemnification runs 45 days and
# does not expire until 2026-10-16.
RELEASE_WINDOW_CLOCK = "2026-10-01T00:00:00Z"

ROLLBACK_REASON = "transferee custodial account number was wrong on the mapping file"
CLAWBACK_REASON = "wire recalled after the seller failed the post-transfer audit"


def _swept_transfer(api: ApiClient) -> JsonDict:
    """A settled pool-T trade whose custodial funds have been swept."""
    env = build_settled_trade(api)
    F.map_data(api, env["transfer_id"], env["buyer_id"])
    env["transfer"] = F.map_escrow(api, env["transfer_id"], env["buyer_id"])
    return env


def _loans_by_number(api: ApiClient, env: JsonDict) -> JsonDict:
    """The pool's loans keyed by loan number, read as the acquiring servicer."""
    rows = F.list_loans(api, env["portfolio_id"], env["buyer_headers"])
    return {row["loan_number"]: row for row in rows}


def _release_window_trade(api: ApiClient) -> JsonDict:
    """A completed pool-T transfer with the clock inside the release window."""
    env = build_completed_transfer(api)
    F.set_clock(api, RELEASE_WINDOW_CLOCK)
    env["clock"] = RELEASE_WINDOW_CLOCK
    refresh_agreement(api, env)
    return env


def _released_trade(api: ApiClient) -> JsonDict:
    """The same trade with its whole holdback released to the seller."""
    env = _release_window_trade(api)
    env["version_before_release"] = env["agreement_version"]
    env["agreement"] = F.release_holdback(
        api, env["agreement_id"], env["agreement_version"])
    env["agreement_version"] = env["agreement"]["version"]
    return env


# ---------------------------------------------------------------------------
# The custodial sweep and its rollback
# ---------------------------------------------------------------------------
def test_custodial_sweep_pools_the_cash_and_zeroes_every_loan_balance(api):
    """
    The sweep moves all four loans' escrow and suspense onto the transfer and
    leaves every loan balance at zero, without changing the pool's total.

    PRD: "The transfer's `escrow_transferred_cents` is then set to the sum of `escrow_balance_cents` over those loans and each of those loan balances is set to 0; `suspense_transferred_cents` is set to the sum of `suspense_balance_cents` over the same loans and each of those is likewise set to 0."

    Design: Difficulty/compensating_invariant/escrow_mapping_rollback_restores_custodial_funds_without_drift
    """
    env = build_settled_trade(api)

    assert_custodial_funds(F.read_portfolio(api, env["portfolio_id"]),
                           C.POOL_T_CUSTODIAL_FUNDS_CENTS)
    before = _loans_by_number(api, env)
    for number in POOL_LOAN_NUMBERS:
        assert before[number]["escrow_balance_cents"] == ESCROW_PER_LOAN_CENTS
        assert before[number]["suspense_balance_cents"] == SUSPENSE_PER_LOAN_CENTS

    F.map_data(api, env["transfer_id"], env["buyer_id"])
    transfer = F.map_escrow(api, env["transfer_id"], env["buyer_id"])

    assert transfer["escrow_transferred_cents"] == SWEPT_ESCROW_CENTS
    assert transfer["suspense_transferred_cents"] == SWEPT_SUSPENSE_CENTS
    assert_dimensions(transfer, data="ESCROW_MAPPED")

    after = _loans_by_number(api, env)
    for number in POOL_LOAN_NUMBERS:
        assert after[number]["escrow_balance_cents"] == 0
        assert after[number]["suspense_balance_cents"] == 0
    assert loan_custodial_total(list(after.values())) == 0
    assert_custodial_funds(F.read_portfolio(api, env["portfolio_id"]),
                           C.POOL_T_CUSTODIAL_FUNDS_CENTS)


def test_custodial_sweep_snapshots_each_loan_balance_before_moving_it(api):
    """
    Each loan's own escrow and suspense figures are stamped on the loan before
    the sweep empties them, so the per-loan split survives the pooling.

    PRD: "Before anything moves, each loan on the included tape has its current balances snapshotted: `escrow_balance_at_mapping_cents` takes the value of `escrow_balance_cents` and `suspense_balance_at_mapping_cents` takes the value of `suspense_balance_cents`."

    Design: Difficulty/compensating_invariant/escrow_mapping_rollback_restores_custodial_funds_without_drift
    """
    env = build_settled_trade(api)

    before = _loans_by_number(api, env)
    for number in POOL_LOAN_NUMBERS:
        assert before[number]["escrow_balance_at_mapping_cents"] is None
        assert before[number]["suspense_balance_at_mapping_cents"] is None

    F.map_data(api, env["transfer_id"], env["buyer_id"])
    F.map_escrow(api, env["transfer_id"], env["buyer_id"])

    after = _loans_by_number(api, env)
    for number in POOL_LOAN_NUMBERS:
        assert (after[number]["escrow_balance_at_mapping_cents"]
                == ESCROW_PER_LOAN_CENTS)
        assert (after[number]["suspense_balance_at_mapping_cents"]
                == SUSPENSE_PER_LOAN_CENTS)


def test_rollback_restores_every_loan_balance_from_its_snapshot(api):
    """
    The rollback hands each loan back its own escrow and suspense figures,
    empties the transfer's two custodial buckets and demotes the data stream.

    PRD: "A rollback, which takes a free-text `reason`, restores each included tape loan's `escrow_balance_cents` and `suspense_balance_cents` from their `escrow_balance_at_mapping_cents` and `suspense_balance_at_mapping_cents` snapshots, resets both `escrow_transferred_cents` and `suspense_transferred_cents` to 0, moves `data_status` `ESCROW_MAPPED → MAPPED`, re-derives `readiness` to `NOT_READY`, and increments the transfer's `version` by 1."

    Design: Difficulty/compensating_invariant/escrow_mapping_rollback_restores_custodial_funds_without_drift
    """
    env = _swept_transfer(api)
    swept_version = env["transfer"]["version"]

    transfer = F.rollback_escrow(api, env["transfer_id"], env["buyer_id"],
                                 reason=ROLLBACK_REASON)

    assert transfer["escrow_transferred_cents"] == 0
    assert transfer["suspense_transferred_cents"] == 0
    assert_dimensions(transfer, data="MAPPED")
    assert_readiness(transfer, "NOT_READY")
    assert transfer["version"] == swept_version + 1

    restored = _loans_by_number(api, env)
    for number in POOL_LOAN_NUMBERS:
        assert restored[number]["escrow_balance_cents"] == ESCROW_PER_LOAN_CENTS
        assert (restored[number]["suspense_balance_cents"]
                == SUSPENSE_PER_LOAN_CENTS)
    assert (loan_custodial_total(list(restored.values()))
            == C.POOL_T_CUSTODIAL_FUNDS_CENTS)


def test_custodial_total_is_conserved_across_the_sweep_and_the_rollback(api):
    """
    The pool's custodial cash reads exactly 500000 cents before the sweep, while
    the transfer holds it, and again once the sweep has been rolled back.

    PRD: "Sweeping custodial funds into a transfer and rolling that sweep back must both leave this figure exactly where it was."

    Design: Difficulty/compensating_invariant/escrow_mapping_rollback_restores_custodial_funds_without_drift
    """
    env = build_settled_trade(api)
    assert_custodial_funds(F.read_portfolio(api, env["portfolio_id"]),
                           C.POOL_T_CUSTODIAL_FUNDS_CENTS)

    F.map_data(api, env["transfer_id"], env["buyer_id"])
    swept = F.map_escrow(api, env["transfer_id"], env["buyer_id"])
    assert_custodial_funds(F.read_portfolio(api, env["portfolio_id"]),
                           C.POOL_T_CUSTODIAL_FUNDS_CENTS)
    assert (swept["escrow_transferred_cents"] + swept["suspense_transferred_cents"]
            == C.POOL_T_CUSTODIAL_FUNDS_CENTS)

    rolled_back = F.rollback_escrow(api, env["transfer_id"], env["buyer_id"],
                                    reason=ROLLBACK_REASON)
    assert_custodial_funds(F.read_portfolio(api, env["portfolio_id"]),
                           C.POOL_T_CUSTODIAL_FUNDS_CENTS)
    held_on_loans = loan_custodial_total(
        list(_loans_by_number(api, env).values()))
    assert (held_on_loans
            + rolled_back["escrow_transferred_cents"]
            + rolled_back["suspense_transferred_cents"]
            == C.POOL_T_CUSTODIAL_FUNDS_CENTS)


def test_sweep_can_be_retaken_after_a_rollback_without_drift(api):
    """
    Sweeping, rolling back and sweeping again reproduces exactly the same two
    custodial figures, so the cycle can be taken any number of times.

    PRD: "The custodial total returns to exactly its pre-sweep value with no drift, and a rollback attempted while `data_status` is anything other than `ESCROW_MAPPED` is refused with `ERR_TRANSFER_INVALID_STATE`."

    Design: Difficulty/compensating_invariant/escrow_mapping_rollback_restores_custodial_funds_without_drift
    """
    env = _swept_transfer(api)

    for _cycle in range(2):
        F.rollback_escrow(api, env["transfer_id"], env["buyer_id"],
                          reason=ROLLBACK_REASON)
        reswept = F.map_escrow(api, env["transfer_id"], env["buyer_id"])
        assert reswept["escrow_transferred_cents"] == SWEPT_ESCROW_CENTS
        assert reswept["suspense_transferred_cents"] == SWEPT_SUSPENSE_CENTS
        assert_dimensions(reswept, data="ESCROW_MAPPED")
        assert_custodial_funds(F.read_portfolio(api, env["portfolio_id"]),
                               C.POOL_T_CUSTODIAL_FUNDS_CENTS)
        swept_loans = _loans_by_number(api, env)
        for number in POOL_LOAN_NUMBERS:
            assert swept_loans[number]["escrow_balance_cents"] == 0
            assert swept_loans[number]["suspense_balance_cents"] == 0


def test_second_rollback_from_the_mapped_state_is_refused(api):
    """
    Once the sweep has been rolled back there is nothing left to compensate, so a
    second rollback is refused on state grounds and moves no money.

    PRD: "The custodial total returns to exactly its pre-sweep value with no drift, and a rollback attempted while `data_status` is anything other than `ESCROW_MAPPED` is refused with `ERR_TRANSFER_INVALID_STATE`."

    Design: Difficulty/compensating_invariant/escrow_mapping_rollback_restores_custodial_funds_without_drift
    """
    env = _swept_transfer(api)
    rolled_back = F.rollback_escrow(api, env["transfer_id"], env["buyer_id"],
                                    reason=ROLLBACK_REASON)

    response = api.rollback_escrow_mapping(
        env["transfer_id"], {"reason": ROLLBACK_REASON}, env["buyer_headers"])
    validate_error(response, ERR_TRANSFER_INVALID_STATE)

    unchanged = F.read_transfer(api, env["transfer_id"])
    assert unchanged["version"] == rolled_back["version"]
    assert unchanged["escrow_transferred_cents"] == 0
    assert unchanged["suspense_transferred_cents"] == 0
    assert_dimensions(unchanged, data="MAPPED")
    restored = _loans_by_number(api, env)
    for number in POOL_LOAN_NUMBERS:
        assert restored[number]["escrow_balance_cents"] == ESCROW_PER_LOAN_CENTS
        assert (restored[number]["suspense_balance_cents"]
                == SUSPENSE_PER_LOAN_CENTS)


def test_reconcile_after_a_rollback_is_refused_until_the_sweep_is_retaken(api):
    """
    Reconciliation needs custodial funds sitting on the transfer, so it is
    refused while the sweep stands rolled back.

    PRD: "Reconciliation requires that the sweep has happened — `data_status` must be `ESCROW_MAPPED` — and it is one of the three deliberate carve-outs of §2.12: a reconcile filed too early passes the transfer state check so that it can be refused with the specific `ERR_ESCROW_NOT_MAPPED` (HTTP 409) instead of a generic state error."

    Design: Difficulty/compensating_invariant/escrow_mapping_rollback_restores_custodial_funds_without_drift
    """
    env = _swept_transfer(api)
    F.rollback_escrow(api, env["transfer_id"], env["buyer_id"],
                      reason=ROLLBACK_REASON)

    response = api.reconcile(env["transfer_id"], env["buyer_headers"])
    validate_error(response, ERR_ESCROW_NOT_MAPPED)

    still_mapped = F.read_transfer(api, env["transfer_id"])
    assert_dimensions(still_mapped, data="MAPPED")
    assert still_mapped.get("reconciled_at") is None


# ---------------------------------------------------------------------------
# The holdback release and its clawback
# ---------------------------------------------------------------------------
def test_full_release_moves_the_retained_balance_into_the_released_bucket(api):
    """
    A complaint-free transfer releases the whole holdback, so the three buckets
    move from 28320 / 0 / 0 to 0 / 28320 / 0 with the sized holdback untouched.

    PRD: "The three holdback buckets then move together: `holdback_retained_cents` decreases by the gross release, `holdback_released_cents` increases by the net wire, and `holdback_applied_cents` increases by the charge — which is precisely why the identity of §2.11 survives every release."

    Design: Difficulty/compensating_invariant/holdback_clawback_rewinds_the_release_split_without_drift
    """
    env = _release_window_trade(api)

    opening = env["agreement"]
    assert opening["holdback_cents"] == HOLDBACK_TOTAL_CENTS
    assert_holdback_split(opening, retained=HOLDBACK_TOTAL_CENTS, released=0,
                          applied=0)

    released = F.release_holdback(api, env["agreement_id"],
                                  env["agreement_version"])

    assert released["holdback_cents"] == HOLDBACK_TOTAL_CENTS
    assert_holdback_split(released, retained=0,
                          released=HOLDBACK_TOTAL_CENTS, applied=0)


def test_full_release_before_indemnification_expiry_lands_in_holdback_released(api):
    """
    Exhausting the retained balance on 2026-10-01, while indemnification still
    runs to 2026-10-16, leaves the agreement clawable rather than closed.

    PRD: "A release that exhausts the balance *before* the indemnification period has run does **not** close the agreement; it lands in `HOLDBACK_RELEASED`, where it can still be clawed back."

    Design: Difficulty/compensating_invariant/holdback_clawback_rewinds_the_release_split_without_drift
    """
    env = _release_window_trade(api)
    assert env["agreement"]["status"] == "SETTLED"

    released = F.release_holdback(api, env["agreement_id"],
                                  env["agreement_version"])

    assert released["status"] == "HOLDBACK_RELEASED"
    assert released["holdback_retained_cents"] == 0
    assert released["holdback_released_cents"] == HOLDBACK_TOTAL_CENTS


def test_full_clawback_rewinds_the_agreement_to_settled(api):
    """
    Returning the entire released balance puts the agreement back in the state it
    released from, so the release decision can be taken again.

    PRD: "A clawback that returns the entire released balance — leaving `holdback_released_cents` at 0 — rewinds the agreement `HOLDBACK_RELEASED → SETTLED` so the release decision can be taken again; a partial clawback leaves the agreement in `HOLDBACK_RELEASED`."

    Design: Difficulty/compensating_invariant/holdback_clawback_rewinds_the_release_split_without_drift
    """
    env = _released_trade(api)
    assert env["agreement"]["status"] == "HOLDBACK_RELEASED"

    clawed_back = F.clawback_holdback(api, env["agreement_id"],
                                      HOLDBACK_TOTAL_CENTS,
                                      reason=CLAWBACK_REASON)

    assert clawed_back["status"] == "SETTLED"
    assert clawed_back["holdback_released_cents"] == 0
    assert clawed_back["version"] == env["agreement_version"] + 1


def test_full_clawback_restores_the_opening_three_way_split(api):
    """
    The clawback moves the released cash back into the retained bucket component
    by component, so the split reads 28320 / 0 / 0 again with no drift.

    PRD: "The clawback subtracts `amount_cents` from `holdback_released_cents` and adds the same amount to `holdback_retained_cents`, so no value is created or destroyed and the holdback identity is preserved exactly."

    Design: Difficulty/compensating_invariant/holdback_clawback_rewinds_the_release_split_without_drift
    """
    env = _released_trade(api)
    assert_holdback_split(env["agreement"], retained=0,
                          released=HOLDBACK_TOTAL_CENTS, applied=0)

    clawed_back = F.clawback_holdback(api, env["agreement_id"],
                                      HOLDBACK_TOTAL_CENTS,
                                      reason=CLAWBACK_REASON)

    assert clawed_back["holdback_cents"] == HOLDBACK_TOTAL_CENTS
    assert_holdback_split(clawed_back, retained=HOLDBACK_TOTAL_CENTS,
                          released=0, applied=0)

    reread = F.read_agreement(api, env["agreement_id"])
    assert reread["holdback_cents"] == HOLDBACK_TOTAL_CENTS
    assert_holdback_split(reread, retained=HOLDBACK_TOTAL_CENTS, released=0,
                          applied=0)


def test_partial_clawback_keeps_the_agreement_in_holdback_released(api):
    """
    A clawback of part of the released balance redistributes exactly that amount
    and leaves the agreement where it was.

    PRD: "A clawback that returns the entire released balance — leaving `holdback_released_cents` at 0 — rewinds the agreement `HOLDBACK_RELEASED → SETTLED` so the release decision can be taken again; a partial clawback leaves the agreement in `HOLDBACK_RELEASED`."

    Design: Difficulty/compensating_invariant/holdback_clawback_rewinds_the_release_split_without_drift
    """
    env = _released_trade(api)

    clawed_back = F.clawback_holdback(api, env["agreement_id"], 10000,
                                      reason=CLAWBACK_REASON)

    assert clawed_back["status"] == "HOLDBACK_RELEASED"
    assert clawed_back["holdback_cents"] == HOLDBACK_TOTAL_CENTS
    assert_holdback_split(clawed_back, retained=10000,
                          released=HOLDBACK_TOTAL_CENTS - 10000, applied=0)


def test_clawback_above_the_released_balance_is_refused(api):
    """
    A clawback of 28321 cents against a released balance of 28320 is refused, and
    the split is left straddling nothing.

    PRD: "The amount must be greater than 0 and must not exceed `holdback_released_cents`, else `ERR_CLAWBACK_EXCEEDS_RELEASED` (HTTP 422)."

    Design: Difficulty/compensating_invariant/holdback_clawback_rewinds_the_release_split_without_drift
    """
    env = _released_trade(api)

    response = api.create_holdback_clawback(
        env["agreement_id"],
        {"amount_cents": HOLDBACK_TOTAL_CENTS + 1, "reason": CLAWBACK_REASON},
        U.COMPLIANCE_2)
    validate_error(response, ERR_CLAWBACK_EXCEEDS_RELEASED)

    unchanged = F.read_agreement(api, env["agreement_id"])
    assert unchanged["status"] == "HOLDBACK_RELEASED"
    assert unchanged["version"] == env["agreement_version"]
    assert unchanged["holdback_cents"] == HOLDBACK_TOTAL_CENTS
    assert_holdback_split(unchanged, retained=0,
                          released=HOLDBACK_TOTAL_CENTS, applied=0)


def test_clawback_against_a_settled_agreement_is_refused(api):
    """
    The compensation is only available from the state the release produced, so a
    second clawback taken once the agreement has rewound is refused.

    PRD: "A `ComplianceOfficer` claws back against a `HOLDBACK_RELEASED` agreement, supplying `amount_cents` and a `reason`."

    Design: Difficulty/compensating_invariant/holdback_clawback_rewinds_the_release_split_without_drift
    """
    env = _released_trade(api)
    rewound = F.clawback_holdback(api, env["agreement_id"],
                                  HOLDBACK_TOTAL_CENTS,
                                  reason=CLAWBACK_REASON)
    assert rewound["status"] == "SETTLED"

    response = api.create_holdback_clawback(
        env["agreement_id"],
        {"amount_cents": HOLDBACK_TOTAL_CENTS, "reason": CLAWBACK_REASON},
        U.COMPLIANCE_2)
    validate_error(response, ERR_AGREEMENT_INVALID_STATE)

    unchanged = F.read_agreement(api, env["agreement_id"])
    assert unchanged["status"] == "SETTLED"
    assert unchanged["version"] == rewound["version"]
    assert_holdback_split(unchanged, retained=HOLDBACK_TOTAL_CENTS, released=0,
                          applied=0)


def test_release_refiled_with_the_pre_clawback_version_is_refused_as_stale(api):
    """
    The rewind is a mutation of the agreement, so the token observed before the
    release no longer opens the next release.

    PRD: "A mismatch fails with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412) and no holdback field changes."

    Design: Difficulty/compensating_invariant/holdback_clawback_rewinds_the_release_split_without_drift
    """
    env = _released_trade(api)
    stale_version = env["version_before_release"]
    rewound = F.clawback_holdback(api, env["agreement_id"],
                                  HOLDBACK_TOTAL_CENTS,
                                  reason=CLAWBACK_REASON)
    assert rewound["version"] > stale_version

    response = api.create_holdback_release(
        env["agreement_id"],
        {"expected_purchase_agreement_version": stale_version},
        U.COMPLIANCE_2)
    validate_error(response, ERR_STALE_AGREEMENT_VERSION)

    unchanged = F.read_agreement(api, env["agreement_id"])
    assert unchanged["version"] == rewound["version"]
    assert_holdback_split(unchanged, retained=HOLDBACK_TOTAL_CENTS, released=0,
                          applied=0)


def test_release_refiled_after_the_rewind_reproduces_the_same_split(api):
    """
    With the refreshed token the release can be taken again and lands on exactly
    the same three-way split as the first time, with no drift.

    PRD: "A clawback that returns the entire released balance — leaving `holdback_released_cents` at 0 — rewinds the agreement `HOLDBACK_RELEASED → SETTLED` so the release decision can be taken again; a partial clawback leaves the agreement in `HOLDBACK_RELEASED`."

    Design: Difficulty/compensating_invariant/holdback_clawback_rewinds_the_release_split_without_drift
    """
    env = _released_trade(api)
    F.clawback_holdback(api, env["agreement_id"], HOLDBACK_TOTAL_CENTS,
                        reason=CLAWBACK_REASON)

    refreshed = refresh_agreement(api, env)
    assert refreshed["status"] == "SETTLED"

    rereleased = F.release_holdback(api, env["agreement_id"],
                                    env["agreement_version"])

    assert rereleased["status"] == "HOLDBACK_RELEASED"
    assert rereleased["holdback_cents"] == HOLDBACK_TOTAL_CENTS
    assert_holdback_split(rereleased, retained=0,
                          released=HOLDBACK_TOTAL_CENTS, applied=0)
