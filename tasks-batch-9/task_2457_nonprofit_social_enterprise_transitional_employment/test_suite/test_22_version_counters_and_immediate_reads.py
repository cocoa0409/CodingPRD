"""Shared version counters, the ops-run grace boundary, and reads that never lag."""

from test_helpers import (
    ApiErrorId,
    BusinessLineStatus,
    CheckpointStatus,
    CostCategory,
    CostClassification,
    CostEntryStatus,
    EmploymentStatus,
    IntakePosture,
    ParticipantStatus,
    ReviewDecision,
    ShiftAssignmentStatus,
    WorkShiftStatus,
    assert_entry_allocation_complements,
    assert_hours,
    assert_instant_equals,
    assert_period_ledger,
    assert_ratio,
    factories,
    fixtures,
    make_case_manager_headers,
    make_funder_analyst_headers,
    make_intake_specialist_headers,
    make_program_director_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    CLOCK_NOV_14,
    CLOCK_NOV_15,
    CLOCK_SEP_07,
    CLOCK_SEP_07_EVENING,
)

HIRE_DATE = "2026-10-01T00:00:00Z"


class TestLedgerVersionGuard:
    """Every accepted entry re-allocates the period, so every post needs a fresh read."""

    def _open_period_and_the_callers_snapshot(self, api):
        fixtures.set_clock(api, CLOCK_SEP_07)
        line = fixtures.create_launched_business_line(api)
        period = fixtures.create_open_subsidy_period(api, line["id"])
        return {
            "business_line": line,
            "subsidy_period": period,
            "snapshot_version": period["version"],
        }

    def _post(self, api, period_id, version, category, classification, amount_cents):
        return api.create_cost_entry(
            factories.cost_entry_payload(
                period_id,
                version,
                category=category,
                classification=classification,
                amount_cents=amount_cents,
            ),
            make_program_director_headers(),
        )

    def test_a_second_post_from_one_read_is_refused_as_stale(self, api):
        """The first accepted entry consumed the version the caller was holding.

        "**Manual cost posting** requires `expected_subsidy_period_version` as a
        non-optional input field, carrying the client's last observed `version` of
        the target subsidy period. If that value does not match the period's current
        `version`, the post is rejected with `ERR_STALE_SUBSIDY_PERIOD_VERSION` (HTTP
        412)."

        Design: Corner/cross_cutting_complexity_layers/stale_subsidy_period_version_on_second_cost_entry_returns_412
        """
        rows = self._open_period_and_the_callers_snapshot(api)
        period_id = rows["subsidy_period"]["id"]
        snapshot = rows["snapshot_version"]

        first = validate_success(
            self._post(
                api,
                period_id,
                snapshot,
                CostCategory.MATERIALS,
                CostClassification.BUSINESS,
                40000,
            ),
            201,
        )
        assert first["status"] == CostEntryStatus.POSTED
        assert fixtures.subsidy_period_version(api, period_id) == snapshot + 1

        stale = self._post(
            api,
            period_id,
            snapshot,
            CostCategory.OVERHEAD,
            CostClassification.SHARED,
            25000,
        )

        validate_error(stale, ApiErrorId.ERR_STALE_SUBSIDY_PERIOD_VERSION, 412)

        assert fixtures.cost_entry_count(api, {"subsidy_period_id": period_id}) == 1

    def test_the_identical_body_is_accepted_once_the_version_is_re_read(self, api):
        """Only the quoted version differed between the refusal and the acceptance.

        "An open period accepts an unlimited number of posted entries, so this
        request too would otherwise succeed; the guard is there because every
        accepted entry re-derives the period's `mission_share` and therefore silently
        re-allocates every other shared entry the client had already read."

        Design: Corner/cross_cutting_complexity_layers/stale_subsidy_period_version_on_second_cost_entry_returns_412
        """
        rows = self._open_period_and_the_callers_snapshot(api)
        period_id = rows["subsidy_period"]["id"]
        snapshot = rows["snapshot_version"]

        validate_success(
            self._post(
                api,
                period_id,
                snapshot,
                CostCategory.MATERIALS,
                CostClassification.BUSINESS,
                40000,
            ),
            201,
        )
        validate_error(
            self._post(
                api,
                period_id,
                snapshot,
                CostCategory.OVERHEAD,
                CostClassification.SHARED,
                25000,
            ),
            ApiErrorId.ERR_STALE_SUBSIDY_PERIOD_VERSION,
            412,
        )

        retried = validate_success(
            self._post(
                api,
                period_id,
                fixtures.subsidy_period_version(api, period_id),
                CostCategory.OVERHEAD,
                CostClassification.SHARED,
                25000,
            ),
            201,
        )
        assert retried["amount_cents"] == 25000

        assert fixtures.cost_entry_count(api, {"subsidy_period_id": period_id}) == 2
        assert fixtures.subsidy_period_version(api, period_id) == snapshot + 2


