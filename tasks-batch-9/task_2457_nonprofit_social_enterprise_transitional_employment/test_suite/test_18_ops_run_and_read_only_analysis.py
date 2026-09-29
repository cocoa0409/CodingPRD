"""The ops run, the what-if question, and what may be posted by hand."""

from test_helpers import (
    AllocationBasis,
    ApiErrorId,
    CostCategory,
    CostClassification,
    CostEntryStatus,
    IntakePosture,
    ParticipantStatus,
    ReleasedReason,
    ShiftAssignmentStatus,
    SubsidyPeriodStatus,
    WorkShiftStatus,
    assert_entry_allocation_complements,
    assert_hours,
    assert_instant_equals,
    assert_per_hour_cents,
    assert_period_ledger,
    assert_ratio,
    factories,
    fixtures,
    make_funder_analyst_headers,
    make_program_director_headers,
    validate_error,
    validate_success,
)
from test_helpers.constants import CLOCK_MAR_09_2027, CLOCK_OCT_01, CLOCK_SEP_07

FUTURE_SHIFT_START = "2027-04-05T08:00:00Z"
FUTURE_SHIFT_END = "2027-04-05T20:00:00Z"


class TestDurationLimitSweep:
    """Elapsed time only becomes state when the ops run is invoked."""

    def _trainee_past_the_duration_limit(self, api):
        """Enrolled 2026-09-07 for 26 weeks, one untouched seat, clock 2027-03-09."""
        program = fixtures.enrolled_participant_program(api)
        shift = fixtures.create_work_shift(
            api,
            program["business_line"]["id"],
            FUTURE_SHIFT_START,
            FUTURE_SHIFT_END,
        )
        program["work_shift"] = shift
        program["assignment"] = fixtures.seat_participant(
            api, shift["id"], program["participant"]["id"]
        )
        fixtures.set_clock(api, CLOCK_MAR_09_2027)
        return program

    def test_the_sweep_exits_the_trainee_and_releases_the_untouched_seat(self, api):
        """One pass, one exit, one release, all reported in the counted summary.

        "Second, duration-limit exits: participants still in
        `TRANSITIONAL_EMPLOYED` or `READY_FOR_GRADUATION` whose `enrolled_at` plus
        `max_transitional_weeks` multiplied by seven days has been passed by the
        logical clock move to `EXITED_UNSUCCESSFUL`, releasing their `ASSIGNED`
        assignments with `released_reason` `PARTICIPANT_EXITED` and forcing the
        line's `training_slots_filled` and `intake_posture` to be re-derived."

        "The sweep reports what it did: `missed_checkpoint_count`,
        `exited_participant_count`, `released_assignment_count`, and `swept_at`,
        the logical-clock instant at which the sweep ran."

        Design: Corner/endpoints/retention_sweep_exits_participant_past_duration_limit_and_releases_seats
        """
        program = self._trainee_past_the_duration_limit(api)

        summary = validate_success(
            api.run_retention_sweep(
                make_program_director_headers(),
                {"business_line_id": program["business_line"]["id"]},
            )
        )

        assert summary["missed_checkpoint_count"] == 0
        assert summary["exited_participant_count"] == 1
        assert summary["released_assignment_count"] == 1
        assert_instant_equals(summary["swept_at"], CLOCK_MAR_09_2027, "swept_at")

        participant = fixtures.read_participant(api, program["participant"]["id"])
        assert participant["status"] == ParticipantStatus.EXITED_UNSUCCESSFUL

        assignment = fixtures.read_shift_assignment(api, program["assignment"]["id"])
        assert assignment["status"] == ShiftAssignmentStatus.RELEASED
        assert assignment["released_reason"] == ReleasedReason.PARTICIPANT_EXITED
        assert assignment["wage_cost_cents"] is None

        line = fixtures.read_business_line(api, program["business_line"]["id"])
        assert line["training_slots_filled"] == 0
        assert line["intake_posture"] == IntakePosture.OPEN

    def test_an_emptied_shift_stays_scheduled_and_a_repeat_sweep_is_a_no_op(self, api):
        """Nothing was billed, so there is nothing to close and nothing left to sweep.

        "A shift on which every seat was released therefore stays `SCHEDULED`
        rather than closing, because there is nothing to bill."

        Design: Corner/endpoints/retention_sweep_exits_participant_past_duration_limit_and_releases_seats
        """
        program = self._trainee_past_the_duration_limit(api)
        validate_success(
            api.run_retention_sweep(
                make_program_director_headers(),
                {"business_line_id": program["business_line"]["id"]},
            )
        )

        shift = fixtures.read_work_shift(api, program["work_shift"]["id"])
        assert shift["status"] == WorkShiftStatus.SCHEDULED
        assert shift["assigned_count"] == 0
        assert shift["billable_labor_cost_cents"] is None

        repeat = validate_success(
            api.run_retention_sweep(
                make_program_director_headers(),
                {"business_line_id": program["business_line"]["id"]},
            )
        )
        assert repeat["missed_checkpoint_count"] == 0
        assert repeat["exited_participant_count"] == 0
        assert repeat["released_assignment_count"] == 0


