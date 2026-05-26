"""Listing endpoints: pagination defaults and total_count visibility."""
from test_helpers import (
    validate_paginated,
    set_clock,
    setup_clean_world,
    create_pairing,
    TEST_USERS,
)


def test_list_pairings_default_returns_all_within_default_limit(api, planner_headers):
    """PRD §2.3: "The `limit` parameter caps the number of items returned and
    defaults to 10; the minimum permitted value is 1 and the maximum is 100.
    The `offset` parameter specifies how many leading items to skip and
    defaults to 0."
    PRD §2.3: "Paginated responses include the following fields inside the
    response envelope's `meta` object: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/endpoints/list_pairings_pagination_default_limit
    """
    setup_clean_world("2026-06-01T00:00:00Z")
    create_pairing(
        pairing_code="P-2026-500",
        scheduled_start_utc="2026-06-02T00:00:00Z",
        scheduled_end_utc="2026-06-02T10:00:00Z",
        bidding_close_utc="2026-06-01T12:00:00Z",
    )
    create_pairing(
        pairing_code="P-2026-501",
        scheduled_start_utc="2026-06-03T00:00:00Z",
        scheduled_end_utc="2026-06-03T10:00:00Z",
        bidding_close_utc="2026-06-01T12:00:00Z",
    )
    create_pairing(
        pairing_code="P-2026-502",
        scheduled_start_utc="2026-06-04T00:00:00Z",
        scheduled_end_utc="2026-06-04T10:00:00Z",
        bidding_close_utc="2026-06-01T12:00:00Z",
    )
    res = api.list_pairings(planner_headers)
    data, meta = validate_paginated(res)
    assert len(data) == 3, f"expected 3 pairings, got {len(data)}"
    assert meta["total_count"] == 3, (
        f"total_count must report all rows ({3}), got {meta['total_count']}"
    )
    assert meta["has_more"] is False, (
        f"has_more must be False when count <= limit, got {meta['has_more']!r}"
    )
