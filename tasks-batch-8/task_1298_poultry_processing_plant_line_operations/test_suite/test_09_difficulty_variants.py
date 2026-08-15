"""Second-coverage tests for difficulty instances: each probes the same design
instance from a different angle (different state, endpoint read, or metric)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    create_utility_reading_payload, create_flock_lot_payload,
    create_condemnation_record_payload, create_waiver_payload,
    create_line_run_payload, create_deboning_batch_payload, create_order_payload,
    make_line, make_shift, fully_staffed_shift, book_and_receive_lot, queue_run,
    open_shift, set_clock, create_passed_preop, make_order, make_batch,
    setup_running_shift_with_run, setup_completed_run, setup_chilled_lot,
    setup_settled_lot, setup_trace_locked_lot, setup_production_line_for_deboning,
    complete_run,
    make_qa_technician_headers, make_usda_inspector_headers,
    TEST_USERS,
)

PM = TEST_USERS["plant_manager_headers"]
SUP = TEST_USERS["shift_supervisor_headers"]
RCV = TEST_USERS["receiving_clerk_headers"]
OP = TEST_USERS["line_operator_headers"]
QA = TEST_USERS["qa_technician_headers"]
PLAN = TEST_USERS["order_planner_headers"]


class TestYieldDivergenceAngles:

    def test_provisional_yield_excludes_certified_counts(self, api):
        """PRD §3.4: "It is an eviscerated-basis estimate: take the lot's
        `birds_hung_total` minus the provisional condemnation count (the sum of
        `effective_count` over records in `DRAFT` or `DISPUTED`), multiply by
        the eviscerated-basis allowance — 0.88 times the average live weight
        per bird, where the average live weight is the lot's
        `total_live_weight_lb` divided by its `head_count_received` — divide by
        `total_live_weight_lb`, multiply by 100 to express a percentage, and
        round half-up to two decimal places."

        Design: Difficulty/dual_variant_calc/flock_yield_provisional_vs_certified_diverge
        """
        env = setup_completed_run(completion_clock=None, condemnation=100,
                                  condemn_user_id="qa-1")
        # Before certification: provisional uses the DRAFT count of 100.
        lot = get_success_data(api.get_flock_lot(env["lot"]["id"], PM))
        assert lot["provisional_yield_pct"] == pytest.approx(86.68)

        # First certification (DRAFT->CERTIFIED) is not among the provisional
        # variant's recompute triggers in PRD 3.4 ("recomputed at each run
        # completion and on every condemnation create, dispute, or recertify
        # while condemnations remain uncertified"), so the provisional figure
        # stays at its last computed value of 86.68.
        get_success_data(api.advance_condemnation_record(
            env["record"]["id"], {"to_status": "CERTIFIED"},
            make_usda_inspector_headers("usda-1")))
        lot = get_success_data(api.get_flock_lot(env["lot"]["id"], PM))
        assert lot["provisional_yield_pct"] == pytest.approx(86.68)
        # Certified variant is null until the first settle.
        assert lot["certified_yield_pct"] is None

    def test_certified_yield_recomputes_on_reopen_recertify(self, api):
        """PRD §3.8: "While the lot is `REOPENED`, its condemnation records may
        be disputed and recertified as described in §3.4, and each
        certification change recomputes `certified_yield_pct`".
        PRD §3.4: "The regrade cycle runs through dispute and recertification."

        Design: Difficulty/dual_variant_calc/flock_yield_provisional_vs_certified_diverge
        """
        env = setup_completed_run(completion_clock="2026-08-01T06:00:00Z",
                                  condemnation=100, condemn_user_id="qa-1")
        get_success_data(api.advance_condemnation_record(
            env["record"]["id"], {"to_status": "CERTIFIED"},
            make_usda_inspector_headers("usda-1")))
        set_clock("2026-08-01T10:00:00Z")
        settled = validate_success(api.advance_flock_lot(
            env["lot"]["id"], {"to_status": "SETTLED"}, SUP))
        assert settled["certified_yield_pct"] == pytest.approx(71.28)

        # Reopen and dispute the record: certified count empties, yield -> 72.0
        get_success_data(api.advance_flock_lot(
            env["lot"]["id"], {"to_status": "REOPENED"},
            make_usda_inspector_headers("usda-1")))
        get_success_data(api.advance_condemnation_record(
            env["record"]["id"], {"to_status": "DISPUTED",
                                  "reason": "regrade requested"}, PM))
        lot = get_success_data(api.get_flock_lot(env["lot"]["id"], PM))
        assert lot["certified_yield_pct"] == pytest.approx(72.0)

        # Recertify with amendment 120: yield recomputes to the amended figure.
        get_success_data(api.advance_condemnation_record(
            env["record"]["id"], {"to_status": "CERTIFIED",
                                  "amended_carcass_count": 120},
            make_usda_inspector_headers("usda-1")))
        lot = get_success_data(api.get_flock_lot(env["lot"]["id"], PM))
        # (36000 - 120 * (36000/9950)) / 50000 * 100 == 71.13
        assert lot["certified_yield_pct"] == pytest.approx(71.13)


class TestWaterDivergenceAngles:

    def test_weight_basis_rate_reported_alongside_compliant_birds_basis(self, api):
        """PRD §3.5: "The weight-basis rate, `water_rate_weight_basis`, is
        `process_water_gallons` multiplied by 100 and divided by
        `chilled_weight_lb` — null while `chilled_weight_lb` is zero."
        PRD §3.5: "The flag `water_breach_active` is true exactly when the
        birds-basis rate is strictly greater than the 1500.0
        gallons-per-1000-birds limit of §2.8 — a rate exactly equal to the
        limit is compliant."

        Design: Difficulty/dual_variant_calc/water_intensity_birds_vs_weight_basis_diverge
        """
        env = setup_completed_run(completion_clock=None)
        # 10000 gal: birds basis 1005.03 (compliant), weight basis 27.78
        get_success_data(api.create_utility_reading(
            create_utility_reading_payload(env["shift"]["id"], gallons=10000.0), QA))
        shift = get_success_data(api.get_shift(env["shift"]["id"], QA))
        assert shift["water_rate_birds_basis"] == pytest.approx(1005.03)
        assert shift["water_rate_weight_basis"] == pytest.approx(27.78)
        assert shift["water_breach_active"] is False
        assert shift["status"] == "RUNNING"  # compliant basis leaves the shift running

    def test_chiller_limit_breach_blocks_fresh_without_suspending(self, api):
        """PRD §2.8: "Chiller water is tracked separately, on the birds basis
        only, against a limit of 800.0 gallons per 1000 birds; a breached
        chiller limit does not suspend the shift but blocks fresh routing of
        finished lots at trace-lock."
        PRD §3.5: "Independently, `chiller_limit_breached` is true when
        `chiller_water_gallons` multiplied by 1000 and divided by
        `birds_processed` is strictly greater than the 800.0 chiller limit; it
        does not suspend the shift but blocks fresh routing at trace-lock."

        Design: Difficulty/dual_variant_calc/water_intensity_birds_vs_weight_basis_diverge
        """
        env = setup_completed_run(completion_clock=None)
        # 9000 gal chiller over 9950 birds -> 904.52 > 800: breach flag, no suspension
        get_success_data(api.create_utility_reading(
            create_utility_reading_payload(env["shift"]["id"],
                                           meter_type="CHILLER_WATER",
                                           gallons=9000.0), QA))
        shift = get_success_data(api.get_shift(env["shift"]["id"], QA))
        assert shift["chiller_limit_breached"] is True
        assert shift["status"] == "RUNNING"  # chiller breach never suspends


class TestSpeedCeilingAngles:

    def test_waiver_raises_ceiling_only_while_active(self, api):
        """PRD §3.1: "Fourth, a regulatory cap is selected: the `max_speed_bpm`
        of the line's waiver in `ACTIVE` status whose half-open window covers
        the current logical time, or, when no active waiver applies, the
        regulatory base cap — 175 birds per minute for an `EVISCERATION` line
        and 45 birds-equivalent per minute for a `DEBONING` line."
        PRD §3.4: "a speed change supplies `new_speed_bpm`, requires the
        enclosing shift in `RUNNING`, and is authorized when the new speed is
        no greater than the effective maximum — equality allowed — else
        `ERR_LINE_SPEED_NOT_AUTHORIZED`."

        Design: Difficulty/combinatorial_formula/effective_speed_nested_min_waiver_staffing
        """
        # No waiver: ceiling is min(200 rated, 175 base, 200 staffing) == 175
        env = setup_running_shift_with_run()
        rid = env["run"]["id"]
        ok = validate_success(api.set_line_run_speed(rid, {"new_speed_bpm": 175}, OP))
        assert ok["current_speed_bpm"] == 175
        resp = api.set_line_run_speed(rid, {"new_speed_bpm": 176}, OP)
        validate_error(resp, ApiErrorId.ERR_LINE_SPEED_NOT_AUTHORIZED)

    def test_waiver_future_window_does_not_raise_ceiling(self, api):
        """PRD §3.1: "An `APPROVED` waiver becomes `ACTIVE` by the system once
        the logical clock reaches `effective_from` while remaining earlier than
        `effective_to` (evaluated on clock-set and lazily on waiver and speed
        reads), and from that moment the line's effective speed ceiling uses
        the waiver's `max_speed_bpm`."
        PRD §3.4: "a speed change supplies `new_speed_bpm`, requires the
        enclosing shift in `RUNNING`, and is authorized when the new speed is
        no greater than the effective maximum — equality allowed — else
        `ERR_LINE_SPEED_NOT_AUTHORIZED`."

        Design: Difficulty/combinatorial_formula/staffing_speed_evaluation_order_pinned
        """
        # Waiver window entirely in the future relative to the default clock:
        # it is APPROVED but not ACTIVE, so the base cap 175 still governs
        # even at full staffing (ratio 1.0) — the regulatory-cap step selects
        # the base cap whenever no ACTIVE waiver covers now.
        env = setup_running_shift_with_run(
            waiver_max_speed_bpm=195,
            waiver_window=("2026-08-02T00:00:00Z", "2026-08-03T00:00:00Z"))
        rid = env["run"]["id"]
        ok = validate_success(api.set_line_run_speed(rid, {"new_speed_bpm": 175}, OP))
        assert ok["current_speed_bpm"] == 175
        resp = api.set_line_run_speed(rid, {"new_speed_bpm": 176}, OP)
        validate_error(resp, ApiErrorId.ERR_LINE_SPEED_NOT_AUTHORIZED)


class TestShiftCycleAngles:

    def test_suspended_shift_keeps_on_hold_batches_on_resume(self, api):
        """PRD §3.5: "Batches in `ON_HOLD` deliberately stay on hold; they
        resume only through the batch's own advance."
        PRD §3.5: "On resume, every run paused automatically (those with
        `auto_paused` true) returns to `RUNNING` with the flag reset to false,
        and `suspend_reason` resets to `NONE`."

        Design: Difficulty/non_linear_state_machine/shift_running_suspended_cycle
        """
        env = setup_chilled_lot()
        db_line = make_line(line_code="DB-1", line_type="DEBONING", rated_speed_bpm=50)
        order = make_order(pounds_ordered=500.0)
        batch = make_batch(order["id"], env["lot"]["id"], env["shift"]["id"], db_line["id"])
        get_success_data(api.advance_deboning_batch(batch["id"], {"to_status": "IN_PROGRESS"}, OP))

        sid = env["shift"]["id"]
        get_success_data(api.transition_shift(
            sid, {"to_status": "SUSPENDED", "reason_code": "MANUAL"}, SUP))
        held = get_success_data(api.get_deboning_batch(batch["id"], OP))
        assert held["status"] == "ON_HOLD"

        get_success_data(api.transition_shift(
            sid, {"to_status": "RUNNING", "resolution_note": "line cleared and verified"}, SUP))
        still_held = get_success_data(api.get_deboning_batch(batch["id"], OP))
        assert still_held["status"] == "ON_HOLD"  # batches do NOT auto-resume

        resumed = validate_success(api.advance_deboning_batch(
            batch["id"], {"to_status": "IN_PROGRESS"}, OP))
        assert resumed["status"] == "IN_PROGRESS"

    def test_second_suspend_after_completion_allows_close(self, api):
        """PRD §3.5: "Suspension from any state other than `RUNNING` is
        rejected with `ERR_SHIFT_NOT_RUNNING`; the `suspend_reason` field reads
        `NONE` whenever the shift is not suspended."
        PRD §3.5: "Closing a shift — from `RUNNING` or `SUSPENDED` to `CLOSED`
        — is a `ShiftSupervisor` action guarded by run terminality: no line run
        of the shift may remain in `RUNNING` or `PAUSED`, else
        `ERR_RUNS_NOT_TERMINAL`".

        Design: Difficulty/non_linear_state_machine/shift_running_suspended_cycle
        """
        env = setup_running_shift_with_run()
        sid = env["shift"]["id"]
        complete_run(env["run"]["id"])
        # Suspend, then close directly from SUSPENDED (both origins legal).
        suspended = validate_success(api.transition_shift(
            sid, {"to_status": "SUSPENDED", "reason_code": "REGULATORY_HOLD"},
            make_usda_inspector_headers("usda-1")))
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspend_reason"] == "REGULATORY_HOLD"
        closed = validate_success(api.transition_shift(sid, {"to_status": "CLOSED"}, SUP))
        assert closed["status"] == "CLOSED"


class TestOrderDimensionAngles:

    def test_allocation_partial_then_allocated_across_batches(self, api):
        """PRD §3.6: "Allocation follows directly: `filled_lb` of exactly zero
        leaves the order `UNALLOCATED`; greater than zero but less than
        `pounds_ordered` makes it `PARTIALLY_ALLOCATED`; and `filled_lb`
        greater than or equal to `pounds_ordered` — equality allocates — makes
        it `ALLOCATED`."

        Design: Difficulty/non_linear_state_machine/order_parallel_allocation_fulfillment_dimensions
        """
        env = setup_chilled_lot()
        db_line = make_line(line_code="DB-1", line_type="DEBONING", rated_speed_bpm=50)
        order = make_order(pounds_ordered=100.0)
        oid = order["id"]

        b1 = make_batch(oid, env["lot"]["id"], env["shift"]["id"], db_line["id"],
                        input_weight_lb=50.0)
        get_success_data(api.advance_deboning_batch(b1["id"], {"to_status": "IN_PROGRESS"}, OP))
        get_success_data(api.advance_deboning_batch(
            b1["id"], {"to_status": "COMPLETED", "actual_output_weight_lb": 50.0,
                       "actual_labor_hours": 0.2}, OP))
        mid = get_success_data(api.get_order(oid, PLAN))
        # filled 49.0 < 100 -> PARTIALLY_ALLOCATED while IN_PRODUCTION
        assert mid["filled_lb"] == pytest.approx(49.0)
        assert mid["allocation_status"] == "PARTIALLY_ALLOCATED"
        assert mid["fulfillment_status"] == "IN_PRODUCTION"

        b2 = make_batch(oid, env["lot"]["id"], env["shift"]["id"], db_line["id"],
                        input_weight_lb=60.0)
        get_success_data(api.advance_deboning_batch(b2["id"], {"to_status": "IN_PROGRESS"}, OP))
        get_success_data(api.advance_deboning_batch(
            b2["id"], {"to_status": "COMPLETED", "actual_output_weight_lb": 60.0,
                       "actual_labor_hours": 0.2}, OP))
        done = get_success_data(api.get_order(oid, PLAN))
        # 49.0 + 58.8 == 107.8 >= 100 -> ALLOCATED; fulfillment unchanged until ship
        assert done["filled_lb"] == pytest.approx(107.8)
        assert done["allocation_status"] == "ALLOCATED"
        assert done["fulfillment_status"] == "IN_PRODUCTION"

    def test_filled_lb_equality_allocates(self, api):
        """PRD §3.6: "and `filled_lb` greater than or equal to
        `pounds_ordered` — equality allocates — makes it `ALLOCATED`."

        Design: Difficulty/combinatorial_formula/order_fill_round_per_batch_then_sum
        """
        env = setup_chilled_lot()
        db_line = make_line(line_code="DB-1", line_type="DEBONING", rated_speed_bpm=50)
        # net = round_half_up(output * 0.98, 2); choose output 100.0 -> net 98.0
        order = make_order(pounds_ordered=98.0)
        b = make_batch(order["id"], env["lot"]["id"], env["shift"]["id"], db_line["id"],
                       input_weight_lb=110.0)
        get_success_data(api.advance_deboning_batch(b["id"], {"to_status": "IN_PROGRESS"}, OP))
        batch = get_success_data(api.advance_deboning_batch(
            b["id"], {"to_status": "COMPLETED", "actual_output_weight_lb": 100.0,
                      "actual_labor_hours": 0.2}, OP))
        assert batch["net_weight_lb"] == pytest.approx(98.0)
        after = get_success_data(api.get_order(order["id"], PLAN))
        assert after["filled_lb"] == pytest.approx(98.0)
        assert after["allocation_status"] == "ALLOCATED"  # equality allocates


class TestCondemnationCycleAngles:

    def test_recertify_gate_uses_post_amendment_effective_count(self, api):
        """PRD §3.4: "A `USDAInspector` recertifies a `DISPUTED` record back to
        `CERTIFIED`, optionally supplying an `amended_carcass_count` greater
        than zero; the same segregation-of-duties and birds-hung gates apply,
        evaluated with the post-amendment `effective_count`, and the same
        four-link cascade follows."
        PRD §3.4: "Certification also passes a numerical gate: the sum of
        `effective_count` over the run's already-`CERTIFIED` records, plus the
        `effective_count` of the record being certified, must be no greater
        than the run's `birds_hung` — equality allowed — with `DRAFT` and
        `DISPUTED` records not participating in the gate; a violation is
        `ERR_CONDEMNATION_COUNT_EXCEEDS_HUNG`."

        Design: Difficulty/non_linear_state_machine/condemnation_certified_disputed_recertified_cycle
        """
        env = setup_completed_run(completion_clock=None, condemnation=100,
                                  condemn_user_id="qa-1")
        cid = env["record"]["id"]
        usda = make_usda_inspector_headers("usda-1")
        get_success_data(api.advance_condemnation_record(cid, {"to_status": "CERTIFIED"}, usda))
        get_success_data(api.advance_condemnation_record(
            cid, {"to_status": "DISPUTED", "reason": "count review"}, PM))
        # Amendment beyond birds_hung (9950) must fail the gate at recertify
        resp = api.advance_condemnation_record(
            cid, {"to_status": "CERTIFIED", "amended_carcass_count": 9960}, usda)
        validate_error(resp, ApiErrorId.ERR_CONDEMNATION_COUNT_EXCEEDS_HUNG)
        after = get_success_data(api.get_condemnation_record(cid, QA))
        assert after["status"] == "DISPUTED"

    def test_dispute_requires_reason(self, api):
        """PRD §3.4: "A `PlantManager` may advance a `CERTIFIED` record to
        `DISPUTED`, supplying a `reason` (absent, `ERR_INVALID_REQUEST`)."
        PRD §2.6: "Malformed payloads — a missing required field, a type
        mismatch, an invalid enum value, an unknown field, a sanitation
        `window_start` that is not strictly earlier than `window_end`, or a
        required `findings` or `resolution_note` left absent — are rejected
        with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Difficulty/non_linear_state_machine/condemnation_certified_disputed_recertified_cycle
        """
        env = setup_completed_run(completion_clock=None, condemnation=100,
                                  condemn_user_id="qa-1")
        cid = env["record"]["id"]
        get_success_data(api.advance_condemnation_record(
            cid, {"to_status": "CERTIFIED"}, make_usda_inspector_headers("usda-1")))
        resp = api.advance_condemnation_record(cid, {"to_status": "DISPUTED"}, PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        after = get_success_data(api.get_condemnation_record(cid, QA))
        assert after["status"] == "CERTIFIED"


class TestCascadeAngles:

    def test_flip_never_touches_shipped_lots(self, api):
        """PRD §3.7: "The flip never runs `FROZEN` to `FRESH`, and it never
        touches lots already `SHIPPED` or `RECALLED`."
        PRD §3.4: "Fourth, when that recomputation lowers the certified yield,
        finished lots of this flock lot in `TRACE_LOCKED` with `routing_status`
        `FRESH` whose order is `FLEXIBLE` flip from `FRESH` to `FROZEN` if the
        new certified yield has fallen below the fresh-yield threshold of
        §3.7."

        Design: Difficulty/transitive_cascade/condemnation_recertify_yield_routing_flip_cascade
        """
        env = setup_trace_locked_lot(temperature_requirement="FLEXIBLE",
                                     chill_temp_c=3.5, lot_code="FL-200")
        fl = env["finished_lot"]
        assert fl["routing_status"] == "FRESH"
        # Ship the lot first: SHIPPED lots are immune to the flip.
        get_success_data(api.advance_finished_lot(fl["id"], {"to_status": "SHIPPED"}, SUP))

        get_success_data(api.advance_flock_lot(
            env["lot"]["id"], {"to_status": "REOPENED"},
            make_usda_inspector_headers("usda-1")))
        record = get_success_data(api.create_condemnation_record(
            create_condemnation_record_payload(env["run"]["id"],
                                               condemnation_code="BRUISING",
                                               carcass_count=100),
            make_qa_technician_headers("qa-1")))
        get_success_data(api.advance_condemnation_record(
            record["id"], {"to_status": "CERTIFIED"},
            make_usda_inspector_headers("usda-1")))

        lot = get_success_data(api.get_flock_lot(env["lot"]["id"], PM))
        assert lot["certified_yield_pct"] == pytest.approx(71.28)  # below 72.0
        after = get_success_data(api.get_finished_lot(fl["id"], QA))
        assert after["routing_status"] == "FRESH"  # SHIPPED lot untouched by the flip
        assert after["status"] == "SHIPPED"

    def test_water_breach_cascade_is_atomic_within_reading_request(self, api):
        """PRD §3.5: "A process-water reading that flips `water_breach_active`
        from false to true while the shift is `RUNNING` triggers the plant's
        automatic suspension: the shift moves `RUNNING` → `SUSPENDED` with
        `suspend_reason` set to `WATER_LIMIT_BREACH`, every line run of the
        shift in `RUNNING` moves to `PAUSED` with `auto_paused` set to true,
        and every deboning batch of the shift in `IN_PROGRESS` moves to
        `ON_HOLD` — all atomically within the reading's request."
        PRD §2.10: "The plant's consistency model is immediate: every mutation,
        together with all cascades it triggers, commits atomically within the
        request."

        Design: Difficulty/transitive_cascade/water_breach_suspend_pause_hold_cascade
        """
        env = setup_running_shift_with_run()
        sid = env["shift"]["id"]
        # PRD 3.5: the birds-basis rate is null while birds_processed is zero,
        # so a breach requires a completed run in the denominator. Complete the
        # first run, then keep a second run RUNNING for the pause cascade.
        complete_run(env["run"]["id"])  # birds_processed = 9950
        lot2 = book_and_receive_lot(sid, lot_code="FL-200", grower_name="GrowerB")
        run2 = queue_run(sid, env["line"]["id"], lot2["id"])
        run2 = get_success_data(api.advance_line_run(run2["id"], {"to_status": "RUNNING"}, OP))
        # 15000 gal * 1000 / 9950 birds == 1507.54 > 1500.0 -> breach flips on
        resp = api.create_utility_reading(
            create_utility_reading_payload(sid, gallons=15000.0), QA)
        reading = validate_success(resp, expected_status=201)
        # Cascade already committed: the immediately-following reads observe it.
        shift = get_success_data(api.get_shift(sid, QA))
        run2 = get_success_data(api.get_line_run(run2["id"], OP))
        assert shift["status"] == "SUSPENDED"
        assert shift["suspend_reason"] == "WATER_LIMIT_BREACH"
        assert run2["status"] == "PAUSED"
        assert run2["auto_paused"] is True
        # The reading itself is recorded at the logical time of posting
        assert reading["recorded_at"].startswith("2026-08-01T")


class TestPriorityPairAngles:

    def test_set_speed_unauthorized_when_shift_running(self, api):
        """PRD §3.4: "a speed change supplies `new_speed_bpm`, requires the
        enclosing shift in `RUNNING`, and is authorized when the new speed is
        no greater than the effective maximum — equality allowed — else
        `ERR_LINE_SPEED_NOT_AUTHORIZED`."
        PRD §2.6: "Regulatory and safety gates (priority 5). Line-speed
        authorization, segregation of duties, and the chiller-limit fresh block
        — `ERR_LINE_SPEED_NOT_AUTHORIZED`, `ERR_SOD_PREOP_SANITATION`,
        `ERR_SOD_CONDEMNATION_SELF_CERTIFY`, and
        `ERR_CHILLER_LIMIT_FRESH_BLOCKED` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/set_speed_suspended_and_unauthorized_state_wins
        """
        env = setup_running_shift_with_run()
        # Shift RUNNING (priority-4 passes); only the safety gate can fire.
        resp = api.set_line_run_speed(env["run"]["id"], {"new_speed_bpm": 196}, OP)
        validate_error(resp, ApiErrorId.ERR_LINE_SPEED_NOT_AUTHORIZED)
        after = get_success_data(api.get_line_run(env["run"]["id"], OP))
        assert after["current_speed_bpm"] == 175

    def test_labor_budget_exceeded_fires_when_window_open(self, api):
        """PRD §3.6: "Two forward gates apply at creation: the order's
        `due_at` must still lie in the future of the logical clock, else
        `ERR_ORDER_WINDOW_CLOSED`, and the batch's estimated labor must fit the
        shift's remaining budget, else `ERR_LABOR_BUDGET_EXCEEDED` — this
        fiscal check runs last, after every other validation, per the ladder of
        §2.6."

        Design: Difficulty/priority_pair_validation_conflict/batch_create_window_closed_and_labor_exceeded_temporal_wins
        """
        db_line = make_line(line_code="DB-1", line_type="DEBONING", rated_speed_bpm=50)
        shift = make_shift(labor_hours_budget=1.0)
        lot = book_and_receive_lot(shift["id"])
        order = make_order(pounds_ordered=100.0, temperature_requirement="FROZEN",
                           product_code="THIGH_MEAT", customer_name="CustZ")
        # due_at 2026-08-03 is in the future at the default clock; only the
        # fiscal gate can fire (est 2.0 > 1.0 remaining).
        resp = api.create_deboning_batch(
            create_deboning_batch_payload(order["id"], lot["id"], shift["id"],
                                          db_line["id"], crew_count=4,
                                          input_weight_lb=1000.0), SUP)
        validate_error(resp, ApiErrorId.ERR_LABOR_BUDGET_EXCEEDED)


class TestBoundaryAngles:

    def test_water_rate_one_gallon_under_limit_compliant(self, api):
        """PRD §2.8: "a rate must be strictly greater than its limit to breach;
        a rate exactly equal to its limit is compliant."
        PRD §2.9: "Breach comparisons against the water limits of §2.8 are made
        against the unrounded rate, not the reported rounded value."

        Design: Difficulty/boundary_precision_check/water_rate_exactly_at_limit_compliant
        """
        env = setup_completed_run(completion_clock=None)
        # 14924 gal / 9950 birds -> 1499.899... < 1500.0 -> compliant
        get_success_data(api.create_utility_reading(
            create_utility_reading_payload(env["shift"]["id"], gallons=14924.0), QA))
        shift = get_success_data(api.get_shift(env["shift"]["id"], QA))
        assert shift["water_rate_birds_basis"] == pytest.approx(1499.9)
        assert shift["water_breach_active"] is False
        assert shift["status"] == "RUNNING"

    def test_staffing_full_band_keeps_rated_speed_cap(self, api):
        """PRD §3.1: "when the ratio is at least 1.0, the cap is the line's
        `rated_speed_bpm` multiplied by 1.0, rounded down to a whole bird per
        minute".
        PRD §3.4: "a speed change supplies `new_speed_bpm`, requires the
        enclosing shift in `RUNNING`, and is authorized when the new speed is
        no greater than the effective maximum — equality allowed — else
        `ERR_LINE_SPEED_NOT_AUTHORIZED`."

        Design: Difficulty/boundary_precision_check/staffing_ratio_exactly_0_9_band
        """
        # Waiver 195 ACTIVE + full staffing (ratio 1.0): ceiling 195.
        env = setup_running_shift_with_run(waiver_max_speed_bpm=195)
        rid = env["run"]["id"]
        ok = validate_success(api.set_line_run_speed(rid, {"new_speed_bpm": 195}, OP))
        assert ok["current_speed_bpm"] == 195
        resp = api.set_line_run_speed(rid, {"new_speed_bpm": 196}, OP)
        validate_error(resp, ApiErrorId.ERR_LINE_SPEED_NOT_AUTHORIZED)

    def test_certified_yield_below_threshold_routes_frozen(self, api):
        """PRD §3.7: "otherwise, if the flock lot's `certified_yield_pct` is at
        least the fresh-yield threshold of 72.0 percent, it routes `FRESH` — a
        yield exactly at the threshold routes fresh — and otherwise it routes
        `FROZEN`."

        Design: Difficulty/boundary_precision_check/certified_yield_exactly_72_routes_fresh
        """
        # Settle a lot with a certified condemnation of 100 -> yield 71.28 < 72.0
        env = setup_chilled_lot(condemnation=100, condemn_user_id="qa-1")
        get_success_data(api.advance_condemnation_record(
            env["record"]["id"], {"to_status": "CERTIFIED"},
            make_usda_inspector_headers("usda-1")))
        lot = get_success_data(api.advance_flock_lot(
            env["lot"]["id"], {"to_status": "SETTLED"}, SUP))
        lot = get_success_data(api.get_flock_lot(env["lot"]["id"], PM))
        assert lot["certified_yield_pct"] == pytest.approx(71.28)

        db_line = make_line(line_code="DB-1", line_type="DEBONING", rated_speed_bpm=50)
        order = make_order(pounds_ordered=400.0, temperature_requirement="FLEXIBLE",
                           product_code="BREAST_FILLET", customer_name="CustY")
        batch = make_batch(order["id"], env["lot"]["id"], env["shift"]["id"],
                           db_line["id"], input_weight_lb=500.0)
        get_success_data(api.advance_deboning_batch(batch["id"], {"to_status": "IN_PROGRESS"}, OP))
        get_success_data(api.advance_deboning_batch(
            batch["id"], {"to_status": "COMPLETED", "actual_output_weight_lb": 500.0,
                          "actual_labor_hours": 1.0}, OP))
        lots, _ = validate_paginated(api.list_finished_lots(QA))
        fl = lots[0]
        # Compliant chill log: chill compliance holds, but yield < threshold.
        from test_helpers import create_chill_chain_log_payload
        get_success_data(api.create_chill_chain_log(
            create_chill_chain_log_payload(fl["id"], temperature_c=3.5), QA))
        locked = validate_success(api.trace_lock_finished_lot(fl["id"], {}, QA))
        assert locked["status"] == "TRACE_LOCKED"
        assert locked["routing_status"] == "FROZEN"  # 71.28 < 72.0


class TestCrossEntityGateAngles:

    def test_batch_start_requires_shift_running(self, api):
        """PRD §3.6: "Starting — `SCHEDULED` → `IN_PROGRESS` — requires the
        enclosing shift in `RUNNING` (else `ERR_SHIFT_NOT_RUNNING`) and the
        source lot at `CHILLED`, `SETTLED`, or `REOPENED` (else
        `ERR_LOT_NOT_CHILLED`)".

        Design: Difficulty/cross_entity_state_dependency/line_run_start_requires_shift_running
        """
        # Lot CHILLED but the shift is SUSPENDED (not RUNNING, not CLOSED — a
        # CLOSED shift would reject the batch create itself with
        # ERR_SHIFT_TERMINAL): the shift gate fires at batch start.
        env = setup_chilled_lot()
        sid = env["shift"]["id"]
        complete_shift = get_success_data(api.get_shift(sid, SUP))
        assert complete_shift["status"] == "RUNNING"
        get_success_data(api.transition_shift(
            sid, {"to_status": "SUSPENDED", "reason_code": "MANUAL"}, SUP))
        db_line = make_line(line_code="DB-1", line_type="DEBONING", rated_speed_bpm=50)
        order = make_order()
        batch = make_batch(order["id"], env["lot"]["id"], sid, db_line["id"])
        resp = api.advance_deboning_batch(batch["id"], {"to_status": "IN_PROGRESS"}, OP)
        validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_RUNNING)
        after = get_success_data(api.get_deboning_batch(batch["id"], OP))
        assert after["status"] == "SCHEDULED"

    def test_batch_start_on_settled_lot_allowed(self, api):
        """PRD §3.6: "Starting — `SCHEDULED` → `IN_PROGRESS` — requires the
        enclosing shift in `RUNNING` (else `ERR_SHIFT_NOT_RUNNING`) and the
        source lot at `CHILLED`, `SETTLED`, or `REOPENED` (else
        `ERR_LOT_NOT_CHILLED`)".

        Design: Difficulty/cross_entity_state_dependency/deboning_batch_start_requires_lot_chilled
        """
        env = setup_settled_lot()
        assert env["lot"]["status"] == "SETTLED"
        db_line = make_line(line_code="DB-1", line_type="DEBONING", rated_speed_bpm=50)
        order = make_order()
        batch = make_batch(order["id"], env["lot"]["id"], env["shift"]["id"], db_line["id"])
        started = validate_success(api.advance_deboning_batch(
            batch["id"], {"to_status": "IN_PROGRESS"}, OP))
        assert started["status"] == "IN_PROGRESS"

    def test_trace_lock_succeeds_when_all_certified(self, api):
        """PRD §3.7: "First, every condemnation record on the source flock
        lot's runs must be `CERTIFIED`, else
        `ERR_TRACE_LOCK_BLOCKED_UNCERTIFIED`."
        PRD §3.7: "For `FROZEN`: the lot routes `FROZEN` unconditionally."

        Design: Difficulty/cross_entity_state_dependency/trace_lock_requires_certified_condemnations
        """
        env = setup_chilled_lot(condemnation=25, condemn_user_id="qa-1")
        get_success_data(api.advance_condemnation_record(
            env["record"]["id"], {"to_status": "CERTIFIED"},
            make_usda_inspector_headers("usda-1")))
        db_line = make_line(line_code="DB-1", line_type="DEBONING", rated_speed_bpm=50)
        order = make_order(pounds_ordered=500.0)  # FROZEN
        batch = make_batch(order["id"], env["lot"]["id"], env["shift"]["id"], db_line["id"])
        get_success_data(api.advance_deboning_batch(batch["id"], {"to_status": "IN_PROGRESS"}, OP))
        get_success_data(api.advance_deboning_batch(
            batch["id"], {"to_status": "COMPLETED", "actual_output_weight_lb": 500.0,
                          "actual_labor_hours": 1.0}, OP))
        lots, _ = validate_paginated(api.list_finished_lots(QA))
        fl = lots[0]
        locked = validate_success(api.trace_lock_finished_lot(fl["id"], {}, QA))
        assert locked["status"] == "TRACE_LOCKED"
        assert locked["routing_status"] == "FROZEN"


class TestResourceBoundaryAngles:

    def test_booking_within_capacity_and_single_lot_at_capacity(self, api):
        """PRD §3.3: "Booking enforces the shift's shackle capacity: the sum of
        `booked_head_count` across all lots of the shift, plus the new lot's
        booking, must not exceed the shift's `shackle_capacity_birds`; a total
        exactly equal to capacity is allowed, while a total strictly above it
        is rejected with `ERR_SHIFT_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/flock_booking_shift_aggregate_capacity
        """
        shift = make_shift(shackle_capacity_birds=20000, labor_hours_budget=50.0,
                           shift_code="NIGHT")
        # Single lot exactly at capacity is allowed.
        lot = validate_success(api.create_flock_lot(
            create_flock_lot_payload(shift["id"], lot_code="FL-FULL",
                                     booked_head_count=20000), RCV),
            expected_status=201)
        assert lot["status"] == "BOOKED"
        # One bird beyond the aggregate is rejected.
        resp = api.create_flock_lot(
            create_flock_lot_payload(shift["id"], lot_code="FL-OVER",
                                     booked_head_count=1), RCV)
        validate_error(resp, ApiErrorId.ERR_SHIFT_CAPACITY_EXCEEDED)

    def test_supersession_of_overlapping_draft_waiver(self, api):
        """PRD §3.1: "Creation also carries a supersession rule: if the new
        waiver's window overlaps the window of any existing waiver on the same
        line still in `DRAFT` or `SUBMITTED`, each such overlapping waiver is
        transitioned by the system to `SUPERSEDED`, and the line's `version`
        increments by one."

        Design: Difficulty/resource_temporal_overlap/waiver_windows_half_open_adjacency
        """
        line = make_line()
        w1 = get_success_data(api.create_waiver(
            line["id"], create_waiver_payload(
                line["version"], max_speed_bpm=195,
                effective_from="2026-08-01T06:00:00Z",
                effective_to="2026-08-01T14:00:00Z"), PM))
        line = get_success_data(api.get_line(line["id"], PM))
        # Second waiver overlaps the first's window -> first is SUPERSEDED.
        w2 = get_success_data(api.create_waiver(
            line["id"], create_waiver_payload(
                line["version"], max_speed_bpm=190,
                effective_from="2026-08-01T10:00:00Z",
                effective_to="2026-08-01T18:00:00Z"), PM))
        w1_after = get_success_data(api.get_waiver(w1["id"], PM))
        assert w1_after["status"] == "SUPERSEDED"
        w2_after = get_success_data(api.get_waiver(w2["id"], PM))
        assert w2_after["status"] == "DRAFT"


class TestInvariantAngles:

    def test_labor_ledger_swaps_estimate_for_actual_on_complete(self, api):
        """PRD §3.6: "The shift's `labor_hours_remaining` is its
        `labor_hours_budget` minus the sum of `estimated_labor_hours` over the
        shift's batches in `SCHEDULED`, `IN_PROGRESS`, or `ON_HOLD`, minus the
        sum of `actual_labor_hours` over its batches in `COMPLETED`."
        PRD §3.6: "the shift's labor ledger swaps estimate for actual — the
        estimate is released and the actual hours are debited."

        Design: Difficulty/compensating_invariant/labor_hours_conserved_on_batch_create_cancel
        """
        env = setup_production_line_for_deboning(labor_hours_budget=10.0,
                                                 input_weight_lb=1000.0)
        sid = env["shift"]["id"]
        after_create = get_success_data(api.get_shift(sid, SUP))
        # estimate 1000/500 == 2.0 debited
        assert env["batch"]["estimated_labor_hours"] == pytest.approx(2.0)
        assert after_create["labor_hours_remaining"] == pytest.approx(8.0)

        get_success_data(api.advance_deboning_batch(
            env["batch"]["id"], {"to_status": "IN_PROGRESS"}, OP))
        get_success_data(api.advance_deboning_batch(
            env["batch"]["id"], {"to_status": "COMPLETED",
                                 "actual_output_weight_lb": 900.0,
                                 "actual_labor_hours": 1.5}, OP))
        after_complete = get_success_data(api.get_shift(sid, SUP))
        # estimate 2.0 released, actual 1.5 debited: 10 - 1.5 == 8.5
        assert after_complete["labor_hours_remaining"] == pytest.approx(8.5)

    def test_draft_record_counts_toward_accountability(self, api):
        """PRD §3.4: "Draft records count immediately: the run and lot
        condemned aggregates are recomputed on creation, and `DRAFT` counts
        feed the provisional yield."
        PRD §3.4: "First, the run's condemned aggregate is updated: the lot's
        `condemned_accounted` is the sum of `effective_count` over records in
        `DRAFT` or `CERTIFIED` on the lot's runs, with `DISPUTED` records
        excluded, and the lot's `carcasses_to_chill` is its `birds_hung_total`
        minus its `condemned_accounted`."

        Design: Difficulty/compensating_invariant/bird_accountability_conserved_on_certify_dispute
        """
        env = setup_completed_run(completion_clock=None, condemnation=100,
                                  condemn_user_id="qa-1")
        lot = get_success_data(api.get_flock_lot(env["lot"]["id"], PM))
        # DRAFT already counts: 9950 - 100 == 9850 before any certification.
        assert lot["condemned_accounted"] == 100
        assert lot["carcasses_to_chill"] == 9850
        assert lot["birds_hung_total"] == 9950
