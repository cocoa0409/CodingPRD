"""Auth pipeline, not-found handling, and the list response envelope."""
from test_helpers import (
    validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, build_user_headers,
    assert_playbook,
    setup_user_directory, headers_by_id, create_playbook_payload,
)


class TestAuthPipeline:
    def test_missing_user_id_header_rejected(self, api):
        """A request missing X-User-ID fails the first pipeline check.

        PRD §2.1: "A request missing either header, or carrying a malformed header, is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        headers = {"X-User-Role": "ContractAnalyst", "Content-Type": "application/json"}
        resp = api.list_playbooks(headers)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        assert resp.status_code == 400

    def test_unresolvable_user_id_rejected(self, api):
        """An X-User-ID that resolves to no ACTIVE User row fails the second
        pipeline check.

        PRD §2.1: "An `X-User-ID` that does not resolve to a `User` row whose `status`
        is `ACTIVE` is rejected with `ERR_USER_NOT_FOUND` (HTTP 401); a deactivated
        account therefore cannot act."

        Design: Corner/validations/unknown_user_id_returns_401
        """
        headers = build_user_headers(NON_EXISTENT_UUID, "ContractAnalyst")
        resp = api.list_playbooks(headers)
        validate_error(resp, ApiErrorId.ERR_USER_NOT_FOUND)
        assert resp.status_code == 401

    def test_contract_analyst_cannot_publish_playbook(self, api):
        """Publish is a ChiefCounsel-only operation; an analyst is refused at the
        role gate.

        PRD §2.1: "A caller whose role is not permitted on the target endpoint is
        rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/playbooks/{playbookId}/publish` | Publish a Playbook
        (`DRAFT → ACTIVE`) | ChiefCounsel |"

        Design: Corner/validations/forbidden_role_on_publish_returns_403
        """
        users = setup_user_directory()
        hdrs = headers_by_id(users)
        playbook = get_success_data(api.create_playbook(
            create_playbook_payload(name="V3"), hdrs[users["cc"]["id"]]))

        resp = api.publish_playbook(playbook["id"], hdrs[users["ca"]["id"]])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert resp.status_code == 403


class TestNestedResourceRetrieval:
    def test_get_missing_negotiation_returns_404(self, api):
        """An unknown negotiation identifier fails path resolution.

        PRD §2.9: "rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first
        identifier that does not resolve to an existing resource."

        Design: Corner/entities/negotiation_get_not_found_returns_404
        """
        users = setup_user_directory()
        hdrs = headers_by_id(users)
        resp = api.get_negotiation(NON_EXISTENT_UUID, hdrs[users["ca"]["id"]])
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert resp.status_code == 404


class TestListEnvelope:
    def test_playbook_list_uses_paginated_envelope_with_defaults(self, api):
        """List responses carry the array envelope and the pagination meta fields
        with limit defaulting to 10 and offset to 0.

        PRD §2.3: "The `limit` parameter caps the number of items returned: it
        defaults to 10 when omitted, accepts a minimum of 1, and is capped at a
        maximum of 100. The `offset` parameter specifies how many items to skip and
        defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries the pagination fields
        `limit`, `offset`, `total_count`, and `has_more`".

        Design: Corner/endpoints/list_playbooks_pagination_defaults
        """
        users = setup_user_directory()
        hdrs = headers_by_id(users)
        cc = hdrs[users["cc"]["id"]]
        for name in ("P1", "P2", "P3"):
            get_success_data(api.create_playbook(create_playbook_payload(name=name), cc))

        resp = api.list_playbooks(cc)
        body = resp.json()
        assert body.get("response_type") == "array"
        assert str(body["meta"]["api_request_id"]).startswith("req_")

        data, meta = validate_paginated(resp)
        assert len(data) == 3
        for playbook in data:
            assert_playbook(playbook)
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
