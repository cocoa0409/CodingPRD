"""Cross-cutting concerns: RBAC, authentication, optimistic concurrency,
pagination, filters, and read-after-write visibility (PRD §2)."""
from test_helpers import (
    ADMIN,
    ADVISOR,
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_customer,
    create_cylinder,
    create_cylinder_payload,
    create_exchange_unit,
    create_seal_kit_payload,
    create_shop,
    create_work_order_payload,
    get_success_data,
    make_customer_headers,
    make_technician_headers,
    open_work_order,
    setup_master_data,
    setup_quote_draft,
    setup_quote_sent,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRbac:
    def test_technician_cannot_create_quote_forbidden(self, api):
        """PRD §2.1: "Access to specific operations is further restricted by role
        per the endpoint matrix in §4; an attempt to perform an action outside
        the caller's designated role is rejected with an `ERR_FORBIDDEN` error."
        PRD §4: "| POST | `/fluid-power/quotes` | Draft a quote from the current
        teardown report | ShopAdmin, ServiceAdvisor |"

        Design: Corner/rbac/technician_cannot_create_quote_forbidden
        """
        sc = setup_quote_draft(rod_needed=False, honing_passes=0, estimated_labor_hours=1.0)
        resp = api.create_quote(
            {"work_order_id": sc.work_order["id"]},
            make_technician_headers(sc.tech["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert resp.status_code == 403

    def test_customer_cannot_approve_other_customers_quote(self, api):
        """PRD §3.4: "Approval belongs to the owning `Customer` alone; a customer
        whose `X-User-ID` does not equal the work order's `customer_id` is
        rejected with `ERR_NOT_OWNER`"

        Design: Corner/rbac/customer_cannot_approve_other_customers_quote
        """
        sc = setup_quote_sent(rod_needed=False, honing_passes=0, estimated_labor_hours=1.0)
        other = create_customer(full_name="Beta", email="b@b.com")
        resp = api.approve_quote(sc.quote["id"], make_customer_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_OWNER)
        assert resp.status_code == 403
        quote = get_success_data(api.get_quote(sc.quote["id"], ADVISOR))
        assert quote["status"] == "SENT"

    def test_customer_cannot_write_catalog_forbidden(self, api):
        """PRD §2.1: "Access to specific operations is further restricted by role
        per the endpoint matrix in §4; an attempt to perform an action outside
        the caller's designated role is rejected with an `ERR_FORBIDDEN` error."
        PRD §4: "| POST | `/fluid-power/seal-kits` | Create a seal-kit catalog
        entry | ShopAdmin |"

        Design: Corner/rbac/customer_cannot_write_catalog_forbidden
        """
        create_shop()
        customer = create_customer()
        resp = api.create_seal_kit(
            create_seal_kit_payload(kit_code="SK-X", price_cents=1000),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert resp.status_code == 403


class TestAuthentication:
    def test_request_without_credentials_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role outside
        this declared set, is rejected with an `ERR_UNAUTHENTICATED` error."
        PRD §2.9: "Validations are applied to every request in a fixed priority
        order, and an earlier failure masks every later one — the client always
        sees the first failing check's error, never a later check's."

        Design: Corner/errors/request_without_credentials_unauthenticated
        """
        create_shop()
        # No X-User-Role / X-User-ID headers at all; even with an unknown id in
        # the path, authentication (priority 2) precedes existence (priority 5).
        resp = api.get_shop(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert resp.status_code == 401


class TestOptimisticConcurrency:
    def test_teardown_patch_stale_version_rejected(self, api):
        """PRD §2.6: "Revising a teardown report requires
        `expected_teardown_report_version`, compared against the
        `TeardownReport`'s current `version`. A rejection means the client's
        edits are based on a stale revision of the findings."
        PRD §2.6: "A sequential retry carrying the current version succeeds:
        revisions legitimately build on one another, and several non-overlapping
        jobs legitimately share one technician's calendar."

        Design: Corner/cross_cutting_layers/teardown_patch_stale_version_rejected
        """
        sc = setup_quote_draft(rod_needed=False, honing_passes=0, estimated_labor_hours=1.0)
        headers = make_technician_headers(sc.tech["id"])
        revised = get_success_data(
            api.patch_teardown_report(
                sc.report["id"],
                {"expected_teardown_report_version": sc.report["version"],
                 "estimated_labor_hours": 1.5},
                headers,
            )
        )
        assert revised["version"] == 2
        # Stale write carrying the pre-update version is rejected.
        resp = api.patch_teardown_report(
            sc.report["id"],
            {"expected_teardown_report_version": 1, "estimated_labor_hours": 2.0},
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412
        report = get_success_data(api.get_teardown_report(sc.report["id"], ADVISOR))
        assert report["estimated_labor_hours"] == 1.5
        assert report["version"] == 2
        # Sequential retry with the current version succeeds.
        retried = get_success_data(
            api.patch_teardown_report(
                sc.report["id"],
                {"expected_teardown_report_version": 2, "estimated_labor_hours": 2.0},
                headers,
            )
        )
        assert retried["version"] == 3
        assert retried["estimated_labor_hours"] == 2.0

    def test_shop_config_patch_stale_version_rejected(self, api):
        """PRD §2.6: "Updating shop configuration requires
        `expected_shop_version`, compared against the `Shop`'s current
        `version`. A rejection means rate and cutoff edits would not be building
        on the current configuration."

        Design: Corner/cross_cutting_layers/shop_config_patch_stale_version_rejected
        """
        shop = create_shop()
        assert shop["version"] == 1
        updated = get_success_data(
            api.patch_shop(
                shop["id"],
                {"expected_shop_version": shop["version"],
                 "labor_rate_cents_per_hour": 15000},
                ADMIN,
            )
        )
        assert updated["version"] == 2
        assert updated["labor_rate_cents_per_hour"] == 15000
        resp = api.patch_shop(
            shop["id"],
            {"expected_shop_version": 1, "honing_pass_fee_cents": 4500},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412
        shop_after = get_success_data(api.get_shop(shop["id"], ADMIN))
        assert shop_after["honing_pass_fee_cents"] == 4000
        assert shop_after["labor_rate_cents_per_hour"] == 15000
        assert shop_after["version"] == 2


class TestListingAndEnvelope:
    def test_exchange_units_pagination_limit_offset_has_more(self, api):
        """PRD §2.3: "Paginated list responses include the following fields in
        the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."
        PRD §2.3: "The `limit` parameter specifies the maximum number of items to
        return; if not provided it defaults to 10, with a minimum of 1 and a
        maximum of 100. The `offset` parameter specifies the number of items to
        skip and defaults to 0."

        Design: Corner/endpoints/exchange_units_pagination_limit_offset_has_more
        """
        create_shop()
        create_exchange_unit()
        create_exchange_unit(bore_mm=100, stroke_mm=600, rod_diameter_mm=50,
                             pressure_class="CLASS_5000", unit_price_cents=320000)
        create_exchange_unit(bore_mm=125, stroke_mm=700, rod_diameter_mm=60,
                             unit_price_cents=410000)
        resp1 = api.list_exchange_units(ADVISOR, params={"limit": 2})
        data1, meta1 = validate_paginated(resp1)
        assert resp1.json()["response_type"] == "array"
        assert len(data1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0
        data2, meta2 = validate_paginated(
            api.list_exchange_units(ADVISOR, params={"limit": 2, "offset": 2})
        )
        assert len(data2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert meta2["offset"] == 2

    def test_work_orders_filtered_list_by_fk_narrows_results(self, api):
        """PRD §3.2: "The work-order collection can be listed with filters on
        `cylinder_id`, `customer_id`, `status`, and `assigned_technician_id`."

        Design: Corner/endpoints/work_orders_filtered_list_by_fk_narrows_results
        """
        md = setup_master_data()
        cust_b = create_customer(full_name="Beta", email="b@b.com")
        cyl_a1 = create_cylinder(md.customer["id"], md.kit["id"], serial_number="A-1")
        cyl_a2 = create_cylinder(md.customer["id"], md.kit["id"], serial_number="A-2")
        cyl_b1 = create_cylinder(cust_b["id"], md.kit["id"], serial_number="B-1")
        for cyl, complaint in ((cyl_a1, "leak"), (cyl_a2, "drift"), (cyl_b1, "scored rod")):
            open_work_order(cyl["id"], tier="STANDARD", promised_hours=96,
                            complaint=complaint)
        data_a, meta_a = validate_paginated(
            api.list_work_orders(ADVISOR, params={"customer_id": md.customer["id"]})
        )
        assert meta_a["total_count"] == 2
        assert all(wo["customer_id"] == md.customer["id"] for wo in data_a)
        data_narrow, meta_narrow = validate_paginated(
            api.list_work_orders(
                ADVISOR,
                params={"customer_id": md.customer["id"], "cylinder_id": cyl_a2["id"]},
            )
        )
        assert meta_narrow["total_count"] == 1
        assert data_narrow[0]["cylinder_id"] == cyl_a2["id"]


class TestReadAfterWrite:
    def test_read_after_write_immediate_consistency(self, api):
        """PRD §2.4: "`version` (integer): starts at 1 when the resource is
        created and increments by one with every modification."
        PRD §3.1: "A registered cylinder starts `ACTIVE` and later moves to
        `RETIRED` when scrapped or `EXCHANGED` when swapped for a remanufactured
        unit."

        Design: Corner/consistency_model/read_after_write_immediate_consistency
        """
        md = setup_master_data()
        created = create_cylinder(md.customer["id"], md.kit["id"], serial_number="CYL-C99")
        fetched = get_success_data(api.get_cylinder(created["id"], ADVISOR))
        assert fetched["serial_number"] == "CYL-C99"
        assert fetched["status"] == "ACTIVE"
        assert fetched["version"] == 1
        assert fetched["customer_id"] == md.customer["id"]
        assert fetched["seal_kit_id"] == md.kit["id"]
        assert fetched["bore_mm"] == 80
        assert fetched["stroke_mm"] == 500
        assert fetched["rod_diameter_mm"] == 45
        assert fetched["pressure_class"] == "CLASS_3000"
        assert fetched["fluid_type"] == "MINERAL_OIL"

    def test_inventory_item_get_not_found_returns_404(self, api):
        """PRD §2.9: "Path identifiers and body foreign keys reference existing
        resources, validated left-to-right so the first missing reference in the
        path is the one reported; failures are rejected with `ERR_NOT_FOUND`."

        Design: Corner/entities/inventory_item_get_not_found_returns_404
        """
        create_shop()
        resp = api.get_inventory_item(NON_EXISTENT_UUID, ADVISOR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert resp.status_code == 404
