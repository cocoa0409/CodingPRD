"""Authentication, role authorization, and entity-backed ownership (PRD §2.1, §2.9)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_readiness_report,
    book_mock_interview,
    create_ceremony,
    create_fee_waiver,
    create_general_volunteer,
    create_program,
    create_screened_applicant,
    create_section,
    get_section,
    make_applicant_headers,
    make_volunteer_headers,
    register_applicant,
    submit_fee_waiver,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["intake_coordinator_headers"]


class TestAuthentication:
    def test_request_missing_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity in
        which they act. The system recognizes exactly four roles: `ProgramAdmin`,
        `IntakeCoordinator`, `Volunteer`, and `Applicant`. A request missing either
        header, or naming a role outside this set, is rejected with
        `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/request_missing_headers_returns_unauthenticated
        """
        create_program()
        response = api.get_current_program(headers={})
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_existence_checked_before_ownership(self, api):
        """PRD §2.9: "Validations on a request execute in a fixed priority order, and
        an earlier failure masks every later check."
        PRD §2.9: "4. **Existence.** Path identifiers resolve left to right and
        body-supplied foreign keys exist, else `ERR_NOT_FOUND` (HTTP 404)."
        PRD §2.9: "5. **Ownership.** Entity-backed actors may touch only their own
        rows, else `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/validations/existence_checked_before_ownership
        """
        create_program()
        owner = register_applicant(full_name="Self")
        # The target id does not exist at all; existence (tier 4) masks the ownership
        # check (tier 5) that would also fail for this entity-backed caller.
        response = api.get_applicant(
            NON_EXISTENT_UUID, make_applicant_headers(owner["id"])
        )
        validate_error(response, ApiErrorId.ERR_NOT_FOUND)


class TestRoleAuthorization:
    def test_applicant_cannot_create_class_section(self, api):
        """PRD §3.4: "Instruction is organized into **class sections**, created by a
        `ProgramAdmin` with a `title`, a `weekday` (one of `MON`, `TUE`, `WED`,
        `THU`, `FRI`, `SAT`, `SUN`), a meeting window given as `start_minute` and
        `end_minute` in minutes from midnight (the end must be later than the start),
        a `room_id`, an `instructor_volunteer_id`, a `capacity` of at least one seat,
        and a `total_sessions` count of at least two."
        PRD §2.9: "3. **Role authorization.** The role must be listed for the
        endpoint, else `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/applicant_cannot_create_class_section
        """
        create_program()
        applicant = register_applicant()
        response = api.create_class_section(
            {"title": "Nope", "weekday": "MON", "start_minute": 600,
             "end_minute": 660, "room_id": "R1",
             "instructor_volunteer_id": NON_EXISTENT_UUID, "capacity": 2,
             "total_sessions": 10},
            make_applicant_headers(applicant["id"]),
        )
        validate_error(response, ApiErrorId.ERR_FORBIDDEN)

    def test_volunteer_cannot_decide_fee_waiver(self, api):
        """PRD §3.7: "Adjudication belongs to a `ProgramAdmin`, who decides a
        `SUBMITTED` request by supplying a `decision` together with the verified
        evidence `documented_income_cents` and `documented_benefit`."
        PRD §2.1: "A request whose role is not listed among an endpoint's permitted
        roles is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/volunteer_cannot_decide_fee_waiver
        """
        create_program()
        applicant, _ = create_screened_applicant()
        request = create_fee_waiver(applicant["id"], household_size=1,
                                    self_reported_income_cents=1000000)
        submit_fee_waiver(request["id"], 2)
        volunteer = create_general_volunteer(full_name="Vic")

        response = api.decide_fee_waiver_request(
            request["id"],
            {"decision": "APPROVED", "documented_income_cents": 1000000,
             "documented_benefit": False},
            make_volunteer_headers(volunteer["id"]),
        )
        validate_error(response, ApiErrorId.ERR_FORBIDDEN)
        rows, meta = validate_paginated(api.list_fee_waiver_requests(COORD))
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "SUBMITTED", "the forbidden decide changed nothing"

    def test_coordinator_cannot_conclude_ceremony(self, api):
        """PRD §3.9: "Concluding a ceremony is a `ProgramAdmin` action guarded twice:
        the ceremony must be `SCHEDULED` (`ERR_INVALID_STATE`) and the clock must be
        at or after `ceremony_date` (`ERR_CEREMONY_NOT_YET_HELD`)."
        PRD §2.1: "A request whose role is not listed among an endpoint's permitted
        roles is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/coordinator_cannot_conclude_ceremony
        """
        create_program()
        # Dated before the default clock so only the role guard can fail.
        ceremony = create_ceremony(ceremony_date="2026-07-01T17:00:00Z", capacity=2)
        response = api.conclude_oath_ceremony(ceremony["id"], COORD)
        validate_error(response, ApiErrorId.ERR_FORBIDDEN)


