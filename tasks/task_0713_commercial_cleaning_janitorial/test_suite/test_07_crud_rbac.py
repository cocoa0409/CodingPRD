"""CRUD defaults, validation errors, RBAC denials, listing, and FK reverse reads."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_account_payload, create_rfp_payload, create_service_area_payload,
    create_account, create_rfp, add_service_areas,
    assert_account, SINGLE_LIGHT_AREA, TEST_USERS,
)

_SALES = TEST_USERS["sales_rep_headers"]
_BID = TEST_USERS["bid_estimator_headers"]
_OPS = TEST_USERS["operations_manager_headers"]
_ADMIN = TEST_USERS["platform_admin_headers"]


class TestEntityCreationAndDefaults:
    """Corner section: entities."""

    def test_create_account_returns_defaults(self, api):
        """PRD §3.1: "On creation the account's lifecycle_stage is PROSPECT, its
        health_score is 100, and its owner_user_id is null until the onboarding handoff."
        PRD §2.4: "an integer version that begins at 1 and increments by one on each
        mutation."

        Design: Corner/entities/create_account_returns_201_with_defaults
        """
        res = api.create_account(create_account_payload(legal_name="Init Co", industry="RETAIL"), _SALES)
        acct = validate_success(res, 201)
        assert_account(acct)
        assert acct["lifecycle_stage"] == "PROSPECT"
        assert acct["health_score"] == 100
        assert acct["version"] == 1

    def test_get_nonexistent_account_returns_not_found(self, api):
        """PRD §2.5: "The first segment in the chain that does not resolve produces
        ERR_NOT_FOUND (HTTP 404)."

        Design: Corner/entities/get_account_not_found_returns_404
        """
        res = api.get_account("00000000-0000-0000-0000-000000000000", _SALES)
        validate_error(res, "ERR_NOT_FOUND")

    def test_create_rfp_missing_due_at_rejected(self, api):
        """PRD §2.7: "then presence and typing of required input fields
        (ERR_INVALID_REQUEST)".
        PRD §3.1: "The rep opens an RFP opportunity under the account by supplying a
        title, a due_at proposal-submission deadline, and an estimated_total_sqft that
        must be greater than zero."

        Design: Corner/entities/create_rfp_missing_required_field_returns_invalid_request
        """
        acct = create_account(legal_name="Req Co")
        payload = create_rfp_payload()
        del payload["due_at"]
        res = api.create_rfp(acct["id"], payload, _SALES)
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_create_account_invalid_industry_enum_rejected(self, api):
        """PRD §3.1: "where industry must be one of OFFICE, MEDICAL, INDUSTRIAL, RETAIL,
        or EDUCATION."
        PRD §2.7: "then enum-domain membership (ERR_INVALID_ENUM)".

        Design: Corner/entities/create_account_invalid_enum_industry_returns_invalid_enum
        """
        res = api.create_account(
            create_account_payload(legal_name="Bad Enum", industry="SPACEPORT"), _SALES)
        validate_error(res, "ERR_INVALID_ENUM")

    def test_service_area_sqft_zero_rejected(self, api):
        """PRD §3.3: "A sqft of zero or less, or a frequency outside 1 through 7, is
        rejected with ERR_INVALID_RANGE."

        Design: Corner/entities/service_area_sqft_zero_returns_invalid_range
        """
        acct = create_account(legal_name="SA Co")
        rfp = create_rfp(acct["id"])
        res = api.create_service_area(
            acct["id"], rfp["id"],
            create_service_area_payload(label="Empty", sqft=0, soil_level="LIGHT", frequency_per_week=1),
            _BID)
        validate_error(res, "ERR_INVALID_RANGE")

    def test_service_area_frequency_out_of_range_rejected(self, api):
        """PRD §3.3: "A sqft of zero or less, or a frequency outside 1 through 7, is
        rejected with ERR_INVALID_RANGE."

        Design: Corner/entities/service_area_frequency_out_of_range_returns_invalid_range
        """
        acct = create_account(legal_name="Freq Co")
        rfp = create_rfp(acct["id"])
        res = api.create_service_area(
            acct["id"], rfp["id"],
            create_service_area_payload(label="TooOften", sqft=5000, soil_level="LIGHT",
                                        frequency_per_week=8),
            _BID)
        validate_error(res, "ERR_INVALID_RANGE")

    def test_bid_estimate_system_fields_minted(self, api):
        """PRD §3.3: "The new BidEstimate records its rfp_id and is created in status
        DRAFT; the status enumerates DRAFT and PRICED."
        PRD §2.4: "an integer version that begins at 1".

        Design: Corner/entities/bid_estimate_id_system_minted_ignores_input_id
        """
        acct = create_account(legal_name="Sys Co")
        rfp = create_rfp(acct["id"], estimated_total_sqft=5000)
        bid = validate_success(api.create_bid_estimate(
            acct["id"], rfp["id"], {"base_wage_cents": 1800, "target_margin_pct": 0.20}, _BID), 201)
        assert bid["status"] == "DRAFT"
        assert bid["version"] == 1

    def test_list_accounts_pagination_envelope(self, api):
        """PRD §2.3: "The pagination fields limit, offset, total_count, and has_more are
        echoed inside the meta object of every list response, where total_count is the
        number of records matching the query before pagination".

        Design: Corner/entities/list_accounts_pagination_envelope
        """
        create_account(legal_name="L1", industry="OFFICE")
        create_account(legal_name="L2", industry="RETAIL")
        data, meta = validate_paginated(api.list_accounts(_ADMIN))
        assert meta["total_count"] >= 2


class TestPaginationAndErrors:
    """Corner section: errors."""

    def test_pagination_limit_out_of_range_rejected(self, api):
        """PRD §2.3: "a limit outside the range 1 through 100 inclusive is rejected with
        ERR_VALIDATION_LIMIT (HTTP 422)."

        Design: Corner/errors/validation_limit_pagination_out_of_range
        """
        res = api.list_accounts(_ADMIN, params={"limit": 500})
        validate_error(res, "ERR_VALIDATION_LIMIT")


class TestRbacDenials:
    """Corner section: rbac."""

    def test_bid_estimator_cannot_create_account(self, api):
        """PRD §2.1: "A SalesRep owns prospect capture, RFP creation, site-contact
        creation, walkthrough scheduling and completion, proposal creation and lifecycle
        (send, revise, accept, decline), and contract creation and signing."
        PRD §2.1: "If the headers are present but the named role is not permitted to
        perform the requested operation, the request is rejected with ERR_UNAUTHORIZED
        (HTTP 403)."

        Design: Corner/rbac/bid_estimator_cannot_create_account
        """
        res = api.create_account(create_account_payload(legal_name="X", industry="OFFICE"), _BID)
        validate_error(res, "ERR_UNAUTHORIZED")

    def test_sales_rep_cannot_approve_requisition(self, api):
        """PRD §2.1: "An OperationsManager owns crew creation and retirement, start-up
        crewing, mark-ready, go-live and abort actions, crew-shift cancellation,
        supply-budget creation, and supply-requisition creation, approval, and
        cancellation."
        PRD §2.1: "If the headers are present but the named role is not permitted to
        perform the requested operation, the request is rejected with ERR_UNAUTHORIZED
        (HTTP 403)."

        Design: Corner/rbac/sales_rep_cannot_approve_requisition
        """
        # A SalesRep attempting the OperationsManager-exclusive approve is denied. The
        # denial is authorization, which §2.7 evaluates before any state/budget check,
        # so a minimal target is sufficient.
        res = api.approve_requisition(
            "00000000-0000-0000-0000-000000000000",
            "00000000-0000-0000-0000-000000000000",
            {"expected_supply_budget_version": 1}, _SALES)
        validate_error(res, "ERR_UNAUTHORIZED")

    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two headers: X-User-ID, identifying the
        acting user, and X-User-Role, naming that user's role. If either header is
        missing, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

        Design: Corner/rbac/missing_auth_header_returns_unauthenticated
        """
        res = api.list_accounts({})
        validate_error(res, "ERR_UNAUTHENTICATED")


class TestForeignKeyReverseReads:
    """Corner section: endpoints."""

    def test_list_service_areas_of_rfp(self, api):
        """PRD §4 (endpoint): "List service areas of RFP".
        PRD §3.3: "Each service area records its parent rfp_id."
        PRD §2.3: "where total_count is the number of records matching the query before
        pagination".

        Design: Corner/endpoints/fk_reverse_list_service_areas_of_rfp
        """
        acct = create_account(legal_name="FK Co")
        rfp = create_rfp(acct["id"], estimated_total_sqft=14000)
        add_service_areas(acct["id"], rfp["id"], [
            {"label": "A1", "sqft": 10000, "soil_level": "MEDIUM", "frequency_per_week": 5},
            {"label": "A2", "sqft": 4000, "soil_level": "HEAVY", "frequency_per_week": 5},
        ])
        data, meta = validate_paginated(api.list_service_areas(acct["id"], rfp["id"], _BID))
        assert meta["total_count"] == 2
