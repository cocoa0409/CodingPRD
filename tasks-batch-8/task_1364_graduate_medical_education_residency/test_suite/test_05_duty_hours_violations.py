"""Duty-hour logging and violation surveillance: the official/projected
variant split, strict boundary rules (80h average, 8h rest, 4-in-28 days off),
the attest/void compensating pair, the auto-remediation cascade, and the
violation workflow (PRD §3.5)."""
from test_helpers import (
    AUTO_REMEDIATION_GOALS, PC, PD, ApiClient, ApiErrorId, approx2,
    assert_duty_summary, attest_log, create_duty_log_payload,
    list_remediation_plans, list_violations, make_active_resident,
    make_active_year, make_attested_log, make_complement, make_daily_logs,
    make_duty_log, make_moonlighting, make_program,
    make_rolling_window_logs, resident_headers, set_clock,
    setup_program_with_active_resident, setup_rest_violation, validate_error,
    validate_paginated, validate_success,
)


def _summary(api, resident_id, week_start):
    data = validate_success(api.get_duty_hour_summary(resident_id, week_start, PD))
    assert_duty_summary(data, resident_id)
    return data


def _violation_total(api, resident_id):
    _, meta = validate_paginated(api.list_violations(
        PD, params={"resident_id": resident_id, "limit": 100}))
    return meta["total_count"]


class TestEightyHourBoundary:
    def _setup(self, api):
        s = setup_program_with_active_resident(approved_positions=4)
        resident = s["resident"]
        # 16 ATTESTED 20.00h logs, 4 per ISO week over 2026-08-03..2026-08-28
        # (total 320.00h; rolling 4-week average exactly 80.00).
        make_rolling_window_logs(resident, hours=20.0)
        return resident

    def test_average_exactly_80_creates_no_violation(self, api: ApiClient):
        """PRD §3.5: "a violation is created with `threshold_value` 80.00 only
        when the average is strictly greater than 80.00 — an average of exactly
        80.00 passes."

        Design: Difficulty/boundary_precision_check/eighty_hour_average_exact_boundary
        """
        resident = self._setup(api)
        assert _violation_total(api, resident["id"]) == 0
        summary = _summary(api, resident["id"], "2026-08-24")
        assert summary["rolling_4wk_avg_official"] == approx2(80.00)

    def test_one_cent_of_an_hour_over_trips_the_rule(self, api: ApiClient):
        """PRD §3.5: "a violation is created with `threshold_value` 80.00 only
        when the average is strictly greater than 80.00 — an average of exactly
        80.00 passes."
        PRD §3.5: "On acceptance the log's `duration_hours` is computed as the
        elapsed time from `started_at` to `ended_at` in hours, rounded half-up
        to 2 decimal places, and the log enters `SUBMITTED` status."

        Design: Difficulty/boundary_precision_check/eighty_hour_average_exact_boundary
        """
        resident = self._setup(api)
        # 2 minutes 24 seconds = 0.04h; window total becomes 320.04h.
        log = make_duty_log(resident, "2026-08-29T08:00:00Z",
                            "2026-08-29T08:02:24Z")
        assert log["duration_hours"] == approx2(0.04)
        attest_log(log["id"], resident)

        data, meta = list_violations(resident_id=resident["id"])
        assert meta["total_count"] == 1
        v = data[0]
        assert v["rule_code"] == "HOURS_80_AVG"
        assert v["measured_value"] == approx2(80.01)
        assert v["threshold_value"] == approx2(80.00)
        assert v["status"] == "FLAGGED"
        assert _summary(api, resident["id"], "2026-08-24")[
            "rolling_4wk_avg_official"] == approx2(80.01)


