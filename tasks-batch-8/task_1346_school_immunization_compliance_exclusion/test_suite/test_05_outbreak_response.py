"""Outbreak declaration and lift: suspension cascade, exclusion, reinstatement."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_compliance_notice,
    assert_instants_equal,
    assert_outbreak_event,
    create_outbreak_event_payload,
    create_student_with_approved_exemption,
    declare_outbreak,
    get_student,
    lift_outbreak,
    list_exemptions,
    list_notices,
    validate_error,
    validate_success,
)


class TestOutbreakDeclarationCascade:

    def test_outbreak_declare_suspends_exemption_and_excludes(self):
        """PRD section 3.6: "Declaration triggers an immediate protective cascade.
        Every ExemptionRequest in `APPROVED` status whose student's `school_code`
        and whose `vaccine_code` match the event transitions to
        `SUSPENDED_OUTBREAK` — a suspended exemption no longer satisfies its
        requirement under either lens. Each affected student is then re-evaluated,
        and because the requirement is now unsatisfied, the student transitions to
        `EXCLUDED` regardless of whether they were previously
        `ENROLLED_PROVISIONAL`, `ENROLLED_COMPLIANT`, or `NON_COMPLIANT`."

        Design: Difficulty/transitive_cascade/outbreak_declare_depth3_cascade
        """
        student, exemption = create_student_with_approved_exemption("SCH-X")
        assert student["status"] == "ENROLLED_COMPLIANT"
        assert exemption["status"] == "APPROVED"

        outbreak = declare_outbreak("SCH-X", "MMR")
        assert_outbreak_event(outbreak)
        assert outbreak["status"] == "ACTIVE"

        exemptions, _ = list_exemptions(student["id"])
        assert exemptions[0]["status"] == "SUSPENDED_OUTBREAK", (
            "hop 1: the matching APPROVED exemption must be suspended"
        )
        excluded = get_student(student["id"])
        assert excluded["status"] == "EXCLUDED", (
            "hop 2: suspension makes the requirement unsatisfied, so the student "
            "is excluded"
        )

    def test_outbreak_declare_creates_immediate_exclusion_notice(self):
        """PRD section 3.6: "For each excluded student the system creates an
        `OUTBREAK_EXCLUSION` notice already in `EXCLUSION_EFFECTIVE` status, with
        `issue_date` and `exclusion_date` both set to the current clock, and
        increments the student's `version`."
        PRD section 3.5: "For an `OUTBREAK_EXCLUSION` notice the exclusion date
        equals the issue date: exclusion is immediate, and such notices are created
        by the system alone during an outbreak cascade, never by hand."

        Design: Difficulty/transitive_cascade/outbreak_declare_depth3_cascade
        """
        student, _ = create_student_with_approved_exemption("SCH-X")
        declare_outbreak("SCH-X", "MMR")

        notices, meta = list_notices(student["id"])
        assert meta["total_count"] == 1, (
            "hop 3: exactly one notice is created for the excluded student"
        )
        notice = notices[0]
        assert_compliance_notice(notice)
        assert notice["notice_type"] == "OUTBREAK_EXCLUSION"
        assert notice["status"] == "EXCLUSION_EFFECTIVE"
        assert_instants_equal(notice["exclusion_date"], notice["issue_date"],
                              "outbreak exclusion is immediate: exclusion_date "
                              "equals issue_date")
        assert_instants_equal(notice["issue_date"], "2026-08-01T00:00:00Z",
                              "issue_date must be stamped from the logical clock")


class TestOutbreakLift:

    def test_outbreak_lift_reinstates_and_readmits(self):
        """PRD section 3.6: "Every matching exemption in `SUSPENDED_OUTBREAK`
        returns to `APPROVED`. Each affected student is re-evaluated: a student
        whose requirements are now all satisfied (typically because the reinstated
        exemption satisfies the outstanding requirement) transitions from
        `EXCLUDED` to `ENROLLED_COMPLIANT` with the deficiency list cleared; a
        student still deficient under LOCAL_RECORDS after reinstatement transitions
        from `EXCLUDED` to `NON_COMPLIANT` with `deficiency_vaccine_codes`
        recomputed. In both cases the student's `OUTBREAK_EXCLUSION` notice in
        `EXCLUSION_EFFECTIVE` moves to `CURED` with `resolved_at` stamped, and the
        student's `version` is incremented."

        Design: Corner/state_machines/outbreak_lift_reinstates_and_readmits
        """
        student, _ = create_student_with_approved_exemption("SCH-XL")
        outbreak = declare_outbreak("SCH-XL", "MMR")
        assert get_student(student["id"])["status"] == "EXCLUDED"

        lifted = lift_outbreak(outbreak["id"])
        assert_outbreak_event(lifted)
        assert lifted["status"] == "LIFTED"
        assert lifted["lifted_at"] is not None

        exemptions, _ = list_exemptions(student["id"])
        assert exemptions[0]["status"] == "APPROVED"
        readmitted = get_student(student["id"])
        assert readmitted["status"] == "ENROLLED_COMPLIANT"
        assert readmitted["deficiency_vaccine_codes"] == []

        notices, _ = list_notices(student["id"])
        assert notices[0]["status"] == "CURED"
        assert_instants_equal(notices[0]["resolved_at"], "2026-08-01T00:00:00Z",
                              "resolved_at must be stamped from the current clock")

    def test_lift_twice_rejected(self, officer_headers):
        """PRD section 3.6: "Lifting the outbreak — again a `DistrictHealthOfficer`
        action, permitted only while the event is `ACTIVE` and otherwise rejected
        with `ERR_OUTBREAK_ALREADY_LIFTED` — moves the event to its terminal
        `LIFTED` status, stamps `lifted_at`, and runs the cascade in reverse."

        Design: Corner/state_machines/lift_twice_rejected
        """
        outbreak = declare_outbreak("SCH-L2", "MMR")
        lift_outbreak(outbreak["id"])
        resp = api_client.lift_outbreak_event(outbreak["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_OUTBREAK_ALREADY_LIFTED)

    def test_duplicate_active_outbreak_rejected(self, officer_headers):
        """PRD section 3.6: "Only one active outbreak may exist per
        school-and-vaccine pair; declaring a duplicate while one is still `ACTIVE`
        is rejected with `ERR_OUTBREAK_ALREADY_ACTIVE`."

        Design: Corner/validations/duplicate_active_outbreak_rejected
        """
        declare_outbreak("SCH-DUP", "MMR")
        resp = api_client.create_outbreak_event(
            create_outbreak_event_payload(school_code="SCH-DUP", vaccine_code="MMR"),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_OUTBREAK_ALREADY_ACTIVE)
