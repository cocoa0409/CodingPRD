"""Catalog config and account basics: creation, retrieval, listing, identity,
defaults, immutability, and parent-reference resolution (PRD §2.4, §3.1, §3.2)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_product,
    retire_product,
    create_account,
    create_active_account,
    create_and_post_transaction,
    list_account_lots,
)

_ADMIN = TEST_USERS["program_admin_headers"]


def test_create_card_product_returns_201_with_all_fields(api):
    """PRD §3.1: "A product is created in `status` `ACTIVE`; the `status`
    enumerates `ACTIVE` and `RETIRED`."
    PRD §2.4: "The `version` field is an integer that begins at 1 and increments
    by one with every mutation of the resource".

    Design: Corner/entities/create_card_product_returns_201_with_all_fields
    """
    set_clock("2026-07-01T00:00:00Z")
    res = api.create_product(
        {
            "name": "Cash Visa",
            "base_earn_rate_bps": 100,
            "signup_bonus_points": 10000,
            "signup_bonus_spend_threshold_cents": 100000,
            "signup_bonus_window_days": 90,
            "tier_thresholds": [],
            "points_expiry_months": 24,
        },
        _ADMIN,
    )
    prod = validate_success(res, expected_status=201)
    assert prod["status"] == "ACTIVE", f"new product must be ACTIVE, got {prod['status']!r}"
    assert prod["version"] == 1, f"version must begin at 1, got {prod['version']!r}"
    assert prod["base_earn_rate_bps"] == 100, "base_earn_rate_bps must echo input"


def test_get_account_returns_stored_and_computed_fields(api):
    """PRD §3.2: "Its computed ledgers all begin at zero: `points_balance` ...
    `pending_points` ... and `current_tier_index` (0). The `signup_bonus_status`
    begins at `NOT_QUALIFIED`".

    Design: Corner/entities/get_account_returns_stored_and_computed_fields
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product()
    acct = create_account(prod["id"])
    res = api.get_account(acct["id"], _ADMIN)
    data = validate_success(res)
    assert data["status"] == "PENDING", f"new account must be PENDING, got {data['status']!r}"
    assert data["points_balance"] == 0, "points_balance must begin at 0"
    assert data["pending_points"] == 0, "pending_points must begin at 0"
    assert data["current_tier_index"] == 0, "current_tier_index must begin at 0"


