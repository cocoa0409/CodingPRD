"""Payment agency lifecycle: parallel funding/distribution dimensions,
execution gates, window occupation, notice buffer, settlement, reversal
(PRD §3.4, §2.8)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    ApiErrorId,
    CLOCK_START, set_clock,
    create_active_indenture_with_tranche, setup_indenture_with_positions,
    register_account, register_position,
    create_interest_run, create_redemption_run, fund_run, execute_run,
    reverse_run, get_payment_run, get_position, get_tranche, get_indenture,
    get_account, list_run_records, run_records_by_position,
    declare_default, confirm_default, cure_default,
    assert_payment_run,
    make_trust_officer_headers, make_trust_manager_headers,
)

OFFICER = make_trust_officer_headers("officer-1")


class TestParallelFundingDistributionDimensions:
    def _setup_single_position_run(self, api):
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000,), holder_prefixes=("H-A",),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 400000000},
            reset_clock=False)
        run = create_interest_run(ctx["tranche"]["id"])
        return ctx, run

    def test_partial_funding_blocks_execute_shortfall(self, api):
        """PRD §3.4: "Each deposit adds to `funded_amount_cents`; the first
        deposit that leaves a shortfall moves `funding_status` to
        `PARTIALLY_FUNDED`, and once the cumulative funded amount reaches or
        exceeds `gross_amount_cents` — exact equality is sufficient — the run
        is `FUNDED`."
        PRD §3.4: "the run must be `FUNDED` (a shortfall is rejected with
        `ERR_FUNDING_SHORTFALL`, equality executes)"

        Design: Difficulty/non_linear_state_machine/payment_run_parallel_funding_and_distribution_dimensions
        """
        ctx, run = self._setup_single_position_run(api)
        run = fund_run(run["id"], 10000000, issuer_ref="issuer-1")
        assert run["funding_status"] == "PARTIALLY_FUNDED"
        assert run["distribution_status"] == "SCHEDULED", (
            "funding axis moved while distribution axis stayed put")

        resp = api.execute_payment_run(run["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_FUNDING_SHORTFALL)
        run_after = get_payment_run(run["id"])
        assert run_after["distribution_status"] == "SCHEDULED", (
            "failed execute leaves the distribution dimension untouched")

    def test_reverse_leaves_funding_dimension_funded(self, api):
        """PRD §3.4: "`funding_status` remains `FUNDED` because the funds
        stay on deposit."
        PRD §3.4: "the run's `distribution_status` becomes `REVERSED`, every
        record in `PENDING`, `HELD`, or `PAID` becomes `RETURNED`"

        Design: Difficulty/non_linear_state_machine/payment_run_parallel_funding_and_distribution_dimensions
        """
        ctx, run = self._setup_single_position_run(api)
        fund_run(run["id"], 10000000, issuer_ref="issuer-1")
        # Exact-equality crossing to FUNDED (10000000 + 166667 == 10166667).
        run = fund_run(run["id"], 166667, issuer_ref="issuer-1")
        assert run["funding_status"] == "FUNDED"
        assert run["funded_amount_cents"] == 10166667

        run = execute_run(run["id"])
        assert run["distribution_status"] == "DISTRIBUTED"

        run = reverse_run(run["id"], manager_id="manager-1")
        assert run["distribution_status"] == "REVERSED"
        assert run["funding_status"] == "FUNDED", (
            "parallel axes: reversal does not touch the funding dimension")

        records = list_run_records(run["id"])
        assert len(records) == 1
        assert records[0]["status"] == "RETURNED"
        position = get_position(ctx["positions"][0]["id"])
        assert position["principal_amount_cents"] == 400000000, (
            "interest runs never touch principal")


class TestExecuteGates:
    def _setup_suspended_underfunded_run(self, api):
        """Run both SUSPENDED (state) and underfunded (fiscal)."""
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000,), holder_prefixes=("H-A",),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 400000000},
            reset_clock=False)
        run = create_interest_run(ctx["tranche"]["id"])
        fund_run(run["id"], 10000000, issuer_ref="issuer-1")  # gross 10166667
        case = declare_default(ctx["indenture"]["id"], officer_id="officer-1")
        case = confirm_default(case["id"], manager_id="manager-1")
        return ctx, run, case

    def test_suspended_underfunded_execute_reports_state_error(self, api):
        """PRD §2.8: "Every request is validated against an ordered rule
        stack, and when several rules are violated at once the rejection
        carries the error of the **earliest** rule in the stack."
        PRD §2.8: "5. State admissibility: the target resource's state admits
        the operation — `ERR_INVALID_STATE`; writes against a terminal state
        are rejected as `ERR_ALREADY_TERMINAL`; payment execution while the
        indenture is not `ACTIVE` is rejected as `ERR_INDENTURE_NOT_ACTIVE`."
        PRD §2.8: "20. Funding sufficiency — `ERR_FUNDING_SHORTFALL`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_suspended_run_execute
        """
        ctx, run, case = self._setup_suspended_underfunded_run(api)
        run_now = get_payment_run(run["id"])
        assert run_now["distribution_status"] == "SUSPENDED"
        assert run_now["funded_amount_cents"] < run_now["gross_amount_cents"], (
            "fiscal violation also present")

        resp = api.execute_payment_run(run["id"], OFFICER)
        # PRD §2.8 rule 5 names ERR_INVALID_STATE and ERR_INDENTURE_NOT_ACTIVE
        # as members of the same state-admissibility priority level without an
        # intra-level order; the run is simultaneously SUSPENDED and under a
        # DEFAULTED indenture, so either member is a faithful rejection. The
        # pinned assertion is that a priority-5 state error beats the
        # priority-20 fiscal error.
        actual = validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE,
                   ApiErrorId.ERR_INDENTURE_NOT_ACTIVE])
        assert actual != "ERR_FUNDING_SHORTFALL", (
            "state rule (priority 5) precedes funding sufficiency (priority 20)")

    def test_suspended_run_state_untouched_by_failed_execute(self, api):
        """PRD §2.8: "when several rules are violated at once the rejection
        carries the error of the **earliest** rule in the stack."
        PRD §3.5: "the indenture moves `ACTIVE` → `DEFAULTED`, every payment
        run of every tranche with `distribution_status` `SCHEDULED` becomes
        `SUSPENDED`"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_suspended_run_execute
        """
        ctx, run, case = self._setup_suspended_underfunded_run(api)
        api.execute_payment_run(run["id"], OFFICER)

        run_after = get_payment_run(run["id"])
        assert run_after["distribution_status"] == "SUSPENDED"
        assert run_after["funded_amount_cents"] == 10000000
        indenture = get_indenture(ctx["indenture"]["id"])
        assert indenture["status"] == "DEFAULTED"
        assert indenture["active_default_count"] == 1

    def _setup_defaulted_with_late_funded_run(self, api):
        """Indenture DEFAULTED first; run created and fully funded AFTER, so
        the run itself is cleanly SCHEDULED — isolating the cross-entity gate."""
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000,), holder_prefixes=("H-A",),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 400000000},
            reset_clock=False)
        case = declare_default(ctx["indenture"]["id"], officer_id="officer-1")
        confirm_default(case["id"], manager_id="manager-1")
        run = create_interest_run(ctx["tranche"]["id"])
        run = fund_run(run["id"], 10166667, issuer_ref="issuer-1")
        return ctx, run

    def test_execute_rejected_when_indenture_defaulted(self, api):
        """PRD §3.4: "the indenture must be `ACTIVE` (otherwise
        `ERR_INDENTURE_NOT_ACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/payment_execute_gated_by_indenture_status
        """
        ctx, run = self._setup_defaulted_with_late_funded_run(api)
        assert run["funding_status"] == "FUNDED"
        assert run["distribution_status"] == "SCHEDULED"

        resp = api.execute_payment_run(run["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INDENTURE_NOT_ACTIVE)

    def test_funded_run_untouched_by_indenture_gate_rejection(self, api):
        """PRD §3.4: "Execution, a `TrustOfficer` action, is gated by three
        checks: the run must be `FUNDED` (a shortfall is rejected with
        `ERR_FUNDING_SHORTFALL`, equality executes), the indenture must be
        `ACTIVE` (otherwise `ERR_INDENTURE_NOT_ACTIVE`), and the tranche must
        be `ACTIVE` (otherwise `ERR_INVALID_STATE`)"

        Design: Difficulty/cross_entity_state_dependency/payment_execute_gated_by_indenture_status
        """
        ctx, run = self._setup_defaulted_with_late_funded_run(api)
        api.execute_payment_run(run["id"], OFFICER)

        run_after = get_payment_run(run["id"])
        assert run_after["distribution_status"] == "SCHEDULED", "state untouched"
        assert run_after["funding_status"] == "FUNDED"
        indenture = get_indenture(ctx["indenture"]["id"])
        assert indenture["status"] == "DEFAULTED"


class TestTrancheTerminalGate:
    def _setup_fully_redeemed_tranche(self, api):
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000,), holder_prefixes=("H-A",),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 400000000,
                               "notice_period_days": 30},
            reset_clock=False)
        run = create_redemption_run(ctx["tranche"]["id"], 400000000,
                                    payment_type="FULL_REDEMPTION",
                                    scheduled_payment_date="2026-06-15")
        fund_run(run["id"], 400000000, issuer_ref="issuer-1")
        execute_run(run["id"])
        return ctx, run

    def test_payment_run_create_rejected_on_redeemed_tranche(self, api):
        """PRD §3.4: "A `TrustOfficer` schedules a run on an `ACTIVE` tranche
        — any other tranche state is rejected with `ERR_INVALID_STATE`"

        Design: Difficulty/cross_entity_state_dependency/payment_run_create_gated_by_tranche_status
        """
        ctx, run = self._setup_fully_redeemed_tranche(api)
        tranche = get_tranche(ctx["tranche"]["id"])
        assert tranche["status"] == "REDEEMED"
        assert tranche["outstanding_principal_cents"] == 0

        resp = api.create_payment_run(
            {"tranche_id": ctx["tranche"]["id"], "payment_type": "INTEREST",
             "period_start_date": "2026-06-15", "period_end_date": "2026-12-15",
             "scheduled_payment_date": "2026-12-15"},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_full_redemption_drives_tranche_and_indenture_terminal(self, api):
        """PRD §3.4: "A `FULL_REDEMPTION` or `FINAL_MATURITY` execution that
        leaves the tranche's outstanding principal at zero moves the tranche
        to `REDEEMED` or `MATURED` respectively, with all of its positions
        `REDEEMED`; and when every tranche of the indenture has reached a
        terminal state (`REDEEMED` or `MATURED`), the indenture itself becomes
        `SATISFIED`, its terminal state."

        Design: Difficulty/cross_entity_state_dependency/payment_run_create_gated_by_tranche_status
        """
        ctx, run = self._setup_fully_redeemed_tranche(api)

        tranche = get_tranche(ctx["tranche"]["id"])
        assert tranche["status"] == "REDEEMED"
        position = get_position(ctx["positions"][0]["id"])
        assert position["status"] == "REDEEMED"
        assert position["principal_amount_cents"] == 0
        indenture = get_indenture(ctx["indenture"]["id"])
        assert indenture["status"] == "SATISFIED", "bubble-up: all tranches terminal"


class TestInterestWindowOccupation:
    def _setup_existing_interest_run(self, api):
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000,), holder_prefixes=("H-A",),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 400000000},
            reset_clock=False)
        run1 = create_interest_run(ctx["tranche"]["id"])
        return ctx, run1

    def test_overlapping_interest_window_rejected(self, api):
        """PRD §3.4: "the windows of a tranche's `INTEREST` runs must not
        overlap any other non-`REVERSED` run's window, though windows that
        merely touch at a boundary date are permitted, and a violating
        schedule is rejected with `ERR_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/interest_period_half_open_overlap_with_adjacency_allowed
        """
        ctx, run1 = self._setup_existing_interest_run(api)
        # [2026-09-01, 2027-03-01) intersects [2026-06-15, 2026-12-15).
        resp = api.create_payment_run(
            {"tranche_id": ctx["tranche"]["id"], "payment_type": "INTEREST",
             "period_start_date": "2026-09-01", "period_end_date": "2027-03-01",
             "scheduled_payment_date": "2027-03-01"},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_PERIOD_OVERLAP)

    def test_adjacent_interest_window_accepted(self, api):
        """PRD §3.4: "`period_start_date` and `period_end_date` are required
        and define a half-open accrual window that includes the start date and
        excludes the end date; the windows of a tranche's `INTEREST` runs must
        not overlap any other non-`REVERSED` run's window, though windows that
        merely touch at a boundary date are permitted"

        Design: Difficulty/resource_temporal_overlap/interest_period_half_open_overlap_with_adjacency_allowed
        """
        ctx, run1 = self._setup_existing_interest_run(api)
        # [2026-12-15, 2027-06-15) shares only the excluded boundary date.
        resp = api.create_payment_run(
            {"tranche_id": ctx["tranche"]["id"], "payment_type": "INTEREST",
             "period_start_date": "2026-12-15", "period_end_date": "2027-06-15",
             "scheduled_payment_date": "2027-06-15"},
            OFFICER)
        run2 = validate_success(resp, 201)
        assert run2["distribution_status"] == "SCHEDULED"
        assert run2["period_start_date"] == "2026-12-15"


class TestRedemptionNoticeBuffer:
    def _setup_tranche_with_notice_30(self, api):
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000,), holder_prefixes=("H-A",),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 400000000,
                               "notice_period_days": 30},
            reset_clock=False)
        return ctx

    def test_redemption_notice_below_buffer_rejected(self, api):
        """PRD §3.4: "Redemption notice is enforced at scheduling: the
        scheduled payment date must fall at least the tranche's
        `notice_period_days` after the creation date, and a shorter notice is
        rejected with `ERR_NOTICE_PERIOD_SHORT` (HTTP 422)."

        Created at logical date 2026-05-01; 2026-05-30 is 29 days out.

        Design: Difficulty/resource_temporal_overlap/redemption_notice_buffer_boundary
        """
        ctx = self._setup_tranche_with_notice_30(api)
        resp = api.create_payment_run(
            {"tranche_id": ctx["tranche"]["id"],
             "payment_type": "SINKING_FUND_REDEMPTION",
             "scheduled_payment_date": "2026-05-30", "target_amount_cents": 1000000},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_NOTICE_PERIOD_SHORT)

    def test_redemption_notice_exact_buffer_accepted(self, api):
        """PRD §3.4: "the scheduled payment date must fall at least the
        tranche's `notice_period_days` after the creation date, and a shorter
        notice is rejected with `ERR_NOTICE_PERIOD_SHORT` (HTTP 422)."

        Created at logical date 2026-05-01; 2026-05-31 is exactly 30 days out
        — "at least" admits equality.

        Design: Difficulty/resource_temporal_overlap/redemption_notice_buffer_boundary
        """
        ctx = self._setup_tranche_with_notice_30(api)
        resp = api.create_payment_run(
            {"tranche_id": ctx["tranche"]["id"],
             "payment_type": "SINKING_FUND_REDEMPTION",
             "scheduled_payment_date": "2026-05-31", "target_amount_cents": 1000000},
            OFFICER)
        run = validate_success(resp, 201)
        assert_payment_run(run)
        assert run["distribution_status"] == "SCHEDULED"


class TestResumeCascadeAndSettlement:
    def test_cure_resumes_suspended_run(self, api):
        """PRD §3.5: "when the count reaches zero the indenture resumes
        `DEFAULTED` → `ACTIVE` through the resume cascade — suspended runs
        return to `SCHEDULED`, held records return to `PENDING` with
        `total_unpaid_cents` decremented accordingly"

        Design: Corner/state_machines/cure_resumes_suspended_run_and_execute_succeeds
        """
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000,), holder_prefixes=("H-A",),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 400000000},
            reset_clock=False)
        run = create_interest_run(ctx["tranche"]["id"])
        fund_run(run["id"], 10166667, issuer_ref="issuer-1")
        case = declare_default(ctx["indenture"]["id"], officer_id="officer-1")
        confirm_default(case["id"], manager_id="manager-1")

        run_mid = get_payment_run(run["id"])
        assert run_mid["distribution_status"] == "SUSPENDED", "cascade suspended the run"

        cure_default(case["id"], manager_id="manager-1")
        indenture = get_indenture(ctx["indenture"]["id"])
        assert indenture["status"] == "ACTIVE", "last active default cleared"
        run_resumed = get_payment_run(run["id"])
        assert run_resumed["distribution_status"] == "SCHEDULED", "resume cascade"

        run_done = execute_run(run["id"])
        assert run_done["distribution_status"] == "DISTRIBUTED"
        records = list_run_records(run["id"])
        assert len(records) == 1
        assert records[0]["allocated_cents"] == 10166667
        assert records[0]["status"] == "PENDING"

    def _setup_executed_then_settled(self, api):
        """Executed INTEREST run (records PENDING), then clock advanced to the
        scheduled payment date so the settlement sweep pays out."""
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000, 350000000, 250000000),
            holder_prefixes=("H-A", "H-B", "H-C"),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 1000000000},
            reset_clock=False)
        run = create_interest_run(ctx["tranche"]["id"])
        fund_run(run["id"], 25416667, issuer_ref="issuer-1")
        execute_run(run["id"])
        set_clock("2026-12-15T00:00:00Z")  # at the scheduled payment date
        return ctx, run

    def test_settled_cash_totals_after_sweep(self, api):
        """PRD §3.4: "A clock sweep at or after a run's
        `scheduled_payment_date` moves that run's `PENDING` records to `PAID`,
        stamps `paid_at` from the logical clock, and adds each
        `allocated_cents` to the holder's `total_received_cents`"

        Design: Difficulty/compensating_invariant/interest_execute_settle_reverse_cash_conservation
        """
        ctx, run = self._setup_executed_then_settled(api)
        expected = [10166667, 8895833, 6354167]
        total = 0
        for account, want in zip(ctx["accounts"], expected):
            account_after = get_account(account["id"])
            assert account_after["total_received_cents"] == want, (
                f"settled total: expected {want}, "
                f"got {account_after['total_received_cents']}")
            total += account_after["total_received_cents"]
        assert total == 25416667

    def test_reverse_after_settlement_restores_cash_ledgers(self, api):
        """PRD §3.4: "A `TrustManager` may reverse an entire `DISTRIBUTED`
        run, provided none of its records is already `RETURNED` (otherwise
        `ERR_INVALID_STATE`): the run's `distribution_status` becomes
        `REVERSED`, every record in `PENDING`, `HELD`, or `PAID` becomes
        `RETURNED`, redemption principal reductions are undone with
        `principal_amount_cents` restored and the restored value appended to
        `principal_history`, positions the run had redeemed return to
        `ACTIVE`, the tranche's `outstanding_principal_cents` is restored and
        a tranche this run had moved to `REDEEMED` or `MATURED` returns to
        `ACTIVE`, holder `total_received_cents` is decremented by returned
        allocations and `total_unpaid_cents` decremented for records
        returning from `HELD`, and `funding_status` remains `FUNDED` because
        the funds stay on deposit."

        Design: Difficulty/compensating_invariant/interest_execute_settle_reverse_cash_conservation
        """
        ctx, run = self._setup_executed_then_settled(api)
        run = reverse_run(run["id"], manager_id="manager-1")
        assert run["distribution_status"] == "REVERSED"
        assert run["funding_status"] == "FUNDED"

        for account in ctx["accounts"]:
            account_after = get_account(account["id"])
            assert account_after["total_received_cents"] == 0, (
                "cash ledger conserved: reverse returns totals to exactly 0")

        records = list_run_records(run["id"])
        for record in records:
            assert record["status"] == "RETURNED"

        tranche = get_tranche(ctx["tranche"]["id"])
        assert tranche["outstanding_principal_cents"] == 1000000000, (
            "interest runs never touch principal")

    def test_execute_response_immediately_consistent(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §2.10: "the reconciliation invariants of §3.2 and §3.4 hold at
        every observable instant."

        Design: Corner/consistency_model/immediate_consistency_visible_in_same_response
        """
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000,), holder_prefixes=("H-A",),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 400000000},
            reset_clock=False)
        run = create_interest_run(ctx["tranche"]["id"])
        fund_run(run["id"], 10166667, issuer_ref="issuer-1")

        resp = api.execute_payment_run(run["id"], OFFICER)
        data = validate_success(resp, 200)
        assert data["distribution_status"] == "DISTRIBUTED"
        assert data["funded_amount_cents"] == 10166667

        fetched = get_payment_run(run["id"])
        assert fetched["distribution_status"] == "DISTRIBUTED", "GET agrees immediately"
        assert fetched["funded_amount_cents"] == 10166667
        records = list_run_records(run["id"])
        assert len(records) == 1
        assert records[0]["status"] == "PENDING"
        assert records[0]["allocated_cents"] == 10166667