class TestOfficialVsProjectedDivergence:
    def _setup(self, api):
        s = setup_program_with_active_resident(approved_positions=4)
        resident = s["resident"]
        set_clock("2026-08-28T12:00:00Z")
        make_rolling_window_logs(resident, hours=20.0)
        # One additional SUBMITTED (unattested) 3.00h log on 2026-08-29.
        make_duty_log(resident, "2026-08-29T00:00:00Z", "2026-08-29T03:00:00Z")
        return resident

    def test_official_variant_ignores_unattested_log(self, api: ApiClient):
        """PRD §3.5: "The projected variant, used by the moonlighting headroom
        check and the projected fields of the summary, is identical except that
        it also counts `SUBMITTED` (unattested) logs in the clinical sum; for
        identical data it is therefore always greater than or equal to the
        official figure."

        Design: Difficulty/dual_variant_calc/duty_hours_official_vs_projected_divergence
        """
        resident = self._setup(api)
        summary = _summary(api, resident["id"], "2026-08-24")
        assert summary["official_hours"] == approx2(80.00)
        assert summary["rolling_4wk_avg_official"] == approx2(80.00)
        assert summary["rolling_4wk_avg_projected"] == approx2(80.75)
        # Official average 80.00 is not > 80.00: no HOURS_80_AVG violation.
        assert _violation_total(api, resident["id"]) == 0

    def test_projected_variant_defeats_moonlighting_approval(self, api: ApiClient):
        """PRD §3.6: "first, compute the resident's rolling projected average
        (the projected variant of §3.5, which counts `SUBMITTED` logs and
        attributes hours from requests in `APPROVED`, `ACTIVE`, or `COMPLETED`)
        over the four ISO weeks ending with the current clock week, excluding
        the candidate request itself; second, add the candidate's
        `hours_per_week` to that base exactly once; third, approve only if the
        resulting decision value is less than or equal to 80.00 — equality
        passes, anything greater is rejected."

        Design: Difficulty/dual_variant_calc/duty_hours_official_vs_projected_divergence
        """
        resident = self._setup(api)
        req = make_moonlighting(resident, start_date="2026-09-01",
                                end_date="2026-10-01", hours_per_week=1.00,
                                submit=True)
        # Projected base 80.75 + candidate 1.00 = 81.75 > 80.00.
        resp = api.approve_moonlighting(req["id"], PD)
        validate_error(resp, ApiErrorId.ERR_PROJECTED_HOURS_EXCEED_80)
        assert resp.status_code == 422
        assert validate_success(api.get_moonlighting(req["id"], PD))[
            "status"] == "SUBMITTED"


class TestAttestVoidConservation:
    def _setup(self, api):
        s = setup_program_with_active_resident()
        resident = s["resident"]
        # 4 ATTESTED 10.00h logs Mon-Thu of week 2026-08-03.
        for day in ("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06"):
            make_attested_log(resident, f"{day}T00:00:00Z", f"{day}T10:00:00Z")
        return resident

    def test_attest_moves_official_hours(self, api: ApiClient):
        """PRD §3.5: "For a resident and an ISO week (Monday 00:00:00 UTC
        through Sunday 24:00:00 UTC), clinical hours are the sum of
        `duration_hours` over the resident's `ATTESTED` logs whose `started_at`
        falls within the week." and "The rolling average is the sum of the
        official weekly figures over the window of four ISO weeks ending with
        the reference week, divided by four — the divisor stays four even when
        fewer than four of those weeks contain any data."

        Design: Difficulty/compensating_invariant/attest_void_conserves_official_weekly_hours
        """
        resident = self._setup(api)
        baseline = _summary(api, resident["id"], "2026-08-03")
        assert baseline["official_hours"] == approx2(40.00)
        assert baseline["rolling_4wk_avg_official"] == approx2(10.00)

        make_attested_log(resident, "2026-08-07T00:00:00Z", "2026-08-07T16:00:00Z")
        after = _summary(api, resident["id"], "2026-08-03")
        assert after["official_hours"] == approx2(56.00)
        assert after["rolling_4wk_avg_official"] == approx2(14.00)

    def test_void_restores_the_aggregate_exactly(self, api: ApiClient):
        """PRD §3.5: "the log moves to `VOID` and is excluded from all
        duty-hour aggregates, so an attest-then-void sequence leaves official
        hours unchanged."

        Design: Difficulty/compensating_invariant/attest_void_conserves_official_weekly_hours
        """
        resident = self._setup(api)
        log = make_attested_log(resident, "2026-08-07T00:00:00Z",
                                "2026-08-07T16:00:00Z")
        voided = validate_success(api.void_duty_log(
            log["id"], {"void_reason": "duplicate entry"},
            resident_headers(resident)))
        assert voided["status"] == "VOID"

        restored = _summary(api, resident["id"], "2026-08-03")
        assert restored["official_hours"] == approx2(40.00)
        assert restored["rolling_4wk_avg_official"] == approx2(10.00)
        assert _violation_total(api, resident["id"]) == 0


