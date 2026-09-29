"""List endpoints: the pagination window and its accepted limit range."""

from test_helpers import (
    ApiErrorId,
    PRODUCT_P1,
    create_branch,
    create_product,
    make_platform_admin_headers,
    receive_reel,
    validate_error,
    validate_paginated,
)

ADMIN = make_platform_admin_headers()


def test_reel_list_pagination_defaults_and_limit_bounds(api):
    """PRD §2.3: "Every list endpoint accepts two optional query parameters,
    `limit` and `offset`. `limit` defaults to 10 when omitted, has a minimum
    accepted value of 1 and a maximum accepted value of 100; a supplied
    `limit` outside the range from 1 to 100 inclusive is a malformed request
    and is rejected with `ERR_INVALID_REQUEST` (HTTP 422)."
    PRD §2.3: "`offset` defaults to 0 when omitted and has a minimum accepted
    value of 0. The `meta` block of a list response carries `limit`, `offset`,
    `total_count` (the number of rows matching the filter before the window is
    applied) and `has_more` (true when rows remain beyond the current
    window)."

    Design: Corner/endpoints/reel_list_pagination_defaults_and_upper_bound
    """
    branch = create_branch()
    product = create_product(PRODUCT_P1)
    for _ in range(12):
        receive_reel(product["id"], branch["id"], 500, lot_code="L1")

    unpaged = api.list_reels(ADMIN, {"branch_id": branch["id"]})
    rows, meta = validate_paginated(unpaged)
    assert len(rows) == 10, f"limit defaults to 10, got {len(rows)} rows"
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 12
    assert meta["has_more"] is True

    windowed = api.list_reels(ADMIN, {"branch_id": branch["id"], "offset": 10})
    tail, tail_meta = validate_paginated(windowed)
    assert len(tail) == 2
    assert tail_meta["has_more"] is False

    over_limit = api.list_reels(ADMIN, {"branch_id": branch["id"], "limit": 101})
    validate_error(over_limit, ApiErrorId.ERR_INVALID_REQUEST.value)
