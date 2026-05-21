"""Auth headers, role-based access control, response envelope shape.

Covers PRD §2.1 (auth), §2.2 (envelope), §2.3 (pagination), §2.7
(left-to-right path validation), §2.10 (validation priority — auth
beats existence which beats state).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_claimant_payload,
    create_employer,
    create_eligible_claim,
    make_claimant_headers,
    make_employer_agent_headers,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


class TestAuthHeaders:

    def test_missing_both_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "If either header is missing or unrecognised, the
        request is rejected with ERR_UNAUTHENTICATED."

        Claim: GET with empty headers -> ERR_UNAUTHENTICATED.
        """
        resp = api._request("GET", "/_clock", headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_user_id_returns_unauthenticated(self, api):
        """PRD §2.1: "If either header is missing or unrecognised, the
        request is rejected with ERR_UNAUTHENTICATED."
        """
        resp = api._request(
            "GET", "/_clock", headers={"X-User-Role": "SystemAdmin"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_user_role_returns_unauthenticated(self, api):
        """PRD §2.1: "If either header is missing or unrecognised, the
        request is rejected with ERR_UNAUTHENTICATED."
        """
        resp = api._request(
            "GET", "/_clock", headers={"X-User-ID": "anyone"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    @pytest.mark.parametrize("role", [
        "Claimant", "Adjudicator", "AppealOfficer",
        "EmployerAgent", "SystemAdmin",
    ])
    def test_each_of_five_roles_clears_auth_stage(self, api, role):
        """PRD §2.1: "The five roles are exactly: Claimant ...
        Adjudicator ... AppealOfficer ... EmployerAgent ...
        SystemAdmin."

        Claim: each of the five accepted role values clears the auth
        gate (the response, whatever it is, is NOT ERR_UNAUTHENTICATED).
        """
        headers = build_user_headers(f"user-{role.lower()}-probe", role)
        resp = api._request("GET", "/_clock", headers=headers)
        try:
            body = resp.json()
            err = body.get("data", {}).get("error_id")
        except Exception:
            err = None
        assert err != ApiErrorId.ERR_UNAUTHENTICATED.value, (
            f"role {role!r} should clear auth gate; got "
            f"ERR_UNAUTHENTICATED. Response: {body}"
        )

    def test_unknown_role_returns_unauthenticated(self, api):
        """PRD §2.1: "If either header is missing or unrecognised, the
        request is rejected with ERR_UNAUTHENTICATED."

        A role string outside the five-value catalogue is unrecognised
        at the auth stage.
        """
        bad_headers = build_user_headers("user-x", "Janitor")
        resp = api._request("GET", "/_clock", headers=bad_headers)
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            ApiErrorId.ERR_FORBIDDEN.value,
        ])


class TestRoleBasedAccessControl:

    def test_claimant_cannot_register_employer(self, api):
        """PRD §4: "POST /employers ... Authorized Role(s): SystemAdmin."
        PRD §2.1: "If the named role is not permitted by the
        per-endpoint role matrix in §4, the request is rejected with
        ERR_FORBIDDEN."
        """
        resp = api.create_employer(
            {"ein": "123456789", "legal_name": "X",
             "reserve_ratio_basis_cents": 1_000_000,
             "taxable_payroll_cents": 10_000_000},
            TEST_USERS["claimant_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_claimant_cannot_create_wage_record(self, api):
        """PRD §4: "POST /claimants/{cid}/wage-records ... Authorized
        Role(s): SystemAdmin."
        PRD §3.1: "Quarterly wage records are admin-filed and immutable
        once written."
        """
        from test_helpers import create_claimant
        claimant = create_claimant()
        resp = api.create_wage_record(
            claimant["id"],
            {"employer_id": NON_EXISTENT_UUID, "quarter_year": 2024,
             "quarter_index": 1, "wages_cents": 100_000},
            make_claimant_headers(claimant["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_employer_agent_cannot_create_claimant(self, api):
        """PRD §4: "POST /claimants ... Authorized Role(s): SystemAdmin,
        Claimant."

        EmployerAgent is not in the role list.
        """
        resp = api.create_claimant(
            create_claimant_payload(),
            TEST_USERS["employer_agent_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestSuccessEnvelope:

    def test_get_clock_envelope_structure(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body."
        """
        resp = api.get_clock(TEST_USERS["system_admin_headers"])
        data = validate_success(resp, expected_status=200)
        assert "now" in data, f"SystemClock response missing 'now': {data}"


class TestPagination:

    def test_list_wage_records_paginated_envelope(self, api):
        """PRD §2.3: "The pagination context returned in `meta` consists
        of `limit`, `offset`, `total_count`, and `has_more`."
        """
        from test_helpers import create_claimant
        claimant = create_claimant()
        resp = api.list_wage_records(
            claimant["id"], TEST_USERS["system_admin_headers"],
        )
        data, meta = validate_paginated(resp)
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta, f"meta missing '{key}': {meta}"

    @pytest.mark.parametrize("bad_limit", [0, 101, -1])
    def test_pagination_limit_out_of_range_rejected(self, api, bad_limit):
        """PRD §2.3: "any integer from 1 up to 100 inclusive ...
        Any value outside these ranges is rejected with
        ERR_VALIDATION_FAILED."
        """
        from test_helpers import create_claimant
        claimant = create_claimant()
        resp = api.list_wage_records(
            claimant["id"], TEST_USERS["system_admin_headers"],
            params={"limit": bad_limit},
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED.value)

    def test_pagination_negative_offset_rejected(self, api):
        """PRD §2.3: "The default offset is 0 and must be a non-negative
        integer. Any value outside these ranges is rejected with
        ERR_VALIDATION_FAILED."
        """
        from test_helpers import create_claimant
        claimant = create_claimant()
        resp = api.list_wage_records(
            claimant["id"], TEST_USERS["system_admin_headers"],
            params={"offset": -1},
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED.value)


class TestLeftToRightPathValidation:

    def test_nonexistent_claimant_in_wage_record_path_is_not_found(self, api):
        """PRD §2.7: "URL paths are validated left to right. When an
        endpoint targets a nested resource ... the parent identifier is
        resolved first and a non-existent parent produces ERR_NOT_FOUND
        before any further check."
        """
        resp = api.list_wage_records(
            NON_EXISTENT_UUID, TEST_USERS["system_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestOwnershipChecks:

    def test_claimant_cannot_submit_anothers_claim(self, api):
        """PRD §2.1: "Ownership checks on any resource that references
        a Claimant (a Claim, a WeeklyCertification, an Overpayment, an
        Appeal) compare the resource's owning claimant_id (resolved
        through the Claim if necessary) to X-User-ID. A mismatch yields
        ERR_NOT_OWNER."
        """
        bundle = create_eligible_claim()
        intruder_headers = build_user_headers(
            "claimant-intruder-XXX", "Claimant",
        )
        # Issue another submit as a different claimant_id.
        resp = api.submit_claim(bundle["claim"]["id"], intruder_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_OWNER.value)

    def test_employer_agent_cannot_read_anothers_charges(self, api):
        """PRD §2.1: "Ownership checks on any resource that references
        an Employer (notably EmployerCharge lists and the relief
        endpoint) compare the resource's employer_id to X-User-ID."
        """
        emp = create_employer()
        intruder_headers = make_employer_agent_headers(NON_EXISTENT_UUID)
        resp = api.list_employer_charges(emp["id"], intruder_headers)
        # The intruder's X-User-ID is a UUID-shaped id that does not
        # equal the real employer's id; the server first resolves the
        # employer (exists), then checks ownership.
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_NOT_OWNER.value,
            ApiErrorId.ERR_FORBIDDEN.value,
        ])
