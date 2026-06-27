"""Ticket validation routing, claim-deadline boundaries, escheat sweep, and the
counter-pay → reversal ledger conservation invariant.

Covers difficulty boundary_precision_check (claim-deadline inclusive boundary),
compensating_invariant (counter-pay conserves commission balance), plus ticket
state-machine, threshold, escheat, and derived-field corner instances.
"""
from test_helpers import (
    api_client, validate_success, validate_error, officer_headers,
    create_game, setup_active_retailer_with_terminal, setup_game_retailer_terminal,
    sell_ticket, sell_and_validate_winner, sell_and_validate_nonwinner,
    sell_and_counter_pay, set_clock, fresh_retailer_version, ApiErrorId, TEST_USERS,
)

LIC = TEST_USERS["licensing_admin_headers"]
OP = TEST_USERS["terminal_operator_headers"]
OFF = TEST_USERS["lottery_officer_headers"]


class TestClaimDeadlineBoundary:
    def test_validate_winner_at_exactly_deadline_succeeds(self, api):
        """PRD 3.10: "at the exact deadline instant the ticket is still claimable, because
        the boundary is inclusive of the deadline and escheat requires a strictly-later
        clock."
        PRD 3.4: "This branch requires that the logical clock not have passed the ticket's
        `claim_deadline`; if the deadline has strictly passed, the validate is rejected
        with `ERR_CLAIM_WINDOW_EXPIRED`."

        Design: Difficulty/boundary_precision_check/claim_deadline_inclusive_boundary_on_validate
        """
        game, ret, term = setup_game_retailer_terminal(
            game_type="INSTANT", threshold_cents=600000, clock="2026-01-05T00:00:00Z")
        tk = sell_ticket(game["id"], term["id"], declared_tier=1, gross_prize_cents=1000000,
                         draw_date="2026-01-10T00:00:00Z")  # deadline = 2026-02-09
        set_clock("2026-02-09T00:00:00Z")  # exactly the deadline
        data = validate_success(api.validate_ticket(tk["id"], OP))
        assert data["validation_status"] == "VALIDATED_WINNER", data["validation_status"]
        assert data["claim_deadline"] == "2026-02-09T00:00:00.000Z", data["claim_deadline"]

    def test_validate_winner_strictly_after_deadline_rejected(self, api):
        """PRD 3.4: "When the ticket is still `UNVALIDATED` and the logical clock is
        strictly past the ticket's `claim_deadline`, validation transitions the ticket
        `UNVALIDATED → REJECTED`; an expired ticket cannot be validated into any active
        state."

        Design: Difficulty/boundary_precision_check/claim_deadline_inclusive_boundary_on_validate
        """
        game, ret, term = setup_game_retailer_terminal(
            game_type="INSTANT", threshold_cents=600000, clock="2026-01-05T00:00:00Z")
        tk = sell_ticket(game["id"], term["id"], declared_tier=1, gross_prize_cents=1000000,
                         draw_date="2026-01-10T00:00:00Z")  # deadline = 2026-02-09
        set_clock("2026-02-10T00:00:00Z")  # strictly after
        data = validate_success(api.validate_ticket(tk["id"], OP))
        assert data["validation_status"] == "REJECTED", data["validation_status"]


