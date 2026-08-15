"""Notices, compliance sweeps, exclusion, readmission, and roster conservation."""
from test_helpers import (
    ApiErrorId,
    add_manual_dose,
    api_client,
    assert_compliance_notice,
    assert_instants_equal,
    assert_student,
    book_appointment,
    create_compliance_notice_payload,
    create_deficient_student,
    create_mmr_requirement,
    create_open_session,
    create_student,
    get_student,
    list_notices,
    rescind_notice_payload,
    run_sweep,
    set_logical_clock,
    setup_student_excluded_via_sweep,
    setup_student_non_compliant_with_notice,
    setup_two_student_roster,
    validate_error,
    validate_paginated,
    validate_success,
    verify_record,
)


class TestProvisionalDeadlineBoundary:

    def test_provisional_deadline_exact_boundary_is_noop(self):
        """PRD section 3.5: "Every student still in `ENROLLED_PROVISIONAL` whose
        `provisional_deadline` is **strictly** in the past — the current clock is
        later than the deadline; sitting exactly at the deadline leaves the student
        provisional — and who has at least one applicable requirement unsatisfied
        under LOCAL_RECORDS, transitions to `NON_COMPLIANT`."

        Design: Difficulty/boundary_precision_check/provisional_deadline_inclusive_boundary
        """
        # Enrolled 2026-08-01T00:00:00Z -> provisional_deadline 2026-08-31T00:00:00Z.
        student = create_deficient_student("SCH-B1")
        set_logical_clock("2026-08-31T00:00:00Z")
        sweep = run_sweep()
        assert sweep["provisional_expired_count"] == 0, (
            "sitting exactly at the deadline leaves the student provisional"
        )
        after = get_student(student["id"])
        assert after["status"] == "ENROLLED_PROVISIONAL"
        _, meta = list_notices(student["id"])
        assert meta["total_count"] == 0, "no notice may be issued at the deadline"

    def test_one_second_past_provisional_deadline_flips(self):
        """PRD section 3.5: "Every student still in `ENROLLED_PROVISIONAL` whose
        `provisional_deadline` is **strictly** in the past — the current clock is
        later than the deadline; sitting exactly at the deadline leaves the student
        provisional — and who has at least one applicable requirement unsatisfied
        under LOCAL_RECORDS, transitions to `NON_COMPLIANT`. The sweep issues that
        student an `INITIAL_NONCOMPLIANCE` notice in `ISSUED` status with
        `issue_date` set to the current clock and `exclusion_date` 14 days out,
        recomputes `deficiency_vaccine_codes`, and increments the student's
        `version`."

        Design: Difficulty/boundary_precision_check/provisional_deadline_inclusive_boundary
        """
        student = create_deficient_student("SCH-B1")
        set_logical_clock("2026-08-31T00:00:01Z")
        sweep = run_sweep()
        assert sweep["provisional_expired_count"] == 1
        after = get_student(student["id"])
        assert after["status"] == "NON_COMPLIANT"
        assert after["deficiency_vaccine_codes"] == ["MMR"]

        notices, meta = list_notices(student["id"])
        assert meta["total_count"] == 1
        notice = notices[0]
        assert_compliance_notice(notice)
        assert notice["notice_type"] == "INITIAL_NONCOMPLIANCE"
        assert notice["status"] == "ISSUED"
        assert_instants_equal(notice["issue_date"], "2026-08-31T00:00:01Z",
                              "issue_date must be stamped from the logical clock")
        assert_instants_equal(notice["exclusion_date"], "2026-09-14T00:00:01Z",
                              "exclusion_date must be issue_date + 14 days")


