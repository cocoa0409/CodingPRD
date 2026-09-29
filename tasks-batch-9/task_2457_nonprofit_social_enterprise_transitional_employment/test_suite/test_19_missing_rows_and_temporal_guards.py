"""Codes that name their own entity, and the guards that bracket a shift or a period."""

import pytest

from test_helpers import (
    AllocationBasis,
    ApiErrorId,
    CostCategory,
    CostClassification,
    ParticipantStatus,
    SubsidyPeriodStatus,
    WorkShiftStatus,
    factories,
    fixtures,
    make_case_manager_headers,
    make_employer_partner_headers,
    make_funder_analyst_headers,
    make_intake_specialist_headers,
    make_job_coach_headers,
    make_program_director_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    CLOCK_OCT_01,
    CLOCK_SEP_07,
    CLOCK_SEP_07_EVENING,
    UNKNOWN_UUID_1,
    UNKNOWN_UUID_2,
    UNKNOWN_UUID_3,
    UNKNOWN_UUID_4,
    UNKNOWN_UUID_5,
    UNKNOWN_UUID_6,
    UNKNOWN_UUID_7,
)

MISSING_ROW_PROBES = {
    "referral_partner": (
        ApiErrorId.ERR_REFERRAL_PARTNER_NOT_FOUND,
        lambda api: api.get_referral_partner(
            UNKNOWN_UUID_1, make_program_director_headers()
        ),
    ),
    "referral": (
        ApiErrorId.ERR_REFERRAL_NOT_FOUND,
        lambda api: api.get_referral(UNKNOWN_UUID_2, make_intake_specialist_headers()),
    ),
    "shift_assignment": (
        ApiErrorId.ERR_SHIFT_ASSIGNMENT_NOT_FOUND,
        lambda api: api.get_shift_assignment(
            UNKNOWN_UUID_3, make_case_manager_headers()
        ),
    ),
    "support_activity": (
        ApiErrorId.ERR_SUPPORT_ACTIVITY_NOT_FOUND,
        lambda api: api.get_support_activity(UNKNOWN_UUID_4, make_job_coach_headers()),
    ),
    "placement": (
        ApiErrorId.ERR_PLACEMENT_NOT_FOUND,
        lambda api: api.get_placement(UNKNOWN_UUID_5, make_case_manager_headers()),
    ),
    "cost_entry": (
        ApiErrorId.ERR_COST_ENTRY_NOT_FOUND,
        lambda api: api.get_cost_entry(UNKNOWN_UUID_6, make_funder_analyst_headers()),
    ),
}


class TestMissingRowsNameTheirOwnEntity:
    """A 404 says which kind of thing could not be found."""

    @pytest.mark.parametrize("probe_name", sorted(MISSING_ROW_PROBES))
    def test_each_collection_reports_its_own_not_found_code(self, api, probe_name):
        """The code belongs to the entity the identifier addresses.

        "The failure carries the code for the missing type:
        `ERR_BUSINESS_LINE_NOT_FOUND`, `ERR_REFERRAL_PARTNER_NOT_FOUND`,
        `ERR_REFERRAL_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`,
        `ERR_WORK_SHIFT_NOT_FOUND`, `ERR_SHIFT_ASSIGNMENT_NOT_FOUND`,
        `ERR_SUPPORT_ACTIVITY_NOT_FOUND`, `ERR_EMPLOYER_NOT_FOUND`,
        `ERR_PLACEMENT_NOT_FOUND`, `ERR_RETENTION_CHECKPOINT_NOT_FOUND`,
        `ERR_SUBSIDY_PERIOD_NOT_FOUND`, or `ERR_COST_ENTRY_NOT_FOUND`, each with
        HTTP 404."

        Design: Corner/errors/unknown_ids_return_the_entity_specific_not_found_code
        """
        expected_error_id, probe = MISSING_ROW_PROBES[probe_name]

        error = validate_error(probe(api), expected_error_id, 404)

        assert error["message"]

    def test_an_unknown_checkpoint_is_missing_before_it_is_unowned(self, api):
        """Existence is settled before ownership, so the acting identity never matters.

        "**Existence.** Every identifier the request references must resolve to a
        row."

        Design: Corner/errors/unknown_ids_return_the_entity_specific_not_found_code
        """
        response = api.confirm_retention_checkpoint(
            UNKNOWN_UUID_7,
            factories.checkpoint_confirmation_payload(
                still_employed=True, verified_wage_cents_per_hour=1900
            ),
            make_employer_partner_headers(UNKNOWN_UUID_1),
        )

        error = validate_error(
            response, ApiErrorId.ERR_RETENTION_CHECKPOINT_NOT_FOUND, 404
        )
        assert error["message"]


