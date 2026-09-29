"""Refusals caused by a row the request never names.

Each call here targets resources that are themselves in a perfectly legal state.
What blocks it sits one edge away: the dealer facing the trade, the station under
the flight leg, the sibling trade behind the collateral row. Curing that third
row — and nothing else — lets the identical call through.
"""

from test_helpers import (
    ADMIN,
    ERR_COLLATERAL_SHORTFALL,
    ERR_COUNTERPARTY_NOT_APPROVED,
    ERR_INSTRUMENT_INVALID_TRADE_STATE,
    ERR_PROGRAM_NOT_ACTIVE,
    ERR_STATION_INVENTORY_SHORT,
    ERR_TANKERING_NOT_ECONOMIC,
    ERR_TANKERING_WEIGHT_LIMIT,
    OPS,
    TREASURY,
    assert_counterparty_credit,
    assert_instrument_ledgers,
    assert_instrument_status,
    assert_money,
    assert_nothing_pinned,
    assert_pinned_prices,
    assert_program_coverage,
    assert_station_supply,
    factories as f,
    fixtures as fx,
    validate_error,
)

#: The dealer every scenario in this file faces.
DEALER_A = dict(
    counterparty_code="DLRA",
    legal_name="Dealer A Bank NA",
    credit_rating="A",
    credit_limit_usd=1000000.00,
)

#: The two review notes of the downgrade-and-cure scenario.
DOWNGRADE_NOTE = "Downgrade after covenant breach."
REINSTATEMENT_NOTE = "Covenant cured; reinstated."

#: Half the stock the origin station needs to leave `SHORT`.
THIN_OPENING_STOCK = 250000

#: Each of the two 1,500,000-gallon swaps carries this much margin at 0.06 a
#: gallon, and each collateral row therefore freezes the same requirement.
CE3_MARGIN_USD = 90000.00


def _posting_by_id(api, instrument_id, posting_id):
    """Collateral rows are readable only through their parents' lists."""
    rows = fx.list_instrument_postings(api, instrument_id)
    matches = [row for row in rows if row["id"] == posting_id]
    assert matches, f"posting {posting_id} not listed under instrument {instrument_id}"
    return matches[0]


