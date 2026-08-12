"""Role-based access control and ownership scoping (PRD §2.1, §4)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    make_customer_headers, make_operator_headers, make_quality_tech_headers,
    make_customer, make_employee, make_ingredient, make_line,
    create_ingredient_payload, create_flush_record_payload,
    create_weighment_payload, setup_active_grow_formula, make_order,
)

MM = TEST_USERS["mill_manager_headers"]
NUT = TEST_USERS["nutritionist_headers"]


class TestRoleAdmission:
    def test_customer_cannot_create_ingredient(self, api):
        """PRD §2.1: "Each endpoint declares the roles admitted to it; a caller whose role is not admitted is rejected with `ERR_FORBIDDEN`."
        (PRD §4 endpoint catalogue admits only MillManager to POST /api/ingredients.)

        Design: Corner/rbac/customer_cannot_create_ingredient
        """
        customer = make_customer("Acme Farms", 1000000)
        resp = api.create_ingredient(
            create_ingredient_payload("CORN"),
            make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_operator_cannot_enter_sample_result(self, api):
        """PRD §2.11: "Authorization — the role is admitted to the endpoint and, for the floor roles, the employee's capability covers the role (`ERR_FORBIDDEN`)."
        (PRD §4 endpoint catalogue admits only QualityTech to POST /api/samples and POST /api/samples/{id}/result.)

        Design: Corner/rbac/operator_cannot_enter_sample_result
        """
        op = make_employee("Olly Operator", "OPERATOR")
        # The authorization layer precedes existence, so even a placeholder
        # batch id draws 403, not 404.
        resp = api.create_sample(
            {"batch_id": str(NON_EXISTENT_UUID), "sample_type": "COMPOSITE"},
            make_operator_headers(op["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_qualitytech_cannot_record_weighment(self, api):
        """PRD §2.11: "Authorization — the role is admitted to the endpoint and, for the floor roles, the employee's capability covers the role (`ERR_FORBIDDEN`)."
        (PRD §4 endpoint catalogue admits only Operator to POST /api/batches/{id}/weighments.)

        Design: Corner/rbac/qualitytech_cannot_record_weighment
        """
        qt = make_employee("Quinn Quality", "QUALITY_TECH")
        resp = api.record_weighment(
            str(NON_EXISTENT_UUID),
            create_weighment_payload(str(NON_EXISTENT_UUID),
                                     str(NON_EXISTENT_UUID), 1.0),
            make_quality_tech_headers(qt["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_nutritionist_cannot_start_batch(self, api):
        """PRD §2.1: "Each endpoint declares the roles admitted to it; a caller whose role is not admitted is rejected with `ERR_FORBIDDEN`."
        (PRD §4 endpoint catalogue admits only Operator to POST /api/batches/{id}/start.)

        Design: Corner/rbac/nutritionist_cannot_start_batch
        """
        resp = api.start_batch(str(NON_EXISTENT_UUID), NUT)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_capability_mismatch_employee_rejected(self, api):
        """PRD §2.1: "Acting as `Operator` requires an employee whose `capability` is `OPERATOR` or `DUAL`; acting as `QualityTech` requires `QUALITY_TECH` or `DUAL`. A capability mismatch — a quality-only technician attempting an operator action, for instance — is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/capability_mismatch_employee_rejected
        """
        qt = make_employee("Quinn Quality", "QUALITY_TECH")
        hulls = make_ingredient("HULLS")
        line = make_line("L1")
        # A QUALITY_TECH-only employee acting under the Operator role.
        resp = api.create_flush_record(
            create_flush_record_payload(line["id"], hulls["id"], 0.5),
            make_operator_headers(qt["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestCustomerOwnershipScoping:
    def test_customer_b_reading_foreign_order_returns_404(self, api):
        """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a customer compare the resource's customer reference against `X-User-ID`, and a `Customer` caller can only ever see their own orders and the trips belonging to those orders — an identifier belonging to another customer resolves exactly as if the resource did not exist, surfacing `ERR_NOT_FOUND`."
        PRD §3.5: "Order listings accept optional `customer_id`, `formula_id`, and `status` filters — and for a `Customer` caller the customer filter is forced to the caller."

        Design: Corner/rbac/customer_b_reading_foreign_order_returns_404
        """
        env = setup_active_grow_formula()
        customer_a = make_customer("Customer A", 1000000)
        customer_b = make_customer("Customer B", 1000000)
        order_a = make_order(customer_a, env["formula"]["id"], 10)

        # A foreign order id resolves exactly as if it did not exist.
        resp = api.get_order(order_a["id"], make_customer_headers(customer_b["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

        # B's order list contains only B's orders — none exist.
        data, meta = validate_paginated(
            api.list_orders(make_customer_headers(customer_b["id"])))
        assert meta["total_count"] == 0
        assert data == []
