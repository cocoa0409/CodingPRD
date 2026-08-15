"""Creation defaults, request validation, authentication, and RBAC denials."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_broadcaster,
    assert_rights_asset,
    build_user_headers,
    create_broadcaster_payload,
    create_package_payload,
    create_rights_asset_payload,
    execute_deal_payload,
    is_valid_uuid,
    setup_awarded_deal,
    setup_open_market,
    validate_error,
    validate_success,
)

RM = TEST_USERS["rights_manager_headers"]
FC = TEST_USERS["finance_controller_headers"]


class TestCreationAndDefaults:
    def test_create_rights_asset_returns_open_with_zero_packages(self, api):
        """PRD §3.1: "A new asset is born `OPEN` with an
        `active_package_count` of zero".
        PRD §2.5: "a unique, server-minted UUID with no type prefix."

        Design: Corner/entities/create_rights_asset_required_fields
        """
        res = api.create_rights_asset(
            create_rights_asset_payload(
                asset_code="PL-2026",
                competition_name="Premier League",
                season_label="2026-27",
                season_start_date="2026-08-01T00:00:00Z",
                season_end_date="2027-05-31T23:59:59Z",
                total_package_pool=5,
                guaranteed_rating_basis_points=5000,
            ),
            RM,
        )
        asset = validate_success(res, 201)
        assert_rights_asset(asset)
        assert asset["status"] == "OPEN"
        assert asset["active_package_count"] == 0
        assert is_valid_uuid(asset["id"])
        assert isinstance(asset["version"], int)

    def test_create_rights_asset_missing_required_field_returns_400(self, api):
        """PRD §3.1: "The `guaranteed_rating_basis_points` states the
        league-wide audience delivery guarantee in basis points".
        PRD §2.12: "A request that fails basic shape or field validation
        outside any of these rules is rejected with `ERR_INVALID_REQUEST`
        (HTTP 400)."

        Design: Corner/entities/create_rights_asset_missing_required_field_returns_400
        """
        payload = create_rights_asset_payload()
        del payload["guaranteed_rating_basis_points"]
        res = api.create_rights_asset(payload, RM)
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

    def test_create_broadcaster_defaults_to_registered(self, api):
        """PRD §3.2: "A registered broadcaster begins in `REGISTERED` status
        and may not yet bid."

        Design: Corner/entities/create_broadcaster_default_status_registered
        """
        res = api.create_broadcaster(
            create_broadcaster_payload(
                legal_name="Test Co",
                home_territory="US",
                platform_classes=["LINEAR_TV"],
                credit_rating="INVESTMENT_GRADE",
            ),
            RM,
        )
        broadcaster = validate_success(res, 201)
        assert_broadcaster(broadcaster)
        assert broadcaster["status"] == "REGISTERED"

    def test_create_broadcaster_invalid_credit_rating_returns_400(self, api):
        """PRD §3.2: "a `credit_rating` of `INVESTMENT_GRADE`, `SPECULATIVE`,
        or `UNRATED`."
        PRD §2.12: "A request that fails basic shape or field validation
        outside any of these rules is rejected with `ERR_INVALID_REQUEST`
        (HTTP 400)."

        Design: Corner/entities/enum_invalid_value_returns_400
        """
        res = api.create_broadcaster(
            create_broadcaster_payload(credit_rating="JUNK"), RM
        )
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


class TestAuthAndExistence:
    def test_missing_user_id_header_returns_400(self, api):
        """PRD §2.1: "A request in which either header is missing or malformed
        is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        headers = {"X-User-Role": "RightsManager", "Content-Type": "application/json"}
        res = api.create_rights_asset(create_rights_asset_payload(), headers)
        validate_error(
            res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", expected_status=400
        )

    def test_get_unknown_rights_asset_returns_404(self, api):
        """PRD §2.8: "The not-found error is specific to the resource kind
        that failed to resolve: `ERR_ASSET_NOT_FOUND` for a missing
        `assetId`".

        Design: Corner/validations/not_found_returns_404
        """
        res = api.get_rights_asset(NON_EXISTENT_UUID, RM)
        validate_error(res, "ERR_ASSET_NOT_FOUND", expected_status=404)


class TestRbacDenials:
    def test_finance_controller_cannot_create_package(self, api):
        """PRD §2.1: "an authenticated caller whose role is not authorized
        for the endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §4: POST /packages — "Create a rights package under an asset",
        authorized role RightsManager.

        Design: Corner/endpoints/rbac_denial_finance_controller_cannot_create_package
        """
        asset, _package = setup_open_market()
        res = api.create_package(create_package_payload(asset["id"]), FC)
        validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)

    def test_bid_coordinator_cannot_execute_deal(self, api):
        """PRD §2.1: "an authenticated caller whose role is not authorized
        for the endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §4: POST /deals/{dealId}/execute — "Execute a DRAFT deal (locks
        schedule)", authorized role RightsManager.

        Design: Corner/endpoints/rbac_denial_bid_coordinator_cannot_execute_deal
        """
        bundle = setup_awarded_deal()
        deal = bundle["deal"]
        headers = build_user_headers(bundle["broadcaster"]["id"], "BidCoordinator")
        res = api.execute_deal(
            deal["id"], execute_deal_payload(deal["version"]), headers
        )
        validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