class TestExecuteBlockedBySuspendedCounterparty:
    @staticmethod
    def _active_program_facing_a_downgraded_dealer(api):
        ctx = fx.setup_active_program_with_proposed_swap(
            api,
            policy_overrides=dict(policy_code="FY27-CE1"),
            counterparty_overrides=DEALER_A,
            program_overrides=dict(program_code="HP-CE1", target_coverage_pct=20.00),
            swap_overrides=dict(
                notional_gallons=2000000,
                strike_usd_per_gal=2.4000,
                maturity_month="2027-03",
            ),
        )
        ctx["counterparty"] = fx.do_credit_review(
            api, ctx["counterparty"]["id"], "BB", DOWNGRADE_NOTE
        )
        return ctx

    def test_the_downgrade_suspends_the_dealer_and_the_trade_cannot_be_done(self, api):
        """PRD §3.1: "A review that lands on `BB` sets `status` to `SUSPENDED`; a
        review that lands on any rating above `BB` — that is, `BBB`, `A` or `AA` —
        sets `status` back to `APPROVED`, which is how a downgraded dealer is
        rehabilitated."

        PRD §3.4: "The facing counterparty must be `APPROVED`, otherwise
        `ERR_COUNTERPARTY_NOT_APPROVED`."

        Nothing about the request is wrong: the trade is `PROPOSED` and its
        programme is `ACTIVE`. The dealer named in the body of a call made weeks
        earlier is what refuses it.

        Design: Difficulty/cross_entity_state_dependency/execute_blocked_by_suspended_counterparty
        """
        ctx = self._active_program_facing_a_downgraded_dealer(api)
        assert ctx["counterparty"]["status"] == "SUSPENDED"

        error = validate_error(
            api.execute_hedge_instrument(ctx["instrument"]["id"], headers=TREASURY),
            ERR_COUNTERPARTY_NOT_APPROVED,
            409,
        )
        assert error["error_id"] not in (
            ERR_INSTRUMENT_INVALID_TRADE_STATE,
            ERR_PROGRAM_NOT_ACTIVE,
        )

    def test_neither_row_named_in_the_path_was_at_fault(self, api):
        """PRD §2.5: "The target resource must be in a state from which the
        requested transition is declared, and any cross-entity state gate must hold
        — the owning programme must be `ACTIVE` for trade execution and for
        designation, and the owning trade must be `EXECUTED` for designation, for
        effectiveness testing and for collateral posting."

        The instrument the path names is still `PROPOSED` and the programme above it
        is still `ACTIVE`, which is precisely the point: the gate that fired reads a
        row that appears in neither the path nor the body of this request.

        Design: Difficulty/cross_entity_state_dependency/execute_blocked_by_suspended_counterparty
        """
        ctx = self._active_program_facing_a_downgraded_dealer(api)
        validate_error(
            api.execute_hedge_instrument(ctx["instrument"]["id"], headers=TREASURY),
            ERR_COUNTERPARTY_NOT_APPROVED,
            409,
        )

        assert_instrument_status(
            fx.read_instrument(api, ctx["instrument"]["id"]),
            trade_status="PROPOSED",
            accounting_status="UNDESIGNATED",
        )
        assert fx.read_program(api, ctx["program"]["id"])["status"] == "ACTIVE"
        assert_counterparty_credit(
            fx.read_counterparty(api, ctx["counterparty"]["id"]),
            utilized_credit_usd=0.00,
            utilization_pct=0.00,
        )

    def test_reinstating_the_rating_lets_the_identical_call_through(self, api):
        """PRD §3.1: "Because the limit may have moved, the review recomputes
        `utilization_pct` and `credit_posture` and increments the counterparty's
        `version` by one."

        PRD §3.4: "Step five multiplies the base margin by one plus the add-on rate
        and rounds to two decimal places, producing `margin_requirement_usd`."

        A second review at `A` restores `APPROVED` and records its note, and the
        execute that was refused a moment ago now writes 120,000.00 of margin,
        18.18 percent of delta coverage and 12.00 percent of the dealer's limit.

        Design: Difficulty/cross_entity_state_dependency/execute_blocked_by_suspended_counterparty
        """
        ctx = self._active_program_facing_a_downgraded_dealer(api)
        validate_error(
            api.execute_hedge_instrument(ctx["instrument"]["id"], headers=TREASURY),
            ERR_COUNTERPARTY_NOT_APPROVED,
            409,
        )

        reinstated = fx.do_credit_review(
            api, ctx["counterparty"]["id"], "A", REINSTATEMENT_NOTE
        )
        assert reinstated["status"] == "APPROVED"
        assert reinstated["last_review_note"] == REINSTATEMENT_NOTE

        executed = fx.do_execute_instrument(api, ctx["instrument"]["id"])
        assert_instrument_status(executed, trade_status="EXECUTED")
        assert_instrument_ledgers(executed, margin_requirement_usd=120000.00)

        assert_program_coverage(
            fx.read_program(api, ctx["program"]["id"]),
            consumption_basis_gallons=11000000,
            hedged_gallons=2000000,
            coverage_pct_delta=18.18,
        )
        assert_counterparty_credit(
            fx.read_counterparty(api, ctx["counterparty"]["id"]),
            utilized_credit_usd=120000.00,
            utilization_pct=12.00,
            credit_posture="NORMAL",
        )


