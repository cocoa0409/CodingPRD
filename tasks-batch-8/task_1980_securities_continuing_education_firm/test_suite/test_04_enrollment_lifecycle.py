"""Enrollment lifecycle: creation guards, retake budget, expiry, void shape,
cancellation terminal lockdown."""
import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_DEFAULT,
    NON_EXISTENT_UUID,
    complete_enrollment,
    create_approved_content,
    create_enrollment,
    create_instructor_led_setup,
    create_rep,
    get_success_data,
    make_rep_headers,
    set_clock,
    start_enrollment,
    validate_error,
    validate_paginated,
    validate_success,
    void_enrollment,
)


class TestEnrollmentCreationGuards:
    def test_enroll_requires_content_approved(self, api, admin_headers):
        """PRD §3.4: "Creation further requires the rep to be `ACTIVE` (per
        §3.1's registration guard), the content to be `APPROVED`
        (`ERR_CONTENT_NOT_APPROVED`), and — when session-linked — the session
        to be `SCHEDULED` (`ERR_SESSION_NOT_SCHEDULED`) with at least one seat
        still free."

        Design: Difficulty/cross_entity_state_dependency/enroll_requires_content_approved
        """
        rep = create_rep(crd_number="CRD-CE1")
        # Content stays DRAFT (never submitted).
        from test_helpers import create_draft_content
        content = create_draft_content(code="DRAFT-1")
        resp = api.create_enrollment(
            {"rep_id": rep["id"], "content_id": content["id"]}, admin_headers)
        validate_error(resp, ApiErrorId.ERR_CONTENT_NOT_APPROVED)

    def test_enroll_rejected_leaves_no_row(self, api, admin_headers):
        """PRD §3.4: "Creation further requires the rep to be `ACTIVE` (per
        §3.1's registration guard), the content to be `APPROVED`
        (`ERR_CONTENT_NOT_APPROVED`)."
        PRD §3.4: "The enrollment list can be filtered by `rep_id`,
        `content_id`, `session_id`, and `enrollment_status`."

        Design: Difficulty/cross_entity_state_dependency/enroll_requires_content_approved
        """
        rep = create_rep(crd_number="CRD-CE1b")
        from test_helpers import create_draft_content
        content = create_draft_content(code="DRAFT-1b")
        validate_error(
            api.create_enrollment(
                {"rep_id": rep["id"], "content_id": content["id"]}, admin_headers),
            ApiErrorId.ERR_CONTENT_NOT_APPROVED)
        data, _meta = validate_paginated(
            api.list_enrollments(admin_headers, params={"rep_id": rep["id"]}))
        assert data == [], (
            f"rejected creation must leave no enrollment row, got {len(data)}")

    def test_enroll_ilt_without_session_returns_400(self, api, admin_headers):
        """PRD §3.4: "For `ELEARNING` content, the enrollment references the
        content directly through `content_id` and a `session_id` is forbidden;
        for `INSTRUCTOR_LED` content, a `session_id` is required and the
        enrolled content is derived from the session."

        Design: Corner/validations/c_enroll_ilt_without_session_returns_400
        """
        rep = create_rep(crd_number="CRD-C21")
        content = create_approved_content(
            code="ILT-NOSESS", delivery_format="INSTRUCTOR_LED", credit_hours=2.0)
        # INSTRUCTOR_LED content referenced via content_id only: no session_id.
        resp = api.create_enrollment(
            {"rep_id": rep["id"], "content_id": content["id"]}, admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestRetakeBudget:
    def _setup_failed_three_times(self, api):
        rep = create_rep(crd_number="CRD-C17")
        content = create_approved_content(
            code="MAX-3", ce_category="FIRM_ELEMENT", min_passing_score=70)
        enr = create_enrollment(rep["id"], content_id=content["id"])
        rep_h = make_rep_headers(rep["id"])
        for _ in range(3):
            start_enrollment(enr["id"], rep["id"])
            validate_success(api.complete_enrollment(
                enr["id"], {"score": 50}, rep_h))
            if enr is not None:
                pass
            # reattempt between attempts (except after the third failure)
        return rep, content, enr

    def test_reattempt_after_three_failures_rejected(self, api):
        """PRD §3.4: "The retake cycle lets a rep recover: reattempting a
        `FAILED` enrollment returns it to `ENROLLED` and recomputes `expires_at`
        as a fresh ninety-day window from that moment, but only while
        `attempt_count` is still below three — once three attempts have been
        recorded, reattempt is rejected with `ERR_MAX_ATTEMPTS_REACHED`."

        Design: Corner/calculations/c_reattempt_after_max_attempts_returns_409
        """
        rep = create_rep(crd_number="CRD-C17a")
        content = create_approved_content(
            code="MAX-3a", ce_category="FIRM_ELEMENT", min_passing_score=70)
        enr = create_enrollment(rep["id"], content_id=content["id"])
        rep_h = make_rep_headers(rep["id"])
        # Attempts 1 and 2: fail then reattempt.
        for _ in range(2):
            start_enrollment(enr["id"], rep["id"])
            validate_success(api.complete_enrollment(
                enr["id"], {"score": 50}, rep_h))
            validate_success(api.reattempt_enrollment(enr["id"], rep_h))
        # Attempt 3: fail (attempt_count now 3).
        start_enrollment(enr["id"], rep["id"])
        data = validate_success(api.complete_enrollment(
            enr["id"], {"score": 50}, rep_h))
        assert data["attempt_count"] == 3, (
            f"three failed attempts must yield attempt_count 3, "
            f"got {data['attempt_count']}")

        resp = api.reattempt_enrollment(enr["id"], rep_h)
        validate_error(resp, ApiErrorId.ERR_MAX_ATTEMPTS_REACHED)

    def test_reattempt_before_budget_exhausted_succeeds(self, api):
        """PRD §3.4: "reattempting a `FAILED` enrollment returns it to
        `ENROLLED` and recomputes `expires_at` as a fresh ninety-day window
        from that moment, but only while `attempt_count` is still below three."

        Design: Corner/calculations/c_reattempt_after_max_attempts_returns_409
        """
        rep = create_rep(crd_number="CRD-C17b")
        content = create_approved_content(
            code="MAX-3b", ce_category="FIRM_ELEMENT", min_passing_score=70)
        enr = create_enrollment(rep["id"], content_id=content["id"])
        rep_h = make_rep_headers(rep["id"])
        start_enrollment(enr["id"], rep["id"])
        validate_success(api.complete_enrollment(enr["id"], {"score": 50}, rep_h))
        # attempt_count == 1 < 3: reattempt must succeed.
        data = validate_success(api.reattempt_enrollment(enr["id"], rep_h))
        assert data["enrollment_status"] == "ENROLLED", (
            f"reattempt with attempt_count < 3 must return to ENROLLED, "
            f"got {data['enrollment_status']}")


class TestScoreBoundary:
    """Passing threshold is inclusive: score == min_passing_score passes."""

    def test_score_exactly_at_passing_completes(self, api):
        """PRD §3.4: "When the `score` meets or exceeds the content's
        `min_passing_score`, the enrollment moves to `COMPLETED`."

        Design: Corner/calculations/c_score_exactly_at_passing_completes
        """
        rep = create_rep(crd_number="CRD-C16A")
        content = create_approved_content(
            code="SCR-70", ce_category="FIRM_ELEMENT", min_passing_score=70)
        enr = create_enrollment(rep["id"], content_id=content["id"])
        start_enrollment(enr["id"], rep["id"])
        data = validate_success(api.complete_enrollment(
            enr["id"], {"score": 70}, make_rep_headers(rep["id"])))
        assert data["enrollment_status"] == "COMPLETED", (
            f"score 70 == min_passing_score must complete, "
            f"got {data['enrollment_status']}")

    def test_score_one_below_passing_fails(self, api):
        """PRD §3.4: "When the `score` falls short, the enrollment moves to
        `FAILED` instead — `attempt_count` still increments and `last_score` is
        still recorded, but no credit hours accrue anywhere."

        Design: Corner/calculations/c_score_exactly_at_passing_completes
        """
        rep = create_rep(crd_number="CRD-C16B")
        content = create_approved_content(
            code="SCR-69", ce_category="FIRM_ELEMENT", min_passing_score=70)
        enr = create_enrollment(rep["id"], content_id=content["id"])
        start_enrollment(enr["id"], rep["id"])
        data = validate_success(api.complete_enrollment(
            enr["id"], {"score": 69}, make_rep_headers(rep["id"])))
        assert data["enrollment_status"] == "FAILED", (
            f"score 69 < min_passing_score must fail, "
            f"got {data['enrollment_status']}")


class TestExpiryValidation:
    def _setup_expired_in_progress(self, api):
        """Enrollment created+started at the default clock (expires
        2026-10-30); clock advanced to 2026-10-31; NO sweep run."""
        set_clock(CLOCK_DEFAULT)
        rep = create_rep(crd_number="CRD-EXP")
        content = create_approved_content(
            code="FE-EXP", ce_category="FIRM_ELEMENT")
        enr = create_enrollment(rep["id"], content_id=content["id"])
        start_enrollment(enr["id"], rep["id"])
        # 90 days after 2026-08-01T00:00:00Z is 2026-10-30T00:00:00Z.
        set_clock("2026-10-31T00:00:00Z")
        return rep, content, enr

    def test_complete_after_expiry_rejected(self, api):
        """PRD §3.4: "Starting requires the rep to be `ACTIVE`, the logical
        clock to be no later than `expires_at` (a request exactly at
        `expires_at` is still valid; a later one is rejected with
        `ERR_ENROLLMENT_EXPIRED`)."
        PRD §3.4: "Completion requires the enrollment to be `IN_PROGRESS`
        (otherwise `ERR_ENROLLMENT_INVALID_STATE`), with the same ownership,
        registration-standing, expiry, and content-approval guards as
        starting."

        Design: Corner/errors/c_complete_after_expiry_without_sweep_returns_409
        """
        rep, _content, enr = self._setup_expired_in_progress(api)
        resp = api.complete_enrollment(
            enr["id"], {"score": 90}, make_rep_headers(rep["id"]))
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_EXPIRED)

    def test_validation_time_expiry_does_not_mutate_state(self, api, admin_headers):
        """PRD §3.4: "When the enforcement sweep runs, every enrollment in
        `ENROLLED` or `IN_PROGRESS` whose `expires_at` is strictly earlier than
        the logical clock moves to `EXPIRED`."
        PRD §3.9: "Remember that the sweep is the only clock-driven actor in
        the system: setting the logical clock to a future instant changes no
        record until a sweep is run."

        Design: Corner/errors/c_complete_after_expiry_without_sweep_returns_409
        """
        rep, _content, enr = self._setup_expired_in_progress(api)
        validate_error(
            api.complete_enrollment(
                enr["id"], {"score": 90}, make_rep_headers(rep["id"])),
            ApiErrorId.ERR_ENROLLMENT_EXPIRED)
        data = validate_success(api.get_enrollment(enr["id"], admin_headers))
        assert data["enrollment_status"] == "IN_PROGRESS", (
            f"no sweep ran, so validation-time expiry must not mutate state; "
            f"got {data['enrollment_status']}")


