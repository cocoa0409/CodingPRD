"""Creation, defaults, computed fields and reads across the entity surface (PRD §2.2, §3.1, §3.3, §3.5)."""

from test_helpers import (
    FLOUR_HRW_LIST_ONLY,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    approve_substitution_request,
    claim_substitution_request,
    create_contract_line_payload,
    create_customer_payload,
    create_order_line_payload,
    create_product,
    create_product_payload,
    create_zone,
    open_order,
    publish_index_quote,
    raise_substitution_request,
    read_lot,
    read_order,
    read_order_line,
    read_zone,
    receive_lot,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import AM, PC, WO, buyer_headers


class TestCustomerRegistrationSurface:
    """The four fields registration derives, and the one optional input."""

    def test_registering_a_bakery_initialises_status_exposure_score_and_tier(self):
        """PRD §3.1: "Registration initialises the remaining fields
        deterministically: `status` becomes `ACTIVE`, `open_exposure_cents`
        becomes 0, `allergen_risk_score` becomes 0.00, and `risk_tier` becomes
        `GREEN`."

        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."

        Design: Corner/entities/corner_create_customer_initialises_system_and_computed_fields
        """
        set_clock("2026-08-01T00:00:00Z")

        response = api_client.create_customer(
            create_customer_payload(
                legal_name="Rye Lane Bakery",
                allergen_program="STANDARD",
                credit_limit_cents=5000000,
                min_drop_cents=25000,
            ),
            AM,
        )

        customer = validate_success(response, 201)
        assert customer["status"] == "ACTIVE", (
            f"Expected ACTIVE, got {customer['status']}"
        )
        assert customer["open_exposure_cents"] == 0, (
            f"Expected open_exposure_cents 0, got {customer['open_exposure_cents']}"
        )
        assert float(customer["allergen_risk_score"]) == 0.00, (
            f"Expected allergen_risk_score 0.00, got {customer['allergen_risk_score']}"
        )
        assert customer["risk_tier"] == "GREEN", (
            f"Expected GREEN, got {customer['risk_tier']}"
        )
        assert customer["min_drop_cents"] == 25000, (
            f"Expected the supplied floor of 25000, got {customer['min_drop_cents']}"
        )
        body = response.json()
        assert body["response_type"] == "object", (
            f"Expected response_type object, got {body['response_type']}"
        )
        assert body["meta"]["api_request_id"].startswith("req_"), (
            f"Expected an api_request_id starting with req_, got {body['meta']['api_request_id']}"
        )
        assert body["meta"]["api_request_timestamp"], (
            "Every success envelope carries an api_request_timestamp"
        )

    def test_omitting_the_drop_floor_persists_the_two_hundred_fifty_dollar_default(self):
        """PRD §3.1: "A fourth input, `min_drop_cents`, is optional and expresses
        the smallest priced value a single delivery drop to this bakery may carry;
        when the account manager does not supply it, the account is created with a
        two hundred fifty dollar floor — that is, 25000 cents."

        Design: Corner/entities/corner_default_min_drop_cents_applied_when_field_omitted
        """
        set_clock("2026-08-01T00:00:00Z")
        payload = create_customer_payload(
            legal_name="Default Drop Bakery",
            allergen_program="STANDARD",
            credit_limit_cents=900000,
        )
        payload.pop("min_drop_cents")

        customer = validate_success(api_client.create_customer(payload, AM), 201)

        assert customer["min_drop_cents"] == 25000, (
            f"Expected the default 25000, got {customer['min_drop_cents']}"
        )
        assert customer["min_drop_cents"] is not None
        assert customer["allergen_program"] == "STANDARD", (
            f"Expected STANDARD, got {customer['allergen_program']}"
        )


class TestLotComputedExpiry:
    """`expires_on` is computed from the SKU's shelf life, never supplied."""

    def test_receipt_derives_the_expiry_from_the_products_shelf_life_days(self):
        """PRD §3.5: "Receipt computes `expires_on` as the manufacture date
        advanced by the product's `shelf_life_days`, landing at midnight UTC, and
        initialises the three pound buckets: `quantity_on_hand_lb` equals
        `quantity_received_lb`, while `quantity_reserved_lb` and
        `quantity_consumed_lb` are both 0."

        180 shelf-life days advanced from 2026-07-01 land on 2026-12-28.

        Design: Corner/entities/corner_computed_lot_expires_on_derived_from_shelf_life_days
        """
        set_clock("2026-08-01T00:00:00Z")
        flour = create_product(
            FLOUR_HRW_LIST_ONLY,
            sku="FLR-BREAD-50",
            shelf_life_days=180,
            list_price_cents_per_lb=30,
            min_rotation_days=0,
        )
        zone = create_zone(zone_code="Z-GLU", allergen_class="GLUTEN")

        lot = receive_lot(
            flour["id"],
            zone["id"],
            lot_code="LOT-GLU-0001",
            manufactured_on="2026-07-01T00:00:00Z",
            quantity_received_lb=40000,
        )

        assert lot["expires_on"] == "2026-12-28T00:00:00Z", (
            f"Expected expires_on 2026-12-28T00:00:00Z, got {lot['expires_on']}"
        )
        assert lot["quantity_on_hand_lb"] == 40000, (
            f"Expected 40000 lb on hand, got {lot['quantity_on_hand_lb']}"
        )
        assert lot["quantity_reserved_lb"] == 0, (
            f"Expected 0 lb reserved, got {lot['quantity_reserved_lb']}"
        )
        assert lot["quantity_consumed_lb"] == 0, (
            f"Expected 0 lb consumed, got {lot['quantity_consumed_lb']}"
        )
        assert lot["status"] == "AVAILABLE", (
            f"Expected AVAILABLE, got {lot['status']}"
        )
        assert read_lot(lot["id"])["expires_on"] == "2026-12-28T00:00:00Z", (
            "The computed expiry must survive a read-back"
        )
        assert read_zone(zone["id"])["on_hand_lb"] == 40000, (
            "The zone total follows the on-hand pounds of its lots"
        )


class TestOrderReadSurface:
    """A freshly opened order shows both dimensions and five zeroed money fields."""

    def test_reading_a_new_order_shows_new_unpriced_and_every_money_field_at_zero(self):
        """PRD §3.3: "A new order begins with `fulfillment_status` at `NEW`,
        `pricing_status` at `UNPRICED`, `surge_window` false, `short_ship_lb` at
        0, and every money field — `subtotal_cents`, `fuel_surcharge_cents`,
        `tech_attach_fee_cents`, `volume_rebate_cents` and `total_cents` — at 0."

        PRD §3.3: "Both `order_placed_on` and `delivered_on` are null until the
        respective events stamp them."

        Design: Corner/entities/corner_read_order_returns_both_status_dimensions_and_money_fields
        """
        set_clock("2026-08-01T00:00:00Z")
        customer = validate_success(
            api_client.create_customer(
                create_customer_payload(
                    legal_name="Read Back Bakery", credit_limit_cents=5000000
                ),
                AM,
            ),
            201,
        )
        opened = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on="2026-09-10T00:00:00Z",
        )

        order = validate_success(
            api_client.get_order(opened["id"], buyer_headers(customer))
        )

        assert order["fulfillment_status"] == "NEW", (
            f"Expected NEW, got {order['fulfillment_status']}"
        )
        assert order["pricing_status"] == "UNPRICED", (
            f"Expected UNPRICED, got {order['pricing_status']}"
        )
        assert order["subtotal_cents"] == 0, (
            f"Expected subtotal_cents 0, got {order['subtotal_cents']}"
        )
        assert order["fuel_surcharge_cents"] == 0, (
            f"Expected fuel_surcharge_cents 0, got {order['fuel_surcharge_cents']}"
        )
        assert order["tech_attach_fee_cents"] == 0, (
            f"Expected tech_attach_fee_cents 0, got {order['tech_attach_fee_cents']}"
        )
        assert order["volume_rebate_cents"] == 0, (
            f"Expected volume_rebate_cents 0, got {order['volume_rebate_cents']}"
        )
        assert order["total_cents"] == 0, (
            f"Expected total_cents 0, got {order['total_cents']}"
        )
        assert order["surge_window"] is False, (
            f"A 2026-09-10 delivery is outside both windows, got {order['surge_window']}"
        )
        assert order["short_ship_lb"] == 0, (
            f"Expected short_ship_lb 0, got {order['short_ship_lb']}"
        )
        assert order["order_placed_on"] is None, (
            f"Expected order_placed_on null, got {order['order_placed_on']}"
        )
        assert order["delivered_on"] is None, (
            f"Expected delivered_on null, got {order['delivered_on']}"
        )


