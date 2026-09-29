"""The futures book: opening positions, re-averaging on added lots, marking to
market, the margin call it raises, curing it, and the liquidation gates."""

import pytest

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    advance_clock,
    assert_hedge_position,
    assert_margin_call,
    assert_position_margin_invariants,
    create_hedge_position_payload,
    cure_call,
    mark_position,
    new_desk,
    new_hedge_position,
    open_margin_call_for,
    read_desk,
    read_margin_call,
    read_position,
    setup_contract_scenario,
    setup_position_in_margin_call,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS


TRADER = TEST_USERS["futures_trader_headers"]
RISK = TEST_USERS["risk_officer_headers"]


class TestOpeningAndGrowingAPosition:

    def test_new_position_posts_initial_margin_and_seeds_the_settlement_price(self, api):
        """PRD §3.3: "At creation the position posts initial margin:
        `posted_margin_usd` becomes the open lot count multiplied by the per-lot
        initial margin for the commodity — 1,650.00 dollars for `CORN`, 3,300.00 for
        `SOYBEANS`, 2,200.00 for `HRW_WHEAT` — and `last_settlement_price_cents` is
        seeded to the entry price so that an unmarked position shows no unrealised
        profit or loss."
        PRD §3.3: "`lots_available` on any position is simply its open lots less its
        committed lots."

        Design: Corner/entities/hedge_position_computed_fields_start_at_zero_and_ignore_client_input
        """
        desk = new_desk(desk_code="CD08", name="Corner Desk 8")

        payload = create_hedge_position_payload(
            desk["id"], commodity_code="CORN", futures_month="2026-12",
            side="SHORT", lots_open=6, avg_entry_price_cents=448,
        )
        position = validate_success(api.create_hedge_position(payload, TRADER), 201)
        assert_hedge_position(position)

        assert position["posted_margin_usd"] == pytest.approx(9900.00, abs=0.01), (
            f"6 CORN lots post 6 x 1,650.00 = 9,900.00, got "
            f"{position['posted_margin_usd']}"
        )
        assert position["last_settlement_price_cents"] == pytest.approx(448, abs=0.0001)
        assert position["lots_committed"] == 0
        assert position["lots_available"] == 6
        assert position["unrealized_pnl_usd"] == pytest.approx(0, abs=0.01)
        assert position["status"] == "OPEN"
        assert_position_margin_invariants(position)

        assert read_desk(desk["id"])["margin_requirement_usd"] == pytest.approx(
            9900.00, abs=0.01
        )

    def test_adding_lots_reaverages_the_entry_price_to_four_decimals(self, api):
        """PRD §3.3: "Adding lots takes a `lots` count and a `fill_price_cents`, and
        rewrites `avg_entry_price_cents` as the volume-weighted blend of the old and
        new fills: the prior average multiplied by the prior open lots, plus the
        fill price multiplied by the lots being added, all divided by the sum of the
        prior open lots and the added lots, rounded half-up to 4 decimal places."
        PRD §3.3: "`lots_open` then becomes the prior open lots plus the added lots,
        and `posted_margin_usd` is recomputed as the new open lot count multiplied
        by the commodity's per-lot initial margin, rounded half-up to 2 decimal
        places."

        Design: Corner/calculations/add_lots_reaverages_entry_price_to_four_decimal_places
        """
        desk = new_desk(desk_code="CD20", name="Corner Desk 20")
        position = new_hedge_position(
            desk["id"], commodity_code="CORN", futures_month="2026-12",
            side="SHORT", lots_open=4, avg_entry_price_cents=448,
        )

        grown = validate_success(api.add_lots(
            position["id"], {"lots": 3, "fill_price_cents": 455}, TRADER
        ), 200)

        assert grown["avg_entry_price_cents"] == pytest.approx(451.0000, abs=0.0001), (
            f"(448*4 + 455*3) / 7 = 451.0000, got {grown['avg_entry_price_cents']}"
        )
        assert grown["lots_open"] == 7
        assert grown["posted_margin_usd"] == pytest.approx(11550.00, abs=0.01)
        assert read_desk(desk["id"])["margin_requirement_usd"] == pytest.approx(
            11550.00, abs=0.01
        )