class TestAutoRemediationCascade:
    def _setup(self, api):
        s = setup_program_with_active_resident(approved_positions=4)
        resident = s["resident"]
        moon = make_moonlighting(resident, start_date="2026-08-03",
                                 end_date="2026-09-01", hours_per_week=2.00,
                                 type="INTERNAL", site_name="Metro ICU",
                                 approve=True)
        set_clock("2026-08-05T12:00:00Z")
        # Three short-rest pairs; the third attest raises the 3rd violation.
        for start, end in (("2026-08-03T00:00:00Z", "2026-08-03T08:00:00Z"),
                           ("2026-08-03T12:00:00Z", "2026-08-03T20:00:00Z"),
                           ("2026-08-04T00:00:00Z", "2026-08-04T08:00:00Z")):
            make_attested_log(resident, start, end)
        l4 = make_duty_log(resident, "2026-08-04T12:00:00Z",
                           "2026-08-04T20:00:00Z")
        attest_log(l4["id"], resident)
        return s, moon

    def test_third_violation_auto_creates_remediation_plan(self, api: ApiClient):
        """PRD §3.5: "If, after a detection pass, the count of unresolved
        violations for the resident within the current `ACTIVE` academic year
        reaches 3 or more and the resident has no `ACTIVE` remediation plan,
        the system automatically creates one: `trigger_source`
        `DUTY_HOUR_VIOLATIONS`, status `ACTIVE`, the goals text "Automatic
        remediation: repeated duty-hour violations", `start_date` taken from
        the logical clock, and `end_date` ninety days later."

        Design: Difficulty/transitive_cascade/duty_violation_threshold_auto_remediation_cascade
        """
        s, _ = self._setup(api)
        resident = s["resident"]
        data, meta = list_violations(resident_id=resident["id"])
        assert meta["total_count"] == 3
        for v in data:
            assert v["rule_code"] == "REST_8H"
            assert v["status"] == "FLAGGED"
            assert v["measured_value"] == approx2(4.00)
            assert v["threshold_value"] == approx2(8.00)

        plans, pmeta = list_remediation_plans(resident_id=resident["id"])
        assert pmeta["total_count"] == 1
        plan = plans[0]
        assert plan["trigger_source"] == "DUTY_HOUR_VIOLATIONS"
        assert plan["status"] == "ACTIVE"
        assert plan["goals"] == AUTO_REMEDIATION_GOALS
        assert plan["start_date"].startswith("2026-08-05")   # logical clock date
        assert plan["end_date"].startswith("2026-11-03")     # start + 90 days

    def test_cascade_revokes_moonlighting_and_drops_attribution(self, api: ApiClient):
        """PRD §3.6: "whenever a resident's standing leaves `GOOD_STANDING`
        (§3.8), every one of the resident's requests in `APPROVED` or `ACTIVE`
        is revoked with `decision_reason` set to `STANDING_CHANGE`, and the
        weekly aggregates are recomputed without those hours."

        Design: Difficulty/transitive_cascade/duty_violation_threshold_auto_remediation_cascade
        """
        s, moon = self._setup(api)
        resident = s["resident"]
        r = validate_success(api.get_resident(resident["id"], PD))
        assert r["standing_status"] == "UNDER_REMEDIATION"
        assert r["lifecycle_status"] == "ACTIVE"

        after = validate_success(api.get_moonlighting(moon["id"], PD))
        assert after["status"] == "REVOKED"
        assert after["decision_reason"] == "STANDING_CHANGE"
        summary = _summary(api, resident["id"], "2026-08-03")
        assert summary["attributed_moonlighting_hours"] == approx2(0.00)


class TestRestGapBoundary:
    def test_exactly_8h_passes_7h59m_violates(self, api: ApiClient):
        """PRD §3.5: "if such a previous log exists and the gap from its
        `ended_at` to the new log's `started_at` is strictly less than 8.00
        hours — a gap of exactly 8.00 passes — a violation is created whose
        window runs from the previous log's `ended_at` to the new log's
        `started_at` inclusive, whose measured value is the gap in hours at 2
        decimal places, and whose `threshold_value` is 8.00."

        Design: Corner/calculations/rest_gap_exact_boundary
        """
        s = setup_program_with_active_resident()
        resident = s["resident"]
        make_attested_log(resident, "2026-08-03T00:00:00Z", "2026-08-03T08:00:00Z")
        # Gap exactly 8.00h (08:00 -> 16:00): passes.
        make_attested_log(resident, "2026-08-03T16:00:00Z", "2026-08-04T00:00:00Z")
        assert _violation_total(api, resident["id"]) == 0

        # Gap 7h59m (00:00 -> 07:59) = 7.98h: violates.
        make_attested_log(resident, "2026-08-04T07:59:00Z", "2026-08-04T12:00:00Z")
        data, meta = list_violations(resident_id=resident["id"])
        assert meta["total_count"] == 1
        v = data[0]
        assert v["rule_code"] == "REST_8H"
        assert v["measured_value"] == approx2(7.98)
        assert v["threshold_value"] == approx2(8.00)


