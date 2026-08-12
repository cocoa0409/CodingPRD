"""Response envelope, pagination, and filtered listing (PRD §2.2, §2.3, §4)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    create_product_payload,
    new_ctx, create_job,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["operator_headers"]


class TestListingAndEnvelope:
    def test_product_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0."
        PRD §2.3: "every list endpoint returns resources sorted by `created_at` in ascending order, and the `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/product_list_pagination_envelope
        """
        for code, family, group, flash in (
                ("P1", "GASOLINE", "GAS", -40), ("P2", "JET", "JET", 38),
                ("P3", "CRUDE", "CRUDE", 20)):
            validate_success(api.create_product(
                create_product_payload(code=code, family=family,
                                       viscosity_class="LOW" if family != "CRUDE" else "HIGH",
                                       compatibility_group=group,
                                       flash_point_c=flash),
                ADMIN), 201)

        res1 = api.list_products(OPERATOR, params={"limit": 2, "offset": 0})
        body1 = res1.json()
        page1, meta1 = validate_paginated(res1)
        assert body1["response_type"] == "array"
        assert isinstance(body1["meta"].get("api_request_id"), str)
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        res2 = api.list_products(OPERATOR, params={"limit": 2, "offset": 2})
        page2, meta2 = validate_paginated(res2)
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 3

    def test_jobs_filtered_list_by_tank(self, api):
        """PRD §4: "GET /ops/cleaning-jobs | List cleaning jobs, filterable by `terminal_id`, `tank_id`, `contractor_id`, `from_product_id`, `to_product_id`, `window_id`, `status` (paginated)"

        Design: Corner/endpoints/jobs_filtered_list_by_tank
        """
        ctx = new_ctx()
        tank_b = validate_success(api.create_tank(
            {"terminal_id": ctx["terminal"]["id"], "tank_number": "T-B",
             "capacity_m3": 3000, "current_product_id": ctx["gas"]["id"]},
            ADMIN), 201)
        job = create_job(ctx, heel_volume_liters_sounding=100,
                         base_service_fee_cents=1000)

        page_a, meta_a = validate_paginated(api.list_cleaning_jobs(
            OPERATOR, params={"tank_id": ctx["tank"]["id"]}))
        assert meta_a["total_count"] == 1
        assert [j["id"] for j in page_a] == [job["id"]]

        page_b, meta_b = validate_paginated(api.list_cleaning_jobs(
            OPERATOR, params={"tank_id": tank_b["id"]}))
        assert page_b == []
        assert meta_b["total_count"] == 0

    def test_error_envelope_shape_on_404(self, api):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/endpoints/error_envelope_shape_on_404
        """
        res = api.get_inspector(NON_EXISTENT_UUID, OPERATOR)
        error = validate_error(res, ApiErrorId.ERR_NOT_FOUND)
        assert isinstance(error["message"], str) and error["message"].strip()