class TestMarkToMarketAndMarginCalls:

    def test_a_short_corn_position_marked_against_itself_books_the_loss(self, api):
        """PRD §3.3: "`unrealized_pnl_usd` becomes that sign multiplied by the
        difference between the supplied settlement price and
        `avg_entry_price_cents`, multiplied by `lots_open`, multiplied by 5,000
        bushels per lot, divided by 100 to convert cents into dollars, rounded
        half-up to 2 decimal places."
        PRD §3.3: "The position is breached only when account equity is **strictly
        less** than that maintenance requirement; equity exactly equal to
        maintenance does not call."

        Design: Difficulty/combinatorial_formula/margin_call_amount_three_input_nonlinear
        """
        desk = new_desk(desk_code="GD5", name="Thin Credit Desk",
                        credit_line_usd=16000.00)
        position = new_hedge_position(
            desk["id"], commodity_code="CORN", futures_month="2026-12",
            side="SHORT", lots_open=4, avg_entry_price_cents=448,
        )
        assert position["posted_margin_usd"] == pytest.approx(6600.00, abs=0.01)

        marked = validate_success(api.mark_to_market(
            position["id"], {"settlement_price_cents": 500}, TRADER
        ), 200)

        assert marked["unrealized_pnl_usd"] == pytest.approx(-10400.00, abs=0.01), (
            f"-1 x (500 - 448) x 4 x 5000 / 100 = -10,400.00, got "
            f"{marked['unrealized_pnl_usd']}"
        )
        assert marked["last_settlement_price_cents"] == pytest.approx(500, abs=0.0001)
        assert marked["status"] == "MARGIN_CALL", (
            "equity of -3,800.00 is strictly below the 6,000.00 maintenance floor"
        )

    def test_the_call_restores_the_position_to_full_initial_margin(self, api):
        """PRD §3.3: "The call's `call_amount_usd` is the amount needed to restore
        the position to full initial margin: the initial requirement — `lots_open`
        multiplied by the commodity's per-lot initial margin, rounded half-up to 2
        decimal places — less the account equity just computed, floored at zero so a
        call is never negative, rounded half-up to 2 decimal places."
        PRD §3.3: "Its `issued_at` is the logical clock reading at that moment and
        its `cure_deadline_at` is exactly 24 hours later."

        Design: Difficulty/combinatorial_formula/margin_call_amount_three_input_nonlinear
        """
        scenario = setup_position_in_margin_call(
            desk_code="GD5", credit_line_usd=16000.00, lots_open=4,
            avg_entry_price_cents=448, settlement_price_cents=500,
        )
        call = read_margin_call(scenario["margin_call"]["id"])
        assert_margin_call(call)

        assert call["call_amount_usd"] == pytest.approx(10400.00, abs=0.01), (
            f"6,600.00 initial less -3,800.00 equity = 10,400.00, got "
            f"{call['call_amount_usd']}"
        )
        assert call["status"] == "OPEN"
        assert call["hedge_position_id"] == scenario["position"]["id"]
        assert call["issued_at"] == "2026-08-01T00:00:00.000Z"
        assert call["cure_deadline_at"] == "2026-08-02T00:00:00.000Z"

    def test_a_short_payment_inside_the_window_is_refused(self, api):
        """PRD §3.3: "the logical clock must be at or before `cure_deadline_at`,
        with a cure landing on exactly that instant still accepted and anything
        strictly later refused with `ERR_MARGIN_CALL_EXPIRED`; and the payment must
        be at least the full `call_amount_usd`, with anything smaller refused as
        `ERR_CURE_AMOUNT_INSUFFICIENT` — partial cures are not a concept here."

        Design: Corner/validations/curing_a_call_with_a_short_payment_returns_cure_amount_insufficient
        """
        scenario = setup_position_in_margin_call(
            desk_code="CD39", lots_open=4, avg_entry_price_cents=448,
            settlement_price_cents=500,
        )
        call = scenario["margin_call"]
        assert call["issued_at"] == "2026-08-01T00:00:00.000Z"
        assert call["cure_deadline_at"] == "2026-08-02T00:00:00.000Z"
        assert call["call_amount_usd"] == pytest.approx(10400.00, abs=0.01)

        validate_error(
            api.cure_margin_call(call["id"], {"payment_usd": 100.00}, RISK),
            ApiErrorId.ERR_CURE_AMOUNT_INSUFFICIENT.value, 422,
        )

        after = read_margin_call(call["id"])
        assert after["status"] == "OPEN"
        assert after["cured_amount_usd"] == pytest.approx(0, abs=0.01)
        position = read_position(scenario["position"]["id"])
        assert position["posted_margin_usd"] == pytest.approx(6600.00, abs=0.01)
        assert position["status"] == "MARGIN_CALL"

    def test_curing_an_unknown_margin_call_is_a_not_found(self, api):
        """PRD §2.8: "Every id embedded in the URL path resolves to a stored row,
        checked left to right. The code names the missing entity:
        `ERR_TRADING_DESK_NOT_FOUND`, `ERR_LOCATION_NOT_FOUND`,
        `ERR_DISCOUNT_SCHEDULE_NOT_FOUND`, `ERR_RISK_LIMIT_NOT_FOUND`,
        `ERR_RAIL_FLEET_NOT_FOUND`, `ERR_BID_NOT_FOUND`,
        `ERR_HEDGE_POSITION_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
        `ERR_PRICING_ORDER_NOT_FOUND`, `ERR_MARGIN_CALL_NOT_FOUND`,
        `ERR_DELIVERY_TICKET_NOT_FOUND` or `ERR_FREIGHT_BOOKING_NOT_FOUND`, each at
        HTTP 404."

        Design: Corner/errors/curing_an_unknown_margin_call_id_returns_margin_call_not_found
        """
        new_desk(desk_code="CD45", name="Corner Desk 45", credit_line_usd=250000.00)

        validate_error(
            api.cure_margin_call(UNKNOWN_UUID, {"payment_usd": 5000.00}, RISK),
            ApiErrorId.ERR_MARGIN_CALL_NOT_FOUND.value, 404,
        )