class TestLotListingWindow:
    """Lots deviate from the default ordering: earliest expiry first."""

    def test_a_two_row_page_returns_the_two_earliest_expiring_lots(self):
        """PRD §2.3: "the collections that deviate — lots ordered by `expires_on`
        ascending then `created_at` ascending, index quotes ordered by
        `effective_on` descending, routes ordered by `service_on` ascending then
        `created_at` ascending, and route stops ordered by `window_start_at`
        ascending then `created_at` ascending — say so in their descriptions."

        PRD §2.3: "List responses populate four fields inside `meta`: the `limit`
        and `offset` actually applied, `total_count` giving the number of matching
        rows before the page window is applied, and `has_more`, which is true when
        rows remain beyond the current page."

        Design: Corner/entities/corner_list_lots_pagination_and_expiry_ordering
        """
        set_clock("2026-08-01T00:00:00Z")
        flour = create_product(
            FLOUR_HRW_LIST_ONLY,
            sku="FLR-BREAD-50",
            shelf_life_days=180,
            list_price_cents_per_lb=30,
            min_rotation_days=0,
        )
        zone = create_zone(zone_code="Z-GLU", allergen_class="GLUTEN")
        lot_a = receive_lot(
            flour["id"],
            zone["id"],
            lot_code="LOT-GLU-A",
            manufactured_on="2026-07-01T00:00:00Z",
            quantity_received_lb=40000,
        )
        lot_b = receive_lot(
            flour["id"],
            zone["id"],
            lot_code="LOT-GLU-B",
            manufactured_on="2026-06-01T00:00:00Z",
            quantity_received_lb=10000,
        )
        lot_c = receive_lot(
            flour["id"],
            zone["id"],
            lot_code="LOT-GLU-C",
            manufactured_on="2026-07-15T00:00:00Z",
            quantity_received_lb=5000,
        )

        response = api_client.list_lots(
            WO, params={"product_id": flour["id"], "limit": 2, "offset": 0}
        )

        lots, meta = validate_paginated(response)
        assert response.json()["response_type"] == "array", (
            f"Expected response_type array, got {response.json()['response_type']}"
        )
        assert meta["total_count"] == 3, (
            f"Expected total_count 3 before the window, got {meta['total_count']}"
        )
        assert meta["has_more"] is True, (
            f"Expected has_more true with a third row beyond the page, got {meta['has_more']}"
        )
        assert meta["limit"] == 2, f"Expected limit 2, got {meta['limit']}"
        assert meta["offset"] == 0, f"Expected offset 0, got {meta['offset']}"
        assert len(lots) == 2, f"Expected exactly 2 rows on the page, got {len(lots)}"
        assert lots[0]["id"] == lot_b["id"], (
            f"Expected the 2026-11-28 lot first, got {lots[0]['lot_code']}"
        )
        assert lots[0]["expires_on"] == "2026-11-28T00:00:00Z", (
            f"Expected expires_on 2026-11-28T00:00:00Z, got {lots[0]['expires_on']}"
        )
        assert lots[1]["id"] == lot_a["id"], (
            f"Expected the 2026-12-28 lot second, got {lots[1]['lot_code']}"
        )
        assert lots[1]["expires_on"] == "2026-12-28T00:00:00Z", (
            f"Expected expires_on 2026-12-28T00:00:00Z, got {lots[1]['expires_on']}"
        )
        assert lot_c["id"] not in [lot["id"] for lot in lots], (
            "The 2027-01-11 lot sorts last and must fall outside the first page"
        )


