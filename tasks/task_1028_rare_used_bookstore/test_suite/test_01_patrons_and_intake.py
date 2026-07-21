"""Patron registration, intake basics, and listing/pagination shape."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_patron, assert_book_item,
    create_patron_payload, create_intake_lot_payload, create_book_item_payload,
    create_sale_order_payload, unique_email, NON_EXISTENT_UUID,
    TEST_USERS,
)
from test_helpers.fixtures import new_patron, new_intake_lot

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["storeclerk_headers"]


def test_register_patron_returns_active_with_zero_ledgers(api):
    """PRD §3.1: "On creation a patron begins with `status` of `ACTIVE`, a
    `store_credit_cents` of 0, and a `consignor_payable_cents` of 0."

    Design: Corner/entities/patron_create_returns_201_with_envelope
    """
    res = api.create_patron(create_patron_payload(display_name="Nora"), CLERK)
    patron = validate_success(res, 201)
    assert res.json()["response_type"] == "object"
    assert_patron(patron)
    assert patron["status"] == "ACTIVE"
    assert patron["store_credit_cents"] == 0
    assert patron["consignor_payable_cents"] == 0


def test_patron_default_commission_defaults_to_030(api):
    """PRD §3.1: "may optionally include a `default_commission_pct`, the fractional
    commission (a value between 0 and 1) the shop applies to that consignor's
    agreements when an agreement omits its own rate; when not supplied it defaults
    to 0.30."

    Design: Corner/entities/patron_default_commission_defaults_030
    """
    payload = create_patron_payload(display_name="Molly")
    payload.pop("default_commission_pct", None)
    patron = validate_success(api.create_patron(payload, CLERK), 201)
    assert patron["default_commission_pct"] == 0.30


def test_book_item_copies_consignor_from_lot(api):
    """PRD §3.2: "On intake the item is created in `INTAKE` status, its
    `consignor_id` is copied from the lot, the lot's `item_count` is incremented by
    one, and a `provenance` entry of event type `INTAKE` is appended."

    Design: Corner/entities/book_item_consignor_copied_from_lot
    """
    patron = new_patron(display_name="Leopold")
    lot = new_intake_lot(acquisition_channel="CONSIGNMENT", consignor_id=patron["id"])
    res = api.create_book_item(
        lot["id"], create_book_item_payload(title="The Dead", comp_median_cents=3000), CLERK)
    book = validate_success(res, 201)
    assert_book_item(book)
    assert book["consignor_id"] == patron["id"]
    assert book["status"] == "INTAKE"


def test_sale_order_defaults_to_draft_status(api):
    """PRD §3.8: "A new order is created in `DRAFT`, and its totals are computed
    immediately."

    Design: Corner/entities/sale_order_status_defaults_draft_system_field
    """
    res = api.create_sale_order(create_sale_order_payload("ONLINE", []), CLERK)
    order = validate_success(res, 201)
    assert order["status"] == "DRAFT"


def test_get_unknown_book_item_returns_not_found(api):
    """PRD §2.7: "each id in the path must resolve to an existing resource before the
    next is considered, and the first that does not resolve produces the matching
    not-found error — `ERR_PATRON_NOT_FOUND`, `ERR_INTAKE_LOT_NOT_FOUND`,
    `ERR_BOOK_ITEM_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
    `ERR_OFFER_NOT_FOUND`, `ERR_FAIR_NOT_FOUND`, or `ERR_ORDER_NOT_FOUND` (all HTTP
    404)."

    Design: Corner/entities/get_book_item_not_found_returns_404
    """
    res = api.get_book_item(NON_EXISTENT_UUID, CLERK)
    validate_error(res, "ERR_BOOK_ITEM_NOT_FOUND", expected_status=404)


def test_register_patron_without_email_rejected(api):
    """PRD §3.1: "Registration captures a `display_name` and an `email`, and may
    optionally include a `default_commission_pct`".
    PRD §2.8: "request-body well-formedness — required fields present, enum fields
    within their allowed sets, numeric amounts non-negative, and, for any window, its
    end strictly after its start (`ERR_INVALID_REQUEST`, or `ERR_INVALID_WINDOW` for
    the window ordering, both HTTP 400)".

    Design: Corner/entities/patron_create_missing_email_returns_invalid_request
    """
    res = api.create_patron({"display_name": "NoEmail"}, CLERK)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_list_book_items_pagination_shape(api):
    """PRD §2.3: "When a list endpoint responds, its `meta` object carries `limit`,
    `offset`, `total_count` (the number of records matching the query before the page
    window is applied), and `has_more` (true when records remain beyond the current
    page)."

    Design: Corner/entities/intake_book_items_pagination_shape
    """
    lot = new_intake_lot(acquisition_channel="PURCHASE")
    api.create_book_item(lot["id"], create_book_item_payload(title="Araby", comp_median_cents=2000), CLERK)
    resp = api.list_book_items(CLERK)
    assert resp.json()["response_type"] == "array"
    data, meta = validate_paginated(resp)
    assert isinstance(meta["total_count"], int) and meta["total_count"] >= 1
    assert isinstance(meta["has_more"], bool)


def test_register_duplicate_email_rejected(api):
    """PRD §3.1: "Email addresses must be unique across all patrons; a registration
    whose `email` matches an existing patron is rejected with `ERR_DUPLICATE_EMAIL`."

    Design: Corner/validations/duplicate_email_returns_409
    """
    email = unique_email("dup")
    validate_success(api.create_patron(create_patron_payload(display_name="First", email=email), CLERK), 201)
    res = api.create_patron(create_patron_payload(display_name="Second", email=email), CLERK)
    validate_error(res, "ERR_DUPLICATE_EMAIL", expected_status=409)