class TestBusinessLineVersionCounter:
    """Review, launch and every enrollment all move the same counter."""

    def _draft_line_and_two_eligible_candidates(self, api):
        fixtures.set_clock(api, CLOCK_SEP_07)
        created = validate_success(
            api.create_business_line(
                factories.business_line_payload(), make_program_director_headers()
            ),
            201,
        )
        partner = fixtures.create_referral_partner(api)
        first = fixtures.create_eligible_referral(
            api, partner["id"], candidate_reference="CAND-001"
        )
        second = fixtures.create_eligible_referral(
            api, partner["id"], candidate_reference="CAND-002"
        )
        return {
            "business_line": created,
            "partner": partner,
            "referrals": [first, second],
        }

    def test_the_counter_moves_once_for_the_approval_and_once_for_the_launch(self, api):
        """Two accepted writes, two single steps on the same counter.

        "Approval sets `status` to `APPROVED`, re-derives `intake_posture` (which
        stays `CLOSED`, because posture only opens for a launched line), increments
        the line's `version` by one, and writes no `rejection_reason`."

        "It sets `status` to `LAUNCHED`, stamps `launched_at` from the logical clock,
        increments `version` by one, and re-derives `intake_posture`, which now
        becomes `OPEN` provided `training_slots_filled` is strictly below
        `training_slots_total` and `quality_incident_count` is strictly below the
        quality-incident limit of ten."

        Design: Corner/cross_cutting_complexity_layers/business_line_version_increments_on_every_enrolling_write
        """
        rows = self._draft_line_and_two_eligible_candidates(api)
        line_id = rows["business_line"]["id"]
        drafted_version = rows["business_line"]["version"]

        assert rows["business_line"]["status"] == BusinessLineStatus.DRAFT

        reviewed = validate_success(
            api.review_business_line(
                line_id,
                factories.review_payload(ReviewDecision.APPROVED),
                make_program_director_headers(),
            )
        )
        assert reviewed["version"] == drafted_version + 1

        launched = validate_success(
            api.launch_business_line(line_id, make_program_director_headers())
        )
        assert launched["version"] == drafted_version + 2
        assert launched["status"] == BusinessLineStatus.LAUNCHED
        assert launched["intake_posture"] == IntakePosture.OPEN

    def test_each_enrollment_bumps_it_and_a_replayed_version_is_stale(self, api):
        """The version a caller held before an enrollment is stale for the next one.

        "**Participant enrollment** requires `expected_business_line_version` as a
        non-optional input field, carrying the client's last observed `version` of
        the target business line. If that value does not match the business line's
        current `version`, the enrollment is rejected with
        `ERR_STALE_BUSINESS_LINE_VERSION` (HTTP 412)."

        "On the business-line side, `training_slots_filled` and `intake_posture` are
        re-derived and the line's `version` is incremented by one."

        Design: Corner/cross_cutting_complexity_layers/business_line_version_increments_on_every_enrolling_write
        """
        rows = self._draft_line_and_two_eligible_candidates(api)
        line_id = rows["business_line"]["id"]
        validate_success(
            api.review_business_line(
                line_id,
                factories.review_payload(ReviewDecision.APPROVED),
                make_program_director_headers(),
            )
        )
        launch_version = validate_success(
            api.launch_business_line(line_id, make_program_director_headers())
        )["version"]

        fixtures.enroll_participant(
            api,
            line_id,
            rows["referrals"][0]["id"],
            expected_business_line_version=launch_version,
        )
        after_first = fixtures.business_line_version(api, line_id)
        assert after_first == launch_version + 1

        fixtures.enroll_participant(
            api,
            line_id,
            rows["referrals"][1]["id"],
            expected_business_line_version=after_first,
        )
        line = fixtures.read_business_line(api, line_id)
        assert line["version"] == launch_version + 2
        assert line["training_slots_filled"] == 2

        third = fixtures.create_eligible_referral(
            api, rows["partner"]["id"], candidate_reference="CAND-003"
        )
        response = api.create_participant(
            factories.participant_payload(third["id"], line_id, launch_version),
            make_intake_specialist_headers(),
        )

        validate_error(response, ApiErrorId.ERR_STALE_BUSINESS_LINE_VERSION, 412)


