"""Platform-wide conventions: response envelope, 404 family, auth, pagination,
and left-to-right path-existence ordering (PRD §2.1, §2.2, §2.3, §2.5)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    new_account,
    new_manifest,
    set_clock,
    setup_triaged_item,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestResponseEnvelope:
    def test_success_envelope_carries_meta_and_object_type(self, api, platform_admin_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

        Design: Corner/endpoints/response_envelope_meta_present
        """
        account = new_account("Env Co", "env@x.example")

        resp = api.get_account(account["id"], platform_admin_headers)
        data = validate_success(resp)
        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert data["id"] == account["id"]

    def test_error_envelope_carries_error_id_and_message(self, api, platform_admin_headers):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
        PRD §2.5: "Each unresolved identifier maps to its own dedicated error: `ERR_ACCOUNT_NOT_FOUND`, `ERR_MANIFEST_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_SANITIZATION_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, and `ERR_RECYCLER_NOT_FOUND`, all returned as 404."

        Design: Corner/endpoints/response_envelope_meta_present
        """
        resp = api.get_account(NON_EXISTENT_UUID, platform_admin_headers)
        error = validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert error["error_id"] == "ERR_ACCOUNT_NOT_FOUND"
        assert isinstance(error["message"], str) and len(error["message"].strip()) > 0


class TestNotFoundSweep:
    def test_nonexistent_ids_return_domain_specific_404(self, api, platform_admin_headers,
                                                        compliance_officer_headers,
                                                        intake_operator_headers,
                                                        logistics_coordinator_headers):
        """PRD §2.5: "The server resolves each path identifier in turn — account, then manifest, then item, then batch, then settlement, then listing, then sanitization, then certificate, then recycler, in whatever subset the path contains — and rejects the request at the first identifier that does not resolve, before examining anything to its right."
        PRD §2.5: "Each unresolved identifier maps to its own dedicated error: `ERR_ACCOUNT_NOT_FOUND`, `ERR_MANIFEST_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_SANITIZATION_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, and `ERR_RECYCLER_NOT_FOUND`, all returned as 404."

        Design: Corner/entities/not_found_sweep
        """
        validate_error(api.get_account(NON_EXISTENT_UUID, platform_admin_headers),
                       ApiErrorId.ERR_ACCOUNT_NOT_FOUND)
        validate_error(api.get_recycler(NON_EXISTENT_UUID, compliance_officer_headers),
                       ApiErrorId.ERR_RECYCLER_NOT_FOUND)
        validate_error(api.get_manifest(NON_EXISTENT_UUID, platform_admin_headers),
                       ApiErrorId.ERR_MANIFEST_NOT_FOUND)
        validate_error(api.get_item(NON_EXISTENT_UUID, platform_admin_headers),
                       ApiErrorId.ERR_ITEM_NOT_FOUND)
        validate_error(api.get_recycle_batch(NON_EXISTENT_UUID, logistics_coordinator_headers),
                       ApiErrorId.ERR_BATCH_NOT_FOUND)
        validate_error(api.get_settlement(NON_EXISTENT_UUID, platform_admin_headers),
                       ApiErrorId.ERR_SETTLEMENT_NOT_FOUND)
        validate_error(api.sell_listing(NON_EXISTENT_UUID, {"sale_price_cents": 100},
                                        intake_operator_headers),
                       ApiErrorId.ERR_LISTING_NOT_FOUND)
        validate_error(api.verify_sanitization(NON_EXISTENT_UUID, {"verdict": "APPROVE"},
                                               compliance_officer_headers),
                       ApiErrorId.ERR_SANITIZATION_NOT_FOUND)
        validate_error(api.void_certificate(NON_EXISTENT_UUID, compliance_officer_headers),
                       ApiErrorId.ERR_CERTIFICATE_NOT_FOUND)


class TestAuthentication:
    def test_missing_auth_headers_rejected_unauthenticated(self, api):
        """PRD §2.1: "A request arriving without these headers, or carrying a role string that is not one of the six declared roles, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/errors/missing_auth_headers_returns_unauthenticated
        """
        resp = api.get_account(NON_EXISTENT_UUID, None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert resp.status_code == 401


class TestManifestPagination:
    def test_manifests_pagination_limit_offset(self, api, platform_admin_headers):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0."
        PRD §2.3: "Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order."
        PRD §2.3: "List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope."

        Design: Corner/endpoints/manifests_pagination_limit_offset
        """
        account = new_account("Page Co", "pg@x.example")
        # Advance the logical clock between creations so created_at is strictly
        # increasing and the ascending order is deterministic.
        m1 = new_manifest(account, scheduled_start="2026-06-01T09:00:00Z",
                          scheduled_end="2026-06-01T10:00:00Z")
        set_clock("2026-05-01T01:00:00Z")
        m2 = new_manifest(account, scheduled_start="2026-06-02T09:00:00Z",
                          scheduled_end="2026-06-02T10:00:00Z")
        set_clock("2026-05-01T02:00:00Z")
        m3 = new_manifest(account, scheduled_start="2026-06-03T09:00:00Z",
                          scheduled_end="2026-06-03T10:00:00Z")

        page1, meta1 = validate_paginated(
            api.list_account_manifests(account["id"], platform_admin_headers,
                                       params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0
        assert [row["id"] for row in page1] == [m1["id"], m2["id"]]

        page2, meta2 = validate_paginated(
            api.list_account_manifests(account["id"], platform_admin_headers,
                                       params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert meta2["offset"] == 2
        assert page2[0]["id"] == m3["id"]


class TestExistenceOrdering:
    def test_add_to_nonexistent_batch_returns_batch_not_found(self, api, logistics_coordinator_headers):
        """PRD §2.5: "The server resolves each path identifier in turn — account, then manifest, then item, then batch, then settlement, then listing, then sanitization, then certificate, then recycler, in whatever subset the path contains — and rejects the request at the first identifier that does not resolve, before examining anything to its right."
        PRD §2.6: "3. Path existence, left to right as described in §2.5 — the `ERR_*_NOT_FOUND` family."

        Design: Corner/validations/existence_beats_state_on_batch_add
        """
        # The item is data-bearing and unsanitized: it would fail the batch-add
        # data gate if the batch existed, so the 404 proves existence runs first.
        ctx = setup_triaged_item(disposition="RECYCLE", data_bearing=True, declared_grade="B")
        resp = api.add_batch_item(NON_EXISTENT_UUID, {"item_id": ctx["item"]["id"]},
                                  logistics_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_FOUND)
        assert resp.status_code == 404