class TestUnknownIdentifierReads:
    """Path resolution, and the difference between a path and a body reference."""

    def test_reading_an_order_id_no_row_carries_is_a_not_found(self):
        """PRD §2.7: "The first path segment whose referenced row does not exist
        produces `ERR_RESOURCE_NOT_FOUND` (HTTP 404), and no deeper segment is
        examined."

        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/entities/corner_get_order_unknown_id_not_found
        """
        set_clock("2026-08-01T00:00:00Z")
        customer = validate_success(
            api_client.create_customer(
                create_customer_payload(
                    legal_name="No Orders Bakery", credit_limit_cents=100000
                ),
                AM,
            ),
            201,
        )

        response = api_client.get_order(NON_EXISTENT_UUID, buyer_headers(customer))

        validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND)
        assert response.status_code == 404, (
            f"Expected HTTP 404, got {response.status_code}"
        )
        assert response.json()["response_type"] == "error", (
            f"Expected response_type error, got {response.json()['response_type']}"
        )


class TestRequestBodySchemaSurface:
    """Required fields and declared enums, both reported as `ERR_VALIDATION`."""

    def test_a_line_without_a_quantity_is_a_schema_violation(self):
        """PRD §3.3: "Lines are added to an order while it remains `UNPRICED`,
        each naming a `product_id` and a `quantity_lb` strictly greater than
        zero."

        PRD §2.7: "Schema validation of the request body and query string follows
        — required fields present, types correct, enum values drawn from the
        declared set, `quantity_lb` strictly greater than zero".

        Design: Corner/entities/corner_order_line_missing_required_quantity_lb_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        customer = validate_success(
            api_client.create_customer(
                create_customer_payload(
                    legal_name="Missing Field Bakery", credit_limit_cents=5000000
                ),
                AM,
            ),
            201,
        )
        flour = create_product(
            FLOUR_HRW_LIST_ONLY, sku="FLR-BREAD-50", list_price_cents_per_lb=30
        )
        order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on="2026-09-10T00:00:00Z",
        )
        version_before = read_order(order["id"])["version"]

        response = api_client.create_order_line(
            order["id"], {"product_id": flour["id"]}, buyer_headers(customer)
        )

        validate_error(response, ApiErrorId.ERR_VALIDATION)
        assert response.status_code == 400, (
            f"Expected HTTP 400, got {response.status_code}"
        )
        lines, meta = validate_paginated(
            api_client.list_order_lines_of_order(order["id"], buyer_headers(customer))
        )
        assert meta["total_count"] == 0, (
            f"Expected no line row to have been created, got {meta['total_count']}"
        )
        assert lines == [], f"Expected an empty page, got {len(lines)} rows"
        assert read_order(order["id"])["version"] == version_before, (
            "A rejected call is not a mutation, so the order version must not move"
        )

    def test_an_allergen_class_outside_the_seven_declared_values_is_refused(self):
        """PRD §2.8: "Every SKU carries an `allergen_class` drawn from `NONE`,
        `GLUTEN`, `TREE_NUT`, `PEANUT`, `DAIRY`, `EGG`, or `SOY`, and every
        warehouse zone and every trailer lock uses that same set of seven
        values."

        PRD §2.7: "Schema validation of the request body and query string follows
        — required fields present, types correct, enum values drawn from the
        declared set".

        Design: Corner/entities/corner_product_invalid_enum_allergen_class_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        payload = create_product_payload(
            sku="SESAME-PASTE",
            category="INCLUSION",
            allergen_class="SESAME",
            shelf_life_days=90,
            list_price_cents_per_lb=210,
        )

        response = api_client.create_product(payload, PC)

        validate_error(response, ApiErrorId.ERR_VALIDATION)
        assert response.status_code == 400, (
            f"Expected HTTP 400, got {response.status_code}"
        )
        assert "id" not in response.json()["data"], (
            "A refused creation returns an error envelope, never a persisted id"
        )
        accepted = validate_success(
            api_client.create_product(dict(payload, allergen_class="TREE_NUT"), PC), 201
        )
        assert accepted["allergen_class"] == "TREE_NUT", (
            f"Expected TREE_NUT, got {accepted['allergen_class']}"
        )
        assert accepted["sku"] == "SESAME-PASTE", (
            "The rejected call persisted nothing, so the same SKU code is still free"
        )


