"""Commercial onboarding, computed creation defaults, access control, and
pagination (PRD sections 2.1, 2.3, 2.6, and 3.1)."""
from test_helpers import (
    ADMIN,
    FC,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_grower,
    create_field_payload,
    create_grower,
    create_grower_payload,
    create_plan,
    get_grower,
    make_grower_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestGrowerCreationDefaults:

    def test_grower_creation_sets_computed_defaults(self):
        """PRD section 3.1: "A freshly registered grower starts `ACTIVE` with
        `acres_included_ytd` at zero and `credit_balance_cents` at zero."

        Design: Corner/entities/grower_creation_sets_computed_defaults
        """
        plan = create_plan()
        resp = api_client.create_grower(
            create_grower_payload(plan["id"], legal_name="D Farms",
                                  contact_email="d@x.com"), ADMIN)
        data = validate_success(resp, expected_status=201)
        assert_grower(data)
        assert data["status"] == "ACTIVE", \
            f"new grower must start ACTIVE, got {data['status']}"
        assert data["acres_included_ytd"] == 0, \
            f"acres_included_ytd must start at 0, got {data['acres_included_ytd']}"
        assert data["credit_balance_cents"] == 0, \
            f"credit_balance_cents must start at 0, got {data['credit_balance_cents']}"


class TestFieldCreation:

    def test_field_laanc_required_computed_from_airspace_class(self):
        """PRD section 2.10: "the platform derives from that whether LAANC
        authorization is required: classes `B`, `C`, and `D` are controlled
        airspace and require an authorization, while classes `G` and `E` do
        not."

        Design: Corner/entities/field_laanc_required_computed_from_airspace_class
        """
        grower = create_grower()
        resp_g = api_client.create_field(
            grower["id"],
            create_field_payload(field_name="G-class", airspace_class="G"),
            ADMIN)
        field_g = validate_success(resp_g, expected_status=201)
        resp_b = api_client.create_field(
            grower["id"],
            create_field_payload(field_name="B-class", airspace_class="B"),
            ADMIN)
        field_b = validate_success(resp_b, expected_status=201)
        assert field_g["laanc_required"] is False, \
            f"class G must not require LAANC, got {field_g['laanc_required']}"
        assert field_b["laanc_required"] is True, \
            f"class B must require LAANC, got {field_b['laanc_required']}"

    def test_field_creation_missing_required_field_returns_invalid_request(self):
        """PRD section 2.6: "Separately from this pipeline, malformed input on
        any endpoint — a required field missing, a value of the wrong type, an
        enum outside its declared range, or a violated domain input invariant
        such as planned acreage above the field's deeded acreage, a mission
        window whose end does not follow its start, a window longer than six
        hours, a non-positive claim amount, or a liability coverage purchase
        below the floor — is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD section 3.1: "the authoritative deeded `legal_acres` (which must be
        a positive integer, or the request fails as `ERR_INVALID_REQUEST`)".

        Design: Corner/entities/field_creation_missing_required_field_returns_invalid_request
        """
        grower = create_grower()
        payload = create_field_payload(field_name="Bad")
        payload.pop("legal_acres")
        resp = api_client.create_field(grower["id"], payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestAccessControl:

    def test_missing_auth_header_returns_401(self):
        """PRD section 2.1: "A request in which either header is missing or
        empty is rejected with `ERR_MISSING_AUTH_CONTEXT` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_returns_401
        """
        resp = api_client.list_subscription_plans(headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_CONTEXT)

    def test_forbidden_role_returns_403(self):
        """PRD section 2.1: "a role attempting an operation outside its grant
        is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD section 4: POST /ag-drone/growers is authorized for OpsAdmin only.

        Design: Corner/validations/forbidden_role_returns_403
        """
        plan = create_plan()
        grower = create_grower(plan["id"], legal_name="AuthZFarms")
        resp = api_client.create_grower(
            create_grower_payload(plan["id"], legal_name="Hacker"),
            make_grower_headers(grower["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_not_found_returns_404(self):
        """PRD section 2.6: "the request is rejected with `ERR_NOT_FOUND`
        (HTTP 404) at the first identifier that fails to resolve, before later
        identifiers are even examined."

        Design: Corner/validations/not_found_returns_404
        """
        resp = api_client.get_grower(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestListPagination:

    def test_list_growers_pagination_defaults(self):
        """PRD section 2.3: "The `limit` parameter caps the number of items
        returned; it defaults to 10 when omitted, with a minimum of 1 and a
        maximum of 100. The `offset` parameter states how many items to skip
        and defaults to 0."
        PRD section 2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/list_growers_pagination_defaults
        """
        plan = create_plan()
        for i in range(12):
            create_grower(plan["id"], legal_name=f"G{i + 1}",
                          contact_email=f"g{i + 1}@x.com")
        resp = api_client.list_growers(ADMIN)
        data, meta = validate_paginated(resp)
        assert len(data) == 10, \
            f"default limit must return 10 items, got {len(data)}"
        assert meta["total_count"] == 12, \
            f"total_count must be 12, got {meta['total_count']}"
        assert meta["has_more"] is True, "has_more must be true at offset 0 of 12"
        assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
        assert meta["offset"] == 0, f"default offset must be 0, got {meta['offset']}"
