"""Timesheets: pay tiers, meal penalty, shift cap, linkage, and segregation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_timesheet,
    assert_approved_timesheet_breakdown,
    enter_submit_approve_timesheet,
    enter_timesheet,
    get_timesheet_entry,
    list_assignments,
    make_foreman_headers,
    make_payroll_headers,
    register_worker,
    setup_completed_gang,
    submit_timesheet,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)

PAYROLL = TEST_USERS["payroll_headers"]

HOLDMEN_2 = [
    {"full_name": "W One", "registration_number": "R001",
     "classification": "HOLDMAN", "registered_on": "2010-01-01",
     "base_hourly_rate_cents": 4000},
    {"full_name": "W Two", "registration_number": "R002",
     "classification": "HOLDMAN", "registered_on": "2015-06-01",
     "base_hourly_rate_cents": 4000},
]


def _completed_two_man_gang(vessel_name, voyage_number, shift_overrides=None):
    return setup_completed_gang(
        vessel_overrides={"vessel_name": vessel_name, "voyage_number": voyage_number,
                          "planned_moves": 50, "planned_tons": 10,
                          "credit_limit_cents": 500_000_000},
        shift_overrides=shift_overrides,
        gang_overrides={"required_headcount": 2},
        worker_specs=[dict(s) for s in HOLDMEN_2])


class TestOvertimeBoundary:

    def test_exactly_480_minutes_earns_no_overtime(self, api):
        """PRD §3.8: "Overtime therefore accrues only above eight hours — an entry of exactly 480 minutes carries zero overtime — and double time only above twelve hours."
        PRD §3.8: "The minute split: `straight_minutes` is the smaller of `work_minutes` and 480; `ot_minutes` is the amount by which `work_minutes` exceeds 480, capped at 240 and floored at zero; `dt_minutes` is the amount by which `work_minutes` exceeds 720, floored at zero."

        Design: Difficulty/boundary_precision_check/overtime_accrues_above_480_not_at_480
        """
        ns = _completed_two_man_gang("MV Boundary", "B-201")
        ts = enter_submit_approve_timesheet(ns.gang["id"], ns.workers[0]["id"],
                                            ns.foreman_id, work_minutes=480,
                                            meal_break_taken=True)
        assert_approved_timesheet_breakdown(ts)
        assert ts["straight_minutes"] == 480
        assert ts["ot_minutes"] == 0, "exactly 480 earns no overtime"
        assert ts["dt_minutes"] == 0
        assert ts["meal_penalty_minutes"] == 0
        assert ts["gross_pay_cents"] == 32_000, "480 * 4000 / 60"

    def test_481_minutes_pays_one_minute_of_overtime(self, api):
        """PRD §3.8: "Paid minutes weight the components at 1.0 for straight time, 1.5 for overtime, 2.0 for double time, and 1.0 for the meal penalty. `gross_pay_cents` is then the weighted paid minutes multiplied by the effective base and divided by sixty, with a single round-half-up to integer cents at the very end."

        Design: Difficulty/boundary_precision_check/overtime_accrues_above_480_not_at_480
        """
        ns = _completed_two_man_gang("MV Boundary", "B-201")
        ts = enter_submit_approve_timesheet(ns.gang["id"], ns.workers[1]["id"],
                                            ns.foreman_id, work_minutes=481,
                                            meal_break_taken=True)
        assert ts["straight_minutes"] == 480
        assert ts["ot_minutes"] == 1, "one minute past the breakpoint pays 1.5x"
        assert ts["gross_pay_cents"] == 32_100, "(480 + 1.5) * 4000 / 60"


class TestNightShiftCombinatorial:

    def _setup_night_gang_with_timesheets(self):
        ns = _completed_two_man_gang(
            "MV Nights", "N-301",
            shift_overrides={"period": "NIGHT",
                             "start_utc": "2026-08-10T18:00:00Z",
                             "end_utc": "2026-08-11T02:00:00Z"})
        t1 = enter_timesheet(ns.gang["id"], ns.workers[0]["id"], ns.foreman_id,
                             work_minutes=540, meal_break_taken=False)
        t2 = enter_timesheet(ns.gang["id"], ns.workers[1]["id"], ns.foreman_id,
                             work_minutes=540, meal_break_taken=True)
        submit_timesheet(t1["id"], ns.foreman_id)
        submit_timesheet(t2["id"], ns.foreman_id)
        return ns, t1, t2

    def test_night_overtime_with_meal_penalty(self, api):
        """PRD §3.8: "The meal rule: `meal_penalty_minutes` is 60 when `work_minutes` exceeds 300 and `meal_break_taken` is false, and zero otherwise — exactly 300 minutes without a break draws no penalty."
        PRD §3.8: "The rate: the shift's `period` selects a multiplier of 1.00 for `DAY`, 1.10 for `NIGHT`, or 1.20 for `GRAVEYARD`, and the effective hourly base is `rate_cents_snapshot` multiplied by that factor, kept unrounded."

        Design: Difficulty/combinatorial_formula/payroll_tiered_overtime_meal_penalty_night
        """
        _ns, t1, _t2 = self._setup_night_gang_with_timesheets()
        approved = approve_timesheet(t1["id"], "pay-1")
        assert approved["straight_minutes"] == 480
        assert approved["ot_minutes"] == 60
        assert approved["dt_minutes"] == 0
        assert approved["meal_penalty_minutes"] == 60
        # eff base 4000*1.10 = 4400; paid minutes 480 + 90 + 60 = 630.
        assert approved["gross_pay_cents"] == 46_200

    def test_night_overtime_with_meal_break_taken(self, api):
        """PRD §3.8: "Paid minutes weight the components at 1.0 for straight time, 1.5 for overtime, 2.0 for double time, and 1.0 for the meal penalty. `gross_pay_cents` is then the weighted paid minutes multiplied by the effective base and divided by sixty, with a single round-half-up to integer cents at the very end."

        Design: Difficulty/combinatorial_formula/payroll_tiered_overtime_meal_penalty_night
        """
        _ns, t1, t2 = self._setup_night_gang_with_timesheets()
        a1 = approve_timesheet(t1["id"], "pay-1")
        a2 = approve_timesheet(t2["id"], "pay-1")
        assert a2["meal_penalty_minutes"] == 0
        assert a2["gross_pay_cents"] == 41_800, "(480 + 90) * 4400 / 60"
        assert a1["gross_pay_cents"] - a2["gross_pay_cents"] == 4_400, (
            "the delta is exactly 60 minutes at the NIGHT-adjusted base")


class TestMealPenaltyBoundary:

    def test_meal_penalty_requires_more_than_300_minutes(self, api):
        """PRD §3.8: "The meal rule: `meal_penalty_minutes` is 60 when `work_minutes` exceeds 300 and `meal_break_taken` is false, and zero otherwise — exactly 300 minutes without a break draws no penalty."

        Design: Corner/calculations/meal_penalty_requires_more_than_300_minutes
        """
        ns = _completed_two_man_gang("MV Meal", "C-206")
        t300 = enter_submit_approve_timesheet(ns.gang["id"], ns.workers[0]["id"],
                                              ns.foreman_id, work_minutes=300,
                                              meal_break_taken=False)
        assert t300["meal_penalty_minutes"] == 0, "300 is NOT above the threshold"
        assert t300["gross_pay_cents"] == 20_000, "300 * 4000 / 60"

        t301 = enter_submit_approve_timesheet(ns.gang["id"], ns.workers[1]["id"],
                                              ns.foreman_id, work_minutes=301,
                                              meal_break_taken=False)
        assert t301["meal_penalty_minutes"] == 60
        assert t301["gross_pay_cents"] == 24_067, (
            "round_half_up(361 * 4000 / 60)")


class TestDoubleTime:

    def test_double_time_applies_above_720_minutes(self, api):
        """PRD §3.8: "`dt_minutes` is the amount by which `work_minutes` exceeds 720, floored at zero. Overtime therefore accrues only above eight hours — an entry of exactly 480 minutes carries zero overtime — and double time only above twelve hours."

        Design: Corner/calculations/double_time_applies_above_720_minutes
        """
        ns = setup_completed_gang(
            vessel_overrides={"vessel_name": "MV Double", "voyage_number": "C-207",
                              "planned_moves": 10, "planned_tons": 5,
                              "credit_limit_cents": 1_000_000},
            shift_overrides={"start_utc": "2026-08-10T07:00:00Z",
                             "end_utc": "2026-08-10T19:00:00Z"},
            gang_overrides={"required_headcount": 1},
            worker_specs=[dict(HOLDMEN_2[0])])
        ts = enter_submit_approve_timesheet(ns.gang["id"], ns.workers[0]["id"],
                                            ns.foreman_id, work_minutes=780,
                                            meal_break_taken=True)
        assert ts["straight_minutes"] == 480
        assert ts["ot_minutes"] == 240
        assert ts["dt_minutes"] == 60
        # (480 + 240*1.5 + 60*2) * 4000 / 60 = 960 * 4000 / 60
        assert ts["gross_pay_cents"] == 64_000


class TestTimesheetEntryGates:

    def test_timesheet_minutes_exceeding_shift_plus_grace_returns_422(self, api):
        """PRD §3.8: "The entry may not overstate the shift: when `work_minutes` is greater than the shift's duration in minutes plus a 120-minute grace, the entry is rejected with `ERR_TIMESHEET_EXCEEDS_SHIFT` (422) — a value exactly at the cap is accepted."

        Design: Corner/validations/timesheet_minutes_exceeding_shift_plus_grace_returns_422
        """
        ns = setup_completed_gang(
            vessel_overrides={"vessel_name": "MV Long", "voyage_number": "V-304"},
            gang_overrides={"required_headcount": 1},
            worker_specs=[dict(HOLDMEN_2[0])])
        # 480-minute shift: cap is 480 + 120 = 600; 700 is over.
        resp = api_client.create_timesheet_entry(
            {"gang_order_id": ns.gang["id"], "worker_id": ns.workers[0]["id"],
             "work_minutes": 700, "meal_break_taken": True},
            make_foreman_headers(ns.foreman_id))
        validate_error(resp, ApiErrorId.ERR_TIMESHEET_EXCEEDS_SHIFT)

        # Exactly at the cap is accepted.
        ok = api_client.create_timesheet_entry(
            {"gang_order_id": ns.gang["id"], "worker_id": ns.workers[0]["id"],
             "work_minutes": 600, "meal_break_taken": True},
            make_foreman_headers(ns.foreman_id))
        validate_success(ok, 201)

    def test_timesheet_for_worker_not_on_gang_returns_422(self, api):
        """PRD §3.8: "The worker must hold an assignment on that same gang order in `CHECKED_IN`, `WORKING`, or `COMPLETED` status; a timesheet for anyone else is rejected with `ERR_WORKER_NOT_ON_GANG` (422)."

        Design: Corner/validations/timesheet_for_worker_not_on_gang_returns_422
        """
        ns = setup_completed_gang(
            vessel_overrides={"vessel_name": "MV Ref", "voyage_number": "V-303"},
            gang_overrides={"required_headcount": 1},
            worker_specs=[dict(HOLDMEN_2[0])])
        w2 = register_worker(full_name="W Two", registration_number="R002",
                             classification="HOLDMAN", registered_on="2015-06-01",
                             base_hourly_rate_cents=4000)

        resp = api_client.create_timesheet_entry(
            {"gang_order_id": ns.gang["id"], "worker_id": w2["id"],
             "work_minutes": 120, "meal_break_taken": True},
            make_foreman_headers(ns.foreman_id))
        validate_error(resp, ApiErrorId.ERR_WORKER_NOT_ON_GANG)

        rows, meta = validate_paginated(
            api_client.list_timesheet_entries(PAYROLL,
                                              params={"worker_id": w2["id"]}))
        assert len(rows) == 0


class TestTimesheetReworkCycle:

    def _setup_submitted_timesheet(self):
        ns = setup_completed_gang(
            vessel_overrides={"vessel_name": "MV Rework", "voyage_number": "RW-701"},
            gang_overrides={"required_headcount": 1},
            worker_specs=[dict(HOLDMEN_2[0])])
        t1 = enter_timesheet(ns.gang["id"], ns.workers[0]["id"], ns.foreman_id,
                             work_minutes=480, meal_break_taken=True)
        submit_timesheet(t1["id"], ns.foreman_id)
        return ns, t1

    def test_reject_then_resubmit_refreshes_submitter(self, api):
        """PRD §3.8: "A payroll clerk may reject a `SUBMITTED` entry, moving it to `REJECTED`; the foreman may then resubmit through the same submission action, which returns the entry to `SUBMITTED` and refreshes `submitted_by_user_id` to the resubmitting foreman. The `SUBMITTED` → `REJECTED` → `SUBMITTED` cycle may repeat as often as needed."

        Design: Difficulty/non_linear_state_machine/timesheet_reject_resubmit_recompute_cycle
        """
        ns, t1 = self._setup_submitted_timesheet()

        rejected = validate_success(
            api_client.reject_timesheet_entry(t1["id"], PAYROLL))
        assert rejected["status"] == "REJECTED"

        resubmitted = submit_timesheet(t1["id"], ns.foreman_id)
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["submitted_by_user_id"] == ns.foreman_id, (
            "submitted_by_user_id refreshed on the rework loop")

    def test_resubmitted_timesheet_approves_with_full_breakdown(self, api):
        """PRD §3.8: "Approval computes the full pay breakdown and freezes it on the entry. The minute split: `straight_minutes` is the smaller of `work_minutes` and 480; `ot_minutes` is the amount by which `work_minutes` exceeds 480, capped at 240 and floored at zero; `dt_minutes` is the amount by which `work_minutes` exceeds 720, floored at zero."

        Design: Difficulty/non_linear_state_machine/timesheet_reject_resubmit_recompute_cycle
        """
        ns, t1 = self._setup_submitted_timesheet()
        api_client.reject_timesheet_entry(t1["id"], PAYROLL)
        submit_timesheet(t1["id"], ns.foreman_id)

        approved = approve_timesheet(t1["id"], "pay-1")
        assert approved["status"] == "APPROVED"
        assert approved["straight_minutes"] == 480
        assert approved["ot_minutes"] == 0
        assert approved["dt_minutes"] == 0
        assert approved["meal_penalty_minutes"] == 0
        assert approved["gross_pay_cents"] == 32_000


class TestTimesheetSegregation:

    def test_timesheet_approve_by_submitting_foreman_violates_segregation(self, api):
        """PRD §3.8: "Approval belongs to the `PayrollClerk`, and the approver's `X-User-ID` must differ from `submitted_by_user_id` — a clerk who submitted a timesheet through a foreman hat may not approve it — with collisions rejected as `ERR_SEGREGATION_OF_DUTIES` (403)."
        PRD §2.1: "Two segregation-of-duties invariants follow from this model and are enforced wherever they apply: the claims adjuster deciding a damage claim must not be the worker who reported it, and the payroll clerk approving a timesheet must not be the foreman who submitted it; a violation of either is rejected with `ERR_SEGREGATION_OF_DUTIES` (403)."

        Design: Corner/validations/timesheet_approve_by_submitting_foreman_violates_segregation
        """
        ns = setup_completed_gang(
            vessel_overrides={"vessel_name": "MV Sod2", "voyage_number": "V-302"},
            gang_overrides={"required_headcount": 1},
            worker_specs=[dict(HOLDMEN_2[0])])
        t1 = enter_timesheet(ns.gang["id"], ns.workers[0]["id"], ns.foreman_id,
                             work_minutes=120, meal_break_taken=True)
        submit_timesheet(t1["id"], ns.foreman_id)

        # PayrollClerk role but X-User-ID equal to the submitting foreman's id.
        same_identity = api_client.approve_timesheet_entry(
            t1["id"], make_payroll_headers(ns.foreman_id))
        validate_error(same_identity, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_timesheet_entry(t1["id"], PAYROLL)["status"] == "SUBMITTED"

        other = api_client.approve_timesheet_entry(
            t1["id"], make_payroll_headers("pay-1"))
        assert validate_success(other)["status"] == "APPROVED"
