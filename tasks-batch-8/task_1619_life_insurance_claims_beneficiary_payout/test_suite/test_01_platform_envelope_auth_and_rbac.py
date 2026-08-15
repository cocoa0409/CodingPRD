"""Platform-wide contract: auth header enforcement, role gating, the response
envelope, pagination, per-resource 404s, immediate read-after-write, and the
fixed startup logical clock."""
from test_helpers import (
    EXAMINER_2,
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_claim_payload,
    create_policy_payload,
    create_policy_with_statute,
    create_statute_payload,
    file_claim,
    file_claim_with_verified_docs,
    is_valid_uuid,
    make_claims_examiner_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthHeaderEnforcement:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role the
        system does not recognize, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/c_missing_auth_header_returns_unauthenticated
        """
        resp = api.create_policy(create_policy_payload(policy_number="P-VAL-1"),
                                 headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRoleGating:
    def test_approve_as_examiner_forbidden(
        self, api, claims_examiner_headers, policy_administrator_headers
    ):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §4: "POST | `/claims/{claimId}/approve` | Approve the claim; compute
        interest and run the allocation waterfall | ClaimsApprover".

        Design: Corner/rbac/c_approve_as_examiner_forbidden
        """
        policy = create_policy_with_statute("IL", policy_number="P-RBAC-1")
        claim, _docs = file_claim_with_verified_docs(policy["id"])
        assert claim["status"] == "UNDER_REVIEW"

        # A third examiner (not the filer) attempts the ClaimsApprover action.
        resp = api.approve_claim(claim["id"], make_claims_examiner_headers("examiner-3"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert api.get_claim(claim["id"], claims_examiner_headers).json()["data"][
            "status"] == "UNDER_REVIEW"

    def test_statute_create_as_examiner_forbidden(
        self, api, claims_examiner_headers
    ):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §4: "POST | `/state-statutes` | Configure a state's claims statute |
        ComplianceOfficer".

        Design: Corner/rbac/c_statute_create_as_examiner_forbidden
        """
        resp = api.create_state_statute(create_statute_payload(),
                                        claims_examiner_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        data, meta = validate_paginated(api.list_state_statutes(claims_examiner_headers))
        assert meta["total_count"] == 0 and data == []

    def test_interpleader_as_approver_forbidden(
        self, api, claims_approver_headers
    ):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §4: "POST | `/claims/{claimId}/refer-interpleader` | Refer competing
        claims to court via interpleader | LegalCounsel".

        Design: Corner/rbac/c_interpleader_as_approver_forbidden
        """
        policy = create_policy_with_statute("IL", policy_number="P-RBAC-2")
        claim, _docs = file_claim_with_verified_docs(policy["id"])

        resp = api.refer_interpleader(claim["id"], {"court_reference": "2026-CV-0002"},
                                      claims_approver_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestEnvelopeAndPagination:
    def test_claims_list_pagination_and_envelope(
        self, api, claims_examiner_headers
    ):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it
        defaults to 10, accepts a minimum of 1, and is capped at a maximum of
        100. The `offset` parameter states how many items to skip and defaults
        to 0."
        PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/entities/c_list_pagination_and_envelope_shape
        """
        policy = create_policy_with_statute("IL", policy_number="P-COR-5")
        set_clock("2026-03-05T00:00:00Z")
        c1 = file_claim(policy["id"], "2026-03-01")
        c2 = file_claim(policy["id"], "2026-03-02")

        page1_resp = api.list_claims(
            claims_examiner_headers,
            params={"policy_id": policy["id"], "limit": 1, "offset": 0})
        assert page1_resp.json()["response_type"] == "array"
        assert page1_resp.json()["meta"]["api_request_id"].startswith("req_")
        page1, meta1 = validate_paginated(page1_resp)
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1 and meta1["offset"] == 0

        page2_resp = api.list_claims(
            claims_examiner_headers,
            params={"policy_id": policy["id"], "limit": 1, "offset": 1})
        page2, meta2 = validate_paginated(page2_resp)
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False

        ids = {page1[0]["id"], page2[0]["id"]}
        assert ids == {c1["id"], c2["id"]}, "Pages must partition the two claims"


class TestNotFoundCatalog:
    def test_get_claim_not_found(self, api, claims_examiner_headers):
        """PRD §2.12: "The request is rejected at the first identifier that does
        not correspond to an existing resource, with the error naming that
        resource" (the claim member of that list is `ERR_CLAIM_NOT_FOUND`,
        HTTP 404).

        Design: Corner/entities/c_get_claim_not_found
        """
        resp = api.get_claim(NON_EXISTENT_UUID, claims_examiner_headers)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FOUND)
        assert resp.json()["response_type"] == "error"

    def test_per_resource_not_found_catalog(
        self, api, claims_examiner_headers, policy_administrator_headers,
        claims_approver_headers, compliance_officer_headers
    ):
        """PRD §2.12: "The request is rejected at the first identifier that does
        not correspond to an existing resource, with the error naming that
        resource: `ERR_POLICY_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
        `ERR_DOCUMENT_NOT_FOUND`, `ERR_DESIGNATION_NOT_FOUND`,
        `ERR_BENEFICIARY_CLAIM_NOT_FOUND`, `ERR_ELECTION_NOT_FOUND`,
        `ERR_ACCOUNT_NOT_FOUND`, `ERR_MATCH_NOT_FOUND`, or `ERR_CASE_NOT_FOUND`
        (all HTTP 404)."

        Design: Corner/errors/c_not_found_catalog
        """
        policy = create_policy_with_statute("IL", policy_number="P-ERR-1")
        set_clock("2026-03-05T00:00:00Z")
        claim = file_claim(policy["id"], "2026-03-01")

        cases = [
            (api.create_claim(
                create_claim_payload(policy_id=NON_EXISTENT_UUID,
                                     date_of_death="2026-03-01"),
                claims_examiner_headers), ApiErrorId.ERR_POLICY_NOT_FOUND),
            (api.review_document(claim["id"], NON_EXISTENT_UUID,
                                 {"review_result": "VERIFIED"}, EXAMINER_2),
             ApiErrorId.ERR_DOCUMENT_NOT_FOUND),
            (api.revoke_beneficiary_designation(NON_EXISTENT_UUID,
                                                policy_administrator_headers),
             ApiErrorId.ERR_DESIGNATION_NOT_FOUND),
            (api.validate_beneficiary_claim(NON_EXISTENT_UUID, claims_examiner_headers),
             ApiErrorId.ERR_BENEFICIARY_CLAIM_NOT_FOUND),
            (api.confirm_payout_election(NON_EXISTENT_UUID, claims_examiner_headers),
             ApiErrorId.ERR_ELECTION_NOT_FOUND),
            (api.withdraw_from_account(NON_EXISTENT_UUID, {"amount_cents": 1},
                                       claims_approver_headers),
             ApiErrorId.ERR_ACCOUNT_NOT_FOUND),
            (api.review_death_master_match(NON_EXISTENT_UUID,
                                           {"review_outcome": "CONFIRMED"},
                                           compliance_officer_headers),
             ApiErrorId.ERR_MATCH_NOT_FOUND),
            (api.resolve_escheatment_case(NON_EXISTENT_UUID, {},
                                          compliance_officer_headers),
             ApiErrorId.ERR_CASE_NOT_FOUND),
        ]
        for resp, error_id in cases:
            validate_error(resp, error_id)
            assert resp.status_code == 404


class TestImmediateConsistencyAndClock:
    def test_immediate_read_after_write(self, api, claims_examiner_headers,
                                        policy_administrator_headers):
        """PRD §2.11: "Consistency is immediate: every mutation and every cascade
        it triggers is visible in the same response and in all subsequent
        reads."

        Design: Corner/consistency_model/c_immediate_read_after_write
        """
        created = validate_success(
            api.create_policy(create_policy_payload(policy_number="P-CON-1"),
                              policy_administrator_headers),
            expected_status=201)
        assert is_valid_uuid(created["id"])
        assert created["status"] == "ACTIVE"
        assert isinstance(created["version"], int)

        fetched = validate_success(api.get_policy(created["id"], claims_examiner_headers))
        assert fetched["policy_number"] == "P-CON-1"
        assert fetched["status"] == "ACTIVE"

        data, meta = validate_paginated(
            api.list_policies(claims_examiner_headers, params={"state_code": "IL"}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == created["id"]

    def test_clock_default_startup_date(self, api, claims_examiner_headers):
        """PRD §2.4: "At startup the logical clock reads exactly
        2026-08-01T00:00:00Z."
        PRD §3.4: "A successfully filed claim stands in `NOTIFIED` status with
        its `notification_date` stamped from the logical clock".

        Design: Corner/cross_cutting_layers/c_clock_default_is_2026_08_01
        """
        # Deliberately no set_clock call anywhere in this scenario.
        policy = create_policy_with_statute("IL", policy_number="P-CLK-1")
        claim = file_claim(policy["id"], "2026-03-01")
        assert claim["notification_date"] == "2026-08-01", (
            f"notification_date must come from the fixed startup clock, got "
            f"{claim['notification_date']!r}")
