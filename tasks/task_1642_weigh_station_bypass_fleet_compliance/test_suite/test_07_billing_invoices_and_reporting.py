"""Billing close, invoice math (tiers, surcharge, rounding, pause accrual),
payments, the past-due sweep, and ROI reporting."""
from test_helpers import (
    FINANCE,
    ApiErrorId,
    activate_credential,
    assert_invoice,
    close_period,
    create_active_carrier,
    create_config,
    create_subscription_for,
    create_vehicle_for,
    get_carrier,
    list_invoices_for,
    post_event,
    post_snapshot,
    set_clock,
    setup_bypass_ready,
    setup_carrier_with_invoice,
    validate_error,
    validate_success,
)

FULL_CREDS = ["IFTA", "IRP", "UCR"]


class TestInvoicePreviewVsClose:
    def test_preview_projects_full_period_for_active_subscription(self, api):
        """PRD §3.8: "The invoice preview answers "what would this period
        cost" without persisting anything: it defaults to the current period
        when `period_year` and `period_month` are omitted, uses the same
        line, tier, surcharge, and half-up rounding math as a real close, but
        projects billable days forward — an `ACTIVE` subscription bills from
        the later of its start and the period start through the earlier of
        its end and the period end, minus paused days accrued to date"

        Design: Difficulty/dual_variant_calc/provisional_vs_final_invoice_divergence
        """
        fx = setup_bypass_ready()
        preview = validate_success(api.get_invoice_preview(
            fx["carrier"]["id"], FINANCE,
            params={"period_year": 2026, "period_month": 8}))
        assert preview["billed_line_count"] == 1
        assert preview["tier_applied"] == "TIER_1"
        assert preview["gross_cents"] == 1799, \
            "the ACTIVE subscription projects all 31 days of August"
        assert preview["amount_due_cents"] == 1799
        assert preview["credit_applied_cents"] == 0
        assert list_invoices_for(fx["carrier"]["id"]) == [], \
            "the preview persists nothing"

    def test_final_close_bills_only_realized_days(self, api):
        """PRD §3.8: "Preview and close diverge whenever pauses or
        activations land between the preview day and period end."
        PRD §3.8: "The paused total is the subscription's accumulated
        `paused_days_current_period` plus — if the subscription is still
        `PAUSED` at close time — the days from `paused_at` through the
        month's final day inclusive, all confined to the overlap window;
        `billable_days` is the overlap minus that pause figure."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_invoice_divergence
        """
        fx = setup_bypass_ready()
        preview = validate_success(api.get_invoice_preview(
            fx["carrier"]["id"], FINANCE,
            params={"period_year": 2026, "period_month": 8}))
        assert preview["gross_cents"] == 1799

        # A safety pause begins on 2026-08-20 and is still open at close.
        set_clock("2026-08-20T00:00:00Z")
        post_snapshot(fx["carrier"]["id"], iss_score=90,
                      effective_date="2026-08-20")
        sub = validate_success(api.get_subscription(fx["subscription"]["id"],
                                                    FINANCE))
        assert sub["status"] == "PAUSED" and sub["paused_at"] == "2026-08-20"

        set_clock("2026-09-01T00:00:00Z")
        invoice = close_period(fx["carrier"]["id"])
        assert_invoice(invoice)
        # 31 overlap days minus 12 paused days (08-20..08-31) = 19 billable.
        assert invoice["lines"][0]["billable_days"] == 19
        assert invoice["lines"][0]["line_net_cents"] == 1103, \
            "round_half_up(1799*19/31)"
        assert invoice["gross_cents"] == 1103
        assert invoice["tier_applied"] == "TIER_1"
        assert invoice["billed_line_count"] == 1
        assert invoice["credit_applied_cents"] == 0
        assert invoice["amount_due_cents"] == 1103
        assert preview["gross_cents"] != invoice["gross_cents"], \
            "same subscription, two algorithm variants, different cents"


