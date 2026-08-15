"""Secondary bids: fork/converge lifecycle, pricing bands, OCC on settle."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_approved_vehicle,
    create_ic_approved_proposal,
    commitment_for_proposal,
    create_pending_distribution,
    create_secondary_bid_payload,
    get_program,
    make_cio_headers,
    make_staff_trio,
    program_version,
    setup_open_program_with_plan,
    setup_with_executed_commitment,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSecondaryBidFork:
    def test_secondary_bid_fork_direct_accept_vs_counter_then_accept(self):
        """PRD §3.7: "The `CIO` accepts a bid from either `PROPOSED` or
        `COUNTERED`, with identical preconditions in both cases: the program
        must be `OPEN` with posture `NORMAL` (else `ERR_POSTURE_GATED`); on
        the `PURCHASE` side, `pricing_deviation_pct` must not exceed
        `secondary_premium_cap_pct` (else `ERR_PREMIUM_CAP_EXCEEDED`, HTTP
        422)"
        PRD §3.7: "the settle appends a `SECONDARY_SETTLEMENT_OUT` ledger
        entry for the negative `price`, creates a new `Commitment` on the
        traded vehicle already in `EXECUTED` status with `sized_amount` equal
        to the sum of `price` and `unfunded_assumed`, `unfunded_amount` equal
        to `unfunded_assumed`, and `proposal_id` null"

        Design: Difficulty/non_linear_state_machine/secondary_bid_fork_direct_accept_vs_counter_then_accept
        """
        ctx = setup_open_program_with_plan(
            cash=30_000_000, staff_prefix="sixp", program_name="P6",
            strategy_cap_pct=0.95, manager_cap_pct=0.95,
        )
        ana_h, ic_h, ops_h = ctx.analyst_headers, ctx.ic_headers, ctx.ops_headers
        _, vehicle = create_approved_vehicle(
            ana_h, ic_h, fund_name="Zeta II", strategy="CREDIT", vintage_year=2025,
            fund_size_target=300_000_000, mgmt_fee_rate_early=0.015,
            investment_period_years=4, carry_rate=0.15,
        )
        bid1 = validate_success(
            api_client.create_secondary_bid(
                ctx.program["id"],
                create_secondary_bid_payload(vehicle["id"], price=10_400_000),
                ana_h,
            ),
            expected_status=201,
        )
        bid2 = validate_success(
            api_client.create_secondary_bid(
                ctx.program["id"],
                create_secondary_bid_payload(vehicle["id"], price=10_400_000),
                ana_h,
            ),
            expected_status=201,
        )

        # Branch A: PROPOSED -> ACCEPTED directly.
        accepted1 = validate_success(
            api_client.accept_secondary_bid(ctx.program["id"], bid1["id"], make_cio_headers())
        )
        assert accepted1["status"] == "ACCEPTED"

        # Branch B: PROPOSED -> COUNTERED -> ACCEPTED.
        countered = validate_success(
            api_client.counter_secondary_bid(ctx.program["id"], bid2["id"], ic_h)
        )
        assert countered["status"] == "COUNTERED"
        accepted2 = validate_success(
            api_client.accept_secondary_bid(ctx.program["id"], bid2["id"], make_cio_headers())
        )
        assert accepted2["status"] == "ACCEPTED"

        pv = program_version(ctx.program["id"], ops_h)
        settled1 = validate_success(
            api_client.settle_secondary_bid(
                ctx.program["id"], bid1["id"], {"expected_program_version": pv}, ops_h
            )
        )
        assert settled1["status"] == "SETTLED"
        pv2 = program_version(ctx.program["id"], ops_h)
        settled2 = validate_success(
            api_client.settle_secondary_bid(
                ctx.program["id"], bid2["id"], {"expected_program_version": pv2}, ops_h
            )
        )
        assert settled2["status"] == "SETTLED"

        # Both branches converge: each settle spawned an EXECUTED commitment
        # of sized 10,400,000 with unfunded 0 and proposal_id null.
        commitments, meta = validate_paginated(
            api_client.list_program_commitments(ctx.program["id"], ops_h)
        )
        assert meta["total_count"] == 2
        for c in commitments:
            assert c["status"] == "EXECUTED"
            assert c["sized_amount"] == pytest.approx(10_400_000.00, abs=0.005)
            assert c["unfunded_amount"] == pytest.approx(0.00, abs=0.005)
            assert c["proposal_id"] is None

        program = get_program(ctx.program["id"], ops_h)
        assert program["unrestricted_cash"] == pytest.approx(9_200_000.00, abs=0.005)
        assert program["committed_total"] == pytest.approx(20_800_000.00, abs=0.005)

    def test_secondary_settle_purchase_ledger_and_aggregates(self):
        """PRD §3.7: "the settle appends a `SECONDARY_SETTLEMENT_OUT` ledger
        entry for the negative `price`, creates a new `Commitment` on the
        traded vehicle already in `EXECUTED` status with `sized_amount` equal
        to the sum of `price` and `unfunded_assumed`, `unfunded_amount` equal
        to `unfunded_assumed`, and `proposal_id` null, and recomputes
        `secondary_purchase_unfunded_total`, `committed_total`,
        `unfunded_total`, and `unrestricted_cash`."

        Second test on the fork instance: with unfunded_assumed > 0 the new
        commitment carries the assumed unfunded amount and the program's
        unfunded_total includes it.

        Design: Difficulty/non_linear_state_machine/secondary_bid_fork_direct_accept_vs_counter_then_accept
        """
        ctx = setup_open_program_with_plan(
            cash=30_000_000, staff_prefix="sixb", program_name="P6B",
            strategy_cap_pct=0.95, manager_cap_pct=0.95,
        )
        ana_h, ic_h, ops_h = ctx.analyst_headers, ctx.ic_headers, ctx.ops_headers
        _, vehicle = create_approved_vehicle(
            ana_h, ic_h, fund_name="Zeta III", strategy="CREDIT", vintage_year=2025,
        )
        bid = validate_success(
            api_client.create_secondary_bid(
                ctx.program["id"],
                create_secondary_bid_payload(
                    vehicle["id"], price=10_000_000, unfunded_assumed=2_000_000
                ),
                ana_h,
            ),
            expected_status=201,
        )
        validate_success(api_client.accept_secondary_bid(ctx.program["id"], bid["id"], make_cio_headers()))
        pv = program_version(ctx.program["id"], ops_h)
        settled = validate_success(
            api_client.settle_secondary_bid(
                ctx.program["id"], bid["id"], {"expected_program_version": pv}, ops_h
            )
        )
        assert settled["status"] == "SETTLED"
        commitments, _ = validate_paginated(
            api_client.list_program_commitments(ctx.program["id"], ops_h)
        )
        assert len(commitments) == 1
        new_c = commitments[0]
        assert new_c["status"] == "EXECUTED"
        assert new_c["sized_amount"] == pytest.approx(12_000_000.00, abs=0.005)
        assert new_c["unfunded_amount"] == pytest.approx(2_000_000.00, abs=0.005)
        assert new_c["proposal_id"] is None
        program = get_program(ctx.program["id"], ops_h)
        assert program["unrestricted_cash"] == pytest.approx(20_000_000.00, abs=0.005)
        assert program["committed_total"] == pytest.approx(12_000_000.00, abs=0.005)
        assert program["unfunded_total"] == pytest.approx(2_000_000.00, abs=0.005)
        entries, _ = validate_paginated(api_client.list_ledger_entries(ctx.program["id"], ops_h))
        assert entries[-1]["entry_kind"] == "SECONDARY_SETTLEMENT_OUT"
        assert float(entries[-1]["amount"]) == pytest.approx(-10_000_000.00, abs=0.005)


class TestSecondaryPricingBands:
    def test_secondary_premium_and_discount_caps(self):
        """PRD §3.7: "on the `PURCHASE` side, `pricing_deviation_pct` must not
        exceed `secondary_premium_cap_pct` (else `ERR_PREMIUM_CAP_EXCEEDED`,
        HTTP 422); on the `SALE` side, the negated deviation — the discount
        below NAV basis — must not exceed `secondary_discount_cap_pct` (else
        `ERR_DISCOUNT_CAP_EXCEEDED`, HTTP 422); and on the `SALE` side, the
        linked commitment must be in `EXECUTED` status and belong to this
        program and this vehicle."

        Design: Corner/validations/secondary_premium_and_discount_caps
        """
        ctx = setup_with_executed_commitment(
            cash=50_000_000, proposed_amount=15_000_000, staff_prefix="v6",
            program_name="PV6", total_nav_budget=200_000_000,
            strategy_cap_pct=0.95, manager_cap_pct=0.95,
            plan_overrides={"target_strategy_mix": [{"strategy": "CREDIT", "weight": 1.0}]},
            vehicle_overrides={"fund_name": "Sec I", "strategy": "CREDIT", "vintage_year": 2025},
        )
        ana_h = ctx.analyst_headers

        bid_hi = validate_success(
            api_client.create_secondary_bid(
                ctx.program["id"],
                create_secondary_bid_payload(ctx.vehicle["id"], price=10_600_000),
                ana_h,
            ),
            expected_status=201,
        )
        bid_ok = validate_success(
            api_client.create_secondary_bid(
                ctx.program["id"],
                create_secondary_bid_payload(ctx.vehicle["id"], price=10_500_000),
                ana_h,
            ),
            expected_status=201,
        )
        bid_lo = validate_success(
            api_client.create_secondary_bid(
                ctx.program["id"],
                create_secondary_bid_payload(
                    ctx.vehicle["id"], side="SALE", price=8_900_000,
                    unfunded_assumed=0, linked_commitment_id=ctx.commitment["id"],
                ),
                ana_h,
            ),
            expected_status=201,
        )
        bid_ok2 = validate_success(
            api_client.create_secondary_bid(
                ctx.program["id"],
                create_secondary_bid_payload(
                    ctx.vehicle["id"], side="SALE", price=9_000_000,
                    unfunded_assumed=0, linked_commitment_id=ctx.commitment["id"],
                ),
                ana_h,
            ),
            expected_status=201,
        )

        # +6% premium over cap 5%
        resp_hi = api_client.accept_secondary_bid(ctx.program["id"], bid_hi["id"], make_cio_headers())
        validate_error(resp_hi, ApiErrorId.ERR_PREMIUM_CAP_EXCEEDED)
        # exactly +5% is inclusive-accepted
        ok1 = validate_success(api_client.accept_secondary_bid(ctx.program["id"], bid_ok["id"], make_cio_headers()))
        assert ok1["status"] == "ACCEPTED"
        # -11% discount over cap 10%
        resp_lo = api_client.accept_secondary_bid(ctx.program["id"], bid_lo["id"], make_cio_headers())
        validate_error(resp_lo, ApiErrorId.ERR_DISCOUNT_CAP_EXCEEDED)
        # exactly -10% is inclusive-accepted
        ok2 = validate_success(api_client.accept_secondary_bid(ctx.program["id"], bid_ok2["id"], make_cio_headers()))
        assert ok2["status"] == "ACCEPTED"


class TestSecondarySettleOcc:
    def test_occ_stale_version_on_secondary_settle(self):
        """PRD §2.5: "Each such request must carry a non-optional
        `expected_program_version` field carrying the client's last observed
        `version` of the parent `FoFProgram`. If the supplied value does not
        match the program's current `version`, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read the
        program before retrying. The three guarded writes are: superseding the
        approved pacing plan, executing a commitment, and settling a
        secondary bid."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_secondary_settle
        """
        ctx = setup_with_executed_commitment(
            cash=30_000_000, proposed_amount=5_000_000, staff_prefix="x3",
            program_name="PX3", total_nav_budget=200_000_000,
            strategy_cap_pct=0.95, manager_cap_pct=0.95,
            plan_overrides={"target_strategy_mix": [{"strategy": "CREDIT", "weight": 1.0}]},
            vehicle_overrides={"fund_name": "OccSec I", "strategy": "CREDIT", "vintage_year": 2025},
        )
        ana_h, ops_h = ctx.analyst_headers, ctx.ops_headers
        dist = create_pending_distribution(
            ctx, amount=1_000_000, distribution_type="INCOME", received_at="2026-08-10T00:00:00Z"
        )
        bid = validate_success(
            api_client.create_secondary_bid(
                ctx.program["id"],
                create_secondary_bid_payload(ctx.vehicle["id"], price=10_000_000),
                ana_h,
            ),
            expected_status=201,
        )
        validate_success(api_client.accept_secondary_bid(ctx.program["id"], bid["id"], make_cio_headers()))
        pv_stale = program_version(ctx.program["id"], ops_h)
        # Distribution receive bumps the program version.
        validate_success(api_client.receive_distribution(dist["id"], ops_h))

        resp = api_client.settle_secondary_bid(
            ctx.program["id"], bid["id"], {"expected_program_version": pv_stale}, ops_h
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        pv_fresh = program_version(ctx.program["id"], ops_h)
        settled = validate_success(
            api_client.settle_secondary_bid(
                ctx.program["id"], bid["id"], {"expected_program_version": pv_fresh}, ops_h
            )
        )
        assert settled["status"] == "SETTLED"
        program = get_program(ctx.program["id"], ops_h)
        # 30,000,000 + 1,000,000 (distribution) - 10,000,000 (settle out)
        assert program["unrestricted_cash"] == pytest.approx(21_000_000.00, abs=0.005)
