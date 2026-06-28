"""CRUD, input validation, and listing for the Yearbook root and its ladder pages.

Each test translates exactly one corner-design instance (queue B).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    assert_yearbook,
    assert_ladder_page,
    create_yearbook_payload,
    create_page_payload,
    create_presale_order_payload,
    create_yearbook,
    create_yearbook_early_window,
    TEST_USERS,
)

ADVISER = TEST_USERS["adviser_headers"]
SALESREP = TEST_USERS["salesrep_headers"]
CONTRIBUTOR = TEST_USERS["contributor_headers"]


def test_create_yearbook_returns_201_with_derived_defaults(api):
    """PRD §3.1: "A newly created yearbook starts with `production_phase` equal to
    `LADDER_BUILD`, all of its derived counts and revenue figures
    (`ladder_filled_count`, `ad_revenue_cents`, `presale_revenue_cents`,
    `production_cost_cents`) at zero, `ladder_complete` false, and `version` at 1."

    Design: Corner/entities/create_yearbook_returns_201_with_derived_defaults
    """
    res = api.create_yearbook(create_yearbook_payload(), ADVISER)
    yb = validate_success(res, 201)
    assert_yearbook(yb)
    assert yb["production_phase"] == "LADDER_BUILD"
    assert yb["ladder_filled_count"] == 0
    assert yb["ad_revenue_cents"] == 0
    assert yb["presale_revenue_cents"] == 0
    assert yb["production_cost_cents"] == 0
    assert yb["ladder_complete"] is False
    assert yb["version"] == 1


def test_get_yearbook_nonexistent_returns_not_found(api):
    """PRD §2.5: "if the yearbook portion of the path does not resolve to a real
    record, the request fails with `ERR_NOT_FOUND` before the page portion is even
    consulted".

    Design: Corner/entities/get_yearbook_nonexistent_returns_not_found
    """
    res = api.get_yearbook("00000000-0000-4000-8000-000000000000", ADVISER)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_yearbook_missing_required_field_returns_invalid_request(api):
    """PRD §2.6: "structural validity of the request body — required fields present,
    enumerated values legal, numbers within their declared ranges — else
    `ERR_INVALID_REQUEST` (HTTP 422)".

    Design: Corner/entities/create_yearbook_missing_required_field_returns_invalid_request
    """
    payload = create_yearbook_payload()
    del payload["target_page_count"]
    res = api.create_yearbook(payload, ADVISER)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_yearbook_target_pages_not_divisible_by_four_invalid(api):
    """PRD §3.1: "The `target_page_count` must be a positive number and, because
    pages are bound in four-page signatures, must be evenly divisible by four; a
    value that is not greater than zero or not divisible by four is a malformed body
    and is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_yearbook_target_pages_not_divisible_by_four_invalid
    """
    res = api.create_yearbook(create_yearbook_payload(target_page_count=97), ADVISER)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_page_default_spread_span_one(api):
    """PRD §3.1: "The `spread_span` records how many consecutive page slots the layout
    occupies and must be either 1 (a single page) or 2 (a double-page spread); when
    omitted it defaults to 1." PRD §3.1: "Each newly created page begins in `DRAFT`
    status".

    Design: Corner/entities/create_page_default_spread_span_one
    """
    yb = create_yearbook()
    res = api.create_page(
        create_page_payload(yb["id"], 5, "ACADEMICS"), ADVISER
    )
    page = validate_success(res, 201)
    assert_ladder_page(page)
    assert page["spread_span"] == 1
    assert page["status"] == "DRAFT"


def test_presale_personalize_without_stamp_name_invalid(api):
    """PRD §3.5: "When `personalize` is true the `stamp_name` must be a non-empty
    string; a personalized order with an empty `stamp_name` is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/presale_personalize_without_stamp_name_invalid
    """
    yb = create_yearbook_early_window()
    res = api.create_presale_order(
        create_presale_order_payload(yb["id"], buyer_name="No Name", quantity=1,
                                     personalize=True),
        SALESREP,
    )
    validate_error(res, "ERR_INVALID_REQUEST")


def test_list_yearbooks_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_yearbooks_pagination_envelope
    """
    create_yearbook()
    res = api.list_yearbooks(ADVISER, params={"limit": 10, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] >= 1
    assert "has_more" in meta


def test_fk_reverse_pages_by_yearbook_filtered_list(api):
    """PRD §4: "ladder-page listing accepts `yearbook_id` and `assigned_staff_id`
    filters".

    Design: Corner/endpoints/fk_reverse_pages_by_yearbook_filtered_list
    """
    yb = create_yearbook()
    page = validate_success(
        api.create_page(create_page_payload(yb["id"], 1, "CLUBS"), ADVISER), 201
    )
    res = api.list_pages(ADVISER, params={"yearbook_id": yb["id"]})
    data, meta = validate_paginated(res)
    returned_ids = [p["id"] for p in data]
    assert page["id"] in returned_ids
    assert all(p["yearbook_id"] == yb["id"] for p in data)
