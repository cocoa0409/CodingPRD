"""Role-based access control and CustomerBuyer ownership (PRD §2.1, §4)."""
from test_helpers import (
    ADMIN,
    SALES,
    SUPPLIER,
    ApiErrorId,
    create_customer,
    create_line,
    create_order,
    create_part,
    get_success_data,
    make_customer_buyer_headers,
    order_line_spec,
    propose_alternate,
    setup_catalog,
    validate_error,
    validate_success,
)


class TestExclusiveOperations:
    def test_customer_buyer_cannot_create_part(self, api):
        """PRD §2.1: "Access to specific operations is restricted by role; an
        attempt to perform an action outside of a user's designated role is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4 restricts catalog creation to DistributorAdmin: "Create a
        catalog part on a line".

        Design: Corner/rbac/customer_buyer_cannot_create_part
        """
        line = create_line(line_code="LIN-RB1")
        customer = create_customer(name="Cust RB1")
        resp = api.create_part(
            {"manufacturer_line_id": line["id"], "part_number": "PRB-1",
             "msl_level": 3, "floor_life_hours": 100, "date_code_limit_months": 24,
             "standard_cost_cents": 1000, "book_price_cents": 1500},
            make_customer_buyer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_supplier_admin_cannot_acknowledge_order(self, api):
        """PRD §2.1: "Access to specific operations is restricted by role; an
        attempt to perform an action outside of a user's designated role is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4 restricts acknowledgement to SalesRep: "Acknowledge a
        `SUBMITTED` order; snapshots prices and cancellation terms".

        Design: Corner/rbac/supplier_admin_cannot_acknowledge_order
        """
        line, part = setup_catalog(line_code="LIN-RB2")
        customer = create_customer(name="Cust RB2")
        order = create_order(customer["id"],
                             [order_line_spec(part["id"], 5, "2026-10-01")])

        resp = api.acknowledge_order(order["id"], SUPPLIER)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert get_success_data(api.get_order(order["id"], ADMIN))["status"] == "SUBMITTED"


class TestCustomerBuyerOwnership:
    def test_customer_buyer_other_customer_order_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `CustomerBuyer`, `X-User-ID` is the
        `id` of the acting `Customer`; ownership checks on any resource that
        references a `Customer` compare the resource's `customer_id`
        foreign-key field to `X-User-ID`, and a mismatch is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/customer_buyer_other_customer_order_forbidden
        """
        line, part = setup_catalog(line_code="LIN-RB4")
        cust_a = create_customer(name="Cust A-RB4")
        cust_b = create_customer(name="Cust B-RB4")
        order = create_order(cust_b["id"],
                             [order_line_spec(part["id"], 5, "2026-10-01")])
        get_success_data(api.acknowledge_order(order["id"], SALES))

        resp = api.cancel_order(order["id"], make_customer_buyer_headers(cust_a["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        order_after = get_success_data(api.get_order(order["id"], ADMIN))
        assert order_after["status"] == "ACKNOWLEDGED"

    def test_alternate_decision_exclusive_to_owning_customer(self, api):
        """PRD §3.8: "The decision belongs to the customer side alone: a
        `CustomerBuyer` acting for that customer approves or rejects from
        `PROPOSED`, and may later revoke an `APPROVED` approval to `REVOKED`."
        PRD §4 assigns the decision to CustomerBuyer: "Customer decision:
        approve or reject from `PROPOSED`, revoke from `APPROVED`".

        Design: Corner/rbac/alternate_decision_exclusive_to_owning_customer
        """
        line = create_line(line_code="LIN-RB5")
        primary = create_part(line["id"], part_number="PRB-5A")
        alternate = create_part(line["id"], part_number="PRB-5B",
                                standard_cost_cents=900, book_price_cents=1400)
        customer = create_customer(name="Cust RB5")
        approval = propose_alternate(customer["id"], primary["id"], alternate["id"])
        assert approval["status"] == "PROPOSED"

        resp = api.decide_alternate_approval(approval["id"], {"decision": "APPROVE"},
                                             SALES)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        decided = validate_success(
            api.decide_alternate_approval(
                approval["id"], {"decision": "APPROVE"},
                make_customer_buyer_headers(customer["id"])),
            200)
        assert decided["status"] == "APPROVED"
