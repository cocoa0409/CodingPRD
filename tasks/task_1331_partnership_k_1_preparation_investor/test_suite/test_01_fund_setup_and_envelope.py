"""Fund configuration, tax-year setup, response envelope, and entry validation."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, make_tax_preparer_headers,
    create_fund_payload, create_tax_year_payload, create_partner_payload,
    create_fund, create_partner, create_tax_year, close_books, get_tax_year,
    assert_fund, assert_tax_year,
)

ADMIN = TEST_USERS["fund_tax_admin_headers"]
PREPARER = TEST_USERS["tax_preparer_headers"]
REVIEWER = TEST_USERS["tax_reviewer_headers"]

FEE_FUND = {
    "management_fee_rate_bps": 100,
    "fee_discount_threshold_cents": 5000000000,
    "fee_discount_bps": 5000,
}


class TestFundCreationAndEnvelope:
    def test_create_fund_returns_201_with_system_fields(self, api):
        """PRD §4: "Operations that create a new resource return `201 Created`;
        this includes creating funds, tax years, partners, capital events (and
        the mirror event produced by a reversal), transfers, allocation runs,
        special allocations, composite filings, withholding accruals, K-1
        generation, amendments, and tickets."
        PRD §2.4: "The `id` is a server-minted UUID with no type prefix. The
        `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with
        three fractional digits, stamped from the logical clock at creation and
        at every later modification."

        Design: Corner/entities/create_fund_returns_201_with_system_fields
        """
        payload = create_fund_payload(
            legal_name="Fund C1",
            foreign_ownership_cap_pct_bps=5000,
            management_fee_rate_bps=100,
            fee_discount_threshold_cents=5000000000,
            fee_discount_bps=5000,
        )
        resp = api.create_fund(payload, ADMIN)
        data = validate_success(resp, 201)
        assert_fund(data)
        for field, value in payload.items():
            assert data[field] == value, f"Fund.{field} should echo input {value!r}, got {data[field]!r}"

    def test_success_envelope_shape_on_create(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/endpoints/success_envelope_shape_on_create
        """
        resp = api.create_fund(create_fund_payload(legal_name="Fund E1"), ADMIN)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "api_request_id must start with 'req_'"
        )
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["response_type"] == "object"
        assert isinstance(body["data"]["id"], str) and body["data"]["id"]


class TestManagementFeeEvaluationOrder:
    def _fund_with_one_gp(self, api):
        fund = create_fund(fund_overrides=FEE_FUND)
        create_partner(
            fund["id"],
            legal_name="GP", partner_type="US_ENTITY", partner_class="GENERAL",
            residency_state="DE", ownership_pct_bps=10000,
            capital_commitment_cents=100000000, admission_date="2025-01-01",
        )
        return fund

    def test_fee_no_discount_when_gross_equals_threshold(self, api):
        """PRD §3.1: "Third, the discount applies if and only if
        `gross_ordinary_income_cents` is strictly below
        `fee_discount_threshold_cents` — income exactly equal to the threshold
        receives no discount."
        PRD §3.1: "Fifth, `net_ordinary_income_cents` is
        `gross_ordinary_income_cents` minus `management_fee_cents`."

        Design: Difficulty/combinatorial_formula/management_fee_evaluation_order_boundary
        """
        fund = self._fund_with_one_gp(api)
        resp = api.create_tax_year(
            create_tax_year_payload(
                fund["id"], year=2024,
                gross_ordinary_income_cents=5000000000,
                capital_gain_cents=0, interest_income_cents=0,
            ),
            ADMIN,
        )
        ty = validate_success(resp, 201)
        assert_tax_year(ty)
        # fee base 100000000 x 100bps = 1000000; gross == threshold -> no discount
        assert ty["management_fee_cents"] == 1000000, (
            f"gross == threshold must receive no discount: {ty['management_fee_cents']}"
        )
        assert ty["net_ordinary_income_cents"] == 4999000000

    def test_fee_discount_applies_one_cent_below_threshold(self, api):
        """PRD §3.1: "Third, the discount applies if and only if
        `gross_ordinary_income_cents` is strictly below
        `fee_discount_threshold_cents` — income exactly equal to the threshold
        receives no discount."
        PRD §3.1: "Fourth, `management_fee_cents` is, when the discount
        applies, the gross fee multiplied by ten thousand minus
        `fee_discount_bps` and divided by ten thousand, rounded half-up;
        otherwise it is the gross fee unchanged."

        Design: Difficulty/combinatorial_formula/management_fee_evaluation_order_boundary
        """
        fund = self._fund_with_one_gp(api)
        resp = api.create_tax_year(
            create_tax_year_payload(
                fund["id"], year=2025,
                gross_ordinary_income_cents=4999999999,
                capital_gain_cents=0, interest_income_cents=0,
            ),
            ADMIN,
        )
        ty = validate_success(resp, 201)
        # gross fee 1000000, halved by the 5000bps discount -> 500000
        assert ty["management_fee_cents"] == 500000, (
            f"gross one cent below threshold must be discounted: {ty['management_fee_cents']}"
        )
        assert ty["net_ordinary_income_cents"] == 4999499999


class TestTaxYearCreationRules:
    def test_duplicate_tax_year_rejected(self, api):
        """PRD §3.1: "Only one tax year may exist per fund and calendar year; a
        duplicate is rejected with `ERR_DUPLICATE_TAX_YEAR`."

        Design: Corner/validations/duplicate_tax_year_rejected
        """
        fund = create_fund()
        create_tax_year(fund["id"], year=2025, gross_ordinary_income_cents=0)
        resp = api.create_tax_year(
            create_tax_year_payload(fund["id"], year=2025, gross_ordinary_income_cents=1),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_TAX_YEAR)

    def test_close_books_without_partners_rejected(self, api):
        """PRD §3.5: "Closing the books, performed by a `FundTaxAdmin`, moves
        the year from `OPEN` to `BOOKS_CLOSED` and requires at least one
        `ACTIVE` partner in the fund, else `ERR_NO_ALLOCABLE_PARTNERS`; it
        increments the tax year’s `version`."

        Design: Corner/validations/close_books_without_partners_rejected
        """
        fund = create_fund()
        ty = create_tax_year(fund["id"], year=2025, gross_ordinary_income_cents=0)
        resp = api.close_books(ty["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_NO_ALLOCABLE_PARTNERS)
        after = get_tax_year(ty["id"])
        assert after["status"] == "OPEN", f"tax year must remain OPEN, got {after['status']}"

    def test_close_books_twice_returns_invalid_state(self, api):
        """PRD §2.8: "State-transition legality — the requested transition is
        declared from the resource’s current state, else
        `ERR_INVALID_STATE_TRANSITION`."
        PRD §3.5: "Closing the books, performed by a `FundTaxAdmin`, moves the
        year from `OPEN` to `BOOKS_CLOSED` and requires at least one `ACTIVE`
        partner in the fund, else `ERR_NO_ALLOCABLE_PARTNERS`; it increments
        the tax year’s `version`."

        Design: Corner/state_machines/close_books_twice_returns_invalid_state
        """
        fund = create_fund()
        create_partner(fund["id"], legal_name="P")
        ty = create_tax_year(fund["id"], year=2025, gross_ordinary_income_cents=0)
        closed = close_books(ty["id"])
        resp = api.close_books(ty["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_tax_year(ty["id"])
        assert after["version"] == closed["version"], (
            f"rejected close-books must not bump version: {closed['version']} -> {after['version']}"
        )
        assert after["status"] == "BOOKS_CLOSED"


class TestEntryValidation:
    def test_missing_auth_headers_returns_400(self, api):
        """PRD §2.8: "Authentication context — the `X-User-ID` and
        `X-User-Role` headers are present and the role is recognized, else
        `ERR_MISSING_AUTH_CONTEXT`."

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        resp = api.get_fund(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_CONTEXT)

    def test_not_found_beats_state_check(self, api):
        """PRD §2.8: "Every request is evaluated against a fixed validation
        pipeline and is rejected with the first failing check in the order
        below; later checks never mask earlier ones."
        PRD §2.8: "Path existence — every identifier in the path resolves to an
        existing resource, validated left to right, else `ERR_NOT_FOUND`."

        Design: Corner/validations/not_found_beats_state_check
        """
        resp = api.approve_k1(NON_EXISTENT_UUID, REVIEWER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
