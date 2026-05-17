"""Auth, RBAC, response envelope, pagination, and existence checks.

PRD §2.1 (auth/role), §2.2 (envelope), §2.3 (pagination), §2.7
(left-to-right resolution -> ERR_RESOURCE_NOT_FOUND), §2.8 rungs 1-3.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_plan_payload,
    setup_reference_data,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §2.1 Auth — missing / malformed headers
# ===========================================================================
class TestAuthHeaders:
    """PRD §2.1: every request must carry X-User-ID and X-User-Role."""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "Missing or empty values for either header are
        rejected with ERR_UNAUTHENTICATED."

        Claim: a POST with neither header set returns
        ERR_UNAUTHENTICATED at HTTP 401.
        """
        res = api.create_plan(create_plan_payload(), headers={})
        validate_error(res, "ERR_UNAUTHENTICATED")

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "Missing or empty values for either header are
        rejected with ERR_UNAUTHENTICATED."

        Claim: omitting X-User-ID returns ERR_UNAUTHENTICATED.
        """
        res = api.create_plan(
            create_plan_payload(),
            headers={"X-User-Role": "PBMAdmin"},
        )
        validate_error(res, "ERR_UNAUTHENTICATED")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "Missing or empty values for either header are
        rejected with ERR_UNAUTHENTICATED."

        Claim: omitting X-User-Role returns ERR_UNAUTHENTICATED.
        """
        res = api.create_plan(
            create_plan_payload(),
            headers={"X-User-ID": "pbm-admin-001"},
        )
        validate_error(res, "ERR_UNAUTHENTICATED")

    def test_empty_user_id_rejected(self, api):
        """PRD §2.1: "Missing or empty values for either header are
        rejected with ERR_UNAUTHENTICATED."

        Claim: empty X-User-ID returns ERR_UNAUTHENTICATED.
        """
        res = api.create_plan(
            create_plan_payload(),
            headers={"X-User-ID": "", "X-User-Role": "PBMAdmin"},
        )
        validate_error(res, "ERR_UNAUTHENTICATED")

    def test_empty_user_role_rejected(self, api):
        """PRD §2.1: "Missing or empty values for either header are
        rejected with ERR_UNAUTHENTICATED."

        Claim: empty X-User-Role returns ERR_UNAUTHENTICATED.
        """
        res = api.create_plan(
            create_plan_payload(),
            headers={"X-User-ID": "pbm-admin-001", "X-User-Role": ""},
        )
        validate_error(res, "ERR_UNAUTHENTICATED")


