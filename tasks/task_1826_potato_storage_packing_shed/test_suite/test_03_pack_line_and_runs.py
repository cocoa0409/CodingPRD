"""Pack-line operations: partial-fill cycle, wash-freshness windows, schedule
conflicts with the sanitation buffer, priority conflicts, and run-close draw
accounting (PRD §3.5)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, ApiErrorId,
    setup_grower_shed_bin_lot, setup_allocated_contract_order,
    create_grower, create_shed, create_bin, create_binned_lot, assess_lot,
    create_contract, create_order, allocate_order, record_pass_wash, record_fail_wash,
    record_wash_check, create_scheduled_run, complete_run, abort_run, set_clock,
    refresh_lot, refresh_order, refresh_contract, refresh_shed, make_draw,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
SALES = TEST_USERS["sales_headers"]
QA = TEST_USERS["qa_headers"]
STORAGE = TEST_USERS["storage_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


class TestPartialFillCycle:
    def test_partial_fill_cycles_order_back_to_allocated(self, api):
        """PRD §3.5: "Its `packed_to_date_cwt` increases by the run's total packed. If the accumulated total has reached the requested volume, the order transitions to `SHIPPED`; otherwise it cycles back to `ALLOCATED` — a partial fill from which it may later be topped up or run again."
        PRD §3.5: "For each draw, the lot's `packed_total_cwt` increases by the draw's `packed_cwt`, its `cull_total_cwt` increases by the draw's `cull_cwt`, its `available_cwt` decreases by the `raw_drawn_cwt`, and its `reserved_cwt` decreases by the same raw amount; the reservation on that lot is consumed."

        Design: Difficulty/non_linear_state_machine/pack_order_partial_fill_cycle
        """
        ctx = setup_allocated_contract_order(
            lot_weight_cwt=1000.00, committed_cwt=400.00, requested_packed_cwt=300.00,
            grade_min_us1_pct=80.0,
            assess={"us1_pct": 70.0, "us2_pct": 20.0, "cull_pct": 10.0,
                    "cumulative_shrink_cwt": 0.00},
            set_clock_to="2026-08-02T00:00:00Z",
        )
        set_clock("2026-08-10T00:00:00Z")
        record_pass_wash(ctx["shed"]["id"], "2026-08-10T00:00:00Z")
        run = create_scheduled_run(ctx["order"]["id"], "2026-08-10T08:00:00Z",
                                   "2026-08-10T10:00:00Z")

        run = complete_run(run["id"], [make_draw(
            ctx["lot"]["id"], 333.33, 180.00, 150.00, 30.00, 153.33, "WASTE"
        )])
        assert run["status"] == "COMPLETED"

        order = refresh_order(ctx["order"]["id"])
        assert order["status"] == "ALLOCATED"  # cycle back, not SHIPPED: 180 < 300
        assert abs(order["packed_to_date_cwt"] - 180.00) <= 0.005
        assert order["reservations"] == []  # the 333.33 raw reservation was consumed

        lot = refresh_lot(ctx["lot"]["id"])
        assert abs(lot["available_cwt"] - 666.67) <= 0.005  # 1000 - 333.33
        assert abs(lot["reserved_cwt"] - 0.00) <= 0.005

    def test_partial_fill_updates_contract_commitment_ledger(self, api):
        """PRD §3.5: "For a `CONTRACT` order, the contract's packed ledger moves in step: its `packed_to_date_cwt` increases by the run's packed total and its `allocated_active_cwt` decreases by the same amount."
        PRD §3.3: "`remaining_committed_cwt` is the committed volume less both of those quantities."

        Design: Difficulty/non_linear_state_machine/pack_order_partial_fill_cycle
        """
        ctx = setup_allocated_contract_order(
            lot_weight_cwt=1000.00, committed_cwt=400.00, requested_packed_cwt=300.00,
            grade_min_us1_pct=80.0,
            assess={"us1_pct": 70.0, "us2_pct": 20.0, "cull_pct": 10.0,
                    "cumulative_shrink_cwt": 0.00},
            set_clock_to="2026-08-02T00:00:00Z",
        )
        set_clock("2026-08-10T00:00:00Z")
        record_pass_wash(ctx["shed"]["id"], "2026-08-10T00:00:00Z")
        run = create_scheduled_run(ctx["order"]["id"], "2026-08-10T08:00:00Z",
                                   "2026-08-10T10:00:00Z")
        complete_run(run["id"], [make_draw(
            ctx["lot"]["id"], 333.33, 180.00, 150.00, 30.00, 153.33, "WASTE"
        )])
        # aggregate us1 share 150/180 = 83.33% >= grade_min 80.0 so the grade gate passed

        contract = refresh_contract(ctx["contract"]["id"])
        assert abs(contract["remaining_committed_cwt"] - 100.00) <= 0.005
        assert abs(contract["allocated_active_cwt"] - 120.00) <= 0.005
        assert abs(contract["packed_to_date_cwt"] - 180.00) <= 0.005
        # identity 400 == 100 + 120 + 180


class TestWashFreshnessWindow:
    @staticmethod
    def _setup_restricted_shed_order():
        """Allocated order on a shed whose last PASS is followed by two mild FAILs
        (posture RESTRICTED; freshness window tightens to 4h)."""
        ctx = setup_allocated_contract_order(
            lot_weight_cwt=500.00, committed_cwt=300.00, requested_packed_cwt=75.00,
            set_clock_to="2026-08-02T00:00:00Z",
        )
        record_pass_wash(ctx["shed"]["id"], "2026-08-10T00:00:00Z")
        record_fail_wash(ctx["shed"]["id"], "2026-08-10T00:30:00Z")
        record_fail_wash(ctx["shed"]["id"], "2026-08-10T00:45:00Z")
        return ctx

    def test_restricted_window_includes_exactly_four_hours(self, api):
        """PRD §3.5: "The window is 12 hours when the shed is in `NORMAL` posture and 4 hours when it is `RESTRICTED`; a check exactly at the boundary counts as fresh."

        Design: Corner/endpoints/c_wash_validity_window_restricted_tightens
        """
        ctx = self._setup_restricted_shed_order()
        shed = refresh_shed(ctx["shed"]["id"])
        assert shed["posture"] == "RESTRICTED"

        # PASS is 3.5h old: fresh under the 4h RESTRICTED window.
        set_clock("2026-08-10T03:30:00Z")
        run1 = create_scheduled_run(ctx["order"]["id"], "2026-08-10T08:00:00Z",
                                    "2026-08-10T09:00:00Z")
        assert run1["status"] == "SCHEDULED"
        abort_run(run1["id"])

        # Exactly 4h old: inclusive boundary, still fresh.
        set_clock("2026-08-10T04:00:00Z")
        run2 = create_scheduled_run(ctx["order"]["id"], "2026-08-10T09:00:00Z",
                                    "2026-08-10T10:00:00Z")
        assert run2["status"] == "SCHEDULED"
        abort_run(run2["id"])

    def test_restricted_window_rejects_four_and_a_half_hours(self, api):
        """PRD §3.5: "The window is 12 hours when the shed is in `NORMAL` posture and 4 hours when it is `RESTRICTED`; a check exactly at the boundary counts as fresh. ... A stale shed rejects the run with `ERR_WASH_CHECK_STALE`."

        Design: Corner/endpoints/c_wash_validity_window_restricted_tightens
        """
        ctx = self._setup_restricted_shed_order()
        set_clock("2026-08-10T04:30:00Z")  # PASS is 4.5h old under RESTRICTED
        resp = api.create_pack_run(
            ctx["order"]["id"],
            {"scheduled_start": "2026-08-10T10:00:00Z", "scheduled_end": "2026-08-10T11:00:00Z"},
            SUPERVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_WASH_CHECK_STALE)

    def test_shed_with_no_pass_check_is_stale(self, api):
        """PRD §3.5: "a shed with no recorded `PASS` at all is treated as stale. A stale shed rejects the run with `ERR_WASH_CHECK_STALE`."

        Design: Corner/endpoints/c_run_create_missing_wash_returns_stale
        """
        ctx = setup_allocated_contract_order(
            lot_weight_cwt=500.00, committed_cwt=300.00, requested_packed_cwt=75.00,
            set_clock_to="2026-08-02T00:00:00Z",
        )
        resp = api.create_pack_run(
            ctx["order"]["id"],
            {"scheduled_start": "2026-08-02T08:00:00Z", "scheduled_end": "2026-08-02T10:00:00Z"},
            SUPERVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_WASH_CHECK_STALE)
        order = refresh_order(ctx["order"]["id"])
        assert order["status"] == "ALLOCATED"


class TestPackLineScheduleConflict:
    @staticmethod
    def _setup_three_orders():
        """Shed with an RB lot (assessed 0.9) in B1, a YG lot (no assessment) in B2,
        two contracts, and three allocated orders: O1 RB, O2 RB, O3 YG."""
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower Sixteen", grower_code="G-16", shed_name="Shed P",
            lot_weight_cwt=1000.00, set_clock_to="2026-08-02T00:00:00Z",
        )
        g, s = ctx["grower"], ctx["shed"]
        b1 = ctx["bin"]
        l1 = ctx["lot"]
        assess_lot(l1["id"], l1["version"], us1_pct=70.0, us2_pct=20.0, cull_pct=10.0,
                   cumulative_shrink_cwt=0.00)
        b2 = create_bin(s["id"], bin_code="B-2")
        create_binned_lot(g["id"], b2["id"], variety="YUKON_GOLD", harvest_date="2026-07-21",
                          original_weight_cwt=500.00)
        c1 = create_contract(committed_volume_cwt=300.00, price_cents_per_cwt=2000,
                             buyer_name="Buyer L")
        c2 = create_contract(variety="YUKON_GOLD", committed_volume_cwt=200.00,
                             price_cents_per_cwt=2200, buyer_name="Buyer M")
        o1 = create_order(s["id"], contract_id=c1["id"], requested_packed_cwt=100.00)
        allocate_order(o1["id"])
        o2 = create_order(s["id"], contract_id=c1["id"], requested_packed_cwt=100.00)
        allocate_order(o2["id"])
        o3 = create_order(s["id"], contract_id=c2["id"], variety="YUKON_GOLD",
                          pack_unit_weight_lbs=10, requested_packed_cwt=100.00)
        allocate_order(o3["id"])
        set_clock("2026-08-10T07:00:00Z")
        record_pass_wash(s["id"], "2026-08-10T00:00:00Z")
        return {**ctx, "bin2": b2, "o1": o1, "o2": o2, "o3": o3}

    def test_same_variety_adjacency_allowed(self, api):
        """PRD §3.5: "A new run conflicts with an existing `SCHEDULED` run on the same shed whenever the two windows overlap under a sanitation buffer: when the two orders are of different varieties the buffer is one hour, and when they are of the same variety the buffer is zero. Formally, a conflict exists when the new run's start falls before the other run's end plus the buffer and the other run's start falls before the new run's end plus the buffer; half-open adjacency — a new run starting exactly when the prior one ends plus buffer — is allowed."

        Design: Difficulty/resource_temporal_overlap/pack_line_variety_buffer_overlap
        """
        ctx = self._setup_three_orders()
        r1 = create_scheduled_run(ctx["o1"]["id"], "2026-08-10T08:00:00Z",
                                  "2026-08-10T10:00:00Z")
        assert r1["status"] == "SCHEDULED"
        # Same variety: half-open adjacency, 10:00 start after 10:00 end, no buffer.
        r2 = create_scheduled_run(ctx["o2"]["id"], "2026-08-10T10:00:00Z",
                                  "2026-08-10T11:00:00Z")
        assert r2["status"] == "SCHEDULED"

    def test_different_variety_requires_one_hour_buffer(self, api):
        """PRD §3.5: "A new run conflicts with an existing `SCHEDULED` run on the same shed whenever the two windows overlap under a sanitation buffer: when the two orders are of different varieties the buffer is one hour, and when they are of the same variety the buffer is zero. Formally, a conflict exists when the new run's start falls before the other run's end plus the buffer and the other run's start falls before the new run's end plus the buffer; half-open adjacency — a new run starting exactly when the prior one ends plus buffer — is allowed. A conflict is rejected with `ERR_LINE_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/pack_line_variety_buffer_overlap
        """
        ctx = self._setup_three_orders()
        create_scheduled_run(ctx["o1"]["id"], "2026-08-10T08:00:00Z", "2026-08-10T10:00:00Z")
        create_scheduled_run(ctx["o2"]["id"], "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")

        # YUKON_GOLD at 10:30 violates the 1-hour sanitation buffer after R2's 11:00 end.
        resp = api.create_pack_run(
            ctx["o3"]["id"],
            {"scheduled_start": "2026-08-10T10:30:00Z", "scheduled_end": "2026-08-10T12:00:00Z"},
            SUPERVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_LINE_SCHEDULE_CONFLICT)

        # 12:00 start is exactly buffer_end of R2's 11:00 end + 1h: boundary allowed.
        r4 = create_scheduled_run(ctx["o3"]["id"], "2026-08-10T12:00:00Z",
                                  "2026-08-10T13:00:00Z")
        assert r4["status"] == "SCHEDULED"

    def test_fail_checks_do_not_invalidate_existing_pass_freshness(self, api):
        """PRD §3.5: "`FAIL` checks recorded after the most recent `PASS` do not extend or invalidate freshness — they act through posture instead".

        Design: Difficulty/priority_pair_validation_conflict/safety_outranks_temporal_on_run_create
        """
        ctx = setup_allocated_contract_order(
            lot_weight_cwt=1000.00, committed_cwt=600.00, requested_packed_cwt=100.00,
            assess={"us1_pct": 70.0, "us2_pct": 20.0, "cull_pct": 10.0,
                    "cumulative_shrink_cwt": 0.00},
            set_clock_to="2026-08-02T00:00:00Z",
        )
        set_clock("2026-08-10T00:00:00Z")
        # PASS measured 4h before the run-create clock: fresh under the NORMAL 12h window.
        record_pass_wash(ctx["shed"]["id"], "2026-08-09T20:00:00Z")
        run = create_scheduled_run(ctx["order"]["id"], "2026-08-10T08:00:00Z",
                                   "2026-08-10T10:00:00Z")
        assert run["status"] == "SCHEDULED"  # PASS at 4h old authorized this run
        # FAILs recorded after that PASS tighten posture but do not retro-invalidate it.
        record_fail_wash(ctx["shed"]["id"], "2026-08-10T00:30:00Z")
        record_fail_wash(ctx["shed"]["id"], "2026-08-10T00:45:00Z")
        shed = refresh_shed(ctx["shed"]["id"])
        assert shed["posture"] == "RESTRICTED"

    def test_wash_staleness_outranks_schedule_conflict(self, api):
        """PRD §2.9: "A corollary of this ordering is that a food-safety failure surfaces ahead of a shape error, and a shape error surfaces ahead of a fiscal ceiling".
        PRD §2.9 tier 6 lists "the wash-check freshness gate on pack-run creation" among food-safety gates surfacing as "`ERR_WASH_CHECK_STALE`", while tier 8 lists "the pack-line schedule overlap check" among temporal-window failures surfacing as "`ERR_LINE_SCHEDULE_CONFLICT`".

        Design: Difficulty/priority_pair_validation_conflict/safety_outranks_temporal_on_run_create
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower Eleven", grower_code="G-ELEVEN", shed_name="Shed K",
            lot_weight_cwt=1000.00, set_clock_to="2026-08-02T00:00:00Z",
        )
        l = ctx["lot"]
        assess_lot(l["id"], l["version"], us1_pct=70.0, us2_pct=20.0, cull_pct=10.0,
                   cumulative_shrink_cwt=0.00)
        contract = create_contract(committed_volume_cwt=600.00, price_cents_per_cwt=2000,
                                   buyer_name="Buyer I")
        o1 = create_order(ctx["shed"]["id"], contract_id=contract["id"],
                          requested_packed_cwt=100.00)
        allocate_order(o1["id"])
        o2 = create_order(ctx["shed"]["id"], contract_id=contract["id"],
                          requested_packed_cwt=100.00)
        allocate_order(o2["id"])
        set_clock("2026-08-10T00:00:00Z")
        record_pass_wash(ctx["shed"]["id"], "2026-08-09T20:00:00Z")
        # R1 on O1: PASS 4h old, fresh under the NORMAL 12h window.
        create_scheduled_run(o1["id"], "2026-08-10T08:00:00Z", "2026-08-10T10:00:00Z")
        # Two mild FAILs drive the shed RESTRICTED (freshness window now 4h).
        record_fail_wash(ctx["shed"]["id"], "2026-08-10T00:30:00Z")
        record_fail_wash(ctx["shed"]["id"], "2026-08-10T00:45:00Z")
        set_clock("2026-08-10T01:00:00Z")  # last PASS is 5h old — stale under RESTRICTED

        # The 09:00-11:00 window also overlaps R1's 08:00-10:00 schedule, but the
        # food-safety gate (tier 6) surfaces before the temporal check (tier 8).
        resp = api.create_pack_run(
            o2["id"],
            {"scheduled_start": "2026-08-10T09:00:00Z", "scheduled_end": "2026-08-10T11:00:00Z"},
            SUPERVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_WASH_CHECK_STALE)

        order = refresh_order(o2["id"])
        assert order["status"] == "ALLOCATED"  # unchanged
        runs, meta = validate_paginated(api.list_pack_runs(o2["id"], SUPERVISOR))
        assert runs == []  # no run was created for O2


