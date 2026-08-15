"""Catalog item/unit creation rules, response envelope, and list pagination."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    acquire_unit,
    assert_item,
    create_catalog_item,
    create_item_payload,
    create_unit_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCatalogAndEnvelope:
    def test_item_creation_defaults_and_computed_fields(self, api, house_admin_headers):
        """PRD §3.2: "A new item's `status` is `ACTIVE` (the item states are `ACTIVE`,
        `DEACCESSION_PENDING`, and `DEACCESSIONED`) and its `serviceable_unit_count` starts at 0."
        PRD §2.5: "`id` (string): a unique, server-generated identifier formatted as a UUID,
        with no type prefix."

        Design: Corner/entities/item_creation_defaults_and_computed_fields
        """
        resp = api.create_item(
            create_item_payload(name="Tailcoat"), house_admin_headers,
        )
        data = validate_success(resp, 201)
        assert_item(data)
        assert is_valid_uuid(data["id"]), "id must be a server-minted bare UUID"
        assert data["status"] == "ACTIVE"
        assert data["serviceable_unit_count"] == 0
        assert data["version"] == 1

    def test_item_list_filter_pagination_and_deaccession_visibility(
        self, api, house_admin_headers,
    ):
        """PRD §3.2: "deaccessioned items are hidden from default list results unless
        `include_deaccessioned` is true — a deaccessioned item is soft-deleted but remains
        queryable this way."
        PRD §2.9: "every identifier in the path and body ... exists, validated left-to-right
        in the path and then the body, else `ERR_NOT_FOUND`" — a soft-deleted item still exists.

        Design: Corner/entities/item_list_filter_pagination_and_deaccession_visibility
        """
        i1 = create_catalog_item(api, name="I1")  # first COSTUME row (page 1 of the filter)
        assert i1["status"] == "ACTIVE"
        i2 = create_catalog_item(
            api, name="I2", period="REGENCY", size_class="L",
            alteration_policy="REVERSIBLE_ONLY", replacement_value_cents=80000,
            base_daily_rate_cents=900, base_weekly_rate_cents=4500,
        )
        i3 = create_catalog_item(
            api, name="I3", period="TWENTIES", category="PROP", size_class="NONE",
            alteration_policy="PROHIBITED", replacement_value_cents=20000,
            base_daily_rate_cents=500, base_weekly_rate_cents=2500,
        )
        validate_success(api.request_deaccession(i3["id"], house_admin_headers))
        validate_success(api.complete_deaccession(i3["id"], house_admin_headers))

        # Filtered page: category=COSTUME, limit=1, offset=1 -> second of two rows.
        resp = api.list_items(
            house_admin_headers, params={"category": "COSTUME", "limit": 1, "offset": 1},
        )
        data, meta = validate_paginated(resp)
        assert len(data) == 1, f"Expected 1 row on the page, got {len(data)}"
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert data[0]["id"] == i2["id"], "created_at ASC page 2 must be the second COSTUME item"

        # Default list hides the DEACCESSIONED item.
        data, meta = validate_paginated(api.list_items(house_admin_headers))
        assert meta["total_count"] == 2
        assert i3["id"] not in [row["id"] for row in data]

        # include_deaccessioned=true surfaces it again; a direct read still resolves.
        data, meta = validate_paginated(
            api.list_items(house_admin_headers, params={"include_deaccessioned": "true"})
        )
        assert meta["total_count"] == 3
        assert i3["id"] in [row["id"] for row in data]
        direct = validate_success(api.get_item(i3["id"], house_admin_headers))
        assert direct["status"] == "DEACCESSIONED"

    def test_unit_create_invalid_condition_grade_rejected(self, api, house_admin_headers):
        """PRD §2.9: "missing required field, wrong type, invalid enum member, or malformed
        date, reported as `ERR_VALIDATION`".
        PRD §3.2: "its `condition_grade` at acquisition (`A`, `B`, `C`, or `D`)".

        Design: Corner/entities/unit_create_invalid_condition_grade_rejected
        """
        item = create_catalog_item(api, name="I1")
        resp = api.create_unit(
            item["id"], create_unit_payload(barcode="BC-X1", condition_grade="E"),
            house_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)

    def test_unit_create_duplicate_barcode_rejected(self, api, house_admin_headers):
        """PRD §3.2: "The barcode must be unique house-wide — a duplicate is rejected with
        `ERR_DUPLICATE_BARCODE`."

        Design: Corner/entities/unit_create_duplicate_barcode_rejected
        """
        i1 = create_catalog_item(api, name="I1")
        i2 = create_catalog_item(
            api, name="I2", period="REGENCY", category="PROP", size_class="NONE",
            alteration_policy="PROHIBITED", replacement_value_cents=80000,
            base_daily_rate_cents=900, base_weekly_rate_cents=4500,
        )
        acquire_unit(api, i1["id"], barcode="BC-DUP")
        # Same barcode on a DIFFERENT item: the uniqueness rule is house-wide.
        resp = api.create_unit(
            i2["id"],
            create_unit_payload(
                barcode="BC-DUP", condition_grade="A",
                acquisition_date="2025-02-01", acquisition_cost_cents=30000,
            ),
            house_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BARCODE, 409)

    def test_renter_get_not_found_returns_404(self, api, house_admin_headers):
        """PRD §2.9: "every identifier in the path and body (renter, certificate, rate card,
        item, unit, production, reservation, pull list, line, fitting, assessment, claim,
        ticket, invoice) exists, validated left-to-right in the path and then the body, else
        `ERR_NOT_FOUND`."

        Design: Corner/entities/renter_get_not_found_returns_404
        """
        resp = api.get_renter(NON_EXISTENT_UUID, house_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_response_envelope_shape_on_success_and_error(self, api, house_admin_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
        request that starts with `req_`." and "The `meta` object for error responses contains
        only `api_request_id` and `api_request_timestamp`." and "The `error_id` is a unique,
        machine-readable string that identifies the specific error."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        item = create_catalog_item(api, name="I1")

        ok_resp = api.get_item(item["id"], house_admin_headers)
        ok_body = ok_resp.json()
        assert ok_resp.status_code == 200
        assert ok_body["response_type"] == "object"
        assert isinstance(ok_body["meta"]["api_request_id"], str)
        assert ok_body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(ok_body["meta"]["api_request_timestamp"], str)
        assert ok_body["data"]["id"] == item["id"]

        err_resp = api.get_item(NON_EXISTENT_UUID, house_admin_headers)
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str) and err_body["data"]["message"]
        assert "api_request_id" in err_body["meta"]
        assert "api_request_timestamp" in err_body["meta"]

    def test_list_pagination_defaults(self, api, house_admin_headers):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter
        specifies the number of items to skip and defaults to 0."
        PRD §2.3: "List responses include the following fields in the `meta` object of the
        response envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_pagination_defaults_and_limit_floor_rejected
        """
        variants = [
            dict(name="I01"),
            dict(name="I02", period="REGENCY", size_class="S",
                 alteration_policy="REVERSIBLE_ONLY", replacement_value_cents=80000,
                 base_daily_rate_cents=900, base_weekly_rate_cents=4500),
            dict(name="I03", period="TWENTIES", category="PROP", size_class="NONE",
                 alteration_policy="PROHIBITED", replacement_value_cents=20000,
                 base_daily_rate_cents=500, base_weekly_rate_cents=2500),
            dict(name="I04", period="FIFTIES", size_class="L", replacement_value_cents=60000,
                 base_daily_rate_cents=700, base_weekly_rate_cents=3500),
            dict(name="I05", period="EIGHTIES", category="ACCESSORY", size_class="NONE",
                 alteration_policy="REVERSIBLE_ONLY", replacement_value_cents=10000,
                 base_daily_rate_cents=300, base_weekly_rate_cents=1500),
            dict(name="I06", period="MEDIEVAL", category="WEAPONRY", size_class="NONE",
                 alteration_policy="PROHIBITED", replacement_value_cents=150000,
                 base_daily_rate_cents=2000, base_weekly_rate_cents=9000),
            dict(name="I07", period="RENAISSANCE", size_class="XL",
                 alteration_policy="REVERSIBLE_ONLY", replacement_value_cents=120000,
                 base_daily_rate_cents=1100, base_weekly_rate_cents=5500),
            dict(name="I08", period="EDWARDIAN", category="SET_DRESSING", size_class="NONE",
                 alteration_policy="PROHIBITED", replacement_value_cents=90000,
                 base_daily_rate_cents=800, base_weekly_rate_cents=4000),
            dict(name="I09", period="ANCIENT", category="PROP", size_class="NONE",
                 alteration_policy="PROHIBITED", replacement_value_cents=30000,
                 base_daily_rate_cents=400, base_weekly_rate_cents=2000),
            dict(name="I10", period="CONTEMPORARY", size_class="PLUS",
                 replacement_value_cents=40000, base_daily_rate_cents=600,
                 base_weekly_rate_cents=3000),
            dict(name="I11", period="FANTASY", alteration_policy="REVERSIBLE_ONLY",
                 replacement_value_cents=200000, base_daily_rate_cents=1500,
                 base_weekly_rate_cents=7500),
        ]
        for ov in variants:
            create_catalog_item(api, **ov)

        data, meta = validate_paginated(api.list_items(house_admin_headers))
        assert len(data) == 10, f"Default page must hold 10 rows, got {len(data)}"
        assert meta["total_count"] == 11
        assert meta["has_more"] is True
        assert meta["limit"] == 10
        assert meta["offset"] == 0

        # Note: PRD §2.3 states the limit's minimum (1) and maximum (100) but is
        # silent on the enforcement mechanism for an out-of-range value (reject
        # vs clamp), so no error behavior is asserted here.
