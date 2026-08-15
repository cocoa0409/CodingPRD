"""API-wide conventions (PRD §2): envelope pagination, collection filters,
authentication, and role authorization."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_committee_member_payload,
    create_market_payload,
    create_qualified_market,
    create_site,
    create_site_payload,
    get_success_data,
    make_committee_member_headers,
    validate_error,
    validate_paginated,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]


class TestPaginationEnvelope:
    def test_list_pagination_envelope(self, api):
        """PRD §2.3: "All list endpoints accept two query parameters: `limit`,
        which defaults to 10 and must be between 1 and 100 inclusive, and
        `offset`, which defaults to 0. The `meta` object of a list response
        carries `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_pagination_envelope
        """
        market = create_qualified_market(name="Metro PG")
        create_site(market["id"], address="1 First Ave")
        create_site(market["id"], address="2 Second Ave")
        page1, meta1 = validate_paginated(
            api.list_sites(ANALYST, params={"limit": 1, "offset": 0})
        )
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1
        assert meta1["offset"] == 0
        page2, meta2 = validate_paginated(
            api.list_sites(ANALYST, params={"limit": 1, "offset": 1})
        )
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert page1[0]["id"] != page2[0]["id"], "pages are disjoint"

    def test_filtered_list_by_foreign_key(self, api):
        """PRD §2.3: "List endpoints additionally support resource-appropriate
        filters. Sites may be filtered by `market_id` and `site_status`"

        Design: Corner/endpoints/filtered_list_by_foreign_key
        """
        mkt1 = create_qualified_market(name="Metro F1")
        mkt2 = create_qualified_market(name="Metro F2", state_code="OK")
        create_site(mkt1["id"], address="1 First Ave")
        create_site(mkt2["id"], address="2 Second Ave")
        filtered, meta = validate_paginated(
            api.list_sites(ANALYST, params={"market_id": mkt1["id"]})
        )
        assert meta["total_count"] == 1
        assert filtered[0]["market_id"] == mkt1["id"]
        _all, meta_all = validate_paginated(api.list_sites(ANALYST))
        assert meta_all["total_count"] == 2


class TestAuthLayers:
    def test_missing_auth_header_rejected(self, api):
        """PRD §2.1: "Every request carries two headers: `X-User-ID` and
        `X-User-Role`. If either header is missing or blank, or if
        `X-User-Role` is not one of the declared role names below, the request
        is rejected with `ERR_MISSING_AUTH_HEADER` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_rejected
        """
        resp = api.create_market(create_market_payload(name="NoAuth"),
                                 headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_HEADER)

    def test_role_denial_precedes_existence(self, api):
        """PRD §2.7: "Every request is validated against the following layers
        in the order listed; a failure at an earlier layer is reported and
        masks any failure a later layer would have produced."
        PRD §2.1: "If the role is declared but not listed among the roles
        authorized for the endpoint, the request is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/validations/role_denial_precedes_existence
        """
        # RealEstateAnalyst is not authorized for withdraw; the unknown path id
        # must not be reached first.
        resp = api.withdraw_site(NON_EXISTENT_UUID, ANALYST)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_committee_member_cannot_create_site(self, api):
        """PRD §4: the `POST /api/sites` row authorizes only
        "RealEstateAnalyst".
        PRD §2.1: "If the role is declared but not listed among the roles
        authorized for the endpoint, the request is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/committee_member_cannot_create_site
        """
        market = create_qualified_market(name="Metro R3")
        member = get_success_data(api.create_committee_member(
            create_committee_member_payload(display_name="Voter1"), ADMIN,
        ))
        resp = api.create_site(
            create_site_payload(market_id=market["id"]),
            make_committee_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