class TestRunCloseValidation:
    def test_draw_imbalance_rejected(self, api):
        """PRD §3.5: "Within each draw the weights must balance: the raw drawn must equal the packed plus the cull, and the US No. 1 plus US No. 2 portions must equal the packed; any imbalance, any duplicated lot within a single run, or an empty draw list on a completing close is `ERR_RUN_DRAW_IMBALANCE`."

        Design: Corner/validations/c_run_close_draw_imbalance_returns_422
        """
        ctx = _packing_ctx(api)
        resp = api.close_pack_run(
            ctx["run"]["id"],
            {"outcome": "COMPLETED", "draws": [make_draw(
                ctx["lot"]["id"], 100.00, 70.00, 60.00, 10.00, 20.00, "WASTE"
            )]},
            SUPERVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_RUN_DRAW_IMBALANCE)  # 100.00 != 70.00 + 20.00
        run = get_success_data(api.get_pack_run(ctx["run"]["id"], SUPERVISOR))
        assert run["status"] == "SCHEDULED"
        lot = refresh_lot(ctx["lot"]["id"])
        assert abs(lot["available_cwt"] - 500.00) <= 0.005
        assert abs(lot["reserved_cwt"] - 100.00) <= 0.005

    def test_draw_exceeding_reservation_rejected(self, api):
        """PRD §3.5: "Each draw's lot must hold an active reservation on the order and the draw's `raw_drawn_cwt` must not exceed the reserved raw amount; a draw without a reservation, or one that exceeds it, is `ERR_RUN_DRAW_EXCEEDS_RESERVATION`."

        Design: Corner/validations/c_run_close_draw_exceeds_reservation_returns_422
        """
        ctx = _packing_ctx(api)
        # Balanced draw (80.01 + 20.00 == 100.01; 70.00 + 10.01 == 80.01) but over the 100.00 reservation.
        resp = api.close_pack_run(
            ctx["run"]["id"],
            {"outcome": "COMPLETED", "draws": [make_draw(
                ctx["lot"]["id"], 100.01, 80.01, 70.00, 10.01, 20.00, "WASTE"
            )]},
            SUPERVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_RUN_DRAW_EXCEEDS_RESERVATION)

    def test_aggregate_grade_spec_gate(self, api):
        """PRD §3.5: "Across the whole run, the aggregate US No. 1 share — the total `us1_cwt` divided by the total `packed_cwt`, expressed as a percentage — must meet or exceed the order's `grade_min_us1_pct`; falling short is `ERR_GRADE_SPEC_NOT_MET`."

        Design: Corner/validations/c_run_close_grade_spec_gate_returns_422
        """
        ctx = _packing_ctx(api)
        # 30/75 = 40% < 50.0% grade floor; each draw is balanced and within reservation.
        resp = api.close_pack_run(
            ctx["run"]["id"],
            {"outcome": "COMPLETED", "draws": [make_draw(
                ctx["lot"]["id"], 100.00, 75.00, 30.00, 45.00, 25.00, "WASTE"
            )]},
            SUPERVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_GRADE_SPEC_NOT_MET)
        run = get_success_data(api.get_pack_run(ctx["run"]["id"], SUPERVISOR))
        assert run["status"] == "SCHEDULED"
        order = refresh_order(ctx["order"]["id"])
        assert order["status"] == "PACKING"
        lot = refresh_lot(ctx["lot"]["id"])
        assert abs(lot["available_cwt"] - 500.00) <= 0.005


