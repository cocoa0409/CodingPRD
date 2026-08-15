"""Content lifecycle: rework cycle, OCC on edits, and creation-time fields."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_content,
    create_content_payload,
    create_reject_payload,
    get_success_data,
    make_admin_headers,
    make_officer_headers,
    validate_error,
    validate_success,
)


class TestContentReworkCycle:
    """DRAFT -> PENDING_APPROVAL -> REJECTED -> DRAFT -> PENDING_APPROVAL -> APPROVED."""

    def test_rework_loop_reaches_approved(self, api, admin_headers, officer_headers):
        """PRD §3.2: "editing content that sits in `REJECTED` returns it to
        `DRAFT` and clears both `rejection_reason` and `approved_by_user_id`,
        resetting the rework loop."
        PRD §3.2: "A successful approval stamps `approved_by_user_id` with the
        approver's identity and writes a `CONTENT_APPROVED` audit event."

        Design: Difficulty/non_linear_state_machine/content_rework_cycle
        """
        author = make_admin_headers("ta-1")
        content = get_success_data(
            api.create_content(create_content_payload(code="RW-1"), author))
        assert content["content_status"] == "DRAFT"
        assert content["version"] == 1

        # -> PENDING_APPROVAL (v2)
        content = get_success_data(api.submit_content(content["id"], author))
        assert content["content_status"] == "PENDING_APPROVAL"

        # -> REJECTED (v3)
        content = get_success_data(
            api.reject_content(content["id"], create_reject_payload(), officer_headers))
        assert content["content_status"] == "REJECTED"
        assert content["rejection_reason"] == "insufficient learning objectives"

        # rework edit: REJECTED -> DRAFT (v4), clears rejection_reason
        content = get_success_data(
            api.update_content(
                content["id"],
                {"expected_content_version": content["version"],
                 "title": "Rework One Revised"},
                author))
        assert content["content_status"] == "DRAFT", (
            f"rework edit must return content to DRAFT, got {content['content_status']}")
        assert content.get("rejection_reason") in (None, "")

        # second submit -> PENDING_APPROVAL (v5)
        content = get_success_data(api.submit_content(content["id"], author))
        assert content["content_status"] == "PENDING_APPROVAL"

        # approve -> APPROVED (v6)
        content = get_success_data(api.approve_content(content["id"], officer_headers))
        assert content["content_status"] == "APPROVED"
        assert content["approved_by_user_id"] == officer_headers["X-User-ID"]

    def test_version_reaches_six_across_rework_loop(
            self, api, admin_headers, officer_headers):
        """PRD §2.5: "`version` (integer): a system-managed integer that
        increments by one on every mutation of the resource, including
        mutations caused by a cascade from some other operation."
        PRD §3.2: "Every accepted edit increments the content's `version`."

        Design: Difficulty/non_linear_state_machine/content_rework_cycle
        """
        author = make_admin_headers("ta-1")
        content = get_success_data(
            api.create_content(create_content_payload(code="RW-V"), author))
        assert content["version"] == 1
        content = get_success_data(api.submit_content(content["id"], author))
        assert content["version"] == 2
        content = get_success_data(
            api.reject_content(content["id"], create_reject_payload(), officer_headers))
        assert content["version"] == 3
        content = get_success_data(
            api.update_content(
                content["id"],
                {"expected_content_version": 3, "title": "Rework Revised"},
                author))
        assert content["version"] == 4, (
            f"accepted edit must bump version to 4, got {content['version']}")
        content = get_success_data(api.submit_content(content["id"], author))
        assert content["version"] == 5
        content = get_success_data(api.approve_content(content["id"], officer_headers))
        assert content["version"] == 6, (
            f"six mutations from creation must yield version 6, got {content['version']}")

    def test_rework_edit_clears_rejection_fields(
            self, api, admin_headers, officer_headers):
        """PRD §3.2: "editing content that sits in `REJECTED` returns it to
        `DRAFT` and clears both `rejection_reason` and `approved_by_user_id`,
        resetting the rework loop."

        Design: Difficulty/non_linear_state_machine/content_rework_cycle
        """
        author = make_admin_headers("ta-1")
        content = get_success_data(
            api.create_content(create_content_payload(code="RW-C"), author))
        get_success_data(api.submit_content(content["id"], author))
        content = get_success_data(
            api.reject_content(content["id"], create_reject_payload(), officer_headers))
        content = get_success_data(
            api.update_content(
                content["id"],
                {"expected_content_version": content["version"],
                 "credit_hours": 2.0},
                author))
        assert content["content_status"] == "DRAFT"
        assert content.get("rejection_reason") in (None, ""), (
            f"rejection_reason must be cleared, got {content.get('rejection_reason')!r}")
        assert content.get("approved_by_user_id") in (None, ""), (
            "approved_by_user_id must be cleared on rework")


class TestEnrollmentRetakeCycle:
    """ENROLLED -> IN_PROGRESS -> FAILED -> ENROLLED -> IN_PROGRESS -> COMPLETED."""

    def _setup_started_enrollment(self, api, admin_headers, officer_headers):
        from test_helpers import (
            create_approved_content,
            create_enrollment,
            create_rep,
            start_enrollment,
        )
        rep = create_rep(crd_number="CRD-RT1")
        content = create_approved_content(
            code="RT-1", ce_category="FIRM_ELEMENT", min_passing_score=70)
        enrollment = create_enrollment(rep["id"], content_id=content["id"])
        start_enrollment(enrollment["id"], rep["id"])
        return rep, content, enrollment

    def test_retake_cycle_completes_on_second_pass(
            self, api, admin_headers, officer_headers):
        """PRD §3.4: "The retake cycle lets a rep recover: reattempting a
        `FAILED` enrollment returns it to `ENROLLED` and recomputes `expires_at`
        as a fresh ninety-day window from that moment, but only while
        `attempt_count` is still below three."

        Design: Difficulty/non_linear_state_machine/enrollment_retake_cycle
        """
        from test_helpers import make_rep_headers
        rep, content, enrollment = self._setup_started_enrollment(
            api, admin_headers, officer_headers)

        # First attempt: fail with 50 (< 70)
        resp = api.complete_enrollment(
            enrollment["id"], {"score": 50}, make_rep_headers(rep["id"]))
        data = validate_success(resp)
        assert data["enrollment_status"] == "FAILED"
        assert data["attempt_count"] == 1

        # Reattempt -> ENROLLED
        resp = api.reattempt_enrollment(enrollment["id"], make_rep_headers(rep["id"]))
        data = validate_success(resp)
        assert data["enrollment_status"] == "ENROLLED"

        # Start again, then pass with 80
        validate_success(
            api.start_enrollment(enrollment["id"], make_rep_headers(rep["id"])))
        resp = api.complete_enrollment(
            enrollment["id"], {"score": 80}, make_rep_headers(rep["id"]))
        data = validate_success(resp)
        assert data["enrollment_status"] == "COMPLETED"

    def test_retake_cycle_accumulates_attempt_count(
            self, api, admin_headers, officer_headers):
        """PRD §3.4: "When the `score` falls short, the enrollment moves to
        `FAILED` instead — `attempt_count` still increments and `last_score`
        is still recorded, but no credit hours accrue anywhere."
        PRD §3.4: "When the `score` meets or exceeds the content's
        `min_passing_score`, the enrollment moves to `COMPLETED`:
        `attempt_count` increments by one, `last_score` records the score,
        and `completed_at` is stamped from the logical clock."

        Design: Difficulty/non_linear_state_machine/enrollment_retake_cycle
        """
        from test_helpers import make_rep_headers
        rep, content, enrollment = self._setup_started_enrollment(
            api, admin_headers, officer_headers)

        # Fail once (attempt 1)
        data = validate_success(api.complete_enrollment(
            enrollment["id"], {"score": 50}, make_rep_headers(rep["id"])))
        assert data["attempt_count"] == 1
        assert data["last_score"] == 50

        # Reattempt and pass (attempt 2)
        validate_success(api.reattempt_enrollment(
            enrollment["id"], make_rep_headers(rep["id"])))
        validate_success(api.start_enrollment(
            enrollment["id"], make_rep_headers(rep["id"])))
        data = validate_success(api.complete_enrollment(
            enrollment["id"], {"score": 80}, make_rep_headers(rep["id"])))
        assert data["attempt_count"] == 2, (
            f"attempt_count must accumulate across the retake loop, "
            f"got {data['attempt_count']}")
        assert data["last_score"] == 80
        assert data["enrollment_status"] == "COMPLETED"


class TestContentOcc:
    """OCC on PUT /contents/{contentId} (expected_content_version)."""

    def test_first_edit_succeeds_with_current_version(
            self, api, admin_headers):
        """PRD §2.7: "A `PUT /contents/{contentId}` request must carry
        `expected_content_version` holding the content's `version` as the
        client last observed it. An edit bumps the content's `version` and,
        for rejected content, returns it to `DRAFT`; if
        `expected_content_version` does not match the content's current
        `version`, the edit is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/c_occ_content_update_rejects_stale_version
        """
        author = make_admin_headers("ta-1")
        content = get_success_data(
            api.create_content(create_content_payload(code="OCC-1"), author))
        assert content["version"] == 1

        edited = get_success_data(api.update_content(
            content["id"],
            {"expected_content_version": 1, "title": "Occ One Edited"},
            author))
        assert edited["version"] == 2, (
            f"first edit with the current version must succeed and bump to 2, "
            f"got {edited['version']}")
        assert edited["title"] == "Occ One Edited"
        assert edited["content_status"] == "DRAFT"

    def test_second_edit_with_stale_version_rejected(self, api, admin_headers):
        """PRD §2.7: "if `expected_content_version` does not match the
        content's current `version`, the edit is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/c_occ_content_update_rejects_stale_version
        """
        author = make_admin_headers("ta-1")
        content = get_success_data(
            api.create_content(create_content_payload(code="OCC-2"), author))
        stale_version = content["version"]  # 1
        get_success_data(api.update_content(
            content["id"],
            {"expected_content_version": stale_version, "title": "First Edit"},
            author))

        resp = api.update_content(
            content["id"],
            {"expected_content_version": stale_version, "title": "Stale Edit"},
            author)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