class TestExclusionAndReadmission:

    def test_sweep_excludes_student_at_exclusion_date(self):
        """PRD section 3.5: "Every `ISSUED` notice whose `exclusion_date` has been
        reached or passed — the comparison here is inclusive: sitting exactly at
        the exclusion date escalates — while the student is still deficient under
        LOCAL_RECORDS, transitions to `EXCLUSION_EFFECTIVE`, and the student
        transitions from `NON_COMPLIANT` to `EXCLUDED` with a `version` increment."

        Design: Difficulty/non_linear_state_machine/student_exclusion_readmission_cycle
        """
        student = create_deficient_student("SCH-D")

        set_logical_clock("2026-09-01T00:00:00Z")
        sweep1 = run_sweep()
        assert sweep1["provisional_expired_count"] == 1
        mid = get_student(student["id"])
        assert mid["status"] == "NON_COMPLIANT"
        notices, _ = list_notices(student["id"])
        assert notices[0]["status"] == "ISSUED"
        assert_instants_equal(notices[0]["exclusion_date"], "2026-09-15T00:00:00Z",
                              "issue 2026-09-01 + 14 days")

        # Sitting exactly at the exclusion date escalates (inclusive comparison).
        set_logical_clock("2026-09-15T00:00:00Z")
        sweep2 = run_sweep()
        assert sweep2["notices_escalated_count"] == 1
        assert sweep2["students_excluded_count"] == 1
        final = get_student(student["id"])
        assert final["status"] == "EXCLUDED"
        notices, _ = list_notices(student["id"])
        assert notices[0]["status"] == "EXCLUSION_EFFECTIVE"

    def test_dose_verify_readmits_excluded_student(self):
        """PRD section 3.5: "Even a student in `EXCLUDED` can be readmitted the same
        way: a dose verification or clinic completion that brings the record to
        full satisfaction moves the student from `EXCLUDED` back to
        `ENROLLED_COMPLIANT`, curing every notice in `ISSUED` or
        `EXCLUSION_EFFECTIVE` with `resolved_at` stamped, clearing the deficiency
        list, and incrementing `version`."

        Design: Difficulty/non_linear_state_machine/student_exclusion_readmission_cycle
        """
        student, notice = setup_student_excluded_via_sweep("SCH-D")
        assert student["status"] == "EXCLUDED"
        assert notice["status"] == "EXCLUSION_EFFECTIVE"

        record = add_manual_dose(student["id"], student["version"],
                                 administered_date="2026-09-15T00:00:00Z")
        verify_record(record["id"])

        final = get_student(student["id"])
        assert final["status"] == "ENROLLED_COMPLIANT"
        assert final["deficiency_vaccine_codes"] == []
        notices, _ = list_notices(student["id"])
        assert notices[0]["status"] == "CURED"
        assert_instants_equal(notices[0]["resolved_at"], "2026-09-15T00:00:00Z",
                              "resolved_at must be stamped from the current clock")


class TestDoseVerifyCureCascade:

    def test_dose_verify_cures_issued_notice_student_side(self):
        """PRD section 3.5: "Whenever a student in `NON_COMPLIANT` reaches full
        satisfaction under LOCAL_RECORDS — through a dose verification, a completed
        clinic appointment, or an exemption approval — the student transitions to
        `ENROLLED_COMPLIANT`, all of that student's notices still in `ISSUED` move
        to `CURED` with `resolved_at` set to the current clock,
        `deficiency_vaccine_codes` is cleared, and the student's `version` is
        incremented."

        Design: Difficulty/transitive_cascade/dose_verify_depth2_cascade
        """
        student, notice, _ = setup_student_non_compliant_with_notice("SCH-E")
        assert student["status"] == "NON_COMPLIANT"
        assert notice["status"] == "ISSUED"

        record = add_manual_dose(student["id"], student["version"],
                                 administered_date="2026-09-01T00:00:00Z")
        verified = verify_record(record["id"])
        assert verified["status"] == "VERIFIED"

        final = get_student(student["id"])
        assert_student(final)
        assert final["status"] == "ENROLLED_COMPLIANT"
        assert final["deficiency_vaccine_codes"] == []
        assert final["version"] > student["version"]

    def test_dose_verify_cures_issued_notice_notice_side(self):
        """PRD section 3.5: "Whenever a student in `NON_COMPLIANT` reaches full
        satisfaction under LOCAL_RECORDS — through a dose verification, a completed
        clinic appointment, or an exemption approval — the student transitions to
        `ENROLLED_COMPLIANT`, all of that student's notices still in `ISSUED` move
        to `CURED` with `resolved_at` set to the current clock,
        `deficiency_vaccine_codes` is cleared, and the student's `version` is
        incremented."

        Design: Difficulty/transitive_cascade/dose_verify_depth2_cascade
        """
        student, notice, _ = setup_student_non_compliant_with_notice("SCH-E")

        record = add_manual_dose(student["id"], student["version"],
                                 administered_date="2026-09-01T00:00:00Z")
        verify_record(record["id"])

        notices, meta = list_notices(student["id"])
        assert meta["total_count"] == 1
        cured = notices[0]
        assert_compliance_notice(cured)
        assert cured["status"] == "CURED"
        assert_instants_equal(cured["resolved_at"], "2026-09-01T00:00:00Z",
                              "resolved_at must be stamped from the current clock")