def _packing_ctx(api):
    """Allocated order (requested 75.00, reservation raw 100.00 at default blend 0.75)
    with a fresh PASS wash check and a SCHEDULED run."""
    from test_helpers import setup_packing_order_with_run
    return setup_packing_order_with_run(lot_weight_cwt=500.00, committed_cwt=300.00,
                                        requested_packed_cwt=75.00)


class TestRunTerminalState:
    def test_close_twice_returns_run_invalid_state(self, api):
        """PRD §3.5: "Only a `SCHEDULED` run can be closed; anything else is `ERR_RUN_INVALID_STATE`."
        PRD §3.5: "When the outcome is `ABORTED`, no draws are recorded, the run transitions to `ABORTED`, and the order drops back from `PACKING` to `ALLOCATED` as a compensating action — reservations and lot weights are unchanged."

        Design: Corner/state_machines/c_run_close_twice_returns_run_invalid_state
        """
        ctx = _packing_ctx(api)
        abort_run(ctx["run"]["id"])

        resp = api.close_pack_run(
            ctx["run"]["id"],
            {"outcome": "COMPLETED", "draws": [make_draw(
                ctx["lot"]["id"], 100.00, 75.00, 60.00, 15.00, 25.00, "WASTE"
            )]},
            SUPERVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_RUN_INVALID_STATE)
        lot = refresh_lot(ctx["lot"]["id"])
        assert abs(lot["packed_total_cwt"] - 0.00) <= 0.005  # no draw applied
        order = refresh_order(ctx["order"]["id"])
        assert order["status"] == "ALLOCATED"


