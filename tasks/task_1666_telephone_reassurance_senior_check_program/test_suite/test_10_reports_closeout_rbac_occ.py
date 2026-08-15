"""Outcome reports, daily closeout, remaining RBAC denials, and program OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_outcome_report,
    create_assignment,
    create_program,
    create_volunteer,
    enroll_participant,
    log_call,
    make_volunteer_headers,
    set_clock,
    setup_calling_environment,
    validate_error,
    validate_success,
    waitlist_applicant,
)


class TestOutcomeReportCreation:
    def test_outcome_report_created_provisional_mid_period(self, api, reviewer_headers, coordinator_headers):
        """PRD §3.9: "Generating a report for a program and a `period_month` produces a `PROVISIONAL` report stamped with its `program_id`; finalizing is allowed only once the logical clock has passed the last instant of that period — while the period is still open the request fails with `ERR_REPORT_PERIOD_OPEN` — and recomputes every metric under the final variant, leaving the report `FINALIZED`."
        PRD §3.9: "In both, `completion_rate` is `calls_completed` divided by the denominator, multiplied by 100, rounded half-up to one decimal place, and null when the denominator is zero"
        PRD §3.9: "The report's `satisfaction_index` is the mean of `survey_mean` over the program's `SCORED` surveys for the period, rounded half-up to two decimal places, and null when no scored surveys exist."

        Design: Corner/entities/outcome_report_created_provisional_mid_period
        """
        program = create_program()
        set_clock("2026-08-15T00:00:00Z")
        report = validate_success(
            api.generate_outcome_report(program["id"], {"period_month": "2026-08"},
                                        reviewer_headers),
            201,
        )
        assert_outcome_report(report)
        assert report["status"] == "PROVISIONAL"
        assert report["calls_scheduled"] == 0
        assert report["escalations_opened"] == 0
        assert report.get("completion_rate") is None, "zero denominators yield a null rate"
        assert report.get("satisfaction_index") is None

    def test_report_finalize_before_period_end_rejected(self, api, reviewer_headers, coordinator_headers):
        """PRD §3.9: "Generating a report for a program and a `period_month` produces a `PROVISIONAL` report stamped with its `program_id`; finalizing is allowed only once the logical clock has passed the last instant of that period — while the period is still open the request fails with `ERR_REPORT_PERIOD_OPEN` — and recomputes every metric under the final variant, leaving the report `FINALIZED`."

        Design: Corner/state_machines/report_finalize_before_period_end_rejected
        """
        program = create_program()
        set_clock("2026-08-15T00:00:00Z")
        report = validate_success(
            api.generate_outcome_report(program["id"], {"period_month": "2026-08"},
                                        reviewer_headers),
            201,
        )
        resp = api.finalize_outcome_report(report["id"], reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_OPEN, 409)
        after = validate_success(api.get_outcome_report(report["id"], reviewer_headers))
        assert after["status"] == "PROVISIONAL"


class TestCloseout:
    def test_closeout_with_nothing_due_returns_empty(self, api, coordinator_headers):
        """PRD §3.9: "The run returns the identifiers of everything it touched — `expired_assignment_ids`, `expired_offer_entry_ids`, `lapsed_volunteer_ids`, `expired_survey_ids`, and `advanced_escalation_ids` — and increments the program's `version` by one."

        Design: Corner/endpoints/closeout_with_nothing_due_returns_empty
        """
        program = create_program()
        v0 = program["version"]
        result = validate_success(api.daily_closeout(program["id"], coordinator_headers))
        assert result["expired_assignment_ids"] == []
        assert result["expired_offer_entry_ids"] == []
        assert result["lapsed_volunteer_ids"] == []
        assert result["expired_survey_ids"] == []
        assert result["advanced_escalation_ids"] == []
        after = validate_success(api.get_program(program["id"], coordinator_headers))
        assert after["version"] == v0 + 1, "an empty closeout still bumps the version by 1"


class TestRbacDenials:
    def test_volunteer_cannot_create_program_forbidden(self, api, coordinator_headers):
        """PRD §2.1: "A caller whose role is not listed for an endpoint is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §2.1: "A `ProgramCoordinator` runs day-to-day operations: program configuration, the volunteer roster, schedules, assignments, call logs as a coordinator fallback, escalation opening and advancement, and referrals."

        Design: Corner/rbac/volunteer_cannot_create_program_forbidden
        """
        create_program()
        resp = api.create_program(
            {"name": "Evil", "total_capacity": 1, "current_policy_version": "v9"},
            make_volunteer_headers("00000000-0000-0000-0000-000000000001"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_volunteer_logging_others_assignment_rejected(self, api, coordinator_headers):
        """PRD §2.1: "When `X-User-Role` is `VolunteerCaller`, `X-User-ID` is the `id` of the acting `VolunteerCaller` record; ownership checks on any resource that references a volunteer compare the resource's `volunteer_id` field to `X-User-ID`."
        PRD §2.1: "This rule bites on four operations: logging a call against an assignment, creating an availability window, deleting an availability window, and signing a confidentiality agreement — in each case, acting on a resource whose owning `volunteer_id` does not match the caller's `X-User-ID` is rejected with `ERR_NOT_OWN_RESOURCE`."

        Design: Corner/rbac/volunteer_logging_others_assignment_rejected
        """
        program, participant, volunteer = setup_calling_environment()
        assignment = create_assignment(participant["id"], volunteer["id"], "2026-08-03")
        other = create_volunteer(full_name="Vol Two")
        set_clock("2026-08-03T10:00:00Z")
        resp = api.create_call_log(
            assignment["id"],
            {"called_at": "2026-08-03T09:05:00Z", "duration_seconds": 100,
             "outcome": "REACHED_OK"},
            make_volunteer_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_OWN_RESOURCE, 403)
        after = validate_success(api.get_call_assignment(assignment["id"], coordinator_headers))
        assert after["status"] == "SCHEDULED"


class TestOccPromotionRun:
    def test_occ_promotion_run_stale_version(self, api, intake_headers, coordinator_headers):
        """PRD §2.7: "`POST /api/programs/{id}/promotion-runs` requires `expected_program_version`: a promotion run is a legal, repeatable batch operation, but repeating it against a program version the caller read before an intervening mutation — another promotion run, an enrollment that bumped `occupied_slots` — must be rejected with `ERR_STALE_VERSION` (HTTP 412) so offers are never issued from a stale capacity snapshot."
        PRD §3.3: "The run increments `promotion_epoch` and the program's `version` exactly once, and returns the new `epoch`, the `offers_created` count, the `offered_entry_ids`, and `gross_free_after`."

        Design: Corner/complexity_layers/occ_promotion_run_stale_version
        """
        program = create_program(total_capacity=1, max_reserve_slots=0)
        filler = enroll_participant({"full_name": "Fill"})
        waitlisted, entry = waitlist_applicant({"full_name": "W P"})
        validate_success(
            api.disenroll_participant(filler["id"], {"reason": "moved"}, coordinator_headers)
        )
        program_now = validate_success(api.get_program(program["id"], intake_headers))
        version = program_now["version"]
        run1 = validate_success(
            api.run_promotion(program["id"], {"expected_program_version": version},
                              intake_headers),
            201,
        )
        assert run1["epoch"] == 1
        # Replaying the read version is rejected; the rejected run advanced nothing.
        stale = api.run_promotion(program["id"], {"expected_program_version": version},
                                  intake_headers)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)
        program_mid = validate_success(api.get_program(program["id"], intake_headers))
        assert program_mid["promotion_epoch"] == 1
        run3 = validate_success(
            api.run_promotion(program["id"],
                              {"expected_program_version": program_mid["version"]},
                              intake_headers),
            201,
        )
        assert run3["epoch"] == 2


class TestOccProgramConfigPatch:
    def test_occ_program_config_patch_stale_version(self, api, coordinator_headers):
        """PRD §2.7: "`PATCH /api/programs/{id}` requires `expected_program_version`: program configuration is freely editable at any time, so a request whose expected version no longer matches the program's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), because an intervening mutation — another configuration change, an enrollment-driven occupancy bump, a promotion run — has advanced the program since the caller read it."
        PRD §3.1: "Configuration stays editable afterwards. A coordinator may update any subset of `name`, `total_capacity`, `max_reserve_slots`, `no_answer_threshold`, `escalation_retry_hours`, `contact_phase_hours`, `offer_ttl_hours`, `reapply_cooling_days`, `survey_valid_days`, `doc_buffer_minutes`, and `current_policy_version`; the update is concurrency-guarded as described in §2.7 and increments the program's `version`."

        Design: Corner/complexity_layers/occ_program_config_patch_stale_version
        """
        program = create_program()
        before = validate_success(api.get_program(program["id"], coordinator_headers))
        version = before["version"]
        patched = validate_success(api.patch_program(
            program["id"],
            {"expected_program_version": version, "offer_ttl_hours": 96},
            coordinator_headers,
        ))
        assert patched["offer_ttl_hours"] == 96
        assert patched["version"] == version + 1, "a successful patch increments version"
        stale = api.patch_program(
            program["id"],
            {"expected_program_version": version, "survey_valid_days": 14},
            coordinator_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)
        after = validate_success(api.get_program(program["id"], coordinator_headers))
        assert after["survey_valid_days"] == 30, "the rejected patch changed nothing"


class TestReportProvisionalVsFinal:
    """Identical period rows (4 COMPLETED, 1 UNREACHED, 1 past-due SCHEDULED):
    provisional 4/5 = 80.0 vs final 4/6 = 66.7."""

    def _setup_report_rows(self, api, coordinator_headers, reviewer_headers):
        program, participant, volunteer = setup_calling_environment(
            program_overrides={"total_capacity": 5},
        )
        r = {}
        for key, date in [("r1", "2026-08-03"), ("r2", "2026-08-10"),
                          ("r3", "2026-08-17"), ("r4", "2026-08-24"),
                          ("r5", "2026-08-31")]:
            r[key] = create_assignment(participant["id"], volunteer["id"], date)
        # A sixth assignment on 08-31 is left SCHEDULED (past-due at finalize).
        create_assignment(participant["id"], volunteer["id"], "2026-08-31",
                          window_start="10:00", window_end="10:30")
        for key, clock in [("r1", "2026-08-03T10:00:00Z"), ("r2", "2026-08-10T10:00:00Z"),
                           ("r3", "2026-08-17T10:00:00Z"), ("r4", "2026-08-24T10:00:00Z")]:
            set_clock(clock)
            log_call(r[key]["id"], volunteer["id"],
                     f"{r[key]['scheduled_date']}T09:05:00Z", "REACHED_OK",
                     duration_seconds=300)
        set_clock("2026-08-31T14:00:00Z")
        log_call(r["r5"]["id"], volunteer["id"], "2026-08-31T09:05:00Z", "NO_ANSWER",
                 duration_seconds=0)
        return program, participant, volunteer

    def test_provisional_variant_excludes_past_due_scheduled_rows(self, api, coordinator_headers, reviewer_headers):
        """PRD §3.9: "Under the provisional variant, `calls_scheduled` counts assignments whose `scheduled_date` falls in the period and is not after today, and the denominator counts only those whose status is `COMPLETED`, `UNREACHED`, or `EXPIRED` — past-due rows still sitting in `SCHEDULED` are excluded."
        PRD §3.9: "In both, `completion_rate` is `calls_completed` divided by the denominator, multiplied by 100, rounded half-up to one decimal place, and null when the denominator is zero"

        Design: Difficulty/dual_variant_calc/report_provisional_vs_final_completion_rate
        """
        program, participant, volunteer = self._setup_report_rows(
            api, coordinator_headers, reviewer_headers
        )
        # Clock is 2026-08-31T14:00:00Z: the period is still open and no
        # closeout has expired the open 08-31 10:00 assignment.
        report = validate_success(
            api.generate_outcome_report(program["id"], {"period_month": "2026-08"},
                                        reviewer_headers),
            201,
        )
        assert report["status"] == "PROVISIONAL"
        assert report["calls_scheduled"] == 6
        assert report["calls_completed"] == 4
        # denominator 4 COMPLETED + 1 UNREACHED = 5; the past-due SCHEDULED
        # row is excluded.
        assert report["completion_rate"] == pytest.approx(80.0, abs=0.05)

    def test_final_variant_counts_still_scheduled_rows_as_misses(self, api, coordinator_headers, reviewer_headers):
        """PRD §3.9: "Under the final variant, `calls_scheduled` counts every assignment of the period not `CANCELLED`, and the denominator is that same count, so rows still `SCHEDULED` count as misses."
        PRD §3.9: "The completion rate is where the two variants diverge, and only in the denominator."

        Design: Difficulty/dual_variant_calc/report_provisional_vs_final_completion_rate
        """
        program, participant, volunteer = self._setup_report_rows(
            api, coordinator_headers, reviewer_headers
        )
        report = validate_success(
            api.generate_outcome_report(program["id"], {"period_month": "2026-08"},
                                        reviewer_headers),
            201,
        )
        provisional_rate = report["completion_rate"]
        set_clock("2026-10-01T00:00:00Z")
        finalized = validate_success(
            api.finalize_outcome_report(report["id"], reviewer_headers)
        )
        assert finalized["status"] == "FINALIZED"
        assert finalized["calls_scheduled"] == 6
        # denominator all 6 non-CANCELLED rows; the still-SCHEDULED 08-31 row
        # counts as a miss.
        assert finalized["completion_rate"] == pytest.approx(66.7, abs=0.05)
        assert finalized["completion_rate"] != provisional_rate, (
            "identical rows: provisional 80.0 strictly exceeds final 66.7"
        )
