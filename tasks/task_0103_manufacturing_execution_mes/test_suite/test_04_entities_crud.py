"""Corner queue (breadth): entity creation, defaults, system/computed fields,
required-field and type validation, not-found, FK integrity, immutability.
"""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID, TEST_USERS,
    create_product, create_machine,
    create_draft_routing_with_ops,
    assert_product, assert_routing, assert_traveler_signoff,
    setup_started_single_op_wo, setup_released_work_order,
    setup_released_wo_with_demand_and_lot,
)
from test_helpers import api_client as _ac

ENG = TEST_USERS["manufacturing_engineer_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
OPERATOR = TEST_USERS["machine_operator_headers"]
INSPECTOR = TEST_USERS["quality_inspector_headers"]


class TestProductCreation:
    def test_create_product_returns_201_with_system_fields(self, api):
        """PRD §2.4: "The id is a server-minted UUID with no type prefix."
        PRD §2.4: "the version field is an integer that starts at 1 on creation and
        increments by exactly one on every mutation of the resource."

        Design: Corner/entities/create_product_returns_201_with_system_fields
        """
        resp = api.create_product(
            {"sku": "FGE1", "name": "Widget", "product_type": "FINISHED_GOOD"}, ENG)
        data = validate_success(resp, 201)
        assert_product(data)
        assert data["version"] == 1
        assert data["sku"] == "FGE1"

    def test_create_product_missing_sku_returns_invalid_request(self, api):
        """PRD §2.9: "The lowest-precedence check is the generic well-formedness gate:
        required fields present and well-typed and enum members valid, failing which
        the request is rejected with ERR_INVALID_REQUEST (400)."

        Design: Corner/entities/create_product_missing_sku_returns_invalid_request
        """
        resp = api.create_product({"name": "NoSku", "product_type": "FINISHED_GOOD"}, ENG)
        validate_error(resp, "ERR_INVALID_REQUEST", 400)

    def test_create_product_invalid_enum_product_type(self, api):
        """PRD §3.1: "a product_type that classifies it in the bill-of-material tree
        as one of FINISHED_GOOD, SUBASSEMBLY, or RAW_MATERIAL."
        PRD §2.9: "required fields present and well-typed and enum members valid,
        failing which the request is rejected with ERR_INVALID_REQUEST (400)."

        Design: Corner/entities/create_product_invalid_enum_product_type_returns_invalid_request
        """
        resp = api.create_product({"sku": "BAD", "name": "Bad", "product_type": "GADGET"}, ENG)
        validate_error(resp, "ERR_INVALID_REQUEST", 400)

    def test_get_product_nonexistent_returns_not_found(self, api):
        """PRD §2.6: "The same left-to-right existence rule applies to every
        foreign-key identifier supplied in a request body: any referenced resource
        that does not exist yields ERR_NOT_FOUND."

        Design: Corner/entities/get_product_nonexistent_returns_not_found
        """
        resp = api.get_product(NON_EXISTENT_UUID, ENG)
        validate_error(resp, "ERR_NOT_FOUND", 404)

    def test_product_defaults_lot_controlled_false_unit_cost_zero(self, api):
        """PRD §3.1: "Each product also records a unit_cost_cents, an integer
        standard unit cost that must be zero or greater and defaults to 0".
        PRD §3.1: "A lot_controlled boolean, defaulting to false, marks products
        whose issues must reference a specific lot so that genealogy can be traced."

        Design: Corner/entities/product_defaults_lot_controlled_false_unit_cost_zero
        """
        data = validate_success(api.create_product(
            {"sku": "FGDEF", "name": "Def", "product_type": "FINISHED_GOOD"}, ENG), 201)
        assert data["lot_controlled"] is False
        assert data["unit_cost_cents"] == 0


class TestRoutingSystemAndComputedFields:
    def test_routing_initial_status_draft_operation_count_zero(self, api):
        """PRD §3.2: "A new routing begins in DRAFT status and exposes an
        operation_count that starts at 0 and is recomputed whenever an operation is
        attached."

        Design: Corner/entities/routing_initial_status_draft_operation_count_zero
        """
        fg = create_product(product_type="FINISHED_GOOD")
        data = validate_success(api.create_routing(
            {"product_id": fg["id"], "routing_code": "RT-1"}, ENG), 201)
        assert data["status"] == "DRAFT"
        assert data["operation_count"] == 0

    def test_operation_count_recomputed_on_operation_add(self, api):
        """PRD §3.2: "A new routing begins in DRAFT status and exposes an
        operation_count that starts at 0 and is recomputed whenever an operation is
        attached."
        PRD §3.2: "Attaching an operation increments the routing's operation_count."

        Design: Corner/entities/operation_count_recomputed_on_operation_add
        """
        fg = create_product(product_type="FINISHED_GOOD")
        machine = create_machine()
        routing, _ = create_draft_routing_with_ops(
            fg["id"], machine["id"], ops=[{"sequence_no": 10, "ideal_cycle_time_secs": 100}])
        get_success_data(api.create_operation(
            routing["id"], {"machine_id": machine["id"], "sequence_no": 20,
                            "ideal_cycle_time_secs": 50}, ENG))
        updated = validate_success(api.get_routing(routing["id"], ENG))
        assert updated["operation_count"] == 2


class TestTravelerSignoffImmutability:
    def test_signoff_has_no_version_field(self, api):
        """PRD §2.4: "A TravelerSignoff is an append-only record: once written it is
        never modified. It therefore carries only id and created_at — it has no
        updated_at and no version field."

        Design: Corner/entities/travelersignoff_immutable_no_version_field
        """
        ctx = setup_released_work_order(order_qty=1)
        woop_id = ctx["woops"][0]["id"]
        resp = api.create_signoff(woop_id, {"result": "PASS"}, INSPECTOR)
        data = validate_success(resp, 201)
        assert_traveler_signoff(data)
        assert data["result"] == "PASS"
        assert "version" not in data, "append-only sign-off must not carry version"


class TestBomLineSelfLoop:
    def test_bomline_self_loop_rejected(self, api):
        """PRD §3.1: "A bill line may never point a product at itself: if
        parent_product_id equals component_product_id, or if the new edge would
        introduce a cycle anywhere in the bill-of-material graph, the line is
        rejected with ERR_BOM_CYCLE."

        Design: Corner/entities/bomline_self_loop_rejected
        """
        p = create_product(product_type="SUBASSEMBLY", unit_cost_cents=10)
        resp = api.create_bom_line(
            {"parent_product_id": p["id"], "component_product_id": p["id"],
             "quantity_per": 1}, ENG)
        validate_error(resp, "ERR_BOM_CYCLE", 409)


class TestForeignKeyIntegrity:
    def test_routing_with_nonexistent_product_not_found(self, api):
        """PRD §2.6: "The same left-to-right existence rule applies to every
        foreign-key identifier supplied in a request body: any referenced resource
        that does not exist yields ERR_NOT_FOUND."

        Design: Corner/entities/routing_with_nonexistent_product_not_found
        """
        resp = api.create_routing(
            {"product_id": NON_EXISTENT_UUID, "routing_code": "RT-NF"}, ENG)
        validate_error(resp, "ERR_NOT_FOUND", 404)

    def test_lot_issue_reverse_reachable_by_lot_filter(self, api):
        """PRD §3.8: "Lot issues can be listed and filtered by component_demand_id,
        lot_id, or work_order_operation_id."

        Design: Corner/entities/lot_issue_reverse_reachable_by_filter
        """
        ctx = setup_released_wo_with_demand_and_lot(
            quantity_per=1, scrap_factor_pct=0, raw_unit_cost=100, received_qty=5, order_qty=1)
        li = get_success_data(api.create_lot_issue({
            "component_demand_id": ctx["demand"]["id"], "lot_id": ctx["lot"]["id"],
            "work_order_operation_id": ctx["woop"]["id"], "issued_qty": 1}, OPERATOR))
        resp = api.list_lot_issues(OPERATOR, params={"lot_id": ctx["lot"]["id"]})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1, meta
        assert data[0]["lot_id"] == ctx["lot"]["id"]
        assert data[0]["id"] == li["id"]
