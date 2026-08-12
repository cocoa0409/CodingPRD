"""Course-request lifecycle: draft, submit, unsubmit, withdraw, eligibility, caps."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_student_headers,
    setup_counselor, setup_term, setup_course, setup_student,
    make_course_request, make_and_submit_request,
    assert_course_request,
)

ADMIN = TEST_USERS["admin_headers"]


def _basic_setup(code, ref="REQ1"):
    counselor = setup_counselor(max_caseload=50, full_name=f"C {code}")
    term = setup_term(code)
    course = setup_course(f"{code}-1", credits=1.0, subject_area="ELECTIVE")
    student = setup_student(counselor["id"], ref, grade_level=9)
    return counselor, term, course, student


class TestCourseRequestLifecycle:
    def test_request_starts_in_draft_initial_state(self, api):
        """PRD §3.2: "Submitting moves a request from `DRAFT` to `SUBMITTED`"
        (the request is born in `DRAFT`).
        PRD §3.2: "Every request carries a computed `tally_weight`: 1.0 for a
        primary request in `SUBMITTED` or `LOCKED`, 0.5 for an alternate in one
        of those states, and 0 in every other case."

        Design: Corner/state_machines/request_starts_in_draft_initial_state
        """
        _, term, course, student = _basic_setup("2043-FALL", "INI1")
        resp = api.create_course_request({
            "student_id": student["id"], "course_id": course["id"],
            "term_id": term["id"], "priority_rank": 1,
        }, make_student_headers(student["id"]))
        data = validate_success(resp, 201)
        assert_course_request(data)
        assert data["state"] == "DRAFT"
        assert data["tally_weight"] == 0

    def test_unsubmit_from_draft_rejected(self, api):
        """PRD §3.2: "unsubmitting — allowed only while `COLLECTING` lasts,
        moving the request `SUBMITTED` → `DRAFT` — recomputes the weight to zero
        and refreshes the tally again."
        PRD §2.8: "then from-state legality on the target entity
        (`ERR_INVALID_STATE`, HTTP 409)"

        Design: Corner/state_machines/unsubmit_from_draft_rejected
        """
        _, term, course, student = _basic_setup("2044-FALL", "INV1")
        req = make_course_request(student["id"], course["id"], term["id"], 1)
        assert req["state"] == "DRAFT"
        resp = api.unsubmit_course_request(req["id"], make_student_headers(student["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_idempotent_second_submit_rejected(self, api):
        """PRD §3.2: "Submitting moves a request from `DRAFT` to `SUBMITTED`" —
        a request already in `SUBMITTED` is no longer in the legal from-state.
        PRD §2.8: "then from-state legality on the target entity
        (`ERR_INVALID_STATE`, HTTP 409)"

        Design: Corner/state_machines/idempotent_second_submit_rejected
        """
        _, term, course, student = _basic_setup("2048-FALL", "IDM1")
        req = make_course_request(student["id"], course["id"], term["id"], 1)
        first = api.submit_course_request(req["id"], make_student_headers(student["id"]))
        assert validate_success(first, 200)["state"] == "SUBMITTED"
        resp = api.submit_course_request(req["id"], make_student_headers(student["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_delete_draft_request_returns_204(self, api):
        """PRD §3.2: "A request still in `DRAFT` may be withdrawn entirely:
        withdrawal removes the draft row outright as a hard delete (a request
        already `SUBMITTED` must first be unsubmitted)"
        PRD §4: "The single deletion endpoint returns `204 No Content` with no
        body."

        Design: Corner/endpoints/delete_draft_request_returns_204
        """
        counselor, term, _, student = _basic_setup("2061-FALL", "DEL1")
        c1 = setup_course("DEL-1", credits=1.0, subject_area="ELECTIVE")
        c2 = setup_course("DEL-2", credits=1.0, subject_area="ELECTIVE")
        rq_del = make_course_request(student["id"], c1["id"], term["id"], 1)
        rq_sub = make_and_submit_request(student["id"], c2["id"], term["id"], 2)

        resp_ok = api.delete_course_request(rq_del["id"], make_student_headers(student["id"]))
        assert resp_ok.status_code == 204, f"DELETE of DRAFT must return 204, got {resp_ok.status_code}"

        resp_bad = api.delete_course_request(rq_sub["id"], make_student_headers(student["id"]))
        validate_error(resp_bad, ApiErrorId.ERR_INVALID_STATE, 409)


class TestEligibilityAndCaps:
    def test_grade_band_violation(self, api):
        """PRD §3.2: "the student's `grade_level` must fall within the course's
        grade band inclusive of both ends"
        PRD §3.2: "Eligibility is checked when the request is created and again
        when it is submitted, with any failure surfacing as
        `ERR_COURSE_INELIGIBLE` (HTTP 422)"

        Design: Corner/validations/grade_band_violation
        """
        counselor = setup_counselor(max_caseload=50, full_name="C Gb")
        term = setup_term("2053-FALL")
        course = setup_course("SR-SEM", credits=1.0, subject_area="ELECTIVE",
                              title="Senior Seminar", grade_band_min=11, grade_band_max=12)
        student = setup_student(counselor["id"], "GB01", grade_level=9)
        resp = api.create_course_request({
            "student_id": student["id"], "course_id": course["id"],
            "term_id": term["id"], "priority_rank": 1,
        }, make_student_headers(student["id"]))
        validate_error(resp, ApiErrorId.ERR_COURSE_INELIGIBLE, 422)

    def test_request_cap_eight_primaries(self, api):
        """PRD §3.2: "the student must hold fewer than 8 non-alternate requests
        in `DRAFT` or `SUBMITTED` for the term, and the total credit load of
        their primary (non-alternate) requests may not exceed 8.0. Breaching
        either cap rejects the submission with `ERR_REQUEST_CAP_EXCEEDED`
        (HTTP 422)."

        Design: Corner/validations/request_cap_eight_primaries
        """
        counselor = setup_counselor(max_caseload=50, full_name="C Cap")
        term = setup_term("2054-FALL")
        student = setup_student(counselor["id"], "CAP1", grade_level=9)
        for i in range(1, 9):
            course = setup_course(f"CAP-{i}", credits=0.25, subject_area="ELECTIVE")
            make_and_submit_request(student["id"], course["id"], term["id"], priority_rank=i)
        k9 = setup_course("CAP-9", credits=0.25, subject_area="ELECTIVE")
        rq9 = make_course_request(student["id"], k9["id"], term["id"], priority_rank=9)
        resp = api.submit_course_request(rq9["id"], make_student_headers(student["id"]))
        validate_error(resp, ApiErrorId.ERR_REQUEST_CAP_EXCEEDED, 422)
