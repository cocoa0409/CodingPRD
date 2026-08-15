"""Training sessions, checkpoint ops runs (sweeps), and the adoption report."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_user,
    assert_ops_run,
    create_active_enrollment,
    create_enrollment,
    daily_sweep,
    decide,
    get_check_by_number,
    make_check_row,
    present_item,
    schedule_training,
    set_clock,
    setup_reverse_tier_exceptions,
    upload_checks,
    validate_error,
    validate_success,
)

BANK_MGR = TEST_USERS["bank_treasury_manager_headers"]
BANK_OPS = TEST_USERS["bank_ops_headers"]


class TestTrainingScheduleConflicts:
    def test_raw_adjacent_sessions_same_trainer_conflict(self, api):
        """PRD §3.1: "each scheduled session occupies a buffered window that
        begins 30 minutes before its start and ends 30 minutes after its end,
        and a new session for the same trainer whose buffered window intersects
        the buffered window of any existing `SCHEDULED` session is rejected with
        `ERR_TRAINING_SCHEDULE_CONFLICT`. Because of the buffer, even exact
        adjacency of the raw windows — one session ending exactly when another
        begins — counts as a conflict."

        Design: Difficulty/resource_temporal_overlap/training_session_buffered_window_conflict
        """
        enr = create_enrollment("TrainCo", "POSITIVE_PAY", "PAY")
        schedule_training(enr["id"], "tr-x", "2026-08-10T10:00:00Z",
                          "2026-08-10T11:00:00Z")
        resp = api.create_training_session(
            {"enrollment_id": enr["id"], "trainer_id": "tr-x",
             "scheduled_start": "2026-08-10T11:00:00Z",
             "scheduled_end": "2026-08-10T12:00:00Z"}, BANK_OPS)
        validate_error(resp, ApiErrorId.ERR_TRAINING_SCHEDULE_CONFLICT)

    def test_same_clock_window_different_trainer_allowed(self, api):
        """PRD §3.1: "a new session for the same trainer whose buffered window
        intersects the buffered window of any existing `SCHEDULED` session is
        rejected with `ERR_TRAINING_SCHEDULE_CONFLICT`" — the conflict scope is
        per-trainer.

        Design: Difficulty/resource_temporal_overlap/training_session_buffered_window_conflict
        """
        enr = create_enrollment("TrainCo2", "POSITIVE_PAY", "PAY")
        schedule_training(enr["id"], "tr-x", "2026-08-10T10:00:00Z",
                          "2026-08-10T11:00:00Z")
        other = validate_success(api.create_training_session(
            {"enrollment_id": enr["id"], "trainer_id": "tr-y",
             "scheduled_start": "2026-08-10T11:00:00Z",
             "scheduled_end": "2026-08-10T12:00:00Z"}, BANK_OPS), 201)
        assert other["status"] == "SCHEDULED"


class TestTrainingSessionStates:
    def test_complete_after_cancel_rejected(self, api):
        """PRD §3.1: "completion requires the session still be `SCHEDULED`
        (otherwise `ERR_SESSION_NOT_COMPLETABLE`)".

        Design: Corner/state_machines/session_complete_after_cancel_rejected
        """
        enr = create_enrollment("CanCo", "POSITIVE_PAY", "PAY")
        adm = add_user(enr["id"], "Admin", "ADMIN")
        sess = schedule_training(enr["id"])
        cancelled = validate_success(
            api.cancel_training_session(sess["id"], BANK_OPS))
        assert cancelled["status"] == "CANCELLED"
        resp = api.complete_training_session(sess["id"], [adm["id"]], BANK_OPS)
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_COMPLETABLE)

    def test_sweep_marks_overdue_session_no_show(self, api):
        """PRD §3.9: "every `SCHEDULED` training session whose `scheduled_end`
        has passed moves to `NO_SHOW`, counted as `sessions_marked_no_show`."

        Design: Corner/state_machines/session_no_show_via_sweep
        """
        enr = create_enrollment("ShowCo", "POSITIVE_PAY", "PAY")
        sess = schedule_training(enr["id"], "tr-9", "2026-08-02T09:00:00Z",
                                 "2026-08-02T10:00:00Z")
        set_clock("2026-08-03T00:00:00Z")
        run = daily_sweep(enr["id"])
        assert run["sessions_marked_no_show"] == 1
        session = validate_success(api.get_training_session(sess["id"], BANK_OPS))
        assert session["status"] == "NO_SHOW"


class TestSweepChores:
    def test_stale_check_age_boundary(self, api):
        """PRD §3.9: "Every `REGISTERED` check whose age has reached the
        enrollment's `stale_days` — the current logical date is on or after
        `issue_date` plus that many days, with an age of exactly `stale_days`
        days staling the check — moves to `STALE_DATED`, counted as
        `checks_staled`."
        At the default clock 2026-08-01 with the default 180-day staleness,
        2026-02-02 is exactly 180 days old and 2026-02-03 is 179.

        Design: Corner/state_machines/stale_check_sweep_boundary_date
        """
        b = create_active_enrollment("StaleCo", "POSITIVE_PAY", "PAY",
                                     account_number="810003",
                                     training_start="2026-07-01T09:00:00Z",
                                     training_end="2026-07-01T10:00:00Z")
        upload_checks(b["enrollment"]["id"], b["account"]["id"], "F-STALE",
                      [make_check_row("801", 100, "OLD", "2026-02-02"),
                       make_check_row("802", 100, "NEWER", "2026-02-03")],
                      b["headers"]["ADMIN"])
        run = daily_sweep(b["enrollment"]["id"])
        assert run["checks_staled"] == 1
        assert get_check_by_number(b["account"]["id"], "801")["status"] == \
            "STALE_DATED"
        assert get_check_by_number(b["account"]["id"], "802")["status"] == \
            "REGISTERED"

    def test_second_sweep_over_same_scope_is_noop(self, api):
        """PRD §3.9: "Every `OPEN` exception whose `decision_deadline_at` is
        strictly earlier than the logical clock is defaulted per its snapshot,
        counted as `exceptions_defaulted`." — once defaulted, no `OPEN`
        exception remains for a second run at the same clock.

        Design: Corner/calculations/daily_sweep_second_run_noop
        """
        b = setup_reverse_tier_exceptions(1, default_decision="RETURN",
                                          business_name="NoopCo",
                                          account_number="820015",
                                          clock="2026-08-03T10:00:00Z")
        set_clock("2026-08-04T09:00:00Z")
        first = daily_sweep(b["enrollment"]["id"])
        assert first["exceptions_defaulted"] == 1
        second = daily_sweep(b["enrollment"]["id"])
        assert second["exceptions_defaulted"] == 0
        assert second["checks_staled"] == 0

    def test_ops_run_receipt_has_no_version_or_updated_at(self, api):
        """PRD §2.4: "`OpsRun` records are the single exception to this
        convention: an ops run is an immutable checkpoint receipt and carries
        only `id` and `created_at`. It has no `updated_at` and no `version`."

        Design: Corner/entities/ops_run_has_no_version_field
        """
        enr = create_enrollment("OpsCo", "POSITIVE_PAY", "PAY")
        run = daily_sweep(enr["id"])
        fetched = validate_success(api.get_ops_run(run["id"], BANK_OPS))
        assert_ops_run(fetched)
        assert fetched["kind"] == "DAILY_SWEEP"
        assert fetched["exceptions_defaulted"] == 0


class TestAdoptionReport:
    def test_reverse_tier_metrics_and_null_compliance(self, api):
        """PRD §3.9: "`on_time_decision_bp` is the decisioned share of all
        resolved exceptions — decisioned plus defaulted — and is zero when no
        exception has resolved yet; `issue_file_compliance_bp` is the clean-paid
        share of all presented items, and is null for `REVERSE_POSITIVE_PAY`
        enrollments (which submit no issue files)".
        PRD §3.9: "Two ratios are reported in basis points as integers, rounded
        half-up" — 3 decisioned of 4 resolved is 7500.

        Design: Corner/calculations/adoption_report_reverse_tier_metrics
        """
        b = setup_reverse_tier_exceptions(4, default_decision="RETURN",
                                          business_name="AdoptCo",
                                          account_number="820013",
                                          clock="2026-08-03T10:00:00Z",
                                          user_roles=("ADMIN",
                                                      "DECISION_MAKER"))
        decide(b["exception_ids"][0], "PAY", b["headers"]["DECISION_MAKER"])
        decide(b["exception_ids"][1], "PAY", b["headers"]["DECISION_MAKER"])
        decide(b["exception_ids"][2], "RETURN", b["headers"]["DECISION_MAKER"])
        set_clock("2026-08-04T09:00:00Z")
        daily_sweep(b["enrollment"]["id"])
        report = validate_success(
            api.get_adoption_report(b["enrollment"]["id"], BANK_OPS))
        assert report["presented_total"] == 4
        assert report["exceptions_total"] == 4
        assert report["decisioned_total"] == 3
        assert report["defaulted_total"] == 1
        assert report["on_time_decision_bp"] == 7500
        assert report["issue_file_compliance_bp"] is None
        assert report["training_completed_count"] == 1

    def test_payee_tier_compliance_and_empty_denominator(self, api):
        """PRD §3.9: "`issue_file_compliance_bp` is the clean-paid share of all
        presented items" — 3 clean of 4 presented is 7500 basis points — and
        "`on_time_decision_bp` ... is zero when no exception has resolved yet".

        Design: Corner/calculations/adoption_report_payee_tier_compliance
        """
        b = create_active_enrollment("CompCo", "PAYEE_POSITIVE_PAY", "PAY",
                                     account_number="820014")
        upload_checks(b["enrollment"]["id"], b["account"]["id"], "F-CMP",
                      [make_check_row("1", 100, "A"),
                       make_check_row("2", 200, "B"),
                       make_check_row("3", 300, "C")],
                      b["headers"]["ADMIN"])
        for num, amount, payee, ts in (("1", 100, "A", "2026-08-03T10:00:00Z"),
                                       ("2", 200, "B", "2026-08-03T10:01:00Z"),
                                       ("3", 300, "C", "2026-08-03T10:02:00Z")):
            item = present_item(b["account"]["id"], num, amount, payee,
                                presented_at=ts)
            assert item["status"] == "PAID"
        present_item(b["account"]["id"], "9", 400, "GHOST",
                     presented_at="2026-08-03T10:03:00Z")
        report = validate_success(
            api.get_adoption_report(b["enrollment"]["id"], BANK_OPS))
        assert report["presented_total"] == 4
        assert report["clean_paid_total"] == 3
        assert report["issue_file_compliance_bp"] == 7500
        assert report["on_time_decision_bp"] == 0
