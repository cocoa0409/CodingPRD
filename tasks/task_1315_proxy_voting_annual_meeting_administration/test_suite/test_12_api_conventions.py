"""API-wide conventions: response envelopes, authentication, pagination,
resource-specific 404s, and optimistic concurrency on meeting amendment
(PRD §2.1, §2.2, §2.3, §2.6, §2.7)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    is_iso8601_timestamp,
    ApiErrorId,
    assert_meeting, assert_shareholder_account,
    create_draft_meeting, add_account,
    NON_EXISTENT_UUID,
)


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request that is missing either header, or whose role
        value is not one of the declared roles, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.6: "1. **Authentication.** Presence and validity of the
        `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api.list_meetings(headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestResponseEnvelope:
    def test_response_envelope_success_and_error_shape(self, api, proxy_admin_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`"; "The
        `response_type` is either "object" for a single resource or "array" for
        a list of resources."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/endpoints/response_envelope_success_and_error_shape
        """
        meeting = create_draft_meeting()
        resp = api.get_meeting(meeting["id"], proxy_admin_headers)
        assert resp.status_code == 200, f"expected 200, got {resp.status_code}"
        body = resp.json()
        assert isinstance(body["meta"]["api_request_id"], str) and body["meta"]["api_request_id"], (
            "meta.api_request_id must be a non-empty string"
        )
        assert body["meta"]["api_request_id"].startswith("req_"), "api_request_id starts with req_"
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert body["data"]["id"] == meeting["id"]

        err_resp = api.get_meeting(NON_EXISTENT_UUID, proxy_admin_headers)
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_MEETING_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str) and err_body["data"]["message"].strip()
        assert err_resp.status_code == 404


class TestPagination:
    def test_account_list_pagination_limit_offset_total_count(self, api, transfer_agent_headers):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return"; "The `offset` parameter specifies the number of items
        to skip and defaults to 0"; "Paginated and non-paginated list-based
        responses include the following fields in the `meta` object of the
        response envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/account_list_pagination_limit_offset_total_count
        """
        meeting = create_draft_meeting()
        add_account(meeting["id"], "A-1001", shares_held=100, holder_name="H1")
        add_account(meeting["id"], "A-1002", shares_held=200, holder_name="H2")
        add_account(meeting["id"], "A-1003", shares_held=300, holder_name="H3")

        page1, meta1 = validate_paginated(api.list_shareholder_accounts(
            transfer_agent_headers, params={"meeting_id": meeting["id"], "limit": 2, "offset": 0}
        ))
        assert len(page1) == 2, f"page 1 must hold exactly 2 items, got {len(page1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_shareholder_accounts(
            transfer_agent_headers, params={"meeting_id": meeting["id"], "limit": 2, "offset": 2}
        ))
        assert len(page2) == 1, f"page 2 must hold the final item only, got {len(page2)}"
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        for account in page1 + page2:
            assert_shareholder_account(account)


class TestNotFoundSweep:
    def test_not_found_sweep_returns_resource_specific_404s(self, api, proxy_admin_headers):
        """PRD §2.6: "3. **Existence.** Every identifier in the request path,
        validated left to right, with the resource-specific not-found error
        (for example `ERR_MEETING_NOT_FOUND` before `ERR_PROPOSAL_NOT_FOUND`
        when both appear in a path)."
        PRD §2.6: "Each resource type has its own code: `ERR_MEETING_NOT_FOUND`,
        `ERR_ACCOUNT_NOT_FOUND`, `ERR_PROPOSAL_NOT_FOUND`, `ERR_VOTE_NOT_FOUND`,
        `ERR_QUESTION_NOT_FOUND`, `ERR_CHALLENGE_NOT_FOUND`,
        `ERR_SESSION_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`,
        `ERR_DISTRIBUTION_NOT_FOUND`, `ERR_BROKER_SEARCH_NOT_FOUND`, and
        `ERR_CERTIFICATION_NOT_FOUND`."

        Design: Corner/errors/not_found_sweep_returns_resource_specific_404s
        """
        cases = [
            ("shareholder-account", lambda rid: api.get_shareholder_account(rid, proxy_admin_headers),
             ApiErrorId.ERR_ACCOUNT_NOT_FOUND),
            ("proposal", lambda rid: api.get_proposal(rid, proxy_admin_headers),
             ApiErrorId.ERR_PROPOSAL_NOT_FOUND),
            ("vote-instruction", lambda rid: api.get_vote_instruction(rid, proxy_admin_headers),
             ApiErrorId.ERR_VOTE_NOT_FOUND),
            ("question-submission", lambda rid: api.get_question_submission(rid, proxy_admin_headers),
             ApiErrorId.ERR_QUESTION_NOT_FOUND),
            ("vote-challenge", lambda rid: api.get_vote_challenge(rid, proxy_admin_headers),
             ApiErrorId.ERR_CHALLENGE_NOT_FOUND),
            ("platform-session", lambda rid: api.get_platform_session(rid, proxy_admin_headers),
             ApiErrorId.ERR_SESSION_NOT_FOUND),
            ("solicitation-campaign", lambda rid: api.get_solicitation_campaign(rid, proxy_admin_headers),
             ApiErrorId.ERR_CAMPAIGN_NOT_FOUND),
            ("material-distribution", lambda rid: api.get_material_distribution(rid, proxy_admin_headers),
             ApiErrorId.ERR_DISTRIBUTION_NOT_FOUND),
            ("broker-search", lambda rid: api.get_broker_search(rid, proxy_admin_headers),
             ApiErrorId.ERR_BROKER_SEARCH_NOT_FOUND),
            ("inspector-certification", lambda rid: api.get_inspector_certification(rid, proxy_admin_headers),
             ApiErrorId.ERR_CERTIFICATION_NOT_FOUND),
        ]
        for i, (label, call, expected) in enumerate(cases, start=1):
            missing_id = f"00000000-0000-4000-8000-{i:012d}"
            resp = call(missing_id)
            validate_error(resp, expected, 404)


class TestMeetingAmendOcc:
    def test_meeting_patch_occ_success_then_stale_rejection(self, api, proxy_admin_headers):
        """PRD §2.7: "Amending a meeting's parameters. If the meeting's current
        `version` has advanced beyond the supplied value — because another
        writer amended the meeting or drove a lifecycle transition since the
        client last read it — the amendment is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.1: "a successful amendment increments the meeting's `version` by
        one."

        Design: Corner/cross_cutting_layers/meeting_patch_occ_success_then_stale_rejection
        """
        meeting = create_draft_meeting()
        observed_version = meeting["version"]
        first = api.patch_meeting(
            meeting["id"],
            {"quorum_threshold_pct": 0.6, "expected_meeting_version": observed_version},
            proxy_admin_headers,
        )
        data = validate_success(first, 200)
        assert_meeting(data)
        assert data["quorum_threshold_pct"] == 0.6
        assert data["version"] == observed_version + 1, (
            f"successful amendment increments version by one: "
            f"{observed_version} -> {data['version']}"
        )
        stale = api.patch_meeting(
            meeting["id"],
            {"outstanding_shares": 12000, "expected_meeting_version": observed_version},
            proxy_admin_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)
        current = validate_success(api.get_meeting(meeting["id"], proxy_admin_headers), 200)
        assert current["outstanding_shares"] == 10000, (
            "the rejected write applies nothing: outstanding_shares is unchanged"
        )
