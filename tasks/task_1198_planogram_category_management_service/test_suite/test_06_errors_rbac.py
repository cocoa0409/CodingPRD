"""Error-catalog and RBAC corner tests."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_category_payload,
    create_funding_deal_payload,
    create_planogram_payload,
    create_retailer_payload,
    create_supplier_payload,
    make_category_captain_headers,
    setup_approved_planogram,
    setup_planogram_in_review,
    validate_error,
    validate_success,
)


class TestAuthentication:
    def test_error_unauthenticated_missing_role_header(self, api, platform_admin_headers):
        """PRD §2.1: "A request that arrives without these headers, or carrying
        a role the platform does not recognize, is rejected with
        `ERR_UNAUTHENTICATED`."

        Design: Corner/errors/error_unauthenticated_missing_role_header
        """
        retailer = validate_success(
            api.create_retailer(create_retailer_payload(name="R"), platform_admin_headers),
            expected_status=201,
        )
        rid = retailer["id"]
        # No X-User-Role header at all
        resp = api.get_retailer(rid, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRBAC:
    def test_field_auditor_cannot_create_categories(self, api, platform_admin_headers, field_auditor_headers):
        """PRD §2.1: "a caller whose role is not permitted to invoke that
        endpoint is rejected with `ERR_UNAUTHORIZED`."
        PRD §4 endpoint table: POST /retailers/{id}/categories authorized role
        is CategoryManager only.

        Design: Corner/rbac/field_auditor_cannot_create_categories
        """
        retailer = validate_success(
            api.create_retailer(create_retailer_payload(name="R"), platform_admin_headers),
            expected_status=201,
        )
        rid = retailer["id"]
        resp = api.create_category(
            rid,
            create_category_payload(code="X"),
            field_auditor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_category_captain_cannot_approve_planogram(self, api):
        """PRD §4 endpoint table: POST
        /retailers/{id}/categories/{cid}/planograms/{pid}/approve authorized
        role is CategoryManager only.
        PRD §2.1: "a caller whose role is not permitted to invoke that endpoint
        is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/category_captain_cannot_approve_planogram
        """
        retailer, category, supplier, product, pg, line = setup_planogram_in_review()
        rid, cid, pgid = retailer["id"], category["id"], pg["id"]
        captain_headers = make_category_captain_headers(supplier["id"])
        resp = api.approve_planogram(rid, cid, pgid, captain_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_reset_coordinator_cannot_approve_funding(
        self, api, platform_admin_headers, retailer_admin_headers, reset_coordinator_headers
    ):
        """PRD §4 endpoint table: POST /retailers/{id}/funding-deals/{fdid}/approve
        authorized role is RetailerAdmin only.
        PRD §2.1: "a caller whose role is not permitted to invoke that endpoint
        is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/reset_coordinator_cannot_approve_funding
        """
        retailer = validate_success(
            api.create_retailer(create_retailer_payload(name="R"), platform_admin_headers),
            expected_status=201,
        )
        rid = retailer["id"]
        cat = validate_success(
            api.create_category(
                rid, create_category_payload(code="C"), TEST_USERS["category_manager_headers"]
            ),
            expected_status=201,
        )
        supplier = validate_success(
            api.create_supplier(rid, create_supplier_payload(name="S"), retailer_admin_headers),
            expected_status=201,
        )
        deal = validate_success(
            api.create_funding_deal(
                rid, create_funding_deal_payload(cat["id"], supplier["id"]), retailer_admin_headers
            ),
            expected_status=201,
        )
        resp = api.approve_funding_deal(
            rid,
            deal["id"],
            {"expected_funding_deal_version": deal["version"]},
            reset_coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestCaptainIdentity:
    def test_captain_identity_entity_backed_supplier(self, api, category_manager_headers):
        """PRD §2.1: "When `X-User-Role` is `CategoryCaptain`, `X-User-ID` is
        the `id` of the acting `Supplier`; ownership checks on any resource
        that references a `Supplier` compare the resource's foreign-key field
        to `X-User-ID`."
        PRD §3.5: "the calling captain's supplier identifier, taken from the
        `X-User-ID` header, is written to the planogram's
        `submitted_by_captain_supplier_id`."

        Design: Corner/rbac/captain_identity_entity_backed_supplier
        """
        retailer, category, supplier, product, pg, line = setup_planogram_in_review()
        rid, cid, pgid = retailer["id"], category["id"], pg["id"]
        got = validate_success(api.get_planogram(rid, cid, pgid, category_manager_headers))
        assert got["submitted_by_captain_supplier_id"] == supplier["id"]


class TestOCCOnPlanogramActivate:
    def test_error_stale_version_on_planogram_activate(self, api, category_manager_headers):
        """PRD §2.7: "Activating a planogram
        (`POST /retailers/{id}/categories/{cid}/planograms/{pid}/activate`)
        requires `expected_category_version`, matched against the parent
        category's current `version`."
        PRD §2.7: "if that value no longer matches the entity's current
        `version` on the server, the write is rejected with `ERR_STALE_VERSION`
        and HTTP status 412."

        Design: Corner/errors/error_stale_version_on_planogram_activate
        """
        retailer, category, supplier, product, pg, line = setup_approved_planogram()
        rid, cid, pgid = retailer["id"], category["id"], pg["id"]
        # Capture category version, then mutate it via lock+unlock to bump version
        cat_before = validate_success(api.get_category(rid, cid, category_manager_headers))
        cv = cat_before["version"]
        validate_success(api.lock_category(rid, cid, category_manager_headers))
        validate_success(api.unlock_category(rid, cid, category_manager_headers))
        # Caller now holds stale cv
        resp = api.activate_planogram(
            rid, cid, pgid, {"expected_category_version": cv}, category_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