class TestNoticeGuards:

    def test_rescind_terminal_notice_rejected(self, officer_headers):
        """PRD section 3.5: "An officer may rescind a notice still in `ISSUED` (for
        example, a clerical error), supplying a `reason`; the notice moves to
        `RESCINDED` with `resolved_at` set to the current clock. Rescinding a
        notice that has already been cured, rescinded, or made effective is
        rejected with `ERR_NOTICE_NOT_OPEN`."

        Design: Corner/state_machines/rescind_terminal_notice_rejected
        """
        _, notice, _ = setup_student_non_compliant_with_notice("SCH-N")
        assert notice["status"] == "ISSUED"

        first = validate_success(
            api_client.rescind_notice(notice["id"], rescind_notice_payload(),
                                      officer_headers),
            200,
        )
        assert_compliance_notice(first)
        assert first["status"] == "RESCINDED"
        assert_instants_equal(first["resolved_at"], "2026-09-01T00:00:00Z",
                              "resolved_at must be stamped from the current clock")

        resp = api_client.rescind_notice(
            notice["id"], rescind_notice_payload(reason="second attempt"),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOTICE_NOT_OPEN)

    def test_manual_notice_requires_non_compliant(self, officer_headers):
        """PRD section 3.5: "A `DistrictHealthOfficer` may also issue an
        `INITIAL_NONCOMPLIANCE` notice manually against a student, but only while
        that student's `status` is `NON_COMPLIANT`; the attempt against a student
        in any other status — or any attempt to hand-create an
        `OUTBREAK_EXCLUSION` notice — is rejected with `ERR_NOTICE_NOT_ALLOWED`
        (HTTP 422)."

        Design: Corner/validations/manual_notice_requires_non_compliant
        """
        student = create_student("SCH-MN", legal_name="Notice Early")
        assert student["status"] == "ENROLLED_PROVISIONAL"
        resp = api_client.create_compliance_notice(
            student["id"], create_compliance_notice_payload(), officer_headers
        )
        validate_error(resp, ApiErrorId.ERR_NOTICE_NOT_ALLOWED)


class TestSweepPasses:

    def test_sweep_marks_overdue_appointment_no_show(self, nurse_headers):
        """PRD section 3.5: "Every appointment still `BOOKED` whose `end_time` is
        earlier than the current clock transitions to `NO_SHOW`, with the host
        session's `booked_count` recomputed and its `version` incremented (§3.7)."

        Design: Corner/state_machines/sweep_marks_overdue_appointment_no_show
        """
        student = create_student("SCH-Y", legal_name="No Show")
        session = create_open_session("SCH-C9",
                                      session_date="2026-08-02T09:00:00Z",
                                      duration_minutes=60, capacity=5)
        appointment = book_appointment(session["id"], student["id"],
                                       start_time="2026-08-02T09:00:00Z",
                                       end_time="2026-08-02T09:30:00Z")
        assert appointment["status"] == "BOOKED"

        set_logical_clock("2026-08-03T00:00:00Z")
        sweep = run_sweep()
        assert sweep["appointments_no_show_count"] == 1

        after = validate_success(
            api_client.get_appointment(appointment["id"], nurse_headers), 200
        )
        assert after["status"] == "NO_SHOW"
        session_after = validate_success(
            api_client.get_clinic_session(session["id"], nurse_headers), 200
        )
        assert session_after["booked_count"] == 0, (
            "a no-show appointment frees the session seat"
        )

    def test_sweep_no_op_when_no_deadlines_passed(self):
        """PRD section 2.4: "At server startup, before any operator action, the
        logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back
        to wall-clock time."
        PRD section 3.5: "the district's compliance sweep — an ops-run checkpoint a
        `DistrictHealthOfficer` triggers, which walks four kinds of work and
        reports back the counts `provisional_expired_count`,
        `notices_escalated_count`, `students_excluded_count`,
        `students_marked_compliant_count`, and `appointments_no_show_count`."

        Design: Corner/cross_cutting_layers/sweep_no_op_when_no_deadlines_passed
        """
        student = create_deficient_student("SCH-SW")
        sweep = run_sweep()
        assert sweep["provisional_expired_count"] == 0
        assert sweep["notices_escalated_count"] == 0
        assert sweep["students_excluded_count"] == 0
        assert sweep["students_marked_compliant_count"] == 0
        assert sweep["appointments_no_show_count"] == 0
        after = get_student(student["id"])
        assert after["status"] == "ENROLLED_PROVISIONAL", (
            "a no-op sweep must not move a student still inside the window"
        )


