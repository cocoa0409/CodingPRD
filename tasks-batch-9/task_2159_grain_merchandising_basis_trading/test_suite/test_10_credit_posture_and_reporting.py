"""The desk's single derived ledger: utilisation, the posture gate it drives,
the freeze cascade into contract-level pricing locks, the risk-limit ceiling,
and the computed position report."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_desk_credit_invariants,
    create_pricing_order_payload,
    create_purchase_contract_payload,
    mark_position,
    new_bid,
    new_contract,
    new_desk,
    new_hedge_position,
    new_location,
    new_risk_limit,
    read_contract,
    read_desk,
    read_margin_call,
    read_position,
    read_position_report,
    setup_frozen_desk_with_unpriced_contract,
    setup_trading_floor,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS


MERCH = TEST_USERS["merchandiser_headers"]
RISK = TEST_USERS["risk_officer_headers"]
TRADER = TEST_USERS["futures_trader_headers"]


class TestFreezeCascade:
    """A mark that calls margin drives the desk to FROZEN, which locks pricing
    on the desk's unfinished contracts."""

    def test_the_call_raises_the_desk_open_call_total_and_drains_credit(self, api):
        """PRD §2.10: "Marking a position to market at a price that drops account
        equity below maintenance margin (hop 1) creates a margin call row in `OPEN`
        status; because that call now exists, the desk's `open_margin_call_usd`
        rises by the call amount and `available_credit_usd` and `credit_utilization`
        are recomputed (hop 2); because utilisation has crossed a breakpoint,
        `posture` is rewritten (hop 3); and if the new posture is `FROZEN`, then
        `pricing_locked` is set to true on every purchase contract of that desk
        whose `status` is `ACTIVE` and whose `pricing_status` is not yet
        `FULLY_PRICED` (hop 4)."
        PRD §2.9: "`available_credit_usd` is the credit line less the margin
        requirement less the open margin calls, rounded half-up to 2 decimal
        places."

        Design: Difficulty/transitive_cascade/mark_to_market_calls_margin_freezes_desk_locks_contract_pricing
        """
        scenario = setup_frozen_desk_with_unpriced_contract(
            desk_code="GD10", credit_line_usd=16000.00, lots_open=4,
            contract_bushels=10000, settlement_price_cents=500,
        )

        call = read_margin_call(scenario["margin_call"]["id"])
        assert call["call_amount_usd"] == pytest.approx(10400.00, abs=0.01)
        assert call["status"] == "OPEN"

        desk = read_desk(scenario["desk"]["id"])
        assert desk["open_margin_call_usd"] == pytest.approx(10400.00, abs=0.01)
        assert desk["available_credit_usd"] == pytest.approx(-1000.00, abs=0.01), (
            f"16,000.00 credit line less 6,600.00 margin less 10,400.00 of calls = "
            f"-1,000.00, got {desk['available_credit_usd']}"
        )
        assert read_position(scenario["position"]["id"])["status"] == "MARGIN_CALL"

    def test_utilisation_past_the_inclusive_breakpoint_freezes_the_desk(self, api):
        """PRD §2.9: "`credit_utilization` is the margin requirement plus the open
        margin calls, divided by the credit line, rounded half-up to 4 decimal
        places."
        PRD §2.9: "`posture` follows directly from that ratio, and both breakpoints
        are inclusive: the desk is `FROZEN` when `credit_utilization` is at or above
        1.0000, `RESTRICTED` when it is at or above 0.8000 but below 1.0000, and
        `NORMAL` otherwise."

        Design: Difficulty/transitive_cascade/mark_to_market_calls_margin_freezes_desk_locks_contract_pricing
        """
        scenario = setup_frozen_desk_with_unpriced_contract(
            desk_code="GD10", credit_line_usd=16000.00, lots_open=4,
            contract_bushels=10000, settlement_price_cents=500,
        )

        desk = read_desk(scenario["desk"]["id"])
        assert desk["credit_utilization"] == pytest.approx(1.0625, abs=0.0001), (
            f"(6,600.00 + 10,400.00) / 16,000.00 = 1.0625, got "
            f"{desk['credit_utilization']}"
        )
        assert desk["posture"] == "FROZEN"
        assert_desk_credit_invariants(desk)

    def test_the_freeze_locks_pricing_on_the_unfinished_contract(self, api):
        """PRD §2.10: "The `pricing_locked` flag is what makes the freeze bite at
        the contract level: while it is true, no pricing order may be placed against
        that contract and the contract may not be rolled, both refused with
        `ERR_PRICING_LOCKED`."
        PRD §3.5: "And the contract's `pricing_locked` flag must be false, or
        `ERR_PRICING_LOCKED` answers — a check that, as Section 2.8 fixes, is
        evaluated **before** the desk-posture gate, so a locked contract on a frozen
        desk reports the lock rather than `ERR_DESK_FROZEN`."

        Design: Difficulty/transitive_cascade/mark_to_market_calls_margin_freezes_desk_locks_contract_pricing
        """
        scenario = setup_frozen_desk_with_unpriced_contract(
            desk_code="GD10", credit_line_usd=16000.00, lots_open=4,
            contract_bushels=10000, settlement_price_cents=500,
        )

        contract = read_contract(scenario["contract"]["id"])
        assert contract["pricing_locked"] is True, (
            "an ACTIVE contract that is not yet FULLY_PRICED is locked by the freeze"
        )

        payload = create_pricing_order_payload(
            contract["id"], component="BASIS", bushels=10000, price_cents=-30,
        )
        resp = api.create_pricing_order(payload, MERCH)
        error = validate_error(resp, ApiErrorId.ERR_PRICING_LOCKED.value, 409)
        assert resp.status_code == 409
        assert error["error_id"] != ApiErrorId.ERR_DESK_FROZEN.value, (
            "the contract-level lock is reported ahead of the desk-level freeze"
        )


