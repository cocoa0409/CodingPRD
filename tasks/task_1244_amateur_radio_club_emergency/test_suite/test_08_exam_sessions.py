"""License exam session administration (PRD §3.7): capacity, FRN uniqueness,
check-in gating, pass/fail threshold, segregation of duties, and the member
license upgrade on a pass."""
from test_helpers import (
    ApiErrorId,
    assert_exam_candidate,
    assert_instant_equals,
    check_in_candidate,
    create_exam_candidate_payload,
    create_exam_session,
    create_member,
    exam_session_set_status,
    get_success_data,
    make_liaison_headers,
    register_candidate,
    validate_error,
)


def _liaison(callsign="W1LIA"):
    """A member row to back the ExamLiaison role identity."""
    return create_member(callsign)


class TestExamSessionClose:
    def test_close_with_registered_candidate_rejected(self, api, admin_headers):
        """PRD §3.7: "Closing a session (`IN_PROGRESS` → `CLOSED`) is blocked
        while any candidate remains non-terminal — every candidate must be in
        `PASSED`, `FAILED`, `NO_SHOW`, or `CANCELLED`, and a violation is
        rejected with `ERR_CANDIDATES_PENDING`."

        Design: Corner/state_machines/exam_close_with_pending_candidates_rejected
        """
        lia = _liaison()
        session = create_exam_session(lia["id"])
        register_candidate(session["id"], lia["id"])
        exam_session_set_status(session["id"], "IN_PROGRESS", lia["id"])
        resp = api.exam_session_set_status(
            session["id"], {"to": "CLOSED"}, make_liaison_headers(lia["id"]))
        validate_error(resp, ApiErrorId.ERR_CANDIDATES_PENDING)
        after = get_success_data(api.get_exam_session(session["id"], admin_headers))
        assert after["status"] == "IN_PROGRESS"


