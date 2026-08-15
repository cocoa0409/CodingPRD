"""Platform-wide behavior and fund/share-class/capital-activity setup rules."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_fund,
    create_fund,
    create_fund_payload,
    create_security,
    create_share_class,
    is_valid_uuid,
    open_position,
    set_logical_clock,
    subscribe_shares,
    validate_error,
    validate_paginated,
    validate_success,
)

CTRL = TEST_USERS["fund_controller_headers"]
ACCT = TEST_USERS["fund_accountant_headers"]
PC = TEST_USERS["pricing_committee_headers"]


def test_fund_creation_applies_system_defaults(api):
    """PRD §3.1: "A newly created fund has never been through a fiscal-year
    close, so its `last_closed_fiscal_year_end` is null until the first close
    completes."
    PRD §2.5: "`id` (string): a server-minted UUID with no type prefix."

    Design: Corner/entities/fund_creation_applies_system_defaults
    """
    resp = api.create_fund(create_fund_payload(), CTRL)
    data = validate_success(resp, 201)
    assert_fund(data)
    assert is_valid_uuid(data["id"])
    assert data["last_closed_fiscal_year_end"] is None


def test_response_envelope_shape(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the response envelope."

    Design: Corner/endpoints/response_envelope_shape
    """
    resp = api.create_fund(create_fund_payload(), CTRL)
    data = validate_success(resp, 201)
    body = resp.json()
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["response_type"] == "object"
    assert body["data"]["id"] == data["id"]

    err_resp = api.get_security(NON_EXISTENT_UUID, CTRL)
    err_body = err_resp.json()
    assert err_body["response_type"] == "error"
    validate_error(err_resp, ApiErrorId.ERR_NOT_FOUND, 404)

    list_resp = api.list_share_classes(CTRL)
    _, meta = validate_paginated(list_resp)
    assert meta["limit"] == 10, "default limit is 10"
    assert meta["offset"] == 0, "default offset is 0"


def test_pagination_limit_offset_has_more(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The
    `offset` parameter sets the number of items skipped and defaults to 0."
    PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the response envelope."

    Design: Corner/complexity_layers/pagination_limit_offset_has_more
    """
    fund = create_fund()
    share_class = create_share_class(fund["id"])
    sec_a = create_security(security_identifier="CUSIP0001")
    sec_b = create_security(security_identifier="CUSIP0002")
    open_position(share_class["id"], sec_a["id"], quantity=1000)
    open_position(share_class["id"], sec_b["id"], quantity=500)

    page1, meta1 = validate_paginated(
        api.list_positions(CTRL, params={"share_class_id": share_class["id"],
                                         "limit": 1, "offset": 0})
    )
    assert len(page1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True
    assert meta1["limit"] == 1
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_positions(CTRL, params={"share_class_id": share_class["id"],
                                         "limit": 1, "offset": 1})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False
    assert meta2["offset"] == 1

    # Both pages carry only this class's positions and partition the two rows.
    assert page1[0]["share_class_id"] == share_class["id"]
    assert page2[0]["share_class_id"] == share_class["id"]
    assert page1[0]["id"] != page2[0]["id"]
    assert sorted([page1[0]["quantity"], page2[0]["quantity"]]) == [500, 1000]


def test_share_class_create_missing_required_returns_400(api):
    """PRD §2.9: "4. Request-body shape — required fields present, no unknown
    fields (system-managed fields such as `id`, `created_at`, `updated_at`, and
    `version` included), correct types and enum values, and numeric ranges
    respected (a price greater than zero, a creation quantity greater than
    zero, a counterparty quantity of zero or more, a cap rate greater than
    zero, an annual accrual rate greater than zero, a recovery window of one to
    thirty-six months, period and effectiveness end dates not before their
    start dates, positive amounts, positive share counts where supplied, and a
    well-formed clock timestamp) — `ERR_VALIDATION` (HTTP 400)."
    PRD §3.1: "Each class references its fund via `fund_id`"

    Design: Corner/entities/share_class_create_missing_required_returns_400
    """
    fund = create_fund()
    resp = api.create_share_class(
        {"class_ticker": "ALPHXI", "distribution_frequency": "QUARTERLY"}, CTRL
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)
    classes, meta = validate_paginated(
        api.list_share_classes(CTRL, params={"fund_id": fund["id"]})
    )
    assert classes == [] and meta["total_count"] == 0


def test_get_share_class_not_found_returns_404(api):
    """PRD §2.9: "Path resolution — every identifier in the URL path must
    resolve to an existing resource, validated left to right; the first
    unresolved identifier yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_share_class_not_found_returns_404
    """
    resp = api.get_share_class(NON_EXISTENT_UUID, CTRL)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_duplicate_fund_ticker_rejected(api):
    """PRD §3.1: "a `ticker` that must be unique across all funds (a duplicate
    is rejected with `ERR_TICKER_ALREADY_EXISTS`, HTTP 409)"

    Design: Corner/validations/duplicate_fund_ticker_rejected
    """
    create_fund()
    resp = api.create_fund(create_fund_payload(fund_name="Alpha Fund II"), CTRL)
    validate_error(resp, ApiErrorId.ERR_TICKER_ALREADY_EXISTS, 409)


def test_redemption_beyond_shares_rejected(api):
    """PRD §3.1: "redeeming exactly all outstanding shares is allowed, but a
    redemption larger than the current `shares_outstanding` is rejected with
    `ERR_REDEMPTION_EXCEEDS_SHARES` (HTTP 422)."

    Design: Corner/validations/redemption_beyond_shares_rejected
    """
    fund = create_fund()
    share_class = create_share_class(fund["id"])
    subscribe_shares(share_class["id"], 10000)

    resp = api.post_capital_activity(
        share_class["id"],
        {"activity_type": "REDEMPTION", "activity_date": "2026-08-04",
         "shares": 10001},
        ACCT,
    )
    validate_error(resp, ApiErrorId.ERR_REDEMPTION_EXCEEDS_SHARES, 422)

    ok = api.post_capital_activity(
        share_class["id"],
        {"activity_type": "REDEMPTION", "activity_date": "2026-08-04",
         "shares": 10000},
        ACCT,
    )
    data = validate_success(ok, 200)
    assert data["shares_outstanding"] == 0


def test_pricing_committee_cannot_create_fund(api):
    """PRD §2.1: "A request whose role is not among the roles authorized for
    the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "A `PricingCommittee` member governs valuation: approving price
    observations and issuing fair-value overrides."

    Design: Corner/rbac/pricing_committee_cannot_create_fund
    """
    resp = api.create_fund(create_fund_payload(), PC)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_create_fund_missing_auth_header_returns_401(api):
    """PRD §2.1: "A request missing either header, or carrying a role outside
    this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/create_fund_missing_auth_header_returns_401
    """
    resp = api.create_fund(create_fund_payload(), headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_clock_regression_rejected(api):
    """PRD §2.4: "The clock moves strictly forward: a request whose target
    instant is not strictly after the current reading is rejected with
    `ERR_CLOCK_REGRESSION` (HTTP 422)."

    Design: Corner/validations/clock_regression_rejected
    """
    set_logical_clock("2026-08-04T00:00:00Z")
    resp = api.set_clock({"to_iso8601": "2026-08-03T00:00:00Z"}, CTRL)
    validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION, 422)
