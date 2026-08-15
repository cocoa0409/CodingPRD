"""Reminder cadence, the daily operations run, and the correction loop."""
from test_helpers import (
    TEST_USERS,
    assert_instant_equal,
    create_donor,
    create_draft_application,
    create_fund,
    create_open_program,
    create_student,
    drive_to_selected,
    create_offered_award,
    get_success_data,
    get_fund,
    list_reminders,
    make_student_headers,
    run_daily,
    set_clock,
    submit_application,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestReminderCadence:
    def test_cadence_skips_past_offsets_and_dispatches_inclusively(self, api):
        """PRD §3.3: "For each offset whose send time — the close instant
        minus the offset — still lies in the future, a `SCHEDULED` reminder is
        created carrying that `offset_code` and the computed `send_at`;
        offsets whose send time already lies in the past are skipped, never
        scheduled."
        PRD §2.6: "First, it dispatches due reminders: every `SCHEDULED`
        reminder whose `send_at` is at or before now is dispatched to `SENT`
        — a reminder whose `send_at` equals now dispatches — with dispatch
        processed in `send_at` ascending order, ties broken by `created_at`
        ascending."

        Design: Corner/calculations/calc_reminder_cadence_offsets_skip_past
        """
        student = create_student()
        donor = create_donor()
        fund = create_fund()
        program = create_open_program(
            donor["id"], fund["id"], application_close_at="2026-08-20T00:00:00Z"
        )
        # Create the application at 2026-08-10: D14 (2026-08-06) is past.
        set_clock("2026-08-10T00:00:00Z")
        app = create_draft_application(student["id"], program["id"])

        reminders, meta = list_reminders(app["id"])
        assert meta["total_count"] == 2, "D14 send_at already past -> skipped"
        by_offset = {r["offset_code"]: r for r in reminders}
        assert set(by_offset) == {"D7", "D1"}
        assert_instant_equal(
            by_offset["D7"]["send_at"], "2026-08-13T00:00:00Z", "D7 send_at"
        )
        assert_instant_equal(
            by_offset["D1"]["send_at"], "2026-08-19T00:00:00Z", "D1 send_at"
        )
        assert all(r["status"] == "SCHEDULED" for r in reminders)

        # Dispatch exactly at the D7 send_at: the equality boundary dispatches.
        set_clock("2026-08-13T00:00:00Z")
        counters = run_daily()
        assert counters["reminders_sent"] == 1
        sent, meta = list_reminders(app["id"], {"status": "SENT"})
        assert meta["total_count"] == 1
        assert sent[0]["offset_code"] == "D7"
        assert_instant_equal(sent[0]["sent_at"], "2026-08-13T00:00:00Z", "sent_at")
        scheduled, meta = list_reminders(app["id"], {"status": "SCHEDULED"})
        assert meta["total_count"] == 1
        assert scheduled[0]["offset_code"] == "D1"


class TestRunDailySweeps:
    def test_run_daily_closes_program_and_expires_drafts(self, api):
        """PRD §2.6: "Second, it closes programs whose window has ended: every
        program in `OPEN` whose `application_close_at` has been reached or
        passed moves to `CLOSED`, and every `DRAFT` application of such a
        program moves to `EXPIRED` with its `SCHEDULED` reminders suppressed
        to `SUPPRESSED`."
        PRD §2.6: "First, it dispatches due reminders: every `SCHEDULED`
        reminder whose `send_at` is at or before now is dispatched to `SENT`"
        — the dispatch sweep runs before the close sweep, so the expired
        draft's cadence (D14/D7/D1 all precede the close) has already been
        dispatched to `SENT` by the time the program closes.
        PRD §2.6: "The run returns a summary of its work as four counters:
        `reminders_sent`, `programs_closed`, `applications_expired`, and
        `offers_expired`."

        Design: Corner/state_machines/run_daily_closes_program_expires_drafts
        """
        s_draft = create_student()
        s_submitted = create_student()
        donor = create_donor()
        fund = create_fund()
        program = create_open_program(
            donor["id"], fund["id"], application_close_at="2026-09-01T00:00:00Z"
        )
        app_draft = create_draft_application(s_draft["id"], program["id"])
        app_sub = create_draft_application(s_submitted["id"], program["id"])
        submit_application(app_sub["id"])

        set_clock("2026-09-02T00:00:00Z")
        counters = run_daily()
        assert counters["programs_closed"] == 1
        assert counters["applications_expired"] == 1
        assert counters["reminders_sent"] == 3, (
            "the draft application's D14/D7/D1 reminders were all due before "
            "the close and dispatch in the first sweep"
        )

        program_after = validate_success(api.get_program(program["id"], COORD))
        assert program_after["status"] == "CLOSED"
        draft_after = validate_success(api.get_application(app_draft["id"], COORD))
        assert draft_after["status"] == "EXPIRED"
        sub_after = validate_success(api.get_application(app_sub["id"], COORD))
        assert sub_after["status"] == "SUBMITTED", "only DRAFT applications expire"

        reminders, meta = list_reminders(app_draft["id"])
        assert meta["total_count"] == 3
        assert all(r["status"] == "SENT" for r in reminders)

    def test_offer_expires_via_run_daily(self, api):
        """PRD §3.6: "Creation sets `offer_status` to `OFFERED` and
        `funding_status` to `NONE`, increases the fund's `reserved_cents` by
        the offered amount, moves the application from `SELECTED` to
        `AWARDED`, sets `offer_expires_at` to fourteen days after creation,
        starts `renewal_count` at zero, and leaves `accepted_at` null."
        PRD §2.6: "Third, it expires stale offers: every award still `OFFERED`
        whose `offer_expires_at` lies strictly before now moves to `EXPIRED`,
        releasing the fund reservation and firing the waitlist promotion
        described in §3.6."

        Design: Corner/state_machines/award_offer_expires_via_run_daily
        """
        student = create_student()
        donor = create_donor()
        fund = create_fund()
        program = create_open_program(donor["id"], fund["id"])
        flow = drive_to_selected(student["id"], program["id"])
        award = create_offered_award(flow["application"]["id"], student["id"], 500000)
        assert award["offer_status"] == "OFFERED"
        assert_instant_equal(
            award["offer_expires_at"], "2026-08-15T00:00:00Z",
            "offer_expires_at = created_at + 14 days",
        )
        assert get_fund(fund["id"])["available_cents"] == 4500000

        set_clock("2026-08-16T00:00:00Z")
        counters = run_daily()
        assert counters["offers_expired"] == 1

        award_after = validate_success(api.get_award(award["id"], COORD))
        assert award_after["offer_status"] == "EXPIRED"
        fund_after = get_fund(fund["id"])
        assert fund_after["available_cents"] == 5000000, "reservation released"
        assert fund_after["reserved_cents"] == 0


class TestApplicationReturnResubmissionCycle:
    """The correction loop SUBMITTED -> DRAFT -> SUBMITTED on one application."""

    CLOSE = "2026-09-15T00:00:00Z"

    def _submitted_application(self):
        student = create_student(
            grade_level=11, gpa_hundredths=320, intended_major="ARTS",
            household_income_cents=5000000, efc_cents=500000,
        )
        donor = create_donor()
        fund = create_fund()
        program = create_open_program(
            donor["id"], fund["id"], application_close_at=self.CLOSE
        )
        app = create_draft_application(
            student["id"], program["id"], as_student=True
        )
        submit_application(app["id"], student_id=student["id"])
        return student, app

    def test_return_restores_draft_and_rearms_cadence(self, api):
        """PRD §3.3: "The correction loop runs through the coordinator's
        return action: a `SUBMITTED` application returns to `DRAFT`, its
        `returned_count` increases by one, and the reminder cadence is
        re-armed against the program's close — again skipping offsets whose
        send times have passed."
        PRD §3.3: "A reminder still `SCHEDULED` is suppressed to `SUPPRESSED`
        whenever its application leaves `DRAFT` — by submit, withdraw, or
        expiry — or when its program closes."

        Design: Difficulty/non_linear_state_machine/application_return_resubmission_cycle
        """
        student, app = self._submitted_application()
        # The first submit suppressed the initial cadence.
        suppressed, meta = list_reminders(app["id"], {"status": "SUPPRESSED"})
        assert meta["total_count"] == 3

        returned = validate_success(api.return_application(app["id"], COORD))
        assert returned["status"] == "DRAFT"
        assert returned["returned_count"] == 1

        # Re-entry to DRAFT re-arms the cadence: close 2026-09-15 less the
        # D14/D7/D1 offsets, all still in the future at the default clock.
        scheduled, meta = list_reminders(app["id"], {"status": "SCHEDULED"})
        assert meta["total_count"] == 3
        send_ats = {r["offset_code"]: r["send_at"] for r in scheduled}
        assert_instant_equal(send_ats["D14"], "2026-09-01T00:00:00Z", "D14")
        assert_instant_equal(send_ats["D7"], "2026-09-08T00:00:00Z", "D7")
        assert_instant_equal(send_ats["D1"], "2026-09-14T00:00:00Z", "D1")

    def test_resubmit_after_return_completes_cycle(self, api):
        """PRD §3.3: "On success the application moves `DRAFT` → `SUBMITTED`,
        its `verified_match_score` is recomputed using
        `verified_gpa_hundredths` when set and `gpa_hundredths` otherwise,
        `submitted_at` is stamped with the current logical instant, and every
        `SCHEDULED` reminder is suppressed."
        PRD §3.3: "The correction loop runs through the coordinator's return
        action: a `SUBMITTED` application returns to `DRAFT`, its
        `returned_count` increases by one".

        Design: Difficulty/non_linear_state_machine/application_return_resubmission_cycle
        """
        student, app = self._submitted_application()
        get_success_data(api.return_application(app["id"], COORD))

        resubmitted = validate_success(
            api.submit_application(app["id"], make_student_headers(student["id"]))
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["returned_count"] == 1, (
            "returned_count stays at 1 after the resubmit"
        )
        assert resubmitted["submitted_at"], "submitted_at re-stamped"

        scheduled, meta = list_reminders(app["id"], {"status": "SCHEDULED"})
        assert meta["total_count"] == 0, "second submit suppresses the re-armed cadence"
        suppressed, meta = list_reminders(app["id"], {"status": "SUPPRESSED"})
        assert meta["total_count"] == 6, "both cadence rounds now suppressed"