class TestRosterConservation:

    def test_exclusion_keeps_roster_membership(self, officer_headers):
        """PRD section 3.5: "Every `ISSUED` notice whose `exclusion_date` has been
        reached or passed — the comparison here is inclusive: sitting exactly at
        the exclusion date escalates — while the student is still deficient under
        LOCAL_RECORDS, transitions to `EXCLUSION_EFFECTIVE`, and the student
        transitions from `NON_COMPLIANT` to `EXCLUDED` with a `version` increment."
        PRD section 2.3: "List responses carry the following fields in the `meta`
        object of the response envelope: `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Difficulty/compensating_invariant/exclude_readmit_roster_conservation
        """
        deficient, compliant = setup_two_student_roster("SCH-R2")

        def roster():
            members, meta = validate_paginated(
                api_client.list_students(officer_headers,
                                         params={"school_code": "SCH-R2"})
            )
            return members, meta

        members, meta = roster()
        assert meta["total_count"] == 2

        set_logical_clock("2026-09-01T00:00:00Z")
        run_sweep()
        set_logical_clock("2026-09-15T00:00:00Z")
        run_sweep()

        assert get_student(deficient["id"])["status"] == "EXCLUDED"
        assert get_student(compliant["id"])["status"] == "ENROLLED_COMPLIANT"
        members, meta = roster()
        assert meta["total_count"] == 2, (
            "exclusion is a posture change; it must not remove roster members"
        )
        non_withdrawn = [m for m in members if m["status"] != "WITHDRAWN"]
        assert len(non_withdrawn) == 2

    def test_readmission_keeps_roster_membership(self, officer_headers):
        """PRD section 3.5: "Even a student in `EXCLUDED` can be readmitted the same
        way: a dose verification or clinic completion that brings the record to
        full satisfaction moves the student from `EXCLUDED` back to
        `ENROLLED_COMPLIANT`, curing every notice in `ISSUED` or
        `EXCLUSION_EFFECTIVE` with `resolved_at` stamped, clearing the deficiency
        list, and incrementing `version`."

        Design: Difficulty/compensating_invariant/exclude_readmit_roster_conservation
        """
        deficient, compliant = setup_two_student_roster("SCH-R2")
        set_logical_clock("2026-09-01T00:00:00Z")
        run_sweep()
        set_logical_clock("2026-09-15T00:00:00Z")
        run_sweep()
        excluded = get_student(deficient["id"])
        assert excluded["status"] == "EXCLUDED"

        record = add_manual_dose(excluded["id"], excluded["version"],
                                 administered_date="2026-09-15T00:00:00Z")
        verify_record(record["id"])

        assert get_student(deficient["id"])["status"] == "ENROLLED_COMPLIANT"
        members, meta = validate_paginated(
            api_client.list_students(officer_headers, params={"school_code": "SCH-R2"})
        )
        assert meta["total_count"] == 2, (
            "readmission is a posture change; it must not alter roster membership"
        )
        non_withdrawn = [m for m in members if m["status"] != "WITHDRAWN"]
        assert len(non_withdrawn) == 2