class TestDayOffBoundary:
    def test_24_worked_days_passes_25_violates(self, api: ApiClient):
        """PRD §3.5: "a violation is created with `threshold_value` 4 only when
        days off are strictly fewer than 4 — exactly 4 passes."

        Design: Corner/calculations/day_off_minimum_boundary
        """
        s = setup_program_with_active_resident()
        resident = s["resident"]
        # 24 ATTESTED 2h logs on consecutive days 2026-08-03..2026-08-26:
        # 24 worked days in the trailing 28-day window leaves exactly 4 off.
        make_daily_logs(resident, days=24)
        assert _violation_total(api, resident["id"]) == 0

        # The 25th consecutive worked day leaves 3 days off.
        make_attested_log(resident, "2026-08-27T02:00:00Z", "2026-08-27T04:00:00Z")
        data, meta = list_violations(resident_id=resident["id"])
        assert meta["total_count"] == 1
        v = data[0]
        assert v["rule_code"] == "DAY_OFF_4_IN_28"
        assert v["measured_value"] == approx2(3)
        assert v["threshold_value"] == approx2(4)


class TestSummaryInputSetFiltering:
    def test_status_filtering_of_variants(self, api: ApiClient):
        """PRD §3.5: "For a resident and an ISO week (Monday 00:00:00 UTC
        through Sunday 24:00:00 UTC), clinical hours are the sum of
        `duration_hours` over the resident's `ATTESTED` logs whose `started_at`
        falls within the week."
        PRD §3.5: "The projected variant, used by the moonlighting headroom
        check and the projected fields of the summary, is identical except that
        it also counts `SUBMITTED` (unattested) logs in the clinical sum".

        Design: Corner/calculations/summary_input_set_filtering
        """
        s = setup_program_with_active_resident()
        resident = s["resident"]
        make_attested_log(resident, "2026-08-03T00:00:00Z", "2026-08-03T10:00:00Z")
        make_duty_log(resident, "2026-08-05T00:00:00Z", "2026-08-05T20:00:00Z")
        voided_log = make_attested_log(resident, "2026-08-07T00:00:00Z",
                                       "2026-08-07T08:00:00Z")
        validate_success(api.void_duty_log(
            voided_log["id"], {"void_reason": "wrong week entered"},
            resident_headers(resident)))

        summary = _summary(api, resident["id"], "2026-08-03")
        # ATTESTED only; the VOID 8h log excluded.
        assert summary["official_hours"] == approx2(10.00)
        # ATTESTED 10.00 + SUBMITTED 20.00; VOID excluded from both.
        assert summary["projected_hours"] == approx2(30.00)
        assert _violation_total(api, resident["id"]) == 0


class TestCreationGuards:
    def test_log_start_outside_active_year_rejected(self, api: ApiClient):
        """PRD §3.5: "The start must fall inside an `ACTIVE` academic year of
        the resident's program (`ERR_DATE_OUT_OF_ACTIVE_YEAR`, HTTP 422)".

        Design: Corner/validations/duty_log_date_out_of_active_year_rejected
        """
        s = setup_program_with_active_resident()
        resident = s["resident"]
        resp = api.create_duty_log(
            create_duty_log_payload(resident["id"], "2027-07-05T00:00:00Z",
                                    "2027-07-05T08:00:00Z"),
            resident_headers(resident))
        validate_error(resp, ApiErrorId.ERR_DATE_OUT_OF_ACTIVE_YEAR)
        assert resp.status_code == 422

    def test_shift_length_boundary(self, api: ApiClient):
        """PRD §3.5: "the end must be strictly after the start; and the implied
        duration must not exceed 28.00 hours (`ERR_SHIFT_LENGTH_VIOLATION`,
        HTTP 422)."

        Design: Corner/validations/shift_length_exact_boundary
        """
        s = setup_program_with_active_resident()
        resident = s["resident"]
        ok = validate_success(api.create_duty_log(
            create_duty_log_payload(resident["id"], "2026-08-03T00:00:00Z",
                                    "2026-08-04T04:00:00Z"),
            resident_headers(resident)), expected_status=201)
        assert ok["duration_hours"] == approx2(28.00)

        resp = api.create_duty_log(
            create_duty_log_payload(resident["id"], "2026-08-05T00:00:00Z",
                                    "2026-08-06T04:00:36Z"),
            resident_headers(resident))
        validate_error(resp, ApiErrorId.ERR_SHIFT_LENGTH_VIOLATION)
        assert resp.status_code == 422
        # Creation-time rule: no monitoring violation row exists either way.
        assert _violation_total(api, resident["id"]) == 0


