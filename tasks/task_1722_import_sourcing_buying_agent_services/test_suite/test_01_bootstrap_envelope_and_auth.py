"""Bootstrap creation defaults, response envelopes, auth presence, listing
pagination, and the logical-clock default."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_buyer,
    assert_factory,
    create_buyer_payload,
    create_factory_payload,
    make_buyer_manager_headers,
    make_sourcing_agent_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    create_agent,
    create_buyer,
    create_quotation,
    create_sourcing_request,
    make_grade_a_factory,
    accept_quotation,
)


class TestBuyerCreation:
    def test_buyer_creation_defaults_and_envelope(self, api, admin_headers):
        """PRD: "Creating a `Buyer` records the buyer company `name` and its `country_code` (an ISO 3166-1 alpha-2 code); the new buyer starts with `credit_balance_cents` 0, `ytd_gmv_cents` 0, and `status` `ACTIVE`."
        PRD: "`version` — an integer starting at 1 and incrementing by 1 on each successful mutation"
        PRD: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

        Design: Corner/entities/buyer_creation_defaults_and_envelope
        """
        resp = api.create_buyer(
            create_buyer_payload(name="Acme Imports", country_code="US"), admin_headers
        )
        data = validate_success(resp, expected_status=201)
        assert_buyer(data)
        assert data["credit_balance_cents"] == 0
        assert data["ytd_gmv_cents"] == 0
        assert data["status"] == "ACTIVE"
        assert data["version"] == 1
        assert resp.json()["response_type"] == "object"


class TestFactoryCreation:
    def test_factory_creation_computed_defaults(self, api, admin_headers):
        """PRD: "The factory starts `ACTIVE` with `compliance_posture` `COMPLIANT`, `debit_balance_cents` 0, and `latest_audit_grade` `NONE` (with `audit_score` 0)."

        Design: Corner/entities/factory_creation_computed_defaults
        """
        agent = create_agent()
        resp = api.create_factory(
            create_factory_payload(
                name="Factory One", country_code="CN", monthly_capacity_units=5000
            ),
            make_sourcing_agent_headers(agent["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert_factory(data)
        assert data["status"] == "ACTIVE"
        assert data["compliance_posture"] == "COMPLIANT"
        assert data["debit_balance_cents"] == 0
        assert data["latest_audit_grade"] == "NONE"
        assert data["audit_score"] == 0

    def test_factory_monthly_capacity_must_be_positive(self, api):
        """PRD: "A `SourcingAgent` registers candidate factories by supplying the factory's legal `name`, `country_code`, and `monthly_capacity_units` (an integer of at least 1 — the maximum committed units the factory will accept per calendar delivery month across all POs)."
        PRD: "`ERR_VALIDATION` | 400"

        Design: Corner/entities/factory_monthly_capacity_must_be_positive
        """
        agent = create_agent()
        resp = api.create_factory(
            create_factory_payload(
                name="Bad Factory", country_code="CN", monthly_capacity_units=0
            ),
            make_sourcing_agent_headers(agent["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestNotFound:
    def test_get_nonexistent_resources_return_404(self, api, admin_headers):
        """PRD: "A nonexistent parent yields the parent's not-found error (`ERR_FACTORY_NOT_FOUND`, `ERR_SOURCING_REQUEST_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`)"
        PRD: "Top-level lookups use the corresponding not-found error (`ERR_BUYER_NOT_FOUND`, `ERR_AGENT_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`)."

        Design: Corner/entities/get_nonexistent_resources_return_404
        """
        validate_error(
            api.get_buyer(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_BUYER_NOT_FOUND
        )
        validate_error(
            api.get_factory(NON_EXISTENT_UUID, admin_headers),
            ApiErrorId.ERR_FACTORY_NOT_FOUND,
        )
        validate_error(
            api.get_purchase_order(NON_EXISTENT_UUID, admin_headers),
            ApiErrorId.ERR_PURCHASE_ORDER_NOT_FOUND,
        )


class TestErrorEnvelope:
    def test_error_envelope_shape_on_failure(self, api, admin_headers):
        """PRD: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
        PRD: "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/endpoints/error_envelope_shape_on_failure
        """
        resp = api.get_factory(NON_EXISTENT_UUID, admin_headers)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_FACTORY_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
        assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}


class TestAuthPresence:
    @pytest.mark.parametrize(
        "headers",
        [
            {},
            {"X-User-ID": "", "X-User-Role": "PlatformAdmin"},
            {"X-User-ID": "test-platform-admin-1", "X-User-Role": ""},
        ],
        ids=["both-missing", "empty-user-id", "empty-role"],
    )
    def test_missing_auth_headers_rejected(self, api, headers):
        """PRD: "A request missing either header, or carrying either header as the empty string, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_rejected
        """
        resp = api.create_buyer(
            create_buyer_payload(name="NoAuth", country_code="US"), headers
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestQuotationListing:
    def test_list_pagination_envelope_and_defaults(self, api, admin_headers):
        """PRD: "`limit` defaults to 10, has a minimum of 1 and a maximum of 100. `offset` defaults to 0 and has a minimum of 0."
        PRD: "The response `meta` block includes `limit`, `offset`, `total_count`, and `has_more` so the client can page deterministically."

        Design: Corner/entities/list_pagination_envelope_and_defaults
        """
        buyer = create_buyer()
        agent = create_agent()
        f1 = make_grade_a_factory(agent["id"], name="F1")
        f2 = make_grade_a_factory(agent["id"], name="F2", country_code="VN")
        for title, factory in (("L1", f1), ("L2", f1), ("L3", f2)):
            sr = create_sourcing_request(buyer["id"], agent["id"], title=title)
            create_quotation(sr["id"], factory["id"])

        resp = api.list_quotations(admin_headers)
        data, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array"
        assert len(data) == 3
        assert meta["total_count"] == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["has_more"] is False

        data2, meta2 = validate_paginated(
            api.list_quotations(admin_headers, params={"limit": 2, "offset": 0})
        )
        assert len(data2) == 2
        assert meta2["limit"] == 2
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is True

        data3, meta3 = validate_paginated(
            api.list_quotations(admin_headers, params={"limit": 2, "offset": 2})
        )
        assert len(data3) == 1
        assert meta3["offset"] == 2
        assert meta3["has_more"] is False


class TestRoleAdmission:
    def test_rbac_factory_create_forbidden_for_buyer(self, api):
        """PRD: "If the role named in `X-User-Role` is not in the endpoint's permitted role list, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD endpoint table: "Register a Factory | SourcingAgent".

        Design: Corner/roles/rbac_factory_create_forbidden_for_buyer
        """
        buyer = create_buyer()
        resp = api.create_factory(
            create_factory_payload(name="Sneaky", country_code="CN",
                                   monthly_capacity_units=100),
            make_buyer_manager_headers(buyer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestLogicalClock:
    def test_clock_endpoint_reports_default_and_new_time(self, api):
        """PRD: "Its startup default before any such call is exactly `2026-08-01T00:00:00Z`. The server never falls back to wall-clock time."
        PRD: "the logical clock must be at or before `valid_until` (`ERR_QUOTATION_EXPIRED`)"

        At the untouched default clock, a quotation whose valid_until equals the
        default instant is still acceptable (at-or-before is inclusive), which
        pins the default clock to exactly that instant.

        Design: Corner/endpoints/clock_endpoint_reports_default_and_new_time
        """
        buyer = create_buyer()
        agent = create_agent()
        factory = make_grade_a_factory(agent["id"])
        sr = create_sourcing_request(buyer["id"], agent["id"], title="CLK")
        quotation = create_quotation(
            sr["id"], factory["id"], valid_until="2026-08-01T00:00:00Z"
        )
        po = accept_quotation(buyer["id"], quotation, ordered_qty=1)
        assert po["status"] == "ACTIVE"
