"""The two-step labour cost: round each assignment, then sum the rounded figures."""

from test_helpers import (
    CostCategory,
    CostClassification,
    WorkShiftStatus,
    assert_hours,
    assert_shift_assignment,
    fixtures,
)


def _two_trainees_on_a_four_hour_shift(api):
    """Two trainees at 1650 and 1725 cents an hour seated on one four-hour shift.

    The shift runs 08:00 to 12:00 on 2026-09-07 with two seats, and the clock is
    left at 12:00 so both completions are permitted.
    """
    program = fixtures.enrolled_participant_program(api)
    fixtures.add_second_participant(api, program, wage_cents_per_hour=1725)
    shift = fixtures.create_work_shift(
        api,
        program["business_line"]["id"],
        "2026-09-07T08:00:00Z",
        "2026-09-07T12:00:00Z",
    )
    program["work_shift"] = shift
    program["first_assignment"] = fixtures.seat_participant(
        api, shift["id"], program["participant"]["id"]
    )
    program["second_assignment"] = fixtures.seat_participant(
        api, shift["id"], program["second_participant"]["id"]
    )
    fixtures.set_clock(api, "2026-09-07T12:00:00Z")
    return program


class TestPerAssignmentWageRounding:
    """The PRD's own worked example of 3.335 and 2.125 hours."""

    def test_each_assignment_rounds_its_own_wage_cost_to_whole_cents(self, api):
        """Each completion rounds its own product before anything is summed.

        "The transition `ASSIGNED → COMPLETED` stores `actual_hours`,
        `quality_defect_count` and `customer_complaint_count`, and computes the
        assignment's `wage_cost_cents` as `actual_hours` multiplied by the
        participant's `wage_cents_per_hour`, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/shift_labor_cost_rounds_per_assignment_then_sums
        """
        program = _two_trainees_on_a_four_hour_shift(api)

        first = fixtures.complete_assignment(
            api, program["first_assignment"]["id"], 3.335
        )
        second = fixtures.complete_assignment(
            api, program["second_assignment"]["id"], 2.125
        )

        assert_shift_assignment(first)
        assert_shift_assignment(second)
        assert_hours(first["actual_hours"], 3.335, "actual_hours")
        assert first["wage_cost_cents"] == 5503
        assert_hours(second["actual_hours"], 2.125, "actual_hours")
        assert second["wage_cost_cents"] == 3666

    def test_billable_labour_cost_totals_9169_and_not_9168(self, api):
        """The pinned order gives 9169 where sum-then-round would give 9168.

        "Rounding per assignment first and summing second is the specification, and
        it does not agree with summing raw products and rounding once: 3.335 hours
        at 1650 cents an hour and 2.125 hours at 1725 cents an hour give 5503 and
        3666, totalling 9169 under the pinned order, where sum-then-round would
        give 9168."

        Design: Difficulty/combinatorial_formula/shift_labor_cost_rounds_per_assignment_then_sums
        """
        program = _two_trainees_on_a_four_hour_shift(api)
        fixtures.complete_assignment(api, program["first_assignment"]["id"], 3.335)
        fixtures.complete_assignment(api, program["second_assignment"]["id"], 2.125)

        shift = fixtures.read_work_shift(api, program["work_shift"]["id"])

        assert shift["status"] == WorkShiftStatus.CLOSED
        assert shift["billable_labor_cost_cents"] == 9169
        assert shift["billable_labor_cost_cents"] != 9168

    def test_the_ledger_receives_one_rounded_wage_entry_per_assignment(self, api):
        """Each completion auto-posts its own already-rounded trainee-wage entry.

        "One cost entry is auto-posted into the selected accounting period with
        `category` `TRAINEE_WAGES`, `classification` `SHARED`, `amount_cents` equal
        to the assignment's `wage_cost_cents`, `source_activity_id` null and
        `status` `POSTED`, and the period's `version` is incremented by one."

        Design: Difficulty/combinatorial_formula/shift_labor_cost_rounds_per_assignment_then_sums
        """
        program = _two_trainees_on_a_four_hour_shift(api)
        fixtures.complete_assignment(api, program["first_assignment"]["id"], 3.335)
        fixtures.complete_assignment(api, program["second_assignment"]["id"], 2.125)

        period_id = program["subsidy_period"]["id"]
        entries = fixtures.list_cost_entries(api, {"subsidy_period_id": period_id})

        wage_entries = [
            entry for entry in entries if entry["category"] == CostCategory.TRAINEE_WAGES
        ]
        assert len(wage_entries) == 2
        assert sorted(entry["amount_cents"] for entry in wage_entries) == [3666, 5503]
        for entry in wage_entries:
            assert entry["classification"] == CostClassification.SHARED
            assert entry["source_activity_id"] is None

        period = fixtures.read_subsidy_period(api, period_id)
        assert_hours(period["trainee_hours"], 5.460, "trainee_hours")
        assert period["total_cost_cents"] == 9169