class TestMarginCallCycle:
    """OPEN → MARGIN_CALL → OPEN → MARGIN_CALL on one position."""

    def test_curing_a_call_adds_the_payment_to_posted_margin_and_reopens(self, api):
        """PRD §3.3: "On success the call moves `OPEN → CURED` with
        `cured_amount_usd` set to the payment actually made, the payment is added to
        the position's `posted_margin_usd`, and the position moves
        `MARGIN_CALL → OPEN`."

        Design: Difficulty/non_linear_state_machine/hedge_position_open_margin_call_open_margin_call_cycle
        """
        scenario = setup_position_in_margin_call(
            desk_code="GD8", lots_open=4, avg_entry_price_cents=448,
            settlement_price_cents=500,
        )
        call = scenario["margin_call"]

        cured = validate_success(api.cure_margin_call(
            call["id"], {"payment_usd": 10400.00}, RISK
        ), 200)
        assert cured["status"] == "CURED"
        assert cured["cured_amount_usd"] == pytest.approx(10400.00, abs=0.01)

        position = read_position(scenario["position"]["id"])
        assert position["posted_margin_usd"] == pytest.approx(17000.00, abs=0.01), (
            f"6,600.00 posted plus the 10,400.00 cure = 17,000.00, got "
            f"{position['posted_margin_usd']}"
        )
        assert position["status"] == "OPEN"

    def test_a_second_mark_after_a_cure_raises_a_smaller_second_call(self, api):
        """PRD §3.3: "A single position may travel `OPEN → MARGIN_CALL → OPEN` any
        number of times over its life."
        PRD §3.3: "The call's `call_amount_usd` is the amount needed to restore the
        position to full initial margin: the initial requirement — `lots_open`
        multiplied by the commodity's per-lot initial margin, rounded half-up to 2
        decimal places — less the account equity just computed, floored at zero so a
        call is never negative, rounded half-up to 2 decimal places."

        Design: Difficulty/non_linear_state_machine/hedge_position_open_margin_call_open_margin_call_cycle
        """
        scenario = setup_position_in_margin_call(
            desk_code="GD8", lots_open=4, avg_entry_price_cents=448,
            settlement_price_cents=500,
        )
        first_call = scenario["margin_call"]
        cure_call(first_call["id"], 10400.00)

        marked = mark_position(scenario["position"]["id"], 520)
        assert marked["status"] == "MARGIN_CALL"
        assert marked["unrealized_pnl_usd"] == pytest.approx(-14400.00, abs=0.01), (
            f"-1 x (520 - 448) x 4 x 5000 / 100 = -14,400.00, got "
            f"{marked['unrealized_pnl_usd']}"
        )

        second_call = open_margin_call_for(scenario["position"]["id"])
        assert second_call["id"] != first_call["id"], (
            "the second breach raises a fresh call row"
        )
        assert second_call["call_amount_usd"] == pytest.approx(4000.00, abs=0.01), (
            f"6,600.00 initial less 2,600.00 equity = 4,000.00, got "
            f"{second_call['call_amount_usd']}"
        )
        assert read_margin_call(first_call["id"])["status"] == "CURED"

    def test_a_cured_call_leaves_the_position_available_to_call_again(self, api):
        """PRD §3.3: "When equity falls below maintenance, the position moves
        `OPEN → MARGIN_CALL` and a call row is raised against it."
        PRD §3.3: "A single position may travel `OPEN → MARGIN_CALL → OPEN` any
        number of times over its life."

        Design: Difficulty/non_linear_state_machine/hedge_position_open_margin_call_open_margin_call_cycle
        """
        scenario = setup_position_in_margin_call(
            desk_code="GD8", lots_open=4, avg_entry_price_cents=448,
            settlement_price_cents=500,
        )
        cure_call(scenario["margin_call"]["id"], 10400.00)
        assert read_position(scenario["position"]["id"])["status"] == "OPEN"

        mark_position(scenario["position"]["id"], 520)

        _, meta = validate_paginated(api.list_margin_calls(
            RISK, params={"hedge_position_id": scenario["position"]["id"]}
        ))
        assert meta["total_count"] == 2, (
            f"one cured call plus one fresh call, got {meta['total_count']}"
        )
        assert read_position(scenario["position"]["id"])["status"] == "MARGIN_CALL"