class TestSystemStampedOrderDate:
    """`order_placed_on` comes from the logical clock, not from the delivery date."""

    def test_submission_stamps_the_placement_date_from_the_logical_clock(self):
        """PRD §3.3: "Both `order_placed_on` and `delivered_on` are null until the
        respective events stamp them."

        PRD §2.4: "Time in this service is a **logical clock**, not wall-clock
        time. Before any operator sets it, the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and it must never fall back to real system time."

        Submission is the event that stamps placement, so with the clock moved to
        2026-08-20 the order records that date and not the 2026-09-10 delivery
        date. 1000 lb at 30 cents earns no discount: 30000 plus a 750 cent
        out-of-surge surcharge, with a 30750 cent rebate base below 500000 earning
        nothing, gives 30750.

        Design: Corner/entities/corner_system_field_order_placed_on_stamped_from_logical_clock
        """
        set_clock("2026-08-01T00:00:00Z")
        customer = validate_success(
            api_client.create_customer(
                create_customer_payload(
                    legal_name="Clock Stamp Bakery",
                    credit_limit_cents=5000000,
                    min_drop_cents=25000,
                ),
                AM,
            ),
            201,
        )
        flour = create_product(
            FLOUR_HRW_LIST_ONLY, sku="FLR-BREAD-50", list_price_cents_per_lb=30
        )
        order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on="2026-09-10T00:00:00Z",
        )
        validate_success(
            api_client.create_order_line(
                order["id"],
                create_order_line_payload(flour["id"], 1000),
                buyer_headers(customer),
            ),
            201,
        )
        set_clock("2026-08-20T00:00:00Z")

        submitted = validate_success(
            api_client.submit_order(order["id"], {}, buyer_headers(customer))
        )

        assert submitted["order_placed_on"] == "2026-08-20T00:00:00Z", (
            f"Expected order_placed_on 2026-08-20T00:00:00Z, got {submitted['order_placed_on']}"
        )
        assert submitted["requested_delivery_on"] == "2026-09-10T00:00:00Z", (
            f"Expected the delivery date untouched, got {submitted['requested_delivery_on']}"
        )
        assert submitted["pricing_status"] == "PROVISIONAL", (
            f"Expected PROVISIONAL, got {submitted['pricing_status']}"
        )
        assert submitted["fulfillment_status"] == "NEW", (
            f"Expected the physical dimension still NEW, got {submitted['fulfillment_status']}"
        )
        assert submitted["total_cents"] == 30750, (
            f"Expected total 30750, got {submitted['total_cents']}"
        )