class TestDirectiveApproveBlockedByShortOriginStation:
    @staticmethod
    def _economic_directive_over_a_short_origin(api):
        """A 3,000-gallon directive whose economics and envelope are both fine,
        proposed at a station holding only two and a half days of stock."""
        return fx.setup_proposed_directive(
            api,
            3000,
            policy_overrides=dict(policy_code="FY27-CE2"),
            leg_overrides=dict(flight_number="UA500", departure_date="2027-02-18"),
            origin_stock_gallons=THIN_OPENING_STOCK,
        )

    def test_the_station_posture_refuses_an_otherwise_impeccable_approval(self, api):
        """PRD §3.8: "The origin station's `supply_posture` must not be `SHORT`,
        otherwise `ERR_STATION_INVENTORY_SHORT`."

        PRD §3.2: "The rounded `days_cover` is then compared against the
        `min_days_cover` of the single `ACTIVE` hedging policy to set
        `supply_posture`: below that minimum the station is `SHORT`; from the
        minimum up to but not including twice the minimum it is `WATCH`; and at
        twice the minimum or above it is `NORMAL`."

        The uplift is 3,000 gallons against a 10,600.00 cap and the plan nets
        978.82 dollars, so neither the weight gate nor the economics gate has
        anything to say; 250,000 gallons over 100,000 daily liftings does.

        Design: Difficulty/cross_entity_state_dependency/directive_approve_blocked_by_short_origin_station
        """
        ctx = self._economic_directive_over_a_short_origin(api)

        assert_station_supply(
            fx.read_station(api, ctx["origin"]["id"]),
            inventory_gallons=250000.00,
            days_cover=2.50,
            supply_posture="SHORT",
        )
        assert_money(
            ctx["directive"]["planned_net_savings_usd"], 978.82, "planned_net_savings_usd"
        )

        error = validate_error(
            api.approve_tankering_directive(ctx["directive"]["id"], headers=OPS),
            ERR_STATION_INVENTORY_SHORT,
            422,
        )
        assert error["error_id"] not in (
            ERR_TANKERING_NOT_ECONOMIC,
            ERR_TANKERING_WEIGHT_LIMIT,
        )

    def test_the_refusal_pins_no_price_and_leaves_the_directive_proposed(self, api):
        """PRD §3.8: "Creating a directive opens it in `PROPOSED` status with
        `revision_count` 0, `proposed_by_user_id` from the caller's `X-User-ID`,
        `approved_by_user_id` null, and every pinned and reconciled field —
        `pinned_origin_price_usd_per_gal`, `pinned_destination_price_usd_per_gal`,
        `pinned_origin_contract_ref`, `reconciled_burn_penalty_gallons`,
        `reconciled_net_savings_usd` and `savings_variance_usd` — null."

        The gate sits ahead of the pinning step, so the directive is exactly as
        creation left it: still `PROPOSED`, still unapproved, still carrying no
        frozen prices.

        Design: Difficulty/cross_entity_state_dependency/directive_approve_blocked_by_short_origin_station
        """
        ctx = self._economic_directive_over_a_short_origin(api)
        validate_error(
            api.approve_tankering_directive(ctx["directive"]["id"], headers=OPS),
            ERR_STATION_INVENTORY_SHORT,
            422,
        )

        directive = fx.read_directive(api, ctx["directive"]["id"])
        assert directive["status"] == "PROPOSED"
        assert directive["approved_by_user_id"] is None
        assert_nothing_pinned(directive)

    def test_stocking_the_third_row_alone_lets_the_approval_pin_its_prices(self, api):
        """PRD §3.2: "Each adjustment recomputes the station's derived supply fields
        and increments the station's `version` by one."

        PRD §3.8: "Approval then pins prices: `pinned_origin_price_usd_per_gal` and
        `pinned_destination_price_usd_per_gal` are frozen from the two active
        contracts' all-in prices as of the approval instant, and
        `pinned_origin_contract_ref` records the `contract_ref` of the origin
        contract selected."

        A resupply of 250,000 gallons lifts the origin to five days of cover and
        `WATCH`. The directive itself was never touched — same uplift, same
        economics — and the identical approval now succeeds at 2.4700 and 3.1000.

        Design: Difficulty/cross_entity_state_dependency/directive_approve_blocked_by_short_origin_station
        """
        ctx = self._economic_directive_over_a_short_origin(api)
        validate_error(
            api.approve_tankering_directive(ctx["directive"]["id"], headers=OPS),
            ERR_STATION_INVENTORY_SHORT,
            422,
        )

        restocked = fx.do_adjust_inventory(
            api, ctx["origin"]["id"], THIN_OPENING_STOCK, "Resupply barge received"
        )
        assert_station_supply(
            restocked,
            inventory_gallons=500000.00,
            days_cover=5.00,
            supply_posture="WATCH",
        )

        approved = fx.do_approve_directive(api, ctx["directive"]["id"])
        assert approved["status"] == "APPROVED"
        assert_pinned_prices(
            approved,
            pinned_origin_price_usd_per_gal=2.4700,
            pinned_destination_price_usd_per_gal=3.1000,
            pinned_origin_contract_ref="ORD-2027-A",
        )