class TestExpiredCurePrecedesShortPayment:
    """A cure request that is both late and short reports the earlier ladder
    row (rank 19) rather than the later one (rank 37)."""

    def _late_and_short(self):
        desk = new_desk(desk_code="GD13", name="Ladder C Desk")
        advance_clock("2026-08-05T00:00:00Z")
        position = new_hedge_position(
            desk["id"], commodity_code="CORN", futures_month="2026-12",
            side="SHORT", lots_open=4, avg_entry_price_cents=448,
        )
        mark_position(position["id"], 500)
        call = open_margin_call_for(position["id"])
        advance_clock("2026-08-06T00:00:01Z")
        return desk, position, call

    def test_the_cure_deadline_is_exactly_twenty_four_hours_after_issue(self, api):
        """PRD §3.3: "Its `issued_at` is the logical clock reading at that moment
        and its `cure_deadline_at` is exactly 24 hours later."
        PRD §2.5: "Nothing else in the system moves on a clock tick — margin call
        deadlines, delivery grace periods and bid activation windows are all
        evaluated at the moment a request touches them, by comparing the
        request-time clock reading against the stored instant."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_expired_margin_call_cure
        """
        _, _, call = self._late_and_short()

        assert call["issued_at"] == "2026-08-05T00:00:00.000Z"
        assert call["cure_deadline_at"] == "2026-08-06T00:00:00.000Z", (
            f"issued_at plus 24 hours, got {call['cure_deadline_at']}"
        )

    def test_a_late_and_short_cure_reports_the_expiry_not_the_shortfall(self, api):
        """PRD §2.8: "Every request is screened by an ordered sequence of checks,
        and **the first check that fails decides the response**."
        PRD §2.8: "This ordering is normative, not a description of a convenient
        implementation: when two conditions are simultaneously violated, the
        response must name the earlier one."
        PRD §3.3: "the logical clock must be at or before `cure_deadline_at`, with a
        cure landing on exactly that instant still accepted and anything strictly
        later refused with `ERR_MARGIN_CALL_EXPIRED`; and the payment must be at
        least the full `call_amount_usd`, with anything smaller refused as
        `ERR_CURE_AMOUNT_INSUFFICIENT` — partial cures are not a concept here."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_expired_margin_call_cure
        """
        _, position, call = self._late_and_short()

        resp = api.cure_margin_call(call["id"], {"payment_usd": 100.00}, RISK)
        error = validate_error(resp, ApiErrorId.ERR_MARGIN_CALL_EXPIRED.value, 422)
        assert error["error_id"] != ApiErrorId.ERR_CURE_AMOUNT_INSUFFICIENT.value

        after = read_margin_call(call["id"])
        assert after["status"] == "OPEN"
        assert after["cured_amount_usd"] == pytest.approx(0, abs=0.01)
        assert read_position(position["id"])["status"] == "MARGIN_CALL"

    def test_a_late_cure_leaves_the_call_open_for_forced_liquidation(self, api):
        """PRD §3.3: "The call must still be `OPEN`, or the request is refused with
        `ERR_INVALID_STATE`; the logical clock must be at or before
        `cure_deadline_at`, with a cure landing on exactly that instant still
        accepted and anything strictly later refused with `ERR_MARGIN_CALL_EXPIRED`;
        and the payment must be at least the full `call_amount_usd`, with anything
        smaller refused as `ERR_CURE_AMOUNT_INSUFFICIENT` — partial cures are not a
        concept here."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_expired_margin_call_cure
        """
        _, position, call = self._late_and_short()

        validate_error(
            api.cure_margin_call(call["id"], {"payment_usd": 100000.00}, RISK),
            ApiErrorId.ERR_MARGIN_CALL_EXPIRED.value, 422,
        )
        assert read_margin_call(call["id"])["status"] == "OPEN", (
            "a payment large enough to cure is still refused once the deadline passed"
        )


class TestLiquidationPreconditions:

    def test_liquidating_a_position_holding_committed_lots_is_refused(self, api):
        """PRD §3.3: "The voluntary path runs from `OPEN` and requires that the
        position carry no committed lots at all — `lots_committed` must be zero,
        meaning no `ACTIVE` purchase contract is still relying on it — and a
        position with live commitments is refused with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/liquidate_open_position_holding_committed_lots_returns_invalid_state
        """
        scenario = setup_contract_scenario(
            desk_code="CD17", desk_name="Corner Desk 17", with_schedule=False,
            lots_open=10, contract_overrides={"contract_type": "CASH", "bushels": 20000},
        )
        position_id = scenario["position"]["id"]

        validate_error(
            api.liquidate_hedge_position(
                position_id, {"settlement_price_cents": 455}, TRADER
            ),
            ApiErrorId.ERR_INVALID_STATE.value, 409,
        )

        position = read_position(position_id)
        assert position["status"] == "OPEN"
        assert position["lots_committed"] == 4
        assert position["posted_margin_usd"] == pytest.approx(16500.00, abs=0.01)
        assert position["realized_pnl_usd"] == pytest.approx(0, abs=0.01)
