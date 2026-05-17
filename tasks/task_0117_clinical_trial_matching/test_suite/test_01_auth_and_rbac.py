"""Auth, RBAC, ownership, NotFound, and the response envelope.

PRD §2.1 (auth/role), §2.2 (envelope), §2.3 (pagination), §2.5 (SoD),
§2.7 (left-to-right path resolution).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_trial_payload,
    enroll_participant,
    make_participant_self_headers,
    setup_enrolled_participant,
    setup_irb_pending_for_sod_violation,
    setup_trial_open_for_enrollment,
    validate_error,
    validate_success,
)


# ===========================================================================
# §2.1 Auth — missing / malformed headers
# ===========================================================================
class TestAuthHeaders:
    """PRD §2.1: every request must carry X-User-ID and X-User-Role."""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "Missing, empty, or invalid headers cause the
        request to be rejected with ERR_AUTH_REQUIRED."

        Claim: a request with neither header set returns
        ERR_AUTH_REQUIRED.
        """
        res = api.create_trial(create_trial_payload(), headers={})
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "Missing, empty, or invalid headers cause the
        request to be rejected with ERR_AUTH_REQUIRED."

        Claim: omitting X-User-ID returns ERR_AUTH_REQUIRED.
        """
        res = api.create_trial(
            create_trial_payload(),
            headers={"X-User-Role": "PrincipalInvestigator"},
        )
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "Missing, empty, or invalid headers cause the
        request to be rejected with ERR_AUTH_REQUIRED."

        Claim: omitting X-User-Role returns ERR_AUTH_REQUIRED.
        """
        res = api.create_trial(
            create_trial_payload(),
            headers={"X-User-ID": "pi-001"},
        )
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_empty_user_id_rejected(self, api):
        """PRD §2.1: "Missing, empty, or invalid headers cause the
        request to be rejected with ERR_AUTH_REQUIRED."

        Claim: an empty X-User-ID returns ERR_AUTH_REQUIRED.
        """
        res = api.create_trial(
            create_trial_payload(),
            headers={
                "X-User-ID": "",
                "X-User-Role": "PrincipalInvestigator",
            },
        )
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_unrecognized_role_rejected(self, api):
        """PRD §2.1: "The system recognizes exactly four roles, spelled
        as follows: PrincipalInvestigator, IRBReviewer,
        StudyCoordinator, and Participant_self." And: "Missing, empty,
        or invalid headers cause the request to be rejected with
        ERR_AUTH_REQUIRED."

        Claim: a role that is not one of the four is ERR_AUTH_REQUIRED.
        """
        res = api.create_trial(
            create_trial_payload(),
            headers={
                "X-User-ID": "x-1", "X-User-Role": "Admin",
            },
        )
        validate_error(res, "ERR_AUTH_REQUIRED")