class TestDrawReverseReachability:
    def test_draw_listed_under_both_parents(self, api):
        """PRD §3.10: "Run draws are listed two ways — under the run (reverse-reaching each draw's `pack_run_id`) or under the lot (reverse-reaching each draw's `field_lot_id`)."

        Design: Corner/entities/c_lot_draw_reverse_reachability_both_parents
        """
        ctx = _packing_ctx(api)
        complete_run(ctx["run"]["id"], [make_draw(
            ctx["lot"]["id"], 100.00, 75.00, 60.00, 15.00, 25.00, "WASTE"
        )])

        run_draws, _ = validate_paginated(api.list_run_draws(ctx["run"]["id"], SUPERVISOR))
        lot_draws, _ = validate_paginated(api.list_lot_draws(ctx["lot"]["id"], STORAGE))

        assert len(run_draws) == 1 and len(lot_draws) == 1
        assert run_draws[0]["field_lot_id"] == ctx["lot"]["id"]
        assert lot_draws[0]["pack_run_id"] == ctx["run"]["id"]
        assert run_draws[0]["id"] == lot_draws[0]["id"]  # the same record
        draw = run_draws[0]
        assert abs(draw["raw_drawn_cwt"] - 100.00) <= 0.005
        assert abs(draw["packed_cwt"] - 75.00) <= 0.005
        assert abs(draw["us1_cwt"] - 60.00) <= 0.005
        assert abs(draw["us2_cwt"] - 15.00) <= 0.005
        assert abs(draw["cull_cwt"] - 25.00) <= 0.005
        assert draw["cull_channel"] == "WASTE"