class TestOwnership:
    def test_volunteer_cannot_score_others_interview(self, api):
        """PRD §3.3: "Scoring belongs to the assigned volunteer alone — any other
        actor is rejected with `ERR_FORBIDDEN` — and only while the interview is
        `SCHEDULED` (`ERR_INVALID_STATE` otherwise)."
        PRD §2.1: "An entity-backed actor touching a row it does not own — an
        applicant reaching for another applicant's enrollment, a volunteer scoring an
        interview assigned to a colleague — is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/volunteer_cannot_score_others_interview
        """
        create_program()
        applicant, _ = create_screened_applicant()
        assigned = create_general_volunteer(full_name="V1")
        other = create_general_volunteer(full_name="V2")
        interview = book_mock_interview(applicant["id"], assigned["id"],
                                        scheduled_start="2026-08-10T10:00:00Z")

        response = api.score_mock_interview(
            interview["id"], {"english_pct": 80, "civics_pct": 70, "n400_pct": 60},
            make_volunteer_headers(other["id"]),
        )
        validate_error(response, ApiErrorId.ERR_FORBIDDEN)
        assert api.get_mock_interview(interview["id"], COORD).json()["data"]["status"] == "SCHEDULED"

    def test_applicant_cannot_enroll_other_applicant(self, api):
        """PRD §2.1: "When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of
        the acting Applicant, and ownership checks on any resource that references an
        Applicant compare the resource's foreign-key field to `X-User-ID`. An
        entity-backed actor touching a row it does not own — an applicant reaching
        for another applicant's enrollment, a volunteer scoring an interview assigned
        to a colleague — is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/applicant_cannot_enroll_other_applicant
        """
        create_program()
        instructor = create_general_volunteer(full_name="Instructor")
        section = create_section(instructor["id"], capacity=3, total_sessions=10)
        caller, _ = create_screened_applicant()
        target, _ = create_screened_applicant()

        response = api.create_enrollment(
            {"applicant_id": target["id"], "class_section_id": section["id"],
             "expected_section_version": get_section(section["id"])["version"]},
            make_applicant_headers(caller["id"]),
        )
        validate_error(response, ApiErrorId.ERR_FORBIDDEN)
        assert get_section(section["id"])["enrolled_count"] == 0

    def test_applicant_reads_own_records_ok(self, api):
        """PRD §3.2: "Applicants may read their own record; staff may read any."
        PRD §3.3: "Readiness is a computed report on an applicant, available to staff
        and to the applicant themselves, with a `variant` query selecting `attained`
        (the default) or `projected`."

        Design: Corner/rbac/applicant_reads_own_records_ok
        """
        create_program()
        applicant, screening = create_screened_applicant()
        headers = make_applicant_headers(applicant["id"])

        own = validate_success(api.get_applicant(applicant["id"], headers), 200)
        assert own["id"] == applicant["id"]

        rows, meta = validate_paginated(api.list_screenings(applicant["id"], headers))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == screening["id"]

        # Default variant is attained: 25+25+15+5+10 = 80 for the standard screening.
        readiness = validate_success(api.get_readiness(applicant["id"], headers), 200)
        assert_readiness_report(readiness)
        assert readiness["variant"] == "attained"
        assert readiness["score"] == 80