# ===========================================================================
# §2.1 / §4 RBAC — wrong role → ERR_FORBIDDEN
# ===========================================================================
class TestRoleAuthorization:
    """PRD §2.1: "An authenticated caller whose declared role is not
    authorized to invoke the targeted endpoint is rejected with
    ERR_FORBIDDEN.\""""

    def test_study_coordinator_cannot_create_trial(self, api):
        """PRD §4 lists POST /trials as PrincipalInvestigator-exclusive.

        PRD §2.1: "An authenticated caller whose declared role is not
        authorized to invoke the targeted endpoint is rejected with
        ERR_FORBIDDEN."

        Claim: StudyCoordinator calling POST /trials returns
        ERR_FORBIDDEN.
        """
        res = api.create_trial(
            create_trial_payload(),
            TEST_USERS["study_coordinator_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_irb_reviewer_cannot_create_participant(self, api):
        """PRD §4 lists POST /participants as
        StudyCoordinator-exclusive.

        PRD §2.1: "An authenticated caller whose declared role is not
        authorized to invoke the targeted endpoint is rejected with
        ERR_FORBIDDEN."

        Claim: IRBReviewer calling POST /participants returns
        ERR_FORBIDDEN.
        """
        trial, _arms, _v1 = setup_trial_open_for_enrollment()
        res = api.create_participant(
            {"trial_id": trial["id"], "profile": {"age": 30}},
            TEST_USERS["irb_reviewer_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_pi_cannot_complete_visit(self, api):
        """PRD §4 lists POST /visits/{id}/complete as
        StudyCoordinator-exclusive.

        Claim: PrincipalInvestigator calling /complete on a visit
        returns ERR_FORBIDDEN.
        """
        trial, p, _arms = setup_enrolled_participant(
            blood_draw_window_days=7,
        )
        # Schedule a visit then attempt complete as PI.
        from test_helpers import iso_anchor_offset, schedule_visit
        v = schedule_visit(
            p["id"], sequence_no=1,
            target_date=iso_anchor_offset(days=10),
        )
        res = api.complete_visit(
            v["id"],
            {"actual_draw_at": iso_anchor_offset(days=10, hours=12)},
            TEST_USERS["pi_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_pi_cannot_submit_irb_review(self, api):
        """PRD §4 lists POST /trials/{id}/irb-reviews as
        IRBReviewer-exclusive.

        Claim: PrincipalInvestigator calling /irb-reviews returns
        ERR_FORBIDDEN.
        """
        from test_helpers import setup_two_arms_irb_pending
        trial, _arms, _v1 = setup_two_arms_irb_pending()
        res = api.create_irb_review(
            trial["id"],
            {"decision": "APPROVED", "notes": "ok"},
            TEST_USERS["pi_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.1 Participant_self ownership.
# ===========================================================================
class TestParticipantSelfOwnership:
    """PRD §2.1: "Participant_self may sign consent, withdraw, read
    their own participant record, list their own visits, and list their
    own payments only when participant_id == X-User-ID. Any attempt by
    Participant_self to touch another participant's resources is
    ERR_FORBIDDEN.\""""

    def test_participant_self_can_get_own_record(self, api):
        """PRD §2.1: "Participant_self may … read their own participant
        record … only when participant_id == X-User-ID."

        Claim: a Participant_self GET on their own id succeeds.
        """
        trial, p, _arms = setup_enrolled_participant()
        res = api.get_participant(
            p["id"], make_participant_self_headers(p["id"]),
        )
        data = validate_success(res, 200)
        assert data["id"] == p["id"]

    def test_participant_self_cannot_read_other(self, api):
        """PRD §2.1: "Any attempt by Participant_self to touch another
        participant's resources is ERR_FORBIDDEN."

        Claim: a Participant_self GET on someone else's id returns
        ERR_FORBIDDEN.
        """
        trial, p_a, _arms = setup_enrolled_participant()
        p_b = enroll_participant(
            trial["id"], active_consent_version=1,
            profile={"age": 35},
        )
        res = api.get_participant(
            p_b["id"], make_participant_self_headers(p_a["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_participant_self_cannot_withdraw_other(self, api):
        """PRD §2.1: "Any attempt by Participant_self to touch another
        participant's resources is ERR_FORBIDDEN."

        Claim: Participant_self attempting to withdraw a different
        participant returns ERR_FORBIDDEN.
        """
        trial, p_a, _arms = setup_enrolled_participant()
        p_b = enroll_participant(
            trial["id"], active_consent_version=1,
            profile={"age": 40},
        )
        res = api.withdraw_participant(
            p_b["id"], {},
            make_participant_self_headers(p_a["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.5 Segregation of Duties.
# ===========================================================================
class TestSegregationOfDuties:
    """PRD §2.5: "When an IRBReviewer later submits a review decision,
    the reviewer's X-User-ID is compared to that recorded
    created_by_user_id; if they match, the request is rejected with
    ERR_SOD_VIOLATION at HTTP 403.\""""

    def test_sod_violation_blocks_approved(self, api):
        """PRD §2.5: "This holds equally for APPROVED,
        REVISIONS_REQUESTED, and REJECTED — all three are subject to
        the SoD barrier, none of them can be self-served."

        Claim: an IRBReviewer whose X-User-ID equals the creator's
        X-User-ID is rejected with ERR_SOD_VIOLATION on APPROVED.
        """
        trial, bad_headers = setup_irb_pending_for_sod_violation()
        res = api.create_irb_review(
            trial["id"],
            {"decision": "APPROVED", "notes": "self-approve"},
            bad_headers,
        )
        validate_error(res, "ERR_SOD_VIOLATION")

    def test_sod_violation_blocks_revisions_requested(self, api):
        """PRD §2.5: "This holds equally for APPROVED,
        REVISIONS_REQUESTED, and REJECTED — all three are subject to
        the SoD barrier, none of them can be self-served."

        Claim: REVISIONS_REQUESTED is also blocked when reviewer ==
        creator.
        """
        trial, bad_headers = setup_irb_pending_for_sod_violation()
        res = api.create_irb_review(
            trial["id"],
            {"decision": "REVISIONS_REQUESTED",
             "notes": "self-revise"},
            bad_headers,
        )
        validate_error(res, "ERR_SOD_VIOLATION")

    def test_sod_violation_blocks_rejected(self, api):
        """PRD §2.5: "This holds equally for APPROVED,
        REVISIONS_REQUESTED, and REJECTED — all three are subject to
        the SoD barrier, none of them can be self-served."

        Claim: REJECTED is also blocked when reviewer == creator.
        """
        trial, bad_headers = setup_irb_pending_for_sod_violation()
        res = api.create_irb_review(
            trial["id"],
            {"decision": "REJECTED", "notes": "self-reject"},
            bad_headers,
        )
        validate_error(res, "ERR_SOD_VIOLATION")


# ===========================================================================
# §2.7 NotFound — left-to-right path resolution.
# ===========================================================================
class TestNotFound:
    """PRD §2.7: "if trial_id does not refer to any persisted trial,
    the request fails with ERR_NOT_FOUND before any inner segment is
    even examined.\""""

    def test_get_trial_with_nonexistent_id(self, api):
        """PRD §2.7: "if trial_id does not refer to any persisted trial,
        the request fails with ERR_NOT_FOUND before any inner segment
        is even examined."

        Claim: GET /trials/<unknown-uuid> returns ERR_NOT_FOUND.
        """
        res = api.get_trial(
            NON_EXISTENT_UUID, TEST_USERS["pi_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_arms_under_nonexistent_trial(self, api):
        """PRD §2.7: "The outermost path segment is resolved first: if
        trial_id does not refer to any persisted trial, the request
        fails with ERR_NOT_FOUND before any inner segment is even
        examined."

        Claim: POST /trials/<unknown>/arms returns ERR_NOT_FOUND.
        """
        res = api.create_arm(
            NON_EXISTENT_UUID,
            {"code": "A1", "label": "Arm 1", "weight": 1},
            TEST_USERS["pi_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_participant_with_nonexistent_id(self, api):
        """PRD §2.7: "Only after the parent is resolved does the server
        attempt to resolve the next segment".

        Claim: GET /participants/<unknown> returns ERR_NOT_FOUND.
        """
        res = api.get_participant(
            NON_EXISTENT_UUID, TEST_USERS["pi_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_create_participant_unknown_trial_id_is_not_found(self, api):
        """PRD §2.7: "The same principle applies to foreign-key
        identifiers that appear in the request body … a body-referenced
        id that does not resolve is ERR_NOT_FOUND."

        Claim: POST /participants with an unknown trial_id returns
        ERR_NOT_FOUND.
        """
        res = api.create_participant(
            {"trial_id": NON_EXISTENT_UUID, "profile": {"age": 25}},
            TEST_USERS["study_coordinator_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")


# ===========================================================================
# §2.2 Response envelope — success.
# ===========================================================================
class TestResponseEnvelope:
    """PRD §2.2: every 2xx response carries `meta`, `response_type`, and
    `data`."""

    def test_success_envelope_fields(self, api):
        """PRD §2.2: "The api_request_id is a server-generated unique
        identifier for the request that starts with req_."
        PRD §2.2: "The api_request_timestamp is a server-generated ISO
        8601 UTC timestamp with three fractional digits."

        Claim: a successful create returns the standard envelope.
        """
        res = api.create_trial(
            create_trial_payload(),
            TEST_USERS["pi_headers"],
        )
        # validate_success returns the data payload; raw envelope is
        # implicitly checked by the framework, but we also re-read the
        # meta object to assert the timestamp/id shape exists.
        validate_success(res, 201)
        body = res.json()
        assert "meta" in body
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str)
        assert meta["api_request_id"].startswith("req_")
        assert isinstance(meta.get("api_request_timestamp"), str)
