"""Every compensating path must return the conserved quantity exactly."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as fac
from test_helpers.assertions import assert_total_count
from test_helpers.constants import (
    ENTRY_ACCRUAL,
    ENTRY_DISPUTE_ADJUSTMENT,
    ENTRY_FUND_CREDIT,
    ENTRY_PAYOUT_DEBIT,
    ENTRY_PAYOUT_FEE,
    ENTRY_PAYOUT_REVERSAL,
    ENTRY_WITHHOLDING,
    ENTRY_WITHHOLDING_TRUE_UP,
    FAILURE_CODE_BANK_REJECTED,
    FUND_ALLOCATED,
    FUND_DISBURSED,
    FUND_DRAFT,
    PAYOUT_FAILED,
    PAYOUT_STATE_ACCRUING,
    PERIOD_FINALIZED,
    STATEMENT_FINALIZED,
    STATEMENT_UNDER_DISPUTE,
    VARIANT_FINAL,
)
from test_helpers.fixtures import (
    close,
    eligible_creator,
    eligible_creator_with_watch_time,
    finalize,
    july_period,
    new_creator,
    payable_creator,
    post_event,
    refresh_creator,
    statement_for,
    tips_product,
)
from test_helpers.test_users import ADMIN, FINANCE, make_creator_headers


def _mixed_funding_channel(api):
    """A channel whose payable mixes statement money with fund credit."""
    creator, _profile = payable_creator(api, display_name="Hal Rev")
    product = tips_product(api)
    period = july_period(api)
    post_event(api, creator["id"], product["id"], gross_amount_cents=40000)
    close(api, period["id"])
    # PRD 3.9: "The named period's `status` must be `OPEN` or `CLOSED`; a
    # `FINALIZED` period admits no new fund", so the fund is declared while the
    # period is still `CLOSED` — finalizing its only statement would move the
    # period to `FINALIZED` first.
    fund = get_success_data(
        api.create_fund(
            fac.fund_payload(period["id"], name="July Bonus", total_pool_cents=5000),
            ADMIN,
        )
    )
    allocated = validate_success(
        api.allocate_fund(fund["id"], fac.allocate_payload(fund["version"]), FINANCE)
    )
    assert allocated["allocated_cents"] == 5000
    assert allocated["unallocated_remainder_cents"] == 0
    disbursed = validate_success(api.disburse_fund(fund["id"], FINANCE))
    assert disbursed["status"] == FUND_DISBURSED
    statement = finalize(api, statement_for(api, creator["id"], period["id"])["id"])
    return creator, statement


def test_a_mixed_funded_payout_empties_both_pools_at_once(api):
    """The disbursement draws the statement money and the fund credit together.

    The 25000-cent payable carries 5000 of fund credit, the bank fee is 200 and
    the amount 24800, and afterwards the ledger, the fund credit pool and the
    available balance are all zero.

    Design: Difficulty/compensating_invariant/failed_payout_reversal_restores_ledger_and_fund_credit_exactly
    """
    creator, _statement = _mixed_funding_channel(api)
    before = refresh_creator(api, creator["id"])
    assert before["ledger_balance_cents"] == 25000
    assert before["fund_credit_balance_cents"] == 5000
    assert before["available_balance_cents"] == 25000
    assert before["statement_payable_cents"] == 20000

    payout = validate_success(
        api.create_payout(fac.payout_payload(creator["id"]), FINANCE), 201
    )
    assert payout["payable_before_fee_cents"] == 25000
    assert payout["fund_credit_cents"] == 5000
    assert payout["fee_cents"] == 200
    assert payout["amount_cents"] == 24800

    midway = refresh_creator(api, creator["id"])
    assert midway["ledger_balance_cents"] == 0
    assert midway["fund_credit_balance_cents"] == 0
    assert midway["available_balance_cents"] == 0


def test_the_failure_reversal_includes_the_fee_and_restores_the_fund_pool(api):
    """One reversal of 25000 restores both pools without double counting.

    The reversal carries the fee as well as the amount, the fund credit returns
    to its own pool rather than into the ledger, the statement is detached, and
    the five ledger rows sum back to the pre-payout balance.

    Design: Difficulty/compensating_invariant/failed_payout_reversal_restores_ledger_and_fund_credit_exactly
    """
    creator, statement = _mixed_funding_channel(api)
    payout = validate_success(
        api.create_payout(fac.payout_payload(creator["id"]), FINANCE), 201
    )
    get_success_data(api.submit_payout(payout["id"], FINANCE))
    failed = get_success_data(
        api.record_settlement(
            payout["id"],
            fac.settlement_payload(
                "FAILED", failure_code=FAILURE_CODE_BANK_REJECTED
            ),
            FINANCE,
        )
    )
    assert failed["state"] == PAYOUT_FAILED
    assert failed["retry_count"] == 0

    after = refresh_creator(api, creator["id"])
    assert after["ledger_balance_cents"] == 25000
    assert after["fund_credit_balance_cents"] == 5000
    assert after["available_balance_cents"] == 25000
    assert after["statement_payable_cents"] == 20000
    assert after["payout_state"] == PAYOUT_STATE_ACCRUING
    assert after["consecutive_payment_failures"] == 1

    rows = assert_total_count(api.list_ledger_entries(creator["id"], FINANCE), 5)
    assert sum(row["amount_cents"] for row in rows) == 25000
    assert [row["entry_type"] for row in rows] == [
        ENTRY_ACCRUAL,
        ENTRY_FUND_CREDIT,
        ENTRY_PAYOUT_DEBIT,
        ENTRY_PAYOUT_FEE,
        ENTRY_PAYOUT_REVERSAL,
    ]
    reversals = assert_total_count(
        api.list_ledger_entries(
            creator["id"], FINANCE, {"entry_type": ENTRY_PAYOUT_REVERSAL}
        ),
        1,
    )
    assert reversals[0]["amount_cents"] == 25000
    assert reversals[0]["amount_cents"] != 24800

    detached = validate_success(api.get_statement(statement["id"], FINANCE))
    assert detached["status"] == STATEMENT_FINALIZED
    assert detached["payout_id"] is None


def _three_channel_fund(api):
    ids = []
    for name, minutes in (
        ("Ida Pool", 500000),
        ("Jon Pool", 300000),
        ("Kim Pool", 200000),
    ):
        creator = eligible_creator_with_watch_time(
            api, minutes, display_name=name
        )
        ids.append(creator["id"])
    period = july_period(api)
    fund = get_success_data(
        api.create_fund(
            fac.fund_payload(period["id"], name="Q3 Creator Fund"), ADMIN
        )
    )
    assert fund["total_pool_cents"] == 100000
    assert fund["unallocated_remainder_cents"] == 100000
    assert fund["max_allocation_cents"] == 2000000
    return ids, fund


def _active_amount(api, fund_id, creator_id):
    rows = validate_success(
        api.list_fund_allocations(
            fund_id, ADMIN, {"status": "ACTIVE", "creator_id": creator_id}
        )
    )
    return rows[0]


def test_the_pool_is_conserved_across_a_first_and_a_superseding_run(api):
    """Re-allocating after a metrics correction still hands out every cent.

    The first run splits the pool 50000, 30000 and 20000 with nothing left over,
    and the second run over the corrected watch times gives the leftover cent to
    the highest-ranked recipient so the total is still the whole pool.

    Design: Difficulty/compensating_invariant/fund_pool_conserved_across_allocate_supersede_and_void
    """
    ids, fund = _three_channel_fund(api)

    first_run = validate_success(
        api.allocate_fund(fund["id"], fac.allocate_payload(fund["version"]), FINANCE)
    )
    assert first_run["allocated_cents"] == 100000
    assert first_run["unallocated_remainder_cents"] == 0
    assert (
        first_run["allocated_cents"] + first_run["unallocated_remainder_cents"]
    ) == 100000
    assert first_run["allocation_run_count"] == 1
    rows = assert_total_count(
        api.list_fund_allocations(fund["id"], ADMIN, {"status": "ACTIVE"}), 3
    )
    assert [row["amount_cents"] for row in sorted(rows, key=lambda r: r["rank"])] == [
        50000,
        30000,
        20000,
    ]
    top = _active_amount(api, fund["id"], ids[0])
    assert top["amount_cents"] == 50000
    assert top["rank"] == 1

    patched = get_success_data(
        api.patch_creator_metrics(
            ids[2], fac.metrics_payload(watch_time_minutes_365d=400000), ADMIN
        )
    )
    assert patched["watch_time_minutes_365d"] == 400000

    second_run = validate_success(
        api.allocate_fund(
            fund["id"], fac.allocate_payload(first_run["version"]), FINANCE
        )
    )
    assert second_run["allocated_cents"] == 100000
    assert second_run["unallocated_remainder_cents"] == 0
    assert second_run["allocation_run_count"] == 2
    assert _active_amount(api, fund["id"], ids[0])["amount_cents"] == 41667
    assert _active_amount(api, fund["id"], ids[0])["amount_cents"] != 41666
    assert _active_amount(api, fund["id"], ids[2])["amount_cents"] == 33333
    assert _active_amount(api, fund["id"], ids[1])["amount_cents"] == 25000

    superseded = validate_success(
        api.list_fund_allocations(
            fund["id"], ADMIN, {"status": "VOIDED", "creator_id": ids[0]}
        )
    )
    assert superseded[0]["void_reason"] == "SUPERSEDED_BY_REALLOCATION"


def test_voiding_returns_the_whole_pool_and_keeps_every_historical_row(api):
    """Discarding the set conserves the pool and retires nothing else.

    The fund returns to draft with the pool wholly unallocated while both runs
    remain counted, all six rows stay queryable with their two distinct void
    reasons, and no channel was ever credited.

    Design: Difficulty/compensating_invariant/fund_pool_conserved_across_allocate_supersede_and_void
    """
    ids, fund = _three_channel_fund(api)
    first_run = validate_success(
        api.allocate_fund(fund["id"], fac.allocate_payload(fund["version"]), FINANCE)
    )
    get_success_data(
        api.patch_creator_metrics(
            ids[2], fac.metrics_payload(watch_time_minutes_365d=400000), ADMIN
        )
    )
    second_run = validate_success(
        api.allocate_fund(
            fund["id"], fac.allocate_payload(first_run["version"]), FINANCE
        )
    )
    assert second_run["status"] == FUND_ALLOCATED

    voided = validate_success(
        api.void_fund_allocations(
            fund["id"],
            fac.void_allocations_payload(second_run["version"]),
            FINANCE,
        )
    )
    assert voided["allocated_cents"] == 0
    assert voided["unallocated_remainder_cents"] == 100000
    assert (
        voided["allocated_cents"] + voided["unallocated_remainder_cents"]
    ) == 100000
    assert voided["allocation_run_count"] == 2
    assert voided["status"] == FUND_DRAFT

    assert_total_count(
        api.list_fund_allocations(fund["id"], ADMIN, {"status": "ACTIVE"}), 0
    )
    history = assert_total_count(
        api.list_fund_allocations(fund["id"], ADMIN, {"status": "VOIDED"}), 6
    )
    reasons = [row["void_reason"] for row in history]
    assert reasons.count("SUPERSEDED_BY_REALLOCATION") == 3
    assert reasons.count("Programme cancelled by Finance.") == 3
    assert_total_count(api.list_fund_allocations(fund["id"], ADMIN), 6)

    validate_error(
        api.allocate_fund(
            fund["id"], fac.allocate_payload(second_run["version"]), FINANCE
        ),
        err.ERR_STALE_FUND_VERSION,
        412,
    )
    assert_total_count(api.list_ledger_entries(ids[0], FINANCE), 0)
    holder = refresh_creator(api, ids[0])
    assert holder["fund_credit_balance_cents"] == 0
    assert holder["available_balance_cents"] == 0


def _disputable_statement(api):
    creator = eligible_creator(api, display_name="Lev Claim")
    product = tips_product(api)
    period = july_period(api)
    event = post_event(api, creator["id"], product["id"], gross_amount_cents=10000)
    assert event["creator_share_cents"] == 5000
    close(api, period["id"])
    statement = finalize(api, statement_for(api, creator["id"], period["id"])["id"])
    assert statement["withholding_cents"] == 1200
    assert statement["net_payable_cents"] == 3800
    assert statement["withholding_variant"] == VARIANT_FINAL
    return creator, period, statement


def test_a_claim_above_the_net_payable_is_refused_outright(api):
    """One cent above the payable is not a claim the statement can carry.

    The statement keeps its finalized status and the projection, ledger and
    available balance all still show the full 3800 cents.

    Design: Difficulty/compensating_invariant/rejected_dispute_round_trip_restores_statement_payable_with_no_ledger_movement
    """
    creator, _period, statement = _disputable_statement(api)
    before = refresh_creator(api, creator["id"])
    assert before["statement_payable_cents"] == 3800
    assert before["ledger_balance_cents"] == 3800
    assert before["available_balance_cents"] == 3800

    validate_error(
        api.dispute_statement(
            statement["id"],
            fac.dispute_payload(
                3801,
                dispute_reason="Two tips from the 5th were mine, not a co-host's.",
            ),
            make_creator_headers(creator["id"]),
        ),
        err.ERR_DISPUTE_AMOUNT_EXCEEDS_STATEMENT,
        422,
    )
    assert validate_success(api.get_statement(statement["id"], FINANCE))["status"] == (
        STATEMENT_FINALIZED
    )


def test_opening_a_dispute_withdraws_the_whole_payable_not_the_claim(api):
    """A claim of 1000 removes the entire 3800 from the projection.

    No money field on the statement is rewritten and the ledger does not move,
    yet the available balance falls to zero for the duration of the dispute.

    Design: Difficulty/compensating_invariant/rejected_dispute_round_trip_restores_statement_payable_with_no_ledger_movement
    """
    creator, _period, statement = _disputable_statement(api)

    disputed = validate_success(
        api.dispute_statement(
            statement["id"],
            fac.dispute_payload(
                1000,
                dispute_reason="Two tips from the 5th were mine, not a co-host's.",
            ),
            make_creator_headers(creator["id"]),
        )
    )
    assert disputed["status"] == STATEMENT_UNDER_DISPUTE
    assert disputed["dispute_claimed_amount_cents"] == 1000
    assert disputed["net_payable_cents"] == 3800
    assert disputed["withholding_cents"] == 1200

    midway = refresh_creator(api, creator["id"])
    assert midway["statement_payable_cents"] == 0
    assert midway["ledger_balance_cents"] == 3800
    assert midway["available_balance_cents"] == 0


def test_a_rejected_dispute_is_a_perfect_no_op(api):
    """Rejecting restores the full payable and writes no ledger row at all.

    The statement returns to finalized with a zero adjustment, the withholding
    and net still sum to the original share, and the ledger holds exactly the
    two rows it held before the dispute with no adjustment entry.

    Design: Difficulty/compensating_invariant/rejected_dispute_round_trip_restores_statement_payable_with_no_ledger_movement
    """
    creator, period, statement = _disputable_statement(api)
    validate_success(
        api.dispute_statement(
            statement["id"],
            fac.dispute_payload(
                1000,
                dispute_reason="Two tips from the 5th were mine, not a co-host's.",
            ),
            make_creator_headers(creator["id"]),
        )
    )

    resolved = validate_success(
        api.resolve_dispute(
            statement["id"], fac.resolve_dispute_payload("REJECTED", 0), FINANCE
        )
    )
    assert resolved["status"] == STATEMENT_FINALIZED
    assert resolved["dispute_resolution"] == "REJECTED"
    assert resolved["dispute_adjustment_cents"] == 0
    assert resolved["net_payable_cents"] == 3800
    assert resolved["withholding_cents"] == 1200
    assert resolved["withholding_cents"] + resolved["net_payable_cents"] == 5000

    after = refresh_creator(api, creator["id"])
    assert after["statement_payable_cents"] == 3800
    assert after["ledger_balance_cents"] == 3800
    assert after["available_balance_cents"] == 3800

    rows = assert_total_count(api.list_ledger_entries(creator["id"], FINANCE), 2)
    assert [row["entry_type"] for row in rows] == [ENTRY_ACCRUAL, ENTRY_WITHHOLDING]
    assert_total_count(
        api.list_ledger_entries(
            creator["id"], FINANCE, {"entry_type": ENTRY_DISPUTE_ADJUSTMENT}
        ),
        0,
    )
    assert_total_count(
        api.list_ledger_entries(
            creator["id"], FINANCE, {"entry_type": ENTRY_WITHHOLDING_TRUE_UP}
        ),
        0,
    )
    reloaded = validate_success(api.get_period(period["id"], FINANCE))
    assert reloaded["status"] == PERIOD_FINALIZED
    assert reloaded["finalized_statement_count"] == 1
