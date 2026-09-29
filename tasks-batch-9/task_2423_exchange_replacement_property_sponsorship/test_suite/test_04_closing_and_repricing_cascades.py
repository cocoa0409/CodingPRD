"""The two multi-hop cascades, each fired by a single request.

Closing the last subscription runs four hops from one subscription row out to
the trust, the offering and everyone still queuing. Repricing the facility runs
three hops the other way, from the debt back through the offering to the
subscriptions, and touches neither the trust status nor the ledger.
"""

from test_helpers import (
    CANONICAL_CAPITAL_STACK,
    CLOCK,
    EXCHANGE_FILE_B,
    EXCHANGE_FILE_C,
    INVESTOR_B,
    INVESTOR_C,
    TRUSTEE,
    add_qualified_investor,
    api_client,
    close_subscription,
    create_exchange_file,
    create_investor,
    create_subscription,
    file_identification,
    find_ledger_entry,
    get_success_data,
    list_ledger_entries,
    offering_version,
    open_trust_funding,
    read_exchange_file,
    read_loan_facility,
    read_offering,
    read_subscription,
    read_trust,
    reprice_loan_payload,
    review_suitability,
    set_clock,
    setup_offering_effective,
    setup_trust_funding_with_lease,
    validate_paginated,
    verify_accreditation,
)


def _raise_one_close_short_with_reserved_tail() -> dict:
    """Subscription A closed, Subscription C left reserved for 15 units, and
    Subscription B reserved for the 300 units that complete the raise.

    C is created before B so that the offering still has room when C arrives.
    """
    deal = setup_trust_funding_with_lease()

    add_qualified_investor(deal, key="investor_a")
    deal["subscription_a"] = create_subscription(
        deal["offering"]["id"],
        deal["investor_a"]["id"],
        deal["exchange_file_a"]["id"],
        300,
        deal["offering_version"],
    )

    add_qualified_investor(
        deal,
        key="investor_c",
        investor_profile=INVESTOR_C,
        exchange_file=EXCHANGE_FILE_C,
        evidence_reference="CPA-LTR-C-2026",
    )
    deal["subscription_c"] = create_subscription(
        deal["offering"]["id"],
        deal["investor_c"]["id"],
        deal["exchange_file_c"]["id"],
        15,
        offering_version(deal["offering"]["id"]),
    )

    investor_b = create_investor(**INVESTOR_B)
    deal["investor_b"] = investor_b
    deal["exchange_file_b"] = create_exchange_file(investor_b["id"], **EXCHANGE_FILE_B)
    deal["identification_b"] = file_identification(
        deal["exchange_file_b"]["id"], deal["property"]["id"]
    )

    set_clock(CLOCK["SUB_A_CLOSE"])
    deal["subscription_a"] = close_subscription(deal["subscription_a"]["id"])

    set_clock(CLOCK["SUB_B_REVIEW"])
    deal["investor_b"] = verify_accreditation(investor_b["id"], "CPA-LTR-B-2026")
    deal["investor_b"] = review_suitability(investor_b["id"], deal["offering"]["id"])
    deal["subscription_b"] = create_subscription(
        deal["offering"]["id"],
        investor_b["id"],
        deal["exchange_file_b"]["id"],
        300,
        offering_version(deal["offering"]["id"]),
    )

    set_clock(CLOCK["SUB_B_CLOSE"])
    return deal