class TestCollateralPostBlockedByTerminatedParentTrade:
    @staticmethod
    def _two_collateralised_trades_one_of_them_unwound(api):
        """Two 1,500,000-gallon swaps facing one dealer, each with a `REQUIRED`
        row for 90,000.00, after the first trade has been terminated."""
        ctx = fx.setup_sized_program(
            api,
            policy_overrides=dict(policy_code="FY27-CE3"),
            counterparty_overrides=DEALER_A,
            program_overrides=dict(program_code="HP-CE3", target_coverage_pct=28.00),
        )
        program_id = ctx["program"]["id"]
        counterparty_id = ctx["counterparty"]["id"]
        ctx["dead"] = fx.do_propose_swap(
            api,
            program_id,
            counterparty_id,
            notional_gallons=1500000,
            strike_usd_per_gal=2.4000,
            maturity_month="2027-03",
        )
        ctx["live"] = fx.do_propose_swap(
            api,
            program_id,
            counterparty_id,
            notional_gallons=1500000,
            strike_usd_per_gal=2.4100,
            maturity_month="2027-03",
        )
        fx.do_submit_program(api, program_id)
        ctx["program"] = fx.do_activate_program(api, program_id)
        ctx["dead"] = fx.do_execute_instrument(api, ctx["dead"]["id"])
        ctx["live"] = fx.do_execute_instrument(api, ctx["live"]["id"])

        ctx["dead_posting"] = fx.do_create_posting(
            api, counterparty_id, ctx["dead"]["id"]
        )
        ctx["live_posting"] = fx.do_create_posting(
            api, counterparty_id, ctx["live"]["id"]
        )
        ctx["dead"] = fx.do_terminate_instrument(
            api, ctx["dead"]["id"], "Unwound before any collateral moved."
        )
        return ctx

    def test_the_sibling_trade_state_answers_before_the_rows_own_amount(self, api):
        """PRD §3.5: "The covered trade must still be `EXECUTED`, otherwise
        `ERR_INSTRUMENT_INVALID_TRADE_STATE`, and the `amount_usd` offered must be
        greater than or equal to the row's frozen `required_amount_usd`, otherwise
        `ERR_COLLATERAL_SHORTFALL` — over-posting is allowed, under-posting is not."

        PRD §2.5: "**Collateral sufficiency** on collateral posting, otherwise
        `ERR_COLLATERAL_SHORTFALL` (422)."

        The row is in `REQUIRED`, the only state `POSTED` is reachable from, and
        10,000.00 is nowhere near the 90,000.00 it froze. The answer is still the
        409 about the trade, because the state gate sits at rung 7 and the
        sufficiency check at rung 23.

        Design: Difficulty/cross_entity_state_dependency/collateral_post_blocked_by_terminated_parent_trade
        """
        ctx = self._two_collateralised_trades_one_of_them_unwound(api)

        dead_row = _posting_by_id(api, ctx["dead"]["id"], ctx["dead_posting"]["id"])
        assert dead_row["status"] == "REQUIRED"
        assert_money(dead_row["required_amount_usd"], CE3_MARGIN_USD, "required_amount_usd")
        assert_instrument_status(ctx["dead"], trade_status="TERMINATED")

        error = validate_error(
            api.post_collateral(
                ctx["dead_posting"]["id"],
                f.post_collateral_payload(10000.00),
                headers=ADMIN,
            ),
            ERR_INSTRUMENT_INVALID_TRADE_STATE,
            409,
        )
        assert error["error_id"] != ERR_COLLATERAL_SHORTFALL

        after = _posting_by_id(api, ctx["dead"]["id"], ctx["dead_posting"]["id"])
        assert after["status"] == "REQUIRED"
        assert_money(after["posted_amount_usd"], 0, "posted_amount_usd")

    def test_the_same_short_amount_against_a_live_trade_reaches_the_shortfall_check(
        self, api
    ):
        """PRD §3.5: "Creation opens the row in `REQUIRED` status with `origin`
        `MANUAL` and `posted_amount_usd` at 0, and freezes `required_amount_usd` at
        that moment as the trade's `margin_requirement_usd` less its
        `collateral_posted_usd`, floored at zero so a fully collateralised trade
        yields a requirement of 0.00."

        The two rows are twins — same dealer, same frozen 90,000.00, same
        10,000.00 offered. Only the parent trade differs, and against the
        `EXECUTED` one the masked amount check finally speaks.

        Design: Difficulty/cross_entity_state_dependency/collateral_post_blocked_by_terminated_parent_trade
        """
        ctx = self._two_collateralised_trades_one_of_them_unwound(api)

        live_row = _posting_by_id(api, ctx["live"]["id"], ctx["live_posting"]["id"])
        assert_money(live_row["required_amount_usd"], CE3_MARGIN_USD, "required_amount_usd")

        error = validate_error(
            api.post_collateral(
                ctx["live_posting"]["id"],
                f.post_collateral_payload(10000.00),
                headers=ADMIN,
            ),
            ERR_COLLATERAL_SHORTFALL,
            422,
        )
        assert error["error_id"] != ERR_INSTRUMENT_INVALID_TRADE_STATE

    def test_the_full_amount_posts_and_the_surviving_required_row_still_counts(
        self, api
    ):
        """PRD §3.5: "Posting writes `posted_amount_usd` from the offered amount,
        stamps `posted_at` from the logical clock, adds the posted amount to both
        the counterparty's `posted_collateral_usd` and the trade's
        `collateral_posted_usd`, decrements the counterparty's
        `open_margin_call_count` by one, and increments the posting's, the
        counterparty's and the trade's `version` by one each."

        PRD §3.4: "The second hop fires *because* the trade is now terminated: every
        collateral row against this trade that is in `POSTED` status advances
        `POSTED → RETURNED` with `returned_at` stamped from the logical clock, while
        rows still sitting in `REQUIRED` are deliberately left untouched."

        Ninety thousand clears the twin row. The dealer's utilisation is the
        surviving trade's margin alone, 9.00 percent of its limit, and one open
        margin call remains — the untouched row against the unwound trade.

        Design: Difficulty/cross_entity_state_dependency/collateral_post_blocked_by_terminated_parent_trade
        """
        ctx = self._two_collateralised_trades_one_of_them_unwound(api)
        validate_error(
            api.post_collateral(
                ctx["live_posting"]["id"],
                f.post_collateral_payload(10000.00),
                headers=ADMIN,
            ),
            ERR_COLLATERAL_SHORTFALL,
            422,
        )

        posted = fx.do_post_collateral(api, ctx["live_posting"]["id"], CE3_MARGIN_USD)
        assert posted["status"] == "POSTED"
        assert_money(posted["posted_amount_usd"], CE3_MARGIN_USD, "posted_amount_usd")

        assert_counterparty_credit(
            fx.read_counterparty(api, ctx["counterparty"]["id"]),
            utilized_credit_usd=CE3_MARGIN_USD,
            posted_collateral_usd=CE3_MARGIN_USD,
            utilization_pct=9.00,
            open_margin_call_count=1,
        )
        assert_program_coverage(
            fx.read_program(api, ctx["program"]["id"]),
            hedged_gallons=1500000,
            coverage_pct_delta=13.64,
        )
