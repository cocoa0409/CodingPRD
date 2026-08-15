"""Access control: authentication, role permission, entity-backed ownership."""
from test_helpers import (
    validate_error, ApiErrorId, TEST_USERS, make_customer_contact_headers,
    create_plant_payload, create_plant, create_linen_category, create_customer,
    generate_invoice, get_customer_version,
    setup_delivery_delivered,
)

ADMIN = TEST_USERS["plant_admin_headers"]
DRIVER = TEST_USERS["route_driver_headers"]
OPERATOR = TEST_USERS["plant_operator_headers"]


class TestAuthentication:
    def test_unauthenticated_request_rejected(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying the acting role. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_request_rejected
        """
        resp = api.get_plant(
            "00000000-0000-0000-0000-000000000000", headers={}
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRolePermission:
    def test_route_driver_cannot_create_plant(self, api):
        """PRD §2.1: "A request whose role is not permitted to call the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST /plants is authorized for PlantAdmin only.

        Design: Corner/roles/route_driver_cannot_create_plant
        """
        resp = api.create_plant(create_plant_payload(), DRIVER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_plant_operator_cannot_issue_invoice(self, api):
        """PRD §2.1: "A request whose role is not permitted to call the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST /invoices/{id}/issue is authorized for BillingClerk only.

        Design: Corner/roles/plant_operator_cannot_issue_invoice
        """
        plant = create_plant()
        customer = create_customer(plant["id"], billing_mode="COG")
        invoice = generate_invoice(customer["id"])
        version = get_customer_version(customer["id"])
        resp = api.issue_invoice(
            invoice["id"], {"expected_customer_version": version}, OPERATOR
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestOwnership:
    def test_customer_contact_cannot_confirm_other_customers_delivery(self, api):
        """PRD §2.1: "When `X-User-Role` is `CustomerContact`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's foreign-key field to `X-User-ID`. A `CustomerContact` confirms or disputes deliveries belonging to their own customer, and may read their own customer's data; any attempt to act on or read another customer's resources is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/roles/customer_contact_cannot_confirm_other_customers_delivery
        """
        ctx = setup_delivery_delivered(
            pieces_promised=10,
            pieces_delivered=10,
            customer_overrides={
                "name": "C1", "billing_mode": "RENTAL",
            },
        )
        other = create_customer(
            ctx["plant"]["id"], name="C2", billing_mode="RENTAL"
        )
        resp = api.confirm_delivery(
            ctx["delivery"]["id"], make_customer_contact_headers(other["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
