"""Estimated payments: schedule generation (both methods, pinned cumulative
rounding, quarter tiling), manual-creation interval rules, record/reverse
conservation, the lateness sweep, and the state-vs-fiscal error pair.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_estimated_payment_payload,
    create_fy2026_tax_year,
    create_generate_schedule_payload,
    create_us_il_jurisdiction,
    create_us_ny_jurisdiction,
    generate_sorted_schedule,
    get_estimated_payment,
    set_logical_clock,
    setup_year_with_annualized_schedule,
    validate_error,
    validate_paginated,
    validate_success,
)

# Canonical IL annualized quarter amounts under the pinned rounding rule
# (annual estimate 2,210,149 = 1 mod 4, so exactly one quarter rounds up).
IL_QUARTERS = [552537, 552538, 552537, 552537]


class TestGeneratedScheduleShape:
    def test_generated_schedule_tiles_year_and_sets_due_dates(
            self, api, tax_manager_headers):
        """PRD §3.5: "The four quarters tile the fiscal year in three-month
        intervals starting at `period_start_date`, each with `due_date` set 15
        days after its `period_end_date`."
        PRD §3.5: "All four are created in `SCHEDULED` with
        `paid_amount_cents` 0 and `penalty_cents` 0."

        Design: Corner/endpoints/generate_schedule_computes_quarter_dates
        """
        ty = create_fy2026_tax_year()
        jur = create_us_il_jurisdiction()
        payments = generate_sorted_schedule(ty["id"], jur["id"],
                                            method="CURRENT_YEAR_ANNUALIZED")
        by_index = {p["quarter_index"]: p for p in payments}
        assert sorted(by_index) == [1, 2, 3, 4]

        q1 = by_index[1]
        assert q1["period_start_date"] == "2026-01-01"
        assert q1["period_end_date"] == "2026-03-31"
        assert q1["due_date"] == "2026-04-15"  # period_end + 15 days

        q4 = by_index[4]
        assert q4["period_start_date"] == "2026-10-01"
        assert q4["period_end_date"] == "2026-12-31"
        assert q4["due_date"] == "2027-01-15"  # crosses the year boundary

        for p in payments:
            assert p["status"] == "SCHEDULED"
            assert p["paid_amount_cents"] == 0
            assert p["penalty_cents"] == 0


class TestDualMethodSchedules:
    def test_current_year_annualized_amounts(
            self, api, tax_manager_headers, auditor_headers):
        """PRD §3.5: "Under `CURRENT_YEAR_ANNUALIZED`, it is
        `pretax_book_income_cents` multiplied by `apportionment_pct_bp`
        divided by 10000, then multiplied by `statutory_rate_bp` divided by
        10000, rounded half up — the pay-as-you-go view."

        Design: Difficulty/dual_variant_calc/estimated_payment_safe_harbor_vs_annualized
        """
        ty = create_fy2026_tax_year()
        jur_il = create_us_il_jurisdiction()
        payments = generate_sorted_schedule(ty["id"], jur_il["id"],
                                            method="CURRENT_YEAR_ANNUALIZED")
        # annual = round(100,000,000 * 2503 * 883 / 1e8) = 2,210,149
        assert payments[0]["scheduled_amount_cents"] == 552537
        assert payments[1]["scheduled_amount_cents"] == 552538

    def test_safe_harbor_amounts_diverge_from_annualized(
            self, api, tax_manager_headers, auditor_headers):
        """PRD §3.5: "under `PRIOR_YEAR_SAFE_HARBOR`, it is the year's
        `prior_year_total_tax_cents` multiplied by the jurisdiction's
        `apportionment_pct_bp` divided by 10000, then multiplied by 10000
        basis points (100% of prior-year tax) divided by 10000, rounded half
        up to integer cents — a conservative fixed obligation that is immune
        to later re-spreads."

        Design: Difficulty/dual_variant_calc/estimated_payment_safe_harbor_vs_annualized
        """
        set_logical_clock("2026-01-05T00:00:00Z")
        ty = create_fy2026_tax_year()
        jur_il = create_us_il_jurisdiction()
        jur_ny = create_us_ny_jurisdiction()
        il = generate_sorted_schedule(ty["id"], jur_il["id"],
                                      method="CURRENT_YEAR_ANNUALIZED")
        ny = generate_sorted_schedule(ty["id"], jur_ny["id"],
                                      method="PRIOR_YEAR_SAFE_HARBOR")

        # safe-harbor annual = round(8,000,000 * 2503 * 10000 / 1e8) = 2,002,400
        assert ny[0]["scheduled_amount_cents"] == 500600
        # Same year, same-shaped jurisdiction, different statute:
        assert il[0]["scheduled_amount_cents"] != ny[0]["scheduled_amount_cents"]


class TestCumulativeRounding:
    def test_quarter_amounts_follow_pinned_cumulative_rounding(
            self, api, tax_manager_headers):
        """PRD §3.5: "The per-quarter amounts follow a pinned rounding order:
        working in ascending `quarter_index`, each quarter's cumulative target
        is the annual estimate times the quarter number divided by 4, kept as
        an exact unrounded rational; each quarter's
        `base_scheduled_amount_cents` is the cumulative target minus the sum
        of the previously assigned quarters, rounded half up."

        Design: Difficulty/combinatorial_formula/estimated_payment_cumulative_rounding
        """
        ty = create_fy2026_tax_year()
        jur = create_us_il_jurisdiction()
        payments = generate_sorted_schedule(ty["id"], jur["id"],
                                            method="CURRENT_YEAR_ANNUALIZED")
        # targets: 552,537.25 / 1,105,074.50 / 1,657,611.75 / 2,210,149
        assert [p["scheduled_amount_cents"] for p in payments] == IL_QUARTERS
        assert [p["base_scheduled_amount_cents"] for p in payments] == \
            IL_QUARTERS

    def test_cumulative_rounding_conserves_the_annual_estimate(
            self, api, tax_manager_headers):
        """PRD §3.5: "Each quarter is therefore rounded against the exact
        cumulative target — never a quarter of the annual estimate rounded
        four times, since the two orders diverge by cents."

        Design: Difficulty/combinatorial_formula/estimated_payment_cumulative_rounding
        """
        ty = create_fy2026_tax_year()
        jur = create_us_il_jurisdiction()
        payments = generate_sorted_schedule(ty["id"], jur["id"],
                                            method="CURRENT_YEAR_ANNUALIZED")
        total = sum(p["scheduled_amount_cents"] for p in payments)
        # Cumulative rounding conserves the 2,210,149 annual estimate; naive
        # per-quarter rounding would give round(552,537.25) * 4 = 2,210,148.
        assert total == 2210149


class TestManualQuarterIntervals:
    def test_shared_boundary_day_collides_closed_interval(
            self, api, tax_manager_headers):
        """PRD §2.9: "Two manual quarters of the same `tax_year_id` and
        `jurisdiction_id` pair may not overlap, and because the intervals are
        closed, a new quarter whose start equals an existing quarter's end
        collides (`ERR_QUARTER_OVERLAP`)."

        Design: Difficulty/resource_temporal_overlap/payment_quarter_closed_interval_overlap
        """
        set_logical_clock("2026-01-05T00:00:00Z")
        ty = create_fy2026_tax_year()
        jur = create_us_il_jurisdiction()
        validate_success(api.create_estimated_payment(
            create_estimated_payment_payload(ty["id"], jur["id"]),
            tax_manager_headers), 201)

        res = api.create_estimated_payment(
            create_estimated_payment_payload(
                ty["id"], jur["id"], quarter_index=2,
                period_start_date="2026-03-31", period_end_date="2026-06-30",
                due_date="2026-07-15", scheduled_amount_cents=552538),
            tax_manager_headers)
        validate_error(res, ApiErrorId.ERR_QUARTER_OVERLAP,
                       expected_status=409)

    def test_exact_contiguity_permitted(self, api, tax_manager_headers):
        """PRD §2.9: "Manual quarters must also be exactly contiguous with no
        gaps: quarter 1 must start on the tax year's `period_start_date`, and
        any quarter with `quarter_index` greater than 1 must start the day
        after the highest existing quarter's `period_end_date` for the pair
        (`ERR_QUARTER_GAP`)."

        Design: Difficulty/resource_temporal_overlap/payment_quarter_closed_interval_overlap
        """
        set_logical_clock("2026-01-05T00:00:00Z")
        ty = create_fy2026_tax_year()
        jur = create_us_il_jurisdiction()
        validate_success(api.create_estimated_payment(
            create_estimated_payment_payload(ty["id"], jur["id"]),
            tax_manager_headers), 201)

        q2 = validate_success(api.create_estimated_payment(
            create_estimated_payment_payload(
                ty["id"], jur["id"], quarter_index=2,
                period_start_date="2026-04-01", period_end_date="2026-06-30",
                due_date="2026-07-15", scheduled_amount_cents=552538),
            tax_manager_headers), 201)
        assert q2["status"] == "SCHEDULED"
        assert q2["quarter_index"] == 2

    def test_non_contiguous_quarter_gap_rejected(self, api,
                                                 tax_manager_headers):
        """PRD §2.9: "Manual quarters must also be exactly contiguous with no
        gaps: quarter 1 must start on the tax year's `period_start_date`, and
        any quarter with `quarter_index` greater than 1 must start the day
        after the highest existing quarter's `period_end_date` for the pair
        (`ERR_QUARTER_GAP`)."

        Design: Corner/validations/manual_quarter_gap_rejected
        """
        ty = create_fy2026_tax_year()
        jur = create_us_il_jurisdiction()
        validate_success(api.create_estimated_payment(
            create_estimated_payment_payload(ty["id"], jur["id"]),
            tax_manager_headers), 201)

        res = api.create_estimated_payment(
            create_estimated_payment_payload(
                ty["id"], jur["id"], quarter_index=3,
                period_start_date="2026-07-01", period_end_date="2026-09-30",
                due_date="2026-10-15"),
            tax_manager_headers)
        validate_error(res, ApiErrorId.ERR_QUARTER_GAP, expected_status=422)

    def test_duplicate_schedule_generation_rejected(
            self, api, tax_manager_headers, auditor_headers):
        """PRD §3.5: "Generation requires zero existing payments for the pair
        — `ERR_DUPLICATE_QUARTER` otherwise."

        Design: Corner/validations/duplicate_schedule_generation_rejected
        """
        set_logical_clock("2026-01-05T00:00:00Z")
        ty = create_fy2026_tax_year()
        jur = create_us_il_jurisdiction()
        generate_sorted_schedule(ty["id"], jur["id"],
                                 method="CURRENT_YEAR_ANNUALIZED")

        res = api.generate_payment_schedule(
            create_generate_schedule_payload(
                ty["id"], jur["id"], method="PRIOR_YEAR_SAFE_HARBOR"),
            tax_manager_headers)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_QUARTER,
                       expected_status=409)

        data, meta = validate_paginated(api.list_estimated_payments(
            auditor_headers,
            params={"tax_year_id": ty["id"], "jurisdiction_id": jur["id"]}))
        assert len(data) == 4
        assert meta["total_count"] == 4


class TestRecordAndReverse:
    def test_record_then_reverse_restores_scheduled_state(
            self, api, tax_accountant_headers, tax_manager_headers):
        """PRD §3.5: "From `PARTIALLY_PAID`, the reversal amount must be
        positive and no more than the paid total (`ERR_INVALID_AMOUNT`
        otherwise); when the paid total returns to zero the quarter returns to
        `SCHEDULED`."
        PRD §3.5: "The record/reverse pair conserves `paid_amount_cents`
        across the two motions."

        Design: Difficulty/compensating_invariant/payment_record_reverse_conserves_paid
        """
        set_logical_clock("2026-01-05T00:00:00Z")
        _, _, payments = setup_year_with_annualized_schedule()
        q1 = payments[0]

        recorded = validate_success(
            api.record_payment(q1["id"], 200000, tax_accountant_headers), 200)
        assert recorded["paid_amount_cents"] == 200000
        assert recorded["status"] == "PARTIALLY_PAID"

        reversed_back = validate_success(
            api.reverse_payment(q1["id"], 200000, tax_manager_headers), 200)
        assert reversed_back["paid_amount_cents"] == 0
        assert reversed_back["status"] == "SCHEDULED"

    def test_reversal_never_touches_the_schedule(
            self, api, tax_accountant_headers, tax_manager_headers):
        """PRD §3.5: "Reversing a payment is a `TaxManager` compensating
        action, also carrying `amount_cents`, subtracted from
        `paid_amount_cents`."
        PRD §3.5: "the supplied amount also becomes the immutable
        `base_scheduled_amount_cents` anchor."

        Design: Difficulty/compensating_invariant/payment_record_reverse_conserves_paid
        """
        set_logical_clock("2026-01-05T00:00:00Z")
        _, _, payments = setup_year_with_annualized_schedule()
        q1 = payments[0]

        validate_success(
            api.record_payment(q1["id"], 200000, tax_accountant_headers), 200)
        reversed_back = validate_success(
            api.reverse_payment(q1["id"], 200000, tax_manager_headers), 200)

        assert reversed_back["scheduled_amount_cents"] == 552537, \
            "the reversal never touches the schedule"
        assert reversed_back["base_scheduled_amount_cents"] == 552537

    def test_record_payment_amounts_validation(self, api,
                                               tax_accountant_headers):
        """PRD §3.5: "A payment that would push the paid total above the
        scheduled amount is rejected with `ERR_OVERPAYMENT`, a non-positive
        amount with `ERR_INVALID_AMOUNT`, and any record-payment attempt on an
        already-`PAID` quarter with `ERR_PAYMENT_ALREADY_SETTLED` rather than
        the generic state error."

        Design: Corner/validations/record_payment_overpay_rejected
        """
        set_logical_clock("2026-01-05T00:00:00Z")
        _, _, payments = setup_year_with_annualized_schedule()
        q1 = payments[0]

        res = api.record_payment(q1["id"], 552538, tax_accountant_headers)
        validate_error(res, ApiErrorId.ERR_OVERPAYMENT, expected_status=422)

        after = get_estimated_payment(q1["id"])
        assert after["paid_amount_cents"] == 0
        assert after["status"] == "SCHEDULED"

    def test_record_payment_zero_amount_rejected(self, api,
                                                 tax_accountant_headers):
        """PRD §3.5: "A payment that would push the paid total above the
        scheduled amount is rejected with `ERR_OVERPAYMENT`, a non-positive
        amount with `ERR_INVALID_AMOUNT`, and any record-payment attempt on an
        already-`PAID` quarter with `ERR_PAYMENT_ALREADY_SETTLED` rather than
        the generic state error."

        Design: Corner/validations/record_payment_zero_amount_rejected
        """
        set_logical_clock("2026-01-05T00:00:00Z")
        _, _, payments = setup_year_with_annualized_schedule()
        q1 = payments[0]

        res = api.record_payment(q1["id"], 0, tax_accountant_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_AMOUNT, expected_status=422)

    def test_record_payment_unknown_id_not_found(self, api,
                                                 tax_accountant_headers):
        """PRD §2.6: "**Existence** — path identifiers exist, validated left
        to right, and body foreign-key references (`tax_year_id`,
        `jurisdiction_id`, `audit_case_id`) resolve to existing resources
        (`ERR_NOT_FOUND`)."

        Design: Corner/validations/record_payment_unknown_id_returns_not_found
        """
        res = api.record_payment(NON_EXISTENT_UUID, 1000,
                                 tax_accountant_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestLateSweep:
    def test_fully_paid_quarter_never_enters_late(
            self, api, tax_accountant_headers, auditor_headers):
        """PRD §3.5: "Because the sweep's condition is strict, a quarter paid
        to exactly its scheduled amount is `PAID` and never enters `LATE`"
        PRD §2.5: "Threshold comparisons are exact: the UTP recognition
        threshold uses a strictly-greater-than comparison, and the
        late-payment sweep condition is strict, so an exactly-fully-paid
        quarter owes zero penalty."

        Design: Difficulty/boundary_precision_check/payment_paid_in_full_vs_shortfall_at_sweep
        """
        set_logical_clock("2026-01-05T00:00:00Z")
        _, _, payments = setup_year_with_annualized_schedule()
        q1, q2 = payments[0], payments[1]
        # q1 paid in full (552,537 == scheduled); q2 short by 1,000.
        validate_success(api.record_payment(q1["id"], 552537,
                                            tax_accountant_headers), 200)
        validate_success(api.record_payment(q2["id"], 551538,
                                            tax_accountant_headers), 200)

        clock_data = set_logical_clock("2026-07-16T00:00:00Z")
        assert q1["id"] not in clock_data["late_payment_ids"]

        q1_after = get_estimated_payment(q1["id"])
        assert q1_after["status"] == "PAID"
        assert q1_after["penalty_cents"] == 0

    def test_shortfall_quarter_enters_late_with_penalty(
            self, api, tax_accountant_headers, auditor_headers):
        """PRD §3.5: "when the clock date passes `due_date` and
        `paid_amount_cents` is strictly less than `scheduled_amount_cents`,
        the quarter transitions to `LATE` and is assessed, exactly once,
        `penalty_cents` equal to the shortfall (`scheduled_amount_cents` minus
        `paid_amount_cents`) multiplied by 400 basis points (4%) and divided
        by 10000, rounded half up to integer cents."

        Design: Difficulty/boundary_precision_check/payment_paid_in_full_vs_shortfall_at_sweep
        """
        set_logical_clock("2026-01-05T00:00:00Z")
        _, _, payments = setup_year_with_annualized_schedule()
        q1, q2 = payments[0], payments[1]
        validate_success(api.record_payment(q1["id"], 552537,
                                            tax_accountant_headers), 200)
        validate_success(api.record_payment(q2["id"], 551538,
                                            tax_accountant_headers), 200)

        clock_data = set_logical_clock("2026-07-16T00:00:00Z")
        assert q2["id"] in clock_data["late_payment_ids"]

        q2_after = get_estimated_payment(q2["id"])
        assert q2_after["status"] == "LATE"
        # shortfall 1,000 -> round_half_up(1,000 * 400 / 10000) = 40
        assert q2_after["penalty_cents"] == 40

    def test_late_payoff_completes_quarter_and_keeps_penalty(
            self, api, tax_accountant_headers, auditor_headers):
        """PRD §3.5: "a penalty once assessed is never refunded, even by later
        payments or reversals — from `LATE`, recording the exact remaining
        balance still completes the quarter to `PAID` with `penalty_cents`
        untouched."

        Design: Corner/state_machines/payment_late_payoff_keeps_penalty
        """
        set_logical_clock("2026-01-05T00:00:00Z")
        _, _, payments = setup_year_with_annualized_schedule()
        q1 = payments[0]
        validate_success(api.record_payment(q1["id"], 500000,
                                            tax_accountant_headers), 200)
        set_logical_clock("2026-04-16T00:00:00Z")

        late = get_estimated_payment(q1["id"])
        assert late["status"] == "LATE"
        # shortfall 52,537 -> round_half_up(52,537 * 400 / 10000) = 2,101
        assert late["penalty_cents"] == 2101

        paid_off = validate_success(
            api.record_payment(q1["id"], 52537, tax_accountant_headers), 200)
        assert paid_off["status"] == "PAID"
        assert paid_off["paid_amount_cents"] == 552537
        assert paid_off["penalty_cents"] == 2101, "penalty is never refunded"


class TestStateBeatsFiscalOverpayment:
    def _setup_paid_quarter(self, api, accountant_headers):
        set_logical_clock("2026-01-05T00:00:00Z")
        _, _, payments = setup_year_with_annualized_schedule()
        q1 = payments[0]
        paid = validate_success(
            api.record_payment(q1["id"], 552537, accountant_headers), 200)
        assert paid["status"] == "PAID"
        return q1

    def test_payment_on_paid_quarter_surfaces_settled_error(
            self, api, tax_accountant_headers):
        """PRD §2.6: "**State transition legality** — the target entity is in
        a state from which the requested transition exists; recording a
        payment on an already-`PAID` quarter surfaces
        `ERR_PAYMENT_ALREADY_SETTLED`, and every other illegal transition
        surfaces `ERR_INVALID_STATE_TRANSITION`."
        PRD §2.6: "When a single request violates more than one rule, the
        lowest priority number wins and determines the response's `error_id`."

        Design: Difficulty/priority_pair_validation_conflict/payment_state_beats_fiscal_overpayment
        """
        q1 = self._setup_paid_quarter(api, tax_accountant_headers)

        # 552,537 + 1 > 552,537 also violates the overpayment cap, but the
        # state error (priority 4) beats amount sanity (priority 10).
        res = api.record_payment(q1["id"], 1, tax_accountant_headers)
        error = validate_error(res, ApiErrorId.ERR_PAYMENT_ALREADY_SETTLED,
                               expected_status=409)
        assert error["error_id"] != "ERR_OVERPAYMENT"

    def test_rejected_settled_payment_leaves_quarter_untouched(
            self, api, tax_accountant_headers):
        """PRD §3.5: "any record-payment attempt on an already-`PAID` quarter
        with `ERR_PAYMENT_ALREADY_SETTLED` rather than the generic state
        error."

        Design: Difficulty/priority_pair_validation_conflict/payment_state_beats_fiscal_overpayment
        """
        q1 = self._setup_paid_quarter(api, tax_accountant_headers)

        validate_error(
            api.record_payment(q1["id"], 1, tax_accountant_headers),
            ApiErrorId.ERR_PAYMENT_ALREADY_SETTLED, expected_status=409)

        after = get_estimated_payment(q1["id"])
        assert after["status"] == "PAID"
        assert after["paid_amount_cents"] == 552537
        assert after["penalty_cents"] == 0
