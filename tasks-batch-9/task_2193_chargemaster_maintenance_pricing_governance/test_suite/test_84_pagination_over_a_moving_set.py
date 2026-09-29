"""Windows and total_count over a filtered set that gains a row and then loses one."""
from test_helpers import (
    api_client, validate_paginated,
    setup_base, create_item, reprice_item, item_lifecycle, set_clock, ANALYST,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-PAGING",
        "rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 40000,
    },
    revenue_code_overrides={
        "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
        "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
        "pricing_class": "PROCEDURE", "status": "ACTIVE",
    },
    department_overrides={"name": "Cardiac Cath Lab", "cost_center_code": "CC-100",
                         "allowed_revenue_code_values": []},
    price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
)
PRICING = dict(cost_basis_cents=100000, medicare_rate_cents=50000,
               market_p75_cents=900000, effective_from="2026-09-01T00:00:00Z")


def test_an_append_leaves_page_zero_alone_while_a_filter_exit_shifts_every_window_left():
    """PRD §2.3: "Every list endpoint accepts two optional query parameters, `limit` and `offset`."
    PRD §2.3: "Unless a specific endpoint's narrative in §3 pins a different order, list results are sorted
    by `created_at` ascending."
    PRD §2.3: "`total_count` is the number of records matching the filters before pagination is applied,
    and `has_more` is true when records remain beyond the current window."
    PRD §2.11: "Items in `DRAFT`, `PENDING_REVIEW`, `APPROVED`, `INACTIVE` or `ARCHIVED` never contribute to
    any facility aggregate."

    Design: Corner/cross_cutting_complexity_layers/offset_windows_and_total_count_track_the_filtered_set_across_an_append_and_a_removal
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    facility_id = base["facility"]["id"]
    first = create_item(base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                        code_type="CPT", code_value="93458", **PRICING)
    second = create_item(base, cdm_number="CDM-2002", description="CARDIAC CATH COMPLEX",
                         code_type="CPT", code_value="93460", **PRICING)
    third = create_item(base, cdm_number="CDM-3003", description="CARDIAC CATH FOLLOW UP",
                        code_type="CPT", code_value="93461", **PRICING)

    def drafts(offset):
        return validate_paginated(api_client.list_charge_items(
            ANALYST, {"facility_id": facility_id, "lifecycle_status": "DRAFT",
                      "limit": 2, "offset": offset}))

    rows, meta = drafts(0)
    assert meta["total_count"] == 3
    assert meta["limit"] == 2 and meta["offset"] == 0
    assert meta["has_more"] is True
    assert [row["id"] for row in rows] == [first["id"], second["id"]], "created_at ascending"
    rows, meta = drafts(2)
    assert [row["id"] for row in rows] == [third["id"]]
    assert meta["has_more"] is False
    assert meta["total_count"] == 3

    fourth = create_item(base, cdm_number="CDM-4004", description="CARDIAC CATH REVIEW",
                         code_type="CPT", code_value="93462", **PRICING)
    rows, meta = drafts(0)
    assert meta["total_count"] == 4
    assert [row["id"] for row in rows] == [first["id"], second["id"]], (
        "an append at the tail leaves page zero byte-identical"
    )
    assert meta["has_more"] is True
    rows, meta = drafts(2)
    assert [row["id"] for row in rows] == [third["id"], fourth["id"]]
    assert meta["has_more"] is False

    assert reprice_item(first["id"])["gross_charge_cents"] == 240000
    item_lifecycle(first["id"], "SUBMIT_FOR_REVIEW")
    item_lifecycle(first["id"], "APPROVE")
    assert item_lifecycle(first["id"], "ACTIVATE")["lifecycle_status"] == "ACTIVE"

    rows, meta = drafts(0)
    assert meta["total_count"] == 3, "the filtered set lost the activated row"
    assert [row["id"] for row in rows] == [second["id"], third["id"]], (
        "every row shifted exactly one window left"
    )
    assert meta["has_more"] is True
    rows, meta = drafts(2)
    assert [row["id"] for row in rows] == [fourth["id"]]
    assert meta["has_more"] is False

    rows, meta = validate_paginated(api_client.list_charge_items(
        ANALYST, {"facility_id": facility_id, "limit": 100, "offset": 0}))
    assert meta["total_count"] == 4, "nothing was deleted; only the predicate stopped matching"
    assert [row["id"] for row in rows] == [first["id"], second["id"], third["id"], fourth["id"]]

    rows, meta = validate_paginated(api_client.list_charge_items(
        ANALYST, {"facility_id": facility_id, "lifecycle_status": "ACTIVE",
                  "limit": 2, "offset": 0}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
    assert meta["has_more"] is False, "3 DRAFT plus 1 ACTIVE partitions the facility exactly"
