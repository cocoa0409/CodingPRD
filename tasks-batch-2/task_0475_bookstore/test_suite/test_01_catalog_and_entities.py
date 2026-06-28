"""Catalog creation, entity defaults/computed fields, type constraints, ledger
immutability, and basic request validation."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, make_member_headers,
    create_title_payload, create_member_payload, create_order_line_payload,
    create_sales_order_payload, credit_adjustment_payload, create_stock_items_payload,
    unique_isbn13,
    assert_title, assert_member, assert_credit_ledger_entry,
    NON_EXISTENT_UUID,
    make_title, make_member, receive_stock,
)

BOOKSELLER = TEST_USERS["bookseller_headers"]
ADMIN = TEST_USERS["store_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_create_title_returns_computed_counts_zero_and_active(api):
    """PRD §3.3: "Every new title starts in `ACTIVE` status with `on_hand_qty`
    and `reserved_qty` both at zero; the alternate status value a title may hold
    is `DISCONTINUED`."

    Design: Corner/entities/create_title_returns_201_with_computed_counts_zero
    """
    resp = api.create_title(
        create_title_payload(isbn13="9781111111111", name="New Title",
                             list_price_cents=1500),
        BOOKSELLER,
    )
    data = validate_success(resp, expected_status=201)
    assert_title(data)
    assert data["on_hand_qty"] == 0
    assert data["reserved_qty"] == 0
    assert data["status"] == "ACTIVE"


def test_get_member_not_found_returns_404(api):
    """PRD §2.5: "the system validates each identifier in left-to-right order and
    rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier
    that does not resolve to an existing resource."

    Design: Corner/entities/get_member_not_found_returns_404
    """
    resp = api.get_member(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_create_title_missing_list_price_rejected(api):
    """PRD §2.5: "last of all comes the generic body-shape check
    (`ERR_INVALID_REQUEST`, 400) for any required field that is missing,
    ill-typed, carries a `quantity` below 1, or supplies a bad enum value."

    Design: Corner/entities/create_title_missing_list_price_returns_invalid_request
    """
    resp = api.create_title(
        {"isbn13": "9782222222222", "name": "No Price"}, BOOKSELLER
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_member_default_tier_regular(api):
    """PRD §3.2: "When `tier` is omitted it defaults to `REGULAR`; when
    `is_local_author` is omitted it defaults to false. A newly registered member
    is created in `ACTIVE` status with `store_credit_cents` of zero and
    `loyalty_points` of zero."

    Design: Corner/entities/create_member_default_tier_regular_applied
    """
    resp = api.create_member(
        create_member_payload(email="def@x.com", full_name="Default Tier"), ANON
    )
    data = validate_success(resp, expected_status=201)
    assert_member(data)
    assert data["tier"] == "REGULAR"
    assert data["store_credit_cents"] == 0


def test_title_on_hand_after_stock_receive(api):
    """PRD §2.7: "A `Title`'s `on_hand_qty` is always the live count of that
    title's stock items in `AVAILABLE` state, and its `reserved_qty` is the live
    count in `RESERVED` state."
    PRD §3.3: "Receiving distributor stock for a title creates a requested
    `quantity` of new `StockItem` rows, each with `source` `DISTRIBUTOR` and
    `state` `AVAILABLE`, optionally stamped with a `cost_cents` acquisition cost,
    after which the title's `on_hand_qty` is recomputed."

    Design: Corner/entities/title_computed_on_hand_after_stock_receive
    """
    title = make_title(list_price_cents=1000)
    api.create_stock_items(title["id"], create_stock_items_payload(quantity=3),
                           BOOKSELLER)
    data = validate_success(api.get_title(title["id"], BOOKSELLER))
    assert data["on_hand_qty"] == 3


def test_create_title_invalid_category_enum_rejected(api):
    """PRD §2.5: "last of all comes the generic body-shape check
    (`ERR_INVALID_REQUEST`, 400) for any required field that is missing,
    ill-typed, carries a `quantity` below 1, or supplies a bad enum value."

    Design: Corner/entities/create_title_invalid_category_enum_rejected
    """
    resp = api.create_title(
        {"isbn13": "9784444444444", "name": "Bad Cat", "category": "MAGAZINE",
         "list_price_cents": 100},
        BOOKSELLER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_duplicate_isbn_rejected(api):
    """PRD §3.3: "a thirteen-digit value that duplicates an existing title is
    rejected with `ERR_DUPLICATE_ISBN` (HTTP 409)."

    Design: Corner/entities/duplicate_isbn_rejected
    """
    isbn = "9785555555555"
    validate_success(
        api.create_title(create_title_payload(isbn13=isbn, name="First",
                                              list_price_cents=1000), BOOKSELLER),
        expected_status=201,
    )
    resp = api.create_title(
        create_title_payload(isbn13=isbn, name="Dup", list_price_cents=1200),
        BOOKSELLER,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ISBN)


def test_credit_ledger_entry_immutable_no_version_field(api):
    """PRD §2.4: "A `CreditLedgerEntry` is an immutable, append-only record: it
    carries only `id` and `created_at`. It has no `updated_at` and no `version`,
    because once written it is never modified."

    Design: Corner/entities/credit_ledger_entry_immutable_no_version_field
    """
    member = make_member()
    validate_success(
        api.create_credit_adjustment(member["id"],
                                     credit_adjustment_payload(500), ADMIN),
        expected_status=201,
    )
    resp = api.list_credit_ledger(member["id"], ADMIN)
    data = validate_success(resp)
    assert isinstance(data, list) and len(data) == 1
    assert_credit_ledger_entry(data[0])
    assert data[0]["delta_cents"] == 500
    member_now = validate_success(api.get_member(member["id"], ADMIN))
    assert member_now["store_credit_cents"] == 500


def test_order_line_quantity_zero_rejected(api):
    """PRD §2.5: "last of all comes the generic body-shape check
    (`ERR_INVALID_REQUEST`, 400) for any required field that is missing,
    ill-typed, carries a `quantity` below 1, or supplies a bad enum value."

    Design: Corner/errors/invalid_quantity_zero_rejected
    """
    member = make_member()
    title = make_title(list_price_cents=1000)
    mh = make_member_headers(member["id"])
    order = validate_success(
        api.create_sales_order(create_sales_order_payload(member["id"]), mh),
        expected_status=201,
    )
    resp = api.create_order_line(
        order["id"], create_order_line_payload(title["id"], quantity=0), mh
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
