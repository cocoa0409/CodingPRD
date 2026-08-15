"""Profit allocation: waterfall with caps, post/reverse compensation, gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_profit,
    allocation_line_for,
    assert_allocation_run,
    create_activity_account,
    create_allocation_run,
    create_open_campaign,
    get_account,
    get_program,
    setup_open_campaign_shop,
    setup_profit_program,
    setup_waterfall_scenario,
    transition_program,
    TEST_USERS,
    validate_error,
    validate_success,
)

DIRECTOR = TEST_USERS["director_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
TREASURER = TEST_USERS["treasurer_headers"]


class TestAllocationWaterfall:
    def test_caps_overflow_redistributes_proportionally(self, api):
        """PRD §3.8: "Third, a capped account's tentative credit is the
        smaller of its raw share and its remaining headroom — `cap_cents`
        minus its current `balance_cents` — while uncapped accounts have
        unlimited headroom. Fourth, the overflow left unabsorbed by capped
        accounts is redistributed among the still-eligible accounts (uncapped,
        or capped but below their ceiling) in proportion to their weights
        renormalized among the recipients, each share floored, iterating until
        nothing overflows or no eligible recipient remains"

        Design: Difficulty/combinatorial_formula/allocation_waterfall_caps_overflow
        """
        setup = setup_waterfall_scenario()
        run = setup["run"]
        assert_allocation_run(run)
        accounts = setup["accounts"]

        line_a = allocation_line_for(run, accounts["Band"]["id"])
        assert line_a["credit_cents"] == 30000, (
            f"raw share 50000 capped at 30000, got {line_a['credit_cents']}"
        )
        assert line_a["capped"] is True
        line_b = allocation_line_for(run, accounts["Drama"]["id"])
        assert line_b["credit_cents"] == 42000, (
            "30000 raw + floor(20000*30/50) = 12000 overflow share"
        )
        line_c = allocation_line_for(run, accounts["Robotics"]["id"])
        assert line_c["credit_cents"] == 28000, (
            "20000 raw + floor(20000*20/50) = 8000 overflow share"
        )
        total = sum(line["credit_cents"] for line in run["lines"])
        assert total == 100000, (
            f"conservation holds exactly with zero rounding dust, got {total}"
        )

    def test_draft_run_freezes_lines_without_moving_profit(self, api):
        """PRD §3.8: "Creation computes the distribution lines immediately and
        freezes them on the run, each line an `account_id`, its
        `credit_cents`, and a `capped` flag recording whether the account's
        cap limited its credit."
        PRD §3.8: "Posting credits each account's `balance_cents` by its
        line's credit, moves the same total from `undistributed_profit_cents`
        to `distributed_profit_cents` on the program, stamps `posted_at`, and
        leaves the run `POSTED`."

        Design: Difficulty/combinatorial_formula/allocation_waterfall_caps_overflow
        """
        setup = setup_waterfall_scenario()
        assert setup["run"]["status"] == "DRAFT"
        program = get_program(setup["program"]["id"])
        assert program["undistributed_profit_cents"] == 100000, (
            "lines are frozen at DRAFT; nothing moves until post"
        )
        for account in setup["accounts"].values():
            assert get_account(account["id"])["balance_cents"] == 0


class TestPostReverseConservation:
    def test_post_credits_accounts_and_moves_profit(self, api):
        """PRD §3.8: "Posting credits each account's `balance_cents` by its
        line's credit, moves the same total from `undistributed_profit_cents`
        to `distributed_profit_cents` on the program, stamps `posted_at`, and
        leaves the run `POSTED`."

        Design: Difficulty/compensating_invariant/allocation_post_reverse_conserves_balances
        """
        setup = setup_waterfall_scenario()
        transition_program(setup["program"]["id"], "CLOSED")
        posted = validate_success(
            api.post_allocation_run(setup["run"]["id"], TREASURER), 200
        )
        assert posted["status"] == "POSTED"
        assert get_account(setup["accounts"]["Band"]["id"])["balance_cents"] == 30000
        assert get_account(setup["accounts"]["Drama"]["id"])["balance_cents"] == 42000
        assert get_account(setup["accounts"]["Robotics"]["id"])["balance_cents"] == 28000

    def test_reverse_restores_every_balance_exactly(self, api):
        """PRD §3.8: "reversing a `POSTED` run debits each account back by its
        line credit, restores the total to `undistributed_profit_cents` out of
        `distributed_profit_cents`, and leaves the run `REVERSED` — a
        compensating action, not a deletion."

        Design: Difficulty/compensating_invariant/allocation_post_reverse_conserves_balances
        """
        setup = setup_waterfall_scenario()
        transition_program(setup["program"]["id"], "CLOSED")
        validate_success(api.post_allocation_run(setup["run"]["id"], TREASURER), 200)
        reversed_run = validate_success(
            api.reverse_allocation_run(setup["run"]["id"], TREASURER), 200
        )
        assert reversed_run["status"] == "REVERSED"
        for account in setup["accounts"].values():
            assert get_account(account["id"])["balance_cents"] == 0, (
                "the compensating action restores every balance exactly"
            )
        program = get_program(setup["program"]["id"])
        assert program["undistributed_profit_cents"] == 100000
        assert program["distributed_profit_cents"] == 0


class TestAllocationGates:
    def test_allocation_post_requires_program_closed(self, api):
        """PRD §2.8: "posting an allocation run requires it to be `CLOSED`,
        else `ERR_PROGRAM_NOT_CLOSED`."

        Design: Difficulty/cross_entity_state_dependency/allocation_post_requires_program_closed
        """
        setup = setup_profit_program(1000, accounts_spec=[("Band", 1, None)])
        run = create_allocation_run(setup["program"]["id"], 1000)
        res = api.post_allocation_run(run["id"], TREASURER)
        validate_error(res, ApiErrorId.ERR_PROGRAM_NOT_CLOSED, 409)

    def test_allocation_post_succeeds_after_program_closed(self, api):
        """PRD §3.8: "Only a `DRAFT` run can post, and only while the program
        is `CLOSED` — else `ERR_PROGRAM_NOT_CLOSED`."
        PRD §3.8: "Posting credits each account's `balance_cents` by its
        line's credit, moves the same total from `undistributed_profit_cents`
        to `distributed_profit_cents` on the program, stamps `posted_at`, and
        leaves the run `POSTED`."

        Design: Difficulty/cross_entity_state_dependency/allocation_post_requires_program_closed
        """
        setup = setup_profit_program(1000, accounts_spec=[("Band", 1, None)])
        run = create_allocation_run(setup["program"]["id"], 1000)
        transition_program(setup["program"]["id"], "CLOSED")
        posted = validate_success(api.post_allocation_run(run["id"], TREASURER), 200)
        assert posted["status"] == "POSTED"
        assert get_account(setup["accounts"]["Band"]["id"])["balance_cents"] == 1000

    def test_allocation_exceeds_undistributed_profit_rejected(self, api):
        """PRD §3.8: "a `distributable_cents` amount, which must be at least 1
        and no more than the program's current `undistributed_profit_cents` —
        anything else is `ERR_ALLOCATION_EXCEEDS_PROFIT`."

        Design: Corner/errors/allocation_exceeds_undistributed_profit_rejected
        """
        setup = setup_profit_program(500, accounts_spec=[("Band", 1, None)])
        res = api.create_allocation_run(
            {"program_id": setup["program"]["id"], "distributable_cents": 1000},
            TREASURER,
        )
        validate_error(res, ApiErrorId.ERR_ALLOCATION_EXCEEDS_PROFIT, 422)


class TestProgramClosureGates:
    def test_reconcile_with_undistributed_profit_rejected(self, api):
        """PRD §3.1: "The final move, `CLOSED` to `RECONCILED`, requires
        `undistributed_profit_cents` to be exactly 0 — otherwise
        `ERR_PROFIT_NOT_FULLY_ALLOCATED` — and no allocation run of the
        program still in `DRAFT`, which would again surface
        `ERR_UNRESOLVED_OPERATIONS`."

        Design: Corner/errors/reconcile_with_undistributed_profit_rejected
        """
        setup = setup_profit_program(1000)
        transition_program(setup["program"]["id"], "CLOSED")
        res = api.program_lifecycle(
            setup["program"]["id"], {"to_state": "RECONCILED"}, DIRECTOR
        )
        validate_error(res, ApiErrorId.ERR_PROFIT_NOT_FULLY_ALLOCATED, 409)

    def test_program_close_blocked_with_unresolved_campaign(self, api):
        """PRD §3.1: "Closing moves `ACTIVE` to `CLOSED` and is only permitted
        when every event sale of the program has reached `RECONCILED` or
        `CANCELLED` and every preorder campaign has reached `CLOSED` or
        `CANCELLED`; leftover operations block the close with
        `ERR_UNRESOLVED_OPERATIONS`."

        Design: Corner/state_machines/program_close_blocked_with_unresolved_campaign
        """
        shop = setup_open_campaign_shop(goal_units=5)
        assert shop["campaign"]["status"] == "OPEN"
        res = api.program_lifecycle(
            shop["program"]["id"], {"to_state": "CLOSED"}, DIRECTOR
        )
        validate_error(res, ApiErrorId.ERR_UNRESOLVED_OPERATIONS, 409)
