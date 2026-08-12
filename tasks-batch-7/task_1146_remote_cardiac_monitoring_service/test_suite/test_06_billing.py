"""Billing windows, provisional vs final amounts, submission gates, and
segregated adjustments (PRD §3.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_iso_prefix,
    assert_recognized_total_invariant,
    create_and_finalize_report,
    generate_billing,
    make_billing_specialist_headers,
    propose_adjustment_payload,
    read_billing_period,
    read_episode,
    record_gap_strikes,
    run_sweep,
    set_clock,
    setup_completed_episode,
    setup_monitoring_episode,
    setup_ready_billing_period,
    setup_submitted_billing_period,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["enrollment_coordinator_headers"]
BILLING_1 = TEST_USERS["billing_specialist_headers"]


def _setup_suspended_window_scenario(api):
    """EVENT 30-day episode; billing generated while MONITORING; three gap
    strikes (05-03/05-05/05-07, all resolved); SUSPENDED at 05-07; resumed at
    05-13 (6 suspension days); swept READY at 06-01."""
    ctx = setup_monitoring_episode(prescribed_days=30)
    ctx["billing_periods"] = generate_billing(ctx["episode_id"])
    ctx["bp_id"] = ctx["billing_periods"][0]["id"]
    record_gap_strikes(ctx["episode_id"], 3, resolve_last=True)
    set_clock("2026-05-13T00:00:00Z")
    validate_success(api.resume_episode(ctx["episode_id"], COORD))
    set_clock("2026-06-01T00:00:00Z")
    run_sweep()
    return ctx


class TestProvisionalVsFinalBilling:
    def test_provisional_and_final_amounts_diverge(self, api):
        """PRD §3.8: "Two variants use that machinery: at generation time the
        provisional variant prices each window at its full `window_days` with
        suspensions ignored and stores the result as
        `provisional_total_cents`; the final variant, applied when a period
        matures, prices at `billable_days` and stores `tc_amount_cents`,
        `pc_amount_cents`, and their sum `total_amount_cents`."
        PRD §3.8: "The technical component is 18,075 cents for `HOLTER`, 54,915
        cents for `EVENT`, and 90,000 cents for `IMPLANTABLE`; the professional
        component is 2,425, 5,205, and 12,000 cents respectively."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_billing_amounts
        """
        ctx = _setup_suspended_window_scenario(api)
        period = read_billing_period(ctx["bp_id"])
        assert period["status"] == "READY"
        # PROVISIONAL: 30 assumed days -> 54915 + 5205.
        assert period["provisional_total_cents"] == 60120
        # FINAL: 24 suspension-adjusted days -> 43932 + 4164.
        assert period["total_amount_cents"] == 48096
        assert period["total_amount_cents"] != period["provisional_total_cents"], (
            "identical windows must diverge between the two variants"
        )

    def test_final_variant_per_line_amounts_and_billable_days(self, api):
        """PRD §3.8: "At that moment `billable_days` is computed as
        `window_days` minus the whole-day overlap between the window and the
        union of the episode's suspension intervals — an interval still open at
        sweep time treated as ending at the sweep time — and the final per-line
        amounts are written."
        PRD §3.8: "Pricing computes each line as its fee multiplied by the
        number of days, divided by thirty, and rounded half up to whole cents;
        the period total is the sum of the two already-rounded lines —
        rounding always happens per line, before summation, never on the sum."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_billing_amounts
        """
        ctx = _setup_suspended_window_scenario(api)
        period = read_billing_period(ctx["bp_id"])
        # Suspension [05-07, 05-13) removes 6 whole days from the 30-day window.
        assert period["billable_days"] == 24
        assert period["tc_amount_cents"] == 43932
        assert period["pc_amount_cents"] == 4164
        assert period["total_amount_cents"] == 48096


class TestPerLineRoundingOrder:
    def _setup_fifteen_day_ready_period(self):
        ctx = setup_completed_episode(prescribed_days=15)
        periods = generate_billing(ctx["episode_id"])
        ctx["bp_id"] = periods[0]["id"]
        run_sweep()
        return ctx

    def test_per_line_rounded_amounts(self, api):
        """PRD §3.8: "Pricing computes each line as its fee multiplied by the
        number of days, divided by thirty, and rounded half up to whole cents;
        the period total is the sum of the two already-rounded lines —
        rounding always happens per line, before summation, never on the sum."

        Design: Difficulty/combinatorial_formula/per_line_rounding_before_sum
        """
        ctx = self._setup_fifteen_day_ready_period()
        period = read_billing_period(ctx["bp_id"])
        assert period["status"] == "READY"
        assert period["billable_days"] == 15
        # round_half_up(54915*15/30) = round_half_up(27457.5) = 27458
        assert period["tc_amount_cents"] == 27458
        # round_half_up(5205*15/30) = round_half_up(2602.5) = 2603
        assert period["pc_amount_cents"] == 2603

    def test_total_is_sum_of_rounded_lines(self, api):
        """PRD §3.8: "Pricing computes each line as its fee multiplied by the
        number of days, divided by thirty, and rounded half up to whole cents;
        the period total is the sum of the two already-rounded lines —
        rounding always happens per line, before summation, never on the sum."

        Design: Difficulty/combinatorial_formula/per_line_rounding_before_sum
        """
        ctx = self._setup_fifteen_day_ready_period()
        period = read_billing_period(ctx["bp_id"])
        # Sum of rounded lines: 27458 + 2603 = 30061 (sum-then-round would give 30060).
        assert period["total_amount_cents"] == 30061
        assert period["total_amount_cents"] == (
            period["tc_amount_cents"] + period["pc_amount_cents"]
        )


class TestBillableDaysBoundary:
    def _setup_ten_and_nine(self):
        ctx_a = setup_ready_billing_period(prescribed_days=10)
        ctx_b = setup_ready_billing_period(prescribed_days=9)
        return ctx_a, ctx_b

    def test_ten_billable_days_submits(self, api):
        """PRD §3.8: "Then the fiscal gates: the episode must not be
        `SUSPENDED`, else `ERR_EPISODE_SUSPENDED` (HTTP 422), and
        `billable_days` must be at least 10, else
        `ERR_BELOW_MINIMUM_BILLABLE_DAYS` (HTTP 422)."
        PRD §3.8: "A successful submit moves the period from `READY` to
        `SUBMITTED`, snapshots `total_amount_cents` into
        `submitted_total_cents`, adds `total_amount_cents` into the episode's
        `total_billed_cents`, and anchors `recognized_total_cents` at the
        submitted figure."

        Design: Difficulty/boundary_precision_check/billable_days_ten_vs_nine
        """
        ctx_a, ctx_b = self._setup_ten_and_nine()
        period_a = read_billing_period(ctx_a["bp_id"])
        assert period_a["billable_days"] == 10, "boundary is inclusive at 10"
        # TC 18305 + PC 1735 for 10 EVENT days.
        assert period_a["total_amount_cents"] == 20040

        submitted = validate_success(api.submit_billing_period(ctx_a["bp_id"], BILLING_1))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_total_cents"] == 20040

        resp = api.submit_billing_period(ctx_b["bp_id"], BILLING_1)
        validate_error(resp, ApiErrorId.ERR_BELOW_MINIMUM_BILLABLE_DAYS)

    def test_nine_billable_days_rejected(self, api):
        """PRD §3.8: "Then the fiscal gates: the episode must not be
        `SUSPENDED`, else `ERR_EPISODE_SUSPENDED` (HTTP 422), and
        `billable_days` must be at least 10, else
        `ERR_BELOW_MINIMUM_BILLABLE_DAYS` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/billable_days_ten_vs_nine
        """
        ctx_a, ctx_b = self._setup_ten_and_nine()
        period_b = read_billing_period(ctx_b["bp_id"])
        assert period_b["status"] == "READY"
        assert period_b["billable_days"] == 9

        resp = api.submit_billing_period(ctx_b["bp_id"], BILLING_1)
        validate_error(resp, ApiErrorId.ERR_BELOW_MINIMUM_BILLABLE_DAYS)
        assert read_billing_period(ctx_b["bp_id"])["status"] == "READY"

        # The 10-day sibling still submits cleanly in the same environment.
        submitted = validate_success(api.submit_billing_period(ctx_a["bp_id"], BILLING_1))
        assert submitted["status"] == "SUBMITTED"


class TestBillingWindowGeometry:
    def test_half_open_adjacent_windows_generated(self, api):
        """PRD §3.8: "The window with 0-based `period_index` i opens at the
        episode's `started_at` plus i times thirty days, and closes at the
        earlier of thirty days after its own start and the end of service."
        PRD §3.8: "Each period is half-open: its `start_date` is included and
        its `end_date` excluded, so two periods may touch — one ending exactly
        when the next begins — without overlapping; genuine overlap requires
        each window to start before the other ends."

        Design: Difficulty/resource_temporal_overlap/billing_window_half_open_adjacency
        """
        ctx = setup_monitoring_episode(prescribed_days=36)
        resp = api.generate_billing_periods(ctx["episode_id"], BILLING_1)
        periods = validate_success(resp, 201)
        assert isinstance(periods, list) and len(periods) == 2
        bp0, bp1 = periods[0], periods[1]
        assert_iso_prefix(bp0["start_date"], "2026-05-01T00:00:00", "bp0.start_date")
        assert_iso_prefix(bp0["end_date"], "2026-05-31T00:00:00", "bp0.end_date")
        assert_iso_prefix(bp1["start_date"], "2026-05-31T00:00:00", "bp1.start_date")
        assert_iso_prefix(bp1["end_date"], "2026-06-06T00:00:00", "bp1.end_date")
        assert bp0["end_date"] == bp1["start_date"], "adjacency at the half-open boundary"
        # Provisional pricing: 30 days -> 54915+5205; 6 days -> 10983+1041.
        assert bp0["provisional_total_cents"] == 60120
        assert bp1["provisional_total_cents"] == 12024

    def test_overlapping_regeneration_rejected(self, api):
        """PRD §3.8: "Generation is rejected with `ERR_BILLING_WINDOW_OVERLAP`
        (HTTP 409) when any existing billing period of the episode in
        `ACCRUING`, `READY`, `SUBMITTED`, or `ADJUSTMENT_PROPOSED` overlaps the
        range; `ADJUSTED` periods no longer block."

        Design: Difficulty/resource_temporal_overlap/billing_window_half_open_adjacency
        """
        ctx = setup_monitoring_episode(prescribed_days=36)
        periods = generate_billing(ctx["episode_id"])
        assert len(periods) == 2
        resp = api.generate_billing_periods(ctx["episode_id"], BILLING_1)
        validate_error(resp, ApiErrorId.ERR_BILLING_WINDOW_OVERLAP)


class TestSubmitStateGate:
    def _setup_accruing_short_window(self):
        ctx = setup_completed_episode(prescribed_days=6)
        periods = generate_billing(ctx["episode_id"])
        ctx["bp_id"] = periods[0]["id"]
        return ctx

    def test_submit_accruing_period_rejected_invalid_state(self, api):
        """PRD §3.8: "Maturity arrives through the sweep's fifth stage: a
        period whose `end_date` has been reached moves from `ACCRUING` to
        `READY`."
        PRD §2.8: "5. **State-machine preconditions** — from-state and guard
        checks: generic failures yield `ERR_INVALID_STATE` (409); a device
        already committed elsewhere yields `ERR_DEVICE_NOT_IN_STOCK` (409);
        activation before education yields `ERR_EDUCATION_INCOMPLETE` (422); a
        stale order version yields `ERR_STALE_VERSION` (412)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_submit
        """
        ctx = self._setup_accruing_short_window()
        period = read_billing_period(ctx["bp_id"])
        assert period["status"] == "ACCRUING"
        resp = api.submit_billing_period(ctx["bp_id"], BILLING_1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_state_failure_masks_fiscal_failure(self, api):
        """PRD §2.8: "A failure at any rung masks all later rungs: the response
        always carries the highest-priority failure present, never a lower
        one."
        PRD §2.8: "5. **State-machine preconditions** — from-state and guard
        checks: generic failures yield `ERR_INVALID_STATE` (409); a device
        already committed elsewhere yields `ERR_DEVICE_NOT_IN_STOCK` (409);
        activation before education yields `ERR_EDUCATION_INCOMPLETE` (422); a
        stale order version yields `ERR_STALE_VERSION` (412)."
        PRD §2.8: "10. **Business fiscal** — `ERR_EPISODE_SUSPENDED` (422),
        `ERR_BELOW_MINIMUM_BILLABLE_DAYS` (422), and
        `ERR_ADJUSTMENT_EXCEEDS_BILLED` (422)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_submit
        """
        ctx = self._setup_accruing_short_window()
        # The 6-day window would also fail the billable_days >= 10 fiscal gate,
        # but the state rung (5) precedes the fiscal rung (10).
        resp = api.submit_billing_period(ctx["bp_id"], BILLING_1)
        error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert error["error_id"] != "ERR_BELOW_MINIMUM_BILLABLE_DAYS"


class TestSubmitReferentialGate:
    def _setup_ready_without_report(self):
        ctx = setup_completed_episode(prescribed_days=10)
        periods = generate_billing(ctx["episode_id"])
        ctx["bp_id"] = periods[0]["id"]
        run_sweep()
        return ctx

    def test_submit_without_finalized_report_rejected(self, api):
        """PRD §3.8: "The referential gate fires first: the episode must have
        at least one `FINALIZED` diagnostic report, else
        `ERR_REPORT_NOT_FINALIZED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/billing_submit_requires_finalized_report
        """
        ctx = self._setup_ready_without_report()
        assert read_billing_period(ctx["bp_id"])["status"] == "READY"
        resp = api.submit_billing_period(ctx["bp_id"], BILLING_1)
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_FINALIZED)

    def test_submit_succeeds_after_report_finalized(self, api):
        """PRD §3.8: "The referential gate fires first: the episode must have
        at least one `FINALIZED` diagnostic report, else
        `ERR_REPORT_NOT_FINALIZED` (HTTP 422)."
        PRD §3.8: "A successful submit moves the period from `READY` to
        `SUBMITTED`, snapshots `total_amount_cents` into
        `submitted_total_cents`, adds `total_amount_cents` into the episode's
        `total_billed_cents`, and anchors `recognized_total_cents` at the
        submitted figure."

        Design: Difficulty/cross_entity_state_dependency/billing_submit_requires_finalized_report
        """
        ctx = self._setup_ready_without_report()
        resp = api.submit_billing_period(ctx["bp_id"], BILLING_1)
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_FINALIZED)

        create_and_finalize_report(ctx["episode_id"], ctx["physician"]["id"])
        submitted = validate_success(api.submit_billing_period(ctx["bp_id"], BILLING_1))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_total_cents"] == 20040


class TestAdjustments:
    def test_adjustment_exceeds_billed_rejected(self, api):
        """PRD §3.8: "Any `BillingSpecialist` may propose an adjustment
        carrying a signed `delta_cents` and a free-text `reason`; the delta's
        magnitude may not exceed `submitted_total_cents`, else
        `ERR_ADJUSTMENT_EXCEEDS_BILLED` (HTTP 422)."

        Design: Corner/validations/adjustment_exceeds_billed_rejected
        """
        ctx = setup_submitted_billing_period(prescribed_days=10)
        assert ctx["billing_period"]["submitted_total_cents"] == 20040
        resp = api.propose_adjustment(
            ctx["bp_id"],
            propose_adjustment_payload(delta_cents=-20041, reason="excessive clawback"),
            BILLING_1,
        )
        validate_error(resp, ApiErrorId.ERR_ADJUSTMENT_EXCEEDS_BILLED)
        assert read_billing_period(ctx["bp_id"])["status"] == "SUBMITTED"

    def test_segregation_of_duties_same_user_forbidden(self, api):
        """PRD §3.8: "Approval must come from a different specialist: if the
        approver's `X-User-ID` equals `proposed_by_user_id`, the call is
        rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/segregation_of_duties_same_user_forbidden
        """
        ctx = setup_submitted_billing_period(prescribed_days=10)
        billing1 = make_billing_specialist_headers("billing-1")
        validate_success(
            api.propose_adjustment(
                ctx["bp_id"],
                propose_adjustment_payload(delta_cents=100, reason="documentation fee"),
                billing1,
            )
        )
        resp = api.approve_adjustment(ctx["bp_id"], billing1)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert read_billing_period(ctx["bp_id"])["status"] == "ADJUSTMENT_PROPOSED"

    def test_approved_adjustment_raises_recognized_total(self, api):
        """PRD §3.8: "On approval the period moves to `ADJUSTED`,
        `approved_adjustment_cents` accumulates the proposed delta,
        `approved_by_user_id` records the approver, and
        `recognized_total_cents` is recomputed as `submitted_total_cents` plus
        `approved_adjustment_cents` — the invariant anchor that always ties the
        recognized figure to the submission plus its approved corrections."

        Design: Difficulty/compensating_invariant/billing_adjustment_monetary_conservation
        """
        ctx = setup_submitted_billing_period(prescribed_days=10)
        billing1 = make_billing_specialist_headers("billing-1")
        billing2 = make_billing_specialist_headers("billing-2")
        validate_success(
            api.propose_adjustment(
                ctx["bp_id"],
                propose_adjustment_payload(delta_cents=500, reason="late documentation"),
                billing1,
            )
        )
        adjusted = validate_success(api.approve_adjustment(ctx["bp_id"], billing2))
        assert adjusted["status"] == "ADJUSTED"
        assert adjusted["recognized_total_cents"] == 20540
        assert_recognized_total_invariant(adjusted)

    def test_compensating_adjustment_restores_recognized_total(self, api):
        """PRD §3.8: "Corrections after submission follow a segregated
        propose-and-approve loop, cycling `SUBMITTED` → `ADJUSTMENT_PROPOSED` →
        `ADJUSTED`, and a further proposal may start again from `ADJUSTED`."
        PRD §3.8: "On approval the period moves to `ADJUSTED`,
        `approved_adjustment_cents` accumulates the proposed delta,
        `approved_by_user_id` records the approver, and
        `recognized_total_cents` is recomputed as `submitted_total_cents` plus
        `approved_adjustment_cents` — the invariant anchor that always ties the
        recognized figure to the submission plus its approved corrections."

        Design: Difficulty/compensating_invariant/billing_adjustment_monetary_conservation
        """
        ctx = setup_submitted_billing_period(prescribed_days=10)
        billing1 = make_billing_specialist_headers("billing-1")
        billing2 = make_billing_specialist_headers("billing-2")
        validate_success(
            api.propose_adjustment(
                ctx["bp_id"], propose_adjustment_payload(delta_cents=500), billing1
            )
        )
        validate_success(api.approve_adjustment(ctx["bp_id"], billing2))
        validate_success(
            api.propose_adjustment(
                ctx["bp_id"],
                propose_adjustment_payload(delta_cents=-500, reason="reversal of prior adjustment"),
                billing1,
            )
        )
        restored = validate_success(api.approve_adjustment(ctx["bp_id"], billing2))
        assert restored["status"] == "ADJUSTED"
        assert restored["approved_adjustment_cents"] == 0
        assert restored["recognized_total_cents"] == 20040
        assert restored["recognized_total_cents"] == restored["submitted_total_cents"]
        assert_recognized_total_invariant(restored)


class TestSuspendedEpisodeBlocksSubmit:
    def test_suspended_episode_blocks_submit(self, api):
        """PRD §3.8: "Then the fiscal gates: the episode must not be
        `SUSPENDED`, else `ERR_EPISODE_SUSPENDED` (HTTP 422), and
        `billable_days` must be at least 10, else
        `ERR_BELOW_MINIMUM_BILLABLE_DAYS` (HTTP 422)."

        Design: Corner/validations/suspended_episode_blocks_submit
        """
        # 10-day episode; INTERIM report finalized while MONITORING (allowed);
        # billing generated; strikes at 05-03/05-05/05-07 (third left OPEN)
        # suspend the episode; sweep at 05-12 matures the window to READY.
        ctx = setup_monitoring_episode(prescribed_days=10)
        create_and_finalize_report(ctx["episode_id"], ctx["physician"]["id"])
        periods = generate_billing(ctx["episode_id"])
        bp_id = periods[0]["id"]
        record_gap_strikes(ctx["episode_id"], 3, resolve_last=False)
        assert read_episode(ctx["episode_id"])["compliance_status"] == "SUSPENDED"
        set_clock("2026-05-12T00:00:00Z")
        run_sweep()
        assert read_billing_period(bp_id)["status"] == "READY"

        resp = api.submit_billing_period(bp_id, BILLING_1)
        validate_error(resp, ApiErrorId.ERR_EPISODE_SUSPENDED)


class TestDerivedTotalBilled:
    def test_total_billed_snapshot_not_drifted_by_adjustment(self, api):
        """PRD §3.8: "A successful submit moves the period from `READY` to
        `SUBMITTED`, snapshots `total_amount_cents` into
        `submitted_total_cents`, adds `total_amount_cents` into the episode's
        `total_billed_cents`, and anchors `recognized_total_cents` at the
        submitted figure."
        PRD §3.8: "On approval the period moves to `ADJUSTED`,
        `approved_adjustment_cents` accumulates the proposed delta,
        `approved_by_user_id` records the approver, and
        `recognized_total_cents` is recomputed as `submitted_total_cents` plus
        `approved_adjustment_cents` — the invariant anchor that always ties the
        recognized figure to the submission plus its approved corrections."

        Design: Corner/complexity_layers/derived_total_billed_reconciliation
        """
        ctx = setup_ready_billing_period(prescribed_days=10)
        submitted = validate_success(api.submit_billing_period(ctx["bp_id"], BILLING_1))
        assert submitted["submitted_total_cents"] == 20040
        assert read_episode(ctx["episode_id"])["total_billed_cents"] == 20040

        billing1 = make_billing_specialist_headers("billing-1")
        billing2 = make_billing_specialist_headers("billing-2")
        validate_success(
            api.propose_adjustment(
                ctx["bp_id"],
                propose_adjustment_payload(delta_cents=500, reason="documentation"),
                billing1,
            )
        )
        validate_success(api.approve_adjustment(ctx["bp_id"], billing2))

        episode = read_episode(ctx["episode_id"])
        assert episode["total_billed_cents"] == 20040, (
            "approved adjustments move recognized_total_cents on the period, "
            "not the episode's submitted snapshot sum"
        )
        period = read_billing_period(ctx["bp_id"])
        assert period["recognized_total_cents"] == 20540
        assert_recognized_total_invariant(period)


class TestGenerateEnvelope:
    def test_generate_returns_array_envelope(self, api):
        """PRD §3.8: "Each generated period is born `ACCRUING` with
        `window_days` set to the whole days in its window and a
        `provisional_total_cents` priced immediately."
        PRD §3.8: "The window with 0-based `period_index` i opens at the
        episode's `started_at` plus i times thirty days, and closes at the
        earlier of thirty days after its own start and the end of service."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/endpoints/generate_returns_array_envelope
        """
        ctx = setup_monitoring_episode(prescribed_days=10)
        resp = api.generate_billing_periods(ctx["episode_id"], BILLING_1)
        body = resp.json()
        assert resp.status_code == 201
        assert body["response_type"] == "array"
        periods = body["data"]
        assert len(periods) == 1
        period = periods[0]
        assert period["period_index"] == 0
        assert_iso_prefix(period["start_date"], "2026-05-01T00:00:00", "start_date")
        assert_iso_prefix(period["end_date"], "2026-05-11T00:00:00", "end_date")
        assert period["status"] == "ACCRUING"
        assert period["window_days"] == 10
        assert period["provisional_total_cents"] == 20040
