"""The confidentiality wall and role/ownership authorization."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    api_client,
    book_session,
    complete_session,
    create_clinical_note_payload,
    create_counselor,
    create_student,
    make_clinical_director_headers,
    make_counselor_headers,
    setup_open_episode,
    validate_error,
    validate_success,
)

FD = TEST_USERS["front_desk_headers"]
REG = TEST_USERS["registrar_headers"]


def _setup_completed_session_with_note(student_number, note_body,
                                       license_id="LIC-B1"):
    counselor, student, episode = setup_open_episode(
        student_number=student_number, license_id=license_id,
        no_show_strike_limit=5)
    session = book_session(episode["id"], counselor["id"],
                           "2026-08-02T09:00:00Z")
    advance_clock("2026-08-03T00:00:00Z")
    complete_session(session["id"], counselor["id"])
    note = validate_success(api_client.create_clinical_note(
        create_clinical_note_payload(session["id"], counselor["id"],
                                     body=note_body),
        make_counselor_headers(counselor["id"])), expected_status=201)
    return counselor, student, session, note


class TestAuthentication:

    def test_missing_auth_headers_rejected(self):
        """PRD section 2.1: "A request with missing headers, or whose role is
        not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/rbac/missing_auth_headers_rejected
        """
        resp = api_client.list_students(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRegistrarWall:

    def test_registrar_blocked_from_note_and_clinical_view(self):
        """PRD section 2.1: "A request whose role is recognized but not
        permitted to invoke the target endpoint is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD section 2.6: "When a `Registrar` reads a student, the response
        contains only the academic view: counseling-derived fields such as
        risk bands, episode status, session counts, and strike counts must not
        appear."

        The note endpoint admits Counselor and ClinicalDirector only (PRD
        section 4), so a Registrar's read is stopped at the endpoint
        authorization stage; the student read succeeds but shows only the
        academic view.

        Design: Corner/rbac/registrar_blocked_from_clinical_note_and_clinical_view
        """
        counselor, student, session, note = \
            _setup_completed_session_with_note("B100", "Confidential narrative.")
        resp = api_client.get_clinical_note(note["id"], REG)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        view = validate_success(api_client.get_student(student["id"], REG))
        assert "booking_posture" not in view, \
            "the academic view must not expose counseling-derived posture"
        assert "no_show_strike_count" not in view, \
            "the academic view must not expose counseling-derived strike counts"
        assert "academic_record_flags" in view, \
            "the academic view retains the registrar-visible flags"


class TestNoteReadModel:

    def test_non_author_counselor_blocked_but_director_allowed(self):
        """PRD section 2.6: "A ClinicalNote's `body` is clinical narrative: it
        belongs to the counseling record, never the academic record, and it is
        readable only by its author or by a `ClinicalDirector`. Any other read
        attempt — including by another counselor — is rejected with
        `ERR_CONFIDENTIALITY_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/non_author_counselor_blocked_from_note_but_director_allowed
        """
        counselor, student, session, note = \
            _setup_completed_session_with_note("B200", "Author-only content.",
                                               license_id="LIC-B2A")
        other = create_counselor(license_id="LIC-B2B")
        resp = api_client.get_clinical_note(
            note["id"], make_counselor_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_CONFIDENTIALITY_VIOLATION)
        director_read = validate_success(api_client.get_clinical_note(
            note["id"], make_clinical_director_headers(other["id"])))
        assert director_read["body"] == "Author-only content."


class TestFrontDeskDenials:

    def test_front_desk_cannot_complete_session_or_reset_strikes(self):
        """PRD section 2.1: "A request whose role is recognized but not
        permitted to invoke the target endpoint is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD section 4: session completion is listed for "Counselor,
        ClinicalDirector" and the strike-reset action for "ClinicalDirector".

        Design: Corner/rbac/front_desk_cannot_complete_session_or_reset_strikes
        """
        counselor, student, episode = setup_open_episode(
            student_number="B300", license_id="LIC-B3",
            no_show_strike_limit=5)
        session = book_session(episode["id"], counselor["id"],
                               "2026-08-02T09:00:00Z")
        advance_clock("2026-08-03T00:00:00Z")
        resp_complete = api_client.complete_session(session["id"], FD)
        validate_error(resp_complete, ApiErrorId.ERR_UNAUTHORIZED)
        resp_reset = api_client.reset_student_strikes(student["id"], FD)
        validate_error(resp_reset, ApiErrorId.ERR_UNAUTHORIZED)


class TestCounselorOwnership:

    def test_counselor_cannot_complete_another_counselors_session(self):
        """PRD section 2.1: "A `Counselor` may complete or record no-show
        determinations only on sessions whose `counselor_id` equals their own
        id" and "Ownership violations are authorization failures — they are
        rejected with `ERR_UNAUTHORIZED` (HTTP 403), never with a
        state-transition error."

        Design: Corner/rbac/counselor_cannot_complete_another_counselors_session
        """
        counselor, student, episode = setup_open_episode(
            student_number="B400", license_id="LIC-B4A",
            no_show_strike_limit=5)
        other = create_counselor(license_id="LIC-B4B")
        session = book_session(episode["id"], counselor["id"],
                               "2026-08-02T09:00:00Z")
        advance_clock("2026-08-03T00:00:00Z")
        resp = api_client.complete_session(
            session["id"], make_counselor_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        current = validate_success(api_client.get_session(
            session["id"], make_counselor_headers(counselor["id"])))
        assert current["status"] == "SCHEDULED", \
            "a rejected completion leaves the session untouched"