class TestLineRoundingAndTiers:
    def _three_vehicle_carrier(self, api):
        set_clock()
        create_config(state_code="CA", promote_to_participating=True)
        carrier = create_active_carrier()
        starts = {"2026-08-01": None, "2026-08-15": None, "2026-08-08": None}
        subs = {}
        for i, start in enumerate(starts, 1):
            veh = create_vehicle_for(carrier["id"], vin=f"VIN-000{i}")
            sub = create_subscription_for(carrier["id"], veh["id"],
                                          service_start_date=start)
            subs[sub["id"]] = {"vehicle_id": veh["id"], "start": start}
        set_clock("2026-09-01T00:00:00Z")
        return carrier, subs

    def test_per_line_rounding_then_sum(self, api):
        """PRD §2.8: "Where a computation produces a fractional cent — the
        per-line proration of subscription billing — each invoice line is
        rounded half-up to a whole cent, and only then are the rounded lines
        summed into the invoice gross (§3.8)."
        PRD §3.8: "Each line's `line_net_cents` is then the tier rate plus
        the surcharge, multiplied by the line's `billable_days`, divided by
        the number of days in the billing month, rounded half-up to a whole
        cent"

        Design: Difficulty/combinatorial_formula/invoice_line_rounding_order_per_line_then_sum
        """
        carrier, subs = self._three_vehicle_carrier(api)
        invoice = close_period(carrier["id"])
        assert_invoice(invoice)
        by_sub = {l["subscription_id"]: l for l in invoice["lines"]}
        nets = {}
        for sub_id, info in subs.items():
            line = by_sub[sub_id]
            nets[info["start"]] = (line["billable_days"], line["line_net_cents"])
        assert nets["2026-08-01"] == (31, 1799)   # round_half_up(1799*31/31)
        assert nets["2026-08-15"] == (17, 987)    # round_half_up(1799*17/31)
        assert nets["2026-08-08"] == (24, 1393)   # round_half_up(1799*24/31)
        assert invoice["gross_cents"] == 4179, \
            "per-line-then-sum, not round(1799*72/31) == 4178"

    def test_rounding_invoice_header_fields(self, api):
        """PRD §3.8: "The `billed_line_count` selects the tier — one through
        ten lines price at `TIER_1`"
        PRD §3.8: "The invoice's `due_date` falls on the fifteenth day of the
        month after the period — the first day of the following month plus
        fourteen days, so an August 2026 period falls due on 2026-09-15."
        PRD §3.8: "A pilot surcharge applies per line: when a state program
        config exists for the vehicle's `home_state_code` and that config's
        `participation_status` is `PILOT` at close time, the line's
        `surcharge_cents` is 200; otherwise it is 0."

        Design: Difficulty/combinatorial_formula/invoice_line_rounding_order_per_line_then_sum
        """
        carrier, _subs = self._three_vehicle_carrier(api)
        invoice = close_period(carrier["id"])
        assert invoice["billed_line_count"] == 3
        assert invoice["tier_applied"] == "TIER_1"
        assert all(l["surcharge_cents"] == 0 for l in invoice["lines"]), \
            "the home-state config is PARTICIPATING at close time"
        assert all(l["tier_rate_cents"] == 1799 for l in invoice["lines"])
        assert invoice["due_date"] == "2026-09-15"
        assert invoice["status"] == "ISSUED"
        assert invoice["amount_due_cents"] == 4179

    def test_eleventh_line_drops_every_line_to_tier_2(self, api):
        """PRD §3.8: "The `billed_line_count` selects the tier — one through
        ten lines price at `TIER_1`, eleven through fifty at `TIER_2`,
        fifty-one or more at `TIER_3` — and the corresponding per-vehicle
        rate of 1,799, 1,599, or 1,399 cents applies to every line on the
        invoice, so the eleventh subscribed vehicle lowers the rate for the
        first ten as well."

        Design: Corner/calculations/tier_drops_all_lines_at_11
        """
        set_clock()
        car_a = create_active_carrier(dot_number="100001", legal_name="Carrier A")
        car_b = create_active_carrier(dot_number="100002", legal_name="Carrier B")
        for i in range(1, 11):
            veh = create_vehicle_for(car_a["id"], vin=f"VIN-A-{i:02d}")
            create_subscription_for(car_a["id"], veh["id"])
        for i in range(1, 12):
            veh = create_vehicle_for(car_b["id"], vin=f"VIN-B-{i:02d}")
            create_subscription_for(car_b["id"], veh["id"])
        set_clock("2026-09-01T00:00:00Z")

        inv_a = close_period(car_a["id"])
        assert inv_a["billed_line_count"] == 10
        assert inv_a["tier_applied"] == "TIER_1"
        assert inv_a["gross_cents"] == 10 * 1799

        inv_b = close_period(car_b["id"])
        assert inv_b["billed_line_count"] == 11
        assert inv_b["tier_applied"] == "TIER_2"
        assert inv_b["gross_cents"] == 11 * 1599
        assert inv_b["gross_cents"] < inv_a["gross_cents"], \
            "the eleventh subscribed vehicle lowers the rate for the first ten as well"

    def test_pilot_surcharge_applied_at_close(self, api):
        """PRD §3.8: "A pilot surcharge applies per line: when a state
        program config exists for the vehicle's `home_state_code` and that
        config's `participation_status` is `PILOT` at close time, the line's
        `surcharge_cents` is 200; otherwise it is 0."

        Design: Corner/calculations/pilot_surcharge_applied_at_close
        """
        set_clock()
        create_config(state_code="CA", promote_to_participating=True)
        create_config(state_code="OR")  # stays PILOT
        carrier = create_active_carrier()
        veh_ca = create_vehicle_for(carrier["id"], vin="VIN-0001",
                                    plate_number="P-1", home_state_code="CA")
        veh_or = create_vehicle_for(carrier["id"], vin="VIN-0002",
                                    plate_number="P-2", plate_state="OR",
                                    home_state_code="OR")
        create_subscription_for(carrier["id"], veh_ca["id"])
        create_subscription_for(carrier["id"], veh_or["id"])
        set_clock("2026-09-01T00:00:00Z")

        invoice = close_period(carrier["id"])
        by_vehicle = {l["vehicle_id"]: l for l in invoice["lines"]}
        assert by_vehicle[veh_ca["id"]]["surcharge_cents"] == 0
        assert by_vehicle[veh_ca["id"]]["line_net_cents"] == 1799
        assert by_vehicle[veh_or["id"]]["surcharge_cents"] == 200
        assert by_vehicle[veh_or["id"]]["line_net_cents"] == 1999, \
            "round_half_up((1799+200)*31/31)"
        assert invoice["gross_cents"] == 3798
        assert invoice["tier_applied"] == "TIER_1"
        assert invoice["billed_line_count"] == 2


