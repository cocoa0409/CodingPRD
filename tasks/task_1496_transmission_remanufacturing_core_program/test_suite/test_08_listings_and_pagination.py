"""List endpoints: pagination envelope contract and reverse-lookup filters."""
import pytest

from test_helpers import (
    ANY_H,
    create_hard_part_record,
    create_interchange_mapping_payload,
    create_mapping,
    create_min_model,
    create_order,
    api_client,
    validate_paginated,
    validate_success,
)


class TestOrdersPagination:

    def test_orders_list_pagination_envelope(self):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0."
        PRD §2.3: "List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the response envelope."

        Design: Corner/endpoints/orders_list_pagination_envelope
        """
        model = create_min_model()
        o1 = create_order(model["id"], "BUYER-1")
        o2 = create_order(model["id"], "BUYER-2")

        page1 = api_client.list_reman_orders(ANY_H, params={"limit": 1, "offset": 0})
        data1, meta1 = validate_paginated(page1)
        assert len(data1) == 1
        assert meta1["total_count"] == 2
        assert meta1["limit"] == 1
        assert meta1["offset"] == 0
        assert meta1["has_more"] is True

        page2 = api_client.list_reman_orders(ANY_H, params={"limit": 1, "offset": 1})
        data2, meta2 = validate_paginated(page2)
        assert len(data2) == 1
        assert meta2["total_count"] == 2
        assert meta2["offset"] == 1
        assert meta2["has_more"] is False

        paged_ids = {data1[0]["id"], data2[0]["id"]}
        assert paged_ids == {o1["id"], o2["id"]}, \
            "the two pages must return the two distinct orders"


class TestInterchangeFilters:

    def test_interchange_filters_reverse_lookup(self):
        """PRD §3.1: "The mapping collection accepts optional `hard_part_id` and `transmission_model_id` filters."

        Design: Corner/endpoints/interchange_filtered_list_reverse_lookup
        """
        model = create_min_model()
        part = create_hard_part_record()
        mapping = create_mapping(part["id"], model["id"], "DIRECT")

        by_model = api_client.list_interchange_mappings(
            ANY_H, params={"transmission_model_id": model["id"]})
        data, meta = validate_paginated(by_model)
        assert len(data) == 1
        assert data[0]["id"] == mapping["id"]
        assert data[0]["hard_part_id"] == part["id"]
        assert data[0]["transmission_model_id"] == model["id"]
        assert data[0]["tier"] == "DIRECT"

        by_part = api_client.list_interchange_mappings(
            ANY_H, params={"hard_part_id": part["id"]})
        data2, _meta2 = validate_paginated(by_part)
        assert len(data2) == 1
        assert data2[0]["id"] == mapping["id"]
