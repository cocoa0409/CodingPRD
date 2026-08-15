"""Transaction booking, matching tolerance, elimination, and the two
independent state dimensions."""
from test_helpers import (
    ADMIN,
    ANALYST,
    MANAGER,
    ApiErrorId,
    assert_transaction,
    begin_closing,
    begin_netting,
    book_transaction,
    close_year,
    create_agreement,
    create_pool,
    setup_active_agreement,
    setup_agreement_with_matched_transactions,
    setup_year_entities_study,
    validate_error,
    validate_success,
    api_client,
    find_position,
)


class TestBookingComputation:

    def test_booking_computes_provisional_price_and_margin(self):
        """PRD section 3.4: "The provisional arm's-length price,
        `provisional_al_price_cents`, is the cost base multiplied by the
        markup factor — that is, `cost_base_cents` multiplied by the sum of
        10000 and `markup_bp`, divided by 10000 — rounded half-up to whole
        cents. The realized margin, `margin_bp`, is the excess of
        `provider_revenue_cents` over `cost_base_cents`, multiplied by 10000
        and divided by `cost_base_cents`, rounded half-up."
        PRD section 3.4: "A new booking starts `UNMATCHED` and `UNSETTLED`,
        with `origin_run_id` null and `is_true_up_adjustment` false."

        Design: Corner/entities/transaction_computed_price_and_margin_at_booking
        """
        ctx = setup_active_agreement()
        resp = api_client.create_transaction(
            {
                "agreement_id": ctx["agreement"]["id"],
                "fiscal_year_id": ctx["fiscal_year"]["id"],
                "cost_base_cents": 1_000_000,
                "provider_revenue_cents": 1_020_000,
                "recipient_cost_cents": 1_020_000,
            },
            ANALYST,
        )
        tx = validate_success(resp, expected_status=201)
        assert_transaction(tx)
        # 1000000 * (10000 + 200) / 10000 = 1020000
        assert tx["provisional_al_price_cents"] == 1_020_000
        # (1020000 - 1000000) * 10000 / 1000000 = 200
        assert tx["margin_bp"] == 200
        assert tx["elimination_status"] == "UNMATCHED"
        assert tx["settlement_status"] == "UNSETTLED"
        assert tx["origin_run_id"] is None
        assert tx["is_true_up_adjustment"] is False

    def test_margin_rounds_half_up_at_exact_half(self):
        """PRD section 3.4: "The realized margin, `margin_bp`, is the excess
        of `provider_revenue_cents` over `cost_base_cents`, multiplied by
        10000 and divided by `cost_base_cents`, rounded half-up."
        PRD section 2.6: "Every computed monetary or basis-point value is
        rounded half-up to a whole integer at each computation step where a
        rule states a rounding — no banker's rounding, no truncation."

        Design: Corner/calculations/margin_bp_rounds_half_up_at_exact_half
        """
        ctx = setup_active_agreement()
        resp = api_client.create_transaction(
            {
                "agreement_id": ctx["agreement"]["id"],
                "fiscal_year_id": ctx["fiscal_year"]["id"],
                "cost_base_cents": 2_000_000,
                "provider_revenue_cents": 2_000_100,
                "recipient_cost_cents": 2_000_100,
            },
            ANALYST,
        )
        tx = validate_success(resp, expected_status=201)
        assert_transaction(tx)
        # raw margin = 100 * 10000 / 2000000 = exactly 0.5 -> half-up -> 1
        assert tx["margin_bp"] == 1
        # provisional price = 2000000 * 10200 / 10000 = 2040000
        assert tx["provisional_al_price_cents"] == 2_040_000


