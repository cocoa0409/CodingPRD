"""Appeals lifecycle, segregation of duties, remand cascade — PRD §2.8, §3.9, §2.10."""
from __future__ import annotations

import pytest

from test_helpers import (
    APPEAL_AUTHORITY_SECONDARY_ID,
    APPEAL_AUTHORITY_SHARED_ID,
    ApiErrorId,
    OFFICER_SECONDARY_ID,
    OFFICER_SHARED_ID,
    TEST_USERS,
    accept_appeal_for_review,
    assert_appeal,
    create_appeal_payload,
    decide_appeal,
    decide_appeal_payload,
    file_appeal,
    get_request,
    make_appeal_authority_headers,
    make_officer_headers,
    make_requester_headers,
    setup_denied_request,
    setup_denied_request_with_distinct_authority,
    setup_glomar_then_remand_ready,
    setup_remand_ready_appeal,
    validate_error,
    validate_success,
)


# ===========================================================================
# Appeal filing — PRD §3.9
# ===========================================================================
class TestAppealFiling:

    def test_file_requester_appeal_against_denied_request(self, api):
        """PRD §3.9: "The referenced request's `status` must be in the
        set `DENIED`, `PARTIAL_RELEASE`, or `GLOMAR_ISSUED`; an appeal
        against any other status is rejected with `ERR_INVALID_STATE`."
        PRD §3.9: "A newly filed appeal lands in `SUBMITTED` with
        `filed_at` set to the current time".

        Claim: filing a REQUESTER appeal against a DENIED request
        succeeds with status=SUBMITTED.
        """
        requester, denied, _records = setup_denied_request()
        appeal = file_appeal(
            request=denied, appellant_id=requester["id"],
            appellant_role="REQUESTER",
        )
        assert_appeal(appeal)
        assert appeal["status"] == "SUBMITTED"
        assert appeal["filed_at"] is not None
        assert appeal["appellant_role"] == "REQUESTER"
        assert appeal["request_id"] == denied["id"]

    def test_file_appeal_against_acknowledged_request_rejected(self, api):
        """PRD §3.9: "The referenced request's `status` must be in the
        set `DENIED`, `PARTIAL_RELEASE`, or `GLOMAR_ISSUED`; an appeal
        against any other status is rejected with `ERR_INVALID_STATE`."

        Claim: an appeal filed against a Request still in ACKNOWLEDGED
        fails with ERR_INVALID_STATE.
        """
        from test_helpers import create_acknowledged_request
        requester, request = create_acknowledged_request()
        payload = create_appeal_payload(
            request_id=request["id"], appellant_role="REQUESTER",
        )
        resp = api.create_appeal(
            payload, make_requester_headers(requester["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_duplicate_open_appeal_rejected(self, api):
        """PRD §3.9: "At most one open appeal may exist per
        `(request_id, appellant_role)` pair where the appeal's `status`
        is not `DISMISSED` - a second filing in the same pair is rejected
        with `ERR_DUPLICATE_APPEAL` and HTTP 409."

        Claim: a second REQUESTER appeal on the same request fails with
        ERR_DUPLICATE_APPEAL.
        """
        requester, denied, _records = setup_denied_request()
        file_appeal(
            request=denied, appellant_id=requester["id"],
            appellant_role="REQUESTER",
        )
        payload = create_appeal_payload(
            request_id=denied["id"], appellant_role="REQUESTER",
        )
        resp = api.create_appeal(
            payload, make_requester_headers(requester["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPEAL.value)


# ===========================================================================
# accept-for-review + segregation — PRD §2.8, §3.9
# ===========================================================================
class TestAcceptForReview:

    def test_accept_for_review_by_distinct_authority_succeeds(self, api):
        """PRD §3.9: "The appeal authority then accepts the appeal for
        review, transitioning it from `SUBMITTED` to `UNDER_REVIEW`."
        PRD §3.9: "On acceptance, the calling `X-User-ID` is captured
        into `Appeal.deciding_officer_id`, freezing the identity of the
        adjudicator."

        Claim: /accept-for-review by an AppealAuthority whose X-User-ID
        differs from the underlying determining Officer transitions to
        UNDER_REVIEW and writes deciding_officer_id.
        """
        requester, denied, _off_h, auth_h = (
            setup_denied_request_with_distinct_authority(
                officer_operator_id=OFFICER_SHARED_ID,
                appeal_authority_operator_id=APPEAL_AUTHORITY_SHARED_ID,
            )
        )
        appeal = file_appeal(
            request=denied, appellant_id=requester["id"],
            appellant_role="REQUESTER",
        )
        accepted = accept_appeal_for_review(appeal["id"], auth_h)
        assert accepted["status"] == "UNDER_REVIEW"
        assert accepted["deciding_officer_id"] == APPEAL_AUTHORITY_SHARED_ID

    def test_accept_for_review_by_original_officer_rejected_segregation(self, api):
        """PRD §2.8: "when an appeal authority attempts to accept an
        appeal for review, the server compares `X-User-ID` against the
        `actor_id` recorded on the `DETERMINATION_ISSUED` audit entry
        for the underlying request. If they match, the call is rejected
        with `ERR_SEGREGATION_OF_DUTIES` and HTTP 403".

        Claim: /accept-for-review with X-User-ID equal to the original
        determining Officer's X-User-ID fails with
        ERR_SEGREGATION_OF_DUTIES at HTTP 403.
        """
        # Use the same operator id for both officer and appeal authority.
        officer_id = OFFICER_SHARED_ID
        officer_headers = make_officer_headers(officer_id)
        # Drive the determination using that officer.
        from test_helpers import create_requester
        requester, denied, _records = setup_denied_request(
            officer_headers=officer_headers,
        )
        appeal = file_appeal(
            request=denied, appellant_id=requester["id"],
            appellant_role="REQUESTER",
        )
        # Attempt accept-for-review with the SAME X-User-ID as the officer
        # who issued the determination — but as AppealAuthority role.
        bad_auth_h = make_appeal_authority_headers(officer_id)
        resp = api.accept_appeal_for_review(appeal["id"], bad_auth_h)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# ===========================================================================
# decide — PRD §3.9
# ===========================================================================
class TestAppealDecide:

    def test_decide_upheld_transitions_to_upheld(self, api):
        """PRD §3.9: "A decision of `UPHELD` keeps the original
        determination in place; the precondition requires only that the
        appeal is currently `UNDER_REVIEW` and that the calling
        `X-User-ID` equals `Appeal.deciding_officer_id`."

        Claim: /decide with decision=UPHELD transitions to UPHELD.
        """
        _r, _denied, appeal, auth_h = setup_remand_ready_appeal()
        decided = decide_appeal(
            appeal["id"], decision="UPHELD",
            appeal_authority_headers=auth_h,
        )
        assert decided["status"] == "UPHELD"
        assert decided["decision_at"] is not None

    def test_decide_remanded_cascades_request_to_reopened(self, api):
        """PRD §2.10: "when an appeal is decided as remanded, the
        underlying request automatically transitions from its terminal
        determination state (`DENIED`, `PARTIAL_RELEASE`, or
        `GLOMAR_ISSUED`) to `REOPENED_BY_APPEAL`".

        Claim: /decide REMANDED on a DENIED-request appeal cascades
        the Request to REOPENED_BY_APPEAL.
        """
        _r, denied, appeal, auth_h = setup_remand_ready_appeal()
        decide_appeal(
            appeal["id"], decision="REMANDED",
            appeal_authority_headers=auth_h,
        )
        # Verify the cascade on the Request.
        refreshed = get_request(denied["id"])
        assert refreshed["status"] == "REOPENED_BY_APPEAL"

    def test_decide_remanded_on_glomar_clears_basis(self, api):
        """PRD §2.10: "if the appealed determination was Glomar, the
        cascade also clears `glomar_invoked` back to false and empties
        `glomar_exemption_basis` so that the agency starts the new
        search fresh."

        Claim: REMAND of a Glomar appeal cascades to the Request:
        glomar_invoked=false, glomar_exemption_basis=[],
        status=REOPENED_BY_APPEAL.
        """
        _r, glomar_req, appeal, auth_h = setup_glomar_then_remand_ready(
            glomar_basis=["B1"],
        )
        decide_appeal(
            appeal["id"], decision="REMANDED",
            appeal_authority_headers=auth_h,
        )
        refreshed = get_request(glomar_req["id"])
        assert refreshed["status"] == "REOPENED_BY_APPEAL"
        assert refreshed["glomar_invoked"] is False
        assert refreshed["glomar_exemption_basis"] == []

    def test_decide_reversed_available_only_to_requester_appellant(self, api):
        """PRD §3.9: "A decision of `REVERSED` (available only when
        `appellant_role` is `REQUESTER`) reverses the determination".

        Claim: /decide REVERSED succeeds on a REQUESTER appeal.
        """
        _r, _denied, appeal, auth_h = setup_remand_ready_appeal()
        decided = decide_appeal(
            appeal["id"], decision="REVERSED",
            appeal_authority_headers=auth_h,
        )
        assert decided["status"] == "REVERSED"

    def test_decide_by_different_authority_rejected(self, api):
        """PRD §3.9: "the precondition requires ... that the calling
        `X-User-ID` equals `Appeal.deciding_officer_id`."

        Claim: /decide invoked by an AppealAuthority whose X-User-ID
        differs from Appeal.deciding_officer_id (set at accept-for-review)
        is rejected.
        """
        _r, _denied, appeal, auth_h = setup_remand_ready_appeal(
            appeal_authority_operator_id=APPEAL_AUTHORITY_SHARED_ID,
        )
        # The decision is being attempted by a DIFFERENT authority id —
        # a violation of "same authority sees the appeal through".
        other_auth_h = make_appeal_authority_headers(
            APPEAL_AUTHORITY_SECONDARY_ID,
        )
        resp = api.decide_appeal(
            appeal["id"], decide_appeal_payload(decision="UPHELD"),
            other_auth_h,
        )
        from test_helpers import validate_error_is_one_of
        # PRD §3.9 prose binds the rule to the deciding_officer_id —
        # the natural error is ERR_SEGREGATION_OF_DUTIES or
        # ERR_FORBIDDEN. Either is faithful to a PRD-only reading.
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
                ApiErrorId.ERR_FORBIDDEN.value,
            ],
        )


# ===========================================================================
# Resume-search after REMANDED — PRD §3.9
# ===========================================================================
class TestResumeSearchAfterRemand:

    def test_resume_search_after_remand_returns_to_search(self, api):
        """PRD §3.9: "After a request enters `REOPENED_BY_APPEAL`, the
        officer reopens search by transitioning the request from
        `REOPENED_BY_APPEAL` back to `SEARCH`".

        Claim: /resume-search after REOPENED_BY_APPEAL transitions to
        SEARCH.
        """
        _r, denied, appeal, auth_h = setup_remand_ready_appeal()
        decide_appeal(
            appeal["id"], decision="REMANDED",
            appeal_authority_headers=auth_h,
        )
        resp = api.resume_search(
            denied["id"], TEST_USERS["officer_headers"],
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "SEARCH"