class TestPauseAccrualAndPartition:
    def _pause_and_resume(self, api):
        fx = setup_bypass_ready()
        set_clock("2026-08-16T12:00:00Z")
        post_snapshot(fx["carrier"]["id"], iss_score=90,
                      effective_date="2026-08-16")
        paused = validate_success(api.get_subscription(fx["subscription"]["id"],
                                                       FINANCE))
        assert paused["status"] == "PAUSED" and paused["paused_at"] == "2026-08-16"
        set_clock("2026-08-21T12:00:00Z")
        post_snapshot(fx["carrier"]["id"], iss_score=20,
                      effective_date="2026-08-21")
        cred = activate_credential(fx["credential"]["id"], fx["carrier"]["id"])
        return fx, cred

    def test_reactivation_resumes_and_accrues_paused_days(self, api):
        """PRD §3.4: "When activation succeeds against a `PAUSED` covering
        subscription, the subscription resumes automatically — service
        follows the credential."
        PRD §3.4: "Reactivation reverses that bookkeeping: the vehicle's
        `PAUSED` subscription returns to `ACTIVE`, the day count between the
        recorded `paused_at` date and the resume date is added to
        `paused_days_current_period`, and `paused_at` is cleared."

        Design: Difficulty/compensating_invariant/subscription_day_partition_conservation
        """
        fx, cred = self._pause_and_resume(api)
        assert cred["status"] == "ACTIVE", \
            "reactivation succeeds even though the subscription was PAUSED"
        sub = validate_success(api.get_subscription(fx["subscription"]["id"],
                                                    FINANCE))
        assert sub["status"] == "ACTIVE"
        assert sub["paused_days_current_period"] == 5, \
            "2026-08-16 through the 2026-08-21 resume is five days"
        assert sub["paused_at"] is None

    def test_close_bills_billable_days_and_resets_pause_counter(self, api):
        """PRD §3.8: "`billable_days` is the overlap minus that pause
        figure."
        PRD §3.8: "After the computation, the close resets pause bookkeeping
        on all of the carrier's subscriptions — `paused_days_current_period`
        returns to zero while a still-paused row keeps its `paused_at`"

        Design: Difficulty/compensating_invariant/subscription_day_partition_conservation
        """
        fx, _cred = self._pause_and_resume(api)
        sub_before = validate_success(api.get_subscription(
            fx["subscription"]["id"], FINANCE))
        paused_days = sub_before["paused_days_current_period"]

        set_clock("2026-09-01T00:00:00Z")
        invoice = close_period(fx["carrier"]["id"])
        line = invoice["lines"][0]
        assert line["billable_days"] == 26
        assert line["billable_days"] + paused_days == 31, \
            "billable days plus paused days partition the month's overlap"
        assert line["line_net_cents"] == 1509, "round_half_up(1799*26/31)"
        assert invoice["gross_cents"] == 1509
        assert invoice["credit_applied_cents"] == 0
        assert invoice["amount_due_cents"] == 1509

        sub_after = validate_success(api.get_subscription(
            fx["subscription"]["id"], FINANCE))
        assert sub_after["paused_days_current_period"] == 0, \
            "the close resets pause bookkeeping"
        assert sub_after["status"] == "ACTIVE"


