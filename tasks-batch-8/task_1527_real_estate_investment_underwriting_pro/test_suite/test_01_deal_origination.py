"""Deal origination and intake (PRD §3.1): creation, retrieval, uniqueness."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_deal,
    create_deal_payload,
    is_valid_uuid,
    validate_error,
    validate_success,
)

ANALYST_ID = "u-analyst-1"


def test_deal_create_returns_server_minted_id_and_draft_status(api, analyst_headers):
    """PRD §3.1: "The server records the caller's `X-User-ID` onto `deal.analyst_id`
    and initializes `status` to `DRAFT`."
    PRD §2.4: "`id` is a server-minted UUID with no type prefix."
    PRD §2.4: "`version` is an integer that starts at 1 on creation and increments
    by exactly 1 on every mutation of the resource."

    Design: Corner/entities/deal_create_returns_server_minted_id_and_draft_status
    """
    payload = create_deal_payload(
        deal_code="D-COR1",
        deal_name="Corner",
        strategy="CORE",
        target_purchase_price_cents=100_000_000,
    )
    deal = validate_success(api.create_deal(payload, analyst_headers), 201)
    assert_deal(deal)
    assert deal["status"] == "DRAFT", f"expected DRAFT, got {deal['status']}"
    assert deal["version"] == 1, f"expected version 1, got {deal['version']}"
    assert deal["analyst_id"] == ANALYST_ID, (
        f"analyst_id must be stamped from X-User-ID, got {deal['analyst_id']!r}"
    )
    assert is_valid_uuid(deal["id"]), f"id must be a UUID with no prefix, got {deal['id']!r}"


def test_deal_get_returns_persisted_entity(api, analyst_headers):
    """PRD §4: "GET | `/re-underwriting/deals/{id}` | Fetch a single deal".
    PRD §3.1: "The analyst supplies a `deal_code` (a human-readable identifier
    unique across the firm, between 4 and 32 characters), a short `deal_name`,
    the investment `strategy` (one of `CORE`, `CORE_PLUS`, `VALUE_ADD`,
    `OPPORTUNISTIC`), and the proposed `target_purchase_price_cents`."

    Design: Corner/entities/deal_get_returns_persisted_entity
    """
    created = validate_success(
        api.create_deal(
            create_deal_payload(
                deal_code="D-COR2",
                deal_name="Get Test",
                strategy="VALUE_ADD",
                target_purchase_price_cents=200_000_000,
            ),
            analyst_headers,
        ),
        201,
    )
    fetched = validate_success(api.get_deal(created["id"], analyst_headers), 200)
    assert_deal(fetched)
    assert fetched["id"] == created["id"]
    assert fetched["deal_code"] == "D-COR2"
    assert fetched["deal_name"] == "Get Test"
    assert fetched["strategy"] == "VALUE_ADD"
    assert fetched["target_purchase_price_cents"] == 200_000_000


def test_deal_get_nonexistent_returns_404(api, analyst_headers):
    """PRD §2.6: "If any path segment does not resolve, the request is rejected
    with `ERR_NOT_FOUND` (HTTP 404) before any other check runs."

    Design: Corner/entities/deal_get_nonexistent_returns_404
    """
    res = api.get_deal(NON_EXISTENT_UUID, analyst_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_deal_create_missing_deal_code_returns_400(api, analyst_headers):
    """PRD §3.1: "The analyst supplies a `deal_code` (a human-readable identifier
    unique across the firm, between 4 and 32 characters), a short `deal_name`,
    the investment `strategy` (one of `CORE`, `CORE_PLUS`, `VALUE_ADD`,
    `OPPORTUNISTIC`), and the proposed `target_purchase_price_cents`."
    PRD §2.8: "9. Business constraint checks (duplicate `deal_code` —
    `ERR_DUPLICATE_DEAL_CODE` (409); duplicate `(property_id, period_month)` for a
    rent roll or `(property_id, period_year, category)` for an operating expense —
    `ERR_DUPLICATE_PERIOD` (409); out-of-range numerics such as
    `occupancy_stress_pct`, `exit_cap_rate_bps`, `amortization_years`,
    `hold_period_years` — `ERR_INVALID_REQUEST` (400))."

    Design: Corner/entities/deal_create_missing_required_field_returns_400
    """
    payload = {
        "deal_name": "X",
        "strategy": "CORE",
        "target_purchase_price_cents": 100,
    }
    res = api.create_deal(payload, analyst_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_duplicate_deal_code_rejected(api, analyst_headers):
    """PRD §3.1: "If another deal already carries the same `deal_code`, the create
    is rejected with `ERR_DUPLICATE_DEAL_CODE` (HTTP 409)."

    Design: Corner/errors/err_duplicate_deal_code_triggered
    """
    first = create_deal_payload(
        deal_code="D-DUP", deal_name="First", strategy="CORE",
        target_purchase_price_cents=100,
    )
    validate_success(api.create_deal(first, analyst_headers), 201)
    second = create_deal_payload(
        deal_code="D-DUP", deal_name="Second", strategy="VALUE_ADD",
        target_purchase_price_cents=200,
    )
    res = api.create_deal(second, analyst_headers)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_DEAL_CODE)