class TestMissedCheckpointSweep:
    """A checkpoint is written off only by an operator, and only once."""

    def _placement_whose_first_checkpoint_has_run_out_of_grace(self, api):
        """Hired 2026-10-01, so the 30-day rung is due 10-31 and out of grace on 11-15."""
        program = fixtures.mid_september_graduate_program(api)
        program["employer"] = fixtures.create_employer(
            api, min_starting_wage_cents_per_hour=1700
        )
        program["placement"] = fixtures.create_placement(
            api,
            program["participant"]["id"],
            program["employer"]["id"],
            hire_date=HIRE_DATE,
            starting_wage_cents_per_hour=1900,
        )
        program["checkpoints"] = fixtures.list_checkpoints(
            api, program["placement"]["id"]
        )
        return program

    def _sweep(self, api, program):
        return validate_success(
            api.run_retention_sweep(
                make_program_director_headers(),
                {"business_line_id": program["business_line"]["id"]},
            )
        )

    def test_the_last_day_of_grace_writes_nothing_off(self, api):
        """The comparison is strict, so the fortnight is a full fortnight.

        "First, overdue checkpoints: every checkpoint still in `SCHEDULED` status
        whose `due_date` plus the 14-day grace period has been passed by the logical
        clock moves `SCHEDULED → MISSED` and sets `at_risk_flag` to true on its
        placement, processed in order of `due_date` ascending and then `created_at`
        ascending."

        Design: Corner/cross_cutting_complexity_layers/retention_sweep_marks_missed_checkpoint_and_flags_placement
        """
        program = self._placement_whose_first_checkpoint_has_run_out_of_grace(api)
        fixtures.set_clock(api, CLOCK_NOV_14)

        summary = self._sweep(api, program)

        assert summary["missed_checkpoint_count"] == 0

        checkpoints = fixtures.list_checkpoints(api, program["placement"]["id"])
        for checkpoint in checkpoints:
            assert checkpoint["status"] == CheckpointStatus.SCHEDULED

    def test_the_day_after_grace_writes_it_off_exactly_once(self, api):
        """The re-run finds nothing left in SCHEDULED status to write off.

        "Note the asymmetry between the two thresholds: a checkpoint becomes
        answerable the instant the clock reaches `due_date` but is only written off
        two weeks later, which gives an employer a fortnight of slack without letting
        the record drift indefinitely."

        Design: Corner/cross_cutting_complexity_layers/retention_sweep_marks_missed_checkpoint_and_flags_placement
        """
        program = self._placement_whose_first_checkpoint_has_run_out_of_grace(api)
        fixtures.set_clock(api, CLOCK_NOV_15)

        summary = self._sweep(api, program)
        assert summary["missed_checkpoint_count"] == 1
        assert summary["exited_participant_count"] == 0
        assert summary["released_assignment_count"] == 0
        assert_instant_equals(summary["swept_at"], CLOCK_NOV_15, "swept_at")

        assert self._sweep(api, program)["missed_checkpoint_count"] == 0

        missed, meta = validate_paginated(
            api.list_retention_checkpoints(
                program["placement"]["id"],
                make_funder_analyst_headers(),
                {"status": CheckpointStatus.MISSED},
            )
        )
        assert meta["total_count"] == 1
        assert_instant_equals(missed[0]["due_date"], "2026-10-31T00:00:00Z", "due_date")

        by_interval = {
            row["interval_days"]: row
            for row in fixtures.list_checkpoints(api, program["placement"]["id"])
        }
        for interval_days in (90, 180, 365):
            assert by_interval[interval_days]["status"] == CheckpointStatus.SCHEDULED

        placement = fixtures.read_placement(api, program["placement"]["id"])
        assert placement["at_risk_flag"] is True
        assert placement["employment_status"] == EmploymentStatus.ACTIVE


