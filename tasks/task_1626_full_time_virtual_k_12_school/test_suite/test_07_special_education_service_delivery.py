"""Special-education service delivery: gating, lifecycle, and rescheduling."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_district,
    create_enrolled_student,
    create_service_delivery_payload,
    create_special_ed_enrolled_student,
    create_student,
    create_teacher,
    set_clock,
    setup_missed_service_delivery,
    setup_service_delivery,
    validate_error,
    validate_success,
    verify_student,
)

SPECIAL_ED = TEST_USERS["special_ed_coordinator_headers"]


class TestCreationGates:
    def test_service_delivery_on_eligible_student_rejected(self, api):
        """PRD §3.8: "Validation runs in order: the referenced student and
        provider must exist (`ERR_NOT_FOUND`); the student must be `ENROLLED`
        (`ERR_INVALID_STATE`); the provider's `certification_state_codes` must
        include the `state_code` of the student's district of residence, or
        the request fails with `ERR_PROVIDER_NOT_CERTIFIED_IN_STATE`; and the
        student's `special_education_flag` must be true, or the request fails
        with `ERR_NOT_SPECIAL_ED_STUDENT`."

        Design: Difficulty/cross_entity_state_dependency/service_delivery_create_gated_on_student_enrolled
        """
        district = create_district(district_code="D-060", state_code="CA",
                                   funding_rate_cents=500, enrollment_cap=10)
        student = create_student(district["id"], legal_name="Paul",
                                 date_of_birth="2012-09-09T00:00:00Z",
                                 grade_level=6, special_education_flag=True)
        student = verify_student(student["id"])
        assert student["enrollment_status"] == "ELIGIBLE"
        provider = create_teacher(full_name="Ms. Ray",
                                  certification_state_codes=["CA"])
        resp = api.create_service_delivery(
            create_service_delivery_payload(
                student["id"], provider["id"], service_type="COUNSELING",
                scheduled_at="2026-08-10T10:00:00Z", duration_minutes=30),
            SPECIAL_ED,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_service_delivery_on_applied_student_rejected(self, api):
        """PRD §2.7: "This stage also covers the enrollment-dependent creation
        rules: scheduling a special-education session, issuing a stipend,
        creating a teacher assignment, and booking a proctored seat each
        require the referenced student to be `ENROLLED`. Violations yield
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/service_delivery_create_gated_on_student_enrolled
        """
        district = create_district(district_code="D-060b", state_code="CA",
                                   funding_rate_cents=500, enrollment_cap=10)
        student = create_student(district["id"], legal_name="Paula",
                                 special_education_flag=True)
        assert student["enrollment_status"] == "APPLIED"
        provider = create_teacher(full_name="Ms. Ray",
                                  certification_state_codes=["CA"])
        resp = api.create_service_delivery(
            create_service_delivery_payload(
                student["id"], provider["id"], service_type="COUNSELING",
                scheduled_at="2026-08-10T10:00:00Z", duration_minutes=30),
            SPECIAL_ED,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_provider_not_certified_in_student_state_rejected(self, api):
        """PRD §3.8: "the provider's `certification_state_codes` must include
        the `state_code` of the student's district of residence, or the
        request fails with `ERR_PROVIDER_NOT_CERTIFIED_IN_STATE`"

        Design: Corner/validations/provider_not_certified_in_student_state_rejected
        """
        district = create_district(district_code="D-134", state_code="CA",
                                   funding_rate_cents=500, enrollment_cap=50)
        _, student = create_special_ed_enrolled_student(district=district,
                                                        legal_name="Z4")
        provider = create_teacher(full_name="P",
                                  certification_state_codes=["NV"])
        resp = api.create_service_delivery(
            create_service_delivery_payload(
                student["id"], provider["id"], service_type="COUNSELING",
                scheduled_at="2026-08-10T10:00:00Z", duration_minutes=30),
            SPECIAL_ED,
        )
        validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_CERTIFIED_IN_STATE)

    def test_service_delivery_for_non_special_ed_student_rejected(self, api):
        """PRD §3.8: "and the student's `special_education_flag` must be true,
        or the request fails with `ERR_NOT_SPECIAL_ED_STUDENT`."

        Design: Corner/validations/service_delivery_for_non_special_ed_student_rejected
        """
        district = create_district(district_code="D-135", state_code="CA",
                                   funding_rate_cents=500, enrollment_cap=50)
        _, student = create_enrolled_student(district=district, legal_name="Z5")
        assert student["special_education_flag"] is False
        provider = create_teacher(full_name="P2",
                                  certification_state_codes=["CA"])
        resp = api.create_service_delivery(
            create_service_delivery_payload(
                student["id"], provider["id"], service_type="COUNSELING",
                scheduled_at="2026-08-10T10:00:00Z", duration_minutes=30),
            SPECIAL_ED,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_SPECIAL_ED_STUDENT)


class TestMissedAndReschedule:
    def test_reschedule_returns_missed_session_to_scheduled(self, api):
        """PRD §3.8: "A `MISSED` session can be brought back: rescheduling
        takes a new `scheduled_at` that must lie strictly in the future
        relative to the logical clock — anything else is
        `ERR_SCHEDULE_TIME_IN_PAST` — writes the new time over the old, and
        returns the session to `SCHEDULED`."

        Design: Difficulty/non_linear_state_machine/service_delivery_missed_to_scheduled_loop
        """
        ctx = setup_missed_service_delivery(
            scheduled_at="2026-08-05T10:00:00Z", duration_minutes=30,
            clock_after="2026-08-05T11:00:00Z", student_state="NV")
        delivery = ctx["delivery"]
        assert delivery["delivery_status"] == "MISSED"
        resp = api.reschedule_service_delivery(delivery["id"],
                                               "2026-08-06T10:00:00Z",
                                               SPECIAL_ED)
        rescheduled = validate_success(resp, 200)
        assert rescheduled["delivery_status"] == "SCHEDULED"

    def test_reschedule_writes_new_scheduled_at(self, api):
        """PRD §3.8: "A `MISSED` session can be brought back: rescheduling
        takes a new `scheduled_at` that must lie strictly in the future
        relative to the logical clock — anything else is
        `ERR_SCHEDULE_TIME_IN_PAST` — writes the new time over the old, and
        returns the session to `SCHEDULED`."

        Design: Difficulty/non_linear_state_machine/service_delivery_missed_to_scheduled_loop
        """
        ctx = setup_missed_service_delivery(
            scheduled_at="2026-08-05T10:00:00Z", duration_minutes=30,
            clock_after="2026-08-05T11:00:00Z", student_state="NV")
        delivery = ctx["delivery"]
        rescheduled = validate_success(
            api.reschedule_service_delivery(delivery["id"],
                                            "2026-08-06T10:00:00Z",
                                            SPECIAL_ED),
            200)
        assert rescheduled["scheduled_at"].startswith("2026-08-06T10:00"), (
            f"reschedule writes the new time over the old, got "
            f"{rescheduled['scheduled_at']!r}")
        assert rescheduled["scheduled_at"] != delivery["scheduled_at"]

    def test_reschedule_to_past_rejected(self, api):
        """PRD §3.8: "A `MISSED` session can be brought back: rescheduling
        takes a new `scheduled_at` that must lie strictly in the future
        relative to the logical clock — anything else is
        `ERR_SCHEDULE_TIME_IN_PAST` — writes the new time over the old, and
        returns the session to `SCHEDULED`."

        Design: Corner/validations/reschedule_to_past_rejected
        """
        ctx = setup_missed_service_delivery(
            scheduled_at="2026-08-05T10:00:00Z", duration_minutes=30,
            clock_after="2026-08-05T11:00:00Z")
        resp = api.reschedule_service_delivery(ctx["delivery"]["id"],
                                               "2026-08-04T10:00:00Z",
                                               SPECIAL_ED)
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_TIME_IN_PAST)

    def test_mark_missed_before_duration_elapsed_rejected(self, api):
        """PRD §3.8: "Marking a session missed moves it from `SCHEDULED` to
        `MISSED`, but only once the logical clock has moved strictly past the
        end of the scheduled session — the `scheduled_at` instant plus the
        planned `duration_minutes`; an earlier attempt is rejected with
        `ERR_MARK_MISSED_TOO_EARLY`."

        Design: Corner/validations/mark_missed_before_duration_elapsed_rejected
        """
        ctx = setup_service_delivery(scheduled_at="2026-08-05T10:00:00Z",
                                     duration_minutes=60)
        # Mid-session: the 60-minute session ends at 11:00; clock is 10:30.
        set_clock("2026-08-05T10:30:00Z")
        resp = api.mark_service_missed(ctx["delivery"]["id"], SPECIAL_ED)
        validate_error(resp, ApiErrorId.ERR_MARK_MISSED_TOO_EARLY)