class TestCloseEligibilityAndPayments:
    def test_close_unelapsed_period_rejected(self, api):
        """PRD §3.8: "only after the month has fully elapsed — a period
        whose last day is today or still ahead is rejected with
        `ERR_BILLING_PERIOD_NOT_CLOSABLE` (HTTP 422)"

        Design: Corner/validations/close_period_not_elapsed_returns_422
        """
        fx = setup_bypass_ready()
        set_clock("2026-08-15T00:00:00Z")
        resp = api.close_billing_period(fx["carrier"]["id"], 2026, 8, FINANCE)
        validate_error(resp, ApiErrorId.ERR_BILLING_PERIOD_NOT_CLOSABLE)

    def test_close_already_closed_period_rejected(self, api):
        """PRD §2.6: "a carrier's billing history is closed exactly once per
        period: a close request for a month already present in
        `closed_billing_periods` is rejected with
        `ERR_BILLING_PERIOD_ALREADY_CLOSED`."
        PRD §3.8: "appends the period label to `closed_billing_periods`"

        Design: Corner/validations/close_period_already_closed_returns_409
        """
        fx = setup_carrier_with_invoice()
        resp = api.close_billing_period(fx["carrier"]["id"], 2026, 8, FINANCE)
        validate_error(resp, ApiErrorId.ERR_BILLING_PERIOD_ALREADY_CLOSED)
        invoices = list_invoices_for(fx["carrier"]["id"])
        assert len(invoices) == 1, "only one invoice ever exists for the pair"
        carrier = get_carrier(fx["carrier"]["id"])
        assert len(carrier["closed_billing_periods"]) == 1, \
            "one period label was appended by the single successful close"

    def test_payment_amount_must_match_exactly(self, api):
        """PRD §3.8: "the amount must equal the invoice's `amount_due_cents`
        to the cent — partial payments and overpayments are both rejected
        with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 400)"

        Design: Corner/validations/payment_amount_mismatch_returns_400
        """
        fx = setup_carrier_with_invoice()
        invoice = fx["invoice"]
        assert invoice["amount_due_cents"] == 1799
        resp = api.record_payment(invoice["id"], 1800, FINANCE)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)
        fresh = validate_success(api.get_invoice(invoice["id"], FINANCE))
        assert fresh["status"] == "ISSUED"
        assert fresh["amount_due_cents"] == 1799