class TestSeatingRefusalOrder:
    """Three seat-level rules on one single-seat shift, each in its own turn."""

    def _one_seat_shift_with_two_trainees(self, api):
        """A single-seat shift on a line roomy enough that supervision never binds."""
        program = fixtures.enrolled_participant_program(
            api, line_overrides={"supervisor_capacity": 4}
        )
        fixtures.add_second_participant(api, program, wage_cents_per_hour=1650)
        shift = fixtures.create_work_shift(
            api,
            program["business_line"]["id"],
            "2026-09-07T08:00:00Z",
            "2026-09-07T20:00:00Z",
            trainee_capacity=1,
        )
        program["work_shift"] = shift
        program["assignment"] = fixtures.seat_participant(
            api, shift["id"], program["participant"]["id"]
        )
        return program

    def test_the_same_trainee_twice_is_a_duplicate_before_it_is_a_capacity_breach(
        self, api
    ):
        """Both rules are true at once, and the earlier rung answers.

        "The participant must not already hold an `ASSIGNED` or `COMPLETED`
        assignment on this exact shift (`ERR_DUPLICATE_SHIFT_ASSIGNMENT`)."

        "Rules are evaluated strictly in the order below, and the **first** failing
        rule decides the response; no later rule is evaluated, and no state is
        written."

        Design: Corner/errors/shift_assignment_duplicate_full_and_closed_shift_rejected
        """
        program = self._one_seat_shift_with_two_trainees(api)

        response = api.create_shift_assignment(
            factories.shift_assignment_payload(
                program["work_shift"]["id"], program["participant"]["id"]
            ),
            make_case_manager_headers(),
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_SHIFT_ASSIGNMENT, 409)

    def test_a_different_trainee_meets_the_seat_ceiling(self, api):
        """The single seat is taken, so the count is no longer below capacity.

        "The shift's own `assigned_count` must be strictly below its
        `trainee_capacity` (`ERR_SHIFT_CAPACITY_FULL`)."

        Design: Corner/errors/shift_assignment_duplicate_full_and_closed_shift_rejected
        """
        program = self._one_seat_shift_with_two_trainees(api)

        response = api.create_shift_assignment(
            factories.shift_assignment_payload(
                program["work_shift"]["id"], program["second_participant"]["id"]
            ),
            make_case_manager_headers(),
        )

        validate_error(response, ApiErrorId.ERR_SHIFT_CAPACITY_FULL, 409)

    def test_once_the_shift_has_closed_the_shift_state_gate_answers_first(self, api):
        """A closed shift is refused on its state, not on its seat count.

        "The work shift behind a shift-assignment create, complete or release is in
        `SCHEDULED` status — otherwise `ERR_SHIFT_NOT_SCHEDULED` (409)."

        Design: Corner/errors/shift_assignment_duplicate_full_and_closed_shift_rejected
        """
        program = self._one_seat_shift_with_two_trainees(api)
        fixtures.set_clock(api, CLOCK_SEP_07_EVENING)

        completed = fixtures.complete_assignment(api, program["assignment"]["id"], 12.000)
        assert completed["wage_cost_cents"] == 19800
        shift = fixtures.read_work_shift(api, program["work_shift"]["id"])
        assert shift["status"] == WorkShiftStatus.CLOSED
        assert shift["billable_labor_cost_cents"] == 19800

        response = api.create_shift_assignment(
            factories.shift_assignment_payload(
                program["work_shift"]["id"], program["second_participant"]["id"]
            ),
            make_case_manager_headers(),
        )

        validate_error(response, ApiErrorId.ERR_SHIFT_NOT_SCHEDULED, 409)

        _rows, meta = validate_paginated(
            api.list_shift_assignments(
                make_case_manager_headers(),
                {"work_shift_id": program["work_shift"]["id"]},
            )
        )
        assert meta["total_count"] == 1


class TestPeriodTemporalGuards:
    """A period cannot close early, and cannot be posted to once it has closed."""

    def _open_september_period(self, api):
        fixtures.set_clock(api, CLOCK_SEP_07)
        line = fixtures.create_launched_business_line(api)
        period = fixtures.create_open_subsidy_period(api, line["id"])
        return {"business_line": line, "subsidy_period": period}

    def test_a_close_inside_the_interval_is_refused(self, api):
        """The clock must be strictly past the period's end.

        "Four preconditions apply: the period must be `OPEN`; the logical clock
        must be strictly after `period_end`, with an earlier attempt refused as
        `ERR_PERIOD_NOT_ENDED`; `revenue_cents` must be present; and no assignment
        in `ASSIGNED` status may remain on a shift of this line whose `starts_at`
        falls inside the period interval, since an unresolved seat means an unknown
        labour cost — that failure reports `ERR_OPEN_ASSIGNMENTS_BLOCK_CLOSE`."

        Design: Corner/errors/period_close_before_end_and_manual_post_after_close_rejected
        """
        rows = self._open_september_period(api)

        response = api.close_subsidy_period(
            rows["subsidy_period"]["id"],
            factories.period_close_payload(AllocationBasis.HOURS, 500000),
            make_program_director_headers(),
        )

        validate_error(response, ApiErrorId.ERR_PERIOD_NOT_ENDED, 409)

        period = fixtures.read_subsidy_period(api, rows["subsidy_period"]["id"])
        assert period["status"] == SubsidyPeriodStatus.OPEN

    def test_a_closed_period_refuses_a_post_even_with_a_current_version(self, api):
        """The closed-period gate is settled before the version guard is consulted.

        "**Period still open.** Any subsidy period a cost movement would touch is in
        `OPEN` status, whether the movement is a direct manual post or the
        compensating void of a delivered support activity — otherwise
        `ERR_PERIOD_CLOSED` (409). Applies to manual cost posting and
        support-activity voiding."

        Design: Corner/errors/period_close_before_end_and_manual_post_after_close_rejected
        """
        rows = self._open_september_period(api)
        period_id = rows["subsidy_period"]["id"]
        fixtures.set_clock(api, CLOCK_OCT_01)

        closed = fixtures.close_subsidy_period(
            api, period_id, AllocationBasis.HOURS, 500000
        )
        assert closed["status"] == SubsidyPeriodStatus.CLOSED
        assert closed["revenue_cents"] == 500000
        version_after_close = fixtures.subsidy_period_version(api, period_id)

        response = api.create_cost_entry(
            factories.cost_entry_payload(
                period_id,
                version_after_close,
                category=CostCategory.MATERIALS,
                classification=CostClassification.BUSINESS,
                amount_cents=40000,
            ),
            make_program_director_headers(),
        )

        validate_error(response, ApiErrorId.ERR_PERIOD_CLOSED, 409)

        assert fixtures.cost_entry_count(api, {"subsidy_period_id": period_id}) == 0
        assert fixtures.subsidy_period_version(api, period_id) == version_after_close


