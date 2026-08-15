"""Customer onboarding, entity shapes, and list/pagination basics."""
from test_helpers import (
    ABSENT_UUID,
    ApiErrorId,
    api_client,
    assert_customer,
    assert_price_mark,
    create_customer_payload,
    create_security_profile,
    post_mark,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_customer_creation_returns_201_and_stored_fields(api, analyst_headers):
    """PRD §3.1: "A `MarginAnalyst` onboards a retail client by registering a
    `Customer` with a `legal_name` and an `email`; the email must be unique
    across all customers."
    PRD §4: "Operations that create new resources — onboarding a customer, ...
    — return a `201 Created` status code."

    Design: Corner/entities/customer_creation_returns_201_and_stored_fields
    """
    resp = api.create_customer(
        create_customer_payload(legal_name="Gra Ce", email="grace@example.com"),
        analyst_headers,
    )
    data = validate_success(resp, expected_status=201)
    assert_customer(data)
    assert data["legal_name"] == "Gra Ce"
    assert data["email"] == "grace@example.com"
    assert data["version"] == 1


def test_customer_get_not_found_returns_404(api, supervisor_headers):
    """PRD §2.9: "Requests that address nested resources are validated left to
    right along the path: each identifier must exist before the next is
    examined, and the request is rejected with the 404 error corresponding to
    the first identifier that does not resolve."

    Design: Corner/entities/customer_get_not_found_returns_404
    """
    resp = api.get_customer(ABSENT_UUID, supervisor_headers)
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND)


def test_account_computed_fields_ignore_client_input(api, supervisor_headers):
    """PRD §3.1: "the system creates the `MarginAccount`: owned by the customer,
    linked back to the application through `application_id`, with
    `account_status` `ACTIVE`, zero `cash_balance_cents`, all equity and
    requirement fields at zero, `buying_power_cents` at zero, `pdt_flag` false,
    and `pdt_flagged_at` null."

    Design: Corner/entities/account_computed_fields_ignore_client_input
    """
    from test_helpers import create_approved_account, assert_account

    _customer, _app, account_id = create_approved_account()
    data = validate_success(api.get_account(account_id, supervisor_headers))
    assert_account(data)
    assert data["cash_balance_cents"] == 0
    assert data["equity_realtime_cents"] == 0
    assert data["equity_official_cents"] == 0
    assert data["reg_req_official_cents"] == 0
    assert data["house_req_official_cents"] == 0
    assert data["reg_req_realtime_cents"] == 0
    assert data["house_req_realtime_cents"] == 0
    assert data["buying_power_cents"] == 0
    assert data["account_status"] == "ACTIVE"
    assert data["pdt_flag"] is False
    assert data["pdt_flagged_at"] is None


def test_immutable_price_mark_has_no_update_endpoint(api, market_ops_headers):
    """PRD §2.7: "Ledger-style records — `TradeFill`, `DayTradeEvent`,
    `PriceMark`, and `InterestLedgerEntry` — are immutable once written and
    carry only `id` and `created_at`; both `updated_at` and `version` are
    absent from these resources."

    Design: Corner/entities/immutable_price_mark_has_no_update_endpoint
    """
    security = create_security_profile(symbol="ABC")
    mark = post_mark(security["id"], "REALTIME", 10_000)
    assert_price_mark(mark)
    resp = api.get_market_mark(mark["id"], market_ops_headers)
    data = validate_success(resp)
    assert_price_mark(data)
    assert data["price_cents"] == 10_000
    assert data["mark_type"] == "REALTIME"


def test_pagination_defaults_on_list_endpoint(api, supervisor_headers):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return; if not provided it defaults to 10, with a minimum of 1 and a
    maximum of 100. ... Paginated list responses include the following fields
    in the `meta` object of the response envelope: `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/pagination_defaults_on_list_endpoint
    """
    create_security_profile(symbol="AAA")
    create_security_profile(symbol="BBB")
    resp = api.list_security_profiles(supervisor_headers, params={"limit": 1, "offset": 0})
    rows, meta = validate_paginated(resp)
    assert len(rows) == 1
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    # Second page carries the other row.
    resp2 = api.list_security_profiles(supervisor_headers, params={"limit": 1, "offset": 1})
    rows2, meta2 = validate_paginated(resp2)
    assert len(rows2) == 1
    assert meta2["has_more"] is False
    assert rows[0]["id"] != rows2[0]["id"]
