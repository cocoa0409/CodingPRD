"""Authentication, response envelope, and role-based access control.

Covers PRD §2.1 (auth headers, role recognition, segregation of
duties, borrower ownership), §2.2 (success / error envelope), §2.3
(pagination), §2.4 (common fields), and §2.10 (validation ordering
for auth).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    activate_heloc_payload,
    api_client,
    build_user_headers,
    create_borrower,
    create_borrower_payload,
    create_heloc_payload,
    create_property_payload,
    create_senior_lien_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_borrower_headers,
    setup_active_heloc,
    setup_active_heloc_with_balance,
    setup_borrower_property_lien,
    setup_pending_heloc,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §2.2 Response envelope
# ===========================================================================
class TestSuccessEnvelope:

    def test_success_envelope_shape(self, api, originator_headers):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body" — meta.api_request_id starting with req_,
        api_request_timestamp ISO 8601, response_type, data.
        """
        resp = api.create_borrower(
            create_borrower_payload(), originator_headers,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "meta" in body
        meta = body["meta"]
        assert "api_request_id" in meta
        # PRD §2.2: "The api_request_id is a server-generated unique
        # identifier for the request that starts with req_."
        assert isinstance(meta["api_request_id"], str)
        assert meta["api_request_id"].startswith("req_"), (
            f"api_request_id must start with req_, got "
            f"{meta['api_request_id']!r}"
        )
        # PRD §2.2: "The api_request_timestamp is a server-generated
        # ISO 8601 UTC timestamp with three fractional digits."
        assert is_iso8601_timestamp(meta["api_request_timestamp"])
        # PRD §2.2: "The `response_type` is either "object" for a
        # single resource or "array" for a list of resources."
        assert body["response_type"] == "object"
        assert isinstance(body["data"], dict)

    def test_error_envelope_shape(self, api, originator_headers):
        """PRD §2.2: "All error API responses (4xx status codes) follow
        this standard envelope format ... data { error_id ..., message ... }."
        """
        resp = api.get_borrower(NON_EXISTENT_UUID, originator_headers)
        assert resp.status_code == 404
        body = resp.json()
        assert "meta" in body
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_RESOURCE_NOT_FOUND"
        assert isinstance(body["data"].get("message"), str)


# ===========================================================================
# §2.4 Common resource properties: server-minted UUID, ISO timestamps,
# version starts at 1
# ===========================================================================
class TestCommonResourceFields:

    def test_borrower_id_is_uuid_and_version_is_one(
        self, api, originator_headers,
    ):
        """PRD §2.4: "The id is a server-minted UUID (no type prefix) that
        uniquely identifies the resource."
        PRD §2.4: "The version field is an integer that begins at 1 on
        creation and increments by exactly one with every mutation to
        the resource."
        """
        b = validate_success(api.create_borrower(
            create_borrower_payload(), originator_headers,
        ), 201)
        assert is_valid_uuid(b["id"])
        assert b["version"] == 1
        assert is_iso8601_timestamp(b["created_at"])
        assert is_iso8601_timestamp(b["updated_at"])

    def test_ledger_entry_omits_updated_at_and_version(
        self, api,
    ):
        """PRD §2.4: "ledger-style child resources of a HELOC — Draw,
        Payment, RateReset, Fee, DefaultEvent — and the audit-log
        entities ... do not carry updated_at or version — both fields
        are absent from their responses because no in-place mutation
        is ever performed on them."
        """
        borrower, _, _, heloc = setup_active_heloc()
        # Take a draw via the borrower's own header (ownership-gated).
        draw_resp = api.create_draw(
            heloc["id"],
            {"amount_cents": 50_000},
            make_borrower_headers(borrower["id"]),
        )
        draw = validate_success(draw_resp, 201)
        assert is_valid_uuid(draw["id"])
        assert "created_at" in draw
        assert "updated_at" not in draw, (
            "Draw is an immutable ledger entry — must omit updated_at"
        )
        assert "version" not in draw, (
            "Draw is an immutable ledger entry — must omit version"
        )


# ===========================================================================
# §2.1 Auth header validation
# ===========================================================================
class TestAuthHeaders:

    def test_missing_user_id_returns_missing_auth(self, api):
        """PRD §2.1: "Every request to the API must carry two HTTP
        headers: X-User-ID, identifying the acting user, and
        X-User-Role, identifying their operational capacity. If either
        header is missing or empty, the request is rejected with
        ERR_MISSING_AUTH."
        """
        resp = api.create_borrower(
            create_borrower_payload(),
            headers={"X-User-Role": "Originator"},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)

    def test_missing_user_role_returns_missing_auth(self, api):
        """PRD §2.1: "If either header is missing or empty, the
        request is rejected with ERR_MISSING_AUTH."
        """
        resp = api.create_borrower(
            create_borrower_payload(),
            headers={"X-User-ID": "x"},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)

    @pytest.mark.parametrize(
        "user_id,role",
        [
            ("", "Originator"),
            ("x", ""),
        ],
        ids=["empty-user-id", "empty-role"],
    )
    def test_empty_auth_header_returns_missing_auth(
        self, api, user_id, role,
    ):
        """PRD §2.1: "If either header is missing or empty, the
        request is rejected with ERR_MISSING_AUTH."
        """
        resp = api.create_borrower(
            create_borrower_payload(),
            headers={"X-User-ID": user_id, "X-User-Role": role},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)

    def test_unknown_role_rejected(self, api):
        """PRD §2.1: "If X-User-Role is supplied but is not one of the
        four recognized values, the request is rejected with
        ERR_UNKNOWN_ROLE."
        """
        resp = api.create_borrower(
            create_borrower_payload(),
            headers=build_user_headers("x", "Wizard"),
        )
        validate_error(resp, ApiErrorId.ERR_UNKNOWN_ROLE.value)


# ===========================================================================
# §2.1, §2.10 Role-based authorization gates
# ===========================================================================
class TestRoleAuthorization:

    def test_borrower_cannot_create_heloc(
        self, api, borrower_fallback_headers,
    ):
        """PRD §4: POST /helocs is authorized to "Originator,
        PlatformAdmin"; Borrower is not in the grant.
        PRD §2.1: "Any attempt by a non-authorized role to invoke an
        endpoint outside its grant is rejected with ERR_FORBIDDEN".
        """
        # Build a real borrower + property + senior lien first as
        # opaque setup. The Borrower-acting forbidden test does not
        # need its user-id to match the body, since the role check
        # fires before any ownership check.
        borrower, prop, _ = setup_borrower_property_lien()
        resp = api.create_heloc(
            create_heloc_payload(
                borrower_id=borrower["id"], property_id=prop["id"],
            ),
            make_borrower_headers(borrower["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_originator_cannot_post_payment(self, api, originator_headers):
        """PRD §4: POST /helocs/{id}/payments is authorized to
        "Borrower, Servicer, PlatformAdmin"; Originator is not.
        PRD §2.1: "Any attempt by a non-authorized role to invoke an
        endpoint outside its grant is rejected with ERR_FORBIDDEN".
        """
        _, _, _, heloc, _ = setup_active_heloc_with_balance(
            draw_amount_cents=100_000,
        )
        resp = api.create_payment(
            heloc["id"], {"amount_cents": 1000},
            originator_headers,
        )
        # Originator on a Servicer-shared endpoint: PRD §2.1
        # segregation of duties rule.
        assert resp.status_code == 403, (
            f"expected 403 from forbidden role, got {resp.status_code}"
        )
        assert resp.json()["data"]["error_id"] in {
            ApiErrorId.ERR_FORBIDDEN.value,
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        }

    def test_originator_cannot_close_heloc_segregation_of_duties(
        self, api, originator_headers,
    ):
        """PRD §2.1: "any attempt by an Originator to invoke an
        operation reserved to the Servicer (or any equivalent crossing
        of the originate/service boundary) yields the more specific
        ERR_SEGREGATION_OF_DUTIES."
        PRD §4: POST /helocs/{id}/close is authorized to "Servicer,
        Borrower, PlatformAdmin"; Originator is not — and an
        Originator attempting it crosses the originate/service
        boundary, so the rule pins ERR_SEGREGATION_OF_DUTIES.
        """
        _, _, _, heloc = setup_active_heloc()
        resp = api.close_heloc(heloc["id"], originator_headers)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_originator_cannot_create_rate_reset_segregation(
        self, api, originator_headers,
    ):
        """PRD §4: POST /helocs/{id}/rate-resets is "Servicer,
        PlatformAdmin"; not Originator.
        PRD §2.1: "any attempt by an Originator to invoke an operation
        reserved to the Servicer (or any equivalent crossing of the
        originate/service boundary) yields the more specific
        ERR_SEGREGATION_OF_DUTIES."
        """
        _, _, _, heloc = setup_active_heloc()
        resp = api.create_rate_reset(
            heloc["id"], {"prime_rate_bps": 500}, originator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_originator_cannot_record_bankruptcy_event_segregation(
        self, api, originator_headers,
    ):
        """PRD §4: POST /borrowers/{id}/bankruptcy-events is
        "Servicer, PlatformAdmin"; not Originator.
        PRD §2.1: "any attempt by an Originator to invoke an operation
        reserved to the Servicer (or any equivalent crossing of the
        originate/service boundary) yields the more specific
        ERR_SEGREGATION_OF_DUTIES."
        """
        borrower, _, _ = setup_borrower_property_lien()
        resp = api.create_bankruptcy_event(
            borrower["id"], originator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_servicer_cannot_create_heloc(self, api, servicer_headers):
        """PRD §4: POST /helocs is authorized to "Originator,
        PlatformAdmin"; Servicer is not.
        PRD §2.1: "The Servicer role handles in-life servicing but may
        not originate new HELOCs."
        """
        borrower, prop, _ = setup_borrower_property_lien()
        resp = api.create_heloc(
            create_heloc_payload(
                borrower_id=borrower["id"], property_id=prop["id"],
            ),
            servicer_headers,
        )
        assert resp.status_code == 403, (
            f"Servicer must not originate, got {resp.status_code}"
        )

    def test_non_admin_cannot_advance_clock(self, api, servicer_headers):
        """PRD §4: POST /_clock/advance is "PlatformAdmin" only.
        PRD §2.1: "The PlatformAdmin role is a superuser that may
        invoke any endpoint, including the administrative
        clock-advance and sweep capabilities".
        """
        resp = api.clock_advance({"seconds": 100}, servicer_headers)
        assert resp.status_code == 403

    def test_non_admin_cannot_run_billing_cycle_sweep(
        self, api, servicer_headers,
    ):
        """PRD §4: POST /_sweep/billing-cycle is PlatformAdmin only."""
        resp = api.sweep_billing_cycle(servicer_headers)
        assert resp.status_code == 403

    def test_non_admin_cannot_run_annual_fees_sweep(
        self, api, servicer_headers,
    ):
        """PRD §4: POST /_sweep/annual-fees is PlatformAdmin only."""
        resp = api.sweep_annual_fees(servicer_headers)
        assert resp.status_code == 403


# ===========================================================================
# §2.1 / §3.10 Borrower entity-backed ownership
# ===========================================================================
class TestBorrowerOwnership:

    def test_borrower_reads_own_heloc(self, api):
        """PRD §3.10: "When the acting role is Borrower, however, the
        server additionally enforces the identity rule from §2.1: the
        borrower's X-User-ID must match the resource's owning
        borrower_id, traversing the chain from the resource back to
        its owning borrower".
        """
        borrower, _, _, heloc = setup_active_heloc()
        resp = api.get_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        data = validate_success(resp, 200)
        assert data["id"] == heloc["id"]
        assert data["borrower_id"] == borrower["id"]

    def test_borrower_reading_other_borrowers_heloc_forbidden(self, api):
        """PRD §3.10: "A borrower reading another borrower's resource
        is rejected with ERR_FORBIDDEN."
        """
        owner, _, _, heloc = setup_active_heloc()
        stranger, _, _ = setup_borrower_property_lien()
        assert stranger["id"] != owner["id"]
        resp = api.get_heloc(
            heloc["id"], make_borrower_headers(stranger["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_borrower_reading_other_borrowers_property_forbidden(
        self, api,
    ):
        """PRD §3.10: "A borrower reading another borrower's resource
        is rejected with ERR_FORBIDDEN."
        """
        owner, prop, _ = setup_borrower_property_lien()
        stranger = create_borrower()
        assert stranger["id"] != owner["id"]
        resp = api.get_property(
            prop["id"], make_borrower_headers(stranger["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# §2.3 Pagination
# ===========================================================================
class TestPagination:

    def test_list_helocs_pagination_defaults(
        self, api, originator_headers,
    ):
        """PRD §2.3: "The limit parameter caps the number of items in
        the response; if omitted it defaults to 10".
        PRD §2.3: "Paginated responses include the fields limit,
        offset, total_count, and has_more inside the meta object of
        the envelope."
        """
        # Create three HELOCs.
        for _ in range(3):
            setup_pending_heloc()
        resp = api.list_helocs(originator_headers)
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] >= 3
        # has_more is false when total_count <= limit + offset.
        assert isinstance(meta["has_more"], bool)

    def test_list_helocs_limit_one_pagination(
        self, api, originator_headers,
    ):
        """PRD §2.3: "The limit parameter caps the number of items in
        the response; if omitted it defaults to 10, with a minimum of
        1 and a maximum of 100."
        """
        for _ in range(3):
            setup_pending_heloc()
        resp = api.list_helocs(
            originator_headers, params={"limit": 1, "offset": 0},
        )
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert meta["limit"] == 1
        assert meta["has_more"] is True


# ===========================================================================
# Existence (§2.7 left-to-right + body FK)
# ===========================================================================
class TestExistence:

    def test_get_nonexistent_borrower_returns_not_found(
        self, api, originator_headers,
    ):
        """PRD §2.7: "The first identifier in the path that does not
        match an existing resource immediately yields
        ERR_RESOURCE_NOT_FOUND, and validation does not continue past
        that point."
        """
        resp = api.get_borrower(NON_EXISTENT_UUID, originator_headers)
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)

    def test_heloc_body_with_nonexistent_borrower_returns_not_found(
        self, api, originator_headers,
    ):
        """PRD §2.7: "The same ERR_RESOURCE_NOT_FOUND is also returned
        when a foreign-key identifier supplied in a request body (such
        as a borrower_id, property_id, or heloc_id) does not refer to
        an existing resource; this body-level existence check applies
        on HELOC creation".
        """
        _, prop, _ = setup_borrower_property_lien()
        resp = api.create_heloc(
            create_heloc_payload(
                borrower_id=NON_EXISTENT_UUID,
                property_id=prop["id"],
            ),
            originator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)

    def test_heloc_body_with_nonexistent_property_returns_not_found(
        self, api, originator_headers,
    ):
        """PRD §2.7: "The same ERR_RESOURCE_NOT_FOUND is also returned
        when a foreign-key identifier supplied in a request body ...
        does not refer to an existing resource; this body-level
        existence check applies on HELOC creation, property and
        senior-lien registration, and all child-collection writes
        (draws, payments, rate resets)."
        """
        borrower, _, _ = setup_borrower_property_lien()
        resp = api.create_heloc(
            create_heloc_payload(
                borrower_id=borrower["id"],
                property_id=NON_EXISTENT_UUID,
            ),
            originator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)
