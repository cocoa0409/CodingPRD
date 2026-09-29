"""The two unwind paths, each of which conserves a quantity exactly.

Rescinding a closed subscription puts the trust's unit count back where it was;
voiding a reserve-funded need puts the reserve cash back where it was. Both do it
by writing a compensating reversal, never by deleting the original entry.
"""

from test_helpers import (
    CANONICAL_OPERATING_TRUST,
    TRUSTEE,
    api_client,
    close_subscription,
    find_ledger_entry,
    get_success_data,
    list_ledger_entries,
    read_capital_need,
    read_exchange_file,
    read_subscription,
    read_trust,
    rescind_subscription,
    set_clock,
    setup_reserve_draw_to_floor,
    setup_reserved_subscription_a,
    validate_paginated,
)


class TestRescissionConservesTrustUnits:
    def _closed_then_rescinded(self) -> dict:
        deal = setup_reserved_subscription_a(300)
        set_clock("2026-09-15T00:00:00Z")
        deal["subscription_a"] = close_subscription(deal["subscription_a"]["id"])
        deal["equity_entry"] = find_ledger_entry(
            deal["trust"]["id"], "EQUITY_CONTRIBUTION", "OPERATING"
        )
        set_clock("2026-09-18T00:00:00Z")
        deal["subscription_a"] = rescind_subscription(
            deal["subscription_a"]["id"], deal["investor_a"]["id"]
        )
        return deal

    def test_the_unit_count_and_equity_return_to_their_pre_close_values(self):
        """Reversing an entry restores the bucket to the cent.

        PRD: "A reversal always carries exactly the negation of the amount of the
        entry it names, so a reversed entry and the reversal that names it
        contribute nothing between them: reversing an entry restores the bucket to
        the balance it held before that entry was booked, exactly, to the cent."

        Design: Difficulty/compensating_invariant/subscription_rescission_conserves_trust_units
        """
        deal = self._closed_then_rescinded()

        trust = read_trust(deal["trust"]["id"])
        assert trust["units_issued"] == 0
        assert trust["equity_raised_cents"] == 0
        assert trust["operating_balance_cents"] == 720_000_000

    def test_the_rescinded_row_gives_up_its_closing_ordinal(self):
        """The remaining closings keep a dense sequence.

        PRD: "The rescinded row's `closing_sequence_no` is cleared to empty and
        the remaining `CLOSED` subscriptions on the offering are renumbered by the
        same `closed_at` ascending rule, so the sequence is always 1 through n with
        no gaps."

        Design: Difficulty/compensating_invariant/subscription_rescission_conserves_trust_units
        """
        deal = self._closed_then_rescinded()

        subscription = read_subscription(deal["subscription_a"]["id"])
        assert subscription["status"] == "RESCINDED"
        assert subscription["closing_sequence_no"] is None

    def test_the_reversal_names_the_original_entry_which_still_exists(self):
        """Compensation, never deletion.

        PRD: "The rescission books a `REVERSAL` entry in the `OPERATING` bucket
        for the negative of `investment_amount_cents`, with `reversal_of_entry_id`
        pointing at the `EQUITY_CONTRIBUTION` entry booked at close and
        `source_kind` `REVERSAL`."

        Design: Difficulty/compensating_invariant/subscription_rescission_conserves_trust_units
        """
        deal = self._closed_then_rescinded()

        response = api_client.list_ledger_entries(
            TRUSTEE,
            params={
                "trust_id": deal["trust"]["id"],
                "reversal_of_entry_id": deal["equity_entry"]["id"],
                "limit": 100,
            },
        )
        rows, meta = validate_paginated(response)
        assert meta["total_count"] == 1
        assert rows[0]["entry_type"] == "REVERSAL"
        assert rows[0]["bucket"] == "OPERATING"
        assert rows[0]["amount_cents"] == -300_000_000
        assert rows[0]["source_kind"] == "REVERSAL"

        original = get_success_data(
            api_client.get_ledger_entry(deal["equity_entry"]["id"], TRUSTEE)
        )
        assert original["entry_type"] == "EQUITY_CONTRIBUTION"
        assert original["amount_cents"] == 300_000_000

    def test_the_exchange_file_walks_back_to_open_inside_the_window(self):
        """An investor who unwinds in time gets his identification period back.

        PRD: "Finally the exchange file walks back from `CLOSED_MATCHED`: to
        `OPEN` when the file's `identification_deadline` has not yet passed, and to
        `EXPIRED` when it has — an investor who unwinds late does not get a fresh
        identification period, he gets a dead file."

        Design: Difficulty/compensating_invariant/subscription_rescission_conserves_trust_units
        """
        deal = self._closed_then_rescinded()

        exchange_file = read_exchange_file(deal["exchange_file_a"]["id"])
        assert exchange_file["status"] == "OPEN"
        assert exchange_file["identification_deadline"] == "2026-09-19T23:59:59.999Z"


