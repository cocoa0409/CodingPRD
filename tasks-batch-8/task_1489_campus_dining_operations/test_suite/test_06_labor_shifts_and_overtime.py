"""Labor shifts: PLANNED/ASSIGNED initial states, overlap and rest guards,
worked-minutes bounds, terminal no-show, and weekly overtime allocation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    complete_shift,
    confirm_shift,
    create_completed_shift,
    create_hall,
    create_shift,
    get_shift,
    validate_error,
    validate_success,
)

HALL_MANAGER = TEST_USERS["hall_manager_headers"]


class TestPlannedInitialState:
    def test_shift_without_staff_ref_starts_planned_then_assigns(self, api):
        """PRD §3.5: "The `staff_ref` — an opaque staff identifier — is optional
        at creation: a shift created without it starts `PLANNED`, while one
        created with it starts `ASSIGNED` immediately, and in the latter case
        the assignment checks below run at creation time."

        Design: Corner/state_machines/labor_shift_planned_initial_then_assign
        """
        hall = create_hall(name="Hall SM11")
        shift = create_shift(hall["id"], staff_ref=None, role="DISHWASHER",
                             shift_date="2026-08-14", start_minute=960,
                             end_minute=1200, hourly_rate_cents=1800)
        assert shift["status"] == "PLANNED"
        assert shift["staff_ref"] is None

        assigned = validate_success(api.assign_labor_shift(
            shift["id"], {"staff_ref": "S11"}, HALL_MANAGER))
        assert assigned["status"] == "ASSIGNED"
        assert assigned["staff_ref"] == "S11"


class TestNoShowTerminal:
    def test_complete_after_no_show_rejected(self, api):
        """PRD §3.5: "A confirmed shift resolves in one of two terminal ways:
        completion or no-show."
        PRD §3.5: "Until completion, all four computed fields —
        `regular_minutes`, `overtime_minutes`, `regular_pay_cents`,
        `overtime_pay_cents` — rest at 0, and `worked_minutes` is null."
        PRD §2.7: "4. **State** — the target entity sits in one of the
        transition's from-states (`ERR_INVALID_STATE`), and the cross-entity
        state gates live at this same tier: `ERR_HALL_SUSPENDED` when an
        operation requires an `ACTIVE` hall, `ERR_CONTRACT_NOT_ACTIVE` when a
        statement operation requires an `ACTIVE` contract,
        `ERR_FORECAST_LOCKED_PERIOD` when a forecast operation requires a
        `SCHEDULED` period, `ERR_PENDING_WASTE_LOGS` when a period close finds
        unposted waste, and `ERR_INSPECTION_INCOMPLETE` when a report close
        finds unverified actions."

        Design: Corner/state_machines/labor_shift_no_show_terminal_lockdown
        """
        hall = create_hall(name="Hall SM7")
        shift = create_shift(hall["id"], staff_ref="S7", role="CASHIER",
                             shift_date="2026-08-12", start_minute=600,
                             end_minute=900, hourly_rate_cents=1800)
        confirm_shift(shift["id"])
        no_show = validate_success(api.mark_labor_shift_no_show(shift["id"],
                                                                HALL_MANAGER))
        assert no_show["status"] == "NO_SHOW"

        resp = api.complete_labor_shift(shift["id"], {"worked_minutes": 300},
                                        HALL_MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_shift(shift["id"])
        assert after["status"] == "NO_SHOW"
        assert after["regular_minutes"] == 0
        assert after["overtime_minutes"] == 0


class TestWorkedMinutesBounds:
    def test_grace_bound_inclusive(self, api):
        """PRD §3.5: "Completion (`CONFIRMED` → `COMPLETED`) takes a
        `worked_minutes` input — at least 1 and at most the scheduled length
        (end minute minus start minute) plus a 60-minute grace, otherwise
        `ERR_VALIDATION` — and triggers the weekly overtime allocation."

        Design: Corner/validations/shift_worked_minutes_bounds
        """
        hall = create_hall(name="Hall V3")
        shift = create_shift(hall["id"], staff_ref="SV3", role="SERVER",
                             shift_date="2026-08-13", start_minute=480,
                             end_minute=960, hourly_rate_cents=1800)
        confirm_shift(shift["id"])

        resp = api.complete_labor_shift(shift["id"], {"worked_minutes": 541},
                                        HALL_MANAGER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        assert get_shift(shift["id"])["status"] == "CONFIRMED"

        completed = complete_shift(shift["id"], 540)
        assert completed["status"] == "COMPLETED", (
            "540 == scheduled 480 + 60 grace, the inclusive bound")
        assert completed["regular_minutes"] == 540
        assert completed["overtime_minutes"] == 0


class TestRestBufferBoundary:
    def test_gap_below_480_rejected_and_exactly_480_allowed(self, api):
        """PRD §3.5: "The **rest guard**: for every prior shift of the same
        `staff_ref` in `ASSIGNED`, `CONFIRMED`, or `COMPLETED` status that ends
        before the new shift starts, the gap between the prior shift's end and
        the new shift's start — computed on an absolute minute timeline where a
        minute's absolute position is the day offset times 1,440 plus the
        minute-of-day — must be at least 480 minutes, with a gap of exactly 480
        minutes allowed; a tighter turn-around is refused with
        `ERR_REST_PERIOD_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/labor_shift_rest_buffer_boundary
        """
        hall = create_hall(name="Hall OV2")
        # Prior shift: 2026-08-10 [780, 1320) ASSIGNED.
        create_shift(hall["id"], staff_ref="S9", role="COOK",
                     shift_date="2026-08-10", start_minute=780, end_minute=1320,
                     hourly_rate_cents=1800)

        # Gap = (1440 - 1320) + 300 = 420 < 480.
        resp = api.create_labor_shift(
            {"dining_hall_id": hall["id"], "staff_ref": "S9", "role": "COOK",
             "shift_date": "2026-08-11", "start_minute": 300, "end_minute": 600,
             "hourly_rate_cents": 1800},
            HALL_MANAGER)
        validate_error(resp, ApiErrorId.ERR_REST_PERIOD_VIOLATION)

        # Gap = (1440 - 1320) + 360 = 480 exactly — boundary inclusive.
        ok = validate_success(api.create_labor_shift(
            {"dining_hall_id": hall["id"], "staff_ref": "S9", "role": "COOK",
             "shift_date": "2026-08-11", "start_minute": 360, "end_minute": 600,
             "hourly_rate_cents": 1800},
            HALL_MANAGER), expected_status=201)
        assert ok["status"] == "ASSIGNED"

    def test_same_day_interval_overlap_rejected(self, api):
        """PRD §3.5: "The **overlap guard**: no other shift of the same
        `staff_ref` in `ASSIGNED`, `CONFIRMED`, or `COMPLETED` status may have a
        half-open interval on the same `shift_date` that intersects the new
        interval — because the intervals are half-open, one shift ending exactly
        when another begins is not an overlap — and a violation is refused with
        `ERR_SHIFT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/labor_shift_rest_buffer_boundary
        """
        hall = create_hall(name="Hall OV2")
        create_shift(hall["id"], staff_ref="S9", role="COOK",
                     shift_date="2026-08-10", start_minute=780, end_minute=1320,
                     hourly_rate_cents=1800)
        resp = api.create_labor_shift(
            {"dining_hall_id": hall["id"], "staff_ref": "S9", "role": "COOK",
             "shift_date": "2026-08-10", "start_minute": 800, "end_minute": 1000,
             "hourly_rate_cents": 1800},
            HALL_MANAGER)
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)


class TestOvertimeThresholdExactly2400:
    def _setup_week(self, api):
        """Staff S1: Mon–Thu 2026-08-03..06, 600 worked minutes each (running
        total 2400 exactly), plus a CONFIRMED Friday 120-minute shift."""
        hall = create_hall(name="Hall OTB")
        completed = []
        for day in ("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06"):
            completed.append(create_completed_shift(
                hall["id"], staff_ref="S1", role="SERVER", shift_date=day,
                start_minute=480, end_minute=1080, hourly_rate_cents=2000,
                worked_minutes=600))
        friday = create_shift(hall["id"], staff_ref="S1", role="SERVER",
                              shift_date="2026-08-07", start_minute=480,
                              end_minute=600, hourly_rate_cents=2000)
        confirm_shift(friday["id"])
        return hall, completed, friday

    def test_shift_landing_on_exactly_2400_contributes_no_overtime(self, api):
        """PRD §3.5: "A shift that brings the running total to exactly 2,400
        minutes contributes zero overtime — only minutes strictly beyond the
        threshold are overtime."

        Design: Difficulty/boundary_precision_check/overtime_threshold_exactly_2400_minutes
        """
        _hall, completed, _friday = self._setup_week(api)
        thursday = completed[-1]
        assert thursday["regular_minutes"] == 600
        assert thursday["overtime_minutes"] == 0, (
            "accumulator ends at exactly 2400; the boundary minute is not OT")

    def test_minutes_beyond_2400_are_all_overtime(self, api):
        """PRD §3.5: "The shift's pay fields then materialize:
        `regular_pay_cents` is `regular_minutes` times `hourly_rate_cents`
        divided by 60, rounded half-up to whole cents, and `overtime_pay_cents`
        is `overtime_minutes` times `hourly_rate_cents` times 1.5 divided by 60,
        rounded half-up to whole cents."

        Design: Difficulty/boundary_precision_check/overtime_threshold_exactly_2400_minutes
        """
        _hall, _completed, friday = self._setup_week(api)
        done = complete_shift(friday["id"], 120)
        assert done["regular_minutes"] == 0
        assert done["overtime_minutes"] == 120, (
            "accumulator already at 2400, so all 120 minutes are OT")
        assert done["regular_pay_cents"] == 0
        assert done["overtime_pay_cents"] == 6000, (
            "round_half_up(120 * 2000 * 1.5 / 60)")


class TestOvertimeSplitShiftEvaluationOrder:
    def _setup_split_week(self, api):
        """Staff S2: Mon–Thu 540 worked minutes each (running total 2160), plus
        a CONFIRMED Friday 480-minute shift."""
        hall = create_hall(name="Hall OT")
        completed = []
        for day in ("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06"):
            completed.append(create_completed_shift(
                hall["id"], staff_ref="S2", role="COOK", shift_date=day,
                start_minute=480, end_minute=1020, hourly_rate_cents=2000,
                worked_minutes=540))
        friday = create_shift(hall["id"], staff_ref="S2", role="COOK",
                              shift_date="2026-08-07", start_minute=480,
                              end_minute=960, hourly_rate_cents=2000)
        confirm_shift(friday["id"])
        return hall, completed, friday

    def test_friday_shift_splits_at_threshold(self, api):
        """PRD §3.5: "The set is walked in a pinned order — by `shift_date`
        ascending, then `start_minute` ascending, then `created_at` ascending —
        with a running total of minutes worked. For each shift in that walk, its
        regular portion is the smaller of its `worked_minutes` and the room
        remaining under the 2,400-minute weekly threshold (forty hours) after
        the running total, floored at zero; its overtime portion is whatever
        `worked_minutes` remain beyond the regular portion; then its minutes
        accumulate into the running total."

        Design: Difficulty/combinatorial_formula/overtime_split_shift_evaluation_order
        """
        _hall, _completed, friday = self._setup_split_week(api)
        done = complete_shift(friday["id"], 480)
        # 2160 + 240 reaches exactly 2400; the remaining 240 are OT.
        assert done["regular_minutes"] == 240
        assert done["overtime_minutes"] == 240
        assert done["regular_pay_cents"] == 8000, "240 * 2000 / 60"
        assert done["overtime_pay_cents"] == 12000, (
            "round_half_up(240 * 2000 * 1.5 / 60)")

    def test_earlier_completions_not_retroactively_adjusted(self, api):
        """PRD §3.5: "Because completion order need not match chronological
        order, only the just-completed shift is re-scored; earlier `COMPLETED`
        shifts keep the split frozen at their own completion time and are never
        retroactively adjusted."

        Design: Difficulty/combinatorial_formula/overtime_split_shift_evaluation_order
        """
        _hall, completed, friday = self._setup_split_week(api)
        complete_shift(friday["id"], 480)
        monday = get_shift(completed[0]["id"])
        assert monday["regular_minutes"] == 540
        assert monday["overtime_minutes"] == 0, (
            "Monday's split stays frozen after Friday's completion")
