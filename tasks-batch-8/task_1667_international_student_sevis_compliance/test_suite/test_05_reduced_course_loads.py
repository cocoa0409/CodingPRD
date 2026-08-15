"""Reduced-course-load eligibility, floors, and decision claims (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    assert_reduced_course_load,
    assert_term_enrollment,
    create_rcl,
    create_term_enrollment,
    decide_rcl,
    get_enrollment,
    register_enrollment,
    set_clock,
    setup_active_student,
    setup_initialized_student,
    validate_error,
    validate_success,
)

class TestRclAcademicFloorMultiInput:
    """ACADEMIC floor = max(3, floor(base_min / 2)) = 6 for an undergraduate."""

    def _setup(self):
        # INITIAL record; FALL enrollment PENDING, 12 credits.
        return setup_active_student(register=False)

    def test_academic_rcl_below_floor_rejected(self, api, dso_headers):
        """PRD §3.4: "The requested credits must be at least the academic floor,
        which is half the base minimum rounded down, but never below 3 credits
        in absolute terms — so 6 for an undergraduate and 4 for a graduate. A
        request below that floor is rejected with
        `ERR_RCL_CREDITS_OUT_OF_RANGE` (HTTP 422)."

        Design: Difficulty/combinatorial_formula/rcl_academic_floor_multi_input
        """
        ctx = self._setup()
        enrollment_id = ctx["enrollment"]["id"]
        resp = api.create_reduced_course_load(
            {"enrollment_id": enrollment_id, "reason_category": "ACADEMIC",
             "requested_credits": 5},
            dso_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RCL_CREDITS_OUT_OF_RANGE, 422)

        # At the floor (6) the request is accepted.
        rcl = create_rcl(enrollment_id, "ACADEMIC", 6)
        assert_reduced_course_load(rcl)
        assert rcl["status"] == "REQUESTED"

    def test_academic_rcl_approval_recomputes_floor_and_registers_at_floor(
        self, api, dso_headers,
    ):
        """PRD §3.4: "Approval recomputes the parent enrollment's
        `effective_min_credits` by category: for `ACADEMIC`, the larger of 3
        credits and half the base minimum rounded down; for `MEDICAL`, exactly
        the approved `requested_credits`, which may be zero; for `FINAL_TERM`,
        the larger of 1 credit and the requested amount."
        PRD §3.3: "meeting the floor exactly counts as full-time (otherwise
        `ERR_BELOW_FULL_COURSE_LOAD`, HTTP 422)".

        Design: Difficulty/combinatorial_formula/rcl_academic_floor_multi_input
        """
        ctx = self._setup()
        enrollment_id = ctx["enrollment"]["id"]
        rcl = create_rcl(enrollment_id, "ACADEMIC", 6)
        decided = decide_rcl(rcl["id"], "APPROVED")
        assert decided["status"] == "APPROVED"

        enrollment = get_enrollment(enrollment_id)
        assert enrollment["effective_min_credits"] == 6, (
            f"expected floor 6 = max(3, floor(12/2)), got "
            f"{enrollment['effective_min_credits']}"
        )

        patched = validate_success(
            api.patch_term_enrollment(enrollment_id, {"enrolled_credits": 6},
                                      dso_headers),
            200,
        )
        assert patched["enrolled_credits"] == 6
        registered = register_enrollment(enrollment_id)
        assert registered["status"] == "REGISTERED"


def test_medical_rcl_zero_credits_passes_registration(api, dso_headers):
    """PRD §3.4: "Approval recomputes the parent enrollment's
    `effective_min_credits` by category: for `ACADEMIC`, the larger of 3
    credits and half the base minimum rounded down; for `MEDICAL`, exactly the
    approved `requested_credits`, which may be zero; for `FINAL_TERM`, the
    larger of 1 credit and the requested amount."
    PRD §3.4: "a `reason_category` of `ACADEMIC`, `MEDICAL`, or `FINAL_TERM`,
    and the planned `requested_credits` (zero or greater)".

    Design: Corner/calculations/medical_rcl_zero_credits_passes_registration
    """
    ctx = setup_active_student(register=False)  # INITIAL record; PENDING enrollment
    enrollment_id = ctx["enrollment"]["id"]
    rcl = create_rcl(enrollment_id, "MEDICAL", 0)
    decided = decide_rcl(rcl["id"], "APPROVED")
    assert decided["status"] == "APPROVED"

    enrollment = get_enrollment(enrollment_id)
    assert enrollment["effective_min_credits"] == 0

    patched = validate_success(
        api.patch_term_enrollment(enrollment_id, {"enrolled_credits": 0}, dso_headers),
        200,
    )
    assert patched["enrolled_credits"] == 0
    registered = register_enrollment(enrollment_id)
    assert registered["status"] == "REGISTERED"


def test_final_term_rcl_requires_program_end_in_term(api, dso_headers):
    """PRD §3.4: "`FINAL_TERM` — the enrollment's term window, from
    `term_start_date` through `term_end_date`, must contain the record's
    `program_end_date`; otherwise the request is rejected with
    `ERR_RCL_NOT_FINAL_TERM`."

    Design: Corner/calculations/final_term_rcl_requires_program_end_in_term
    """
    ctx = setup_active_student(register=False)  # INITIAL record; PENDING enrollment
    # Term 2026-08-24..2026-12-11 does not contain program_end 2027-05-31.
    resp = api.create_reduced_course_load(
        {"enrollment_id": ctx["enrollment"]["id"], "reason_category": "FINAL_TERM",
         "requested_credits": 3},
        dso_headers,
    )
    validate_error(resp, ApiErrorId.ERR_RCL_NOT_FINAL_TERM, 409)


def test_academic_rcl_second_use_returns_reason_exhausted(api, dso_headers):
    """PRD §3.4: "`ACADEMIC` — available at most once per student across the
    entire program level; if any earlier `ACADEMIC` RCL for the student exists
    in `REQUESTED` or `APPROVED` status, the new request is rejected with
    `ERR_RCL_REASON_EXHAUSTED`."

    Design: Corner/calculations/academic_rcl_second_use_returns_reason_exhausted
    """
    ctx = setup_active_student(register=False)  # INITIAL record; PENDING enrollment
    student_id = ctx["student"]["id"]
    fall = ctx["enrollment"]
    rcl = create_rcl(fall["id"], "ACADEMIC", 6)
    decide_rcl(rcl["id"], "APPROVED")

    spring = create_term_enrollment(
        student_id, term_code="2027-SPRING",
        term_start_date="2027-01-11", term_end_date="2027-05-07",
        enrolled_credits=12,
    )
    resp = api.create_reduced_course_load(
        {"enrollment_id": spring["id"], "reason_category": "ACADEMIC",
         "requested_credits": 6},
        dso_headers,
    )
    validate_error(resp, ApiErrorId.ERR_RCL_REASON_EXHAUSTED, 409)


def test_rcl_decision_on_decided_returns_not_requested(api, dso_headers):
    """PRD §3.4: "A decision against a request no longer in `REQUESTED` status
    is rejected with `ERR_RCL_NOT_REQUESTED`."

    Design: Corner/state_machines/rcl_decision_on_decided_returns_not_requested
    """
    ctx = setup_active_student(register=False)  # INITIAL record; PENDING enrollment
    rcl = create_rcl(ctx["enrollment"]["id"], "ACADEMIC", 6)
    decide_rcl(rcl["id"], "APPROVED")
    resp = api.decide_reduced_course_load(rcl["id"], {"decision": "DENIED"}, dso_headers)
    validate_error(resp, ApiErrorId.ERR_RCL_NOT_REQUESTED, 409)


def test_rcl_create_after_add_drop_returns_add_drop_closed(api, dso_headers):
    """PRD §3.4: "The request itself must be filed by the add/drop close, 14
    days after the enrollment's `term_start_date`; later filings are rejected
    with `ERR_RCL_ADD_DROP_CLOSED`."

    Design: Corner/validations/rcl_create_after_add_drop_returns_add_drop_closed
    """
    ctx = setup_initialized_student()
    # Past add/drop close (term_start 2026-08-24 + 14 days = 2026-09-07), then
    # create the enrollment late so it remains PENDING (state check passes).
    set_clock("2026-09-24T00:00:00Z")
    enrollment = create_term_enrollment(ctx["student"]["id"])
    assert enrollment["status"] == "PENDING"
    resp = api.create_reduced_course_load(
        {"enrollment_id": enrollment["id"], "reason_category": "ACADEMIC",
         "requested_credits": 6},
        dso_headers,
    )
    validate_error(resp, ApiErrorId.ERR_RCL_ADD_DROP_CLOSED, 409)


class TestRclCreateStateErrorBeatsTemporal:
    """Priority pair: state precondition (band 5) beats deadline rule (band 8)
    on RCL creation."""

    def test_rcl_on_swept_enrollment_reports_state_error(self, api, dso_headers):
        """PRD §2.9: "When a single request would violate several rules, the
        system reports the first applicable failure in a fixed priority order
        rather than an arbitrary one:"
        PRD §2.9: "This priority band also applies to reduced-course-load
        creation, where the parent enrollment must be `PENDING` or `REGISTERED`
        (`ERR_ENROLLMENT_NOT_REGISTERABLE`)."
        PRD §2.9: "8. **Deadline and window rules.** Registration deadline
        (`ERR_REGISTRATION_DEADLINE_PASSED`), RCL add/drop close
        (`ERR_RCL_ADD_DROP_CLOSED`), enrollment-credit edits after add/drop
        (`ERR_ADD_DROP_CLOSED`), OPT filing and OPT_POST start windows
        (`ERR_OPT_WINDOW_CLOSED`), CPT/OPT_PRE end-date containment
        (`ERR_AUTH_WINDOW_INVALID`), extension-approval cutoff
        (`ERR_EXTENSION_WINDOW_CLOSED`), extension forward-progress
        (`ERR_EXTENSION_NOT_FORWARD`), and the FINAL_TERM containment check
        (`ERR_RCL_NOT_FINAL_TERM`)."

        Design: Difficulty/priority_pair_validation_conflict/rcl_create_state_error_beats_temporal
        """
        ctx = setup_active_student(register=False)  # INITIAL record, PENDING enrollment
        enrollment_id = ctx["enrollment"]["id"]
        # Sweep flips the enrollment to NOT_ENROLLED; add/drop also closed.
        set_clock("2026-09-24T00:00:00Z")
        assert get_enrollment(enrollment_id)["status"] == "NOT_ENROLLED"

        resp = api.create_reduced_course_load(
            {"enrollment_id": enrollment_id, "reason_category": "ACADEMIC",
             "requested_credits": 6},
            dso_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_REGISTERABLE, 409)

    def test_rcl_on_completed_enrollment_reports_state_error(self, api, dso_headers):
        """PRD §2.9: "When a single request would violate several rules, the
        system reports the first applicable failure in a fixed priority order
        rather than an arbitrary one:"
        PRD §2.9: "This priority band also applies to reduced-course-load
        creation, where the parent enrollment must be `PENDING` or `REGISTERED`
        (`ERR_ENROLLMENT_NOT_REGISTERABLE`)."
        PRD §3.3: "Separately, an enrollment in `REGISTERED` whose
        `term_end_date` has passed flips to `COMPLETED`."

        Design: Difficulty/priority_pair_validation_conflict/rcl_create_state_error_beats_temporal
        """
        ctx = setup_active_student()  # FALL enrollment REGISTERED
        enrollment_id = ctx["enrollment"]["id"]
        # Past term_end 2026-12-11: enrollment COMPLETED; add/drop long closed.
        set_clock("2026-12-15T00:00:00Z")
        assert get_enrollment(enrollment_id)["status"] == "COMPLETED"

        resp = api.create_reduced_course_load(
            {"enrollment_id": enrollment_id, "reason_category": "ACADEMIC",
             "requested_credits": 6},
            dso_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_REGISTERABLE, 409)