class TestThresholdBoundary:
    def test_winner_at_exactly_threshold_is_over_threshold(self, api):
        """PRD 3.4: "When the `declared_tier` is between 1 and 9 and the
        `gross_prize_cents` is at or above the game's `federal_withholding_threshold_cents`,
        the prize is too large to pay at the counter and must be claimed centrally: the
        ticket transitions `UNVALIDATED → VALIDATED_WINNER`"

        Design: Corner/cross_cutting_complexity_layers/threshold_boundary_at_exactly_T_is_over_threshold_winner
        """
        game, ret, term = setup_game_retailer_terminal(
            game_type="INSTANT", threshold_cents=600000, clock="2026-01-05T00:00:00Z")
        tk = sell_ticket(game["id"], term["id"], declared_tier=1, gross_prize_cents=600000,
                         draw_date="2026-01-10T00:00:00Z")
        data = validate_success(api.validate_ticket(tk["id"], OP))
        assert data["validation_status"] == "VALIDATED_WINNER", data["validation_status"]

    def test_under_threshold_counter_pay_accrues_bonus(self, api):
        """PRD 3.8: "the retailer that owns the selling terminal is credited a bonus equal
        to the ticket's `gross_prize_cents` multiplied by the retailer's
        `cashing_bonus_rate`, rounded half-up to the nearest cent, and that amount is added
        to `commission_balance_cents`."

        Design: Corner/state_machines/under_threshold_counter_pay_accrues_cashing_bonus
        """
        game = create_game(game_type="INSTANT", federal_withholding_threshold_cents=600000)
        ret, term = setup_active_retailer_with_terminal(
            retailer_overrides={"cashing_bonus_rate": 0.01})
        set_clock("2026-01-05T00:00:00Z")
        tk = sell_and_counter_pay(game["id"], term["id"], gross_prize_cents=50000,
                                  draw_date="2026-01-10T00:00:00Z", price_cents=100)
        assert tk["validation_status"] == "PAID_AT_COUNTER", tk["validation_status"]
        r = validate_success(api.get_retailer(ret["id"], OFF))
        assert r["commission_balance_cents"] == 500, r["commission_balance_cents"]


class TestCounterPayConservation:
    def test_counter_pay_then_reversal_conserves_balance(self, api):
        """PRD 3.8: "the exact same bonus amount (the ticket's `gross_prize_cents` times
        the retailer's `cashing_bonus_rate`, rounded half-up) is debited back out of
        `commission_balance_cents`, with the balance floored at 0 so it never goes
        negative."

        Design: Difficulty/compensating_invariant/counter_pay_then_reversal_conserves_commission_balance
        """
        game = create_game(game_type="INSTANT", federal_withholding_threshold_cents=600000)
        ret, term = setup_active_retailer_with_terminal(
            retailer_overrides={"commission_rate": 0.06, "cashing_bonus_rate": 0.01})
        set_clock("2026-07-02T00:00:00Z")
        tk = sell_and_counter_pay(game["id"], term["id"], gross_prize_cents=50000,
                                  draw_date="2026-07-03T00:00:00Z", price_cents=100)
        assert validate_success(api.get_retailer(ret["id"], OFF))["commission_balance_cents"] == 500
        data = validate_success(api.reverse_counter_pay(tk["id"], OFF))
        assert data["validation_status"] == "COUNTER_REVERSED", data["validation_status"]
        r = validate_success(api.get_retailer(ret["id"], OFF))
        assert r["commission_balance_cents"] == 0, r["commission_balance_cents"]

    def test_reverse_counter_pay_transitions_ticket(self, api):
        """PRD 3.8: "If a `LotteryOfficer` later reverses an erroneous or expired
        counter-pay — moving the ticket `PAID_AT_COUNTER → COUNTER_REVERSED`"

        Design: Difficulty/compensating_invariant/counter_pay_then_reversal_conserves_commission_balance
        """
        game = create_game(game_type="INSTANT", federal_withholding_threshold_cents=600000)
        ret, term = setup_active_retailer_with_terminal(
            retailer_overrides={"cashing_bonus_rate": 0.01})
        set_clock("2026-07-02T00:00:00Z")
        tk = sell_and_counter_pay(game["id"], term["id"], gross_prize_cents=50000,
                                  draw_date="2026-07-03T00:00:00Z", price_cents=100)
        data = validate_success(api.reverse_counter_pay(tk["id"], OFF))
        assert data["validation_status"] == "COUNTER_REVERSED", data["validation_status"]