class TestPastDueSweep:
    def test_due_date_boundary_and_standing_propagation(self, api):
        """PRD §3.8: "the past-due sweep — run at every clock-set and at
        every billing close — flips an `ISSUED` invoice to `PAST_DUE` once
        its `due_date` lies in the past, and that flip propagates
        `payment_standing` `PAST_DUE` onto the carrier's `SCHEDULED`,
        `ACTIVE`, and `PAUSED` subscriptions"

        Design: Corner/cross_cutting_layers/invoice_due_date_boundary_past_due_sweep
        """
        fx = setup_carrier_with_invoice()
        assert fx["invoice"]["due_date"] == "2026-09-15"

        set_clock("2026-09-15T23:59:00Z")
        on_due_day = validate_success(api.get_invoice(fx["invoice"]["id"], FINANCE))
        assert on_due_day["status"] == "ISSUED", \
            "the due date itself is not yet in the past"

        set_clock("2026-09-16T00:00:00Z")
        after = validate_success(api.get_invoice(fx["invoice"]["id"], FINANCE))
        assert after["status"] == "PAST_DUE"
        sub = validate_success(api.get_subscription(fx["subscription"]["id"],
                                                    FINANCE))
        assert sub["payment_standing"] == "PAST_DUE", \
            "the flip propagates standing onto the carrier's subscriptions"

    def test_parallel_status_and_standing_dimensions(self, api):
        """PRD §3.4: "From there the subscription evolves on two independent
        dimensions of the same row."
        PRD §3.8: "that flip propagates `payment_standing` `PAST_DUE` onto
        the carrier's `SCHEDULED`, `ACTIVE`, and `PAUSED` subscriptions"

        Design: Difficulty/non_linear_state_machine/subscription_parallel_status_and_standing
        """
        fx = setup_carrier_with_invoice()
        set_clock("2026-09-16T00:00:00Z")
        sub = validate_success(api.get_subscription(fx["subscription"]["id"],
                                                    FINANCE))
        assert sub["status"] == "ACTIVE"
        assert sub["payment_standing"] == "PAST_DUE", \
            "the past-due sweep moves standing without touching lifecycle"

    def test_standing_recovers_while_still_paused(self, api):
        """PRD §3.8: "When the last past-due invoice is settled — by payment
        or by the dispute credit sweep of §3.6 — standing returns to
        `CURRENT`."
        PRD §3.4: "From there the subscription evolves on two independent
        dimensions of the same row."

        Design: Difficulty/non_linear_state_machine/subscription_parallel_status_and_standing
        """
        fx = setup_carrier_with_invoice()
        set_clock("2026-09-16T00:00:00Z")
        # Safety cascade pauses the (already PAST_DUE) subscription.
        post_snapshot(fx["carrier"]["id"], iss_score=90,
                      effective_date="2026-09-16")
        sub = validate_success(api.get_subscription(fx["subscription"]["id"],
                                                    FINANCE))
        assert sub["status"] == "PAUSED"
        assert sub["payment_standing"] == "PAST_DUE", \
            "the two dimensions moved on different triggers"

        paid = validate_success(api.record_payment(fx["invoice"]["id"], 1799,
                                                   FINANCE))
        assert paid["status"] == "PAID"
        sub = validate_success(api.get_subscription(fx["subscription"]["id"],
                                                    FINANCE))
        assert sub["status"] == "PAUSED", "payment does not resume service"
        assert sub["payment_standing"] == "CURRENT", \
            "settling the last past-due invoice restores standing"


