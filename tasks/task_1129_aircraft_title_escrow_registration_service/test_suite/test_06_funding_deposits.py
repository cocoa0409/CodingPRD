"""Funding: exact-cent FUNDED threshold, deposit/return conservation, FUNDED
revert, ON_HOLD block, and deposit OCC (PRD §3.5, §2.7, §3.10)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_escrow_money_invariants,
    create_deposit,
    create_deposit_payload,
    get_escrow_file,
    get_statement,
    return_deposit,
    setup_cleared_file,
    setup_funded_file,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]

DUE = 250_560_553  # price 250,000,000 / annual 120,000 / DAILY close 2026-06-30
HIGH_PRICE_OVERRIDES = {
    "purchase_price_cents": 250_000_000,
    "annual_registration_fee_cents": 120_000,
}


class TestFundingThresholdExactCent:
    def test_one_cent_below_due_leaves_file_cleared(self, api):
        """PRD §3.5: "If the file was `CLEARED` and the new `total_funded_cents`
        is greater than or equal to `buyer_amount_due_cents` — equality counts —
        the file transitions to `FUNDED` automatically."

        At due - 1 the inclusive threshold is not met.

        Design: Difficulty/boundary_precision_check/b1_funding_threshold_exact_cent
        """
        ctx = setup_cleared_file(file_overrides=dict(HIGH_PRICE_OVERRIDES))
        assert get_statement(ctx["file"]["id"])["buyer_amount_due_cents"] == DUE

        create_deposit(ctx["file"]["id"], ctx["buyer"]["id"], DUE - 1)
        after = get_escrow_file(ctx["file"]["id"])
        assert after["status"] == "CLEARED"
        assert after["total_funded_cents"] == DUE - 1

    def test_exact_due_flips_file_to_funded(self, api):
        """PRD §3.5: "If the file was `CLEARED` and the new `total_funded_cents`
        is greater than or equal to `buyer_amount_due_cents` — equality counts —
        the file transitions to `FUNDED` automatically."

        The final cent reaching exactly the due figure triggers the transition.

        Design: Difficulty/boundary_precision_check/b1_funding_threshold_exact_cent
        """
        ctx = setup_cleared_file(file_overrides=dict(HIGH_PRICE_OVERRIDES))
        create_deposit(ctx["file"]["id"], ctx["buyer"]["id"], DUE - 1)
        create_deposit(ctx["file"]["id"], ctx["buyer"]["id"], 1)
        after = get_escrow_file(ctx["file"]["id"])
        assert after["status"] == "FUNDED"
        assert after["total_funded_cents"] == DUE


class TestDepositReturnConservesCash:
    def test_deposit_raises_funded_and_balance(self, api):
        """PRD §3.5: "Its arrival triggers two recomputations:
        `total_funded_cents` becomes the sum of `amount_cents` across all
        `RECEIVED` deposits on the file, and `escrow_balance_cents` becomes that
        total minus the sum of `amount_cents` across all `RELEASED` disbursements
        on the file."

        Design: Difficulty/compensating_invariant/i1_deposit_return_conserves_escrow_cash
        """
        ctx = setup_cleared_file()
        before = get_escrow_file(ctx["file"]["id"])
        assert before["total_funded_cents"] == 0
        assert before["escrow_balance_cents"] == 0

        create_deposit(ctx["file"]["id"], ctx["buyer"]["id"], 5_000_000,
                       purpose="EARNEST_MONEY")
        after = get_escrow_file(ctx["file"]["id"])
        assert after["total_funded_cents"] == 5_000_000
        assert after["escrow_balance_cents"] == 5_000_000
        assert_escrow_money_invariants(after)

    def test_return_restores_exact_pre_action_figures(self, api):
        """PRD §3.5: "Returning stamps `returned_at` to the logical instant,
        transitions the deposit to `RETURNED`, and recomputes `total_funded_cents`
        and `escrow_balance_cents` with the returned row now excluded."

        The forward/compensating pair restores 0 / 0 with no drift.

        Design: Difficulty/compensating_invariant/i1_deposit_return_conserves_escrow_cash
        """
        ctx = setup_cleared_file()
        deposit = create_deposit(ctx["file"]["id"], ctx["buyer"]["id"], 5_000_000,
                                 purpose="EARNEST_MONEY")
        returned = return_deposit(deposit["id"])
        assert returned["status"] == "RETURNED"
        assert returned["returned_at"] is not None

        after = get_escrow_file(ctx["file"]["id"])
        assert after["total_funded_cents"] == 0
        assert after["escrow_balance_cents"] == 0
        assert_escrow_money_invariants(after)


class TestFundedRevertOnReturn:
    def test_return_dropping_below_due_reverts_to_cleared(self, api):
        """PRD §3.5: "If the file was `FUNDED` and the return drops
        `total_funded_cents` strictly below `buyer_amount_due_cents`, the file
        automatically reverts from `FUNDED` to `CLEARED`."

        Design: Corner/state_machines/s_funded_revert_on_return
        """
        ctx = setup_cleared_file()
        due = get_statement(ctx["file"]["id"])["buyer_amount_due_cents"]
        assert due == 10_150_000
        deposit = create_deposit(ctx["file"]["id"], ctx["buyer"]["id"], due)
        assert get_escrow_file(ctx["file"]["id"])["status"] == "FUNDED"

        return_deposit(deposit["id"])
        after = get_escrow_file(ctx["file"]["id"])
        assert after["status"] == "CLEARED"
        assert after["total_funded_cents"] == 0


class TestHoldBlocksChildMutation:
    def test_deposit_on_held_file_rejected_file_on_hold(self, api):
        """PRD §3.10: "While a file is `ON_HOLD`, every mutation scoped beneath
        the file — title search completion, lien actions, releases, deposits,
        disbursements, filings, documents — and the close action are rejected with
        `ERR_FILE_ON_HOLD`."

        The deposit carries a correct OCC version; the hold gate fires regardless.

        Design: Corner/state_machines/s_hold_blocks_deposit_returns_file_on_hold
        """
        ctx = setup_cleared_file()
        validate_success(api.hold_escrow_file(ctx["file"]["id"], OFFICER), 200)
        version = get_escrow_file(ctx["file"]["id"])["version"]
        res = api.create_deposit(
            ctx["file"]["id"],
            create_deposit_payload(ctx["buyer"]["id"], 1_000, version,
                                   purpose="EARNEST_MONEY"),
            OFFICER,
        )
        validate_error(res, ApiErrorId.ERR_FILE_ON_HOLD, expected_status=409)
        after = get_escrow_file(ctx["file"]["id"])
        assert after["status"] == "ON_HOLD"
        assert after["total_funded_cents"] == 0


class TestDepositOptimisticConcurrency:
    def test_second_deposit_with_same_version_rejected_stale(self, api):
        """PRD §2.7: "In each case, the presented value is compared against the
        file's current `version`; if another writer has advanced the file since
        the client last read it, the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412), and no mutation is applied."

        Two strictly sequential deposits carrying one captured version: the first
        succeeds and bumps the file version; the second is rejected and its write
        never applies (total_funded stays at the first deposit's 100).

        Design: Corner/cross_cutting_complexity_layers/x_occ_deposit_stale_version_412
        """
        ctx = setup_cleared_file()
        stale_version = get_escrow_file(ctx["file"]["id"])["version"]

        first = api.create_deposit(
            ctx["file"]["id"],
            create_deposit_payload(ctx["buyer"]["id"], 100, stale_version,
                                   purpose="EARNEST_MONEY"),
            OFFICER,
        )
        validate_success(first, 201)

        second = api.create_deposit(
            ctx["file"]["id"],
            create_deposit_payload(ctx["buyer"]["id"], 200, stale_version,
                                   purpose="EARNEST_MONEY"),
            OFFICER,
        )
        validate_error(second, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        after = get_escrow_file(ctx["file"]["id"])
        assert after["total_funded_cents"] == 100
        assert after["version"] == stale_version + 1