class TestIndexQuoteImmutability:
    """A superseding price is a second row, never a mutation of the first."""

    def test_two_quotes_list_newest_first_and_expose_no_version_field(self):
        """PRD §2.4: "The single exception is the published commodity index quote:
        a `CommodityIndexQuote` is an immutable market observation and carries only
        `id` and `created_at` — it has neither `updated_at` nor `version`, and no
        endpoint mutates one once published."

        PRD §3.1: "A published quote governs every observation date from its
        `effective_on` onward until a later quote for the same index supersedes
        it."

        Design: Corner/entities/corner_immutable_index_quote_exposes_no_version_and_no_mutator
        """
        set_clock("2026-08-01T00:00:00Z")
        july = publish_index_quote(
            index_code="HRW_WHEAT",
            effective_on="2026-07-15T00:00:00Z",
            price_cents_per_lb=25,
        )
        august = publish_index_quote(
            index_code="HRW_WHEAT",
            effective_on="2026-08-20T00:00:00Z",
            price_cents_per_lb=40,
        )

        quotes, meta = validate_paginated(
            api_client.list_index_quotes(
                PC, params={"index_code": "HRW_WHEAT", "limit": 10, "offset": 0}
            )
        )

        assert meta["total_count"] == 2, (
            f"Expected total_count 2, got {meta['total_count']}"
        )
        assert quotes[0]["effective_on"] == "2026-08-20T00:00:00Z", (
            f"Expected the newest effective date first, got {quotes[0]['effective_on']}"
        )
        assert quotes[0]["id"] == august["id"]
        assert quotes[1]["effective_on"] == "2026-07-15T00:00:00Z", (
            f"Expected the older quote second, got {quotes[1]['effective_on']}"
        )
        assert quotes[1]["id"] == july["id"]
        for quote in quotes:
            assert "version" not in quote, (
                f"An immutable quote carries no version field, got {quote.get('version')}"
            )
            assert "updated_at" not in quote, (
                f"An immutable quote carries no updated_at field, got {quote.get('updated_at')}"
            )
            assert quote["created_at"], "Every persisted row carries created_at"
        assert quotes[1]["price_cents_per_lb"] == 25, (
            f"Publishing the August quote must not rewrite the July price, got "
            f"{quotes[1]['price_cents_per_lb']}"
        )


class TestNestedPathParentResolution:
    """A missing parent in the path outranks any body foreign key."""

    def test_adding_a_line_to_an_unknown_contract_is_a_path_not_found(self):
        """PRD §2.7: "Nested resources are addressed hierarchically, and existence
        is verified strictly left to right: the route before the stop, the contract
        before the contract line, the order before the order line."

        PRD §2.7: "Foreign keys arriving in a request body are a separate concern:
        `customer_id`, `product_id`, `zone_id`, `contract_id`, `order_id`,
        `order_line_id`, `proposed_product_id` and `route_id` must each resolve to
        an existing row, and a key that does not resolve yields
        `ERR_REFERENCED_ENTITY_NOT_FOUND`, also HTTP 404."

        The body's `product_id` resolves perfectly well; it is the contract in the
        path that does not exist, so path resolution answers first.

        Design: Corner/entities/corner_contract_line_on_unknown_contract_path_not_found
        """
        set_clock("2026-08-01T00:00:00Z")
        flour = create_product(
            FLOUR_HRW_LIST_ONLY, sku="FLR-BREAD-50", list_price_cents_per_lb=30
        )

        response = api_client.create_contract_line(
            NON_EXISTENT_UUID,
            create_contract_line_payload(
                flour["id"], volume_committed_lb=10000, basis_cents_per_lb=5
            ),
            AM,
        )

        validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND)
        assert response.status_code == 404, (
            f"Expected HTTP 404, got {response.status_code}"
        )
        assert response.json()["data"]["error_id"] != "ERR_REFERENCED_ENTITY_NOT_FOUND", (
            "The unresolvable segment is the path parent, not a body foreign key"
        )
        _lines, meta = validate_paginated(
            api_client.list_contract_lines(PC, params={"product_id": flour["id"]})
        )
        assert meta["total_count"] == 0, (
            f"Expected no commitment line to have been created, got {meta['total_count']}"
        )