class TestSubscriptionCloseCascade:
    def test_hop_one_closes_the_row_and_stamps_the_rescission_deadline(self):
        """The close itself is hop one and books the equity contribution.

        PRD: "The subscription's `closed_at` is stamped from the logical clock,
        its `closing_sequence_no` is assigned, and its `rescission_deadline` is set
        to `closed_at` plus the offering's `rescission_window_days` days."

        Design: Difficulty/transitive_cascade/subscription_close_cascade_trust_operating_offering_closed_autoreject
        """
        deal = _raise_one_close_short_with_reserved_tail()

        closed = close_subscription(deal["subscription_b"]["id"])

        assert closed["status"] == "CLOSED"
        assert closed["closing_sequence_no"] == 2
        assert closed["closed_at"] == "2026-11-20T00:00:00.000Z"
        assert closed["rescission_deadline"] == "2026-11-25T00:00:00.000Z"
        assert (
            read_exchange_file(deal["exchange_file_b"]["id"])["status"]
            == "CLOSED_MATCHED"
        )

    def test_hop_two_carries_the_trust_to_operating_and_recomputes_balances(self):
        """The completed raise buys the building and funds the reserve.

        PRD: "Hop two fires only when the raise is complete: if the trust's
        recomputed `equity_raised_cents` is at least the offering's
        `target_equity_cents`, the trust moves `FUNDING → OPERATING`."

        Design: Difficulty/transitive_cascade/subscription_close_cascade_trust_operating_offering_closed_autoreject
        """
        deal = _raise_one_close_short_with_reserved_tail()
        assert read_trust(deal["trust"]["id"])["status"] == "FUNDING"

        close_subscription(deal["subscription_b"]["id"])

        trust = read_trust(deal["trust"]["id"])
        assert trust["status"] == "OPERATING"
        assert trust["units_issued"] == 600
        assert trust["equity_raised_cents"] == 600_000_000
        assert trust["operating_balance_cents"] == 1_098_901
        assert trust["reserve_balance_cents"] == 30_000_000
        assert trust["posture"] == "OPEN"

    def test_hop_two_books_the_acquisition_in_four_legs(self):
        """The reserve funding is two legs, not one.

        PRD: "Cash moving between buckets is always two legs, never one."

        Design: Difficulty/transitive_cascade/subscription_close_cascade_trust_operating_offering_closed_autoreject
        """
        deal = _raise_one_close_short_with_reserved_tail()
        close_subscription(deal["subscription_b"]["id"])
        trust_id = deal["trust"]["id"]

        sponsor_load = list_ledger_entries(trust_id, entry_type="SPONSOR_LOAD")
        acquisition = list_ledger_entries(trust_id, entry_type="ACQUISITION_PAYMENT")
        reserve_legs = list_ledger_entries(trust_id, entry_type="RESERVE_FUNDING")

        assert len(sponsor_load) == 1
        assert sponsor_load[0]["amount_cents"] == -CANONICAL_CAPITAL_STACK[
            "sponsor_load_cents"
        ]
        assert len(acquisition) == 1
        assert acquisition[0]["amount_cents"] == -1_235_000_000
        assert len(reserve_legs) == 2
        assert (
            find_ledger_entry(trust_id, "RESERVE_FUNDING", "OPERATING")["amount_cents"]
            == -30_000_000
        )
        assert (
            find_ledger_entry(trust_id, "RESERVE_FUNDING", "RESERVE")["amount_cents"]
            == 30_000_000
        )

    def test_hop_three_closes_the_offering(self):
        """The offering closes itself when its trust starts operating.

        PRD: "Hop three follows from hop two: because the trust reached
        `OPERATING`, its `EFFECTIVE` offering moves to `CLOSED`."

        Design: Difficulty/transitive_cascade/subscription_close_cascade_trust_operating_offering_closed_autoreject
        """
        deal = _raise_one_close_short_with_reserved_tail()
        assert read_offering(deal["offering"]["id"])["status"] == "EFFECTIVE"

        close_subscription(deal["subscription_b"]["id"])

        assert read_offering(deal["offering"]["id"])["status"] == "CLOSED"

    def test_hop_four_turns_away_the_subscription_still_queuing(self):
        """The reserved tail is rejected without anyone asking.

        PRD: "A single close by the last investor therefore ends the raise, buys
        the building, funds the reserve, shuts the offering and turns away
        everyone still queuing — all inside one request."

        Design: Difficulty/transitive_cascade/subscription_close_cascade_trust_operating_offering_closed_autoreject
        """
        deal = _raise_one_close_short_with_reserved_tail()
        assert read_subscription(deal["subscription_c"]["id"])["status"] == "RESERVED"

        close_subscription(deal["subscription_b"]["id"])

        rejected = read_subscription(deal["subscription_c"]["id"])
        assert rejected["status"] == "REJECTED"
        # No cash was ever booked for the rejected row.
        equity_entries = list_ledger_entries(
            deal["trust"]["id"], entry_type="EQUITY_CONTRIBUTION"
        )
        assert len(equity_entries) == 2
        assert [entry["amount_cents"] for entry in equity_entries] == [
            300_000_000,
            300_000_000,
        ]
        # Investor C's exchange file is untouched by the sweep.
        assert (
            read_exchange_file(deal["exchange_file_c"]["id"])["status"] == "IDENTIFIED"
        )


