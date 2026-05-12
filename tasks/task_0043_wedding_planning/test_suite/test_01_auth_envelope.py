"""Authentication, RBAC, response envelope, pagination, terminal-status
guard, and nested-path existence checks. Covers PRD §2.1, §2.2, §2.3,
§2.4, §2.7, §2.9.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_project_payload,
    setup_project_in_planning,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §2.1 -- Headers must be present and non-empty.
# ===========================================================================
class TestMissingAuthHeaders:

    def test_missing_user_id_header(self, api):
        """PRD §2.1: "If either header is missing or empty, the request is
        rejected with ERR_MISSING_AUTH_HEADERS (HTTP 401)."

        Claim: missing X-User-ID -> ERR_MISSING_AUTH_HEADERS / 401.
        """
        bad = {"X-User-Role": "Planner", "Content-Type": "application/json"}
        res = api._request("GET", "/wedding-projects", headers=bad)
        validate_error(res, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value)

    def test_missing_user_role_header(self, api):
        """PRD §2.1: "If either header is missing or empty, the request is
        rejected with ERR_MISSING_AUTH_HEADERS (HTTP 401)."

        Claim: missing X-User-Role -> ERR_MISSING_AUTH_HEADERS / 401.
        """
        bad = {"X-User-ID": "planner-001", "Content-Type": "application/json"}
        res = api._request("GET", "/wedding-projects", headers=bad)
        validate_error(res, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value)

    def test_empty_user_id_header(self, api):
        """PRD §2.1: "If either header is missing or empty, the request is
        rejected with ERR_MISSING_AUTH_HEADERS (HTTP 401)."

        Claim: empty X-User-ID -> ERR_MISSING_AUTH_HEADERS / 401.
        """
        bad = {"X-User-ID": "", "X-User-Role": "Planner",
               "Content-Type": "application/json"}
        res = api._request("GET", "/wedding-projects", headers=bad)
        validate_error(res, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value)

    def test_empty_user_role_header(self, api):
        """PRD §2.1: "If either header is missing or empty, the request is
        rejected with ERR_MISSING_AUTH_HEADERS (HTTP 401)."

        Claim: empty X-User-Role -> ERR_MISSING_AUTH_HEADERS / 401.
        """
        bad = {"X-User-ID": "planner-001", "X-User-Role": "",
               "Content-Type": "application/json"}
        res = api._request("GET", "/wedding-projects", headers=bad)
        validate_error(res, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value)


class TestInvalidRole:

    @pytest.mark.parametrize("bad_role", ["Admin", "ROOT", "planner",
                                          "vendor_rep", "Unknown"])
    def test_unrecognized_role_value(self, api, bad_role):
        """PRD §2.1: "If X-User-Role is not one of the four recognized
        strings -- Planner, VendorRep, Couple, Auditor -- the request is
        rejected with ERR_INVALID_ROLE (HTTP 401)."

        Claim: X-User-Role outside the recognized set -> ERR_INVALID_ROLE / 401.
        """
        bad = {"X-User-ID": "u-001", "X-User-Role": bad_role,
               "Content-Type": "application/json"}
        res = api._request("GET", "/wedding-projects", headers=bad)
        validate_error(res, ApiErrorId.ERR_INVALID_ROLE.value)


# ===========================================================================
# §2.1 -- RBAC role-not-authorised yields the appropriate error.
# ===========================================================================
class TestRoleAuthorization:

    def test_couple_cannot_create_project(self, api, couple_headers):
        """PRD §4: POST /wedding-projects is authorized to Planner only.
        PRD §2.1: "A request whose role is otherwise authenticated but lacks
        permission for the specific endpoint receives ERR_AUDITOR_REQUIRED,
        ERR_NOT_OWNING_PLANNER, or ERR_NOT_OWNING_VENDOR as appropriate to
        the failed check."

        Claim: Couple POST /wedding-projects -> ERR_NOT_OWNING_PLANNER / 403.
        """
        res = api.create_project(create_project_payload(), couple_headers)
        validate_error(res, ApiErrorId.ERR_NOT_OWNING_PLANNER.value)

    def test_vendor_rep_cannot_create_project(
        self, api, vendor_rep_headers_fallback
    ):
        """PRD §4: POST /wedding-projects is authorized to Planner only.

        Claim: VendorRep POST /wedding-projects -> ERR_NOT_OWNING_PLANNER / 403.
        """
        res = api.create_project(
            create_project_payload(), vendor_rep_headers_fallback
        )
        validate_error(res, ApiErrorId.ERR_NOT_OWNING_PLANNER.value)


class TestAuditorOwnership:

    def test_close_with_wrong_auditor_id(self, api, planner_headers):
        """PRD §2.1: "To close a project, the acting auditor's X-User-ID
        MUST equal WeddingProject.auditor_user_id; otherwise the request
        is rejected with ERR_AUDITOR_REQUIRED (HTTP 403)."

        Claim: Auditor whose X-User-ID != project.auditor_user_id close attempt
        -> ERR_AUDITOR_REQUIRED / 403.
        """
        from test_helpers import build_user_headers
        from test_helpers import (
            setup_project_in_settlement_with_one_finalized_and_one_terminated,
        )
        # Need project in SETTLEMENT with all contracts FINALIZED-or-TERMINATED;
        # then call close with an auditor id NOT recorded as auditor_user_id.
        project, _venue, _terminated = (
            setup_project_in_settlement_with_one_finalized_and_one_terminated()
        )
        wrong_auditor = build_user_headers("auditor-WRONG-9999", "Auditor")
        res = api.close_project(project["id"], wrong_auditor)
        validate_error(res, ApiErrorId.ERR_AUDITOR_REQUIRED.value)


class TestPlannerOwnership:

    def test_other_planner_cannot_activate_project(self, api,
                                                   planner_headers_alt):
        """PRD §2.1: "Project ownership is enforced by string-equality
        between X-User-ID and WeddingProject.planner_user_id. A planner
        who is not the owner of the project named in the URL receives
        ERR_NOT_OWNING_PLANNER (HTTP 403)."

        Claim: Planner whose X-User-ID != project.planner_user_id calling
        activate -> ERR_NOT_OWNING_PLANNER / 403.
        """
        from test_helpers import create_project, add_full_milestones, PLANNER_ID
        # Owner is PLANNER_ID; the alt headers carry a different opaque id.
        project = create_project(planner_id=PLANNER_ID)
        add_full_milestones(project["id"], planner_id=PLANNER_ID)
        res = api.activate_project(project["id"], planner_headers_alt)
        validate_error(res, ApiErrorId.ERR_NOT_OWNING_PLANNER.value)


class TestVendorOwnership:

    def test_other_vendor_rep_cannot_create_quote(self, api):
        """PRD §2.1: "vendor-rep ownership checks compare X-User-ID directly
        to the vendor_id of the resource being acted upon ... A vendor
        representative attempting an action on a vendor that is not their
        own is rejected with ERR_NOT_OWNING_VENDOR (HTTP 403)."

        Claim: VendorRep whose X-User-ID != Vendor.id calling POST
        /vendors/{vid}/quotes -> ERR_NOT_OWNING_VENDOR / 403.
        """
        from test_helpers import (
            create_approved_vendor,
            create_quote_payload,
            make_vendor_rep_headers,
        )
        vendor = create_approved_vendor(category="PHOTOGRAPHY")
        # An entirely different vendor-rep identity. Vendor.id is a UUID;
        # NON_EXISTENT_UUID is guaranteed not to equal it.
        other_vrep = make_vendor_rep_headers(NON_EXISTENT_UUID)
        res = api.create_quote(
            vendor["id"],
            create_quote_payload(amount_cents=100_000),
            other_vrep,
        )
        validate_error(res, ApiErrorId.ERR_NOT_OWNING_VENDOR.value)


# ===========================================================================
# §2.2 -- Response envelope shape on success and error.
# ===========================================================================
class TestResponseEnvelope:

    def test_success_envelope_shape(self, api, planner_headers):
        """PRD §2.2: success body carries meta (api_request_id starting
        req_, api_request_timestamp ISO 8601), response_type in
        ('object','array'), and data.

        Claim: GET /wedding-projects returns the standard success envelope.
        """
        res = api.list_projects(planner_headers, params={"limit": 1})
        body = res.json()
        assert "meta" in body
        assert "response_type" in body
        assert "data" in body
        assert body["response_type"] in ("object", "array")
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str)
        assert meta["api_request_id"].startswith("req_")
        assert isinstance(meta.get("api_request_timestamp"), str)

    def test_error_envelope_shape_on_404(self, api, planner_headers):
        """PRD §2.2: error body carries response_type='error' and data
        with error_id + message. PRD §2.7: missing project -> ERR_PROJECT_NOT_FOUND.

        Claim: GET nonexistent project -> error envelope with non-empty message.
        """
        res = api.get_project(NON_EXISTENT_UUID, planner_headers)
        body = res.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["error_id"], str)
        assert isinstance(body["data"]["message"], str)
        assert len(body["data"]["message"].strip()) > 0


# ===========================================================================
# §2.3 -- Pagination defaults.
# ===========================================================================
class TestPagination:

    def test_default_pagination_block(self, api, planner_headers):
        """PRD §2.3: "The default limit is 10, the minimum is 1, and the
        maximum is 100; the default offset is 0."

        Claim: list response without limit/offset returns meta with
        limit=10, offset=0.
        """
        res = api.list_projects(planner_headers)
        _data, meta = validate_paginated(res)
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert "total_count" in meta
        assert "has_more" in meta

    def test_pagination_filter_respects_offset(self, api, planner_headers):
        """PRD §2.3: "The pagination block in meta exposes four fields --
        limit (the effective limit applied), offset (the effective offset
        applied), total_count (the total number of records matching any
        filter applied to the list call), and has_more (true when offset +
        limit < total_count)."

        Claim: explicit limit=2 offset=0 -> meta.limit==2, meta.offset==0.
        """
        # Create three projects so offset works.
        for _ in range(3):
            setup_project_in_planning()
        res = api.list_projects(
            planner_headers, params={"limit": 2, "offset": 0}
        )
        _data, meta = validate_paginated(res)
        assert meta["limit"] == 2
        assert meta["offset"] == 0


# ===========================================================================
# §2.7 -- Hierarchical path resolution: left-to-right checks.
# ===========================================================================
class TestNestedPathExistence:

    def test_project_not_found_short_circuits(self, api, planner_headers):
        """PRD §2.7: "The projectId is checked first; if no WeddingProject
        with that id exists, the response is ERR_PROJECT_NOT_FOUND (HTTP
        404), and no further segment is examined."

        Claim: GET /wedding-projects/{NON_EXISTENT}/contracts/{NON_EXISTENT}
        returns ERR_PROJECT_NOT_FOUND (NOT ERR_CONTRACT_NOT_FOUND).
        """
        res = api.get_contract(NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                               planner_headers)
        validate_error(res, ApiErrorId.ERR_PROJECT_NOT_FOUND.value)

    def test_contract_not_found_under_real_project(self, api, planner_headers):
        """PRD §2.7: "The contractId is checked next, and the contract must
        belong to the resolved project; otherwise ERR_CONTRACT_NOT_FOUND
        (HTTP 404)."

        Claim: real project id + bogus contract id -> ERR_CONTRACT_NOT_FOUND.
        """
        project = setup_project_in_planning()
        res = api.get_contract(project["id"], NON_EXISTENT_UUID,
                               planner_headers)
        validate_error(res, ApiErrorId.ERR_CONTRACT_NOT_FOUND.value)


# ===========================================================================
# §2.7 -- Project-terminal guard.
# ===========================================================================
class TestProjectTerminalGuard:

    def test_cancelled_project_blocks_mutation(self, api, planner_headers):
        """PRD §2.7: "Once a WeddingProject reaches a terminal status of
        CLOSED or CANCELLED, every mutating endpoint nested under that
        project is rejected with ERR_PROJECT_TERMINAL (HTTP 409),
        regardless of role."

        Claim: cancel a DRAFT project -> CANCELLED, then attempt to add a
        guest -> ERR_PROJECT_TERMINAL / 409.
        """
        from test_helpers import create_project, create_guest_payload
        project = create_project()
        cancel_resp = api.cancel_project(project["id"], planner_headers)
        validate_success(cancel_resp)

        res = api.create_guest(
            project["id"],
            create_guest_payload(full_name="Late Guest"),
            planner_headers,
        )
        validate_error(res, ApiErrorId.ERR_PROJECT_TERMINAL.value)


# ===========================================================================
# §2.4 -- Common resource fields and append-only shape.
# ===========================================================================
class TestCommonFields:

    def test_wedding_project_carries_versioned_fields(self, api,
                                                     planner_headers):
        """PRD §2.4: WeddingProject is in the list of resources that "carry
        three additional system fields: created_at and updated_at, both ISO
        8601 UTC timestamps with three fractional digits, and version, an
        integer that begins at 1 on creation and is incremented by exactly
        1 on every server-side mutation."

        Claim: a fresh project carries created_at, updated_at, version=1.
        """
        from test_helpers import (
            assert_wedding_project,
            create_project_payload,
        )
        res = api.create_project(create_project_payload(), planner_headers)
        data = validate_success(res, expected_status=201)
        assert_wedding_project(data)
        assert data["version"] == 1, (
            "PRD §2.4: version begins at 1 on creation"
        )
