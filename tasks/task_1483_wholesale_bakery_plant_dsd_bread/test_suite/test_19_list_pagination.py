"""List-endpoint pagination envelope (PRD §2.3)."""
from test_helpers import (
    TEST_USERS,
    create_plant,
    create_store,
    validate_paginated,
)


class TestStoreListPagination:
    def test_store_list_pagination_envelope(self, api):
        """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the envelope." And: "The
        `limit` parameter sets the maximum number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter sets the number of items skipped and defaults to
        0."

        Design: Corner/endpoints/store_list_pagination_envelope
        """
        plant = create_plant()
        create_store(plant["id"], name="S1")
        create_store(plant["id"], name="S2")
        create_store(plant["id"], name="S3")

        resp1 = api.list_stores(
            TEST_USERS["admin_headers"],
            params={"plant_id": plant["id"], "limit": 2},
        )
        data1, meta1 = validate_paginated(resp1)
        assert meta1["total_count"] == 3, (
            f"total_count must be 3, got {meta1['total_count']}"
        )
        assert meta1["has_more"] is True, (
            f"has_more must be true with 3 items and limit=2, got {meta1['has_more']}"
        )
        assert len(data1) == 2, f"first page must carry 2 items, got {len(data1)}"

        resp2 = api.list_stores(
            TEST_USERS["admin_headers"],
            params={"plant_id": plant["id"], "limit": 2, "offset": 2},
        )
        data2, meta2 = validate_paginated(resp2)
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False, (
            f"has_more must be false at offset=2 with 1 remaining, got {meta2['has_more']}"
        )
        assert len(data2) == 1, (
            f"second page must carry the 1 remaining row, got {len(data2)}"
        )