class TestSubstitutedFromSelfLink:
    """The order line keeps a self-referential pointer at the SKU it left behind."""

    def test_approval_records_the_original_sku_and_the_filter_finds_the_line(self):
        """PRD §3.8: "**Hop one:** the order line's current `product_id` is copied
        into `substituted_from_product_id`, and `product_id` becomes the request's
        `proposed_product_id`."

        PRD §3.3: "Order lines are likewise readable per order and across orders,
        filterable by `order_id`, `product_id`, `substituted_from_product_id`,
        `lot_id`, `silo_id`, `contract_line_id` and `allocation_status`."

        Hop three reprices the line at the cake flour's 40 cents: 40000 subtotal
        plus a 1000 cent out-of-surge surcharge, with no rebate below 500000, is
        41000.

        Design: Corner/entities/corner_self_referential_substituted_from_product_link_persisted
        """
        set_clock("2026-08-01T00:00:00Z")
        customer = validate_success(
            api_client.create_customer(
                create_customer_payload(
                    legal_name="Swap Trace Bakery",
                    credit_limit_cents=5000000,
                    min_drop_cents=25000,
                ),
                AM,
            ),
            201,
        )
        bread_flour = create_product(
            FLOUR_HRW_LIST_ONLY, sku="FLR-BREAD-50", list_price_cents_per_lb=30
        )
        cake_flour = create_product(
            FLOUR_HRW_LIST_ONLY, sku="FLR-CAKE-50", list_price_cents_per_lb=40
        )
        zone = create_zone(zone_code="Z-GLU", allergen_class="GLUTEN")
        receive_lot(bread_flour["id"], zone["id"], lot_code="LOT-GLU-BREAD")
        receive_lot(cake_flour["id"], zone["id"], lot_code="LOT-GLU-CAKE")
        order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on="2026-09-10T00:00:00Z",
        )
        line = validate_success(
            api_client.create_order_line(
                order["id"],
                create_order_line_payload(bread_flour["id"], 1000),
                buyer_headers(customer),
            ),
            201,
        )
        validate_success(
            api_client.submit_order(order["id"], {}, buyer_headers(customer))
        )
        request = raise_substitution_request(
            line["id"],
            cake_flour["id"],
            read_order(order["id"])["version"],
            rationale="Cake flour protein spec matches the revised sponge formula",
        )
        claim_substitution_request(request["id"])

        approved = approve_substitution_request(request["id"])

        assert approved["status"] == "APPROVED", (
            f"Expected APPROVED, got {approved['status']}"
        )
        swapped = read_order_line(line["id"])
        assert swapped["product_id"] == cake_flour["id"], (
            f"Expected the cake flour on the line, got {swapped['product_id']}"
        )
        assert swapped["substituted_from_product_id"] == bread_flour["id"], (
            f"Expected the bread flour recorded as the origin, got "
            f"{swapped['substituted_from_product_id']}"
        )
        found, meta = validate_paginated(
            api_client.list_order_lines(
                PC, params={"substituted_from_product_id": bread_flour["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            f"Expected exactly one line to carry that origin, got {meta['total_count']}"
        )
        assert found[0]["id"] == line["id"], (
            f"Expected the swapped line, got {found[0]['id']}"
        )
        order_after = read_order(order["id"])
        assert order_after["subtotal_cents"] == 40000, (
            f"Expected subtotal 40000, got {order_after['subtotal_cents']}"
        )
        assert order_after["total_cents"] == 41000, (
            f"Expected total 41000, got {order_after['total_cents']}"
        )
