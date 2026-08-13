"""Valuation snapshots: dual-variant pricing, dual return metrics, overlap
windows, stale-input gate, NAV staleness, investor shares (PRD §3.6, §3.9)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    make_finance_headers, make_compliance_headers, make_investor_headers,
    create_portfolio_payload, create_schedule, list_payments, set_clock,
    setup_case_acquired,
)

CM = TEST_USERS["case_manager_headers"]
PM = TEST_USERS["portfolio_manager_headers"]
UW = TEST_USERS["underwriter_headers"]
FO_1 = make_finance_headers("fo_1")
CO_1 = make_compliance_headers("co_1")


def _portfolio_version(api, pf_id):
    return validate_success(api.get_portfolio(pf_id, PM))["version"]


def _create_snapshot(api, pf_id, period_start, period_end):
    return validate_success(api.create_valuation_snapshot(
        pf_id,
        {"period_start": period_start, "period_end": period_end,
         "expected_portfolio_version": _portfolio_version(api, pf_id)},
        PM,
    ), expected_status=201)


class TestDualVariantValuation:
    def test_policy_value_prospective_vs_investment(self, api):
        """PRD §3.9: "An `ACQUIRED` case under the `PROSPECTIVE` method — fair value
        — is the face times v-to-the-k minus the monthly premium times the annuity
        factor over the remaining k months, rounded half-up, where the rate comes
        from the portfolio's `discount_rate_bps`; this variant discounts the future
        death benefit net of future premiums. An `ACQUIRED` case under the
        `INVESTMENT` method — cost accretion — takes the case's
        `purchase_price_cents` plus the total `PAID` premium cents on its
        schedules, accretes that cost forward at the portfolio's annual discount
        rate compounded over the years held (the days between `acquired_at` and the
        valuation date divided by 365), rounds half-up, and caps the result at the
        face amount; this variant ignores life expectancy except through case
        status."
        PRD §3.9: "For every case, `months_elapsed` is the whole 30-day months
        between the latest eligible report's `delivered_at` and the valuation date,
        and `remaining_le_months` is the case's `blended_le_months` minus that
        figure, floored at 1."
        PRD §3.9: "The snapshot's `nav_cents` is the sum of its rows'
        `value_cents`."

        Design: Difficulty/dual_variant_calc/policy_value_prospective_vs_investment
        """
        ctx_pro = setup_case_acquired(
            start_clock="2026-07-20T00:00:00Z", fund_clock="2026-08-15T00:00:00Z",
            release_clock="2026-09-05T00:00:00Z",
        )
        ctx_inv = setup_case_acquired(
            start_clock="2026-07-20T00:00:00Z", fund_clock="2026-08-15T00:00:00Z",
            release_clock="2026-09-05T00:00:00Z",
            with_license=False,
            broker_overrides={"license_number": "BR-2"},
            policy_overrides={"policy_number": "P-2"},
            portfolio_method="INVESTMENT",
        )
        # No premium schedules: monthly premium falls back to annual/12 = 50000.
        set_clock("2026-12-01T00:00:00Z")
        snap_pro = _create_snapshot(api, ctx_pro["portfolio"]["id"], "2026-09-01", "2026-12-01")
        snap_inv = _create_snapshot(api, ctx_inv["portfolio"]["id"], "2026-09-01", "2026-12-01")

        detail_pro = validate_success(api.get_valuation_snapshot(snap_pro["id"], PM))
        assert detail_pro["method_used"] == "PROSPECTIVE"
        assert detail_pro["nav_cents"] == 1633437
        row_pro = detail_pro["policy_valuations"][0]
        assert row_pro["value_cents"] == 1633437
        assert row_pro["remaining_le_months"] == 82

        detail_inv = validate_success(api.get_valuation_snapshot(snap_inv["id"], PM))
        assert detail_inv["method_used"] == "INVESTMENT"
        assert detail_inv["nav_cents"] == 6164284

        assert detail_pro["nav_cents"] != detail_inv["nav_cents"], (
            "identical policy inputs diverge under the two valuation variants"
        )

    def test_policy_value_investment_cost_accretion_details(self, api):
        """PRD §3.9: "An `ACQUIRED` case under the `INVESTMENT` method — cost
        accretion — takes the case's `purchase_price_cents` plus the total `PAID`
        premium cents on its schedules, accretes that cost forward at the
        portfolio's annual discount rate compounded over the years held (the days
        between `acquired_at` and the valuation date divided by 365), rounds
        half-up, and caps the result at the face amount; this variant ignores life
        expectancy except through case status."
        PRD §3.9: "The snapshot values each case assigned to the portfolio whose
        status is `ACQUIRED`, `MATURED`, or `LAPSED`, producing one
        `policy_valuations` row per case carrying `case_id`, `remaining_le_months`,
        and `value_cents`."
        PRD §3.9: "Creation captures the portfolio's `valuation_method` into the
        snapshot's `method_used`"

        Design: Difficulty/dual_variant_calc/policy_value_prospective_vs_investment
        """
        ctx = setup_case_acquired(
            start_clock="2026-07-20T00:00:00Z", fund_clock="2026-08-15T00:00:00Z",
            release_clock="2026-09-05T00:00:00Z",
            portfolio_method="INVESTMENT",
        )
        case, pf = ctx["case"], ctx["portfolio"]
        assert case["acquired_at"] == "2026-09-05T00:00:00Z"
        # years_held = 87/365; cost 6000000 * (1.12)^(87/365) -> 6164284 (< face cap).
        set_clock("2026-12-01T00:00:00Z")
        snap = _create_snapshot(api, pf["id"], "2026-09-01", "2026-12-01")
        detail = validate_success(api.get_valuation_snapshot(snap["id"], PM))
        assert detail["method_used"] == "INVESTMENT"
        assert detail["nav_cents"] == 6164284
        assert len(detail["policy_valuations"]) == 1
        row = detail["policy_valuations"][0]
        assert row["case_id"] == case["id"]
        assert row["value_cents"] == 6164284

    def test_portfolio_return_mwr_vs_twr_diverge(self, api):
        """PRD §3.9: "The money-weighted return, `money_weighted_return_bps`, is the
        internal rate that makes the discounted sum of all flows zero, where each
        flow is discounted at one-plus-r raised to the number of days from
        `period_start` to the flow's date, divided by 365. The rate is solved by
        bisection over the interval from negative 0.9999 to 10.0 using exactly 64
        iterations, then multiplied by ten thousand and rounded half-up to integer
        basis points. The time-weighted return, `time_weighted_return_bps`, follows
        the Modified Dietz method: with D the days between `period_start` and
        `period_end`, and F the sum of external flows excluding the initial and
        terminal flows, the return is V1 minus V0 minus F, divided by V0 plus the
        day-weighted sum of external flows — each flow weighted by D minus its day
        offset, over D."
        PRD §3.9: "The two metrics are algebraically different views of the same
        flows: the money-weighted figure is sensitive to cash-flow timing, while
        the Dietz figure weights each flow only by its day position."

        Design: Difficulty/dual_variant_calc/portfolio_return_mwr_vs_twr_diverge
        """
        ctx = setup_case_acquired(
            start_clock="2026-07-20T00:00:00Z", fund_clock="2026-08-15T00:00:00Z",
            release_clock="2026-09-05T00:00:00Z",
            insured_overrides={"gender": "F"},
        )
        case, pf = ctx["case"], ctx["portfolio"]
        # Schedule at 2026-09-05 (remaining_le 85, PAY_AS_DUE monthly 50000).
        sched = create_schedule(case["id"])
        pay1 = list_payments(sched["id"])[0]
        assert pay1["due_date"] == "2026-10-05T00:00:00Z"
        set_clock("2026-11-01T00:00:00Z")
        validate_success(api.pay_premium(pay1["id"], {"amount_cents": 50000}, FO_1))

        set_clock("2026-12-01T00:00:00Z")
        snap = _create_snapshot(api, pf["id"], "2026-09-01", "2026-12-01")
        detail = validate_success(api.get_valuation_snapshot(snap["id"], PM))
        assert detail["nav_cents"] == 1633437
        assert detail["money_weighted_return_bps"] == -9950
        assert detail["time_weighted_return_bps"] == -7214
        assert detail["money_weighted_return_bps"] != detail["time_weighted_return_bps"]

    def test_portfolio_return_metrics_diverge_on_same_flows(self, api):
        """PRD §3.9: "The two metrics are algebraically different views of the same
        flows: the money-weighted figure is sensitive to cash-flow timing, while
        the Dietz figure weights each flow only by its day position."
        PRD §3.9: "Portfolio cash flows are the funding outflow — the case's
        `purchase_price_cents` negative, dated at the escrow's `funded_at` — and
        each premium payment's `amount_cents` negative, dated at its `paid_at`;
        death-claim proceeds are deliberately not cash flows here, because a
        matured case already enters the terminal NAV at `net_proceeds_cents`, and
        the fee overage funded beyond price is not a portfolio flow either."

        Design: Difficulty/dual_variant_calc/portfolio_return_mwr_vs_twr_diverge
        """
        ctx = setup_case_acquired(
            start_clock="2026-07-20T00:00:00Z", fund_clock="2026-08-15T00:00:00Z",
            release_clock="2026-09-05T00:00:00Z",
            insured_overrides={"gender": "F"},
        )
        case, pf = ctx["case"], ctx["portfolio"]
        sched = create_schedule(case["id"])
        pay1 = list_payments(sched["id"])[0]
        set_clock("2026-11-01T00:00:00Z")
        validate_success(api.pay_premium(pay1["id"], {"amount_cents": 50000}, FO_1))

        set_clock("2026-12-01T00:00:00Z")
        snap = _create_snapshot(api, pf["id"], "2026-09-01", "2026-12-01")
        detail = validate_success(api.get_valuation_snapshot(snap["id"], PM))
        # V0 = 6000000 funded at 2026-08-15 (before period); premium 50000 at day 61.
        assert detail["money_weighted_return_bps"] == -9950
        assert detail["time_weighted_return_bps"] == -7214
        # The fee overage (90000 funded beyond price) is not a portfolio flow:
        # invested capital tracks price + paid premiums only.
        pf_after = validate_success(api.get_portfolio(pf["id"], PM))
        assert pf_after["invested_capital_cents"] == 6050000


class TestSnapshotWindowsAndInputs:
    def test_snapshot_window_overlap_rejected_but_adjacency_allowed(self, api):
        """PRD §3.9: "The new snapshot's window must not overlap any existing
        `FINALIZED` snapshot on the same portfolio — adjacency, where the new start
        equals another snapshot's end, is allowed; overlap is rejected with
        `ERR_SNAPSHOT_PERIOD_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/snapshot_window_overlap_rejected_but_adjacency_allowed
        """
        ctx = setup_case_acquired(
            start_clock="2026-07-20T00:00:00Z", fund_clock="2026-08-15T00:00:00Z",
            release_clock="2026-09-05T00:00:00Z",
        )
        pf = ctx["portfolio"]
        set_clock("2026-12-01T00:00:00Z")
        s1 = _create_snapshot(api, pf["id"], "2026-09-01", "2026-12-01")
        finalized = validate_success(api.finalize_snapshot(s1["id"], PM))
        assert finalized["status"] == "FINALIZED"

        # Adjacent: start == S1's exclusive end is not an overlap.
        s2 = _create_snapshot(api, pf["id"], "2026-12-01", "2027-03-01")
        assert s2["status"] == "DRAFT"

        # Interior overlap with the FINALIZED window is rejected.
        resp = api.create_valuation_snapshot(
            pf["id"], {"period_start": "2026-11-15", "period_end": "2027-02-01",
                       "expected_portfolio_version": _portfolio_version(api, pf["id"])},
            PM)
        validate_error(resp, ApiErrorId.ERR_SNAPSHOT_PERIOD_OVERLAP)

        rows, _m = validate_paginated(api.list_valuation_snapshots(pf["id"], PM))
        assert len(rows) == 2, "no third snapshot persisted after the rejected create"
        by_id = {r["id"]: r for r in rows}
        assert by_id[s1["id"]]["status"] == "FINALIZED"
        assert by_id[s2["id"]]["status"] == "DRAFT"

    def test_snapshot_window_interior_overlap_rejected(self, api):
        """PRD §3.9: "The new snapshot's window must not overlap any existing
        `FINALIZED` snapshot on the same portfolio — adjacency, where the new start
        equals another snapshot's end, is allowed; overlap is rejected with
        `ERR_SNAPSHOT_PERIOD_OVERLAP` (HTTP 409)."
        PRD §3.9: "a valuation snapshot — a write carrying the OCC field
        `expected_portfolio_version` per §2.6 — with `period_start` and
        `period_end` as ISO dates delimiting a half-open window: `period_start`
        inclusive, `period_end` exclusive, and the exclusive end date is the as-of
        date for every valuation input."

        Design: Difficulty/resource_temporal_overlap/snapshot_window_overlap_rejected_but_adjacency_allowed
        """
        ctx = setup_case_acquired(
            start_clock="2026-07-20T00:00:00Z", fund_clock="2026-08-15T00:00:00Z",
            release_clock="2026-09-05T00:00:00Z",
            broker_overrides={"license_number": "BR-S2"},
            policy_overrides={"policy_number": "P-S2"},
        )
        pf = ctx["portfolio"]
        set_clock("2026-12-01T00:00:00Z")
        s1 = _create_snapshot(api, pf["id"], "2026-09-01", "2026-12-01")
        validate_success(api.finalize_snapshot(s1["id"], PM))

        # Overlap by one day at the tail of the FINALIZED window.
        resp = api.create_valuation_snapshot(
            pf["id"], {"period_start": "2026-11-30", "period_end": "2027-02-01",
                       "expected_portfolio_version": _portfolio_version(api, pf["id"])},
            PM)
        validate_error(resp, ApiErrorId.ERR_SNAPSHOT_PERIOD_OVERLAP)

        rows, _m = validate_paginated(api.list_valuation_snapshots(pf["id"], PM))
        assert len(rows) == 1

    def test_snapshot_invalid_period_rejected(self, api):
        """PRD §3.9: "The end must be strictly later than the start, otherwise
        `ERR_INVALID_PERIOD` (HTTP 422)."

        Design: Corner/validations/snapshot_invalid_period_rejected
        """
        pf = validate_success(api.create_portfolio(create_portfolio_payload(), PM),
                              expected_status=201)
        resp = api.create_valuation_snapshot(
            pf["id"], {"period_start": "2026-12-01", "period_end": "2026-09-01",
                       "expected_portfolio_version": pf["version"]}, PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD)

    def test_valuation_rejected_with_stale_le_then_refresh(self, api):
        """PRD §3.9: "Every `ACQUIRED` case in the portfolio must have at least one
        `DELIVERED` unexpired life-expectancy report at creation, otherwise
        `ERR_VALUATION_INPUT_STALE` (HTTP 422)."
        PRD §3.2: "While a case is in `UNDERWRITING`, `MARKETED`, or `ACQUIRED`, an
        underwriter may order a life-expectancy report by supplying the
        `underwriter_tier`"

        Design: Corner/calculations/valuation_rejected_with_stale_le_then_refresh
        """
        # Default-clock chain: LE delivered 2026-08-01, valid_through 2027-01-28.
        ctx = setup_case_acquired(
            license_overrides={"expiry_date": "2028-12-31"},
            insured_overrides={"smoker_status": "UNKNOWN"},
        )
        case, pf = ctx["case"], ctx["portfolio"]
        set_clock("2027-01-29T00:00:00Z")  # all delivered reports auto-EXPIRED

        resp = api.create_valuation_snapshot(
            pf["id"], {"period_start": "2026-08-16", "period_end": "2027-01-29",
                       "expected_portfolio_version": _portfolio_version(api, pf["id"])},
            PM)
        validate_error(resp, ApiErrorId.ERR_VALUATION_INPUT_STALE)

        le2 = validate_success(api.order_le_report(case["id"], {"underwriter_tier": "B"}, UW),
                               expected_status=201)
        validate_success(api.deliver_le_report(
            le2["id"], {"base_le_months": 60, "impairment_debits": []}, UW))
        snap = validate_success(api.create_valuation_snapshot(
            pf["id"], {"period_start": "2026-08-16", "period_end": "2027-01-29",
                       "expected_portfolio_version": _portfolio_version(api, pf["id"])},
            PM), expected_status=201)
        assert snap["status"] == "DRAFT"


class TestNavStaleness:
    def test_nav_stale_lifecycle(self, api):
        """PRD §3.9: "Finalizing a `DRAFT` snapshot — a portfolio-manager action —
        re-checks the overlap rule against other `FINALIZED` snapshots on the
        portfolio (`ERR_SNAPSHOT_PERIOD_OVERLAP`), supersedes any prior `FINALIZED`
        snapshot on the same portfolio, writes the snapshot's `nav_cents` into the
        portfolio's `cached_nav_cents`, clears the portfolio's `nav_stale` to
        false, and increments the portfolio's `version`."
        PRD §3.7: "A valid payment stamps `paid_at`, moves the row from `SCHEDULED`
        to `PAID` with a version increment, adds the amount to the schedule's
        `total_paid_cents`, and through the case's portfolio adds the amount to
        `invested_capital_cents`, sets `nav_stale` true, and increments the
        portfolio's `version`."
        PRD §3.5: "Funding also dirties the destination portfolio in one cascade:
        the portfolio's `invested_capital_cents` grows by the case's
        `purchase_price_cents`, its `holding_count` grows by 1, `nav_stale` becomes
        true, and the portfolio's `version` increments."

        Design: Corner/cross_cutting_layers/nav_stale_lifecycle
        """
        ctx = setup_case_acquired(
            start_clock="2026-07-20T00:00:00Z", fund_clock="2026-08-15T00:00:00Z",
            release_clock="2026-09-05T00:00:00Z",
            insured_overrides={"smoker_status": "UNKNOWN"},
        )
        case, pf = ctx["case"], ctx["portfolio"]
        sched = create_schedule(case["id"])  # PAY_AS_DUE, monthly 50000

        stale0 = validate_success(api.get_portfolio(pf["id"], PM))
        assert stale0["nav_stale"] is True, "funding dirtied the NAV"

        snap = _create_snapshot(api, pf["id"], "2026-08-01", "2026-09-05")
        assert snap["nav_cents"] == 1438349, "PROSPECTIVE at k = 85, monthly 50000"
        validate_success(api.finalize_snapshot(snap["id"], PM))
        after_fin = validate_success(api.get_portfolio(pf["id"], PM))
        assert after_fin["nav_stale"] is False
        assert after_fin["cached_nav_cents"] == 1438349

        set_clock("2026-10-06T00:00:00Z")
        pay1 = list_payments(sched["id"])[0]
        validate_success(api.pay_premium(pay1["id"], {"amount_cents": 50000}, FO_1))
        stale2 = validate_success(api.get_portfolio(pf["id"], PM))
        assert stale2["nav_stale"] is True, "premium payment re-dirtied the NAV"


class TestInvestorShares:
    def test_investor_share_drift_to_largest_unitholder(self, api):
        """PRD §3.9: "Reading a snapshot's detail derives per-investor shares of the
        finalized NAV. With `total_units` the sum of `units` across the portfolio's
        `allocations`, each allocation's share is the NAV multiplied by its `units`
        and divided by `total_units`, rounded half-up, processed in stored array
        order. The rounding drift — the NAV minus the sum of the rounded shares, a
        small integer possibly negative — is added to the share of the allocation
        holding the largest `units`; on a tie in units, the drift goes to the
        allocation whose investor's `created_at` is earliest."

        Design: Corner/calculations/investor_share_drift_to_largest_unitholder
        """
        from test_helpers import create_investor
        set_clock("2026-07-20T00:00:00Z")
        inv1 = create_investor(name="Inv One", investor_type="FUND")
        inv2 = create_investor(name="Inv Two", investor_type="INDIVIDUAL")
        inv3 = create_investor(name="Inv Three", investor_type="INDIVIDUAL")
        allocations = [{"investor_id": inv1["id"], "units": 3},
                       {"investor_id": inv2["id"], "units": 1},
                       {"investor_id": inv3["id"], "units": 1}]
        ctx = setup_case_acquired(
            fund_clock="2026-08-15T00:00:00Z", release_clock="2026-09-05T00:00:00Z",
            portfolio_allocations=allocations,
            insured_overrides={"smoker_status": "UNKNOWN"},
        )
        pf = ctx["portfolio"]
        set_clock("2026-12-01T00:00:00Z")
        snap = _create_snapshot(api, pf["id"], "2026-09-01", "2026-12-01")
        assert snap["nav_cents"] == 1633437
        validate_success(api.finalize_snapshot(snap["id"], PM))

        detail = validate_success(api.get_valuation_snapshot(snap["id"], PM))
        shares = detail["investor_shares"]
        by_investor = {s["investor_id"]: s["share_cents"] for s in shares}
        # Raw shares [980062, 326687, 326687] sum to 1633436; the +1 drift lands
        # on the largest unitholder (3 units).
        assert by_investor[inv1["id"]] == 980063
        assert by_investor[inv2["id"]] == 326687
        assert by_investor[inv3["id"]] == 326687
        assert sum(by_investor.values()) == 1633437 == detail["nav_cents"]


class TestSnapshotOCC:
    def test_occ_snapshot_create_stale_version(self, api):
        """PRD §2.6: "Creating a valuation snapshot on a portfolio requires
        `expected_portfolio_version` matching the portfolio's current `version`.
        Because creation supersedes the current `DRAFT` snapshot and must price
        against the latest holdings and invested-capital state, a mismatch is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.9: "Creation captures the portfolio's `valuation_method` into the
        snapshot's `method_used`, supersedes any existing `DRAFT` snapshot on the
        portfolio, increments the portfolio's `version`, and begins the snapshot in
        `DRAFT`."

        Design: Corner/cross_cutting_layers/occ_snapshot_create_stale_version
        """
        pf = validate_success(api.create_portfolio(
            create_portfolio_payload(name="P"), PM), expected_status=201)
        v0 = pf["version"]
        s1 = validate_success(api.create_valuation_snapshot(
            pf["id"], {"period_start": "2026-09-01", "period_end": "2026-12-01",
                       "expected_portfolio_version": v0}, PM), expected_status=201)
        assert s1["status"] == "DRAFT"
        assert s1["nav_cents"] == 0, "empty portfolio values to zero"

        resp = api.create_valuation_snapshot(
            pf["id"], {"period_start": "2026-12-01", "period_end": "2027-03-01",
                       "expected_portfolio_version": v0}, PM)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        pf_after = validate_success(api.get_portfolio(pf["id"], PM))
        assert pf_after["version"] == v0 + 1, (
            "exactly one successful creation advanced the portfolio version by 1"
        )


class TestInvestorRBAC:
    def test_investor_unallocated_portfolio_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `Investor`, `X-User-ID` is the `id` of
        the acting `Investor`; reads of a portfolio or its snapshots are authorized
        only when the portfolio's `allocations` contain an entry whose
        `investor_id` equals `X-User-ID`. A violation is rejected with
        `ERR_INVESTOR_NOT_ALLOCATED` (HTTP 403)."
        PRD §3.6: "A portfolio list read by an `Investor` caller shows only
        portfolios where that investor holds an allocation"

        Design: Corner/rbac/investor_unallocated_portfolio_forbidden
        """
        from test_helpers import create_investor
        inv1 = create_investor(name="Inv One", investor_type="FUND")
        pf1 = validate_success(api.create_portfolio(
            create_portfolio_payload(name="P1"), PM), expected_status=201)
        pf2 = validate_success(api.create_portfolio(
            create_portfolio_payload(name="P2",
                                     allocations=[{"investor_id": inv1["id"], "units": 5}]),
            PM), expected_status=201)
        ih = make_investor_headers(inv1["id"])

        resp = api.get_portfolio(pf1["id"], ih)
        validate_error(resp, ApiErrorId.ERR_INVESTOR_NOT_ALLOCATED)

        got = validate_success(api.get_portfolio(pf2["id"], ih))
        assert got["name"] == "P2"

        rows, meta = validate_paginated(api.list_portfolios(ih))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == pf2["id"]

    def test_investor_cannot_read_case_detail(self, api):
        """PRD §2.1: "If the role is recognized but does not appear in the
        endpoint's authorized role list, the request is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: "| GET | /api/cases/{id} | Get a case | PlatformAdmin, Broker,
        Underwriter, CaseManager, ComplianceOfficer, FinanceOfficer,
        PortfolioManager |"

        Design: Corner/rbac/investor_cannot_read_case_detail
        """
        from test_helpers import create_investor, setup_broker_insured_policy, create_case_for
        inv1 = create_investor(name="Inv One", investor_type="FUND")
        broker, insured, policy = setup_broker_insured_policy(with_license=False,
                                                              insured_overrides={"smoker_status": "UNKNOWN"})
        case = create_case_for(broker, policy)
        resp = api.get_case(case["id"], make_investor_headers(inv1["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