def test_list_products_paginated_envelope(api):
    """PRD §2.3: "Every list response carries the pagination bookkeeping in the
    `meta` object: `limit`, `offset`, `total_count` (the total number of matching
    items before paging), and `has_more` (true when items remain beyond the
    current page)."

    Design: Corner/entities/list_products_paginated_envelope
    """
    set_clock("2026-07-01T00:00:00Z")
    create_product(name="P1", base_earn_rate_bps=100)
    create_product(name="P2", base_earn_rate_bps=200)
    res = api.list_products(_ADMIN, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2, f"total_count must be 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "has_more must be true when items remain"
    assert len(data) == 1, f"page of limit=1 must hold 1 item, got {len(data)}"


def test_get_account_not_found_returns_404(api):
    """PRD §2.5: "the first identifier that does not resolve to an existing
    resource (a `CardAccount`, `Transaction`, `Redemption`, `CardProduct`,
    `TransferPartner`, or `QuarterlyCategory`) causes the request to be rejected
    with `ERR_RESOURCE_NOT_FOUND` (HTTP 404) before any later check runs."

    Design: Corner/entities/get_account_not_found_returns_404
    """
    set_clock("2026-07-01T00:00:00Z")
    res = api.get_account("00000000-0000-4000-8000-000000000000", _ADMIN)
    validate_error(res, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)


def test_create_transaction_missing_amount_returns_invalid_request(api):
    """PRD §2.10: "(5) presence and primitive-type/enum correctness of the
    request body, yielding `ERR_INVALID_REQUEST`".
    PRD §3.3: "by supplying the `card_account_id` ... an `amount_cents` (the
    purchase amount in cents, at least 1)".

    Design: Corner/entities/create_transaction_missing_amount_returns_invalid_request
    """
    set_clock("2026-07-01T00:00:00Z")
    acct = create_active_account()
    res = api.create_transaction(
        {
            "card_account_id": acct["id"],
            "category_code": "OTHER",
            "transacted_at": "2026-07-02T00:00:00Z",
        },
        _ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_product_status_defaults_active(api):
    """PRD §3.1: "A product is created in `status` `ACTIVE`; the `status`
    enumerates `ACTIVE` and `RETIRED`."

    Design: Corner/entities/product_status_defaults_active
    """
    set_clock("2026-07-01T00:00:00Z")
    res = api.create_product(
        {
            "name": "Cash Visa",
            "base_earn_rate_bps": 100,
            "signup_bonus_points": 0,
            "signup_bonus_spend_threshold_cents": 100000,
            "signup_bonus_window_days": 90,
            "tier_thresholds": [],
            "points_expiry_months": 24,
        },
        _ADMIN,
    )
    prod = validate_success(res, expected_status=201)
    assert prod["status"] == "ACTIVE", f"default status must be ACTIVE, got {prod['status']!r}"


def test_account_id_and_opened_at_system_minted(api):
    """PRD §3.2: "On creation the account records `opened_at` as the server clock
    at that instant".
    PRD §2.4: "The `id` is a server-minted UUID with no type prefix."

    Design: Corner/entities/account_id_and_opened_at_system_minted_input_ignored
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product()
    res = api.create_account({"card_product_id": prod["id"], "cardholder_name": "Ada"}, _ADMIN)
    acct = validate_success(res, expected_status=201)
    assert acct["opened_at"].startswith("2026-07-01T00:00:00"), (
        f"opened_at must equal the server clock at create, got {acct['opened_at']!r}"
    )
    # id is a UUID with no type prefix (no leading "acct_"/"card_" segment).
    assert "_" not in acct["id"], f"id must be a UUID with no type prefix, got {acct['id']!r}"


def test_transaction_zero_amount_rejected_invalid_request(api):
    """PRD §3.3: "an `amount_cents` (the purchase amount in cents, at least 1)".
    PRD §2.10: "(5) presence and primitive-type/enum correctness of the request
    body, yielding `ERR_INVALID_REQUEST`".

    Design: Corner/entities/transaction_invalid_enum_category_handled
    """
    set_clock("2026-07-01T00:00:00Z")
    acct = create_active_account()
    res = api.create_transaction(
        {
            "card_account_id": acct["id"],
            "amount_cents": 0,
            "category_code": "OTHER",
            "transacted_at": "2026-07-02T00:00:00Z",
        },
        _ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_points_lot_immutable_no_version_field(api):
    """PRD §2.4: "a **PointsLot** is a minimal, system-minted record that carries
    only `id` and `created_at`. A PointsLot has neither an `updated_at` field nor
    a `version` field."
    PRD §3.4: "the system mints a new **PointsLot** of `lot_type` `EARN`, with
    `original_points` and `remaining_points` both set to the earned amount".

    Design: Corner/entities/points_lot_immutable_no_version_field
    """
    set_clock("2026-07-01T00:00:00Z")
    acct = create_active_account(card_product_id=create_product(signup_bonus_spend_threshold_cents=999999)["id"])
    create_and_post_transaction(acct["id"], 100000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    lots = list_account_lots(acct["id"])
    earn_lots = [l for l in lots if l["lot_type"] == "EARN"]
    assert len(earn_lots) == 1, f"exactly one EARN lot expected, got {len(earn_lots)}"
    lot = earn_lots[0]
    assert lot["original_points"] == 1000, f"EARN lot original_points must be 1000, got {lot['original_points']}"
    assert lot["status"] == "ACTIVE", f"new EARN lot must be ACTIVE, got {lot['status']}"
    assert "version" not in lot, "PointsLot must NOT expose a version field (PRD §2.4)"
    assert "updated_at" not in lot, "PointsLot must NOT expose an updated_at field (PRD §2.4)"
    assert "id" in lot and "created_at" in lot, "PointsLot must expose id and created_at"


def test_create_account_under_nonexistent_product_404(api):
    """PRD §2.5: "Whenever a request names a resource — whether by a path
    identifier or by a foreign-key field in its body — that resource must exist.
    ... causes the request to be rejected with `ERR_RESOURCE_NOT_FOUND`
    (HTTP 404) before any later check runs."

    Design: Corner/entities/create_account_under_nonexistent_product_404
    """
    set_clock("2026-07-01T00:00:00Z")
    res = api.create_account(
        {"card_product_id": "00000000-0000-4000-8000-000000000000", "cardholder_name": "Ada"},
        _ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)


def test_open_account_under_retired_product_rejected(api):
    """PRD §3.2: "The referenced product must be `ACTIVE` at open time; opening an
    account under a `RETIRED` product is rejected with `ERR_CROSS_PRODUCT_MISMATCH`
    (HTTP 422)."

    Design: Corner/entities/open_account_under_retired_product_rejected
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(name="Old Visa")
    retire_product(prod["id"])
    res = api.create_account({"card_product_id": prod["id"], "cardholder_name": "Ada"}, _ADMIN)
    validate_error(res, ApiErrorId.ERR_CROSS_PRODUCT_MISMATCH.value)