class TestVoidTerminalLockdown:
    def test_void_is_terminal(self, api: ApiClient):
        """PRD §3.5: "either the owning resident or a `ProgramDirector` may
        void a log in `SUBMITTED` or `ATTESTED` status (otherwise
        `ERR_LOG_NOT_VOIDABLE`, HTTP 409)" and "Attesting requires the log to
        be `SUBMITTED` (otherwise `ERR_LOG_NOT_SUBMITTED`, HTTP 409)".

        Design: Corner/state_machines/duty_log_void_terminal_lockdown
        """
        s = setup_program_with_active_resident()
        resident = s["resident"]
        log = make_duty_log(resident, "2026-08-03T00:00:00Z", "2026-08-03T08:00:00Z")
        voided = validate_success(api.void_duty_log(
            log["id"], {"void_reason": "entered twice"}, resident_headers(resident)))
        assert voided["status"] == "VOID"

        resp = api.void_duty_log(log["id"], {"void_reason": "again"}, PD)
        validate_error(resp, ApiErrorId.ERR_LOG_NOT_VOIDABLE)
        resp2 = api.attest_duty_log(log["id"], resident_headers(resident))
        validate_error(resp2, ApiErrorId.ERR_LOG_NOT_SUBMITTED)
        assert validate_success(api.get_duty_log(log["id"], PD))["status"] == "VOID"
        assert _summary(api, resident["id"], "2026-08-03")[
            "official_hours"] == approx2(0.00)


class TestViolationWorkflow:
    def test_full_path_then_terminal(self, api: ApiClient):
        """PRD §3.5: "A `ProgramCoordinator` acknowledges a `FLAGGED`
        violation, moving it to `ACKNOWLEDGED`; acknowledging from any other
        status fails with `ERR_VIOLATION_NOT_OPEN` (HTTP 409). A
        `ProgramDirector` resolves a violation from either `FLAGGED` or
        `ACKNOWLEDGED` (same error otherwise), moving it to `RESOLVED` and
        recording the supplied `resolution_note`."

        Design: Corner/state_machines/violation_full_path_and_terminal
        """
        s = setup_program_with_active_resident()
        violation = setup_rest_violation(s["resident"])
        assert violation["rule_code"] == "REST_8H"
        assert violation["measured_value"] == approx2(4.00)
        assert violation["threshold_value"] == approx2(8.00)
        assert violation["status"] == "FLAGGED"

        acked = validate_success(api.acknowledge_violation(violation["id"], PC))
        assert acked["status"] == "ACKNOWLEDGED"
        resolved = validate_success(api.resolve_violation(
            violation["id"], {"resolution_note": "Schedule template fixed"}, PD))
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_note"] == "Schedule template fixed"

        resp = api.resolve_violation(violation["id"],
                                     {"resolution_note": "again"}, PD)
        validate_error(resp, ApiErrorId.ERR_VIOLATION_NOT_OPEN)

    def test_dismiss_justification_length_boundary(self, api: ApiClient):
        """PRD §3.5: "A director may instead dismiss from either open status
        with a `justification` of at least ten characters — anything shorter is
        rejected with `ERR_JUSTIFICATION_REQUIRED` (HTTP 400) — moving the
        violation to `DISMISSED` with the justification recorded as its
        `resolution_note`."

        Design: Corner/validations/dismiss_justification_length_boundary
        """
        s = setup_program_with_active_resident()
        violation = setup_rest_violation(s["resident"])

        resp = api.dismiss_violation(violation["id"],
                                     {"justification": "too short"}, PD)  # 9 chars
        validate_error(resp, ApiErrorId.ERR_JUSTIFICATION_REQUIRED)
        assert resp.status_code == 400

        dismissed = validate_success(api.dismiss_violation(
            violation["id"],
            {"justification": "Verified scheduling data-entry error"}, PD))
        assert dismissed["status"] == "DISMISSED"
        assert dismissed["resolution_note"] == \
            "Verified scheduling data-entry error"
        assert _violation_total(api, s["resident"]["id"]) == 1