class TestPostureGatesNewBusiness:

    def test_a_frozen_desk_cannot_write_a_new_contract(self, api):
        """PRD §2.9: "Posture is not a label; it is a gate. While a desk is
        `FROZEN`, no new purchase contract may be struck against it, no pricing
        order may be placed on its contracts, and no contract of its may be rolled —
        all three are refused with `ERR_DESK_FROZEN`."
        PRD §3.4: "A desk whose `posture` is `FROZEN` cannot write new business at
        all and answers `ERR_DESK_FROZEN`."

        Design: Corner/validations/creating_a_contract_on_a_frozen_desk_returns_desk_frozen
        """
        floor = setup_trading_floor(desk_code="CD41", desk_name="Corner Desk 41",
                                    credit_line_usd=16000.00, with_schedule=False,
                                    lots_open=4, avg_entry_price_cents=448)
        spare_position = new_hedge_position(
            floor["desk"]["id"], commodity_code="CORN", futures_month="2026-12",
            side="SHORT", lots_open=4, avg_entry_price_cents=448,
        )
        mark_position(floor["position"]["id"], 500)

        assert read_position(spare_position["id"])["status"] == "OPEN", (
            "the spare position stays OPEN so the priority-12 state rule cannot "
            "mask the posture gate"
        )
        desk = read_desk(floor["desk"]["id"])
        assert desk["credit_utilization"] == pytest.approx(1.4750, abs=0.0001)
        assert desk["posture"] == "FROZEN"

        payload = create_purchase_contract_payload(
            floor["bid"]["id"], spare_position["id"], contract_type="CASH",
            bushels=10000, seller_name="Bell Farms", futures_price_cents=448,
        )
        resp = api.create_purchase_contract(payload, MERCH)
        validate_error(resp, ApiErrorId.ERR_DESK_FROZEN.value, 409)
        assert resp.status_code == 409

        assert read_position(spare_position["id"])["lots_committed"] == 0

    def test_a_restricted_desk_refuses_deferred_but_still_writes_cash(self, api):
        """PRD §2.9: "A desk sitting at exactly 0.8000 is `RESTRICTED`; a desk
        sitting at exactly 1.0000 is `FROZEN`."
        PRD §3.4: "A desk whose `posture` is `RESTRICTED` can still write `CASH`,
        `HTA` and `BASIS` contracts but refuses a `DEFERRED` one with
        `ERR_DESK_RESTRICTED`."

        Design: Corner/validations/deferred_contract_on_a_restricted_desk_returns_desk_restricted
        """
        floor = setup_trading_floor(desk_code="CD29", desk_name="Corner Desk 29",
                                    credit_line_usd=8250.00, with_schedule=False,
                                    lots_open=4, avg_entry_price_cents=448)

        desk = read_desk(floor["desk"]["id"])
        assert desk["credit_utilization"] == pytest.approx(0.8000, abs=0.0001), (
            f"6,600.00 / 8,250.00 = 0.8000 exactly, got {desk['credit_utilization']}"
        )
        assert desk["posture"] == "RESTRICTED"

        deferred = create_purchase_contract_payload(
            floor["bid"]["id"], floor["position"]["id"], contract_type="DEFERRED",
            bushels=10000, seller_name="Bell Farms",
        )
        resp = api.create_purchase_contract(deferred, MERCH)
        validate_error(resp, ApiErrorId.ERR_DESK_RESTRICTED.value, 409)
        assert resp.status_code == 409

        cash = create_purchase_contract_payload(
            floor["bid"]["id"], floor["position"]["id"], contract_type="CASH",
            bushels=10000, seller_name="Bell Farms", futures_price_cents=448,
        )
        accepted = validate_success(api.create_purchase_contract(cash, MERCH), 201)
        assert accepted["pricing_status"] == "FULLY_PRICED"


