"""Master data (programs, stores, products), response envelope, pagination,
and the authentication/role gates at the top of the validation ladder."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_product,
    assert_program,
    create_product_payload,
    create_program_payload,
    make_retailer_manager_headers,
    make_route_driver_headers,
    new_product,
    new_program,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["jobber_admin_headers"]


class TestProgramDefaults:
    def test_program_create_applies_declared_defaults(self, api):
        """PRD section 3.1: "A program carries a display `name` and three
        tunable policies: `promo_min_gap_days`, the minimum number of full days
        that must separate two non-cancelled promotions on the same program and
        product, defaulting to 1; `min_payout_cents`, the smallest net payable
        a settlement statement may reach and still be disbursable, defaulting
        to 5000; and `default_settlement_cadence`, one of `WEEKLY`, `BIWEEKLY`,
        or `MONTHLY`, defaulting to `WEEKLY` and inherited by agreements that
        do not override it."
        PRD section 3.1: "A program is born `ACTIVE` and may later be archived,
        moving it to `ARCHIVED`; archiving is permitted only when no live
        agreements remain under the program."

        Design: Corner/entities/program_create_applies_defaults
        """
        set_clock()
        program = validate_success(
            api.create_program(create_program_payload(name="Defaults Co"),
                               ADMIN), 201)
        assert_program(program)
        assert program["status"] == "ACTIVE", "a program is born ACTIVE"
        assert program["promo_min_gap_days"] == 1
        assert program["min_payout_cents"] == 5000
        assert program["default_settlement_cadence"] == "WEEKLY"
        assert program["version"] == 1, (
            "version starts at 1 and increments by one on every mutation "
            "(PRD section 2.4)")


class TestStoreCreation:
    def test_store_create_missing_total_facings_rejected(self, api):
        """PRD section 3.1: "A Store is created with a display `name`, a
        `store_code` that must be unique across all stores, and
        `total_facings`, the store's total rack facing capacity, which must be
        at least 1."
        PRD section 2.8: "Shape: required fields must be present and
        well-typed, failing with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/store_create_missing_required_rejected
        """
        set_clock()
        res = api.create_store({"name": "NoFacings", "store_code": "NF1"},
                               ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


class TestProductSystemFields:
    def test_product_create_status_input_ignored(self, api):
        """PRD section 3.2: "A product is born `ACTIVE`; a later update may
        revise `jobber_cost_cents` or `min_retail_cents`, or move `status` to
        `DISCONTINUED`."
        PRD section 2.10: "Derived fields — stock postures, cumulative ratios,
        frozen totals — are recomputed by the mutations that feed them and are
        never accepted as client input."

        Design: Corner/entities/product_create_status_input_ignored
        """
        set_clock()
        program = new_program(name="SysFieldCo")
        payload = create_product_payload(program["id"], sku="SYS-001",
                                         name="Sys Test")
        payload["status"] = "DISCONTINUED"
        product = validate_success(api.create_product(payload, ADMIN), 201)
        assert_product(product)
        assert product["status"] == "ACTIVE", (
            "client-supplied status must be ignored; a product is born ACTIVE")


class TestSkuUniqueness:
    def test_duplicate_sku_within_program_rejected(self, api):
        """PRD section 3.2: "Each product belongs to a `program_id` and
        carries a `sku` that must be unique within that program — a duplicate
        is rejected with `ERR_SKU_EXISTS` — plus a display `name`, the
        `jobber_cost_cents` unit cost that anchors restock caps and cost-based
        shrink valuation, the `min_retail_cents` retail price floor, and
        `units_per_facing`, the number of units that fit in one rack facing,
        which doubles as the reorder point for inventory balances."

        Design: Corner/validations/duplicate_sku_rejected
        """
        set_clock()
        program = new_program(name="SkuCo")
        new_product(program["id"], sku="DUP-1", name="First")
        res = api.create_product(
            create_product_payload(program["id"], sku="DUP-1", name="Second",
                                   jobber_cost_cents=200, min_retail_cents=300,
                                   units_per_facing=5),
            ADMIN)
        validate_error(res, ApiErrorId.ERR_SKU_EXISTS)


class TestPaginationEnvelope:
    def test_list_products_pagination_defaults(self, api):
        """PRD section 2.3: "The `limit` parameter specifies the maximum number
        of items to return: it defaults to 10 when omitted, accepts a minimum
        of 1, and is capped at a maximum of 100. The `offset` parameter
        specifies how many items to skip and defaults to 0."
        PRD section 2.3: "The `meta` object of a list response carries the
        pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_pagination_envelope_defaults
        """
        set_clock()
        program = new_program(name="PageCo")
        for i in range(3):
            new_product(program["id"], sku=f"PG-{i}", name=f"P{i}")
        res = api.list_products(ADMIN, params={"program_id": program["id"]})
        data, meta = validate_paginated(res)
        assert res.json()["response_type"] == "array"
        assert meta["limit"] == 10, "default limit is 10"
        assert meta["offset"] == 0, "default offset is 0"
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(data) == 3


class TestErrorEnvelope:
    def test_error_envelope_shape_on_not_found(self, api):
        """PRD section 2.2: "The `meta` object for error responses contains
        only `api_request_id` and `api_request_timestamp`."
        PRD section 2.2: "The `error_id` is a unique, machine-readable string
        that identifies the specific error."
        PRD section 2.8: "Path existence: resource identifiers in the URL path
        must exist, validated strictly left-to-right so that the first missing
        identifier produces `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/errors/error_envelope_shape
        """
        set_clock()
        res = api.get_product(NON_EXISTENT_UUID, ADMIN)
        err = validate_error(res, ApiErrorId.ERR_NOT_FOUND)
        assert isinstance(err.get("message"), str) and err["message"], (
            "error data must carry a human-readable message")
        body = res.json()
        assert body["response_type"] == "error"
        assert body["meta"]["api_request_id"], "meta.api_request_id present"
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "api_request_id starts with req_ (PRD section 2.2)")

    def test_get_nonexistent_agreement_returns_404(self, api):
        """PRD section 2.8: "Path existence: resource identifiers in the URL
        path must exist, validated strictly left-to-right so that the first
        missing identifier produces `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_nonexistent_agreement_returns_404
        """
        set_clock()
        res = api.get_agreement(NON_EXISTENT_UUID, ADMIN)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)


class TestAuthAndRoleGate:
    def test_missing_auth_headers_rejected(self, api):
        """PRD section 2.1: "Every request must carry two HTTP headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the
        capacity in which they act. A request in which either header is missing
        or empty is rejected with `ERR_MISSING_AUTH_CONTEXT` (HTTP 400)."

        Design: Corner/validations/auth_missing_header_rejected
        """
        set_clock()
        res = api.create_program(create_program_payload(name="NoAuth"), {})
        validate_error(res, ApiErrorId.ERR_MISSING_AUTH_CONTEXT)

    def test_route_driver_cannot_create_program(self, api):
        """PRD section 2.1: "Each endpoint declares the roles authorized to
        invoke it; a request whose `X-User-Role` is not in the endpoint's role
        list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD section 4: POST /programs lists JobberAdmin as its only authorized
        role.

        Design: Corner/rbac/rbac_route_driver_cannot_create_program
        """
        set_clock()
        res = api.create_program(create_program_payload(name="Nope"),
                                 make_route_driver_headers("drv-1"))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_retailer_manager_cannot_create_product(self, api):
        """PRD section 2.1: "Each endpoint declares the roles authorized to
        invoke it; a request whose `X-User-Role` is not in the endpoint's role
        list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD section 4: POST /products lists JobberAdmin as its only authorized
        role.

        Design: Corner/rbac/rbac_retailer_manager_cannot_create_product
        """
        set_clock()
        program = new_program(name="RBProd")
        res = api.create_product(
            create_product_payload(program["id"], sku="RB-1", name="Nope"),
            make_retailer_manager_headers(NON_EXISTENT_UUID))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)