class TestTrueCostWhatIf:
    """Asking the question is free, and asking it never moves the ledger."""

    def test_the_revenue_basis_is_refused_while_no_revenue_exists(self, api):
        """An open period has no revenue to divide by.

        "Asking for the revenue basis on a period that has no `revenue_cents` at
        all is refused with `ERR_REVENUE_NOT_AVAILABLE`."

        Design: Corner/endpoints/true_cost_analysis_what_if_basis_never_persists
        """
        program = fixtures.completed_shift_program(api)

        response = api.get_true_cost_analysis(
            program["subsidy_period"]["id"],
            make_funder_analyst_headers(),
            {"allocation_basis": AllocationBasis.REVENUE},
        )

        validate_error(response, ApiErrorId.ERR_REVENUE_NOT_AVAILABLE, 409)

        period = fixtures.read_subsidy_period(api, program["subsidy_period"]["id"])
        assert period["status"] == SubsidyPeriodStatus.OPEN
        assert period["revenue_cents"] is None

    def test_the_hours_basis_answers_from_the_provisional_split(self, api):
        """Twelve trainee hours against forty supervisor hours.

        "The read-only true-cost analysis reports `subsidy_period_id`, the
        `allocation_basis` it applied, `mission_share`, `mission_cost_cents`,
        `business_operating_cost_cents`, `total_cost_cents`, `trainee_hours`,
        `true_cost_per_trainee_hour_cents` and `subsidy_per_trainee_hour_cents`."

        Design: Corner/endpoints/true_cost_analysis_what_if_basis_never_persists
        """
        program = fixtures.completed_shift_program(api)

        analysis = validate_success(
            api.get_true_cost_analysis(
                program["subsidy_period"]["id"],
                make_funder_analyst_headers(),
                {"allocation_basis": AllocationBasis.HOURS},
            )
        )

        assert analysis["subsidy_period_id"] == program["subsidy_period"]["id"]
        assert analysis["allocation_basis"] == AllocationBasis.HOURS
        assert_ratio(analysis["mission_share"], 0.2308, "mission_share")
        assert analysis["mission_cost_cents"] == 4570
        assert analysis["business_operating_cost_cents"] == 15230
        assert analysis["total_cost_cents"] == 19800
        assert_hours(analysis["trainee_hours"], 12.000, "trainee_hours")
        assert_per_hour_cents(
            analysis["true_cost_per_trainee_hour_cents"],
            1650.00,
            "true_cost_per_trainee_hour_cents",
        )
        assert_per_hour_cents(
            analysis["subsidy_per_trainee_hour_cents"],
            380.83,
            "subsidy_per_trainee_hour_cents",
        )

    def test_a_what_if_after_the_close_does_not_rewrite_the_frozen_split(self, api):
        """The stored allocation stays on the basis that was frozen.

        "An `allocation_basis` may be supplied to ask the what-if question,
        defaulting to the period's own stored basis; the answer never persists, so
        asking the question does not move the ledger."

        Design: Corner/endpoints/true_cost_analysis_what_if_basis_never_persists
        """
        program = fixtures.completed_shift_program(api)
        period_id = program["subsidy_period"]["id"]
        fixtures.set_clock(api, CLOCK_OCT_01)

        closed = fixtures.close_subsidy_period(
            api, period_id, AllocationBasis.REVENUE, 500000
        )
        assert_ratio(closed["mission_share"], 0.0000, "mission_share")
        assert_period_ledger(closed, 0, 19800, 19800)
        assert_ratio(closed["margin_pct"], 0.9604, "margin_pct")
        assert_ratio(closed["subsidy_rate"], 0.50, "subsidy_rate")
        assert closed["subsidy_draw_cents"] == 0
        version_after_close = closed["version"]

        what_if = validate_success(
            api.get_true_cost_analysis(
                period_id,
                make_funder_analyst_headers(),
                {"allocation_basis": AllocationBasis.HOURS},
            )
        )
        assert_ratio(what_if["mission_share"], 0.2308, "mission_share")
        assert what_if["mission_cost_cents"] == 4570

        period = fixtures.read_subsidy_period(api, period_id)
        assert_ratio(period["mission_share"], 0.0000, "mission_share")
        assert period["mission_cost_cents"] == 0
        assert period["version"] == version_after_close


