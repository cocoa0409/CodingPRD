"""Catalog administration, pump-order composition, garment add-ons, bundle pricing."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_order_line,
    assert_pump_order,
    create_garment_item,
    create_member,
    create_part_item,
    create_policy,
    create_prescription,
    create_pump_item,
    get_success_data,
    make_member_headers,
    setup_pending_order,
    setup_pending_order_verified,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCatalogDefaults:
    def test_catalog_item_omitted_tier_defaults_to_standard(self, api, platform_admin_headers):
        """PRD §3.2: "Pumps additionally declare an `insurance_tier` of `STANDARD` (the
        default) or `UPGRADE`".

        Design: Corner/entities/catalog_item_defaults_applied
        """
        res = api.create_catalog_item(
            {"item_type": "PART", "name": "Membrane", "sku": "PART-MEMB",
             "unit_price_cents": 300},
            platform_admin_headers,
        )
        item = validate_success(res, 201)
        assert item["insurance_tier"] == "STANDARD"


class TestCatalogRbac:
    def test_warehouse_operator_cannot_create_catalog_item(self, api, warehouse_operator_headers):
        """PRD §3.2: "The catalog is administered exclusively by `PlatformAdmin`."
        PRD §2.1: "if the caller's role is not in the target endpoint's authorized role
        list, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/warehouse_operator_cannot_create_catalog_item
        """
        res = api.create_catalog_item(
            {"item_type": "PART", "name": "X", "sku": "X-1", "unit_price_cents": 100},
            warehouse_operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_member_cannot_create_catalog_item(self, api, care_coordinator_headers):
        """PRD §3.2: "The catalog is administered exclusively by `PlatformAdmin`."

        Design: Corner/rbac/member_cannot_create_catalog_item
        """
        member = create_member(full_name="Rb2 Mem", email="rb2@x.com")
        res = api.create_catalog_item(
            {"item_type": "PART", "name": "Y", "sku": "Y-1", "unit_price_cents": 100},
            make_member_headers(member["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


class TestOrderCreation:
    def test_order_creation_runs_pricing_and_ignores_injected_computed_values(
        self, api, care_coordinator_headers
    ):
        """PRD §3.2: "The server auto-creates the primary `OrderLine` — `line_type`
        `PUMP_PRIMARY`, `quantity` pinned to 1, `unit_price_cents` snapshotted from the
        catalog item — and runs pricing immediately."
        PRD §2.6: "Each order line's total is computed as its quantity multiplied by its
        snapshotted unit price, rounded half up to integer cents, and only then are line
        totals summed into the order subtotal."

        Design: Corner/entities/order_computed_fields_input_ignored
        """
        ctx = setup_pending_order()
        res = api.create_pump_order(
            {
                "member_id": ctx["member"]["id"],
                "policy_id": ctx["policy"]["id"],
                "prescription_id": ctx["rx"]["id"],
                "pump_item_id": ctx["pump"]["id"],
                "shipping_address": "4 D St",
                "provisional_patient_cents": 999999,
            },
            care_coordinator_headers,
        )
        order = validate_success(res, 201)
        assert_pump_order(order)
        # Pricing ran at creation from the 30000-cent primary line.
        assert order["merchandise_subtotal_cents"] == 30000
        assert order["order_total_cents"] == 30000
        # The injected computed value was not honored.
        assert order.get("provisional_patient_cents") != 999999

    def test_order_is_born_pending_qualification_and_unbilled(self, api):
        """PRD §3.2: "The order is born with `fulfillment_status` `PENDING_QUALIFICATION`
        and `billing_status` `UNBILLED`, two parallel dimensions that evolve independently,
        and with `replacement_count` at zero and `warranty_blocked` false."

        Design: Corner/entities/order_computed_fields_input_ignored
        """
        ctx = setup_pending_order()
        order = validate_success(
            api.get_pump_order(ctx["order"]["id"],
                               TEST_USERS["care_coordinator_headers"]), 200
        )
        assert order["fulfillment_status"] == "PENDING_QUALIFICATION"
        assert order["billing_status"] == "UNBILLED"
        assert order["replacement_count"] == 0
        assert order["warranty_blocked"] is False

    def test_order_with_unknown_policy_returns_not_found(self, api, care_coordinator_headers):
        """PRD §2.8: "path identifiers resolve left-to-right and every foreign-key
        reference in the body exists; failures surface the entity-specific not-found
        errors such as `ERR_MEMBER_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`".

        Design: Corner/entities/order_with_unknown_policy_not_found
        """
        member = create_member(full_name="Fk Mem", email="fk@x.com")
        rx = create_prescription(member["id"])
        pump = create_pump_item()
        res = api.create_pump_order(
            {
                "member_id": member["id"],
                "policy_id": NON_EXISTENT_UUID,
                "prescription_id": rx["id"],
                "pump_item_id": pump["id"],
                "shipping_address": "5 E St",
            },
            care_coordinator_headers,
        )
        validate_error(res, ApiErrorId.ERR_POLICY_NOT_FOUND, expected_status=404)


class TestOrderGuards:
    def test_pump_type_mismatch_rejected_at_creation(self, api, care_coordinator_headers):
        """PRD §3.2: "Creation already enforces three guards: the policy must be `ACTIVE`
        (`ERR_POLICY_NOT_ACTIVE`), the current date must fall inside the benefit period
        (`ERR_BENEFIT_PERIOD_ENDED`), and the prescription's `pump_type` must equal the
        pump item's `pump_type` (`ERR_PUMP_TYPE_MISMATCH`)."

        Design: Corner/validations/pump_type_mismatch_rejected
        """
        member = create_member(full_name="Mm Mem", email="mm@x.com")
        policy = create_policy(member["id"])
        rx = create_prescription(member["id"], pump_type="SINGLE_ELECTRIC")
        pump = create_pump_item()  # DOUBLE_ELECTRIC by default
        res = api.create_pump_order(
            {
                "member_id": member["id"],
                "policy_id": policy["id"],
                "prescription_id": rx["id"],
                "pump_item_id": pump["id"],
                "shipping_address": "5 V St",
            },
            care_coordinator_headers,
        )
        validate_error(res, ApiErrorId.ERR_PUMP_TYPE_MISMATCH, expected_status=422)

    def test_addon_line_must_reference_compression_garment(self, api, care_coordinator_headers):
        """PRD §3.2: "Add-on lines must reference `COMPRESSION_GARMENT` items only —
        anything else is rejected with `ERR_INVALID_ITEM_TYPE`".

        Design: Corner/validations/invalid_item_type_on_addon_line
        """
        ctx = setup_pending_order()
        part = create_part_item()
        res = api.add_order_line(
            ctx["order"]["id"], {"catalog_item_id": part["id"], "quantity": 1},
            care_coordinator_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_ITEM_TYPE, expected_status=422)

    def test_add_line_to_cancelled_order_rejected(self, api, care_coordinator_headers):
        """PRD §3.2: "While the order remains `PENDING_QUALIFICATION`, the patient or
        coordinator may add compression-garment add-on lines" — a CANCELLED order is no
        longer PENDING_QUALIFICATION, so the state precondition fails.
        PRD §2.8: "state-machine preconditions hold, including terminal-state lockdown
        (`ERR_INVALID_STATE`, 409, and the state-specific 409 errors".

        Design: Corner/state_machines/add_line_to_cancelled_order_rejected
        """
        ctx = setup_pending_order(policy_overrides={"garment_allowance_per_period": 2})
        garment = create_garment_item()
        validate_success(api.cancel_pump_order(ctx["order"]["id"], care_coordinator_headers), 200)

        res = api.add_order_line(
            ctx["order"]["id"], {"catalog_item_id": garment["id"], "quantity": 1},
            care_coordinator_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestBundlePricing:
    def test_per_line_rounding_then_sum(self, api, care_coordinator_headers):
        """PRD §2.6: "Each order line's total is computed as its quantity multiplied by
        its snapshotted unit price, rounded half up to integer cents, and only then are
        line totals summed into the order subtotal. Summing raw products and rounding once
        at the end is explicitly forbidden — the per-line-rounded sum is the only correct
        result."
        PRD §2.6: "Only if the subtotal is at least the threshold does each garment line
        receive a discount of 10 percent of its line total, rounded half up per discounted
        line."

        Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_bundle_discount
        """
        ctx = setup_pending_order(policy_overrides={"garment_allowance_per_period": 4})
        garment = create_garment_item(sku="GAR-C", name="GarmentC", unit_price_cents=4995)
        line1 = validate_success(
            api.add_order_line(ctx["order"]["id"],
                               {"catalog_item_id": garment["id"], "quantity": 1},
                               care_coordinator_headers), 201)
        line2 = validate_success(
            api.add_order_line(ctx["order"]["id"],
                               {"catalog_item_id": garment["id"], "quantity": 1},
                               care_coordinator_headers), 201)
        assert_order_line(line1)
        assert line1["line_total_cents"] == 4995
        # round_half_up(4995 * 0.10) == 500 per line; a sum-then-round scheme would give 999.
        assert line1["discount_cents"] == 500
        assert line2["discount_cents"] == 500

    def test_per_line_rounding_order_totals(self, api, care_coordinator_headers):
        """PRD §2.6: "The merchandise subtotal is computed first, in full, with no
        discounts." and "The order's `discount_total_cents` sums the per-line discounts,
        and `order_total_cents` is the subtotal minus the discount total." (§3.2)

        Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_bundle_discount
        """
        ctx = setup_pending_order(policy_overrides={"garment_allowance_per_period": 4})
        garment = create_garment_item(sku="GAR-C", name="GarmentC", unit_price_cents=4995)
        for _ in range(2):
            validate_success(
                api.add_order_line(ctx["order"]["id"],
                                   {"catalog_item_id": garment["id"], "quantity": 1},
                                   care_coordinator_headers), 201)
        order = validate_success(api.get_pump_order(ctx["order"]["id"],
                                                    care_coordinator_headers), 200)
        assert order["merchandise_subtotal_cents"] == 39990
        assert order["discount_total_cents"] == 1000
        assert order["order_total_cents"] == 38990

    def test_bundle_tier_keyed_on_pre_discount_subtotal_including_garments(
        self, api, care_coordinator_headers
    ):
        """PRD §2.6: "The tier test then compares that pre-discount subtotal (which itself
        includes the garment lines) against the bundle threshold of 20000 cents — that is,
        $200.00. Only if the subtotal is at least the threshold does each garment line
        receive a discount of 10 percent of its line total, rounded half up per discounted
        line. Because the threshold is keyed on a subtotal that contains the very lines
        being discounted, evaluating the discount before the tier test would be circular."

        Design: Difficulty/combinatorial_formula/bundle_discount_circular_evaluation_order
        """
        ctx = setup_pending_order(
            policy_overrides={"garment_allowance_per_period": 4},
            pump_overrides={"sku": "PUMP-CHEAP", "name": "CheapPump",
                            "unit_price_cents": 15000, "pump_type": "SINGLE_ELECTRIC",
                            "warranty_months": 6},
            rx_overrides={"pump_type": "SINGLE_ELECTRIC"},
        )
        garment = create_garment_item(sku="GAR-A", name="GarmentA", unit_price_cents=6000)
        line = validate_success(
            api.add_order_line(ctx["order"]["id"],
                               {"catalog_item_id": garment["id"], "quantity": 1},
                               care_coordinator_headers), 201)
        # 15000 (pump) + 6000 (garment) = 21000 >= 20000 only because the garment line
        # itself counts toward the tier test.
        assert line["discount_cents"] == 600

    def test_bundle_circular_order_totals(self, api, care_coordinator_headers):
        """PRD §3.2: "The order's `discount_total_cents` sums the per-line discounts, and
        `order_total_cents` is the subtotal minus the discount total."

        Design: Difficulty/combinatorial_formula/bundle_discount_circular_evaluation_order
        """
        ctx = setup_pending_order(
            policy_overrides={"garment_allowance_per_period": 4},
            pump_overrides={"sku": "PUMP-CHEAP", "name": "CheapPump",
                            "unit_price_cents": 15000, "pump_type": "SINGLE_ELECTRIC",
                            "warranty_months": 6},
            rx_overrides={"pump_type": "SINGLE_ELECTRIC"},
        )
        garment = create_garment_item(sku="GAR-A", name="GarmentA", unit_price_cents=6000)
        validate_success(
            api.add_order_line(ctx["order"]["id"],
                               {"catalog_item_id": garment["id"], "quantity": 1},
                               care_coordinator_headers), 201)
        order = validate_success(api.get_pump_order(ctx["order"]["id"],
                                                    care_coordinator_headers), 200)
        assert order["merchandise_subtotal_cents"] == 21000
        assert order["discount_total_cents"] == 600
        assert order["order_total_cents"] == 20400


class TestGarmentAllowanceBoundary:
    def test_addon_projecting_exactly_to_allowance_is_allowed(self, api, care_coordinator_headers):
        """PRD §3.2: "The garment budget is checked **projectively and inclusively**: the
        policy's current `garments_consumed_count` plus the quantities of all garment lines
        on this order including the new one must not exceed `garment_allowance_per_period`;
        projecting to exactly the allowance is allowed, and exceeding it is rejected with
        `ERR_GARMENT_ALLOWANCE_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/garment_allowance_exactly_at_cap
        """
        ctx = setup_pending_order(policy_overrides={"garment_allowance_per_period": 2})
        garment = create_garment_item()
        line = validate_success(
            api.add_order_line(ctx["order"]["id"],
                               {"catalog_item_id": garment["id"], "quantity": 2},
                               care_coordinator_headers), 201)
        assert line["quantity"] == 2
        assert line["line_total_cents"] == 12000

    def test_addon_one_over_allowance_rejected_and_nothing_consumed_yet(
        self, api, care_coordinator_headers
    ):
        """PRD §2.7: "Both budgets reject inclusively at their boundary: qualifying when
        the consumed count already equals the allowance is rejected, while a garment add-on
        that projects to exactly the allowance is permitted."
        PRD §2.7: "consumption happens at qualification and is released at cancellation."

        Design: Difficulty/boundary_precision_check/garment_allowance_exactly_at_cap
        """
        ctx = setup_pending_order(policy_overrides={"garment_allowance_per_period": 2})
        garment = create_garment_item()
        validate_success(
            api.add_order_line(ctx["order"]["id"],
                               {"catalog_item_id": garment["id"], "quantity": 2},
                               care_coordinator_headers), 201)
        res = api.add_order_line(ctx["order"]["id"],
                                 {"catalog_item_id": garment["id"], "quantity": 1},
                                 care_coordinator_headers)
        validate_error(res, ApiErrorId.ERR_GARMENT_ALLOWANCE_EXCEEDED, expected_status=422)

        policy = validate_success(api.get_policy(ctx["policy"]["id"],
                                                 care_coordinator_headers), 200)
        assert policy["garments_consumed_count"] == 0


class TestOrderLineReachability:
    def test_order_lines_listed_from_order(self, api, care_coordinator_headers):
        """PRD §3.2: "An order's lines can be listed at any time."

        Design: Corner/endpoints/order_lines_reverse_reachability
        """
        ctx = setup_pending_order(policy_overrides={"garment_allowance_per_period": 4})
        garment = create_garment_item()
        validate_success(
            api.add_order_line(ctx["order"]["id"],
                               {"catalog_item_id": garment["id"], "quantity": 1},
                               care_coordinator_headers), 201)
        data, meta = validate_paginated(
            api.list_order_lines(ctx["order"]["id"], care_coordinator_headers)
        )
        assert meta["total_count"] == 2
        by_type = {line["line_type"]: line for line in data}
        assert by_type["PUMP_PRIMARY"]["quantity"] == 1
        assert by_type["PUMP_PRIMARY"]["unit_price_cents"] == 30000
        assert by_type["ADDON_GARMENT"]["quantity"] == 1
        assert by_type["ADDON_GARMENT"]["unit_price_cents"] == 6000

    def test_order_lines_listed_from_catalog_item(self, api, care_coordinator_headers):
        """PRD §3.2: "Catalog listings filter by `item_type` or `covered_under_resupply`,
        and one can also list the order lines referencing a given catalog item."

        Design: Corner/endpoints/order_lines_reverse_reachability
        """
        ctx = setup_pending_order(policy_overrides={"garment_allowance_per_period": 4})
        garment = create_garment_item()
        validate_success(
            api.add_order_line(ctx["order"]["id"],
                               {"catalog_item_id": garment["id"], "quantity": 1},
                               care_coordinator_headers), 201)
        data, meta = validate_paginated(
            api.list_catalog_item_order_lines(garment["id"], care_coordinator_headers)
        )
        assert meta["total_count"] == 1
        assert data[0]["order_id"] == ctx["order"]["id"]
