"""Financing lines, reserves, and utilization invariants."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_counterparty,
    create_financing_line,
    get_lot_for_shipment,
    pledge_reserve,
    release_reserve,
    set_clock,
    setup_released_lot,
    validate_error,
    validate_success,
)

RISK = TEST_USERS["risk_manager_headers"]
TRADER = TEST_USERS["trader_headers"]


class TestFacilityLimit:
    def test_facility_limit_exceeded(self, api):
        """PRD §3.6: "Two validations guard the pledge, evaluated in order:
        first facility headroom — the line's `utilized_usd` plus the new
        reserve's advance must not exceed `facility_limit_usd`, otherwise
        `ERR_FACILITY_LIMIT_EXCEEDED`"

        Design: Corner/validations/facility_limit_exceeded
        """
        set_clock()
        # 1000 lbs at 2.00/lb, advance rate 0.50 -> 1000.00 advance.
        ctx = setup_released_lot(supplier_ref="SUP-FLE", contract_ref="C-FLE",
                                  shipment_ref="SH-FLE", lot_code="L-FLE",
                                  received_lbs=1000, fixed_price=2.00)
        # Facility limit 100 -> advance 1000 > 100 -> ERR_FACILITY_LIMIT_EXCEEDED
        line = create_financing_line(lender_name="BankFLE",
                                      facility_limit_usd=100,
                                      advance_rate_pct=0.50)
        lot = ctx["green_lot"]
        resp = api.create_financing_reserve(
            line["id"],
            {"green_lot_id": lot["id"], "reserved_lbs": 1000},
            RISK,
        )
        validate_error(resp, ApiErrorId.ERR_FACILITY_LIMIT_EXCEEDED)


class TestFinancingUtilizationInvariant:
    def test_financing_line_utilization_conserved_under_release(self, api):
        """PRD §3.6: "Releasing a reserve is the mirror image. An `ACTIVE`
        reserve transitions to `RELEASED`; the pledged mass returns to the
        lot's `available_lbs`; the line's `utilized_usd` falls by the
        reserve's advance and its `collateral_value_usd` falls by the
        reserve's poundage times the lot's landed cost; the position
        recomputes; and both the reserve and the line increment their
        `version`."
        PRD §3.6: "The reserve's `reserve_advance_usd` is computed as
        `reserved_lbs` times the lot's `landed_cost_usd_per_lb` times the
        line's `advance_rate_pct`, rounded half-up to 2 decimals."

        Design: Difficulty/compensating_invariant/financing_line_utilization_conserved_under_release
        """
        set_clock()
        ctx = setup_released_lot(supplier_ref="SUP-U", contract_ref="C-U",
                                  shipment_ref="SH-U", lot_code="L-U",
                                  received_lbs=1000, fixed_price=2.00)
        lot = ctx["green_lot"]
        line = create_financing_line(lender_name="Bank U",
                                      facility_limit_usd=10000,
                                      advance_rate_pct=0.50)
        line0 = validate_success(api.get_financing_line(line["id"], RISK))
        assert line0["utilized_usd"] == 0
        # Forward: pledge 1000 lbs; advance = 1000 * 2.00 * 0.50 = 1000.00
        rsv = pledge_reserve(line["id"], lot["id"], 1000)
        assert rsv["reserve_advance_usd"] == pytest.approx(1000.00, abs=0.01)
        line1 = validate_success(api.get_financing_line(line["id"], RISK))
        assert line1["utilized_usd"] == pytest.approx(1000.00, abs=0.01)
        # Compensate: release returns utilization to zero.
        release_reserve(rsv["id"])
        line2 = validate_success(api.get_financing_line(line["id"], RISK))
        assert line2["utilized_usd"] == 0, (
            "release compensates exactly — zero drift"
        )
        rsv_after = validate_success(api.get_financing_reserve(rsv["id"], RISK))
        assert rsv_after["reserve_status"] == "RELEASED"

    def test_financing_release_returns_mass_to_lot(self, api):
        """PRD §3.6: "Releasing a reserve is the mirror image. An `ACTIVE`
        reserve transitions to `RELEASED`; the pledged mass returns to
        the lot's `available_lbs`; the line's `utilized_usd` falls by
        the reserve's advance and its `collateral_value_usd` falls by
        the reserve's poundage times the lot's landed cost; the position
        recomputes; and both the reserve and the line increment their
        `version`."

        Design: Difficulty/compensating_invariant/financing_line_utilization_conserved_under_release
        """
        set_clock()
        ctx = setup_released_lot(supplier_ref="SUP-U2", contract_ref="C-U2",
                                  shipment_ref="SH-U2", lot_code="L-U2",
                                  received_lbs=1000, fixed_price=2.00)
        lot = ctx["green_lot"]
        line = create_financing_line(lender_name="Bank U2",
                                      facility_limit_usd=10000,
                                      advance_rate_pct=0.50)
        # Pledge 400 lbs out of the 1000
        rsv = pledge_reserve(line["id"], lot["id"], 400)
        lot_mid = validate_success(api.get_green_lot(lot["id"], RISK))
        assert lot_mid["available_lbs"] == 600, (
            "pledge moves pounds out of the open pool"
        )
        # Release returns the pledged mass to the lot.
        release_reserve(rsv["id"])
        lot_after = validate_success(api.get_green_lot(lot["id"], RISK))
        assert lot_after["available_lbs"] == 1000, (
            "release returns pledged mass to available_lbs"
        )
        # Line's utilized_usd back to zero
        line_after = validate_success(
            api.get_financing_line(line["id"], RISK))
        assert line_after["utilized_usd"] == 0


class TestOverHedgeValidation:
    def test_over_hedge_rejected(self, api):
        """PRD §3.3: "then the over-hedge cap — the cumulative `hedge_lbs`
        across the contract's already-`APPROVED` hedges plus this hedge's
        pounds must not exceed the contract's `unpriced_lbs` at approval
        time, otherwise `ERR_OVER_HEDGE`."

        Design: Corner/validations/over_hedge_rejected
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-OH", credit_limit_usd=10000000)
        contract_resp = api.create_contract(
            supplier["id"],
            {"contract_ref": "C-OH", "pricing_mode": "DIFFERENTIAL_PTBF",
             "coffee_grade": "SHB", "total_lbs": 1000,
             "differential_usd_per_lb": 0.25,
             "delivery_window_start": "2026-08-01T00:00:00Z",
             "delivery_window_end": "2026-12-31T23:59:59Z"},
            TRADER,
        )
        contract = validate_success(contract_resp, 201)
        # Hedge 1 (600 lbs) submitted by trader-oh-1, approved by risk-oh.
        h1 = validate_success(api.create_futures_hedge(
            contract["id"],
            {"hedge_side": "BUY_FUTURES", "hedge_lbs": 600,
             "entry_price_usd_per_lb": 1.80},
            # Submitted by a distinct trader id so risk-oh can approve.
            {"X-User-ID": "trader-oh-1", "X-User-Role": "Trader"},
        ), 201)
        validate_success(api.approve_futures_hedge(
            h1["id"], {"X-User-ID": "risk-oh", "X-User-Role": "RiskManager"}))
        # Hedge 2 (500 lbs) submitted by trader-oh-2.
        h2 = validate_success(api.create_futures_hedge(
            contract["id"],
            {"hedge_side": "BUY_FUTURES", "hedge_lbs": 500,
             "entry_price_usd_per_lb": 1.80},
            {"X-User-ID": "trader-oh-2", "X-User-Role": "Trader"},
        ), 201)
        # 600 + 500 = 1100 > unpriced 1000 -> ERR_OVER_HEDGE
        resp = api.approve_futures_hedge(
            h2["id"], {"X-User-ID": "risk-oh", "X-User-Role": "RiskManager"})
        validate_error(resp, ApiErrorId.ERR_OVER_HEDGE)
