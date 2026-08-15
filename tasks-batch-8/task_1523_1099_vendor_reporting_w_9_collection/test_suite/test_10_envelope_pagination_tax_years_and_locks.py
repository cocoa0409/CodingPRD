"""Response envelope, pagination and listing filters, authentication context,
TaxYear half-open boundaries, the closed-year payment/void gates, and the
accepted-return payment lock."""
import pytest

from test_helpers import (
    ADMIN,
    CLERK,
    IRS,
    SPEC,
    ApiErrorId,
    assert_tax_year,
    assert_vendor,
    create_accepted_return,
    create_matched_vendor,
    create_payment,
    create_tax_year,
    create_tax_year_payload,
    create_vendor,
    create_vendor_payload,
    make_tax_specialist_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestResponseEnvelope:
    def test_response_envelope_shape(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."
        PRD §2.3: "The `limit` parameter specifies the maximum number of items to
        return; if not provided it defaults to 10, with a minimum of 1 and a maximum
        of 100. The `offset` parameter specifies the number of items to skip and
        defaults to 0."

        Design: Corner/endpoints/c_response_envelope_shape
        """
        create_resp = api.create_vendor(
            create_vendor_payload(legal_name="Env V", entity_classification="C_CORP"),
            CLERK,
        )
        assert create_resp.status_code == 201
        body = create_resp.json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["response_type"] == "object"
        assert_vendor(body["data"])

        list_resp = api.list_vendors(CLERK, params={})
        assert list_resp.status_code == 200
        list_body = list_resp.json()
        assert list_body["response_type"] == "array"
        meta = list_body["meta"]
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 1
        assert meta["has_more"] is False

    def test_pagination_limit_offset_window(self, api):
        """PRD §2.3: "Paginated list responses include the following fields in the
        `meta` object of the response envelope: `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/endpoints/c_pagination_limit_offset_window
        """
        create_vendor(legal_name="Pg A", entity_classification="C_CORP")
        create_vendor(legal_name="Pg B", entity_classification="S_CORP")
        create_vendor(legal_name="Pg C", entity_classification="PARTNERSHIP")

        page1, meta1 = validate_paginated(api.list_vendors(CLERK, params={"limit": 2, "offset": 0}))
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert len(page1) == 2

        page2, meta2 = validate_paginated(api.list_vendors(CLERK, params={"limit": 2, "offset": 2}))
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert len(page2) == 1

    def test_list_filter_by_vendor(self, api):
        """PRD §3.4: "Payments may be listed with the `vendor_id`, `tax_year`,
        `payment_type`, `source_system`, and `status` filters."

        Design: Corner/endpoints/c_list_filter_by_vendor
        """
        create_tax_year()
        vendor_a, _ = create_matched_vendor(legal_name="Filt A", tin="111000111")
        vendor_b, _ = create_matched_vendor(legal_name="Filt B", tin="222000222")
        create_payment(vendor_a["id"], amount_cents=1000, payment_date="2025-06-01T00:00:00Z")
        create_payment(vendor_a["id"], amount_cents=2000, payment_date="2025-06-02T00:00:00Z",
                       payment_type="RENT", source_system="MANUAL")
        create_payment(vendor_b["id"], amount_cents=3000, payment_date="2025-06-03T00:00:00Z",
                       source_system="CORP_CARD")

        rows, meta = validate_paginated(
            api.list_payments(SPEC, params={"vendor_id": vendor_a["id"]})
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2
        assert all(p["vendor_id"] == vendor_a["id"] for p in rows)


class TestAuthenticationContext:
    def test_missing_auth_header_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or carrying an empty value
        for either, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/c_missing_auth_header_returns_400
        """
        # No X-User-ID / X-User-Role headers at all.
        resp = api.create_vendor(
            create_vendor_payload(legal_name="NoAuth", entity_classification="C_CORP"),
            {},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)

    def test_taxspecialist_cannot_set_clock(self, api):
        """PRD §2.4: "A `TaxAdmin`-only test-driving capability advances the clock to
        a supplied `to_iso8601` instant and answers with the resulting
        `current_utc`."
        PRD §2.1: "Access to every endpoint is restricted by role, and an attempt to
        perform an action outside the caller's designated role is rejected with
        `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/roles/c_taxspecialist_cannot_set_clock
        """
        resp = api.set_clock(
            {"to_iso8601": "2026-01-01T00:00:00Z"}, make_tax_specialist_headers("spec-1")
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)


class TestTaxYearBoundaries:
    def test_tax_year_half_open_adjacency(self, api):
        """PRD §3.1: "Creation is rejected with `ERR_INVALID_REQUEST` when the
        exclusive end does not fall after the start or when `tax_year` duplicates an
        existing row, and with `ERR_TAX_YEAR_OVERLAP` when the new half-open period
        intersects any existing tax year's period — under half-open semantics a
        period that merely touches a neighbor's endpoint does not overlap it."

        Design: Difficulty/resource_temporal_overlap/tax_year_half_open_adjacency
        """
        first = create_tax_year(tax_year=2025)
        assert_tax_year(first)

        # Starts one day before the existing period's exclusive end: intersects.
        overlapping = api.create_tax_year(
            create_tax_year_payload(
                tax_year=2026,
                period_start="2025-12-31T00:00:00Z",
                period_end_exclusive="2027-01-01T00:00:00Z",
                recipient_copy_deadline="2027-01-31T00:00:00Z",
            ),
            ADMIN,
        )
        validate_error(overlapping, ApiErrorId.ERR_TAX_YEAR_OVERLAP, 409)

        # Starts exactly at the exclusive end: adjacent, not overlapping.
        adjacent = api.create_tax_year(
            create_tax_year_payload(
                tax_year=2026,
                period_start="2026-01-01T00:00:00Z",
                period_end_exclusive="2027-01-01T00:00:00Z",
                recipient_copy_deadline="2027-01-31T00:00:00Z",
            ),
            ADMIN,
        )
        created = validate_success(adjacent, 201)
        assert_tax_year(created)
        assert created["status"] == "OPEN"

    def test_tax_year_duplicate_and_interior_overlap_rejected(self, api):
        """PRD §3.1: "Creation is rejected with `ERR_INVALID_REQUEST` when the
        exclusive end does not fall after the start or when `tax_year` duplicates an
        existing row, and with `ERR_TAX_YEAR_OVERLAP` when the new half-open period
        intersects any existing tax year's period..."

        Design: Difficulty/resource_temporal_overlap/tax_year_half_open_adjacency
        """
        create_tax_year(tax_year=2025)

        # An interior-start period intersects the existing half-open window.
        interior = api.create_tax_year(
            create_tax_year_payload(
                tax_year=2026,
                period_start="2025-06-01T00:00:00Z",
                period_end_exclusive="2027-01-01T00:00:00Z",
                recipient_copy_deadline="2027-01-31T00:00:00Z",
            ),
            ADMIN,
        )
        validate_error(interior, ApiErrorId.ERR_TAX_YEAR_OVERLAP, 409)

        # A disjoint earlier period is accepted.
        earlier = api.create_tax_year(
            create_tax_year_payload(
                tax_year=2024,
                period_start="2024-01-01T00:00:00Z",
                period_end_exclusive="2025-01-01T00:00:00Z",
                recipient_copy_deadline="2025-01-31T00:00:00Z",
            ),
            ADMIN,
        )
        validate_success(earlier, 201)

    def test_tax_year_inverted_period_returns_invalid_request(self, api):
        """PRD §3.1: "Creation is rejected with `ERR_INVALID_REQUEST` when the
        exclusive end does not fall after the start or when `tax_year` duplicates an
        existing row..."

        Design: Corner/entities/c_tax_year_inverted_period_returns_invalid_request
        """
        resp = api.create_tax_year(
            create_tax_year_payload(
                tax_year=2025,
                period_start="2025-06-01T00:00:00Z",
                period_end_exclusive="2025-01-01T00:00:00Z",
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestClosedYearGates:
    def test_payment_blocked_when_tax_year_closed(self, api):
        """PRD §3.1: "Once closed, payments whose `payment_date` falls inside the
        year's half-open period can no longer be created (`ERR_TAX_YEAR_CLOSED`) or
        voided (`ERR_PAYMENT_NOT_VOIDABLE`)."

        Design: Difficulty/cross_entity_state_dependency/payment_blocked_when_tax_year_closed
        """
        year = create_tax_year()
        vendor, _ = create_matched_vendor(legal_name="Gate V", tin="787878787")

        before = api.create_payment(
            {
                "vendor_id": vendor["id"],
                "source_system": "AP_ERP",
                "payment_type": "SERVICE",
                "amount_cents": 1000,
                "payment_date": "2025-06-01T00:00:00Z",
            },
            CLERK,
        )
        validate_success(before, 201)

        validate_success(api.close_tax_year(year["id"], ADMIN), 200)

        after = api.create_payment(
            {
                "vendor_id": vendor["id"],
                "source_system": "AP_ERP",
                "payment_type": "SERVICE",
                "amount_cents": 1000,
                "payment_date": "2025-06-02T00:00:00Z",
            },
            CLERK,
        )
        validate_error(after, ApiErrorId.ERR_TAX_YEAR_CLOSED, 409)

    def test_void_blocked_when_tax_year_closed(self, api):
        """PRD §3.1: "Once closed, payments whose `payment_date` falls inside the
        year's half-open period can no longer be created (`ERR_TAX_YEAR_CLOSED`) or
        voided (`ERR_PAYMENT_NOT_VOIDABLE`)."

        Design: Difficulty/cross_entity_state_dependency/payment_blocked_when_tax_year_closed
        """
        year = create_tax_year()
        vendor, _ = create_matched_vendor(legal_name="GateV2", tin="787878787")
        payment = create_payment(vendor["id"], amount_cents=1000,
                                 payment_date="2025-06-01T00:00:00Z")
        validate_success(api.close_tax_year(year["id"], ADMIN), 200)

        resp = api.void_payment(payment["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_VOIDABLE, 409)

        after = validate_success(api.get_payment(payment["id"], CLERK), 200)
        assert after["status"] == "POSTED"


class TestAcceptedReturnPaymentLock:
    def test_void_payment_in_accepted_return_returns_409(self, api):
        """PRD §3.4: "Voiding is blocked with `ERR_PAYMENT_NOT_VOIDABLE` when the
        covering tax year is `CLOSED`, when the payment is included in any
        `ACCEPTED` return, or when the payment's withholding entry has already been
        `REMITTED`."

        Design: Corner/validations/c_void_payment_in_accepted_return_returns_409
        """
        create_tax_year()
        _vendor, payment, tax_return, _t = create_accepted_return(
            legal_name="LockPay V", tin="333777333"
        )
        assert tax_return["federal_status"] == "ACCEPTED"

        resp = api.void_payment(payment["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_VOIDABLE, 409)

        after = validate_success(api.get_payment(payment["id"], CLERK), 200)
        assert after["status"] == "POSTED"
