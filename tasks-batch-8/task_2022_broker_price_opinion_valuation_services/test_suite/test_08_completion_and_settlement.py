"""Completion settlement: late-fee rounding, on-time boundary, inline computed
fields, cancel cascades on fee lines, and round-per-line payout aggregation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_comparable,
    add_fee,
    add_photo_set_for_order,
    add_selected_comps,
    cancel_order,
    complete,
    create_batch,
    dispatch_to_broker,
    drive_order_to_completed,
    drive_order_to_in_progress,
    get_broker,
    get_order,
    list_fee_lines,
    make_client_admin_headers,
    new_order,
    open_qc,
    reconcile_fees,
    record_verdict,
    set_clock,
    setup_market,
    submit_order,
    submit_report,
    validate_error,
    validate_success,
)

BILLING = TEST_USERS["billing_clerk_headers"]


class TestLateFeeNestedRounding:
    def test_days_rounded_half_up_before_penalty_multiplication(self, api):
        """PRD §3.7: "otherwise it is the elapsed seconds between `sla_due_at`
        and `completed_at` divided by 86,400 (the number of seconds in a day),
        floored and rounded half-up to a whole day count."
        PRD §3.7: "the raw penalty is the order's `agreed_fee_cents` multiplied
        by the owning client's `late_penalty_bps_per_day` (at most 2000 basis
        points per day) multiplied by `days_late`, divided by 10,000; the
        `late_penalty_cents` is that raw penalty rounded half-up to whole cents"

        Design: Difficulty/combinatorial_formula/late_fee_nested_rounding_mode_b
        """
        env = setup_market("AZ", client_code="CLD", broker_code="BRKD",
                           client_overrides={"sla_hours_standard": 48,
                                             "sla_hours_rush": 24,
                                             "late_penalty_bps_per_day": 250})
        # Dispatched at 2026-08-01T00:00:00Z -> sla_due_at 2026-08-03T00:00:00Z.
        # Completed 36 hours late: 129600s = 1.5 days -> round_half_up -> 2 days.
        # raw = 15050 * 250 * 2 / 10000 = 752.5 -> round_half_up -> 753.
        completed = drive_order_to_completed(
            env, complete_clock="2026-08-04T12:00:00Z", agreed_fee_cents=15050)
        assert completed["fulfillment_status"] == "COMPLETED"
        assert completed["days_late"] == 2, (
            f"1.5 days must round half-up to 2, got {completed['days_late']}")
        assert completed["late_penalty_cents"] == 753
        assert completed["net_payable_cents"] == 15050 - 753

    def test_sub_half_day_late_rounds_down_to_zero(self, api):
        """PRD §3.7: "otherwise it is the elapsed seconds between `sla_due_at`
        and `completed_at` divided by 86,400 (the number of seconds in a day),
        floored and rounded half-up to a whole day count. If `days_late` is 0,
        the `late_penalty_cents` is 0."

        Design: Difficulty/combinatorial_formula/late_fee_nested_rounding_mode_b
        """
        env = setup_market("AZ", client_code="CLD", broker_code="BRKD",
                           client_overrides={"sla_hours_standard": 48,
                                             "sla_hours_rush": 24,
                                             "late_penalty_bps_per_day": 250})
        # Completed 8 hours late: 28800s / 86400 = 0.333 days -> round_half_up
        # to a whole day count gives 0, so no penalty accrues.
        completed = drive_order_to_completed(
            env, complete_clock="2026-08-03T08:00:00Z", agreed_fee_cents=10000)
        assert completed["days_late"] == 0
        assert completed["late_penalty_cents"] == 0
        assert completed["net_payable_cents"] == 10000


class TestLateFeeBoundaries:
    def test_late_fee_zero_when_completed_on_time(self, api):
        """PRD §3.7: "The read-only `days_late` is 0 when the order completed on
        or before its `sla_due_at`"
        PRD §3.7: "If `days_late` is 0, the `late_penalty_cents` is 0."

        Design: Corner/calculations/late_fee_zero_when_completed_on_time
        """
        env = setup_market("MD", client_code="CLF1", broker_code="BF1",
                           client_overrides={"sla_hours_standard": 48,
                                             "sla_hours_rush": 24,
                                             "late_penalty_bps_per_day": 500})
        # sla_due_at is 2026-08-03T00:00:00Z; completing exactly at the boundary
        # is "on or before" and yields no penalty.
        completed = drive_order_to_completed(
            env, complete_clock="2026-08-03T00:00:00Z", agreed_fee_cents=20000)
        assert completed["days_late"] == 0
        assert completed["late_penalty_cents"] == 0
        assert completed["net_payable_cents"] == 20000

    def test_immediate_consistency_on_complete(self, api):
        """PRD §3.7: "Completion stamps `completed_at` to the current instant and
        settles the late-fee arithmetic."
        PRD §3.7: "The read-only `net_payable_cents` is then `agreed_fee_cents`
        minus `late_penalty_cents`, floored at 0."
        (10000 * 1000 bps * 1 day / 10000 = 1000, rounded half-up.)

        Design: Corner/consistency_model/immediate_consistency_on_complete
        """
        env = setup_market("WV", client_code="CIMM", broker_code="BIMM",
                           client_overrides={"sla_hours_standard": 48,
                                             "sla_hours_rush": 24,
                                             "late_penalty_bps_per_day": 1000})
        # Same-response check: the completion response itself must carry the
        # computed fields (no secondary read needed to observe them).
        completed = drive_order_to_completed(
            env, complete_clock="2026-08-04T00:00:00Z", agreed_fee_cents=10000)
        assert completed["days_late"] == 1
        assert completed["late_penalty_cents"] == 1000
        assert completed["net_payable_cents"] == 9000


class TestCompletionCascade:
    def test_complete_sets_terminal_state_and_settlement(self, api):
        """PRD §3.7: "the raw penalty is the order's `agreed_fee_cents`
        multiplied by the owning client's `late_penalty_bps_per_day` (at most
        2000 basis points per day) multiplied by `days_late`, divided by 10,000"
        (20000 * 500 * 3 / 10000 = 3000.)

        Design: Difficulty/transitive_cascade/order_complete_cascades_broker_then_score
        """
        env = setup_market("UT", client_code="CLH", broker_code="BRKH",
                           client_overrides={"sla_hours_standard": 48,
                                             "sla_hours_rush": 24,
                                             "late_penalty_bps_per_day": 500})
        completed = drive_order_to_completed(
            env, complete_clock="2026-08-06T00:00:00Z", agreed_fee_cents=20000)
        assert completed["fulfillment_status"] == "COMPLETED"
        assert completed["days_late"] == 3
        assert completed["late_penalty_cents"] == 3000
        assert completed["net_payable_cents"] == 17000

    def test_complete_triggers_composite_score_recompute(self, api):
        """PRD §3.3: "The turnaround component is 1 minus the ratio of
        late-completed orders to total completed orders in the window, with the
        ratio capped at 1 and an empty denominator treated as 1."
        PRD §3.7: "Completion also decrements the broker's open-order count,
        triggers a `composite_score` recompute driven by `is_rush_breach` and
        `days_late`"
        (One late completed order, one APPROVE verdict, default weights
        0.5/0.3/0.2: 100 * (0.5*0 + 0.3*1.0 + 0.2*1.0) = 50.00.)

        Design: Difficulty/transitive_cascade/order_complete_cascades_broker_then_score
        """
        env = setup_market("UT", client_code="CLH", broker_code="BRKH",
                           client_overrides={"sla_hours_standard": 48,
                                             "sla_hours_rush": 24,
                                             "late_penalty_bps_per_day": 500})
        completed = drive_order_to_completed(
            env, complete_clock="2026-08-06T00:00:00Z", agreed_fee_cents=20000)
        assert completed["days_late"] == 3

        # Read the score one day later so the completion instant falls strictly
        # inside the trailing-90-day window (the window excludes "now").
        set_clock("2026-08-07T00:00:00Z")
        broker = get_broker(env["broker"]["id"])
        assert float(broker["composite_score"]) == 50.0, (
            f"Late completion must degrade the turnaround component to 0; "
            f"got {broker['composite_score']}")


class TestCancelCascade:
    def test_cancel_from_completed_returns_invalid_state(self, api):
        """PRD §3.4: "A client may cancel an order at any of three points —
        `INTAKE`, `READY_FOR_DISPATCH`, or `DISPATCHED` — through a `ClientAdmin`
        cancellation; an order in any other state rejects the attempt with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cancel_from_completed_returns_invalid_state
        """
        env = setup_market("NJ", client_code="CT1", broker_code="BT1")
        completed = drive_order_to_completed(env)

        resp = api.cancel_order(
            completed["id"], make_client_admin_headers(env["client"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_order(completed["id"])["fulfillment_status"] == "COMPLETED"

    def test_cancel_from_dispatched_preserves_confirmed_fee_lines(self, api):
        """PRD §3.4: "Cancellation moves the order to `CANCELLED` and cancels
        every `DRAFT` comparable and every `DRAFT` fee line on it."
        PRD §3.4: "Cancelling from `DISPATCHED` additionally clears the
        `assigned_broker_id` and decrements the broker's open-order count, but
        deliberately does not increment the broker's decline count — a
        cancellation is not a decline."

        Design: Difficulty/compensating_invariant/fee_reconciliation_conservation_across_cancel
        """
        env = setup_market("MO", client_code="CLR", broker_code="BRKR")
        order = new_order(env, agreed_fee_cents=10000)
        confirmed = add_fee(env, order, 6000, fee_kind="BASE", as_role="ops")
        draft = add_fee(env, order, 4000, fee_kind="RUSH_SURCHARGE", as_role="ops")
        validate_success(
            api.confirm_fee_line(order["id"], confirmed["id"], BILLING))
        order = submit_order(env, order)
        order = dispatch_to_broker(env, order)

        cancelled = cancel_order(env, order)
        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert cancelled["assigned_broker_id"] is None

        lines = {f["id"]: f for f in list_fee_lines(order["id"])}
        assert lines[confirmed["id"]]["status"] == "CONFIRMED", (
            "CONFIRMED fee lines must survive the cancel cascade")
        assert lines[draft["id"]]["status"] == "CANCELLED", (
            "DRAFT fee lines must be cancelled with the order")
        non_cancelled = sum(f["amount_cents"] for f in lines.values()
                            if f["status"] != "CANCELLED")
        assert non_cancelled == 6000, (
            f"Only the CONFIRMED 6000 must remain, got {non_cancelled}")

    def test_cancel_from_intake_cancels_draft_children(self, api):
        """PRD §3.4: "Cancellation moves the order to `CANCELLED` and cancels
        every `DRAFT` comparable and every `DRAFT` fee line on it."

        Design: Difficulty/compensating_invariant/fee_reconciliation_conservation_across_cancel
        """
        env = setup_market("MO", client_code="CLR", broker_code="BRKR")
        order = new_order(env, agreed_fee_cents=10000)
        comp = add_comparable(env, order)
        fee = add_fee(env, order, 10000, as_role="ops")

        cancelled = cancel_order(env, order)
        assert cancelled["fulfillment_status"] == "CANCELLED"

        comps = validate_success(
            api.list_comparables(order["id"], TEST_USERS["operations_manager_headers"]))
        assert {c["id"]: c for c in comps}[comp["id"]]["status"] == "CANCELLED"
        lines = {f["id"]: f for f in list_fee_lines(order["id"])}
        assert lines[fee["id"]]["status"] == "CANCELLED"


class TestPayoutPerLineAggregation:
    def test_per_order_late_fee_values(self, api):
        """PRD §3.7: "the `late_penalty_cents` is that raw penalty rounded
        half-up to whole cents, capped so it never exceeds `agreed_fee_cents`.
        The read-only `net_payable_cents` is then `agreed_fee_cents` minus
        `late_penalty_cents`, floored at 0."
        (10001 * 333 bps * 1 day / 10000 = 333.0333 -> 333 per order.)

        Design: Difficulty/dual_variant_calc/fee_reconciliation_per_line_vs_sum_then_round
        """
        env = setup_market("TX", client_code="CLX", broker_code="BRKX",
                           client_overrides={"sla_hours_standard": 48,
                                             "sla_hours_rush": 24,
                                             "late_penalty_bps_per_day": 333})
        first = drive_order_to_completed(
            env, complete_clock="2026-08-03T12:00:00Z", agreed_fee_cents=10001)
        assert first["days_late"] == 1
        assert first["late_penalty_cents"] == 333
        assert first["net_payable_cents"] == 9668

        # Second order lives entirely under the advanced clock; photos are
        # captured at the current logical instant to satisfy the capture window.
        second = drive_order_to_in_progress(env, agreed_fee_cents=10001)
        add_selected_comps(env, second)
        add_photo_set_for_order(env, second, captured_at="2026-08-03T12:00:00Z")
        reconcile_fees(env, second)
        second = submit_report(env, second)
        qc2 = open_qc(second)
        record_verdict(second, qc2, verdict="APPROVE", defects_found=0)
        set_clock("2026-08-06T00:00:00Z")
        second = complete(second)
        assert second["days_late"] == 1
        assert second["late_penalty_cents"] == 333
        assert second["net_payable_cents"] == 9668

    def test_payout_total_is_round_per_line_sum(self, api):
        """PRD §3.8: "`total_payable_cents`, the sum of `net_payable_cents`
        across orders in `COMPLETED` whose `completed_at` falls within the
        half-open period and whose `assigned_broker_id` is the recipient — with
        each order's contribution rounded to integer cents before summation (a
        round-per-line rule)"
        PRD §3.8: "the round-per-line figure is the authoritative one for
        payout." (9668 + 9668 = 19336.)

        Design: Difficulty/dual_variant_calc/fee_reconciliation_per_line_vs_sum_then_round
        """
        env = setup_market("TX", client_code="CLX", broker_code="BRKX",
                           client_overrides={"sla_hours_standard": 48,
                                             "sla_hours_rush": 24,
                                             "late_penalty_bps_per_day": 333})
        drive_order_to_completed(
            env, complete_clock="2026-08-03T12:00:00Z", agreed_fee_cents=10001)

        second = drive_order_to_in_progress(env, agreed_fee_cents=10001)
        add_selected_comps(env, second)
        add_photo_set_for_order(env, second, captured_at="2026-08-03T12:00:00Z")
        reconcile_fees(env, second)
        second = submit_report(env, second)
        qc2 = open_qc(second)
        record_verdict(second, qc2, verdict="APPROVE", defects_found=0)
        set_clock("2026-08-06T00:00:00Z")
        complete(second)

        batch = create_batch(env["broker"]["id"])
        assert batch["order_count"] == 2
        assert batch["total_payable_cents"] == 19336, (
            f"Per-line-rounded total must be 19336, got "
            f"{batch['total_payable_cents']}")
