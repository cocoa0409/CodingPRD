"""Catalog administration, entity creation shape, defaults, and derived fields."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_dealer,
    assert_order,
    assert_order_line,
    create_dealer_payload,
    create_finish_spec_payload,
    get_success_data,
    is_valid_uuid,
    make_dealer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDealerCatalog:
    def test_dealer_create_returns_full_entity(self, api, plant_admin_headers):
        """PRD §3.1: "Registering a dealer captures the company `name`, a
        `dealer_code` that must be unique across all dealers, the dealer's network
        `price_level` (one of `L1`, `L2`, `L3`, `L4`, `L5`), and a
        `credit_limit_cents` ceiling on open order exposure, which must be zero or
        greater."
        PRD §2.4: "`version` starts at 1 when the resource is created, increments
        by exactly 1 on every mutation of that resource"

        Design: Corner/entities/dealer_create_returns_full_entity
        """
        resp = api.create_dealer(
            {
                "name": "Acme Cabinets",
                "dealer_code": "ACME",
                "price_level": "L2",
                "credit_limit_cents": 5000000,
            },
            plant_admin_headers,
        )
        data = validate_success(resp, 201)
        assert_dealer(data)
        assert data["price_level"] == "L2"
        assert data["credit_limit_cents"] == 5000000
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])

    def test_dealer_duplicate_code_rejected(self, api, plant_admin_headers):
        """PRD §3.1: "A collision on `dealer_code` — or on any other unique code in
        the platform, namely `style_code`, `finish_code`, `sku`, `station_code`,
        `line_code`, or `route_code` — is rejected with `ERR_DUPLICATE_CODE` (HTTP
        400)."

        Design: Corner/entities/dealer_duplicate_code_rejected
        """
        first = api.create_dealer(
            {"name": "Acme", "dealer_code": "ACME", "price_level": "L1", "credit_limit_cents": 1000},
            plant_admin_headers,
        )
        validate_success(first, 201)
        resp = api.create_dealer(
            {"name": "Acme Clone", "dealer_code": "ACME", "price_level": "L2", "credit_limit_cents": 2000},
            plant_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CODE)

    def test_finish_spec_default_tolerance_applied(self, api, plant_admin_headers):
        """PRD §3.1: "a `delta_e_tolerance` giving the maximum acceptable color
        deviation for QC (strictly positive, defaulting to 1.5 when omitted), and
        an `active` flag defaulting to true."

        Design: Corner/entities/finish_spec_default_tolerance_applied
        """
        resp = api.create_finish_spec(
            {"finish_code": "FS-D", "color_name": "Maple", "sheen": "MATTE", "upcharge_pct": 0.05},
            plant_admin_headers,
        )
        data = validate_success(resp, 201)
        assert data["delta_e_tolerance"] == pytest.approx(1.5), (
            f"delta_e_tolerance must default to 1.5 when omitted, got {data['delta_e_tolerance']}"
        )
        assert data["active"] is True

    def test_finish_list_pagination_defaults_and_limit(self, api, plant_admin_headers):
        """PRD §2.3: "The `limit` parameter defaults to 10, must be at least 1, and
        may not exceed 100. The `offset` parameter defaults to 0. The `meta` object
        of a list response carries `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/finish_list_pagination_defaults_and_limit
        """
        for code, color, sheen in (
            ("FS-P1", "C1", "MATTE"),
            ("FS-P2", "C2", "SATIN"),
            ("FS-P3", "C3", "SEMI_GLOSS"),
        ):
            create = api.create_finish_spec(
                {"finish_code": code, "color_name": color, "sheen": sheen, "upcharge_pct": 0.0},
                plant_admin_headers,
            )
            validate_success(create, 201)

        data, meta = validate_paginated(api.list_finish_specs(plant_admin_headers, params={"limit": 2}))
        assert len(data) == 2, f"?limit=2 must return 2 rows, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        data, meta = validate_paginated(api.list_finish_specs(plant_admin_headers))
        assert len(data) == 3, f"default limit 10 must return all 3 rows, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is False


class TestOrderCreation:
    def test_order_create_initial_compound_state(self, api, plant_admin_headers):
        """PRD §3.2: "the platform stamps the new order with the acting dealer's
        identity in `dealer_id`, copies the dealer's current `price_level` into
        `price_level_snapshot` — permanently immune to later dealer edits — and
        initializes `status` to `DRAFT`, `hold_status` to `NONE`, `cube_ft` to 0,
        and `version` to 1."

        Design: Corner/entities/order_create_initial_compound_state
        """
        dealer = get_success_data(
            api.create_dealer(
                {"name": "Dealer L3", "dealer_code": "DL3", "price_level": "L3", "credit_limit_cents": 100000000},
                plant_admin_headers,
            )
        )
        resp = api.create_order(make_dealer_headers(dealer["id"]))
        order = validate_success(resp, 201)
        assert_order(order)
        assert order["status"] == "DRAFT"
        assert order["hold_status"] == "NONE"
        assert order["cube_ft"] == pytest.approx(0)
        assert order["price_level_snapshot"] == "L3"
        assert order["dealer_id"] == dealer["id"]

        # The snapshot is immune to later dealer edits.
        updated = api.update_dealer(dealer["id"], {"price_level": "L5"}, plant_admin_headers)
        validate_success(updated, 200)
        reread = validate_success(api.get_order(order["id"], plant_admin_headers))
        assert reread["price_level_snapshot"] == "L3", (
            "existing order snapshot must remain L3 after the dealer moves to L5"
        )

    def test_order_line_computed_fields_at_creation(self, api, plant_admin_headers):
        """PRD §3.2: "At line creation the platform snapshots the finish's
        `upcharge_pct` into `finish_upcharge_pct_snapshot`, computes the line's
        `line_list_cents` as the unit list price multiplied by the quantity,
        computes `finish_upcharge_cents` as the line list multiplied by the
        snapshotted upcharge fraction and rounded half up to whole cents, and
        initializes `mod_surcharge_cents` to 0. Each line is born in `PENDING`
        status."

        Design: Corner/entities/order_line_computed_fields_at_creation
        """
        dealer = get_success_data(
            api.create_dealer(
                create_dealer_payload(price_level="L3"), plant_admin_headers
            )
        )
        finish = get_success_data(
            api.create_finish_spec(
                create_finish_spec_payload(finish_code="FS-10", upcharge_pct=0.10, delta_e_tolerance=1.5),
                plant_admin_headers,
            )
        )
        order = get_success_data(api.create_order(make_dealer_headers(dealer["id"])))
        resp = api.create_order_line(
            order["id"],
            {
                "line_type": "BOX",
                "finish_id": finish["id"],
                "width_in": 24,
                "height_in": 30,
                "depth_in": 12,
                "qty": 3,
                "unit_list_price_cents": 40000,
            },
            make_dealer_headers(dealer["id"]),
        )
        line = validate_success(resp, 201)
        assert_order_line(line)
        assert line["line_list_cents"] == 120000, "line_list_cents = 40,000 x 3"
        assert line["finish_upcharge_cents"] == 12000, "upcharge = round_half_up(120,000 x 0.10)"
        assert line["finish_upcharge_pct_snapshot"] == pytest.approx(0.10)
        assert line["mod_surcharge_cents"] == 0
        assert line["status"] == "PENDING"

    def test_order_line_system_fields_input_ignored(self, api, plant_admin_headers):
        """PRD §2.4: "Every persisted resource carries an `id` that is a
        server-minted UUID with no type prefix, a `created_at` timestamp, an
        `updated_at` timestamp, and an integer `version`."

        Design: Corner/entities/order_line_system_fields_input_ignored
        """
        dealer = get_success_data(api.create_dealer(create_dealer_payload(), plant_admin_headers))
        finish = get_success_data(
            api.create_finish_spec(create_finish_spec_payload(upcharge_pct=0.10), plant_admin_headers)
        )
        order = get_success_data(api.create_order(make_dealer_headers(dealer["id"])))
        resp = api.create_order_line(
            order["id"],
            {
                "line_type": "BOX",
                "finish_id": finish["id"],
                "width_in": 24,
                "height_in": 30,
                "depth_in": 12,
                "qty": 1,
                "unit_list_price_cents": 40000,
                "id": "client-forged-id",
                "created_at": "1999-01-01T00:00:00Z",
            },
            make_dealer_headers(dealer["id"]),
        )
        line = validate_success(resp, 201)
        assert line["id"] != "client-forged-id", "server must mint its own id"
        assert is_valid_uuid(line["id"])
        assert line["created_at"] != "1999-01-01T00:00:00Z", "server must mint its own created_at"

    def test_order_get_not_found_returns_404(self, api, plant_admin_headers):
        """PRD §2.7: "Existence of path-templated resource ids, validated left to
        right along the URL; the first missing segment produces the corresponding
        not-found error (for example `ERR_ORDER_NOT_FOUND` before
        `ERR_ORDER_LINE_NOT_FOUND` on a nested path)."

        Design: Corner/entities/order_get_not_found_returns_404
        """
        resp = api.get_order("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", plant_admin_headers)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND)

    def test_hold_release_not_found_returns_404(self, api, plant_admin_headers):
        """PRD §2.7: "The per-resource not-found errors are `ERR_DEALER_NOT_FOUND`,
        `ERR_DOOR_STYLE_NOT_FOUND`, `ERR_FINISH_NOT_FOUND`, `ERR_COMPONENT_NOT_FOUND`,
        `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_MODIFICATION_NOT_FOUND`,
        `ERR_BATCH_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, `ERR_RUN_NOT_FOUND`,
        `ERR_PART_NOT_FOUND`, `ERR_ASSEMBLY_LINE_NOT_FOUND`, `ERR_SUB_LOT_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, and `ERR_HOLD_NOT_FOUND`, each
        at HTTP 404."

        Design: Corner/entities/hold_release_not_found_returns_404
        """
        resp = api.release_order_hold("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", plant_admin_headers)
        validate_error(resp, ApiErrorId.ERR_HOLD_NOT_FOUND)
