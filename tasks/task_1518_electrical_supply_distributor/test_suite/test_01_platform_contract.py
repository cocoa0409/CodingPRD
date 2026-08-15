"""Platform-wide contract: response envelope, pagination, auth context,
creation defaults, request-shape rules, existence checks, and RBAC."""
from test_helpers import (
    CREDIT_MGR,
    NON_EXISTENT_UUID,
    REBATE_CLERK,
    SALES_REP,
    WH_MGR,
    ApiErrorId,
    api_client,
    assert_catalog_item,
    assert_contractor,
    build_user_headers,
    create_awarded_quote,
    create_catalog_item_payload,
    create_contractor,
    create_contractor_payload,
    create_ea_item,
    create_job_account,
    create_submitted_quote,
    get_release,
    is_iso8601_timestamp,
    make_contractor_headers,
    setup_delivered_release,
    setup_draft_quote_with_substitution,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestResponseEnvelope:

    def test_success_and_error_envelope_shape(self, rebate_clerk_headers):
        """PRD section 2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD section 2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD section 2.2: "The `message` provides a human-readable explanation
        of what went wrong."

        Design: Corner/endpoints/response_envelope_success_and_error_shape
        """
        contractor = create_contractor("Sierra Electric", 100_000)

        ok_resp = api_client.get_contractor(contractor["id"],
                                            rebate_clerk_headers)
        ok_body = ok_resp.json()
        assert ok_resp.status_code == 200
        assert ok_body["response_type"] == "object"
        assert ok_body["meta"]["api_request_id"].startswith("req_"), (
            f"api_request_id must start with 'req_', got "
            f"{ok_body['meta']['api_request_id']!r}")
        assert is_iso8601_timestamp(
            ok_body["meta"]["api_request_timestamp"])
        assert ok_body["data"]["id"] == contractor["id"]

        err_resp = api_client.get_contractor(NON_EXISTENT_UUID,
                                             rebate_clerk_headers)
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        validate_error(err_resp, ApiErrorId.ERR_CONTRACTOR_NOT_FOUND)
        assert isinstance(err_body["data"]["message"], str) and \
            len(err_body["data"]["message"].strip()) > 0


class TestContractorCreation:

    def test_create_contractor_initializes_computed_balances(self):
        """PRD section 3.1: "The new contractor's `invoiced_balance_cents` and
        `committed_balance_cents` start at zero, its `credit_used_cents`
        therefore reads zero, and its `version` starts at 1."

        Design: Corner/entities/create_contractor_initializes_computed_balances
        """
        resp = api_client.create_contractor(
            create_contractor_payload(name="Romeo Electric",
                                      credit_limit_cents=250_000),
            CREDIT_MGR)
        data = validate_success(resp, expected_status=201)
        assert_contractor(data)
        assert data["invoiced_balance_cents"] == 0
        assert data["committed_balance_cents"] == 0
        assert data["credit_used_cents"] == 0
        assert data["version"] == 1

        fetched = validate_success(
            api_client.get_contractor(data["id"], CREDIT_MGR))
        assert fetched["invoiced_balance_cents"] == 0
        assert fetched["committed_balance_cents"] == 0
        assert fetched["credit_used_cents"] == 0
        assert fetched["version"] == 1

    def test_create_contractor_ignores_client_supplied_computed_fields(self):
        """PRD section 3.1: "The new contractor's `invoiced_balance_cents` and
        `committed_balance_cents` start at zero, its `credit_used_cents`
        therefore reads zero, and its `version` starts at 1."

        Design: Corner/entities/create_contractor_computed_fields_input_ignored
        """
        resp = api_client.create_contractor(
            create_contractor_payload(name="Sierra Electric",
                                      credit_limit_cents=100_000,
                                      invoiced_balance_cents=99_999),
            CREDIT_MGR)
        data = validate_success(resp, expected_status=201)
        assert data["invoiced_balance_cents"] == 0, (
            f"client-supplied invoiced_balance_cents must be ignored; the "
            f"balance starts at zero, got {data['invoiced_balance_cents']}")


class TestCatalogItemCreation:

    def test_create_catalog_item_missing_sku_rejected(self):
        """PRD section 3.2: "Creating a **CatalogItem** requires a `sku` —
        unique across all catalog items, with duplicates rejected as
        `ERR_DUPLICATE_SKU`".
        PRD section 2.9: "Every write request is first checked for structural
        validity: required fields must be present".

        Design: Corner/entities/create_catalog_item_missing_sku_rejected
        """
        resp = api_client.create_catalog_item(
            create_catalog_item_payload(manufacturer_name="SquareD",
                                        sell_uom="EA", list_price_cents=2500),
            WH_MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_foot_item_missing_min_cut_rejected(self):
        """PRD section 3.2: "Items sold by the foot additionally require
        `reel_length_ft` (the full reel length in feet), `min_cut_ft` (the
        smallest cut the warehouse will sell), and `cut_charge_cents` (a flat
        charge applied at billing when a line ships less than a full reel);
        for `EA` items all three reel fields must be absent, and either
        mismatch is a request-shape error under §2.9."

        Design: Corner/entities/foot_item_missing_min_cut_rejected
        """
        resp = api_client.create_catalog_item(
            create_catalog_item_payload(
                sku="THHN-12CU", manufacturer_name="Southwire",
                sell_uom="FOOT", list_price_cents=45.25, reel_length_ft=500,
                cut_charge_cents=1500),
            WH_MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_duplicate_sku_rejected(self):
        """PRD section 3.2: "Creating a **CatalogItem** requires a `sku` —
        unique across all catalog items, with duplicates rejected as
        `ERR_DUPLICATE_SKU`".

        Design: Corner/validations/duplicate_sku_rejected
        """
        first = create_ea_item(sku="BRK-20A", manufacturer_name="SquareD",
                               list_price_cents=5000)
        assert_catalog_item(first)
        resp = api_client.create_catalog_item(
            create_catalog_item_payload(sku="BRK-20A",
                                        manufacturer_name="Eaton",
                                        sell_uom="EA", list_price_cents=2400),
            WH_MGR)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SKU)


class TestPagination:

    def test_contractors_list_pagination_envelope(self, sales_rep_headers):
        """PRD section 2.3: "List endpoints accept `limit` and `offset` query
        parameters."
        PRD section 2.3: "The `meta` object of every list response carries the
        pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/contractors_list_pagination_envelope
        """
        for name in ("C1", "C2", "C3"):
            create_contractor(name, 100_000)

        page1, meta1 = validate_paginated(
            api_client.list_contractors(sales_rep_headers,
                                        params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api_client.list_contractors(sales_rep_headers,
                                        params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestExistenceChecks:

    def test_get_unknown_quote_returns_not_found(self, sales_rep_headers):
        """PRD section 2.9: "After shape validation, every path identifier and
        every body foreign key is checked for existence, validated left to
        right; the first missing reference produces the corresponding 404 —
        `ERR_CONTRACTOR_NOT_FOUND`, `ERR_CATALOG_ITEM_NOT_FOUND`,
        `ERR_JOB_ACCOUNT_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`,
        `ERR_QUOTE_LINE_NOT_FOUND`, `ERR_SUBSTITUTION_REQUEST_NOT_FOUND`,
        `ERR_RELEASE_NOT_FOUND`, `ERR_REBATE_PROGRAM_NOT_FOUND`, or
        `ERR_REBATE_CLAIM_NOT_FOUND`, according to which reference failed
        first."

        Design: Corner/entities/get_unknown_quote_returns_not_found
        """
        resp = api_client.get_quote(NON_EXISTENT_UUID, sales_rep_headers)
        validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_FOUND)

    def test_create_quote_unknown_job_returns_not_found(self,
                                                        sales_rep_headers):
        """PRD section 2.9: "After shape validation, every path identifier and
        every body foreign key is checked for existence, validated left to
        right; the first missing reference produces the corresponding 404".

        Design: Corner/validations/create_quote_unknown_job_returns_not_found
        """
        resp = api_client.create_quote(
            {"job_account_id": NON_EXISTENT_UUID, "valid_until": "2027-01-01"},
            sales_rep_headers)
        validate_error(resp, ApiErrorId.ERR_JOB_ACCOUNT_NOT_FOUND)

    def test_get_unknown_release_returns_not_found(self, dispatcher_headers):
        """PRD section 2.9: "After shape validation, every path identifier and
        every body foreign key is checked for existence, validated left to
        right; the first missing reference produces the corresponding 404".

        Design: Corner/validations/get_unknown_release_returns_not_found
        """
        resp = api_client.get_release(NON_EXISTENT_UUID, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_RELEASE_NOT_FOUND)

    def test_decide_unknown_substitution_returns_not_found(
            self, branch_manager_headers):
        """PRD section 2.9: "After shape validation, every path identifier and
        every body foreign key is checked for existence, validated left to
        right; the first missing reference produces the corresponding 404".

        Design: Corner/validations/decide_unknown_substitution_returns_not_found
        """
        resp = api_client.decide_substitution_request(
            NON_EXISTENT_UUID, {"decision": "APPROVE"},
            branch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_REQUEST_NOT_FOUND)


class TestAuthContext:

    def test_unknown_role_header_unauthenticated(self):
        """PRD section 2.1: "A request missing either header, or presenting a
        role the system does not recognize, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400)."

        Design: Corner/validations/unknown_role_header_unauthenticated
        """
        resp = api_client.list_contractors(
            build_user_headers("test-superuser-1", "SuperUser"))
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT)


class TestRoleAuthorization:

    def test_salesrep_cannot_award_quote_forbidden(self):
        """PRD section 4: the award operation is authorized for
        `BranchManager` only.
        PRD section 2.1: "an authenticated caller attempting an operation
        outside their role is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/salesrep_cannot_award_quote_forbidden
        """
        contractor = create_contractor("Tango Electric", 100_000)
        item = create_ea_item()
        job = create_job_account(contractor["id"], "RBAC Job",
                                 jobsite_address="50 Site Rd")
        quote = create_submitted_quote(job["id"], [(item["id"], 1, 5000)])
        resp = api_client.award_quote(quote["id"], SALES_REP)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_contractor_cannot_release_on_others_job_forbidden(self):
        """PRD section 2.1: "a `Contractor` caller may act only on job
        accounts whose `contractor_id` equals their `X-User-ID` — most
        materially when requesting or cancelling a release — and any attempt
        to act against another contractor's account is rejected with
        `ERR_FORBIDDEN`."

        Design: Corner/rbac/contractor_cannot_release_on_others_job_forbidden
        """
        contractor_a = create_contractor("A Electric", 100_000)
        contractor_b = create_contractor("B Electric", 100_000)
        item = create_ea_item()
        job_b = create_job_account(contractor_b["id"], "B Job",
                                   jobsite_address="51 Site Rd")
        quote_b = create_awarded_quote(job_b["id"],
                                       [(item["id"], 1, 5000)])
        resp = api_client.create_release(
            {
                "job_account_id": job_b["id"],
                "quote_id": quote_b["id"],
                "expected_job_account_version": job_b["version"],
                "lines": [{"catalog_item_id": item["id"], "qty": 1}],
            },
            make_contractor_headers(contractor_a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_warehouse_manager_cannot_decide_substitution_forbidden(self):
        """PRD section 4: the substitution decide operation is authorized for
        `BranchManager` only.
        PRD section 2.1: "an authenticated caller attempting an operation
        outside their role is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/warehouse_manager_cannot_decide_substitution_forbidden
        """
        ctx = setup_draft_quote_with_substitution()
        resp = api_client.decide_substitution_request(
            ctx["sub"]["id"], {"decision": "APPROVE"}, WH_MGR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_rebate_clerk_cannot_invoice_forbidden(self):
        """PRD section 4: the invoice operation is authorized for
        `CreditManager` only.
        PRD section 2.1: "an authenticated caller attempting an operation
        outside their role is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/rebate_clerk_cannot_invoice_forbidden
        """
        ctx = setup_delivered_release()
        resp = api_client.invoice_release(ctx["release"]["id"], REBATE_CLERK)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        release = get_release(ctx["release"]["id"])
        assert release["status"] == "DELIVERED", (
            f"release must remain DELIVERED after a forbidden invoice, got "
            f"{release['status']}")