class TestCancelTerminalLockdown:
    def test_complete_cancelled_enrollment_rejected(self, api, admin_headers):
        """PRD §3.4: "Completing an enrollment is the same rep's act of
        recording a `score`, an integer from 0 to 100. Completion requires the
        enrollment to be `IN_PROGRESS` (otherwise
        `ERR_ENROLLMENT_INVALID_STATE`)."
        PRD §3.4: "`CANCELLED`, `EXPIRED`, and `VOIDED` are terminal
        enrollment states."

        Design: Corner/state_machines/c_complete_cancelled_enrollment_returns_409
        """
        rep = create_rep(crd_number="CRD-C09")
        content = create_approved_content(code="CX-1", ce_category="FIRM_ELEMENT")
        enr = create_enrollment(rep["id"], content_id=content["id"])
        get_success_data(api.cancel_enrollment(enr["id"], admin_headers))

        resp = api.complete_enrollment(
            enr["id"], {"score": 90}, make_rep_headers(rep["id"]))
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_INVALID_STATE)

        data = validate_success(api.get_enrollment(enr["id"], admin_headers))
        assert data["attempt_count"] == 0, (
            f"the rejected completion must record no attempt, "
            f"got attempt_count {data['attempt_count']}")


class TestVoidShape:
    def test_void_missing_justification_returns_400(self, api):
        """PRD §3.4: "The request must carry a `justification` of at least ten
        characters (`ERR_INVALID_REQUEST`)."

        Design: Corner/validations/c_void_missing_required_justification_returns_400
        """
        rep = create_rep(crd_number="CRD-C26")
        content = create_approved_content(code="VOID-REQ", ce_category="FIRM_ELEMENT")
        enr = create_enrollment(rep["id"], content_id=content["id"])
        start_enrollment(enr["id"], rep["id"])
        complete_enrollment(enr["id"], rep["id"], score=90)

        from test_helpers import TEST_USERS
        resp = api.void_enrollment(enr["id"], {}, TEST_USERS["officer_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestOwnership:
    def test_rep_cannot_complete_others_enrollment(self, api):
        """PRD §2.1: "When `X-User-Role` is `RegisteredRep`, `X-User-ID` is the
        `id` of the acting Representative record; ownership checks on any
        resource that references a representative compare the resource's rep
        field — or, for an attestation, the parent plan's rep field — to
        `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_REQUIRED`
        (HTTP 403)."

        Design: Corner/validations/c_rep_cannot_complete_others_enrollment
        """
        rep_a = create_rep(crd_number="CRD-C29A")
        rep_b = create_rep(crd_number="CRD-C29B")
        content = create_approved_content(code="OWN-1", ce_category="FIRM_ELEMENT")
        enr = create_enrollment(rep_a["id"], content_id=content["id"])
        start_enrollment(enr["id"], rep_a["id"])

        resp = api.complete_enrollment(
            enr["id"], {"score": 90}, make_rep_headers(rep_b["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_REQUIRED)

        from test_helpers import TEST_USERS
        data = validate_success(
            api.get_enrollment(enr["id"], TEST_USERS["admin_headers"]))
        assert data["enrollment_status"] == "IN_PROGRESS", (
            f"rejected completion must leave the enrollment IN_PROGRESS, "
            f"got {data['enrollment_status']}")
