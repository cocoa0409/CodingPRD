"""Role authorization and entity-backed ownership (PRD §2.1, §3.1)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_contract,
    create_customer,
    create_equipment_unit_payload,
    create_site,
    make_customer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

TEST_SALES = TEST_USERS["sales_engineer_headers"]
TEST_DEPOT = TEST_USERS["depot_manager_headers"]


class TestRoleAuthorization:
    def test_customer_cannot_create_equipment(self, api):
        """PRD §2.1: "Once authenticated, the role is checked against the endpoint's
        authorization list; a role that is not permitted for the endpoint is rejected
        with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /power-rental/equipment-units is authorized for DepotManager
        only.

        Design: Corner/rbac/customer_cannot_create_equipment
        """
        customer = create_customer()
        res = api.create_equipment_unit(
            create_equipment_unit_payload(),
            make_customer_headers(customer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

        _, meta = validate_paginated(api.list_equipment_units(TEST_DEPOT))
        assert meta["total_count"] == 0, "the forbidden create persists nothing"


class TestCustomerOwnership:
    def test_customer_cannot_read_other_customers_contract(self, api):
        """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the
        acting Customer record; ownership checks on any resource that references a
        customer — a contract, a site, an incident — compare the resource's customer
        foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_OWNER`
        (HTTP 403)."

        Design: Corner/rbac/customer_cannot_read_other_customers_contract
        """
        owner = create_customer(name="Acme Construction", billing_email="ap@acme.example")
        other = create_customer(name="Other Co", billing_email="ap@other.example")
        site = create_site(owner["id"])
        contract = create_contract(owner["id"], site["id"])

        denied = api.get_contract(contract["id"], make_customer_headers(other["id"]))
        validate_error(denied, ApiErrorId.ERR_NOT_OWNER, expected_status=403)

        allowed = validate_success(
            api.get_contract(contract["id"], make_customer_headers(owner["id"])), 200
        )
        assert allowed["id"] == contract["id"]
        assert allowed["status"] == "DRAFT"
