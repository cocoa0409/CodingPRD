"""Optimistic concurrency control on the three guarded write surfaces, and
the logical clock's fixed startup instant."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_ordering_at_window_end,
    create_and_submit_order,
    create_campaign_payload,
    get_success_data,
    reset_clock,
    setup_open_campaign_with_seller,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
TREAS = TEST_USERS["treasurer_headers"]


class TestCampaignOcc:
    def test_campaign_patch_stale_version_returns_412(self, api):
        """PRD §2.8: "Editing campaign settings requires
        `expected_campaign_version` to match the campaign's current `version`.
        If the campaign's version has advanced since the client last read it,
        the edit is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing
        the client from overwriting settings it has not observed."

        Design: Corner/complexity_layers/campaign_patch_stale_version_returns_412
        """
        reset_clock()
        resp = api.create_campaign(create_campaign_payload(), ADMIN)
        campaign = validate_success(resp, 201)
        observed = campaign["version"]
        first = api.patch_campaign(
            campaign["id"],
            {"expected_campaign_version": observed, "name": "Fall Sale v2"},
            ADMIN)
        patched = validate_success(first, 200)
        assert patched["version"] == observed + 1
        # The stale write replays the pre-patch version.
        stale = api.patch_campaign(
            campaign["id"],
            {"expected_campaign_version": observed,
             "school_name": "Washington"},
            ADMIN)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        after = get_success_data(api.get_campaign(campaign["id"], ADMIN))
        assert after["school_name"] == "Lincoln", (
            "the rejected patch applied nothing")

    def test_campaign_patch_missing_version_rejected(self, api):
        """PRD §2.8: "Three write endpoints are guarded by optimistic
        concurrency control, and each requires its own non-optional version
        field naming the parent entity's `version` as the client last observed
        it".
        PRD §2.10: "Third, request-body schema validation — required fields
        present, types and enum members valid, integer ranges respected,
        non-empty line arrays — rejected with `ERR_VALIDATION` (HTTP 400)".

        Design: Corner/complexity_layers/campaign_patch_stale_version_returns_412
        """
        reset_clock()
        campaign = validate_success(
            api.create_campaign(create_campaign_payload(), ADMIN), 201)
        resp = api.patch_campaign(campaign["id"], {"name": "No Version"},
                                  ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestProductOcc:
    def test_product_patch_occ_happy_path_version_increments(self, api):
        """PRD §3.1: "A product edit is admitted while the campaign is `DRAFT`
        or `OPEN`, may touch `name`, `unit_price_cents`,
        `supplier_unit_cost_cents`, `profit_share_bps`, `per_seller_limit`, or
        `returnable` alongside the mandatory `expected_product_version`, never
        retro-changes prices or costs already snapshotted onto submitted order
        lines, and increments the product's `version` by 1."

        Design: Corner/complexity_layers/product_patch_occ_happy_path_version_increments
        """
        reset_clock()
        _campaign, _group, product, seller = setup_open_campaign_with_seller()
        order = create_and_submit_order(seller["id"], product["id"], 1)
        observed = product["version"]
        resp = api.patch_product(
            product["id"],
            {"expected_product_version": observed, "unit_price_cents": 1200},
            ADMIN)
        patched = validate_success(resp, 200)
        assert patched["version"] == observed + 1
        assert patched["unit_price_cents"] == 1200
        lines, _meta = validate_paginated(
            api.list_order_lines(order["id"], COORD))
        assert lines[0]["unit_price_cents"] == 1000, (
            "the submitted order line snapshot is immutable")



class TestSupplierOrderOcc:
    def test_supplier_order_patch_stale_version_returns_412(self, api):
        """PRD §2.8: "Revising a DRAFT supplier order's line quantities
        requires `expected_supplier_order_version` to match the supplier
        order's current `version`; a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/supplier_order_patch_stale_version_returns_412
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        create_and_submit_order(seller["id"], product["id"], 2)
        close_ordering_at_window_end(campaign["id"])
        supplier_order = get_success_data(
            api.create_supplier_order({"campaign_id": campaign["id"]}, ADMIN))
        observed = supplier_order["version"]
        first = api.patch_supplier_order(
            supplier_order["id"],
            {"expected_supplier_order_version": observed,
             "line_adjustments": [{"product_id": product["id"],
                                   "requested_units": 5}]},
            ADMIN)
        patched = validate_success(first, 200)
        assert patched["version"] == observed + 1
        stale = api.patch_supplier_order(
            supplier_order["id"],
            {"expected_supplier_order_version": observed,
             "line_adjustments": [{"product_id": product["id"],
                                   "requested_units": 7}]},
            ADMIN)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    def test_supplier_order_patch_fresh_version_recovers(self, api):
        """PRD §2.8: "Revising a DRAFT supplier order's line quantities
        requires `expected_supplier_order_version` to match the supplier
        order's current `version`".

        Design: Corner/complexity_layers/supplier_order_patch_stale_version_returns_412
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        create_and_submit_order(seller["id"], product["id"], 2)
        close_ordering_at_window_end(campaign["id"])
        supplier_order = get_success_data(
            api.create_supplier_order({"campaign_id": campaign["id"]}, ADMIN))
        observed = supplier_order["version"]
        get_success_data(api.patch_supplier_order(
            supplier_order["id"],
            {"expected_supplier_order_version": observed,
             "line_adjustments": [{"product_id": product["id"],
                                   "requested_units": 5}]},
            ADMIN))
        current = get_success_data(
            api.get_supplier_order(supplier_order["id"], ADMIN))
        resp = api.patch_supplier_order(
            supplier_order["id"],
            {"expected_supplier_order_version": current["version"],
             "line_adjustments": [{"product_id": product["id"],
                                   "requested_units": 7}]},
            ADMIN)
        repatched = validate_success(resp, 200)
        assert repatched["version"] == current["version"] + 1, (
            "a fresh observed version is admitted")


class TestLogicalClockDefault:
    def test_clock_default_is_fixed_earliest_instant(self, api):
        """PRD §2.5: "At startup, before any clock-setting call has been made,
        the logical clock reads exactly `2026-08-01T00:00:00Z`; the server
        never falls back to wall-clock time."
        PRD §3.2: "the logical clock must lie at or after
        `order_window_start` and at or before `order_window_end` (else
        `ERR_OUTSIDE_ORDER_WINDOW`)".

        Design: Corner/complexity_layers/clock_default_is_fixed_earliest_instant
        """
        # Deliberately NO clock call: the startup default 2026-08-01T00:00:00Z
        # is the window start, and the inclusive boundary admits the submit.
        campaign = get_success_data(
            api.create_campaign(create_campaign_payload(), ADMIN))
        from test_helpers import create_group, create_product, create_seller
        group = create_group(campaign["id"])
        product = create_product(campaign["id"])
        seller = create_seller(group["id"])
        get_success_data(api.open_campaign(campaign["id"], ADMIN))
        order = create_and_submit_order(seller["id"], product["id"], 1)
        assert order["status"] == "SUBMITTED", (
            "the default clock instant equals the inclusive window start")
