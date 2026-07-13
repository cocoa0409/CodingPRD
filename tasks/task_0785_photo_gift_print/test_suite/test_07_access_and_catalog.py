"""Authentication, authorization, ownership, catalog CRUD, and validation precedence."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, assert_customer,
    NON_EXISTENT_UUID, TEST_USERS,
    setup_paid_order, create_customer, create_template, create_project,
    create_template_payload, create_project_payload,
    make_customer_headers,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
OPERATOR = TEST_USERS["production_operator_headers"]


class TestExistenceBeatsProductionState:
    """On POST /orders/{id}/shipments, an existence failure (404) pre-empts the DONE-job state rule."""

    def test_bogus_address_beats_incomplete_production(self, api):
        """PRD 2.8: "every resource referenced by the path or body must exist; path and body
        references are resolved left to right in their natural nesting order"
        PRD 2.8: "Domain-state and business rules described in Section 3 are evaluated after all of
        the above."

        Design: Difficulty/priority_pair_validation_conflict/shipment_existence_beats_production_state
        """
        ctx = setup_paid_order()  # ProductionJob is QUEUED (not DONE)
        res = api.create_shipment(
            ctx["order"]["id"],
            {"address_id": NON_EXISTENT_UUID, "carrier": "UPS", "method": "STANDARD"}, OPERATOR)
        validate_error(res, "ERR_ADDRESS_NOT_FOUND", 404)

    def test_valid_address_then_incomplete_production_error(self, api):
        """PRD 3.6: "Only once the order's production job has reached DONE may a shipment be created
        for that order; attempting it earlier is refused with ERR_PRODUCTION_NOT_COMPLETE."

        Design: Difficulty/priority_pair_validation_conflict/shipment_existence_beats_production_state
        """
        ctx = setup_paid_order()  # QUEUED job, but a real address exists
        res = api.create_shipment(
            ctx["order"]["id"],
            {"address_id": ctx["addr"]["id"], "carrier": "UPS", "method": "STANDARD"}, OPERATOR)
        # With existence satisfied, the Section-3 business rule is the one that fires.
        validate_error(res, "ERR_PRODUCTION_NOT_COMPLETE", 409)


class TestCustomerCrud:

    def test_create_customer_returns_zero_credit_and_version_one(self, api):
        """PRD 3.1: "Every new customer starts with a store_credit_cents balance of 0."
        PRD 2.4: "an integer version that begins at 1 and increments by exactly 1 on each mutation"

        Design: Corner/entities/corner_customer_creation_returns_fields
        """
        data = validate_success(api.create_customer({"email": "new@x.com", "full_name": "New"}, ADMIN), 201)
        assert_customer(data)
        assert data["store_credit_cents"] == 0
        assert data["version"] == 1

    def test_get_nonexistent_customer_not_found(self, api):
        """PRD 2.8: "the first missing reference yields the matching not-found error —
        ERR_CUSTOMER_NOT_FOUND, ERR_TEMPLATE_NOT_FOUND, ERR_PROJECT_NOT_FOUND, ERR_PROOF_NOT_FOUND,
        ERR_ORDER_NOT_FOUND, ERR_ADDRESS_NOT_FOUND, ERR_PROMOTION_NOT_FOUND,
        ERR_PRODUCTION_JOB_NOT_FOUND, ERR_SHIPMENT_NOT_FOUND, or ERR_SURGE_WINDOW_NOT_FOUND
        (all HTTP 404)."

        Design: Corner/entities/corner_customer_not_found
        """
        res = api.get_customer(NON_EXISTENT_UUID, ADMIN)
        validate_error(res, "ERR_CUSTOMER_NOT_FOUND", 404)


class TestTemplateCatalog:

    def test_missing_required_field_rejected(self, api):
        """PRD 2.8: "Only then is the request body inspected for well-formedness — required fields
        present, enum values legal, chosen finish within the template's offered set, and quantities
        positive — with any failure reported as ERR_VALIDATION (HTTP 422)."

        Design: Corner/entities/corner_template_missing_required_field_returns_invalid_request
        """
        payload = create_template_payload()
        del payload["base_unit_price_cents"]  # required, no default
        res = api.create_template(payload, ADMIN)
        validate_error(res, "ERR_VALIDATION", 422)

    def test_project_on_retired_template_rejected(self, api):
        """PRD 3.2: "Project creation is refused with ERR_TEMPLATE_RETIRED when the chosen template
        is RETIRED."

        Design: Corner/state_machines/corner_project_on_retired_template_rejected
        """
        cust = create_customer()
        h = make_customer_headers(cust["id"])
        tmpl = create_template()
        validate_success(api.retire_template(tmpl["id"], ADMIN), 200)
        res = api.create_project(create_project_payload(customer_id=cust["id"], template_id=tmpl["id"], title="P"), h)
        validate_error(res, "ERR_TEMPLATE_RETIRED", 409)


class TestRoleBasedAccess:

    def test_production_operator_cannot_place_order(self, api):
        """PRD 2.1: "If the headers are well-formed but the role named in X-User-Role is not permitted
        to invoke the target endpoint (per the authorization column of Section 4), the request is
        rejected with ERR_UNAUTHORIZED (HTTP 403)."

        Design: Corner/rbac/corner_production_operator_cannot_place_order
        """
        res = api.create_order({"project_id": NON_EXISTENT_UUID, "quantity": 1, "finish": "MATTE",
                                "ship_method": "STANDARD", "ship_address_id": NON_EXISTENT_UUID,
                                "payment_method": "CARD"}, OPERATOR)
        validate_error(res, "ERR_UNAUTHORIZED", 403)

    def test_customer_cannot_create_template(self, api):
        """PRD 2.1: "If the headers are well-formed but the role named in X-User-Role is not permitted
        to invoke the target endpoint (per the authorization column of Section 4), the request is
        rejected with ERR_UNAUTHORIZED (HTTP 403)."

        Design: Corner/rbac/corner_customer_cannot_create_template
        """
        cust = create_customer()
        h = make_customer_headers(cust["id"])
        res = api.create_template(create_template_payload(name="X"), h)
        validate_error(res, "ERR_UNAUTHORIZED", 403)

    def test_customer_cannot_read_other_customers_project(self, api):
        """PRD 2.1: "When a Customer acts on a project, photo, proof, order, or address whose owning
        customer_id does not equal X-User-ID, the request is rejected with ERR_FORBIDDEN_OWNERSHIP
        (HTTP 403)."

        Design: Corner/rbac/corner_customer_cannot_read_other_customers_project
        """
        cust_a = create_customer(email="a@x.com", full_name="A")
        cust_b = create_customer(email="b@x.com", full_name="B")
        tmpl = create_template()
        proj = create_project(cust_a, tmpl, headers=make_customer_headers(cust_a["id"]))
        res = api.get_project(proj["id"], make_customer_headers(cust_b["id"]))
        validate_error(res, "ERR_FORBIDDEN_OWNERSHIP", 403)

    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD 2.1: "If either header is missing or malformed, the request is rejected with
        ERR_UNAUTHENTICATED (HTTP 401) before any other processing."

        Design: Corner/rbac/corner_missing_auth_headers_unauthenticated
        """
        cust = create_customer()
        res = api.get_customer(cust["id"], {})  # no X-User-ID / X-User-Role
        validate_error(res, "ERR_UNAUTHENTICATED", 401)
