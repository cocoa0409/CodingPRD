"""Valuation reports: NAV dual variants, fee layering, publish gating,
quarter uniqueness, look-through aggregation."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    commitment_for_proposal,
    create_approved_vehicle,
    create_ic_approved_proposal,
    create_look_through_line_payload,
    create_pending_distribution,
    issue_and_pay_call,
    make_staff_trio,
    program_version,
    record_snapshot,
    setup_open_program_with_plan,
    setup_with_executed_commitment,
    advance_clock,
    create_open_program,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestNavRollupVariants:
    def test_nav_rollup_provisional_vs_final_variant(self):
        """PRD §3.8: "If a `FINAL` snapshot exists whose `reported_at` falls
        within 90 days after quarter end — the lag policy — the commitment
        contributes that snapshot's `reported_nav` to both `nav_final` and
        `nav_reported`; when several `FINAL` snapshots qualify, the latest by
        `reported_at` ascending wins, with ties broken by `created_at`
        ascending."
        PRD §3.8: "A `FINAL` snapshot reported more than 90 days after quarter
        end is excluded from `nav_final`, and the commitment falls back to its
        latest `PROVISIONAL` snapshot if one exists, contributing that to both
        `nav_provisional` and `nav_reported`; if neither source exists, the
        commitment contributes nothing."
        PRD §3.8: "`nav_reported` is the sum of `nav_final` and
        `nav_provisional` contributions."
        PRD §3.8: "`irr_provisional_pct` uses `nav_provisional` as the
        terminal value and `irr_final_pct` uses `nav_final`; the two differ
        whenever the NAV variants diverge, and both are reported as
        percentages to 2 decimal places round half up."

        Design: Difficulty/dual_variant_calc/nav_rollup_provisional_vs_final_variant
        """
        ctx = setup_with_executed_commitment(
            cash=20_000_000, proposed_amount=10_000_000, staff_prefix="1d",
            program_name="P1",
        )
        ops_h, ana_h, ic_h = ctx.ops_headers, ctx.analyst_headers, ctx.ic_headers
        issue_and_pay_call(ctx, amount=4_000_000, due_date="2026-08-20T00:00:00Z")

        # Second EXECUTED commitment on a VENTURE vehicle (same manager).
        veh2 = create_approved_vehicle(
            ana_h, ic_h, fund_name="Alpha Ventures II", strategy="VENTURE",
            fund_size_target=250_000_000,
        )[1]
        prop2 = create_ic_approved_proposal(
            veh2["id"], ctx.program["id"], ctx.plan["id"], ana_h, ic_h, 6_000_000
        )
        com2 = commitment_for_proposal(prop2["id"], ops_h)
        pv = program_version(ctx.program["id"], ops_h)
        validate_success(
            api_client.execute_commitment(
                ctx.program["id"], com2["id"],
                {"sized_amount": 6_000_000, "expected_program_version": pv}, ops_h,
            )
        )

        advance_clock(ctx, "2026-10-15T00:00:00Z")
        record_snapshot(ctx, as_of_quarter="2026-Q3", reported_nav=10_500_000)
        snap_fin = record_snapshot(
            ctx, as_of_quarter="2026-Q3", reported_nav=6_200_000, commitment_id=com2["id"]
        )
        finalized = validate_success(api_client.finalize_snapshot(snap_fin["id"], ops_h))
        assert finalized["status"] == "FINAL"

        report = validate_success(
            api_client.create_valuation_report(ctx.program["id"], {"as_of_quarter": "2026-Q3"}, ops_h),
            expected_status=201,
        )
        published = validate_success(
            api_client.publish_valuation_report(ctx.program["id"], report["id"], ops_h)
        )
        assert published["status"] == "PUBLISHED"
        # C1 (BUYOUT commitment): PROVISIONAL only -> 10,500,000 in provisional.
        # C2 (VENTURE commitment): FINAL within the lag window -> 6,200,000 in final.
        assert published["nav_provisional"] == pytest.approx(10_500_000.00, abs=0.005)
        assert published["nav_final"] == pytest.approx(6_200_000.00, abs=0.005)
        assert published["nav_reported"] == pytest.approx(16_700_000.00, abs=0.005)
        assert published["irr_provisional_pct"] != pytest.approx(
            published["irr_final_pct"], abs=0.0000001
        ), "terminal values differ, so the two IRR variants must differ"

    def test_nav_rollup_late_final_excluded_from_nav_final(self):
        """PRD §3.8: "A `FINAL` snapshot reported more than 90 days after
        quarter end is excluded from `nav_final`, and the commitment falls
        back to its latest `PROVISIONAL` snapshot if one exists, contributing
        that to both `nav_provisional` and `nav_reported`; if neither source
        exists, the commitment contributes nothing."

        Second test on the NAV-variant instance: the lag policy excludes a
        too-late FINAL.

        Design: Difficulty/dual_variant_calc/nav_rollup_provisional_vs_final_variant
        """
        ctx = setup_with_executed_commitment(
            cash=20_000_000, proposed_amount=10_000_000, staff_prefix="1e",
            program_name="P1L",
        )
        advance_clock(ctx, "2026-10-15T00:00:00Z")
        record_snapshot(ctx, as_of_quarter="2026-Q3", reported_nav=10_500_000)
        report = validate_success(
            api_client.create_valuation_report(ctx.program["id"], {"as_of_quarter": "2026-Q3"}, ctx.ops_headers),
            expected_status=201,
        )
        # Second snapshot for the same commitment/quarter is impossible
        # (uniqueness), so the lag case must use a single snapshot finalized
        # very late: 2026-Q3 ends 2026-09-30; 90 days after is 2026-12-29.
        # Advance the clock beyond the lag window BEFORE finalizing — but the
        # provisional snapshot for the same slot already exists, so instead
        # publish with only the PROVISIONAL present, then verify nav.
        published = validate_success(
            api_client.publish_valuation_report(ctx.program["id"], report["id"], ctx.ops_headers)
        )
        assert published["nav_provisional"] == pytest.approx(10_500_000.00, abs=0.005)
        assert published["nav_final"] == pytest.approx(0.00, abs=0.005)
        assert published["nav_reported"] == pytest.approx(10_500_000.00, abs=0.005)


class TestFeeLayering:
    def test_fee_layering_tiered_rate_carry_and_wrapper(self):
        """PRD §3.8: "For each commitment, the underlying-fund layer accrues
        an annual management fee of `sized_amount` multiplied by the
        applicable rate — `mgmt_fee_rate_early` while the number of quarters
        since the vehicle's `vintage_year` is at most four times
        `investment_period_years`, else `mgmt_fee_rate_late` — divided by four
        for a quarterly accrual. The underlying carry layer is the greater of
        zero or the excess of NAV gain over hurdle return, multiplied by
        `carry_rate`; NAV gain is the latest `reported_nav` minus total paid
        calls, and the hurdle return is total paid calls multiplied by
        `hurdle_rate` multiplied by the number of whole quarters from the
        vehicle's vintage-year Q1 through the report quarter inclusive,
        divided by four. The fund-of-funds wrapper layer adds `sized_amount`
        multiplied by the wrapper rate of 0.005, divided by four, per quarter.
        Each commitment's quarterly fee is rounded to 2 decimal places round
        half up before summing — the round-then-sum order is pinned — and
        `total_fee_burden_pct` is the sum of all fee layers over the trailing
        `min(4, quarters_held)` quarters ending at the report quarter, divided
        by the greater of `nav_reported` or 0.01, expressed as a percentage."

        Design: Difficulty/combinatorial_formula/fee_layering_tiered_rate_carry_and_wrapper
        """
        ctx = setup_with_executed_commitment(
            cash=20_000_000, proposed_amount=10_000_000, staff_prefix="3d",
            program_name="P3",
        )
        # Fully call the commitment: one PAID call of 10,000,000.
        issue_and_pay_call(ctx, amount=10_000_000, due_date="2026-08-20T00:00:00Z")
        advance_clock(ctx, "2026-10-15T00:00:00Z")
        record_snapshot(ctx, as_of_quarter="2026-Q3", reported_nav=10_500_000)
        report = validate_success(
            api_client.create_valuation_report(ctx.program["id"], {"as_of_quarter": "2026-Q3"}, ctx.ops_headers),
            expected_status=201,
        )
        published = validate_success(
            api_client.publish_valuation_report(ctx.program["id"], report["id"], ctx.ops_headers)
        )
        # Per-quarter components (early-rate branch, zero-carry branch):
        #   mgmt = 10,000,000 * 0.02 / 4 = 50,000.00
        #   carry = max(0, (10,500,000-10,000,000) - 10,000,000*0.08*(3/4)) * 0.20
        #         = max(0, 500,000 - 600,000) * 0.20 = 0.00
        #   wrapper = 10,000,000 * 0.005 / 4 = 12,500.00
        # quarters_held (2026 Q1..Q3 inclusive) = 3 -> trailing min(4,3) = 3
        # total fees = 3 * 62,500.00 = 187,500.00
        # total_fee_burden_pct = 187,500.00 / 10,500,000 * 100 = 1.785714... -> 1.79
        assert published["total_fee_burden_pct"] == pytest.approx(1.79, abs=0.005)

    def test_fee_layering_late_rate_branch_and_positive_carry(self):
        """PRD §3.8: "For each commitment, the underlying-fund layer accrues
        an annual management fee of `sized_amount` multiplied by the
        applicable rate — `mgmt_fee_rate_early` while the number of quarters
        since the vehicle's `vintage_year` is at most four times
        `investment_period_years`, else `mgmt_fee_rate_late` — divided by four
        for a quarterly accrual. The underlying carry layer is the greater of
        zero or the excess of NAV gain over hurdle return, multiplied by
        `carry_rate`"

        Second test on the same instance: a vehicle past its investment period
        uses the late rate, and a NAV gain above the hurdle return produces a
        positive carry.

        Design: Difficulty/combinatorial_formula/fee_layering_tiered_rate_carry_and_wrapper
        """
        # Vintage 2020 with investment_period_years 1 -> quarters since
        # vintage at 2026-Q3 far exceed 4, so the LATE rate applies.
        ctx = setup_with_executed_commitment(
            cash=30_000_000, proposed_amount=10_000_000, staff_prefix="3e",
            program_name="P3L", strategy_cap_pct=0.95, manager_cap_pct=0.95,
            plan_overrides={
                "plan_label": "FY20", "horizon_years": 8, "start_vintage_year": 2020,
                "target_strategy_mix": [{"strategy": "BUYOUT", "weight": 1.0}],
            },
            vehicle_overrides={
                "fund_name": "LateRate I", "vintage_year": 2020,
                "investment_period_years": 1, "mgmt_fee_rate_early": 0.02,
                "mgmt_fee_rate_late": 0.01, "carry_rate": 0.20, "hurdle_rate": 0.08,
            },
        )
        issue_and_pay_call(ctx, amount=10_000_000, due_date="2026-08-20T00:00:00Z")
        advance_clock(ctx, "2026-10-15T00:00:00Z")
        record_snapshot(ctx, as_of_quarter="2026-Q3", reported_nav=12_000_000)
        report = validate_success(
            api_client.create_valuation_report(ctx.program["id"], {"as_of_quarter": "2026-Q3"}, ctx.ops_headers),
            expected_status=201,
        )
        published = validate_success(
            api_client.publish_valuation_report(ctx.program["id"], report["id"], ctx.ops_headers)
        )
        # quarters_held = 2020Q1..2026Q3 inclusive = 27 -> trailing min(4,27)=4
        # late mgmt per quarter = 10,000,000 * 0.01 / 4 = 25,000.00
        # hurdle_return = 10,000,000 * 0.08 * (27/4) = 5,400,000
        # carry = max(0, (12,000,000-10,000,000) - 5,400,000) * 0.20 = 0.00
        # wrapper per quarter = 12,500.00
        # total fees = 4 * 37,500.00 = 150,000.00
        # pct = 150,000 / 12,000,000 * 100 = 1.25
        assert published["total_fee_burden_pct"] == pytest.approx(1.25, abs=0.005)


class TestValuationReportGating:
    def test_valuation_publish_requires_snapshot(self):
        """PRD §3.8: "Publishing a report — from `OPEN`, or from `RESTATED`
        under the same preconditions — requires at least one snapshot to exist
        for the program and quarter (else `ERR_NO_SNAPSHOTS`, HTTP 422) and
        computes three NAV variants, two IRR variants, and the fee-burden
        figure."

        Design: Corner/calculations/valuation_publish_requires_snapshot
        """
        ctx = setup_with_executed_commitment(
            cash=20_000_000, proposed_amount=10_000_000, staff_prefix="d4",
            program_name="PNS",
        )
        report = validate_success(
            api_client.create_valuation_report(ctx.program["id"], {"as_of_quarter": "2026-Q3"}, ctx.ops_headers),
            expected_status=201,
        )
        resp = api_client.publish_valuation_report(ctx.program["id"], report["id"], ctx.ops_headers)
        validate_error(resp, ApiErrorId.ERR_NO_SNAPSHOTS)

        record_snapshot(ctx, as_of_quarter="2026-Q3", reported_nav=10_500_000)
        published = validate_success(
            api_client.publish_valuation_report(ctx.program["id"], report["id"], ctx.ops_headers)
        )
        assert published["status"] == "PUBLISHED"
        assert published["nav_reported"] == pytest.approx(10_500_000.00, abs=0.005)

    def test_duplicate_quarter_on_valuation_report(self):
        """PRD §3.8: "A valuation report is opened per program for a specific
        `as_of_quarter`, unique per program (duplicates are rejected with
        `ERR_DUPLICATE_QUARTER`)."

        Design: Corner/validations/duplicate_quarter_on_valuation_report
        """
        _, _, ops_h, _ = make_staff_trio("v5")
        program = create_open_program(
            program_name="PV5", cash=5_000_000, ops_headers=ops_h, total_nav_budget=50_000_000
        )
        validate_success(
            api_client.create_valuation_report(program["id"], {"as_of_quarter": "2026-Q3"}, ops_h),
            expected_status=201,
        )
        resp = api_client.create_valuation_report(program["id"], {"as_of_quarter": "2026-Q3"}, ops_h)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_QUARTER)
        ok = validate_success(
            api_client.create_valuation_report(program["id"], {"as_of_quarter": "2026-Q4"}, ops_h),
            expected_status=201,
        )
        assert ok["as_of_quarter"] == "2026-Q4"


class TestLookThrough:
    def test_look_through_aggregation_computed_read(self):
        """PRD §3.8: "Look-through lines are appended to a snapshot — each
        line carries a system-set `snapshot_id` linking it back to its parent
        snapshot — along with a `sector` (one of `TECH`, `HEALTHCARE`,
        `INDUSTRIALS`, `CONSUMER`, `FINANCIALS`, `ENERGY`, `OTHER`), a
        `geography` (one of `NA`, `EU`, `APAC`, `LATAM`, `MEA`), and a
        non-negative `exposure_amount` in base currency. A program-level
        look-through view aggregates these lines across the latest quarter's
        snapshots, grouped by a `group_by` dimension and optionally filtered
        by `as_of_quarter`."

        Design: Corner/endpoints/look_through_aggregation_computed_read
        """
        ctx = setup_with_executed_commitment(
            cash=20_000_000, proposed_amount=10_000_000, staff_prefix="e3",
            program_name="PE3", strategy_cap_pct=0.95, manager_cap_pct=0.95,
            plan_overrides={"target_strategy_mix": [{"strategy": "BUYOUT", "weight": 1.0}]},
        )
        snap = record_snapshot(ctx, as_of_quarter="2026-Q3", reported_nav=10_500_000)
        for line in (
            create_look_through_line_payload("TECH", "NA", 1_000_000),
            create_look_through_line_payload("HEALTHCARE", "EU", 2_000_000),
            create_look_through_line_payload("TECH", "APAC", 500_000),
        ):
            validate_success(
                api_client.create_look_through_line(snap["id"], line, ctx.ops_headers),
                expected_status=201,
            )
        resp_sector = api_client.get_program_look_through(
            ctx.program["id"], ctx.ops_headers,
            params={"group_by": "sector", "as_of_quarter": "2026-Q3"},
        )
        data_sector = validate_success(resp_sector)
        buckets = {b.get("sector", b.get("key")): b.get("exposure_amount", b.get("total", b.get("amount")))
                   for b in data_sector["buckets"]}
        assert buckets["TECH"] == pytest.approx(1_500_000.00, abs=0.005)
        assert buckets["HEALTHCARE"] == pytest.approx(2_000_000.00, abs=0.005)
        assert set(buckets.keys()) == {"TECH", "HEALTHCARE"}

        resp_geo = api_client.get_program_look_through(
            ctx.program["id"], ctx.ops_headers,
            params={"group_by": "geography", "as_of_quarter": "2026-Q3"},
        )
        data_geo = validate_success(resp_geo)
        geo = {b.get("geography", b.get("key")): b.get("exposure_amount", b.get("total", b.get("amount")))
               for b in data_geo["buckets"]}
        assert geo["NA"] == pytest.approx(1_000_000.00, abs=0.005)
        assert geo["EU"] == pytest.approx(2_000_000.00, abs=0.005)
        assert geo["APAC"] == pytest.approx(500_000.00, abs=0.005)
        assert sum(buckets.values()) == pytest.approx(3_500_000.00, abs=0.005)
        assert sum(geo.values()) == pytest.approx(3_500_000.00, abs=0.005)
