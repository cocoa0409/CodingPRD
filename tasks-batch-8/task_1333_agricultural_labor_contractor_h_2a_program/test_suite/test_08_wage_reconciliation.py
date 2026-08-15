"""Wage reconciliation: provisional vs final variants, pinned per-day rounding,
the three-quarters guarantee, transportation thresholds, and order close-out."""
from test_helpers import (
    ApiErrorId,
    J1_WORKDAYS_0901_TO_0911,
    TEST_USERS,
    create_work_log,
    create_work_logs,
    end_assignment,
    get_reconciliation,
    get_success_data,
    set_clock,
    setup_active_order_pipeline,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["contractor_admin_headers"]


def _j1_working_with_logs(units, log_dates=J1_WORKDAYS_0901_TO_0911, clock="2026-09-11T00:00:00Z"):
    s = setup_active_order_pipeline(passports=("P0001",))
    asg = s["assignments"]["P0001"]
    set_clock(clock)
    create_work_logs(asg["id"], log_dates, 8, units)
    return s, asg


class TestProvisionalVsFinalDivergence:
    def test_provisional_variant_values_before_end(self, api):
        """PRD 3.7: "While the reconciliation is `OPEN` — the provisional variant —
        it recomputes on every work-log creation and on assignment start, end, and
        transfer-finalization; it accrues through `computed_through_date`, assumes
        the guarantee applies, owes no outbound transport, and applies the inbound
        threshold rule to the current horizon."
        PRD 3.7: "`inbound_transport_owed_cents` equals the order's
        `inbound_transport_cents` once `computed_through_date` has reached the
        order's `transport_threshold_date` — reaching it exactly counts — provided
        the reconciliation is still `OPEN` or, if finalized, the assignment's
        `end_reason` is anything other than `ABANDONED`; in every other case it is
        zero."

        Design: Difficulty/dual_variant_calc/wage_reconciliation_provisional_vs_final_divergence
        """
        s, asg = _j1_working_with_logs(units=25)

        rec = get_reconciliation(asg["id"])
        assert rec["status"] == "OPEN"
        assert rec["computed_through_date"] == "2026-09-11"
        # 10 workdays x 25 units x 450 (week1 150 units, week2 100 units so far).
        assert rec["piece_earnings_cents"] == 112500
        # 10 days x round_half_up(32 quarters x 1850 / 4) = 10 x 14800.
        assert rec["hourly_floor_earnings_cents"] == 148000
        assert rec["makeup_pay_cents"] == 35500  # (88800-67500) + (59200-45000)
        # Basis 2026-09-01..2026-09-11 = 10 workdays; 320 quarters, 3/4 -> 240.
        assert rec["guarantee_basis_workdays"] == 10
        assert rec["guaranteed_quarters"] == 240
        assert rec["worked_quarters"] == 320
        assert rec["shortfall_quarters"] == 0
        assert rec["guarantee_pay_cents"] == 0
        # 2026-09-11 is before the 2026-09-25 transport threshold.
        assert rec["inbound_transport_owed_cents"] == 0
        assert rec["outbound_transport_owed_cents"] == 0
        assert rec["total_due_cents"] == 148000

    def test_final_variant_adds_outbound_transport(self, api):
        """PRD 3.7: "Finalizing — allowed only when the parent assignment has
        reached `COMPLETED`, `TERMINATED`, or `TRANSFERRED_OUT` and the row is
        still `OPEN`, with any other combination rejected as
        `ERR_RECONCILIATION_INVALID_STATE` — freezes the final variant: the horizon
        is pinned to `ended_on`, `guarantee_applied` is decided from the recorded
        `end_reason`, outbound transport is owed per the completion rule, the row
        moves to `FINALIZED`, and `finalized_on` is stamped with the clock date."
        PRD 3.7: "`outbound_transport_owed_cents` equals the order's
        `outbound_transport_cents` only for a `FINALIZED` reconciliation whose
        assignment ended `COMPLETED`, and is zero otherwise. The row's
        `total_due_cents` is the sum of piece earnings, make-up pay, guarantee pay,
        and the two transport amounts."

        Design: Difficulty/dual_variant_calc/wage_reconciliation_provisional_vs_final_divergence
        """
        s, asg = _j1_working_with_logs(units=25)
        provisional_total = get_reconciliation(asg["id"])["total_due_cents"]

        end_assignment(asg["id"], "COMPLETED")
        rec = validate_success(api.finalize_reconciliation(asg["id"], ADMIN), 200)

        assert rec["status"] == "FINALIZED"
        assert rec["finalized_on"] == "2026-09-11"
        assert rec["computed_through_date"] == "2026-09-11"
        assert rec["piece_earnings_cents"] == 112500
        assert rec["makeup_pay_cents"] == 35500
        assert rec["guarantee_pay_cents"] == 0
        assert rec["guarantee_applied"] is True
        assert rec["inbound_transport_owed_cents"] == 0
        assert rec["outbound_transport_owed_cents"] == 75000
        assert rec["total_due_cents"] == 223000
        # The variants diverge by exactly the outbound transport owed only when final.
        assert rec["total_due_cents"] - provisional_total == 75000


class TestMultiInputBranchCombination:
    def _finalized_full_period_recon(self, api):
        s, asg = _j1_working_with_logs(units=30)
        set_clock("2026-10-21T00:00:00Z")
        end_assignment(asg["id"], "COMPLETED")
        return validate_success(api.finalize_reconciliation(asg["id"], ADMIN), 200)

    def test_piece_floor_and_makeup_terms(self, api):
        """PRD 3.7: "The week's make-up pay is the amount by which the weekly floor
        exceeds the weekly piece earnings, or zero when piece earnings meet or beat
        the floor. Across all intersecting weeks, the piece earnings sum to
        `piece_earnings_cents`, the floor earnings sum to
        `hourly_floor_earnings_cents`, and the make-up pay sums to
        `makeup_pay_cents`"

        Design: Difficulty/combinatorial_formula/wage_recon_multi_input_state_branch_mode_a
        """
        rec = self._finalized_full_period_recon(api)
        # 10 days x 30 units x 450: week1 180 units, week2 120 units.
        assert rec["piece_earnings_cents"] == 135000
        assert rec["hourly_floor_earnings_cents"] == 148000  # 10 x 14800
        # week1 max(0, 88800-81000)=7800; week2 max(0, 59200-54000)=5200.
        assert rec["makeup_pay_cents"] == 13000

    def test_guarantee_transports_and_total(self, api):
        """PRD 3.7: "The guaranteed quarter-hours, `guaranteed_quarters`, are the
        basis workdays multiplied by the order's `daily_standard_hours`, converted
        to quarter-hours, then scaled by three-quarters with the result rounded
        down to a whole quarter-hour — an odd quarter count truncates downward."
        PRD 3.7: "Its basis window runs from the later of the order's
        `work_start_date` and the assignment's `started_on` through the earlier of
        the order's `work_end_date` and the reconciliation's
        `computed_through_date`"
        PRD 3.7: "The row's `total_due_cents` is the sum of piece earnings, make-up
        pay, guarantee pay, and the two transport amounts."

        Design: Difficulty/combinatorial_formula/wage_recon_multi_input_state_branch_mode_a
        """
        rec = self._finalized_full_period_recon(api)
        # Basis capped at the order end 2026-10-20: 43 workdays; 43*32=1376
        # quarter-hours; floor(1376*3/4) = 1032 guaranteed.
        assert rec["guarantee_basis_workdays"] == 43
        assert rec["guaranteed_quarters"] == 1032
        assert rec["worked_quarters"] == 320
        assert rec["shortfall_quarters"] == 712
        assert rec["guarantee_pay_cents"] == 329300  # round_half_up(712 x 1850 / 4)
        assert rec["guarantee_applied"] is True
        assert rec["inbound_transport_owed_cents"] == 60000
        assert rec["outbound_transport_owed_cents"] == 75000
        assert rec["total_due_cents"] == 612300


class TestPrecisionAndThresholds:
    def test_wage_recon_per_day_rounding_order_pinned(self, api):
        """PRD 3.7: "The weekly floor earnings are built day by day: each day's
        `hours_worked` (zero for days with no log) is multiplied by the order's
        `required_hourly_floor_cents`, and that per-day product is rounded half-up
        to a whole cent before the week's days are summed. The rounding order is
        pinned — round each day first, then sum within the week; summing hours
        first and rounding once produces different cents and is non-conformant."
        PRD 3.6: "`units_picked` must be zero or greater, and it must be exactly 0
        whenever the order's `effective_piece_rate_cents_per_unit` is null — piece
        counts are meaningless without a piece rate (violations surface as
        `ERR_INVALID_REQUEST`)."

        Design: Corner/calculations/wage_recon_per_day_rounding_order_pinned
        """
        s = setup_active_order_pipeline(
            passports=("P0001",),
            hourly_only=True,
            order_overrides={
                "title": "Chile harvest", "crop": "CHILE", "work_end_date": "2026-09-20",
                "workers_requested": 1, "offered_hourly_cents": 725,
                "offered_piece_rate_cents_per_unit": None,
                "inbound_transport_cents": 0, "outbound_transport_cents": 0,
            },
        )
        asg = s["assignments"]["P0001"]
        assert s["order"]["required_hourly_floor_cents"] == 725
        assert s["order"]["effective_piece_rate_cents_per_unit"] is None

        create_work_log(asg["id"], "2026-09-01", 1.25, 0)
        set_clock("2026-09-02T00:00:00Z")

        # Piece units are meaningless on an hourly-only order.
        resp = api.create_work_log(
            {"worker_assignment_id": asg["id"], "work_date": "2026-09-02",
             "hours_worked": 2, "units_picked": 5},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        create_work_log(asg["id"], "2026-09-02", 1.25, 0)

        rec = get_reconciliation(asg["id"])
        # Each 1.25h day: round_half_up(5 quarters x 725 / 4) = 906 cents;
        # summed per week: 906 + 906 = 1812 (sum-then-round would give 1813).
        assert rec["hourly_floor_earnings_cents"] == 1812
        assert rec["piece_earnings_cents"] == 0
        assert rec["makeup_pay_cents"] == 1812
        # Basis 2026-09-01..2026-09-02 = 2 workdays; 64 quarters; floor(64*3/4)=48.
        assert rec["guarantee_basis_workdays"] == 2
        assert rec["guaranteed_quarters"] == 48
        assert rec["worked_quarters"] == 10
        assert rec["shortfall_quarters"] == 38
        assert rec["guarantee_pay_cents"] == 6888  # round_half_up(38 x 725 / 4)
        assert rec["total_due_cents"] == 8700

    def test_inbound_transport_owed_exactly_at_threshold(self, api):
        """PRD 3.7: "`inbound_transport_owed_cents` equals the order's
        `inbound_transport_cents` once `computed_through_date` has reached the
        order's `transport_threshold_date` — reaching it exactly counts — provided
        the reconciliation is still `OPEN` or, if finalized, the assignment's
        `end_reason` is anything other than `ABANDONED`; in every other case it is
        zero."
        PRD 3.7: "`outbound_transport_owed_cents` equals the order's
        `outbound_transport_cents` only for a `FINALIZED` reconciliation whose
        assignment ended `COMPLETED`, and is zero otherwise."

        Design: Corner/calculations/inbound_transport_owed_exactly_at_threshold
        """
        s = setup_active_order_pipeline(passports=("P0001",))
        asg = s["assignments"]["P0001"]
        create_work_log(asg["id"], "2026-09-01", 8, 25)
        set_clock("2026-09-25T00:00:00Z")
        end_assignment(asg["id"], "COMPLETED")

        rec = validate_success(api.finalize_reconciliation(asg["id"], ADMIN), 200)
        # The J1 transport threshold is 2026-09-25; ending exactly on it owes inbound.
        assert rec["computed_through_date"] == "2026-09-25"
        assert rec["inbound_transport_owed_cents"] == 60000
        assert rec["outbound_transport_owed_cents"] == 75000
        # Basis 2026-09-01..2026-09-25 = 22 workdays; 704 quarters -> 528 guaranteed.
        assert rec["guarantee_basis_workdays"] == 22
        assert rec["guaranteed_quarters"] == 528
        assert rec["worked_quarters"] == 32
        assert rec["shortfall_quarters"] == 496
        assert rec["guarantee_pay_cents"] == 229400  # round_half_up(496 x 1850 / 4)
        assert rec["piece_earnings_cents"] == 11250
        assert rec["makeup_pay_cents"] == 3550
        assert rec["total_due_cents"] == 379200

    def test_provisional_reconciliation_visible_at_start(self, api):
        """PRD 3.7: "Every started assignment owns exactly one wage reconciliation,
        created automatically at start; reading an assignment's reconciliation
        yields an array containing zero rows (before start) or one."
        PRD 3.6: "Starting stamps `started_on` with the clock date, moves the
        assignment to `ACTIVE`, moves the worker from `VISA_ISSUED` to `WORKING`,
        and creates the assignment's one-to-one wage reconciliation in `OPEN`
        status with the provisional variant of §3.7 already computed."

        Design: Corner/calculations/provisional_reconciliation_visible_at_start
        """
        s = setup_active_order_pipeline(passports=("P0001",))
        asg = s["assignments"]["P0001"]

        rec = get_reconciliation(asg["id"])
        assert rec["status"] == "OPEN"
        assert rec["computed_through_date"] == "2026-09-01"
        # Basis is the single workday 2026-09-01: 32 quarters, 3/4 -> 24.
        assert rec["guarantee_basis_workdays"] == 1
        assert rec["guaranteed_quarters"] == 24
        assert rec["worked_quarters"] == 0
        assert rec["shortfall_quarters"] == 24
        assert rec["guarantee_pay_cents"] == 11100  # round_half_up(24 x 1850 / 4)
        assert rec["piece_earnings_cents"] == 0
        assert rec["makeup_pay_cents"] == 0
        assert rec["inbound_transport_owed_cents"] == 0
        assert rec["outbound_transport_owed_cents"] == 0
        assert rec["total_due_cents"] == 11100


class TestOrderCloseOut:
    def test_order_close_finalize_guard_sequence(self, api):
        """PRD 3.7: "A `ContractorAdmin` closes the work period once the order is
        `ACTIVE` (else `ERR_JOB_ORDER_INVALID_STATE`), the clock date has reached
        `work_end_date` (else `ERR_ORDER_PERIOD_NOT_ENDED`), and every worker
        assignment of the order has reached `COMPLETED`, `TERMINATED`, or
        `TRANSFERRED_OUT` (else `ERR_OPEN_ASSIGNMENTS_REMAIN`); the order moves to
        `CLOSING`. Finalizing the order requires `CLOSING` (else
        `ERR_JOB_ORDER_INVALID_STATE`) and requires the wage reconciliation of
        every assignment of the order to be `FINALIZED` (else
        `ERR_UNFINALIZED_RECONCILIATIONS_REMAIN`); the order then reaches its
        terminal `CLOSED` state."

        Design: Corner/errors/order_close_finalize_guard_sequence
        """
        s = setup_active_order_pipeline(passports=("P0001",))
        jo, asg = s["order"], s["assignments"]["P0001"]

        # Clock before work_end_date: period not ended.
        set_clock("2026-10-19T00:00:00Z")
        validate_error(api.close_job_order(jo["id"], ADMIN), ApiErrorId.ERR_ORDER_PERIOD_NOT_ENDED)

        # Period ended but the assignment is still ACTIVE.
        set_clock("2026-10-21T00:00:00Z")
        validate_error(api.close_job_order(jo["id"], ADMIN), ApiErrorId.ERR_OPEN_ASSIGNMENTS_REMAIN)

        end_assignment(asg["id"], "COMPLETED")
        # A terminal assignment cannot be ended again.
        validate_error(
            api.end_worker_assignment(asg["id"], {"end_reason": "COMPLETED"}, ADMIN),
            ApiErrorId.ERR_ASSIGNMENT_INVALID_STATE,
        )

        closing = validate_success(api.close_job_order(jo["id"], ADMIN), 200)
        assert closing["status"] == "CLOSING"

        # Reconciliation still OPEN: order finalize blocked.
        validate_error(api.finalize_job_order(jo["id"], ADMIN), ApiErrorId.ERR_UNFINALIZED_RECONCILIATIONS_REMAIN)

        rec = validate_success(api.finalize_reconciliation(asg["id"], ADMIN), 200)
        assert rec["status"] == "FINALIZED"
        # A FINALIZED reconciliation cannot be finalized again.
        validate_error(api.finalize_reconciliation(asg["id"], ADMIN), ApiErrorId.ERR_RECONCILIATION_INVALID_STATE)

        closed = validate_success(api.finalize_job_order(jo["id"], ADMIN), 200)
        assert closed["status"] == "CLOSED"
        assert get_success_data(api.get_job_order(jo["id"], ADMIN))["status"] == "CLOSED"
