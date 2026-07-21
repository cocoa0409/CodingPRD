"""Catalog listing creation preconditions, parallel axes, duplicate, and OCC."""
from test_helpers import (
    validate_success, validate_error,
    create_listing_payload, TEST_USERS,
)
from test_helpers.fixtures import (
    make_appraised_book, make_graded_book, make_listed_book,
    create_listing, patch_listing,
)

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["storeclerk_headers"]


def test_listing_axes_advance_independently(api):
    """PRD §3.4: "A clerk edits a listing to change its `list_price_cents` and to
    advance either axis independently — bringing the online axis from `DRAFT` to
    `LIVE`, or the shelf axis from `DRAFT` to `ON_SHELF` — and each such edit leaves
    the other axis unchanged, increments the listing's `version` by one, and must
    carry an `expected_catalog_listing_version` matching the listing's current
    `version`."

    Design: Difficulty/non_linear_state_machine/catalog_listing_parallel_axes_independent
    """
    ctx = make_listed_book(condition_grade="FINE", list_price_cents=9000, comp_median_cents=6000)
    listing = ctx["listing"]
    listing = patch_listing(listing["id"], listing["version"], online_status="LIVE")
    listing = patch_listing(listing["id"], listing["version"], shop_status="ON_SHELF")
    assert listing["online_status"] == "LIVE"
    assert listing["shop_status"] == "ON_SHELF"


def test_listing_online_change_leaves_shop_axis_unchanged(api):
    """PRD §3.4: "A clerk edits a listing to change its `list_price_cents` and to
    advance either axis independently — bringing the online axis from `DRAFT` to
    `LIVE`, or the shelf axis from `DRAFT` to `ON_SHELF` — and each such edit leaves
    the other axis unchanged, increments the listing's `version` by one, and must
    carry an `expected_catalog_listing_version` matching the listing's current
    `version`."

    Design: Difficulty/non_linear_state_machine/catalog_listing_parallel_axes_independent
    """
    ctx = make_listed_book(condition_grade="FINE", list_price_cents=9000, comp_median_cents=6000)
    listing = ctx["listing"]
    assert listing["online_status"] == "DRAFT" and listing["shop_status"] == "DRAFT"
    updated = patch_listing(listing["id"], listing["version"], online_status="LIVE")
    assert updated["online_status"] == "LIVE"
    assert updated["shop_status"] == "DRAFT"


def test_create_listing_requires_appraised_graded_item(api):
    """PRD §3.4: "Listing creation requires the book to be in `APPRAISED` status
    (otherwise `ERR_ITEM_NOT_APPRAISED`) and enforces a one-to-one relationship".

    Design: Difficulty/cross_entity_state_dependency/listing_requires_book_item_appraised
    """
    ctx = make_graded_book(condition_grade="GOOD", comp_median_cents=4000, title="Stephen Hero")
    res = api.create_listing(ctx["book"]["id"], create_listing_payload(list_price_cents=5000), CLERK)
    validate_error(res, "ERR_ITEM_NOT_APPRAISED", expected_status=409)


def test_create_listing_requires_appraised_intake_item(api):
    """PRD §3.4: "Listing creation requires the book to be in `APPRAISED` status
    (otherwise `ERR_ITEM_NOT_APPRAISED`) and enforces a one-to-one relationship".

    Design: Difficulty/cross_entity_state_dependency/listing_requires_book_item_appraised
    """
    from test_helpers.fixtures import new_intake_lot, new_book_item
    lot = new_intake_lot(acquisition_channel="PURCHASE")
    book = new_book_item(lot["id"], title="Intake Only", comp_median_cents=3000)
    assert book["status"] == "INTAKE"
    res = api.create_listing(book["id"], create_listing_payload(list_price_cents=5000), CLERK)
    validate_error(res, "ERR_ITEM_NOT_APPRAISED", expected_status=409)


def test_duplicate_listing_rejected(api):
    """PRD §3.4: "a book may have at most one catalog listing and at most one
    consignment agreement, so a second listing attempt is rejected with
    `ERR_DUPLICATE_LISTING`."

    Design: Corner/validations/duplicate_listing_returns_409
    """
    ctx = make_listed_book(condition_grade="GOOD", list_price_cents=5000, comp_median_cents=3500, title="Grace")
    res = api.create_listing(ctx["book"]["id"], create_listing_payload(list_price_cents=5500), CLERK)
    validate_error(res, "ERR_DUPLICATE_LISTING", expected_status=409)


def test_listing_update_stale_version_rejected(api):
    """PRD §2.6: "Updating a catalog listing requires `expected_catalog_listing_version`
    to equal that `CatalogListing`'s current `version`. A client carrying a version
    older than the listing's current `version` has not seen an intervening change and
    is refused with `ERR_STALE_VERSION`."

    Design: Corner/cross_cutting_complexity_layers/listing_update_stale_version_returns_412
    """
    ctx = make_listed_book(condition_grade="GOOD", list_price_cents=4800, comp_median_cents=3300,
                           title="The Boarding House")
    listing = ctx["listing"]
    stale = listing["version"]
    patch_listing(listing["id"], stale, online_status="LIVE")  # advances version
    res = api.update_catalog_listing(
        listing["id"], {"list_price_cents": 5200, "expected_catalog_listing_version": stale}, CLERK)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