# ===========================================================================
# §2.1 RBAC — wrong role
# ===========================================================================
class TestRoleAuthorization:
    """PRD §2.1: "When the headers are present but the supplied role
    is not authorized for the endpoint per §4 and §1.7 of this
    document, the request is rejected with ERR_FORBIDDEN.\""""

    def test_prescriber_cannot_create_plan(self, api, prescriber_headers):
        """PRD §4: POST /pbm/plans is exclusive to PBMAdmin.
        PRD §2.1: "the request is rejected with ERR_FORBIDDEN."

        Claim: Prescriber calling POST /pbm/plans returns ERR_FORBIDDEN.
        """
        res = api.create_plan(create_plan_payload(), prescriber_headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_clinical_reviewer_cannot_create_plan(
        self, api, clinical_reviewer_headers,
    ):
        """PRD §4: POST /pbm/plans is exclusive to PBMAdmin.
        PRD §2.1: "the request is rejected with ERR_FORBIDDEN."

        Claim: ClinicalReviewer calling POST /pbm/plans returns
        ERR_FORBIDDEN.
        """
        res = api.create_plan(
            create_plan_payload(), clinical_reviewer_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_claims_adjudicator_cannot_create_member(
        self, api, claims_adjudicator_headers,
    ):
        """PRD §4: POST /pbm/members is exclusive to PBMAdmin.
        PRD §2.1: ClaimsAdjudicator "Cannot review prior authorizations
        and cannot manage plans, drugs, or members."

        Claim: ClaimsAdjudicator calling POST /pbm/members returns
        ERR_FORBIDDEN.
        """
        res = api.create_member(
            {"plan_id": NON_EXISTENT_UUID,
             "full_name": "X", "date_of_birth": "1990-01-01"},
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_prescriber_cannot_adjudicate_claim(
        self, api, prescriber_headers,
    ):
        """PRD §4: POST /pbm/claims/{id}/adjudicate is exclusive to
        ClaimsAdjudicator.
        PRD §2.1: Prescriber "may not approve their own prior
        authorization (segregation of duties) and may not adjudicate
        claims."

        Claim: Prescriber calling adjudicate returns ERR_FORBIDDEN.
        """
        res = api.adjudicate_claim(
            NON_EXISTENT_UUID, {}, prescriber_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_clinical_reviewer_cannot_adjudicate_claim(
        self, api, clinical_reviewer_headers,
    ):
        """PRD §4: POST /pbm/claims/{id}/adjudicate is exclusive to
        ClaimsAdjudicator.
        PRD §2.1: ClinicalReviewer "cannot adjudicate claims."

        Claim: ClinicalReviewer calling adjudicate returns
        ERR_FORBIDDEN.
        """
        res = api.adjudicate_claim(
            NON_EXISTENT_UUID, {}, clinical_reviewer_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_pbm_admin_cannot_approve_prior_authorization(
        self, api, admin_headers,
    ):
        """PRD §4: POST /pbm/prior-authorizations/{id}/approve is
        exclusive to ClinicalReviewer.
        PRD §2.1: PBMAdmin "may not clinically review prior
        authorizations".

        Claim: PBMAdmin calling approve returns ERR_FORBIDDEN.
        """
        res = api.approve_prior_authorization(
            NON_EXISTENT_UUID, {}, admin_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_pbm_admin_cannot_create_prior_authorization(
        self, api, admin_headers,
    ):
        """PRD §4: POST /pbm/prior-authorizations is exclusive to
        Prescriber.
        PRD §2.1: PBMAdmin "may not clinically review prior
        authorizations and may not adjudicate or settle claims."
        PRD §3.3: PRD treats PA creation as a Prescriber-only
        operation.

        Claim: PBMAdmin calling POST /pbm/prior-authorizations returns
        ERR_FORBIDDEN.
        """
        res = api.create_prior_authorization(
            {"member_id": NON_EXISTENT_UUID,
             "drug_id": NON_EXISTENT_UUID,
             "prescriber_npi": "1234567890",
             "clinical_rationale": "..."},
            admin_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.2 Envelope shape
# ===========================================================================
class TestSuccessEnvelope:
    """PRD §2.2: every 2xx response carries
    {meta:{api_request_id, api_request_timestamp,...},
    response_type:"object"|"array", data:{...}}."""

    def test_success_envelope_keys_on_create(self, api, admin_headers):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body".

        Claim: POST /pbm/plans 201 carries meta+response_type+data.
        """
        res = api.create_plan(create_plan_payload(), admin_headers)
        assert res.status_code == 201
        body = res.json()
        assert "meta" in body and isinstance(body["meta"], dict)
        assert "response_type" in body
        assert body["response_type"] == "object"
        assert "data" in body
        meta = body["meta"]
        # PRD §2.2: api_request_id starts with "req_"; timestamp is
        # ISO 8601.
        assert isinstance(meta.get("api_request_id"), str)
        assert meta["api_request_id"].startswith("req_")
        assert isinstance(meta.get("api_request_timestamp"), str)

    def test_error_envelope_keys(self, api):
        """PRD §2.2: error responses use response_type "error" with
        data.error_id and data.message.

        Claim: ERR_UNAUTHENTICATED carries the documented shape.
        """
        res = api.create_plan(create_plan_payload(), headers={})
        body = res.json()
        assert body.get("response_type") == "error"
        assert "data" in body and isinstance(body["data"], dict)
        assert body["data"].get("error_id") == "ERR_UNAUTHENTICATED"
        assert isinstance(body["data"].get("message"), str)


# ===========================================================================
# §2.3 Pagination
# ===========================================================================
class TestPagination:
    """PRD §2.3: limit defaults to 10, min 1, max 100; offset default 0
    and min 0. Out-of-band -> ERR_VERSION_CONFLICT."""

    def test_list_returns_paginated_meta(self, api, admin_headers):
        """PRD §2.3: "Every paginated response includes the following
        fields in the meta envelope: limit, offset, total_count, and
        has_more."

        Claim: GET /pbm/plans includes all four meta fields.
        """
        # Make at least 2 rows.
        for _ in range(2):
            api.create_plan(create_plan_payload(), admin_headers)
        data, meta = validate_paginated(api.list_plans(admin_headers))
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta, f"missing meta.{key}: meta={meta}"
        assert meta["total_count"] >= 2

    def test_limit_above_max_rejected(self, api, admin_headers):
        """PRD §2.3: "Supplying a limit outside the band of 1 to 100,
        or an offset below 0, is rejected with ERR_VERSION_CONFLICT
        per the unified validation rule that covers list and patch
        endpoints."

        Claim: limit=101 returns ERR_VERSION_CONFLICT.
        """
        res = api.list_plans(admin_headers, params={"limit": 101})
        validate_error(res, "ERR_VERSION_CONFLICT")

    def test_limit_zero_rejected(self, api, admin_headers):
        """PRD §2.3: "Supplying a limit outside the band of 1 to 100,
        or an offset below 0, is rejected with ERR_VERSION_CONFLICT".

        Claim: limit=0 returns ERR_VERSION_CONFLICT.
        """
        res = api.list_plans(admin_headers, params={"limit": 0})
        validate_error(res, "ERR_VERSION_CONFLICT")

    def test_offset_negative_rejected(self, api, admin_headers):
        """PRD §2.3: "Supplying a limit outside the band of 1 to 100,
        or an offset below 0, is rejected with ERR_VERSION_CONFLICT".

        Claim: offset=-1 returns ERR_VERSION_CONFLICT.
        """
        res = api.list_plans(admin_headers, params={"offset": -1})
        validate_error(res, "ERR_VERSION_CONFLICT")

    def test_limit_offset_within_band_accepted(self, api, admin_headers):
        """PRD §2.3: limit and offset within the legal band are
        accepted; the response carries the supplied values back in
        meta.

        Claim: limit=1 returns at most 1 row.
        """
        for _ in range(3):
            api.create_plan(create_plan_payload(), admin_headers)
        data, meta = validate_paginated(
            api.list_plans(admin_headers, params={"limit": 1}),
        )
        assert len(data) <= 1


# ===========================================================================
# §2.7 NotFound — left-to-right resolution
# ===========================================================================
class TestResourceNotFound:
    """PRD §2.7: "The first identifier that fails to resolve causes
    the request to be rejected immediately with
    ERR_RESOURCE_NOT_FOUND, before any state check
    (ERR_INVALID_STATE) or business check (the 422-class errors) is
    evaluated.\""""

    def test_get_unknown_plan(self, api, admin_headers):
        """PRD §2.7: unknown ids resolve to ERR_RESOURCE_NOT_FOUND.

        Claim: GET /pbm/plans/{unknown} returns ERR_RESOURCE_NOT_FOUND.
        """
        res = api.get_plan(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, "ERR_RESOURCE_NOT_FOUND")

    def test_get_unknown_drug(self, api, admin_headers):
        """PRD §2.7: unknown ids resolve to ERR_RESOURCE_NOT_FOUND.

        Claim: GET /pbm/drugs/{unknown} returns
        ERR_RESOURCE_NOT_FOUND.
        """
        res = api.get_drug(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, "ERR_RESOURCE_NOT_FOUND")

    def test_get_unknown_member(self, api, admin_headers):
        """PRD §2.7: unknown ids resolve to ERR_RESOURCE_NOT_FOUND.

        Claim: GET /pbm/members/{unknown} returns
        ERR_RESOURCE_NOT_FOUND.
        """
        res = api.get_member(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, "ERR_RESOURCE_NOT_FOUND")

    def test_adjudicate_unknown_claim(
        self, api, claims_adjudicator_headers,
    ):
        """PRD §2.7: unknown path id returns ERR_RESOURCE_NOT_FOUND
        before any state or business check.

        Claim: adjudicate on unknown id returns
        ERR_RESOURCE_NOT_FOUND.
        """
        res = api.adjudicate_claim(
            NON_EXISTENT_UUID, {}, claims_adjudicator_headers,
        )
        validate_error(res, "ERR_RESOURCE_NOT_FOUND")

    def test_unknown_drug_id_on_create_member_via_unknown_plan(
        self, api, admin_headers,
    ):
        """PRD §2.7: "the system resolves every such identifier in
        left-to-right textual order before considering any state,
        business, or fiscal rule … the first identifier that fails to
        resolve causes the request to be rejected immediately with
        ERR_RESOURCE_NOT_FOUND".

        Claim: create_member with an unknown plan_id returns
        ERR_RESOURCE_NOT_FOUND.
        """
        res = api.create_member(
            {"plan_id": NON_EXISTENT_UUID, "full_name": "Y",
             "date_of_birth": "1990-01-01"},
            admin_headers,
        )
        validate_error(res, "ERR_RESOURCE_NOT_FOUND")

    def test_not_found_precedes_business_check(
        self, api, claims_adjudicator_headers,
    ):
        """PRD §2.7: "before any state check (ERR_INVALID_STATE) or
        business check (the 422-class errors) is evaluated".

        Claim: adjudicate on an unknown id surfaces
        ERR_RESOURCE_NOT_FOUND even though the resource has no state
        to check.
        """
        res = api.adjudicate_claim(
            NON_EXISTENT_UUID, {"version": 1},
            claims_adjudicator_headers,
        )
        validate_error(res, "ERR_RESOURCE_NOT_FOUND")


# ===========================================================================
# Cross-role probe — Prescriber may submit claims (shared op).
# ===========================================================================
class TestSharedOperations:
    """PRD §2.1 / §4: POST /pbm/claims is open to both Prescriber and
    ClaimsAdjudicator."""

    def test_prescriber_can_submit_claim(
        self, api, prescriber_headers,
    ):
        """PRD §4: "POST /pbm/claims … Prescriber, ClaimsAdjudicator".
        PRD §3.4: "A Prescriber or a ClaimsAdjudicator files a Claim".

        Claim: Prescriber calling POST /pbm/claims is accepted.
        """
        plan, drug, _, member = setup_reference_data()
        res = api.create_claim(
            {"member_id": member["id"], "drug_id": drug["id"],
             "channel": "RETAIL_30", "days_supply": 30, "quantity": 1},
            prescriber_headers,
        )
        validate_success(res, expected_status=201)

    def test_claims_adjudicator_can_submit_claim(
        self, api, claims_adjudicator_headers,
    ):
        """PRD §4: "POST /pbm/claims … Prescriber, ClaimsAdjudicator".

        Claim: ClaimsAdjudicator calling POST /pbm/claims is accepted.
        """
        plan, drug, _, member = setup_reference_data()
        res = api.create_claim(
            {"member_id": member["id"], "drug_id": drug["id"],
             "channel": "RETAIL_30", "days_supply": 30, "quantity": 1},
            claims_adjudicator_headers,
        )
        validate_success(res, expected_status=201)
