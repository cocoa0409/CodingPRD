"""Dormancy evaluation boundaries, the inactivity-fee schedule, sweep-driven
closures and their child cascade, reactivation, and statement
production/suppression."""
from test_helpers import (
    MANAGER,
    OFFICER,
    ApiErrorId,
    add_active_signer,
    api_client,
    assert_account_invariants,
    get_account,
    make_dormant_account,
    open_account,
    register_garnishment,
    resolve_garnishment,
    run_sweep,
    schedule_conversion,
    schedule_statement_cycle,
    set_clock,
    transaction_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDormancyThresholdBoundary:

    def test_dormancy_not_triggered_at_364_days(self):
        """PRD section 3.8: "Inactivity is measured in whole calendar days
        from `last_customer_activity_date`."
        PRD section 3.8: "An `OPEN` account inactive for at least 365 days
        becomes `DORMANT`, and the boundary is inclusive: exactly 365 days
        of inactivity qualifies."

        Design: Difficulty/boundary_precision_check/dormancy_threshold_day_364_vs_365
        """
        acct = open_account(opening_deposit_cents=100000,
                            primary_owner_name="Bnd B", owner_tax_id="T14")
        set_clock("2027-07-31T00:00:00Z")  # 364 days after 2026-08-01
        sweep = run_sweep()
        assert sweep["newly_dormant"] == 0

        acct_after = get_account(acct["id"])
        assert acct_after["lifecycle_status"] == "OPEN"

    def test_dormancy_triggered_at_exactly_365_days(self):
        """PRD section 3.8: "An `OPEN` account inactive for at least 365
        days becomes `DORMANT`, and the boundary is inclusive: exactly 365
        days of inactivity qualifies."
        PRD section 3.8: "Entering dormancy is itself an event. The account
        stamps `dormant_since_date` with the current date, leaves
        `fees_assessed_count` untouched because the episode continues,
        recomputes `statement_suppression`, immediately assesses the
        episode's first inactivity fee, and increments its `version`."

        Design: Difficulty/boundary_precision_check/dormancy_threshold_day_364_vs_365
        """
        acct = open_account(opening_deposit_cents=100000,
                            primary_owner_name="Bnd B", owner_tax_id="T14")
        set_clock("2027-08-01T00:00:00Z")  # exactly 365 days
        sweep = run_sweep()
        assert sweep["newly_dormant"] == 1

        acct_after = get_account(acct["id"])
        assert acct_after["lifecycle_status"] == "DORMANT"
        assert acct_after["dormant_since_date"] == "2027-08-01"
        # Entry fee: min(500, 100000) = 500.
        assert acct_after["balance_cents"] == 99500
        assert acct_after["statement_suppression"] == "DORMANT"
        assert acct_after["version"] > acct["version"]


class TestParallelPostureDimensions:

    def _setup_dormant_under_legal_hold(self):
        acct = open_account(opening_deposit_cents=100000,
                            primary_owner_name="Par P", owner_tax_id="T8")
        order = register_garnishment(acct["id"], 50000, "2026-08-01",
                                     exemption_method="FEDERAL_LOOKBACK")
        set_clock("2027-08-01T00:00:00Z")
        run_sweep()
        return acct, order

    def test_account_goes_dormant_while_under_legal_hold(self):
        """PRD section 2.8: "A deposit account carries two independent
        status dimensions that gate operations independently."

        Design: Difficulty/non_linear_state_machine/account_parallel_dimensions_dormant_under_legal_hold
        """
        acct, _order = self._setup_dormant_under_legal_hold()
        acct_after = get_account(acct["id"])
        # Lifecycle advanced (with the dormancy entry fee posted) while the
        # restriction dimension stayed put.
        assert acct_after["lifecycle_status"] == "DORMANT"
        assert acct_after["restriction_status"] == "LEGAL_HOLD"
        assert acct_after["balance_cents"] == 99500
        assert acct_after["total_held_cents"] == 50000
        assert_account_invariants(acct_after)

    def test_garnishment_release_clears_hold_but_not_dormancy(self):
        """PRD section 2.8: "A deposit account carries two independent
        status dimensions that gate operations independently."
        PRD section 3.5: "Either branch records the resolver in
        `resolved_by_user_id`, subtracts the hold from `total_held_cents`,
        recomputes `available_balance_cents`, returns the account's
        restriction to `NONE` when no order remains in `FUNDS_HELD`, and
        increments the account's `version`."

        Design: Difficulty/non_linear_state_machine/account_parallel_dimensions_dormant_under_legal_hold
        """
        acct, order = self._setup_dormant_under_legal_hold()
        resolved = resolve_garnishment(order["id"], "RELEASED")
        assert resolved["status"] == "RELEASED"
        assert resolved["released_amount_cents"] == 50000
        assert resolved["remitted_amount_cents"] == 0

        acct_after = get_account(acct["id"])
        # Restriction flips back; lifecycle stays DORMANT.
        assert acct_after["restriction_status"] == "NONE"
        assert acct_after["lifecycle_status"] == "DORMANT"
        assert acct_after["total_held_cents"] == 0
        assert acct_after["available_balance_cents"] == 99500
        assert_account_invariants(acct_after)


class TestZeroBalanceAutoCloseChain:

    def _setup_chain(self):
        acct = open_account(opening_deposit_cents=1000,
                            primary_owner_name="Dor D", owner_tax_id="T10")
        signer = add_active_signer(acct["id"], reference_number="SC-1",
                                   full_name="Sig S", tax_id="TS1")
        conv = schedule_conversion(acct["id"], "BASIC_CHECKING", 100,
                                   "2026-09-01")
        cyc = schedule_statement_cycle(acct["id"], "2027-09-01",
                                       "2027-10-01")
        set_clock("2027-08-01T00:00:00Z")
        sweep1 = run_sweep()
        return acct, signer, conv, cyc, sweep1

    def test_dormancy_fee_zero_balance_auto_close_sweep_tallies(self):
        """PRD section 3.8: "The fees due now are that target minus
        `fees_assessed_count`, never less than zero, and they post
        sequentially: each fee is the lesser of 500 cents and the balance at
        that instant, posts as an `INACTIVITY_FEE` transaction, and
        increments `fees_assessed_count`."
        PRD section 3.8: "When a fee run drains the balance to exactly zero
        on an account still `DORMANT`, the sweep closes the account
        automatically: the zero-balance auto-close of §3.9."
        PRD section 3.9: "Zero-balance auto-close — a `DORMANT` account
        whose fee run leaves the balance at exactly zero — records
        `closure_payout_cents` of zero with destination `OWNER`."

        Design: Difficulty/transitive_cascade/dormancy_fee_zero_balance_auto_close_chain
        """
        acct, _signer, _conv, _cyc, sweep1 = self._setup_chain()
        # Sweep 1 at day 365: OPEN -> DORMANT and the entry fee posts.
        assert sweep1["newly_dormant"] == 1
        assert sweep1["fees_assessed_cents"] == 500

        # Sweep 2 at day 395: floor(30/30) = 1 complete period past the
        # entry fee, so one more 500 fee drains 500 -> 0 and auto-closes.
        set_clock("2027-08-31T00:00:00Z")
        sweep2 = run_sweep()
        assert sweep2["fees_assessed_count"] == 1
        assert sweep2["fees_assessed_cents"] == 500
        assert sweep2["auto_closed_count"] == 1

        acct_after = get_account(acct["id"])
        assert acct_after["lifecycle_status"] == "CLOSED"
        assert acct_after["balance_cents"] == 0
        assert acct_after["closure_payout_cents"] == 0
        assert acct_after["closure_payout_destination"] == "OWNER"

    def test_zero_balance_auto_close_cascades_to_children(self):
        """PRD section 3.9: "Every closure runs the same cascade over the
        account's children: every `ACTIVE` or `SUSPENDED` signer is
        `REMOVED` with `removed_reason` `ACCOUNT_CLOSED` (or
        `DECEASED_CASCADE` when the closure is an estate release); every
        `SUBMITTED` title change is `REJECTED` with `decision_reason`
        `ACCOUNT_CLOSED`; every `SCHEDULED` product conversion is
        `CANCELLED`; and every `SCHEDULED` statement cycle is `SUPPRESSED`
        with reason `CLOSED`."

        Design: Difficulty/transitive_cascade/dormancy_fee_zero_balance_auto_close_chain
        """
        acct, signer, conv, cyc, _sweep1 = self._setup_chain()
        set_clock("2027-08-31T00:00:00Z")
        run_sweep()

        signers, _ = validate_paginated(
            api_client.list_signers(acct["id"], MANAGER))
        by_signer = {s["id"]: s for s in signers}
        assert by_signer[signer["id"]]["status"] == "REMOVED"
        assert by_signer[signer["id"]]["removed_reason"] == "ACCOUNT_CLOSED"

        convs, _ = validate_paginated(
            api_client.list_conversions(acct["id"], MANAGER))
        by_conv = {c["id"]: c for c in convs}
        assert by_conv[conv["id"]]["status"] == "CANCELLED"

        cycles, _ = validate_paginated(
            api_client.list_statement_cycles(acct["id"], MANAGER))
        by_cycle = {c["id"]: c for c in cycles}
        assert by_cycle[cyc["id"]]["status"] == "SUPPRESSED"
        assert by_cycle[cyc["id"]]["suppression_reason"] == "CLOSED"


class TestInactivityFeeSchedule:

    def test_inactivity_fee_capped_at_balance_auto_closes(self):
        """PRD section 3.8: "each fee is the lesser of 500 cents and the
        balance at that instant, posts as an `INACTIVITY_FEE` transaction,
        and increments `fees_assessed_count`."
        PRD section 3.8: "When a fee run drains the balance to exactly zero
        on an account still `DORMANT`, the sweep closes the account
        automatically: the zero-balance auto-close of §3.9."

        Design: Corner/calculations/inactivity_fee_capped_at_balance_auto_closes
        """
        acct = open_account(opening_deposit_cents=300,
                            primary_owner_name="Cap C", owner_tax_id="C14")
        set_clock("2027-08-01T00:00:00Z")
        sweep = run_sweep()
        # Entry fee is capped by the balance: min(500, 300) = 300 -> 0.
        assert sweep["fees_assessed_cents"] == 300
        assert sweep["auto_closed_count"] == 1

        acct_after = get_account(acct["id"])
        assert acct_after["lifecycle_status"] == "CLOSED"
        assert acct_after["balance_cents"] == 0

    def test_fee_cadence_second_fee_at_exactly_30_days(self):
        """PRD section 3.8: "The dormancy entry transition assesses fee
        number one. On every later sweep, the number of fees that should
        have been assessed in the current episode is pinned as one plus the
        count of complete thirty-day periods elapsed between
        `dormant_since_date` and the sweep date, partial periods discarded."

        Design: Corner/calculations/fee_cadence_second_fee_at_exactly_30_days
        """
        acct = open_account(opening_deposit_cents=10000,
                            primary_owner_name="Cad K", owner_tax_id="C15")
        set_clock("2027-08-01T00:00:00Z")
        run_sweep()  # entry fee: balance 10000 -> 9500

        # Day 29 of the episode: partial period discarded, no fee due.
        set_clock("2027-08-30T00:00:00Z")
        sweep_29 = run_sweep()
        assert sweep_29["fees_assessed_count"] == 0

        # Day 30: floor(30/30) = 1 complete period -> exactly one more fee.
        set_clock("2027-08-31T00:00:00Z")
        sweep_30 = run_sweep()
        assert sweep_30["fees_assessed_count"] == 1

        acct_after = get_account(acct["id"])
        assert acct_after["fees_assessed_count"] == 2
        assert acct_after["balance_cents"] == 9000
        assert acct_after["lifecycle_status"] == "DORMANT"


class TestReactivation:

    def test_reactivation_via_customer_transaction(self):
        """PRD section 3.1: "If the account was `DORMANT` or
        `ESCHEAT_PENDING` and its restriction is `NONE`, the same posting
        reactivates it to `OPEN`: `dormant_since_date` clears to null,
        `fees_assessed_count` resets to zero, ending the dormancy episode,
        and `statement_suppression` is recomputed."
        PRD section 3.1: "When a posting arrives with `customer_initiated`
        set to true, the account's `last_customer_activity_date` advances to
        the transaction's `posted_date`."

        Design: Corner/state_machines/reactivation_via_customer_transaction
        """
        acct = make_dormant_account(opening_deposit_cents=100000,
                                    primary_owner_name="Rea R",
                                    owner_tax_id="C13")
        assert acct["lifecycle_status"] == "DORMANT"
        assert acct["balance_cents"] == 99500  # entry fee posted

        txn = validate_success(
            api_client.post_transaction(
                acct["id"],
                transaction_payload("DEPOSIT", 100, customer_initiated=True,
                                    posted_date="2027-08-02"),
                OFFICER,
            ),
            expected_status=201,
        )
        assert txn["balance_after_cents"] == 99600

        acct_after = get_account(acct["id"])
        assert acct_after["lifecycle_status"] == "OPEN"
        assert acct_after["dormant_since_date"] is None
        assert acct_after["fees_assessed_count"] == 0
        assert acct_after["last_customer_activity_date"] == "2027-08-02"
        assert acct_after["statement_suppression"] == "NONE"


class TestStatementProduction:

    def test_statement_cycle_suppressed_by_dormant_posture(self):
        """PRD section 3.6: "The daily sweep settles cycles whose
        `cycle_end` has arrived, meaning it falls on or before the sweep
        date. When the account's `statement_suppression` is `NONE`, the
        cycle is `PRODUCED` and `produced_date` takes the sweep date. When
        suppression is anything other than `NONE`, the cycle is
        `SUPPRESSED` instead: `suppression_reason` records the posture
        class — `DORMANT`, `DECEASED`, or `CLOSED` — and `produced_date`
        still takes the sweep date."

        Design: Corner/state_machines/statement_cycle_suppressed_by_dormant_posture
        """
        acct = open_account(opening_deposit_cents=50000,
                            primary_owner_name="Sup S", owner_tax_id="C12")
        cyc = schedule_statement_cycle(acct["id"], "2026-08-01",
                                       "2026-09-01")
        set_clock("2027-08-01T00:00:00Z")  # account goes DORMANT this sweep
        sweep = run_sweep()
        assert sweep["statements_suppressed"] == 1

        cycles, _ = validate_paginated(
            api_client.list_statement_cycles(acct["id"], MANAGER))
        by_cycle = {c["id"]: c for c in cycles}
        assert by_cycle[cyc["id"]]["status"] == "SUPPRESSED"
        assert by_cycle[cyc["id"]]["suppression_reason"] == "DORMANT"
        assert by_cycle[cyc["id"]]["produced_date"] == "2027-08-01"

    def test_statement_cycle_produced_when_healthy(self):
        """PRD section 3.6: "When the account's `statement_suppression` is
        `NONE`, the cycle is `PRODUCED` and `produced_date` takes the sweep
        date."

        Design: Corner/state_machines/statement_cycle_produced_when_healthy
        """
        acct = open_account(opening_deposit_cents=50000,
                            primary_owner_name="Prod P", owner_tax_id="C22")
        cyc = schedule_statement_cycle(acct["id"], "2026-08-01",
                                       "2026-09-01")
        set_clock("2026-09-01T00:00:00Z")  # 31 days inactive: still OPEN
        sweep = run_sweep()
        assert sweep["statements_produced"] == 1
        assert sweep["statements_suppressed"] == 0

        cycles, _ = validate_paginated(
            api_client.list_statement_cycles(acct["id"], MANAGER))
        by_cycle = {c["id"]: c for c in cycles}
        assert by_cycle[cyc["id"]]["status"] == "PRODUCED"
        assert by_cycle[cyc["id"]]["produced_date"] == "2026-09-01"


class TestStatementPeriodOverlap:

    def test_statement_cycle_adjacent_period_allowed(self):
        """PRD section 3.6: "Cycles on the same account may touch but never
        overlap: a new period that shares any day with an existing cycle is
        rejected with `ERR_STATEMENT_PERIOD_OVERLAP`, while a cycle starting
        exactly on another cycle's end date is lawful adjacency."

        Design: Difficulty/resource_temporal_overlap/statement_cycle_half_open_adjacency
        """
        acct = open_account(opening_deposit_cents=50000,
                            primary_owner_name="Stmt S", owner_tax_id="T18")
        schedule_statement_cycle(acct["id"], "2026-08-01", "2026-09-01")

        # Starts exactly at the predecessor's cycle_end: lawful adjacency.
        cyc2 = schedule_statement_cycle(acct["id"], "2026-09-01",
                                        "2026-10-01")
        assert cyc2["status"] == "SCHEDULED"
        assert cyc2["cycle_start"] == "2026-09-01"

    def test_statement_cycle_straddling_period_rejected(self):
        """PRD section 3.6: "Cycles on the same account may touch but never
        overlap: a new period that shares any day with an existing cycle is
        rejected with `ERR_STATEMENT_PERIOD_OVERLAP`, while a cycle starting
        exactly on another cycle's end date is lawful adjacency."

        Design: Difficulty/resource_temporal_overlap/statement_cycle_half_open_adjacency
        """
        acct = open_account(opening_deposit_cents=50000,
                            primary_owner_name="Stmt S", owner_tax_id="T18")
        schedule_statement_cycle(acct["id"], "2026-08-01", "2026-09-01")

        # [08-15, 09-15) shares days with [08-01, 09-01): overlap.
        resp = api_client.schedule_statement_cycle(
            acct["id"],
            {"cycle_start": "2026-08-15", "cycle_end": "2026-09-15"},
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_STATEMENT_PERIOD_OVERLAP)