class TestTicketAxesAndEscheat:
    def test_winner_validation_leaves_second_chance_ineligible(self, api):
        """PRD 3.4: "the ticket transitions `UNVALIDATED → VALIDATED_WINNER`, and its
        `second_chance_status` remains `INELIGIBLE` because winning tickets never enter
        second chance."

        Design: Corner/state_machines/ticket_parallel_axes_independent_winner_stays_ineligible
        """
        game, ret, term = setup_game_retailer_terminal(
            game_type="INSTANT", threshold_cents=600000, clock="2026-01-05T00:00:00Z")
        data = sell_and_validate_winner(game["id"], term["id"], gross_prize_cents=1000000)
        assert data["validation_status"] == "VALIDATED_WINNER", data["validation_status"]
        assert data["second_chance_status"] == "INELIGIBLE", data["second_chance_status"]

    def test_double_validate_returns_invalid_state(self, api):
        """PRD 3.4: "A ticket may only be validated while it is `UNVALIDATED`; an attempt
        to validate a ticket in any other validation state is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/double_validate_ticket_returns_invalid_state
        """
        game = create_game(game_type="DAILY", federal_withholding_threshold_cents=600000)
        ret, term = setup_active_retailer_with_terminal()
        set_clock("2026-01-10T00:00:00Z")
        tk = sell_and_validate_nonwinner(game["id"], term["id"], draw_date="2026-01-10T00:00:00Z")
        assert tk["validation_status"] == "VALIDATED_NONWINNER"
        resp = api.validate_ticket(tk["id"], OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        assert validate_success(api.get_ticket(tk["id"], OP))["validation_status"] == "VALIDATED_NONWINNER"

    def test_escheat_sweep_bubbles_winner_with_record(self, api):
        """PRD 3.10: "transitions each such ticket `VALIDATED_WINNER → ESCHEATED`, and for
        each creates an **escheat record** whose `escheated_amount_cents` equals the
        ticket's `gross_prize_cents`"

        Design: Corner/state_machines/escheat_sweep_bubbles_winner_to_escheated_with_record
        """
        game, ret, term = setup_game_retailer_terminal(
            game_type="INSTANT", threshold_cents=600000, clock="2026-01-05T00:00:00Z")
        tk = sell_and_validate_winner(game["id"], term["id"], gross_prize_cents=1000000,
                                      draw_date="2026-01-10T00:00:00Z")
        set_clock("2026-02-10T00:00:00Z")  # past deadline 2026-02-09
        validate_success(api.run_escheat_sweep(OFF))
        t = validate_success(api.get_ticket(tk["id"], OFF))
        assert t["validation_status"] == "ESCHEATED", t["validation_status"]
        recs = validate_success(api.list_escheat_records(OFF, params={"ticket_id": tk["id"]}))
        assert any(r["ticket_id"] == tk["id"] and r["escheated_amount_cents"] == 1000000
                   for r in recs), recs

    def test_clock_default_governs_unset_deadline(self, api):
        """PRD 2.4: "At server startup the logical clock reads exactly
        `2026-01-01T00:00:00Z`, and before any clock-set call it holds precisely this
        default rather than falling back to the host's real time."
        PRD 3.4: "The `claim_deadline` is computed as the `draw_date` plus exactly
        `claim_window_days` whole days (twenty-four hours per day)"

        Design: Corner/cross_cutting_complexity_layers/clock_default_governs_unset_deadline_comparisons
        """
        game = create_game(game_type="INSTANT", federal_withholding_threshold_cents=600000,
                           claim_window_days=30)
        ret, term = setup_active_retailer_with_terminal()
        # NO clock set call: clock is at startup default 2026-01-01
        tk = sell_ticket(game["id"], term["id"], declared_tier=1, gross_prize_cents=1000000,
                         draw_date="2026-01-01T00:00:00Z")
        data = validate_success(api.validate_ticket(tk["id"], OP))
        assert data["validation_status"] == "VALIDATED_WINNER", data["validation_status"]
        assert data["claim_deadline"] == "2026-01-31T00:00:00.000Z", data["claim_deadline"]

    def test_tickets_sold_count_reconciles(self, api):
        """PRD 3.3: "the system tracks `tickets_sold_count`, a computed count of tickets
        sold through that terminal that starts at 0."
        PRD 3.4: "the system records its `claim_deadline` and increments the selling
        terminal's `tickets_sold_count`."

        Design: Corner/cross_cutting_complexity_layers/tickets_sold_count_derived_field_reconciles
        """
        game = create_game(game_type="DAILY", federal_withholding_threshold_cents=600000)
        ret, term = setup_active_retailer_with_terminal()
        set_clock("2026-05-10T00:00:00Z")
        sell_ticket(game["id"], term["id"], declared_tier=0, gross_prize_cents=0,
                    price_cents=100, draw_date="2026-05-10T00:00:00Z")
        sell_ticket(game["id"], term["id"], declared_tier=0, gross_prize_cents=0,
                    price_cents=100, draw_date="2026-05-10T00:00:00Z")
        t = validate_success(api.get_terminal(term["id"], LIC))
        assert t["tickets_sold_count"] == 2, t["tickets_sold_count"]