class TestLoanRepriceCascade:
    def _funding_trust_with_committed_loan(self) -> dict:
        deal = setup_offering_effective()
        deal["trust"] = open_trust_funding(deal["trust"]["id"])
        deal = add_qualified_investor(deal, key="investor_a")
        deal["subscription_a"] = create_subscription(
            deal["offering"]["id"],
            deal["investor_a"]["id"],
            deal["exchange_file_a"]["id"],
            300,
            deal["offering_version"],
        )
        return deal

    def test_hop_one_recuts_the_facility_and_recomputes_both_ratios(self):
        """Repricing is a self-loop that leaves the facility committed.

        PRD: "Hop one updates `principal_cents` and `rate_bps`, increments
        `repriced_count` by 1 and recomputes `ltv_pct` and `dscr`."

        Design: Difficulty/transitive_cascade/loan_reprice_cascade_offering_amend_subscription_revision
        """
        deal = self._funding_trust_with_committed_loan()

        loan = get_success_data(
            api_client.reprice_loan_facility(
                deal["loan"]["id"], reprice_loan_payload(), TRUSTEE
            )
        )

        assert loan["status"] == "COMMITTED"
        assert loan["principal_cents"] == 750_000_000
        assert loan["rate_bps"] == 450
        assert loan["repriced_count"] == 1
        assert loan["ltv_pct"] == 62.5
        assert loan["dscr"] == 2.8741

    def test_hop_two_pushes_the_offering_back_to_draft_with_a_new_target(self):
        """A changed loan changes how much equity the deal needs.

        PRD: "Hop two follows from hop one: if the trust carries an offering in
        status `EFFECTIVE` at that moment — the ordinary case once the trust has
        reached `FUNDING` — that offering is pushed `EFFECTIVE → DRAFT`, its
        `ppm_version` is incremented by 1, and `initial_reserve_cents`,
        `target_equity_cents` and `sponsor_load_cents` are recomputed from the new
        principal, because a changed loan changes how much equity the deal needs."

        Design: Difficulty/transitive_cascade/loan_reprice_cascade_offering_amend_subscription_revision
        """
        deal = self._funding_trust_with_committed_loan()

        api_client.reprice_loan_facility(
            deal["loan"]["id"], reprice_loan_payload(), TRUSTEE
        )

        offering = read_offering(deal["offering"]["id"])
        assert offering["status"] == "DRAFT"
        assert offering["ppm_version"] == 2
        assert offering["initial_reserve_cents"] == 30_000_000
        assert offering["target_equity_cents"] == 565_934_066
        assert offering["sponsor_load_cents"] == 50_934_066

    def test_hop_three_moves_the_reserved_subscription_to_revision_required(self):
        """The revision sweep also gives back the committed units and dollars.

        PRD: "Hop three follows from hop two: every subscription on that offering
        in status `RESERVED` is moved to `REVISION_REQUIRED`, and each such move
        removes that subscription's units and dollars from the offering's
        `units_committed` and `equity_committed_cents`."

        Design: Difficulty/transitive_cascade/loan_reprice_cascade_offering_amend_subscription_revision
        """
        deal = self._funding_trust_with_committed_loan()

        api_client.reprice_loan_facility(
            deal["loan"]["id"], reprice_loan_payload(), TRUSTEE
        )

        subscription = read_subscription(deal["subscription_a"]["id"])
        assert subscription["status"] == "REVISION_REQUIRED"
        offering = read_offering(deal["offering"]["id"])
        assert offering["units_committed"] == 0
        assert offering["equity_committed_cents"] == 0

    def test_the_reprice_cascade_never_touches_the_trust_or_the_ledger(self):
        """No cash moves anywhere in this chain.

        PRD: "Repricing is a self-loop that leaves the facility in `COMMITTED`
        while re-cutting its terms, and it is the head of a three-hop cascade."

        Design: Difficulty/transitive_cascade/loan_reprice_cascade_offering_amend_subscription_revision
        """
        deal = self._funding_trust_with_committed_loan()

        api_client.reprice_loan_facility(
            deal["loan"]["id"], reprice_loan_payload(), TRUSTEE
        )

        trust = read_trust(deal["trust"]["id"])
        assert trust["status"] == "FUNDING"
        assert trust["units_issued"] == 0
        assert trust["equity_raised_cents"] == 0

        response = api_client.list_ledger_entries(
            TRUSTEE, params={"trust_id": deal["trust"]["id"], "limit": 100}
        )
        rows, meta = validate_paginated(response)
        assert meta["total_count"] == 0
        assert rows == []
        assert read_loan_facility(deal["loan"]["id"])["status"] == "COMMITTED"
