"""Customer account creation, defaults, and lookup (PRD §2.1, §2.8, §3.1)."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    assert_customer, create_customer_payload, set_clock, create_customer,
    TEST_USERS, NON_EXISTENT_UUID, make_customer_headers,
)

CS = TEST_USERS["customer_service_headers"]
OM = TEST_USERS["operations_manager_headers"]


class TestCustomerCreation:
    def test_customer_creation_required_fields_and_defaults(self, api):
        """PRD §3.1: "A new customer starts with `credit_balance_cents` at 0,
        `outstanding_refund_cents` at 0, `lifetime_cord_equivalent_delivered`
        at 0, `loyalty_tier` of `STANDARD`, and `account_status` of `ACTIVE`."

        Design: Corner/entities/customer_creation_required_fields_and_defaults
        """
        set_clock()
        res = api.create_customer(create_customer_payload(
            full_name="New Cust", email="new@x.com", phone="9",
            street_address="9 Oak", postal_code="01010"), CS)
        customer = validate_success(res, 201)
        assert_customer(customer)
        assert customer["loyalty_tier"] == "STANDARD"
        assert customer["account_status"] == "ACTIVE"
        assert customer["credit_balance_cents"] == 0
        assert customer["outstanding_refund_cents"] == 0
        assert customer["lifetime_cord_equivalent_delivered"] == 0

    def test_customer_creation_missing_required_field_returns_validation(self, api):
        """PRD §2.8: "Field-level problems that no rule above covers — a missing
        required field or a malformed value — are rejected with the generic
        `ERR_VALIDATION` (HTTP 422)."

        Design: Corner/entities/customer_creation_missing_required_field_returns_validation
        """
        set_clock()
        payload = {
            "full_name": "NoEmail",
            "phone": "1",
            "street_address": "1 St",
            "postal_code": "01010",
        }
        res = api.create_customer(payload, CS)
        validate_error(res, "ERR_VALIDATION", expected_status=422)

    def test_customer_get_not_found_returns_404(self, api):
        """PRD §2.8: "Path existence: every path-templated resource id exists,
        validated left to right (customer, then subscription, route, window,
        order, line, invoice, payment-event as they appear) — otherwise
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/customer_get_not_found_returns_404
        """
        set_clock()
        res = api.get_customer(NON_EXISTENT_UUID, CS)
        validate_error(res, "ERR_NOT_FOUND", expected_status=404)

    def test_customer_cannot_read_other_customers_record(self, api):
        """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id`
        of the acting `Customer`; ownership checks on any resource that
        references a `Customer` compare the resource's `customer_id` foreign-key
        field to `X-User-ID`. A customer therefore sees and mutates only their
        own record and their own orders."

        Design: Corner/rbac/customer_cannot_read_other_customers_record
        """
        set_clock()
        cust_a = create_customer(postal_code="01010")
        cust_b = create_customer(postal_code="02020")
        res = api.get_customer(cust_b["id"], make_customer_headers(cust_a["id"]))
        validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)
