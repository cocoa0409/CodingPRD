"""Corner queue (breadth): role-based access control and optimistic-concurrency
control on work-order release.
"""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error,
    build_user_headers, TEST_USERS,
    setup_released_routing_for_fg, setup_planned_work_order_released_routing,
    create_product, create_machine, create_draft_routing_with_ops,
)
from test_helpers import api_client as _ac

ENG = TEST_USERS["manufacturing_engineer_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
OPERATOR = TEST_USERS["machine_operator_headers"]
ADMIN = TEST_USERS["plant_admin_headers"]


class TestRbac:
    def test_planner_cannot_create_product(self, api):
        """PRD §2.1: "When the headers are well-formed but the role is not permitted
        to perform the requested operation, the request is rejected with
        ERR_FORBIDDEN."
        PRD §2.1: "A ManufacturingEngineer owns master data — products, BOM lines,
        routings, operations, and machine registration — and may also recompute
        machine OEE."

        Design: Corner/rbac/planner_cannot_create_product
        """
        resp = api.create_product(
            {"sku": "FGRB", "name": "FG", "product_type": "FINISHED_GOOD"}, PLANNER)
        validate_error(resp, "ERR_FORBIDDEN", 403)

    def test_operator_cannot_release_work_order(self, api):
        """PRD §2.1: "When the headers are well-formed but the role is not permitted
        to perform the requested operation, the request is rejected with
        ERR_FORBIDDEN."
        PRD §2.1: "A ProductionPlanner owns the work-order lifecycle: creating,
        releasing, completing, closing, and cancelling work orders."

        Design: Corner/rbac/operator_cannot_release_work_order
        """
        ctx = setup_planned_work_order_released_routing(order_qty=1)
        wo = ctx["work_order"]
        resp = api.release_work_order(
            wo["id"], {"expected_work_order_version": wo["version"]}, OPERATOR)
        validate_error(resp, "ERR_FORBIDDEN", 403)

    def test_missing_role_header_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying an X-User-Role that
        is not one of the recognized roles, is rejected with ERR_UNAUTHENTICATED."

        Design: Corner/rbac/missing_auth_headers_unauthenticated
        """
        bad_headers = {"X-User-ID": "anon", "X-User-Role": "Nobody",
                       "Content-Type": "application/json"}
        resp = api.list_work_orders(bad_headers)
        validate_error(resp, "ERR_UNAUTHENTICATED", 401)

    def test_plant_admin_override_can_create_product(self, api):
        """PRD §2.1: "A PlantAdmin is an operational override authorized to perform
        any operation across every module as a superset of all other roles."

        Design: Corner/rbac/plantadmin_override_can_create_product
        """
        data = validate_success(api.create_product(
            {"sku": "FGADM", "name": "FG", "product_type": "FINISHED_GOOD"}, ADMIN), 201)
        assert data["sku"] == "FGADM"


class TestOptimisticConcurrency:
    def test_release_with_correct_version_succeeds_and_bumps(self, api):
        """PRD §2.4: "the version field is an integer that starts at 1 on creation and
        increments by exactly one on every mutation of the resource."
        PRD §3.4: "The work order's version is then incremented."

        Design: Corner/cross_cutting_complexity_layers/occ_release_correct_version_succeeds_and_bumps
        """
        ctx = setup_planned_work_order_released_routing(order_qty=1)
        wo = ctx["work_order"]
        released = validate_success(api.release_work_order(
            wo["id"], {"expected_work_order_version": wo["version"]}, PLANNER))
        assert released["status"] == "RELEASED"
        assert released["version"] == 2, released["version"]

    def test_release_with_stale_version_rejected(self, api):
        """PRD §2.8: "If they do not match — because another writer advanced the work
        order's version after the client read it — the release is rejected with
        ERR_STALE_VERSION (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_release_stale_version_rejected
        """
        ctx = setup_planned_work_order_released_routing(order_qty=1)
        wo = ctx["work_order"]
        resp = api.release_work_order(
            wo["id"], {"expected_work_order_version": wo["version"] - 1}, PLANNER)
        validate_error(resp, "ERR_STALE_VERSION", 412)

    def test_routing_version_increments_on_release(self, api):
        """PRD §2.4: "the version field is an integer that starts at 1 on creation and
        increments by exactly one on every mutation of the resource."
        PRD §3.2: "A ManufacturingEngineer releases a DRAFT routing, advancing its
        status from DRAFT to RELEASED; this is permitted only when the routing has at
        least one operation (operation_count of 1 or more) and every operation under
        it references an existing machine, and it increments the routing's version."

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_mutation
        """
        fg = create_product(product_type="FINISHED_GOOD")
        machine = create_machine()
        routing, _ = create_draft_routing_with_ops(
            fg["id"], machine["id"], ops=[{"sequence_no": 10, "ideal_cycle_time_secs": 100}])
        pre = validate_success(api.get_routing(routing["id"], ENG))
        released = validate_success(api.release_routing(routing["id"], ENG))
        assert released["status"] == "RELEASED"
        assert released["version"] == pre["version"] + 1
