"""Filtered list retrieval (FK reverse-reachability)."""
from test_helpers import validate_paginated, TEST_USERS
from test_helpers.fixtures import (
    set_clock, create_and_publish_index, create_bale, setup_audited_load,
)

SORT = TEST_USERS["sort_manager_headers"]


def test_list_bales_filtered_by_source_load(api):
    """PRD §2.8: "Because there are no nested URLs, every foreign-key relationship
    is reachable through a filtered list. ... bales by `source_load_id`,
    `shipment_id`, `status`, and `commodity`".
    PRD §2.3: "Every list response echoes `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/corner_list_bales_filtered_by_source_load
    """
    set_clock(api, "2026-03-10T00:00:00Z")
    create_and_publish_index(api, "OCC", 8000)
    ctx = setup_audited_load(api, gross_tons=12, tare_tons=2)
    create_bale(api, ctx["load_id"], "OCC", net_tons=3, moisture_pct=0, quality_grade="A")
    create_bale(api, ctx["load_id"], "OCC", net_tons=2, moisture_pct=0, quality_grade="A")
    data, meta = validate_paginated(
        api.list_bales(SORT, params={"source_load_id": ctx["load_id"]}))
    assert len(data) == 2
    assert all(b["source_load_id"] == ctx["load_id"] for b in data)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