class TestViolationDiscovery:
    def test_violation_reachable_by_log_and_resident_filters(self, api: ApiClient):
        """PRD §3.5: "Every violation row records the `resident_id`, the
        `duty_hour_log_id` of the attested log whose detection pass raised it,
        the `rule_code` (`HOURS_80_AVG`, `REST_8H`, or `DAY_OFF_4_IN_28`), the
        inclusive `window_start` and `window_end`, the `measured_value`, and
        the `threshold_value`."
        PRD §3.5: "The violation list may be filtered by `resident_id`,
        `duty_hour_log_id`, and `status`."

        Design: Corner/endpoints/fk_reverse_reachability_via_filtered_lists
        """
        s = setup_program_with_active_resident()
        resident = s["resident"]
        l1 = make_attested_log(resident, "2026-08-03T00:00:00Z",
                               "2026-08-03T08:00:00Z")
        l2 = make_attested_log(resident, "2026-08-03T12:00:00Z",
                               "2026-08-03T20:00:00Z")

        by_log, meta = validate_paginated(api.list_violations(
            PD, params={"duty_hour_log_id": l2["id"]}))
        assert meta["total_count"] == 1
        assert by_log[0]["rule_code"] == "REST_8H"

        by_resident, _ = validate_paginated(api.list_violations(
            PD, params={"resident_id": resident["id"]}))
        assert len(by_resident) == 1
        assert by_resident[0]["id"] == by_log[0]["id"]

        _, meta = validate_paginated(api.list_violations(
            PD, params={"duty_hour_log_id": l1["id"]}))
        assert meta["total_count"] == 0, "l1's attest created nothing"


class TestYearCloseGuard:
    def test_close_blocked_by_unattested_log_then_succeeds(self, api: ApiClient):
        """PRD §3.1: "the year must be `ACTIVE` (otherwise
        `ERR_ACADEMIC_YEAR_NOT_ACTIVE`), and there must be no duty-hour log in
        `SUBMITTED` status for any resident of the program — an institution
        cannot close its books while attestations are outstanding, and the
        attempt is rejected with `ERR_UNATTESTED_LOGS_EXIST` (HTTP 409)."

        Design: Corner/validations/year_close_blocked_by_unattested_logs
        """
        s = setup_program_with_active_resident()
        resident, year = s["resident"], s["year"]
        log = make_duty_log(resident, "2026-08-03T00:00:00Z",
                            "2026-08-03T08:00:00Z")

        resp = api.close_academic_year(year["id"], PC)
        validate_error(resp, ApiErrorId.ERR_UNATTESTED_LOGS_EXIST)
        assert resp.status_code == 409

        validate_success(api.void_duty_log(
            log["id"], {"void_reason": "entered in error"}, PD))
        closed = validate_success(api.close_academic_year(year["id"], PC))
        assert closed["status"] == "CLOSED"


class TestOwnership:
    def test_resident_cannot_attest_anothers_log(self, api: ApiClient):
        """PRD §2.1: "A resident-role call that targets a row whose resident
        reference differs from `X-User-ID` is rejected with
        `ERR_OWNERSHIP_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/resident_ownership_violation_on_attest
        """
        program = make_program()
        year = make_active_year(program["id"])
        make_complement(program["id"], year["id"], approved_positions=3)
        res_a = make_active_resident(program["id"], year["id"], full_name="A One")
        res_b = make_active_resident(program["id"], year["id"], full_name="B Two")
        log_b = make_duty_log(res_b, "2026-08-03T00:00:00Z", "2026-08-03T08:00:00Z")

        resp = api.attest_duty_log(log_b["id"], resident_headers(res_a))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION)
        assert resp.status_code == 403
        assert validate_success(api.get_duty_log(log_b["id"], PD))[
            "status"] == "SUBMITTED"