class TestVoidingACapitalNeedConservesReserveCash:
    def test_the_draw_lands_exactly_on_the_floor_without_restricting_the_trust(self):
        """At the floor is not below the floor.

        PRD: "Balances are pure replays of the journal, never independently
        maintained counters."

        Design: Difficulty/compensating_invariant/capex_draw_void_conserves_reserve_cash
        """
        deal = setup_reserve_draw_to_floor()

        trust = read_trust(deal["trust"]["id"])
        assert trust["reserve_balance_cents"] == 5_000_000
        assert trust["posture"] == "OPEN"
        assert trust["operating_balance_cents"] == (
            CANONICAL_OPERATING_TRUST["operating_balance_cents"]
        )

    def test_voiding_the_funded_need_restores_the_reserve_exactly(self):
        """Voiding a reserve-funded capital need conserves reserve cash.

        PRD: "This is the compensating invariant behind both unwind paths in the
        system — rescinding a closed subscription conserves the trust's unit count
        and equity, and voiding a reserve-funded capital need conserves reserve
        cash."

        Design: Difficulty/compensating_invariant/capex_draw_void_conserves_reserve_cash
        """
        deal = setup_reserve_draw_to_floor()

        voided = get_success_data(
            api_client.void_capital_need(
                deal["capital_need"]["id"],
                TRUSTEE,
                {"reason": "master tenant absorbed the repair instead"},
            )
        )

        assert voided["status"] == "VOIDED"
        trust = read_trust(deal["trust"]["id"])
        assert trust["reserve_balance_cents"] == 30_000_000
        assert trust["operating_balance_cents"] == 1_098_901
        assert trust["posture"] == "OPEN"

    def test_the_reversal_is_a_positive_reserve_leg_naming_the_draw(self):
        """The reversal carries the negation of the entry it names.

        PRD: "A trust's `operating_balance_cents` is the sum of the signed amounts
        of its `OPERATING` entries and its `reserve_balance_cents` is the sum of
        the signed amounts of its `RESERVE` entries."

        Design: Difficulty/compensating_invariant/capex_draw_void_conserves_reserve_cash
        """
        deal = setup_reserve_draw_to_floor()
        draw_entry = deal["reserve_draw_entry"]
        assert draw_entry["amount_cents"] == -25_000_000

        api_client.void_capital_need(deal["capital_need"]["id"], TRUSTEE)

        response = api_client.list_ledger_entries(
            TRUSTEE,
            params={
                "trust_id": deal["trust"]["id"],
                "reversal_of_entry_id": draw_entry["id"],
                "limit": 100,
            },
        )
        rows, meta = validate_paginated(response)
        assert meta["total_count"] == 1
        assert rows[0]["entry_type"] == "REVERSAL"
        assert rows[0]["bucket"] == "RESERVE"
        assert rows[0]["amount_cents"] == 25_000_000

        reserve_rows = list_ledger_entries(deal["trust"]["id"], bucket="RESERVE")
        assert sum(row["amount_cents"] for row in reserve_rows) == 30_000_000

    def test_the_void_leaves_the_need_terminal_and_the_operating_bucket_alone(self):
        """The operating bucket never took part in either leg.

        PRD: "Voiding a `FUNDED` need requires the trust to be `OPERATING`."

        Design: Difficulty/compensating_invariant/capex_draw_void_conserves_reserve_cash
        """
        deal = setup_reserve_draw_to_floor()
        operating_before = [
            row["amount_cents"]
            for row in list_ledger_entries(deal["trust"]["id"], bucket="OPERATING")
        ]

        api_client.void_capital_need(deal["capital_need"]["id"], TRUSTEE)

        assert read_capital_need(deal["capital_need"]["id"])["status"] == "VOIDED"
        operating_after = [
            row["amount_cents"]
            for row in list_ledger_entries(deal["trust"]["id"], bucket="OPERATING")
        ]
        assert operating_after == operating_before
        assert read_trust(deal["trust"]["id"])["status"] == "OPERATING"