class TestRoiReport:
    def _five_event_population(self, api):
        fx = setup_bypass_ready(config_fields={
            "requires_weight_clearance": False,
            "random_pull_in_rate_bps": 0,
            "bypass_rate_cap_bps": 10000,
        })
        set_clock("2026-08-05T12:00:00Z")
        vid = fx["vehicle"]["id"]
        sid = fx["station"]["id"]
        ev1 = post_event(vid, sid, "2026-08-04T10:00:00Z",
                         measured_weight_lbs=80000,
                         credentials_presented=FULL_CREDS)
        ev2 = post_event(vid, sid, "2026-08-04T11:00:00Z",
                         credentials_presented=FULL_CREDS)
        ev3 = post_event(vid, sid, "2026-08-05T10:00:00Z",
                         measured_weight_lbs=80000,
                         credentials_presented=["IFTA"])
        ev4 = post_event(vid, sid, "2026-08-05T11:00:00Z",
                         measured_weight_lbs=80000,
                         credentials_presented=FULL_CREDS)
        ev5 = post_event(vid, sid, "2026-08-05T11:30:00Z",
                         measured_weight_lbs=90000,
                         credentials_presented=FULL_CREDS)
        return fx, [ev1, ev2, ev3, ev4, ev5]

    def test_roi_standard_variant_counts_all_grants(self, api):
        """PRD §3.8: "It buckets the carrier's bypass events by the month of
        `approach_at` and reports `total_approaches`, `bypasses_granted`, and
        `pull_ins` — the three partition, so approaches equal grants plus
        pull-ins — along with `verified_bypasses`, the granted events whose
        `weight_verified` and `credentials_complete` are both true."
        PRD §3.8: "`bypass_rate_bps` is the granted count multiplied by ten
        thousand and divided by the total, fractional part discarded"
        PRD §3.8: "`estimated_savings_cents` multiplies the counted bypasses
        by 1,275 cents, the avoided cost per bypass. `subscription_fees_cents`
        is the `gross_cents` of the carrier's invoice for the period, or zero
        when none exists. `roi_bps` is ... null when the fees are zero."

        Design: Difficulty/dual_variant_calc/roi_standard_vs_conservative_divergence
        """
        fx, events = self._five_event_population(api)
        report = validate_success(api.get_roi_report(
            fx["carrier"]["id"], FINANCE,
            params={"period_year": 2026, "period_month": 8,
                    "variant": "STANDARD"}))
        assert report["total_approaches"] == 5
        assert report["bypasses_granted"] == 3
        assert report["pull_ins"] == 2
        assert report["total_approaches"] == \
            report["bypasses_granted"] + report["pull_ins"]
        assert report["verified_bypasses"] == 2
        assert report["bypass_rate_bps"] == 6000, "floor(3*10000/5)"
        assert report["estimated_savings_cents"] == 3 * 1275
        assert report["subscription_fees_cents"] == 0, \
            "no invoice exists for the period"
        assert report["roi_bps"] is None, "roi is null when the fees are zero"
        assert report["inspections_recorded"] == 0
        assert report["inspection_reduction_bps"] == 6000, \
            "inspection_reduction_bps equals the bypass rate"

    def test_roi_conservative_variant_counts_only_verified(self, api):
        """PRD §3.8: "The `variant` parameter picks the savings basis:
        `STANDARD`, the default, counts every granted bypass as an avoided
        inspection, while `CONSERVATIVE` counts only verified bypasses and
        therefore reports savings no higher than standard on identical data
        whenever any grant went unverified."
        PRD §3.5: "`weight_verified` is true exactly when a reading is
        present and at or under the allowance limit."

        Design: Difficulty/dual_variant_calc/roi_standard_vs_conservative_divergence
        """
        fx, events = self._five_event_population(api)
        # The second event was granted without a weight reading.
        assert events[1]["decision"] == "BYPASS_GRANTED"
        assert events[1]["weight_verified"] is False
        assert events[4]["decision"] == "PULL_IN"
        assert events[4]["decision_reasons"] == ["OVERWEIGHT"]

        report = validate_success(api.get_roi_report(
            fx["carrier"]["id"], FINANCE,
            params={"period_year": 2026, "period_month": 8,
                    "variant": "CONSERVATIVE"}))
        assert report["verified_bypasses"] == 2
        assert report["estimated_savings_cents"] == 2 * 1275, \
            "same events, different variant, different money"
        assert report["subscription_fees_cents"] == 0
        assert report["roi_bps"] is None