class TestManuallyPostableCategories:
    """Three categories are hand-posted; the other three arrive on their own."""

    def _open_period_with_no_trainee_hours(self, api):
        fixtures.set_clock(api, CLOCK_SEP_07)
        line = fixtures.create_launched_business_line(api)
        period = fixtures.create_open_subsidy_period(api, line["id"])
        return {"business_line": line, "subsidy_period": period}

    def test_a_system_only_category_is_refused_and_burns_no_version(self, api):
        """The refused attempt writes no row and leaves the guard usable.

        "Six categories exist — `TRAINEE_WAGES`, `SUPERVISION`, `MATERIALS`,
        `COACHING`, `SUPPORT_SERVICE`, `OVERHEAD` — but only `SUPERVISION`,
        `MATERIALS` and `OVERHEAD` may be posted by hand; `TRAINEE_WAGES`,
        `COACHING` and `SUPPORT_SERVICE` are system-posted only, arriving from
        shift completion and support delivery respectively, and a manual attempt at
        one of them is refused with `ERR_CATEGORY_NOT_MANUALLY_POSTABLE`."

        Design: Corner/endpoints/manual_cost_entry_with_system_only_category_rejected
        """
        rows = self._open_period_with_no_trainee_hours(api)
        period_id = rows["subsidy_period"]["id"]
        version = fixtures.subsidy_period_version(api, period_id)

        response = api.create_cost_entry(
            factories.cost_entry_payload(
                period_id,
                version,
                category=CostCategory.TRAINEE_WAGES,
                classification=CostClassification.SHARED,
                amount_cents=19800,
            ),
            make_program_director_headers(),
        )

        validate_error(response, ApiErrorId.ERR_CATEGORY_NOT_MANUALLY_POSTABLE, 422)

        assert fixtures.cost_entry_count(api, {"subsidy_period_id": period_id}) == 0

        accepted = validate_success(
            api.create_cost_entry(
                factories.cost_entry_payload(
                    period_id,
                    version,
                    category=CostCategory.SUPERVISION,
                    classification=CostClassification.SHARED,
                    amount_cents=300000,
                ),
                make_program_director_headers(),
            ),
            201,
        )
        assert accepted["status"] == CostEntryStatus.POSTED

    def test_a_shared_entry_lands_wholly_on_the_business_side_with_no_hours(self, api):
        """A zero mission share sends the entire shared amount to the business.

        "Under the **hours basis**, which is what an `OPEN` period always uses and
        what a what-if analysis requested on the hours basis reports,
        `mission_share` is `trainee_hours` divided by the sum of `trainee_hours` and
        `supervisor_hours`, rounded half up to four decimal places; when both hour
        figures are zero, `mission_share` is 0.0000."

        "An entry classified `SHARED` sets `allocated_mission_cents` to
        `amount_cents` multiplied by `mission_share`, rounded half up to whole
        cents, and sets `allocated_business_cents` to `amount_cents` minus that
        figure — the exact complement, which is what guarantees the two sides
        reconcile to the cent."

        Design: Corner/endpoints/manual_cost_entry_with_system_only_category_rejected
        """
        rows = self._open_period_with_no_trainee_hours(api)
        period_id = rows["subsidy_period"]["id"]
        version = fixtures.subsidy_period_version(api, period_id)

        entry = validate_success(
            api.create_cost_entry(
                factories.cost_entry_payload(
                    period_id,
                    version,
                    category=CostCategory.SUPERVISION,
                    classification=CostClassification.SHARED,
                    amount_cents=300000,
                ),
                make_program_director_headers(),
            ),
            201,
        )

        assert entry["classification"] == CostClassification.SHARED
        assert entry["amount_cents"] == 300000
        assert entry["allocated_mission_cents"] == 0
        assert entry["allocated_business_cents"] == 300000
        assert_entry_allocation_complements(entry)

        period = fixtures.read_subsidy_period(api, period_id)
        assert_period_ledger(period, 0, 300000, 300000)
        assert period["version"] == version + 1
        assert_hours(period["trainee_hours"], 0.000, "trainee_hours")
        assert period["true_cost_per_trainee_hour_cents"] is None
        assert period["subsidy_per_trainee_hour_cents"] is None