class TestRiskLimitCeiling:
    """The unpriced-bushel ceiling is a strictly-greater-than test, so a
    projected total landing exactly on the ceiling is accepted."""

    def _limit_floor(self):
        desk = new_desk(desk_code="GD15", name="Limit Boundary Desk")
        new_risk_limit(desk["id"], commodity_code="CORN",
                       max_unpriced_bushels=100000, max_net_short_lots=100)
        location = new_location(desk["id"], location_code="ELV1",
                                name="Morris Elevator",
                                intake_capacity_bushels=5000000, rail_served=True)
        position = new_hedge_position(
            desk["id"], commodity_code="CORN", futures_month="2026-12",
            side="SHORT", lots_open=20, avg_entry_price_cents=448,
        )
        bid = new_bid(location["id"], activate=True, commodity_code="CORN",
                      futures_month="2026-12", basis_cents=-32, max_bushels=1000000)
        return {"desk": desk, "location": location, "position": position, "bid": bid}

    def test_a_projected_total_exactly_on_the_ceiling_is_accepted(self, api):
        """PRD §3.4: "Next the risk limit: if an `ACTIVE` risk limit exists for this
        desk and commodity, the desk's current `unpriced_bushels` plus the unpriced
        bushels the new contract would itself carry must not be **strictly greater**
        than `max_unpriced_bushels`. A projected total landing exactly on the
        ceiling is accepted; only a total above it is refused, with
        `ERR_RISK_LIMIT_BREACH`."
        PRD §2.9: "`unpriced_bushels` on the desk is the sum of each `ACTIVE`
        contract's own unpriced bushel figure."

        Design: Difficulty/boundary_precision_check/risk_limit_accepts_exactly_at_ceiling_rejects_one_bushel_over
        """
        floor = self._limit_floor()

        payload = create_purchase_contract_payload(
            floor["bid"]["id"], floor["position"]["id"], contract_type="DEFERRED",
            bushels=100000, seller_name="Bell Farms",
        )
        contract = validate_success(api.create_purchase_contract(payload, MERCH), 201)

        assert contract["unpriced_bushels"] == pytest.approx(100000.00, abs=0.01)
        assert contract["pricing_status"] == "UNPRICED"
        assert contract["hedge_lots_assigned"] == 20
        assert read_desk(floor["desk"]["id"])["unpriced_bushels"] == pytest.approx(
            100000.00, abs=0.01
        )

    def test_one_bushel_past_the_ceiling_is_refused(self, api):
        """PRD §3.4: "A projected total landing exactly on the ceiling is accepted;
        only a total above it is refused, with `ERR_RISK_LIMIT_BREACH`."
        PRD §3.4: "When no `ACTIVE` limit exists for that desk-and-commodity pairing,
        the check is skipped entirely rather than treated as a limit of zero."

        Design: Difficulty/boundary_precision_check/risk_limit_accepts_exactly_at_ceiling_rejects_one_bushel_over
        """
        floor = self._limit_floor()
        new_contract(
            floor["bid"]["id"], floor["position"]["id"], contract_type="DEFERRED",
            bushels=100000, seller_name="Bell Farms",
        )

        payload = create_purchase_contract_payload(
            floor["bid"]["id"], floor["position"]["id"], contract_type="DEFERRED",
            bushels=1, seller_name="Halberd Farms",
        )
        resp = api.create_purchase_contract(payload, MERCH)
        validate_error(resp, ApiErrorId.ERR_RISK_LIMIT_BREACH.value, 422)
        assert resp.status_code == 422

        assert read_desk(floor["desk"]["id"])["unpriced_bushels"] == pytest.approx(
            100000.00, abs=0.01
        ), "the rejected strike adds no unpriced exposure"