class TestCompletionPublishesEverythingAtOnce:
    """One completion, and every derived consequence is already readable."""

    def _seated_shift_at_its_end(self, api):
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
        fixtures.set_clock(api, CLOCK_SEP_07_EVENING)
        return program

    def test_the_completion_response_already_carries_the_labour_cost(self, api):
        """No second call is needed to learn what the shift cost.

        "The transition `ASSIGNED → COMPLETED` stores `actual_hours`,
        `quality_defect_count` and `customer_complaint_count`, and computes the
        assignment's `wage_cost_cents` as `actual_hours` multiplied by the
        participant's `wage_cents_per_hour`, rounded half up to whole cents."

        Design: Corner/consistency_model/completion_response_shows_ledger_and_metrics_immediately
        """
        program = self._seated_shift_at_its_end(api)

        completed = validate_success(
            api.complete_shift_assignment(
                program["assignment"]["id"],
                factories.completion_payload(
                    12.000, quality_defect_count=1, customer_complaint_count=0
                ),
                make_case_manager_headers(),
            )
        )

        assert completed["status"] == ShiftAssignmentStatus.COMPLETED
        assert completed["wage_cost_cents"] == 19800
        assert completed["quality_defect_count"] == 1
        assert completed["customer_complaint_count"] == 0

    def test_the_ledger_the_period_the_trainee_and_the_shift_all_answer_at_once(
        self, api
    ):
        """Every downstream reader sees the cascade on its very next read.

        "One cost entry is auto-posted into the selected accounting period with
        `category` `TRAINEE_WAGES`, `classification` `SHARED`, `amount_cents` equal to
        the assignment's `wage_cost_cents`, `source_activity_id` null and `status`
        `POSTED`, and the period's `version` is incremented by one."

        "Because a new posted entry has landed, the period re-derives `trainee_hours`,
        `mission_share`, every entry's allocation, `mission_cost_cents`,
        `business_operating_cost_cents`, `total_cost_cents` and both per-trainee-hour
        ratios, exactly as §3.9 describes."

        "The participant's `transitional_hours_worked` and
        `scheduled_hours_current_week` are re-derived."

        Design: Corner/consistency_model/completion_response_shows_ledger_and_metrics_immediately
        """
        program = self._seated_shift_at_its_end(api)

        fixtures.complete_assignment(
            api,
            program["assignment"]["id"],
            12.000,
            quality_defect_count=1,
            customer_complaint_count=0,
        )

        entries = fixtures.list_cost_entries(
            api, {"subsidy_period_id": program["subsidy_period"]["id"]}
        )
        assert len(entries) == 1
        entry = fixtures.read_cost_entry(api, entries[0]["id"])
        assert entry["category"] == CostCategory.TRAINEE_WAGES
        assert entry["classification"] == CostClassification.SHARED
        assert entry["amount_cents"] == 19800
        assert entry["source_activity_id"] is None
        assert entry["status"] == CostEntryStatus.POSTED
        assert_entry_allocation_complements(entry)

        period = fixtures.read_subsidy_period(api, program["subsidy_period"]["id"])
        assert_hours(period["trainee_hours"], 12.000, "trainee_hours")
        assert_ratio(period["mission_share"], 0.2308, "mission_share")
        assert_period_ledger(period, 4570, 15230, 19800)

        participant = fixtures.read_participant(api, program["participant"]["id"])
        assert_hours(
            participant["transitional_hours_worked"], 12.000, "transitional_hours_worked"
        )
        assert_hours(
            participant["scheduled_hours_current_week"],
            0.000,
            "scheduled_hours_current_week",
        )
        assert participant["status"] == ParticipantStatus.TRANSITIONAL_EMPLOYED

        shift = fixtures.read_work_shift(api, program["work_shift"]["id"])
        assert shift["status"] == WorkShiftStatus.CLOSED
        assert shift["billable_labor_cost_cents"] == 19800
        assert shift["quality_defect_count"] == 1
        assert shift["customer_complaint_count"] == 0
