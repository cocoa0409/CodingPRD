"""Where two rules both fail, the ladder of §2.6 decides which one answers."""

from test_helpers import (
    ApiErrorId,
    IntakePosture,
    ReferralStatus,
    ShiftAssignmentStatus,
    WorkShiftStatus,
    factories,
    fixtures,
    make_case_manager_headers,
    make_intake_specialist_headers,
    validate_error,
)


class TestStaleVersionOutranksClosedIntake:
    """A one-slot line, filled, read against the version the client last saw."""

    def _single_slot_line_with_a_spare_referral(self, api):
        fixtures.set_clock(api, "2026-09-07T00:00:00Z")
        line = fixtures.create_launched_business_line(api, training_slots_total=1)
        partner = fixtures.create_referral_partner(api)
        first = fixtures.create_eligible_referral(api, partner["id"], "CAND-001")
        second = fixtures.create_eligible_referral(
            api,
            partner["id"],
            "CAND-002",
            barrier_codes=["DISABILITY", "LIMITED_ENGLISH", "YOUTH_AGING_OUT"],
            hours_available_per_week=36,
        )
        observed_version = fixtures.business_line_version(api, line["id"])
        fixtures.enroll_participant(
            api, line["id"], first["id"], observed_version
        )
        return {
            "business_line": line,
            "second_referral": second,
            "observed_version": observed_version,
        }

    def test_the_version_guard_answers_before_the_intake_gate(self, api):
        """Rung nine precedes rung nineteen, so the stale version is reported.

        "And because the version guard (rung 9) precedes every business rule, a
        client holding a stale business-line version learns that fact before it
        learns that intake had closed."

        Design: Difficulty/priority_pair_validation_conflict/stale_business_line_version_outranks_intake_closed
        """
        environment = self._single_slot_line_with_a_spare_referral(api)

        response = api.create_participant(
            factories.participant_payload(
                environment["second_referral"]["id"],
                environment["business_line"]["id"],
                environment["observed_version"],
            ),
            make_intake_specialist_headers(),
        )

        validate_error(response, ApiErrorId.ERR_STALE_BUSINESS_LINE_VERSION, 412)

    def test_the_refused_enrollment_writes_nothing(self, api):
        """A rejected request leaves the line, the referral and the roster alone.

        "Rules are evaluated strictly in the order below, and the **first** failing
        rule decides the response; no later rule is evaluated, and no state is
        written."

        Design: Difficulty/priority_pair_validation_conflict/stale_business_line_version_outranks_intake_closed
        """
        environment = self._single_slot_line_with_a_spare_referral(api)
        second_referral_id = environment["second_referral"]["id"]

        api.create_participant(
            factories.participant_payload(
                second_referral_id,
                environment["business_line"]["id"],
                environment["observed_version"],
            ),
            make_intake_specialist_headers(),
        )

        line = fixtures.read_business_line(api, environment["business_line"]["id"])
        assert line["training_slots_filled"] == 1
        assert line["intake_posture"] == IntakePosture.CLOSED

        assert fixtures.participant_count(api, {"referral_id": second_referral_id}) == 0
        referral = fixtures.read_referral(api, second_referral_id)
        assert referral["status"] == ReferralStatus.ELIGIBLE


class TestShiftNotStartedOutranksHoursExceedShift:
    """A seated twelve-hour shift, completed before it begins with impossible hours."""

    def _seated_before_the_shift_begins(self, api):
        program = fixtures.enrolled_participant_program(api)
        shift = fixtures.create_work_shift(
            api,
            program["business_line"]["id"],
            "2026-09-07T08:00:00Z",
            "2026-09-07T20:00:00Z",
        )
        program["work_shift"] = shift
        program["assignment"] = fixtures.seat_participant(
            api, shift["id"], program["participant"]["id"]
        )
        return program

    def test_the_started_check_answers_before_the_hours_ceiling(self, api):
        """Rung seventeen precedes rung thirty-four, so the clock is reported.

        "**Shift started.** The logical clock is at or after the shift's
        `starts_at` when an assignment is completed — otherwise
        `ERR_SHIFT_NOT_STARTED` (409). Applies to assignment completion."

        Design: Difficulty/priority_pair_validation_conflict/shift_not_started_outranks_actual_hours_exceed_shift
        """
        program = self._seated_before_the_shift_begins(api)

        response = api.complete_shift_assignment(
            program["assignment"]["id"],
            factories.completion_payload(20.0),
            make_case_manager_headers(),
        )

        validate_error(response, ApiErrorId.ERR_SHIFT_NOT_STARTED, 409)

    def test_the_refused_completion_leaves_the_seat_and_the_ledger_untouched(self, api):
        """No completion, no cost, no counters.

        "Rules are evaluated strictly in the order below, and the **first** failing
        rule decides the response; no later rule is evaluated, and no state is
        written."

        Design: Difficulty/priority_pair_validation_conflict/shift_not_started_outranks_actual_hours_exceed_shift
        """
        program = self._seated_before_the_shift_begins(api)

        api.complete_shift_assignment(
            program["assignment"]["id"],
            factories.completion_payload(20.0),
            make_case_manager_headers(),
        )

        assignment = fixtures.read_shift_assignment(api, program["assignment"]["id"])
        assert assignment["status"] == ShiftAssignmentStatus.ASSIGNED
        assert assignment["actual_hours"] is None
        assert assignment["wage_cost_cents"] is None

        shift = fixtures.read_work_shift(api, program["work_shift"]["id"])
        assert shift["status"] == WorkShiftStatus.SCHEDULED
        assert shift["billable_labor_cost_cents"] is None

        period_id = program["subsidy_period"]["id"]
        assert fixtures.cost_entry_count(api, {"subsidy_period_id": period_id}) == 0
