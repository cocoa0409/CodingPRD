"""List-endpoint pagination and FK filtering (PRD 2.3, 3.2)."""
from test_helpers import (
    base_scenario,
    create_facility,
    create_par,
    create_unit,
    schedule_run,
    validate_paginated,
)


def test_list_units_pagination_has_more(api, linen_manager_headers):
    """PRD 2.3: "The `limit` parameter specifies the maximum number of items
    to return; it defaults to 10, with a minimum of 1 and a maximum of 100.
    The `offset` parameter specifies how many items to skip and defaults to
    0."
    PRD 2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the response envelope."
    PRD 3.1: "The unit list may be filtered by `facility_id` or `unit_tier`."

    Design: Corner/endpoints/list_pagination_has_more
    """
    facility = create_facility()
    create_unit(facility["id"], name="ICU", unit_tier="CRITICAL")
    create_unit(facility["id"], name="4 West", unit_tier="STANDARD")

    page1, meta1 = validate_paginated(
        api.list_units(
            linen_manager_headers,
            params={"facility_id": facility["id"], "limit": 1, "offset": 0},
        )
    )
    assert len(page1) == 1, f"page 1 must hold exactly 1 unit, got {len(page1)}"
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_units(
            linen_manager_headers,
            params={"facility_id": facility["id"], "limit": 1, "offset": 1},
        )
    )
    assert len(page2) == 1, f"page 2 must hold exactly 1 unit, got {len(page2)}"
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False
    assert page1[0]["id"] != page2[0]["id"]


def test_cart_runs_filtered_by_unit_id(api, linen_manager_headers):
    """PRD 3.2: "The cart-run list may be filtered by `unit_id`, `status`, or
    `manifest_id`."

    Design: Corner/endpoints/filtered_list_by_unit_fk
    """
    ctx = base_scenario()
    unit2 = create_unit(ctx["facility"]["id"], name="4 West", unit_tier="STANDARD")
    create_par(unit2["id"], ctx["stock"]["id"], 10, "DAILY")
    run1 = schedule_run(
        ctx["unit"]["id"], "2026-08-02T08:00:00Z", "2026-08-02T09:00:00Z"
    )
    schedule_run(unit2["id"], "2026-08-02T08:00:00Z", "2026-08-02T09:00:00Z")

    data, meta = validate_paginated(
        api.list_cart_runs(
            linen_manager_headers, params={"unit_id": ctx["unit"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == run1["id"]
    assert data[0]["unit_id"] == ctx["unit"]["id"]