class TestExamRegistration:
    def test_duplicate_frn_within_session_rejected(self, api, admin_headers):
        """PRD §3.7: "Registration is accepted only while the session is
        `SCHEDULED`, is refused at capacity — when `registered_count` has
        reached `max_candidates`, the rejection is `ERR_SESSION_FULL` — and
        enforces one FRN per session, with a duplicate rejected as
        `ERR_DUPLICATE_CANDIDATE_FRN`."

        Design: Corner/validations/duplicate_frn_within_session_rejected
        """
        lia = _liaison()
        session = create_exam_session(lia["id"])
        register_candidate(session["id"], lia["id"], frn="0001112223")
        resp = api.create_exam_candidate(
            create_exam_candidate_payload(
                session["id"], candidate_name="Cand Two", frn="0001112223",
                element="GENERAL"),
            make_liaison_headers(lia["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CANDIDATE_FRN)

    def test_session_full_boundary(self, api, admin_headers):
        """PRD §3.7: "is refused at capacity — when `registered_count` has
        reached `max_candidates`, the rejection is `ERR_SESSION_FULL`" and
        "`registered_count` itself counts candidates in `REGISTERED` or
        `CHECKED_IN` and is recomputed as registrations and terminal
        transitions occur."

        Design: Corner/validations/session_full_boundary
        """
        lia = _liaison()
        session = create_exam_session(lia["id"], max_candidates=1)
        register_candidate(session["id"], lia["id"], frn="0001112223")
        resp = api.create_exam_candidate(
            create_exam_candidate_payload(
                session["id"], candidate_name="Cand Two", frn="0001112224",
                element="GENERAL"),
            make_liaison_headers(lia["id"]))
        validate_error(resp, ApiErrorId.ERR_SESSION_FULL)
        after = get_success_data(api.get_exam_session(session["id"], admin_headers))
        assert after["registered_count"] == 1


class TestResultRecording:
    def _checked_in_candidate(self, api, admin_headers):
        """Session IN_PROGRESS with one candidate CHECKED_IN by the first
        liaison; a second liaison exists for SoD-compliant recording."""
        lia1 = _liaison("W1LIA")
        lia2 = _liaison("W2LIA")
        session = create_exam_session(lia1["id"])
        candidate = register_candidate(session["id"], lia1["id"], element="GENERAL")
        exam_session_set_status(session["id"], "IN_PROGRESS", lia1["id"])
        check_in_candidate(candidate["id"], lia1["id"])
        return lia1, lia2, session, candidate

    def test_result_requires_checked_in_candidate(self, api, admin_headers):
        """PRD §3.7: "Recording requires the session still `IN_PROGRESS` and
        the candidate in `CHECKED_IN` — recording against a candidate in any
        other state is rejected with `ERR_CANDIDATE_NOT_CHECKED_IN`."

        Design: Corner/state_machines/exam_result_requires_checkedin
        """
        lia = _liaison()
        session = create_exam_session(lia["id"])
        candidate = register_candidate(session["id"], lia["id"])
        exam_session_set_status(session["id"], "IN_PROGRESS", lia["id"])
        resp = api.exam_candidate_record_result(
            candidate["id"], {"score_percent": 90}, make_liaison_headers(lia["id"]))
        validate_error(resp, ApiErrorId.ERR_CANDIDATE_NOT_CHECKED_IN)
        after = get_success_data(api.get_exam_candidate(candidate["id"], admin_headers))
        assert after["status"] == "REGISTERED"

    def test_score_74_passes_and_73_fails(self, api, admin_headers):
        """PRD §3.7: "The supplied `score_percent`, an integer from zero to one
        hundred, decides the outcome: 74 or higher records `PASSED`, anything
        below records `FAILED`."

        Design: Corner/state_machines/exam_pass_threshold_74_boundary
        """
        lia1 = _liaison("W1LIA")
        lia2 = _liaison("W2LIA")
        session = create_exam_session(lia1["id"])
        cand_a = register_candidate(session["id"], lia1["id"], candidate_name="Cand A",
                                    frn="0001112223", element="GENERAL")
        cand_b = register_candidate(session["id"], lia1["id"], candidate_name="Cand B",
                                    frn="0001112224", element="GENERAL")
        exam_session_set_status(session["id"], "IN_PROGRESS", lia1["id"])
        check_in_candidate(cand_a["id"], lia1["id"])
        check_in_candidate(cand_b["id"], lia1["id"])
        passed = get_success_data(api.exam_candidate_record_result(
            cand_a["id"], {"score_percent": 74}, make_liaison_headers(lia2["id"])))
        failed = get_success_data(api.exam_candidate_record_result(
            cand_b["id"], {"score_percent": 73}, make_liaison_headers(lia2["id"])))
        assert passed["status"] == "PASSED"
        assert failed["status"] == "FAILED"

    def test_recorder_must_differ_from_checkin_member(self, api, admin_headers):
        """PRD §3.7: "Result recording is the second segregation-of-duties
        point: the member recording a result must differ from the member
        recorded as `checked_in_by_member_id`, with a violation rejected as
        `ERR_SOD_EXAM_GRADING`."

        Design: Corner/errors/exam_grading_segregation_of_duties
        """
        lia1, _, _, candidate = self._checked_in_candidate(api, admin_headers)
        resp = api.exam_candidate_record_result(
            candidate["id"], {"score_percent": 90}, make_liaison_headers(lia1["id"]))
        validate_error(resp, ApiErrorId.ERR_SOD_EXAM_GRADING)
        after = get_success_data(api.get_exam_candidate(candidate["id"], admin_headers))
        assert after["status"] == "CHECKED_IN"


class TestLicenseUpgradeOnPass:
    def test_pass_upgrades_linked_member_license(self, api, admin_headers):
        """PRD §3.7: "If the passed `element` is ordinally strictly higher than
        the member's current `license_class`, the member's `license_class` is
        upgraded to that element; either way on a pass the member's
        `license_expires_at` is set to the current clock plus 3650 days, and
        the member's `version` is bumped."

        Design: Corner/calculations/exam_pass_upgrades_member_license
        """
        member = create_member("K1OPR", license_class="TECHNICIAN",
                               license_expires_at="2027-01-01T00:00:00Z")
        lia1 = _liaison("W1LIA")
        lia2 = _liaison("W2LIA")
        session = create_exam_session(lia1["id"])
        candidate = register_candidate(session["id"], lia1["id"],
                                       candidate_name="Op Cand", frn="0001112223",
                                       element="GENERAL", member_id=member["id"])
        exam_session_set_status(session["id"], "IN_PROGRESS", lia1["id"])
        check_in_candidate(candidate["id"], lia1["id"])
        result = get_success_data(api.exam_candidate_record_result(
            candidate["id"], {"score_percent": 80}, make_liaison_headers(lia2["id"])))
        assert_exam_candidate(result)
        assert result["status"] == "PASSED"
        detail = get_success_data(api.get_member(member["id"], admin_headers))
        assert detail["license_class"] == "GENERAL"
        # Default logical clock 2026-05-01T00:00:00Z plus 3650 days.
        assert_instant_equals(detail["license_expires_at"], "2036-04-28T00:00:00Z",
                              "license_expires_at")