class TestTraineeWageBand:
    """The transitional wage band is inclusive at both ends."""

    def _line_with_one_eligible_candidate(self, api):
        fixtures.set_clock(api, CLOCK_SEP_07)
        line = fixtures.create_launched_business_line(api)
        partner = fixtures.create_referral_partner(api)
        referral = fixtures.create_eligible_referral(api, partner["id"])
        return {"business_line": line, "partner": partner, "referral": referral}

    @pytest.mark.parametrize("wage_cents_per_hour", [1400, 2300])
    def test_a_wage_outside_the_band_is_refused(self, api, wage_cents_per_hour):
        """Below 1500 and above 2200 are both out of range.

        "An `IntakeSpecialist` enrolls by naming the `referral_id` of an `ELIGIBLE`
        referral and the `business_line_id` of the line to place them on, setting
        `wage_cents_per_hour` — the transitional wage the trading operation will
        pay, which must be at least 1500 and at most 2200 or the request is refused
        with `ERR_TRAINEE_WAGE_OUT_OF_RANGE` — and quoting
        `expected_business_line_version` as described in §2.9."

        Design: Corner/errors/trainee_wage_outside_program_band_rejected
        """
        rows = self._line_with_one_eligible_candidate(api)
        version = fixtures.business_line_version(api, rows["business_line"]["id"])

        response = api.create_participant(
            factories.participant_payload(
                rows["referral"]["id"],
                rows["business_line"]["id"],
                version,
                wage_cents_per_hour=wage_cents_per_hour,
            ),
            make_intake_specialist_headers(),
        )

        validate_error(response, ApiErrorId.ERR_TRAINEE_WAGE_OUT_OF_RANGE, 422)

        assert fixtures.business_line_version(api, rows["business_line"]["id"]) == version

    def test_the_lower_bound_is_accepted_on_the_untouched_version(self, api):
        """Neither refusal moved the line, so the same guard still satisfies §2.9.

        "A successful enrollment writes a participant in `TRANSITIONAL_EMPLOYED`
        `status` with `enrolled_at` stamped from the logical clock, all four progress
        metrics at their zero values, `re_entry_count` at 0, and
        `readiness_certified_by_user_id`, `readiness_certified_at`, `graduated_at`,
        `graduation_wage_cents_per_hour` and `eligible_re_entry_at` all null."

        "On the business-line side, `training_slots_filled` and `intake_posture` are
        re-derived and the line's `version` is incremented by one."

        Design: Corner/errors/trainee_wage_outside_program_band_rejected
        """
        rows = self._line_with_one_eligible_candidate(api)
        line_id = rows["business_line"]["id"]
        version = fixtures.business_line_version(api, line_id)

        for refused_wage in (1400, 2300):
            validate_error(
                api.create_participant(
                    factories.participant_payload(
                        rows["referral"]["id"],
                        line_id,
                        version,
                        wage_cents_per_hour=refused_wage,
                    ),
                    make_intake_specialist_headers(),
                ),
                ApiErrorId.ERR_TRAINEE_WAGE_OUT_OF_RANGE,
                422,
            )

        participant = validate_success(
            api.create_participant(
                factories.participant_payload(
                    rows["referral"]["id"], line_id, version, wage_cents_per_hour=1500
                ),
                make_intake_specialist_headers(),
            ),
            201,
        )

        assert participant["status"] == ParticipantStatus.TRANSITIONAL_EMPLOYED
        assert participant["wage_cents_per_hour"] == 1500

        line = fixtures.read_business_line(api, line_id)
        assert line["training_slots_filled"] == 1
        assert line["version"] == version + 1
