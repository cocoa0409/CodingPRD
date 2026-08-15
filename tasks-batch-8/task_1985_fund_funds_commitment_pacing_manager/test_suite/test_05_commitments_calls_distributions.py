"""Commitment execution bands, capital-call payment cascades, the unfunded
invariant, distributions, vintage-band containment, and snapshot quarters."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    commitment_for_proposal,
    contribute,
    create_approved_vehicle,
    create_ic_approved_proposal,
    create_open_program,
    create_pending_distribution,
    issue_and_pay_call,
    issue_call,
    make_staff_trio,
    program_version,
    record_snapshot,
    setup_open_program_with_plan,
    setup_with_executed_commitment,
    advance_clock,
    get_program,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSizingBand:
    def test_sizing_band_lower_and_upper_bounds(self):
        """PRD §3.4: "the final size must lie within the band of ninety
        percent to one hundred ten percent of the original `proposed_amount`
        inclusive (else `ERR_SIZE_OUT_OF_BAND`, HTTP 422)"

        Design: Corner/validations/sizing_band_lower_and_upper_bounds
        """
        ctx = setup_open_program_with_plan(
            cash=30_000_000, staff_prefix="v2", program_name="PV2",
            strategy_cap_pct=0.95, manager_cap_pct=0.95,
            plan_overrides={"target_strategy_mix": [{"strategy": "CREDIT", "weight": 1.0}]},
        )
        ana_h, ic_h, ops_h = ctx.analyst_headers, ctx.ic_headers, ctx.ops_headers
        _, veh1 = create_approved_vehicle(ana_h, ic_h, strategy="CREDIT")
        _, veh2 = create_approved_vehicle(ana_h, ic_h, strategy="CREDIT")
        prop1 = create_ic_approved_proposal(veh1["id"], ctx.program["id"], ctx.plan["id"], ana_h, ic_h, 10_000_000)
        com1 = commitment_for_proposal(prop1["id"], ops_h)
        prop2 = create_ic_approved_proposal(veh2["id"], ctx.program["id"], ctx.plan["id"], ana_h, ic_h, 10_000_000)
        com2 = commitment_for_proposal(prop2["id"], ops_h)

        pv1 = program_version(ctx.program["id"], ops_h)
        # 11,001,000 > 1.10 * 10,000,000 -> reject
        resp_hi = api_client.execute_commitment(
            ctx.program["id"], com1["id"],
            {"sized_amount": 11_001_000, "expected_program_version": pv1}, ops_h,
        )
        validate_error(resp_hi, ApiErrorId.ERR_SIZE_OUT_OF_BAND)
        # exactly 11,000,000 is inclusive-accepted
        ok1 = validate_success(
            api_client.execute_commitment(
                ctx.program["id"], com1["id"],
                {"sized_amount": 11_000_000, "expected_program_version": pv1}, ops_h,
            )
        )
        assert ok1["status"] == "EXECUTED"

        pv2 = program_version(ctx.program["id"], ops_h)
        # 8,999,999.99 < 0.90 * 10,000,000 -> reject
        resp_lo = api_client.execute_commitment(
            ctx.program["id"], com2["id"],
            {"sized_amount": 8_999_999.99, "expected_program_version": pv2}, ops_h,
        )
        validate_error(resp_lo, ApiErrorId.ERR_SIZE_OUT_OF_BAND)
        # exactly 9,000,000 is inclusive-accepted
        ok2 = validate_success(
            api_client.execute_commitment(
                ctx.program["id"], com2["id"],
                {"sized_amount": 9_000_000, "expected_program_version": pv2}, ops_h,
            )
        )
        assert ok2["status"] == "EXECUTED"


class TestCapitalCallPayment:
    def test_capital_call_pay_cascade_depth2(self):
        """PRD §3.5: "On success, a `CashLedgerEntry` of kind
        `CAPITAL_CALL_PAYMENT` with a negative amount is appended, the
        commitment's `unfunded_amount` is reduced by the payment and its
        `version` increments, and the program's `deployed_total`,
        `unrestricted_cash`, `version`, and posture are all recomputed."

        Design: Difficulty/transitive_cascade/capital_call_pay_cascade_depth2
        """
        ctx = setup_with_executed_commitment(
            cash=20_000_000, proposed_amount=10_000_000, staff_prefix="eight",
            program_name="P8",
        )
        call = issue_call(ctx, amount=4_000_000, due_date="2026-08-20T00:00:00Z")
        pre = get_program(ctx.program["id"], ctx.ops_headers)

        paid = validate_success(api_client.pay_call(call["id"], ctx.ops_headers))
        assert paid["status"] == "PAID"

        commitment = validate_success(api_client.get_commitment_flat(ctx.commitment["id"], ctx.ops_headers))
        assert commitment["unfunded_amount"] == pytest.approx(6_000_000.00, abs=0.005)

        program = get_program(ctx.program["id"], ctx.ops_headers)
        assert program["deployed_total"] == pytest.approx(4_000_000.00, abs=0.005)
        assert program["unrestricted_cash"] == pytest.approx(16_000_000.00, abs=0.005)
        assert program["unfunded_total"] == pytest.approx(6_000_000.00, abs=0.005)
        assert program["version"] == pre["version"] + 1
        assert program["posture"] == "NORMAL"  # 16,000,000 >= 1.10 * 1,000,000

        resp = api_client.list_ledger_entries(ctx.program["id"], ctx.ops_headers)
        entries, _ = validate_paginated(resp)
        last = entries[-1]
        assert last["entry_kind"] == "CAPITAL_CALL_PAYMENT"
        assert last["amount"] == pytest.approx(-4_000_000.00, abs=0.005)
        assert last["balance_after"] == pytest.approx(16_000_000.00, abs=0.005)

    def test_capital_call_pay_bumps_commitment_version(self):
        """PRD §3.5: "the commitment's `unfunded_amount` is reduced by the
        payment and its `version` increments"

        Second test on the same instance: the commitment row's own version
        advances on pay.

        Design: Difficulty/transitive_cascade/capital_call_pay_cascade_depth2
        """
        ctx = setup_with_executed_commitment(
            cash=20_000_000, proposed_amount=10_000_000, staff_prefix="eightb",
            program_name="P8B",
        )
        call = issue_call(ctx, amount=1_000_000, due_date="2026-08-20T00:00:00Z")
        before = validate_success(api_client.get_commitment_flat(ctx.commitment["id"], ctx.ops_headers))
        validate_success(api_client.pay_call(call["id"], ctx.ops_headers))
        after = validate_success(api_client.get_commitment_flat(ctx.commitment["id"], ctx.ops_headers))
        assert after["version"] == before["version"] + 1
        assert after["unfunded_amount"] == pytest.approx(9_000_000.00, abs=0.005)

    def test_capital_call_pay_requires_commitment_executed(self):
        """PRD §3.5: "Paying a call (allowed from `ISSUED` or from `OVERDUE`)
        validates three things: the commitment must be `EXECUTED` (else
        `ERR_COMMITMENT_NOT_EXECUTED`, HTTP 422); the call amount must not
        exceed the commitment's current `unfunded_amount` (else
        `ERR_OVERFUNDED`, HTTP 422) — this rejection happens before any ledger
        append, so the unfunded invariant is never violated; and paying must
        leave the program's `unrestricted_cash` at or above
        `liquidity_buffer_min` (else `ERR_BUFFER_BREACH`)."

        Design: Difficulty/cross_entity_state_dependency/capital_call_pay_requires_commitment_executed
        """
        ctx = setup_open_program_with_plan(cash=20_000_000, staff_prefix="14", program_name="P14")
        ana_h, ic_h, ops_h = ctx.analyst_headers, ctx.ic_headers, ctx.ops_headers
        _, vehicle = create_approved_vehicle(ana_h, ic_h)
        proposal = create_ic_approved_proposal(
            vehicle["id"], ctx.program["id"], ctx.plan["id"], ana_h, ic_h, 10_000_000
        )
        commitment = commitment_for_proposal(proposal["id"], ops_h)
        assert commitment["status"] == "PENDING_DOCS"
        # Calls may be issued ahead of execution; paying must refuse.
        call = validate_success(
            api_client.create_capital_call(
                ctx.program["id"], commitment["id"],
                {"amount": 2_000_000, "purpose": "INVESTMENT", "due_date": "2026-08-20T00:00:00Z"},
                ops_h,
            ),
            expected_status=201,
        )
        resp1 = api_client.pay_call(call["id"], ops_h)
        validate_error(resp1, ApiErrorId.ERR_COMMITMENT_NOT_EXECUTED)

        pv = program_version(ctx.program["id"], ops_h)
        validate_success(
            api_client.execute_commitment(
                ctx.program["id"], commitment["id"],
                {"sized_amount": 10_000_000, "expected_program_version": pv}, ops_h,
            )
        )
        paid = validate_success(api_client.pay_call(call["id"], ops_h))
        assert paid["status"] == "PAID"
        after = validate_success(api_client.get_commitment_flat(commitment["id"], ops_h))
        assert after["unfunded_amount"] == pytest.approx(8_000_000.00, abs=0.005)

    def test_pay_on_pending_docs_call_leaves_all_totals_untouched(self):
        """PRD §3.5: "Paying a call (allowed from `ISSUED` or from `OVERDUE`)
        validates three things: the commitment must be `EXECUTED` (else
        `ERR_COMMITMENT_NOT_EXECUTED`, HTTP 422)"

        Second test on the same instance: the rejection is side-effect free —
        no ledger entry, no aggregate drift.

        Design: Difficulty/cross_entity_state_dependency/capital_call_pay_requires_commitment_executed
        """
        ctx = setup_open_program_with_plan(cash=20_000_000, staff_prefix="14b", program_name="P14B")
        ana_h, ic_h, ops_h = ctx.analyst_headers, ctx.ic_headers, ctx.ops_headers
        _, vehicle = create_approved_vehicle(ana_h, ic_h)
        proposal = create_ic_approved_proposal(
            vehicle["id"], ctx.program["id"], ctx.plan["id"], ana_h, ic_h, 5_000_000
        )
        commitment = commitment_for_proposal(proposal["id"], ops_h)
        call = validate_success(
            api_client.create_capital_call(
                ctx.program["id"], commitment["id"],
                {"amount": 1_000_000, "purpose": "INVESTMENT", "due_date": "2026-08-20T00:00:00Z"},
                ops_h,
            ),
            expected_status=201,
        )
        resp = api_client.pay_call(call["id"], ops_h)
        validate_error(resp, ApiErrorId.ERR_COMMITMENT_NOT_EXECUTED)
        entries, meta = validate_paginated(
            api_client.list_ledger_entries(ctx.program["id"], ops_h)
        )
        # Only the seed CONTRIBUTION exists.
        assert meta["total_count"] == 1
        assert entries[0]["entry_kind"] == "CONTRIBUTION"
        program = get_program(ctx.program["id"], ops_h)
        assert program["unrestricted_cash"] == pytest.approx(20_000_000.00, abs=0.005)
        assert program["deployed_total"] == pytest.approx(0.0, abs=0.005)

    def test_overfunded_call_rejected_before_ledger_append(self):
        """PRD §3.5: "the call amount must not exceed the commitment's current
        `unfunded_amount` (else `ERR_OVERFUNDED`, HTTP 422) — this rejection
        happens before any ledger append, so the unfunded invariant is never
        violated"
        PRD §3.5: "any payment that would drive a commitment's
        `unfunded_amount` negative is rejected before any ledger append."

        Design: Corner/validations/overfunded_call_rejected_before_ledger_append
        """
        ctx = setup_with_executed_commitment(
            cash=20_000_000, proposed_amount=5_000_000, staff_prefix="v3",
            program_name="PV3", strategy_cap_pct=0.95, manager_cap_pct=0.95,
            plan_overrides={"target_strategy_mix": [{"strategy": "BUYOUT", "weight": 1.0}]},
        )
        issue_and_pay_call(ctx, amount=3_000_000, due_date="2026-08-20T00:00:00Z")
        call2 = issue_call(ctx, amount=2_000_001, due_date="2026-08-25T00:00:00Z")
        resp = api_client.pay_call(call2["id"], ctx.ops_headers)
        validate_error(resp, ApiErrorId.ERR_OVERFUNDED)

        entries, meta = validate_paginated(
            api_client.list_ledger_entries(ctx.program["id"], ctx.ops_headers)
        )
        assert meta["total_count"] == 2, "CONTRIBUTION + one CAPITAL_CALL_PAYMENT only"
        call2_after = validate_success(api_client.get_call(call2["id"], ctx.ops_headers))
        assert call2_after["status"] == "ISSUED"
        program = get_program(ctx.program["id"], ctx.ops_headers)
        assert program["unrestricted_cash"] == pytest.approx(17_000_000.00, abs=0.005)

    def test_error_buffer_breach_on_call_pay(self):
        """PRD §3.5: "paying must leave the program's `unrestricted_cash` at
        or above `liquidity_buffer_min` (else `ERR_BUFFER_BREACH`)."
        PRD §3.1: "`liquidity_buffer_min` (the minimum `unrestricted_cash` the
        program must retain after any cash outflow, at least zero)"

        Design: Corner/errors/error_buffer_breach_on_call_pay
        """
        ctx = setup_with_executed_commitment(
            cash=5_000_000, proposed_amount=5_000_000, staff_prefix="f5",
            program_name="PF5", strategy_cap_pct=0.95, manager_cap_pct=0.95,
            plan_overrides={"target_strategy_mix": [{"strategy": "BUYOUT", "weight": 1.0}]},
        )
        call_hi = issue_call(ctx, amount=4_000_001, due_date="2026-08-20T00:00:00Z")
        call_eq = issue_call(ctx, amount=4_000_000, due_date="2026-08-21T00:00:00Z")

        resp = api_client.pay_call(call_hi["id"], ctx.ops_headers)
        validate_error(resp, ApiErrorId.ERR_BUFFER_BREACH)  # 5,000,000 - 4,000,001 < 1,000,000

        paid = validate_success(api_client.pay_call(call_eq["id"], ctx.ops_headers))
        assert paid["status"] == "PAID"
        program = get_program(ctx.program["id"], ctx.ops_headers)
        assert program["unrestricted_cash"] == pytest.approx(1_000_000.00, abs=0.005), (
            "landing exactly on the buffer is allowed (>= boundary)"
        )
        assert program["posture"] == "RESTRICTED", (
            "1,000,000 is strictly below 1.10 * 1,000,000 -> low-cash band"
        )


class TestCommitmentReduce:
    def test_reduce_below_paid_rejected(self):
        """PRD §3.4: "the `OperationsAnalyst` supplies a `reduce_to` amount
        that must be at least the sum of `PAID` capital calls on the
        commitment (else `ERR_REDUCE_BELOW_PAID`, HTTP 422); the commitment
        transitions from `EXECUTED` to `REDUCED`, its `sized_amount` is set to
        `reduce_to`, `unfunded_amount` is recomputed, and the program
        aggregates and `version` follow."

        Design: Corner/validations/reduce_below_paid_rejected
        """
        ctx = setup_with_executed_commitment(
            cash=20_000_000, proposed_amount=10_000_000, staff_prefix="v4",
            program_name="PV4", strategy_cap_pct=0.95, manager_cap_pct=0.95,
            plan_overrides={"target_strategy_mix": [{"strategy": "BUYOUT", "weight": 1.0}]},
        )
        issue_and_pay_call(ctx, amount=4_000_000, due_date="2026-08-20T00:00:00Z")
        resp = api_client.reduce_commitment(
            ctx.program["id"], ctx.commitment["id"], {"reduce_to": 3_999_999.99}, ctx.ops_headers
        )
        validate_error(resp, ApiErrorId.ERR_REDUCE_BELOW_PAID)
        after = validate_success(api_client.get_commitment_flat(ctx.commitment["id"], ctx.ops_headers))
        assert after["status"] == "EXECUTED"
        assert after["sized_amount"] == pytest.approx(10_000_000.00, abs=0.005)

    def test_unfunded_conservation_across_reduce(self):
        """PRD §3.5: "The unfunded bookkeeping runs after every capital-call
        payment, every commitment reduction, and every secondary settlement:
        each commitment's `unfunded_amount` is its `sized_amount` minus the
        sum of `PAID` call amounts, the program's `unfunded_total` aggregates
        `unfunded_amount` over `EXECUTED` commitments plus
        `secondary_purchase_unfunded_total`, and any payment that would drive
        a commitment's `unfunded_amount` negative is rejected before any
        ledger append."
        PRD §2.6: "`committed_total` is the sum of `sized_amount` over
        `Commitment` rows in status `EXECUTED`; `deployed_total` is the sum
        of `amount` over `CapitalCall` rows in status `PAID`"

        Design: Difficulty/compensating_invariant/unfunded_conservation_across_reduce
        """
        ctx = setup_with_executed_commitment(
            cash=20_000_000, proposed_amount=10_000_000, staff_prefix="18",
            program_name="P18",
        )
        issue_and_pay_call(ctx, amount=4_000_000, due_date="2026-08-20T00:00:00Z")
        reduced = validate_success(
            api_client.reduce_commitment(
                ctx.program["id"], ctx.commitment["id"], {"reduce_to": 4_000_000}, ctx.ops_headers
            )
        )
        assert reduced["status"] == "REDUCED"
        assert reduced["sized_amount"] == pytest.approx(4_000_000.00, abs=0.005)
        assert reduced["unfunded_amount"] == pytest.approx(0.00, abs=0.005)
        program = get_program(ctx.program["id"], ctx.ops_headers)
        assert program["deployed_total"] == pytest.approx(4_000_000.00, abs=0.005)
        assert program["unfunded_total"] == pytest.approx(0.00, abs=0.005)

    def test_reduce_to_exactly_paid_total_accepted(self):
        """PRD §3.4: "the `OperationsAnalyst` supplies a `reduce_to` amount
        that must be at least the sum of `PAID` capital calls on the
        commitment (else `ERR_REDUCE_BELOW_PAID`, HTTP 422)"

        Second test on the reduce invariant: the reduce delta shrinks the
        program's committed total by exactly the delta.

        Design: Difficulty/compensating_invariant/unfunded_conservation_across_reduce
        """
        ctx = setup_with_executed_commitment(
            cash=20_000_000, proposed_amount=10_000_000, staff_prefix="18b",
            program_name="P18B",
        )
        issue_and_pay_call(ctx, amount=4_000_000, due_date="2026-08-20T00:00:00Z")
        before = get_program(ctx.program["id"], ctx.ops_headers)
        assert before["committed_total"] == pytest.approx(10_000_000.00, abs=0.005)
        validate_success(
            api_client.reduce_commitment(
                ctx.program["id"], ctx.commitment["id"], {"reduce_to": 4_000_000}, ctx.ops_headers
            )
        )
        after = get_program(ctx.program["id"], ctx.ops_headers)
        # committed_total after reduce tracks the reduced size (delta 6,000,000).
        assert after["committed_total"] == pytest.approx(4_000_000.00, abs=0.005)
        assert after["unfunded_total"] == pytest.approx(0.00, abs=0.005)


class TestCashConservation:
    def test_cash_conservation_across_pay_and_receive(self):
        """PRD §2.6: "`unrestricted_cash` is the sum of all signed entry
        amounts and is recomputed on every append."
        PRD §2.6: "Each entry records a signed `amount` (positive is cash in,
        negative is cash out), an `entry_kind` (one of `CONTRIBUTION`,
        `CAPITAL_CALL_PAYMENT`, `DISTRIBUTION_RECEIPT`,
        `SECONDARY_SETTLEMENT_OUT`, `SECONDARY_SETTLEMENT_IN`,
        `MANUAL_ADJUSTMENT`), a `ref_entity` and `ref_id` identifying the
        source row (`ref_id` is null for `CONTRIBUTION` and
        `MANUAL_ADJUSTMENT`), an optional free-text `note` for manual entries,
        and a computed `balance_after` capturing the running
        `unrestricted_cash` immediately after the entry."

        Design: Difficulty/compensating_invariant/cash_conservation_across_pay_and_receive
        """
        ctx = setup_with_executed_commitment(
            cash=20_000_000, proposed_amount=10_000_000, staff_prefix="17",
            program_name="P17",
        )
        call = issue_call(ctx, amount=4_000_000, due_date="2026-08-20T00:00:00Z")
        dist = create_pending_distribution(
            ctx, amount=4_000_000, distribution_type="RETURN_OF_CAPITAL",
            received_at="2026-08-25T00:00:00Z",
        )
        validate_success(api_client.pay_call(call["id"], ctx.ops_headers))
        validate_success(api_client.receive_distribution(dist["id"], ctx.ops_headers))

        program = get_program(ctx.program["id"], ctx.ops_headers)
        assert program["unrestricted_cash"] == pytest.approx(20_000_000.00, abs=0.005)

        entries, meta = validate_paginated(
            api_client.list_ledger_entries(ctx.program["id"], ctx.ops_headers)
        )
        assert meta["total_count"] == 3
        kinds = [e["entry_kind"] for e in entries]
        assert kinds == ["CONTRIBUTION", "CAPITAL_CALL_PAYMENT", "DISTRIBUTION_RECEIPT"]
        amounts = [float(e["amount"]) for e in entries]
        assert amounts[0] == pytest.approx(20_000_000.00, abs=0.005)
        assert amounts[1] == pytest.approx(-4_000_000.00, abs=0.005)
        assert amounts[2] == pytest.approx(4_000_000.00, abs=0.005)
        balances = [float(e["balance_after"]) for e in entries]
        assert balances[0] == pytest.approx(20_000_000.00, abs=0.005)
        assert balances[1] == pytest.approx(16_000_000.00, abs=0.005)
        assert balances[2] == pytest.approx(20_000_000.00, abs=0.005)
        assert sum(amounts) == pytest.approx(float(program["unrestricted_cash"]), abs=0.005)

    def test_cash_conservation_manual_adjustment_reconciles(self):
        """PRD §3.1: "Each append recomputes `unrestricted_cash`, records
        `balance_after`, recomputes posture, and bumps the program's
        `version`."
        PRD §2.6: "`unrestricted_cash` is the sum of all signed entry amounts
        and is recomputed on every append."

        Second test on the conservation invariant: a negative
        MANUAL_ADJUSTMENT reduces cash and balance_after tracks the running
        total exactly.

        Design: Difficulty/compensating_invariant/cash_conservation_across_pay_and_receive
        """
        _, _, ops_h, _ = make_staff_trio("17b")
        program = create_open_program(
            program_name="P17B", cash=5_000_000, ops_headers=ops_h, total_nav_budget=50_000_000
        )
        contribute(program["id"], -1_500_000, ops_h, note="correction", entry_kind="MANUAL_ADJUSTMENT")
        entries, meta = validate_paginated(api_client.list_ledger_entries(program["id"], ops_h))
        assert meta["total_count"] == 2
        assert float(entries[-1]["balance_after"]) == pytest.approx(3_500_000.00, abs=0.005)
        program_after = get_program(program["id"], ops_h)
        assert program_after["unrestricted_cash"] == pytest.approx(3_500_000.00, abs=0.005)
        assert sum(float(e["amount"]) for e in entries) == pytest.approx(
            float(program_after["unrestricted_cash"]), abs=0.005
        )


class TestVintageBand:
    def test_vintage_band_span_containment(self):
        """PRD §3.4: "the vehicle's `vintage_year`, measured against the
        earliest and the latest `vintage_year` among existing `EXECUTED`
        commitments, must keep both spans within `max_vintage_band_years`
        (else `ERR_VINTAGE_BAND_BREACH`, HTTP 422)"

        Design: Difficulty/resource_temporal_overlap/vintage_band_span_containment
        """
        ctx = setup_with_executed_commitment(
            cash=50_000_000, proposed_amount=5_000_000, staff_prefix="15",
            program_name="P15", total_nav_budget=200_000_000,
            strategy_cap_pct=0.95, manager_cap_pct=0.95, max_vintage_band_years=4,
            plan_overrides={
                "plan_label": "FY26-31", "horizon_years": 6,
                "target_strategy_mix": [{"strategy": "BUYOUT", "weight": 1.0}],
            },
            vehicle_overrides={"fund_name": "Xi 2026", "vintage_year": 2026},
        )
        ana_h, ic_h, ops_h = ctx.analyst_headers, ctx.ic_headers, ctx.ops_headers
        # Second vehicle with vintage 2031: span 2026..2031 = 5 > band 4.
        veh31 = create_approved_vehicle(ana_h, ic_h, fund_name="Xi 2031", vintage_year=2031)[1]
        prop31 = create_ic_approved_proposal(
            veh31["id"], ctx.program["id"], ctx.plan["id"], ana_h, ic_h, 5_000_000
        )
        com31 = commitment_for_proposal(prop31["id"], ops_h)

        pv = program_version(ctx.program["id"], ops_h)
        resp = api_client.execute_commitment(
            ctx.program["id"], com31["id"],
            {"sized_amount": 5_000_000, "expected_program_version": pv}, ops_h,
        )
        validate_error(resp, ApiErrorId.ERR_VINTAGE_BAND_BREACH)
        after = validate_success(api_client.get_commitment_flat(com31["id"], ops_h))
        assert after["status"] == "PENDING_DOCS"
        program = get_program(ctx.program["id"], ops_h)
        assert program["committed_total"] == pytest.approx(5_000_000.00, abs=0.005)

    def test_vintage_band_at_exact_limit_accepted(self):
        """PRD §3.4: "the vehicle's `vintage_year`, measured against the
        earliest and the latest `vintage_year` among existing `EXECUTED`
        commitments, must keep both spans within `max_vintage_band_years`
        (else `ERR_VINTAGE_BAND_BREACH`, HTTP 422)"

        Second test on the same instance: a 2030 vintage keeps the span at
        exactly 4 (2026..2030) and is accepted.

        Design: Difficulty/resource_temporal_overlap/vintage_band_span_containment
        """
        ctx = setup_with_executed_commitment(
            cash=50_000_000, proposed_amount=5_000_000, staff_prefix="15b",
            program_name="P15B", total_nav_budget=200_000_000,
            strategy_cap_pct=0.95, manager_cap_pct=0.95, max_vintage_band_years=4,
            plan_overrides={
                "plan_label": "FY26-31", "horizon_years": 6,
                "target_strategy_mix": [{"strategy": "BUYOUT", "weight": 1.0}],
            },
            vehicle_overrides={"fund_name": "Xi 2026 B", "vintage_year": 2026},
        )
        ana_h, ic_h, ops_h = ctx.analyst_headers, ctx.ic_headers, ctx.ops_headers
        veh30 = create_approved_vehicle(ana_h, ic_h, fund_name="Xi 2030 B", vintage_year=2030)[1]
        prop30 = create_ic_approved_proposal(
            veh30["id"], ctx.program["id"], ctx.plan["id"], ana_h, ic_h, 5_000_000
        )
        com30 = commitment_for_proposal(prop30["id"], ops_h)
        pv = program_version(ctx.program["id"], ops_h)
        ok = validate_success(
            api_client.execute_commitment(
                ctx.program["id"], com30["id"],
                {"sized_amount": 5_000_000, "expected_program_version": pv}, ops_h,
            )
        )
        assert ok["status"] == "EXECUTED"


class TestCallCancelAndOverdue:
    def test_call_cancel_after_due_date_rejected(self):
        """PRD §3.5: "A call may be cancelled only while the server's clock is
        at or before its `due_date` (else `ERR_CALL_OVERDUE`); cancellation
        moves it from `ISSUED` to `CANCELLED` with no ledger impact."

        Design: Corner/state_machines/call_cancel_after_due_date_rejected
        """
        ctx = setup_with_executed_commitment(
            cash=20_000_000, proposed_amount=5_000_000, staff_prefix="c5",
            program_name="PCC",
        )
        call = issue_call(ctx, amount=1_000_000, purpose="FEES", due_date="2026-08-10T00:00:00Z")
        advance_clock(ctx, "2026-08-11T00:00:00Z")
        resp = api_client.cancel_call(call["id"], ctx.ops_headers)
        validate_error(resp, ApiErrorId.ERR_CALL_OVERDUE)
        after = validate_success(api_client.get_call(call["id"], ctx.ops_headers))
        # Grace 10 days: due 08-10 + 10 days -> OVERDUE only from 08-21; at
        # 08-11 the call is still ISSUED (cancel window simply closed).
        assert after["status"] == "ISSUED"

    def test_overdue_sweep_flips_call_and_restricts_posture(self):
        """PRD §3.5: "A clock sweep — driven by advancing the logical clock —
        moves any `ISSUED` call whose `due_date` plus the program's
        `overdue_grace_days` has passed into `OVERDUE` and recomputes the
        program's posture; an overdue call forces posture to `RESTRICTED`."
        PRD §3.5: "Paying an overdue call is the standard recovery path that
        restores posture."

        Design: Corner/state_machines/overdue_sweep_flips_call_and_restricts_posture
        """
        ctx = setup_with_executed_commitment(
            cash=20_000_000, proposed_amount=5_000_000, staff_prefix="c6",
            program_name="POD",
        )
        call = issue_call(ctx, amount=1_000_000, due_date="2026-08-10T00:00:00Z")
        advance_clock(ctx, "2026-08-21T00:00:00Z")
        call_after = validate_success(api_client.get_call(call["id"], ctx.ops_headers))
        assert call_after["status"] == "OVERDUE"
        program_od = get_program(ctx.program["id"], ctx.ops_headers)
        assert program_od["posture"] == "RESTRICTED"

        paid = validate_success(api_client.pay_call(call["id"], ctx.ops_headers))
        assert paid["status"] == "PAID"
        program_ok = get_program(ctx.program["id"], ctx.ops_headers)
        assert program_ok["posture"] == "NORMAL"  # 19,000,000 >= 1.10 * 1,000,000


class TestDistributions:
    def test_derived_fields_reconciled_on_distribution_cancel(self):
        """PRD §3.5: "Receiving a distribution requires the commitment to be
        in `EXECUTED` or `REDUCED` (else `ERR_COMMITMENT_NOT_EXECUTED`),
        appends a `DISTRIBUTION_RECEIPT` ledger entry for the positive amount,
        and recomputes `returned_total`, `unrestricted_cash`, the program's
        `version`, and posture. A `PENDING` distribution may be cancelled."
        PRD §2.6: "`returned_total` is the sum of `amount` over `Distribution`
        rows in status `RECEIVED`"

        Design: Corner/cross_cutting_layers/derived_fields_reconciled_on_distribution_cancel
        """
        ctx = setup_with_executed_commitment(
            cash=20_000_000, proposed_amount=5_000_000, staff_prefix="x5",
            program_name="PX5", strategy_cap_pct=0.95, manager_cap_pct=0.95,
            plan_overrides={"target_strategy_mix": [{"strategy": "BUYOUT", "weight": 1.0}]},
        )
        dist = create_pending_distribution(
            ctx, amount=2_000_000, distribution_type="GAIN", received_at="2026-08-15T00:00:00Z"
        )
        cancelled = validate_success(api_client.cancel_distribution(dist["id"], ctx.ops_headers))
        assert cancelled["status"] == "CANCELLED"
        program = get_program(ctx.program["id"], ctx.ops_headers)
        assert program["returned_total"] == pytest.approx(0.00, abs=0.005)
        assert program["unrestricted_cash"] == pytest.approx(20_000_000.00, abs=0.005)


class TestImmediateConsistency:
    def test_immediate_consistency_mutation_visible_in_same_response(self):
        """PRD §1: "Every write that touches program cash or program-level
        aggregates is reconciled immediately — there is no batch settlement
        window"
        PRD §3.5: "On success, a `CashLedgerEntry` of kind
        `CAPITAL_CALL_PAYMENT` with a negative amount is appended, the
        commitment's `unfunded_amount` is reduced by the payment and its
        `version` increments, and the program's `deployed_total`,
        `unrestricted_cash`, `version`, and posture are all recomputed."

        Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_same_response
        """
        ctx = setup_with_executed_commitment(
            cash=20_000_000, proposed_amount=5_000_000, staff_prefix="y1",
            program_name="PY1", strategy_cap_pct=0.95, manager_cap_pct=0.95,
            plan_overrides={"target_strategy_mix": [{"strategy": "BUYOUT", "weight": 1.0}]},
        )
        call = issue_call(ctx, amount=2_000_000, due_date="2026-08-20T00:00:00Z")
        paid = validate_success(api_client.pay_call(call["id"], ctx.ops_headers))
        assert paid["status"] == "PAID", "pay response body carries the new state"
        program = get_program(ctx.program["id"], ctx.ops_headers)
        assert program["deployed_total"] == pytest.approx(2_000_000.00, abs=0.005)
        assert program["unrestricted_cash"] == pytest.approx(18_000_000.00, abs=0.005)


class TestSnapshotQuarterOccupancy:
    def test_snapshot_quarter_period_collision(self):
        """PRD §3.8: "The label is unique per commitment — a duplicate quarter
        for the same commitment is rejected with `ERR_DUPLICATE_QUARTER`
        (HTTP 409). Each snapshot lands in `PROVISIONAL` with `reported_at`
        stamped from the server clock, and its `is_final` flag is false."

        Design: Difficulty/resource_temporal_overlap/snapshot_quarter_period_collision
        """
        ctx = setup_with_executed_commitment(
            cash=20_000_000, proposed_amount=10_000_000, staff_prefix="16",
            program_name="P16",
        )
        snap1 = record_snapshot(ctx, as_of_quarter="2026-Q3", reported_nav=10_500_000)
        assert snap1["status"] == "PROVISIONAL"

        resp = api_client.create_snapshot(
            ctx.commitment["id"],
            {"as_of_quarter": "2026-Q3", "reported_nav": 10_600_000},
            ctx.ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_QUARTER)

        ok = validate_success(
            api_client.create_snapshot(
                ctx.commitment["id"],
                {"as_of_quarter": "2026-Q4", "reported_nav": 10_600_000},
                ctx.ops_headers,
            ),
            expected_status=201,
        )
        assert ok["as_of_quarter"] == "2026-Q4"
        assert ok["status"] == "PROVISIONAL"

    def test_snapshot_quarter_collision_scoped_per_commitment(self):
        """PRD §3.8: "The label is unique per commitment — a duplicate quarter
        for the same commitment is rejected with `ERR_DUPLICATE_QUARTER`
        (HTTP 409)."

        Second test on the same instance: the same quarter on a DIFFERENT
        commitment is a distinct slot and is accepted.

        Design: Difficulty/resource_temporal_overlap/snapshot_quarter_period_collision
        """
        ctx = setup_with_executed_commitment(
            cash=40_000_000, proposed_amount=5_000_000, staff_prefix="16b",
            program_name="P16B", strategy_cap_pct=0.95, manager_cap_pct=0.95,
            plan_overrides={"target_strategy_mix": [{"strategy": "BUYOUT", "weight": 1.0}]},
        )
        ana_h, ic_h, ops_h = ctx.analyst_headers, ctx.ic_headers, ctx.ops_headers
        # Second EXECUTED commitment on a second vehicle.
        _, veh2 = create_approved_vehicle(ana_h, ic_h, fund_name="Omicron II")
        prop2 = create_ic_approved_proposal(
            veh2["id"], ctx.program["id"], ctx.plan["id"], ana_h, ic_h, 5_000_000
        )
        com2 = commitment_for_proposal(prop2["id"], ops_h)
        pv = program_version(ctx.program["id"], ops_h)
        validate_success(
            api_client.execute_commitment(
                ctx.program["id"], com2["id"],
                {"sized_amount": 5_000_000, "expected_program_version": pv}, ops_h,
            )
        )
        record_snapshot(ctx, as_of_quarter="2026-Q3", reported_nav=5_100_000)
        ok = validate_success(
            api_client.create_snapshot(
                com2["id"], {"as_of_quarter": "2026-Q3", "reported_nav": 5_200_000}, ops_h
            ),
            expected_status=201,
        )
        assert ok["commitment_id"] == com2["id"]
        assert ok["status"] == "PROVISIONAL"
