"""Contract price matrix: rule scoping, activation overlap, OCC, line pricing."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_order_line,
    assert_price_matrix_rule,
    create_active_price_rule,
    create_branch,
    create_customer,
    create_item,
    create_price_rule,
    create_price_rule_payload,
    get_order_lines,
    place_order,
    restock,
    validate_error,
    validate_success,
)


def _silver_two_item_scenario(api, admin_headers):
    """SILVER customer; item1 list 1000 with item-level FIXED 850; item2 list 500
    with only the SILVER x STOCKED class DISCOUNT 10% rule; both rules ACTIVE over
    [2026-01-01, 2027-01-01); branch stocked 60 of item1 and 12 of item2."""
    customer = create_customer(
        account_number="SLV-1", price_tier="SILVER", credit_limit_cents=10000000,
        primary_ship_to_state="OH",
    )
    item1 = create_item(sku="P-100", list_price_cents=1000)
    item2 = create_item(sku="P-200", list_price_cents=500)
    create_active_price_rule(
        customer_tier="SILVER", item_class="STOCKED", rule_type="DISCOUNT_PCT",
        discount_pct=10, effective_from="2026-01-01", effective_to="2027-01-01",
    )
    create_active_price_rule(
        customer_tier="SILVER", item_id=item1["id"], rule_type="FIXED_PRICE",
        contract_unit_price_cents=850, effective_from="2026-01-01",
        effective_to="2027-01-01",
    )
    branch = create_branch(location_code="BR-3")
    restock(branch["id"], item1["id"], 60)
    restock(branch["id"], item2["id"], 12)
    order = place_order(
        customer["id"], branch["id"],
        [
            {"item_id": item1["id"], "qty": 60},
            {"item_id": item2["id"], "qty": 12},
        ],
        fulfillment_method="STANDARD",
    )
    return order


class TestQuantityTieredContractPriceResolution:
    def test_item_rule_beats_class_rule_with_quantity_tiers(self, api, admin_headers):
        """PRD §3.2: "An item-specific rule always beats a class-level rule"
        PRD §3.2: "A whole-quantity tier adjustment then applies to the base:
        quantities of at least 50 units earn five percent off, quantities of at
        least 10 but fewer than 50 earn three percent off, and smaller quantities
        earn no adjustment — the discount applies to the entire quantity as an
        average rate, never marginally, and the adjusted unit price is rounded half
        up as the second rounding step."

        Design: Difficulty/combinatorial_formula/qty_tiered_contract_price_resolution
        """
        order = _silver_two_item_scenario(api, admin_headers)
        lines = get_order_lines(order["id"])

        line1, line2 = lines[0], lines[1]
        assert_order_line(line1)
        assert_order_line(line2)
        # 850 fixed * 0.95 = 807.5 -> round_half_up -> 808
        assert line1["unit_price_cents"] == 808
        assert line1["line_total_cents"] == 60 * 808
        # 500 * 0.9 = 450 (step 1); 450 * 0.97 = 436.5 -> round_half_up -> 437
        assert line2["unit_price_cents"] == 437
        assert line2["line_total_cents"] == 12 * 437

    def test_order_totals_reach_free_freight_threshold(self, api, admin_headers):
        """PRD §3.5: "The order's `subtotal_cents` is the sum of its line totals,
        computed before freight enters the picture. Freight follows a pinned order:
        `WILL_CALL` orders never carry base freight; for delivery methods, a
        `subtotal_cents` reaching 25,000 cents waives the base freight entirely"

        Design: Difficulty/combinatorial_formula/qty_tiered_contract_price_resolution
        """
        order = _silver_two_item_scenario(api, admin_headers)
        assert order["subtotal_cents"] == 48480 + 5244
        assert order["freight_cents"] == 0
        assert order["total_cents"] == 53724


class TestPriceRuleWindowOverlap:
    def _setup_active_rule1(self, api, admin_headers):
        item = create_item(sku="PR-1", list_price_cents=1000)
        rule1 = create_active_price_rule(
            customer_tier="GOLD", item_id=item["id"], rule_type="FIXED_PRICE",
            contract_unit_price_cents=900, effective_from="2026-01-01",
            effective_to="2026-06-01",
        )
        return item, rule1

    def test_adjacent_activation_allowed_under_half_open_windows(
        self, api, admin_headers
    ):
        """PRD §3.2: "Because both windows are half-open, a rule whose
        `effective_from` equals an active rule's `effective_to` touches without
        overlapping and is allowed."

        Design: Difficulty/resource_temporal_overlap/price_rule_half_open_window_adjacency
        """
        item, rule1 = self._setup_active_rule1(api, admin_headers)
        assert rule1["status"] == "ACTIVE"

        rule2 = create_price_rule(
            customer_tier="GOLD", item_id=item["id"], rule_type="FIXED_PRICE",
            contract_unit_price_cents=880, effective_from="2026-06-01",
            effective_to="2027-01-01",
        )
        activated = validate_success(
            api.activate_price_rule(rule2["id"], admin_headers), 200
        )
        assert_price_matrix_rule(activated)
        assert activated["status"] == "ACTIVE"

    def test_overlapping_activation_rejected(self, api, admin_headers):
        """PRD §3.2: "if another `ACTIVE` rule with the same scope key — the same
        tier-and-item pair, or the same tier-and-class pair — has a window that
        shares any day with the candidate's window, activation is rejected with
        `ERR_PRICE_RULE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/price_rule_half_open_window_adjacency
        """
        item, _rule1 = self._setup_active_rule1(api, admin_headers)
        rule3 = create_price_rule(
            customer_tier="GOLD", item_id=item["id"], rule_type="FIXED_PRICE",
            contract_unit_price_cents=870, effective_from="2026-05-15",
            effective_to="2026-07-01",
        )
        res = api.activate_price_rule(rule3["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_PRICE_RULE_WINDOW_OVERLAP)


class TestPriceRuleShapeAndOcc:
    def test_price_rule_scope_exactly_one_rejected(self, api, admin_headers):
        """PRD §3.2: "A rule names the `customer_tier` it prices for and a scope:
        exactly one of `item_id` (an item-specific rule) or `item_class` (a
        class-level rule over `STOCKED`, `SPECIAL_ORDER`, or `NON_RETURNABLE`)
        must be set — supplying both or neither is a shape violation rejected with
        `ERR_VALIDATION`."

        Design: Corner/entities/price_rule_scope_exactly_one_rejected
        """
        item = create_item(sku="SC-1", list_price_cents=100)
        both = api.create_price_rule(
            create_price_rule_payload(
                customer_tier="GOLD", item_id=item["id"], item_class="STOCKED",
                rule_type="FIXED_PRICE", contract_unit_price_cents=90,
            ),
            admin_headers,
        )
        validate_error(both, ApiErrorId.ERR_VALIDATION)

        neither_payload = create_price_rule_payload(
            customer_tier="GOLD", rule_type="FIXED_PRICE",
            contract_unit_price_cents=90,
        )
        neither_payload.pop("item_class", None)
        neither = api.create_price_rule(neither_payload, admin_headers)
        validate_error(neither, ApiErrorId.ERR_VALIDATION)

    def test_price_rule_put_bumps_version(self, api, admin_headers):
        """PRD §2.7: "Updating a price-matrix rule — `PUT /mro/price-rules/{id}` —
        likewise requires a non-optional `expected_price_rule_version` matching the
        rule's current `version` ... A successful update advances the rule's
        `version` by one."

        Design: Corner/state_machines/price_rule_put_bumps_version
        """
        item = create_item(sku="PV-1", list_price_cents=1000)
        rule = create_price_rule(
            customer_tier="GOLD", item_id=item["id"], rule_type="FIXED_PRICE",
            contract_unit_price_cents=900,
        )
        assert rule["version"] == 1
        updated = validate_success(
            api.update_price_rule(
                rule["id"],
                {
                    "contract_unit_price_cents": 950,
                    "expected_price_rule_version": rule["version"],
                },
                admin_headers,
            ),
            200,
        )
        assert updated["contract_unit_price_cents"] == 950
        assert updated["version"] == 2

    def test_occ_price_rule_stale_version_returns_412(self, api, admin_headers):
        """PRD §2.7: "Updating a price-matrix rule — `PUT /mro/price-rules/{id}` —
        likewise requires a non-optional `expected_price_rule_version` matching the
        rule's current `version`, with the same `ERR_STALE_VERSION` (HTTP 412)
        rejection on mismatch. A successful update advances the rule's `version` by
        one."

        Design: Corner/cross_cutting_layers/occ_price_rule_stale_version_returns_412
        """
        item = create_item(sku="OCC-2", list_price_cents=1000)
        rule = create_price_rule(
            customer_tier="SILVER", item_id=item["id"], rule_type="FIXED_PRICE",
            contract_unit_price_cents=900,
        )
        v1 = rule["version"]
        updated = validate_success(
            api.update_price_rule(
                rule["id"],
                {"contract_unit_price_cents": 890, "expected_price_rule_version": v1},
                admin_headers,
            ),
            200,
        )
        assert updated["version"] == 2

        stale = api.update_price_rule(
            rule["id"],
            {"contract_unit_price_cents": 880, "expected_price_rule_version": v1},
            admin_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


class TestQuantityTierBoundary:
    def test_qty_tier_boundary_nine_vs_ten(self, api, admin_headers):
        """PRD §3.2: "quantities of at least 50 units earn five percent off,
        quantities of at least 10 but fewer than 50 earn three percent off, and
        smaller quantities earn no adjustment"
        PRD §3.2: "with no candidate at all, the base is simply `list_price_cents`"

        Design: Corner/calculations/qty_tier_boundary_nine_vs_ten
        """
        customer = create_customer(account_number="QT-1", credit_limit_cents=1000000)
        item = create_item(sku="QT-1", list_price_cents=1000)
        branch = create_branch(location_code="BR-QT")
        restock(branch["id"], item["id"], 19)

        order9 = place_order(
            customer["id"], branch["id"], [{"item_id": item["id"], "qty": 9}]
        )
        order10 = place_order(
            customer["id"], branch["id"], [{"item_id": item["id"], "qty": 10}]
        )
        lines9 = get_order_lines(order9["id"])
        lines10 = get_order_lines(order10["id"])

        assert lines9[0]["unit_price_cents"] == 1000
        assert lines9[0]["line_total_cents"] == 9000
        # 10 >= 10: round_half_up(1000 * 0.97) = 970
        assert lines10[0]["unit_price_cents"] == 970
        assert lines10[0]["line_total_cents"] == 9700


class TestOrderLineSystemFields:
    def test_order_line_system_fields_server_minted(self, api, admin_headers):
        """PRD §3.5: "Pricing is snapshotted at creation and never revisited. Each
        resulting `OrderLine` records its `order_id`, `item_id`, and `qty`, and
        carries the resolved `unit_price_cents` from §3.2 with `line_total_cents`
        as their product."
        PRD §3.5: "New orders start with `status` `SUBMITTED` and
        `fulfillment_status` `UNALLOCATED`, with `promise_date`, `confirmed_at`,
        `fulfilled_at`, and `completed_at` all unset, `sla_breach` false, and every
        allocation quantity on every line at zero with `fulfillment_source`
        `UNRESOLVED`."

        Design: Corner/entities/order_line_system_fields_server_minted
        """
        customer = create_customer(account_number="SF-1", credit_limit_cents=100000)
        item = create_item(sku="SF-1", list_price_cents=1234)
        branch = create_branch(location_code="BR-SF")
        restock(branch["id"], item["id"], 4)
        order = place_order(
            customer["id"], branch["id"], [{"item_id": item["id"], "qty": 4}]
        )

        lines = get_order_lines(order["id"])
        assert len(lines) == 1
        line = lines[0]
        assert_order_line(line)
        assert line["version"] == 1
        # No price rule -> list fallback; qty 4 < 10 -> no quantity tier.
        assert line["unit_price_cents"] == 1234
        assert line["line_total_cents"] == 4936
        assert line["fulfillment_source"] == "UNRESOLVED"
