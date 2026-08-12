"""Cure cycles: scheduling geometry, envelope rules, cure log scoring, cascades."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_cure_cycle_payload,
    create_cure_equipment_payload,
    create_layup_session_payload,
    create_mold,
    create_work_order_payload,
    demold,
    record_session,
    release_work_order,
    run_cure,
    schedule_cure,
    set_clock,
    setup_shop,
    setup_work_order_awaiting_cure,
    setup_work_order_cured,
    setup_work_order_in_layup,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

LAM = TEST_USERS["laminator_headers"]
CT = TEST_USERS["cure_technician_headers"]
SM = TEST_USERS["shop_manager_headers"]
TE = TEST_USERS["tooling_engineer_headers"]


class TestCureDeviationScore:
    def _setup_running(self, api):
        ctx = setup_work_order_awaiting_cure(
            mold_overrides={"mold_code": "MOLD-C1", "tooling_phase": "PRODUCTION"},
            work_order_overrides={"work_order_no": "WO-C1"},
            batch_overrides={"batch_code": "BATCH-C1"},
        )
        cycle = schedule_cure(ctx)
        validate_success(api.start_cure_cycle(cycle["id"], CT), 200)
        return ctx, cycle

    def test_multifactor_score_computed(self, api):
        """PRD §3.5: "Three penalty terms are summed — a temperature term of twice
        the amount by which the absolute gap between `recorded_max_temp_c` and the
        programmed `soak_temp_c` exceeds ten degrees (no penalty within ten), a soak
        term of one-and-a-half times the shortfall of `recorded_soak_minutes` below
        the programmed `soak_minutes` (no penalty when the soak was met or exceeded),
        and a ramp term equal to the amount by which the absolute gap between
        `recorded_ramp_rate_c_per_min` and the programmed `ramp_rate_c_per_min`
        exceeds half a degree per minute (no penalty within that slack) — and the
        total, rounded half-up to one decimal place, is stored as
        `cure_deviation_score`."
        Program 180 C / 120 min / 3.0 vs log max 184 / soak 116 / ramp 4.2:
        temp dead-zone (4 <= 10) -> 0; soak 1.5 * 4 = 6.0; ramp 1.0 * 0.7 = 0.7;
        score 6.7.

        Design: Difficulty/combinatorial_formula/cure_deviation_score_multifactor_branching
        """
        _, cycle = self._setup_running(api)
        completed = validate_success(
            api.complete_cure_cycle(
                cycle["id"],
                {
                    "recorded_min_temp_c": 178,
                    "recorded_max_temp_c": 184,
                    "recorded_soak_minutes": 116,
                    "recorded_ramp_rate_c_per_min": 4.2,
                },
                CT,
            ),
            200,
        )
        assert completed["cure_deviation_score"] == pytest.approx(6.7, abs=1e-9)
        assert completed["cure_log_ok"] is False
        assert completed["status"] == "COMPLETED"

    def test_failed_cure_loops_work_order_back(self, api):
        """PRD §3.5: "a failing completion still completes the cycle but loops the
        work order back from `IN_CURE` to `AWAITING_CURE` for another cure." and
        "otherwise `cure_log_ok` holds when the score is no greater than 5.0, with
        exactly 5.0 passing" — 6.7 exceeds the gate.

        Design: Difficulty/combinatorial_formula/cure_deviation_score_multifactor_branching
        """
        ctx, cycle = self._setup_running(api)
        validate_success(
            api.complete_cure_cycle(
                cycle["id"],
                {
                    "recorded_min_temp_c": 178,
                    "recorded_max_temp_c": 184,
                    "recorded_soak_minutes": 116,
                    "recorded_ramp_rate_c_per_min": 4.2,
                },
                CT,
            ),
            200,
        )
        order = validate_success(api.get_work_order(ctx["work_order"]["id"], CT), 200)
        assert order["status"] == "AWAITING_CURE"


class TestCureAutoReject:
    def test_cure_auto_reject_overtemp_branch(self, api):
        """PRD §3.5: "An auto-reject rule is evaluated first: if
        `recorded_max_temp_c` ran more than eight degrees above the programmed soak
        temperature, `cure_log_ok` is false regardless of the score". Recorded max
        189 vs soak 180 is an excursion of 9 (> 8), yet inside the ten-degree score
        dead-zone, so the score is 0.0 while the log still fails.

        Design: Corner/calculations/cure_auto_reject_overtemp_branch
        """
        ctx = setup_work_order_awaiting_cure(
            mold_overrides={"mold_code": "MOLD-AR1", "tooling_phase": "PRODUCTION"},
            work_order_overrides={"work_order_no": "WO-AR1"},
            batch_overrides={"batch_code": "BATCH-AR1"},
        )
        cycle = schedule_cure(ctx)
        validate_success(api.start_cure_cycle(cycle["id"], CT), 200)
        completed = validate_success(
            api.complete_cure_cycle(
                cycle["id"],
                {
                    "recorded_min_temp_c": 180,
                    "recorded_max_temp_c": 189,
                    "recorded_soak_minutes": 120,
                    "recorded_ramp_rate_c_per_min": 3.0,
                },
                CT,
            ),
            200,
        )
        assert completed["cure_deviation_score"] == pytest.approx(0.0, abs=1e-9)
        assert completed["cure_log_ok"] is False


class TestAbort:
    def test_curecycle_abort_reverts_workorder_without_mold_wear(
        self, api, tooling_engineer_headers
    ):
        """PRD §3.5: "Aborting a running cycle moves it to `ABORTED` and likewise
        returns the work order to `AWAITING_CURE`." and "only a completed cycle with
        `uses_mold` true adds one to the mold's `cycles_since_maintenance`, possibly
        tipping it into `MAINTENANCE_DUE` per §3.2, while an aborted run causes no
        wear at all."

        Design: Corner/state_machines/curecycle_abort_reverts_workorder_without_mold_wear
        """
        ctx = setup_work_order_awaiting_cure(
            mold_overrides={"mold_code": "MOLD-AB1", "tooling_phase": "PRODUCTION"},
            work_order_overrides={"work_order_no": "WO-AB1"},
            batch_overrides={"batch_code": "BATCH-AB1"},
        )
        cycle = schedule_cure(ctx)
        validate_success(api.start_cure_cycle(cycle["id"], CT), 200)
        aborted = validate_success(api.abort_cure_cycle(cycle["id"], CT), 200)
        assert aborted["status"] == "ABORTED"
        order = validate_success(api.get_work_order(ctx["work_order"]["id"], CT), 200)
        assert order["status"] == "AWAITING_CURE"
        mold = validate_success(api.get_mold(ctx["mold"]["id"], tooling_engineer_headers), 200)
        assert mold["cycles_since_maintenance"] == 0
        assert mold["status"] == "ACTIVE"


class TestCureSchedulingValidation:
    def test_pressure_on_oven_rejected(self, api):
        """PRD §3.5: "Pressure is conditional: `pressure_bar` is required on
        autoclaves and must not exceed `max_pressure_bar`, and it must be absent
        entirely on ovens; any of the three violations is
        `ERR_PRESSURE_REQUIRES_AUTOCLAVE`."

        Design: Corner/validations/pressure_on_oven_rejected
        """
        ctx = setup_work_order_awaiting_cure(
            mold_overrides={"mold_code": "MOLD-PR2", "tooling_phase": "PRODUCTION"},
            work_order_overrides={"work_order_no": "WO-PR2"},
            batch_overrides={"batch_code": "BATCH-PR2"},
        )
        res = api.create_cure_cycle(
            create_cure_cycle_payload(
                ctx["work_order"]["id"], ctx["oven"]["id"], pressure_bar=5.0
            ),
            CT,
        )
        validate_error(res, ApiErrorId.ERR_PRESSURE_REQUIRES_AUTOCLAVE, expected_status=422)

    def test_cure_envelope_exceeded_rejected(self, api):
        """PRD §3.5: "a strictly positive `soak_temp_c` bounded above by the
        equipment's `max_temperature_c` (violations are `ERR_CURE_ENVELOPE_EXCEEDED`)".
        The oven tops out at 200 °C; a 250 °C soak is refused.

        Design: Corner/validations/cure_envelope_exceeded_rejected
        """
        ctx = setup_work_order_awaiting_cure(
            mold_overrides={"mold_code": "MOLD-CE1", "tooling_phase": "PRODUCTION"},
            work_order_overrides={"work_order_no": "WO-CE1"},
            batch_overrides={"batch_code": "BATCH-CE1"},
        )
        res = api.create_cure_cycle(
            create_cure_cycle_payload(
                ctx["work_order"]["id"], ctx["oven"]["id"], soak_temp_c=250
            ),
            CT,
        )
        validate_error(res, ApiErrorId.ERR_CURE_ENVELOPE_EXCEEDED, expected_status=422)

    def test_invalid_window_rejected(self, api):
        """PRD §3.5: "a window from `scheduled_start` to a strictly later
        `scheduled_end` (otherwise `ERR_INVALID_WINDOW`)". Equal endpoints are not
        strictly later.

        Design: Corner/validations/invalid_window_rejected
        """
        ctx = setup_work_order_awaiting_cure(
            mold_overrides={"mold_code": "MOLD-IW1", "tooling_phase": "PRODUCTION"},
            work_order_overrides={"work_order_no": "WO-IW1"},
            batch_overrides={"batch_code": "BATCH-IW1"},
        )
        res = api.create_cure_cycle(
            create_cure_cycle_payload(
                ctx["work_order"]["id"],
                ctx["oven"]["id"],
                scheduled_start="2026-06-01T12:00:00Z",
                scheduled_end="2026-06-01T12:00:00Z",
            ),
            CT,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_WINDOW, expected_status=422)


class TestTurnaroundBuffer:
    def _setup_autoclave_three_orders(self, api):
        """Three orders at AWAITING_CURE; autoclave AC-1 turnaround 30 min."""
        shop = setup_shop(
            mold_overrides={"mold_code": "MOLD-TA1", "tooling_phase": "PRODUCTION"},
        )
        mold2 = create_mold(mold_code="MOLD-TA2", tooling_phase="PRODUCTION")
        mold3 = create_mold(mold_code="MOLD-TA3", tooling_phase="PRODUCTION")
        ac = validate_success(
            api.create_cure_equipment(
                create_cure_equipment_payload(
                    equipment_code="AC-1",
                    kind="AUTOCLAVE",
                    max_parts_per_cycle=5,
                    turnaround_minutes=30,
                    max_temperature_c=250,
                    max_pressure_bar=7,
                ),
                SM,
            ),
            201,
        )
        from test_helpers import create_batch

        batch = create_batch(batch_code="BATCH-TA1")
        orders = []
        for mold, no in ((shop["mold"], "WO-TA1"), (mold2, "WO-TA2"), (mold3, "WO-TA3")):
            order = validate_success(
                api.create_work_order(
                    create_work_order_payload(
                        mold["id"], shop["ply_book"]["id"], work_order_no=no
                    ),
                    SM,
                ),
                201,
            )
            validate_success(api.start_layup(order["id"], LAM), 200)
            validate_success(
                api.create_layup_session(
                    create_layup_session_payload(order["id"], batch["id"], resin_used_g=100),
                    LAM,
                ),
                201,
            )
            validate_success(api.complete_layup(order["id"], LAM), 200)
            orders.append(order)
        return {"shop": shop, "autoclave": ac, "orders": orders}

    def test_autoclave_turnaround_buffer_enforced(self, api):
        """PRD §2.10: "Second, turnaround: on `AUTOCLAVE` equipment the new window
        must either start no earlier than each existing window's `scheduled_end`
        plus the equipment's `turnaround_minutes`, or end — with its own turnaround
        added — no later than that window's `scheduled_start`; a start exactly equal
        to a buffered end passes." A start 15 minutes after the prior end is
        refused; a start exactly 30 minutes after is admitted.

        Design: Corner/validations/autoclave_turnaround_buffer_enforced
        """
        ctx = self._setup_autoclave_three_orders(api)
        ac_id = ctx["autoclave"]["id"]
        cc1 = validate_success(
            api.create_cure_cycle(
                create_cure_cycle_payload(
                    ctx["orders"][0]["id"],
                    ac_id,
                    scheduled_start="2026-06-01T12:00:00Z",
                    scheduled_end="2026-06-01T14:00:00Z",
                    pressure_bar=5.0,
                ),
                CT,
            ),
            201,
        )
        assert cc1["status"] == "SCHEDULED"
        res = api.create_cure_cycle(
            create_cure_cycle_payload(
                ctx["orders"][1]["id"],
                ac_id,
                scheduled_start="2026-06-01T14:15:00Z",
                scheduled_end="2026-06-01T15:00:00Z",
                pressure_bar=5.0,
            ),
            CT,
        )
        validate_error(res, ApiErrorId.ERR_TURNAROUND_BUFFER_VIOLATION, expected_status=409)
        cc3 = validate_success(
            api.create_cure_cycle(
                create_cure_cycle_payload(
                    ctx["orders"][2]["id"],
                    ac_id,
                    scheduled_start="2026-06-01T14:30:00Z",
                    scheduled_end="2026-06-01T16:00:00Z",
                    pressure_bar=5.0,
                ),
                CT,
            ),
            201,
        )
        assert cc3["status"] == "SCHEDULED"


class TestAggregateCapacity:
    def _setup_three_awaiting(self, api):
        """Three quantity-2 orders at AWAITING_CURE; oven capacity 3."""
        shop = setup_shop(
            mold_overrides={"mold_code": "MOLD-E1", "tooling_phase": "PRODUCTION"},
        )
        mold2 = create_mold(mold_code="MOLD-E2", tooling_phase="PRODUCTION")
        mold3 = create_mold(mold_code="MOLD-E3", tooling_phase="PRODUCTION")
        oven = validate_success(
            api.create_cure_equipment(
                create_cure_equipment_payload(
                    equipment_code="OVEN-CAP", max_parts_per_cycle=3
                ),
                SM,
            ),
            201,
        )
        from test_helpers import create_batch

        batch = create_batch(batch_code="BATCH-E1")
        orders = []
        for mold, no in ((shop["mold"], "WO-A1"), (mold2, "WO-B1"), (mold3, "WO-C1")):
            order = validate_success(
                api.create_work_order(
                    create_work_order_payload(
                        mold["id"],
                        shop["ply_book"]["id"],
                        work_order_no=no,
                        quantity=2,
                    ),
                    SM,
                ),
                201,
            )
            validate_success(api.start_layup(order["id"], LAM), 200)
            validate_success(
                api.create_layup_session(
                    create_layup_session_payload(order["id"], batch["id"], resin_used_g=100),
                    LAM,
                ),
                201,
            )
            validate_success(api.complete_layup(order["id"], LAM), 200)
            orders.append(order)
        return {"oven": oven, "orders": orders}

    def test_half_open_adjacent_windows_admitted(self, api):
        """PRD §2.10: "Cure cycles reserve half-open windows on their equipment:
        `scheduled_start` is inclusive and `scheduled_end` is exclusive, so a cycle
        beginning exactly when another ends does not overlap it, and the end must be
        strictly after the start."

        Design: Difficulty/resource_temporal_overlap/equipment_aggregate_capacity_half_open_adjacency
        """
        ctx = self._setup_three_awaiting(api)
        oven_id = ctx["oven"]["id"]
        cc_a = validate_success(
            api.create_cure_cycle(
                create_cure_cycle_payload(
                    ctx["orders"][0]["id"],
                    oven_id,
                    scheduled_start="2026-06-01T12:00:00Z",
                    scheduled_end="2026-06-01T14:00:00Z",
                ),
                CT,
            ),
            201,
        )
        assert cc_a["status"] == "SCHEDULED"
        cc_b = validate_success(
            api.create_cure_cycle(
                create_cure_cycle_payload(
                    ctx["orders"][1]["id"],
                    oven_id,
                    scheduled_start="2026-06-01T14:00:00Z",
                    scheduled_end="2026-06-01T16:00:00Z",
                ),
                CT,
            ),
            201,
        )
        assert cc_b["status"] == "SCHEDULED"

    def test_straddling_window_exceeds_aggregate_capacity(self, api):
        """PRD §2.10: "First, capacity: the combined `quantity` of the work orders
        on overlapping cycles, plus the new order's `quantity`, must not exceed the
        equipment's `max_parts_per_cycle`." and "Admission control considers only
        cycles in `SCHEDULED` or `RUNNING` status on the same equipment."
        A [13:00, 15:00) window overlaps both two-part windows: 2 + 2 + 2 = 6 > 3.

        Design: Difficulty/resource_temporal_overlap/equipment_aggregate_capacity_half_open_adjacency
        """
        ctx = self._setup_three_awaiting(api)
        oven_id = ctx["oven"]["id"]
        validate_success(
            api.create_cure_cycle(
                create_cure_cycle_payload(
                    ctx["orders"][0]["id"],
                    oven_id,
                    scheduled_start="2026-06-01T12:00:00Z",
                    scheduled_end="2026-06-01T14:00:00Z",
                ),
                CT,
            ),
            201,
        )
        validate_success(
            api.create_cure_cycle(
                create_cure_cycle_payload(
                    ctx["orders"][1]["id"],
                    oven_id,
                    scheduled_start="2026-06-01T14:00:00Z",
                    scheduled_end="2026-06-01T16:00:00Z",
                ),
                CT,
            ),
            201,
        )
        res = api.create_cure_cycle(
            create_cure_cycle_payload(
                ctx["orders"][2]["id"],
                oven_id,
                scheduled_start="2026-06-01T13:00:00Z",
                scheduled_end="2026-06-01T15:00:00Z",
            ),
            CT,
        )
        validate_error(res, ApiErrorId.ERR_EQUIPMENT_CAPACITY_EXCEEDED, expected_status=409)


class TestCureToMoldMaintenanceCascade:
    def _setup_two_cured_orders(self, api):
        """Interval-2 mold; WO-K1 completed one mold-bearing cure and demolded;
        WO-K2's cycle is RUNNING; WO-K3 released. Returns context dict."""
        shop = setup_shop(
            mold_overrides={
                "mold_code": "MOLD-K1",
                "maintenance_interval_cycles": 2,
                "tooling_phase": "PRODUCTION",
            },
            with_oven=True,
        )
        from test_helpers import create_batch

        batch = create_batch(batch_code="BATCH-K1")
        mold_id = shop["mold"]["id"]
        book_id = shop["ply_book"]["id"]

        wo1 = validate_success(
            api.create_work_order(
                create_work_order_payload(mold_id, book_id, work_order_no="WO-K1"), SM
            ),
            201,
        )
        validate_success(api.start_layup(wo1["id"], LAM), 200)
        validate_success(
            api.create_layup_session(
                create_layup_session_payload(wo1["id"], batch["id"], resin_used_g=200), LAM
            ),
            201,
        )
        validate_success(api.complete_layup(wo1["id"], LAM), 200)
        cc1 = validate_success(
            api.create_cure_cycle(
                create_cure_cycle_payload(wo1["id"], shop["oven"]["id"]), CT
            ),
            201,
        )
        run_cure(cc1)
        validate_success(api.demold_work_order(wo1["id"], 2000.0, LAM), 200)

        set_clock("2026-06-01T10:00:01Z")  # strictly after wo1's demold instant
        wo2 = validate_success(
            api.create_work_order(
                create_work_order_payload(mold_id, book_id, work_order_no="WO-K2"), SM
            ),
            201,
        )
        validate_success(api.start_layup(wo2["id"], LAM), 200)
        validate_success(
            api.create_layup_session(
                create_layup_session_payload(wo2["id"], batch["id"], resin_used_g=200), LAM
            ),
            201,
        )
        validate_success(api.complete_layup(wo2["id"], LAM), 200)
        cc2 = validate_success(
            api.create_cure_cycle(
                create_cure_cycle_payload(
                    wo2["id"],
                    shop["oven"]["id"],
                    scheduled_start="2026-06-01T14:00:00Z",
                    scheduled_end="2026-06-01T16:00:00Z",
                ),
                CT,
            ),
            201,
        )
        validate_success(api.start_cure_cycle(cc2["id"], CT), 200)
        wo3 = validate_success(
            api.create_work_order(
                create_work_order_payload(mold_id, book_id, work_order_no="WO-K3"), SM
            ),
            201,
        )
        return {"shop": shop, "cc2": cc2, "wo3": wo3}

    def test_completion_increment_flips_mold_maintenance_due(self, api, tooling_engineer_headers):
        """PRD §3.5: "only a completed cycle with `uses_mold` true adds one to the
        mold's `cycles_since_maintenance`, possibly tipping it into
        `MAINTENANCE_DUE` per §3.2" and PRD §3.2: "when that increment brings the
        counter to `maintenance_interval_cycles` or beyond, the mold moves
        automatically from `ACTIVE` to `MAINTENANCE_DUE`."

        Design: Difficulty/transitive_cascade/cure_complete_to_mold_maintenance_cascade
        """
        ctx = self._setup_two_cured_orders(api)
        validate_success(api.complete_cure_cycle(ctx["cc2"]["id"], _pass_log(), CT), 200)
        mold = validate_success(
            api.get_mold(ctx["shop"]["mold"]["id"], tooling_engineer_headers), 200
        )
        assert mold["cycles_since_maintenance"] == 2
        assert mold["status"] == "MAINTENANCE_DUE"

    def test_cascaded_posture_gates_later_start_layup(self, api):
        """PRD §3.2: "Work order release remains possible on a due mold, but
        start-layup and first-cure scheduling on it now fail with
        `ERR_MOLD_NOT_AVAILABLE`."

        Design: Difficulty/transitive_cascade/cure_complete_to_mold_maintenance_cascade
        """
        ctx = self._setup_two_cured_orders(api)
        validate_success(api.complete_cure_cycle(ctx["cc2"]["id"], _pass_log(), CT), 200)
        res = api.start_layup(ctx["wo3"]["id"], LAM)
        validate_error(res, ApiErrorId.ERR_MOLD_NOT_AVAILABLE, expected_status=409)


def _pass_log():
    from test_helpers import create_cure_log_payload

    return create_cure_log_payload()