class TestPositionReport:

    def test_the_report_covers_active_contracts_and_hedge_coverage(self, api):
        """PRD §3.9: "`cash_long_bushels` is the sum over the scoped contracts of
        contracted bushels less delivered bushels. `unpriced_bushels` is the sum of
        the scoped contracts' own unpriced quantities. `net_futures_lots` is the
        sum, over the desk's hedge positions whose `status` is `OPEN` or
        `MARGIN_CALL` and narrowed the same way, of the position's side sign
        multiplied by its `lots_open` — so short lots enter negative and long lots
        positive. `required_hedge_lots` is `cash_long_bushels` divided by 5,000
        bushels per lot, rounded half-up to a whole number."
        PRD §3.9: "`margin_requirement_usd`, `open_margin_call_usd`,
        `credit_utilization` and `posture` are read straight off the desk."
        PRD §3.9: "Otherwise it reads `BREACH` when the scoped `unpriced_bushels`
        strictly exceeds the limit's `max_unpriced_bushels`, or when the absolute
        size of the net **short** position — the magnitude of `net_futures_lots`
        when that figure is negative, and zero when it is not — strictly exceeds
        `max_net_short_lots`; and `WITHIN` when neither ceiling is breached."

        Design: Corner/endpoints/position_report_reflects_active_contracts_and_hedge_coverage
        """
        desk = new_desk(desk_code="CD42", name="Corner Desk 42")
        new_risk_limit(desk["id"], commodity_code="CORN",
                       max_unpriced_bushels=50000, max_net_short_lots=20)
        location = new_location(desk["id"], location_code="E1", name="One",
                                intake_capacity_bushels=5000000, rail_served=True)
        position = new_hedge_position(
            desk["id"], commodity_code="CORN", futures_month="2026-12",
            side="SHORT", lots_open=10, avg_entry_price_cents=448,
        )
        bid = new_bid(location["id"], activate=True, commodity_code="CORN",
                      futures_month="2026-12", basis_cents=-32, max_bushels=1000000)
        new_contract(bid["id"], position["id"], contract_type="HTA", bushels=20000,
                     seller_name="Bell Farms", futures_price_cents=448)

        report = read_position_report(desk["id"], commodity_code="CORN")

        assert report["cash_long_bushels"] == pytest.approx(20000.00, abs=0.01)
        assert report["unpriced_bushels"] == pytest.approx(20000.00, abs=0.01)
        assert report["net_futures_lots"] == -10, (
            f"a SHORT position enters negative, got {report['net_futures_lots']}"
        )
        assert report["required_hedge_lots"] == 4
        assert report["hedge_coverage_ratio"] == pytest.approx(2.5000, abs=0.0001), (
            f"abs(-10) / 4 = 2.5000, got {report['hedge_coverage_ratio']}"
        )
        assert report["margin_requirement_usd"] == pytest.approx(16500.00, abs=0.01)
        assert report["open_margin_call_usd"] == pytest.approx(0, abs=0.01)
        assert report["credit_utilization"] == pytest.approx(0.0033, abs=0.0001)
        assert report["posture"] == "NORMAL"
        assert report["risk_limit_status"] == "WITHIN"

    def _empty_scope_desk(self):
        desk = new_desk(desk_code="GD16", name="Empty Scope Desk")
        new_risk_limit(desk["id"], commodity_code="CORN",
                       max_unpriced_bushels=500000, max_net_short_lots=2)
        position = new_hedge_position(
            desk["id"], commodity_code="CORN", futures_month="2026-12",
            side="SHORT", lots_open=3, avg_entry_price_cents=448,
        )
        return desk, position

    def test_an_empty_contract_scope_yields_zeros_and_never_a_division_error(
            self, api):
        """PRD §3.9: "`hedge_coverage_ratio` is zero when no lots are required — an
        empty book yields zeros and never a division by zero — and otherwise the
        absolute value of `net_futures_lots` divided by `required_hedge_lots`,
        rounded half-up to 4 decimal places."
        PRD §3.9: "The report's scope is the desk's purchase contracts whose
        `status` is `ACTIVE`, narrowed to the requested commodity when one is given;
        settled, cancelled, defaulted and rolled contracts are all outside the
        scope, as are liquidated hedge positions."

        Design: Difficulty/boundary_precision_check/position_report_empty_contract_scope_yields_zero_coverage_ratio
        """
        desk, _ = self._empty_scope_desk()

        resp = api.get_position_report(desk["id"], RISK,
                                       params={"commodity_code": "CORN"})
        report = validate_success(resp, 200)

        assert resp.status_code == 200, "an empty book is a 200, not an error"
        assert report["cash_long_bushels"] == pytest.approx(0, abs=0.01)
        assert report["unpriced_bushels"] == pytest.approx(0, abs=0.01)
        assert report["required_hedge_lots"] == 0
        assert report["hedge_coverage_ratio"] == pytest.approx(0, abs=0.0001)

    def test_the_short_lot_limb_breaches_even_with_no_contracts_at_all(self, api):
        """PRD §3.9: "`net_futures_lots` is the sum, over the desk's hedge positions
        whose `status` is `OPEN` or `MARGIN_CALL` and narrowed the same way, of the
        position's side sign multiplied by its `lots_open` — so short lots enter
        negative and long lots positive."
        PRD §3.9: "Otherwise it reads `BREACH` when the scoped `unpriced_bushels`
        strictly exceeds the limit's `max_unpriced_bushels`, or when the absolute
        size of the net **short** position — the magnitude of `net_futures_lots`
        when that figure is negative, and zero when it is not — strictly exceeds
        `max_net_short_lots`; and `WITHIN` when neither ceiling is breached."

        Design: Difficulty/boundary_precision_check/position_report_empty_contract_scope_yields_zero_coverage_ratio
        """
        desk, _ = self._empty_scope_desk()

        report = read_position_report(desk["id"], commodity_code="CORN")

        assert report["net_futures_lots"] == -3
        assert report["risk_limit_status"] == "BREACH", (
            "three short lots strictly exceed the two-lot ceiling"
        )