class TestBookingGates:

    def test_booking_against_draft_agreement_rejected(self):
        """PRD section 3.4: "Booking is only permitted against an agreement
        in `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`) and never against a `CLOSED`
        fiscal year (`ERR_BOOKS_CLOSED`)."

        Design: Difficulty/cross_entity_state_dependency/transaction_booking_requires_agreement_active
        """
        ctx = setup_year_entities_study()
        agreement = create_agreement(ctx["provider"]["id"],
                                     ctx["recipient"]["id"],
                                     ctx["study"]["id"])
        assert agreement["status"] == "DRAFT"

        resp = api_client.create_transaction(
            {
                "agreement_id": agreement["id"],
                "fiscal_year_id": ctx["fiscal_year"]["id"],
                "cost_base_cents": 1_000_000,
                "provider_revenue_cents": 1_020_000,
                "recipient_cost_cents": 1_020_000,
            },
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

    def test_booking_succeeds_after_activation(self):
        """PRD section 3.4: "Booking is only permitted against an agreement
        in `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`) and never against a `CLOSED`
        fiscal year (`ERR_BOOKS_CLOSED`)."
        PRD section 3.4: "A new booking starts `UNMATCHED` and `UNSETTLED`,
        with `origin_run_id` null and `is_true_up_adjustment` false."

        Design: Difficulty/cross_entity_state_dependency/transaction_booking_requires_agreement_active
        """
        ctx = setup_year_entities_study()
        agreement = create_agreement(ctx["provider"]["id"],
                                     ctx["recipient"]["id"],
                                     ctx["study"]["id"])
        api_client.activate_agreement(agreement["id"], MANAGER)

        resp = api_client.create_transaction(
            {
                "agreement_id": agreement["id"],
                "fiscal_year_id": ctx["fiscal_year"]["id"],
                "cost_base_cents": 1_000_000,
                "provider_revenue_cents": 1_020_000,
                "recipient_cost_cents": 1_020_000,
            },
            ANALYST,
        )
        tx = validate_success(resp, expected_status=201)
        assert tx["elimination_status"] == "UNMATCHED"

    def test_booking_into_closed_year_rejected(self):
        """PRD section 3.4: "Booking is only permitted against an agreement
        in `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`) and never against a `CLOSED`
        fiscal year (`ERR_BOOKS_CLOSED`)."

        Design: Corner/errors/booking_into_closed_year_rejected
        """
        # No transactions, no true-up runs, cbc not required: close succeeds.
        ctx = setup_active_agreement()
        begin_closing(ctx["fiscal_year"]["id"])
        close_year(ctx["fiscal_year"]["id"])

        resp = api_client.create_transaction(
            {
                "agreement_id": ctx["agreement"]["id"],
                "fiscal_year_id": ctx["fiscal_year"]["id"],
                "cost_base_cents": 1_000_000,
                "provider_revenue_cents": 1_020_000,
                "recipient_cost_cents": 1_020_000,
            },
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_BOOKS_CLOSED)


class TestMatchTolerance:

    def test_match_over_tolerance_rejected(self):
        """PRD section 3.4: "a `TaxAnalyst` matches a transaction when the
        two sides' booked amounts agree within a tolerance of 100 cents — the
        absolute difference between `provider_revenue_cents` and
        `recipient_cost_cents` must be at most 100, otherwise the match is
        rejected with `ERR_ELIMINATION_MISMATCH`."

        Design: Corner/errors/elimination_mismatch_over_tolerance_rejected
        """
        ctx = setup_active_agreement()
        tx = book_transaction(ctx["agreement"]["id"], ctx["fiscal_year"]["id"],
                              cost_base_cents=1_000_000,
                              provider_revenue_cents=1_000_200,
                              recipient_cost_cents=1_000_000)

        resp = api_client.match_transaction(tx["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_ELIMINATION_MISMATCH)

        after = validate_success(api_client.get_transaction(tx["id"], MANAGER),
                                 200)
        assert after["elimination_status"] == "UNMATCHED"


class TestEliminationInvariant:

    def test_elimination_conserves_consolidated_net_zero(self):
        """PRD section 3.4: "During the begin-closing ceremony every
        `MATCHED` transaction of the year moves to `ELIMINATED`, and each
        elimination books a consolidation plug equal to
        `provider_revenue_cents` minus `recipient_cost_cents`, so the year's
        `consolidated_intercompany_net_cents` — the running sum over
        eliminated transactions of provider revenue minus recipient cost
        minus the plug — increases by exactly zero with each entry."

        Design: Difficulty/compensating_invariant/booking_plus_elimination_conserves_consolidated_net_zero
        """
        # tx2 carries a 50-cent mismatch, inside the 100-cent tolerance.
        ctx = setup_agreement_with_matched_transactions(
            tx_specs=((1_000_000, 1_020_000), (2_000_000, 2_040_050, 2_040_000)))

        resp = api_client.begin_closing(ctx["fiscal_year"]["id"], ADMIN)
        closing_year = validate_success(resp, 200)
        assert closing_year["consolidated_intercompany_net_cents"] == 0, \
            "the plug absorbs the 50-cent mismatch, net stays 0"

    def test_begin_closing_eliminates_matched_pairs(self):
        """PRD section 3.4: "During the begin-closing ceremony every
        `MATCHED` transaction of the year moves to `ELIMINATED`"
        PRD section 3.4: "Eliminations are processed in chronological order
        of transaction creation, ascending, and the invariant that
        `consolidated_intercompany_net_cents` equals 0 holds after every
        elimination batch."

        Design: Difficulty/compensating_invariant/booking_plus_elimination_conserves_consolidated_net_zero
        """
        ctx = setup_agreement_with_matched_transactions(
            tx_specs=((1_000_000, 1_020_000), (2_000_000, 2_040_050, 2_040_000)))

        validate_success(api_client.begin_closing(ctx["fiscal_year"]["id"],
                                                  ADMIN), 200)
        for tx in ctx["transactions"]:
            after = validate_success(
                api_client.get_transaction(tx["id"], MANAGER), 200)
            assert after["elimination_status"] == "ELIMINATED"

        year = validate_success(
            api_client.get_fiscal_year(ctx["fiscal_year"]["id"], ADMIN), 200)
        assert year["status"] == "CLOSING"
        assert year["consolidated_intercompany_net_cents"] == 0


class TestParallelDimensions:

    def _setup_netting_before_closing(self):
        ctx = setup_agreement_with_matched_transactions(
            tx_specs=((1_000_000, 1_020_000),))
        pool = create_pool(ctx["fiscal_year"]["id"])
        return ctx, pool

    def test_netting_advances_settlement_independently(self):
        """PRD section 3.4: "Matching records `matched_by_user_id` and
        advances only the elimination dimension; the settlement dimension is
        untouched, and conversely netting (§3.8) operates on `MATCHED`
        transactions that have not yet been eliminated — the dimensions
        evolve independently."
        PRD section 3.8: "every transaction of the pool's fiscal year that is
        still `UNSETTLED` with an `elimination_status` of `MATCHED` or
        `ELIMINATED` transitions to `NETTED`, adding its
        `provider_revenue_cents` to the provider entity's balance and
        subtracting its `recipient_cost_cents` from the recipient entity's
        balance."

        Design: Difficulty/non_linear_state_machine/transaction_parallel_dimensions_advance_independently
        """
        ctx, pool = self._setup_netting_before_closing()
        netted_pool = begin_netting(pool["id"])

        tx = validate_success(
            api_client.get_transaction(ctx["transactions"][0]["id"], MANAGER),
            200)
        assert tx["settlement_status"] == "NETTED"
        assert tx["elimination_status"] == "MATCHED", \
            "netting must not advance the elimination dimension"

        provider_pos = find_position(netted_pool, ctx["provider"]["id"])
        recipient_pos = find_position(netted_pool, ctx["recipient"]["id"])
        assert provider_pos["balance_cents"] == 1_020_000
        assert recipient_pos["balance_cents"] == -1_020_000

    def test_begin_closing_advances_elimination_independently(self):
        """PRD section 3.4: "Matching records `matched_by_user_id` and
        advances only the elimination dimension; the settlement dimension is
        untouched, and conversely netting (§3.8) operates on `MATCHED`
        transactions that have not yet been eliminated — the dimensions
        evolve independently."
        PRD section 3.4: "During the begin-closing ceremony every `MATCHED`
        transaction of the year moves to `ELIMINATED`"

        Design: Difficulty/non_linear_state_machine/transaction_parallel_dimensions_advance_independently
        """
        ctx, pool = self._setup_netting_before_closing()
        begin_netting(pool["id"])
        begin_closing(ctx["fiscal_year"]["id"])

        tx = validate_success(
            api_client.get_transaction(ctx["transactions"][0]["id"], MANAGER),
            200)
        assert tx["elimination_status"] == "ELIMINATED"
        assert tx["settlement_status"] == "NETTED", \
            "elimination must not advance the settlement dimension"
