"""Warranty registration: certification gate, immutability, and the
registered-bundles computation."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_warranty_registration,
    first_order_line,
    get_success_data,
    make_contractor_headers,
    request_return_payload,
    setup_delivered_order,
    validate_error,
    validate_success,
    ApiErrorId,
)

MANAGER = TEST_USERS["branch_manager_headers"]
WAREHOUSE = TEST_USERS["warehouse_clerk_headers"]


class TestCertificationGate:
    def test_registration_rejected_without_manufacturer_certification(self, api):
        """PRD §3.8: "Certification is enforced at this gate: when a product
        on the order has `requires_certified_installer` set, the contractor's
        `manufacturer_certifications` must include that product's
        manufacturer, or registration is refused with
        `ERR_CERTIFICATION_REQUIRED` (HTTP 422); a successful match is
        recorded in `certification_verified`."

        The product requires a certified installer and the account's
        certification list is empty.

        Design: Difficulty/cross_entity_state_dependency/warranty_blocked_without_manufacturer_certification
        """
        ctx = setup_delivered_order(branch_code="BR-X3", sku="SH-X3",
                                    price=4000, roof_squares=10.0,
                                    manufacturer_name="CertCo",
                                    requires_certified_installer=True,
                                    certs=[], company_name="Uncert Co")
        assert ctx["product"]["requires_certified_installer"] is True
        resp = api_client.register_warranty(
            ctx["order"]["id"],
            make_contractor_headers(ctx["account"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_REQUIRED)

    def test_registration_succeeds_with_matching_certification(self, api):
        """PRD §3.8: "Certification is enforced at this gate: when a product
        on the order has `requires_certified_installer` set, the contractor's
        `manufacturer_certifications` must include that product's
        manufacturer, or registration is refused with
        `ERR_CERTIFICATION_REQUIRED` (HTTP 422); a successful match is
        recorded in `certification_verified`."
        PRD §3.8: "The owning `Contractor` registers the manufacturer warranty
        for a delivered order, which copies the product's `manufacturer_name`
        onto the registration and counts `registered_bundles` as the delivered
        minus the returned bundles at registration time."

        Control arm: the account lists the product's manufacturer; the
        registration succeeds with certification_verified true.

        Design: Difficulty/cross_entity_state_dependency/warranty_blocked_without_manufacturer_certification
        """
        ctx = setup_delivered_order(branch_code="BR-X4", sku="SH-X4",
                                    price=4000, roof_squares=10.0,
                                    manufacturer_name="CertCo",
                                    requires_certified_installer=True,
                                    certs=["CertCo"], company_name="Cert Co")
        registration = validate_success(api_client.register_warranty(
            ctx["order"]["id"],
            make_contractor_headers(ctx["account"]["id"])),
            expected_status=201)
        assert_warranty_registration(registration)
        assert registration["certification_verified"] is True
        assert registration["manufacturer_name"] == "CertCo"
        assert registration["registered_bundles"] == 30


class TestRegistrationShapeAndComputation:
    def test_registration_is_immutable_common_fields_subset(self, api):
        """PRD §2.5: "One entity breaks this pattern deliberately. A
        WarrantyRegistration is immutable once created and therefore carries
        only `id` and `created_at`; both `updated_at` and `version` are absent
        from it."
        PRD §3.8: "The owning `Contractor` registers the manufacturer warranty
        for a delivered order, which copies the product's `manufacturer_name`
        onto the registration and counts `registered_bundles` as the delivered
        minus the returned bundles at registration time."

        15 bundles delivered, none returned: registered_bundles 15.

        Design: Corner/entities/warranty_registration_immutable_no_version_field
        """
        ctx = setup_delivered_order(branch_code="BR-E4", sku="SH-E4",
                                    price=3000, roof_squares=5.0,
                                    lot_code="LOT-E4", company_name="Warr Co")
        registration = validate_success(api_client.register_warranty(
            ctx["order"]["id"],
            make_contractor_headers(ctx["account"]["id"])),
            expected_status=201)
        assert_warranty_registration(registration)
        assert registration["registered_bundles"] == 15
        assert registration["manufacturer_name"] == "Acme"

    def test_registered_bundles_nets_delivered_minus_returned(self, api):
        """PRD §3.8: "The owning `Contractor` registers the manufacturer
        warranty for a delivered order, which copies the product's
        `manufacturer_name` onto the registration and counts
        `registered_bundles` as the delivered minus the returned bundles at
        registration time."

        15 delivered, 5 returned and received before registration:
        registered_bundles 10.

        Design: Corner/endpoints/warranty_registration_computed_read_correct
        """
        ctx = setup_delivered_order(branch_code="BR-EP5", sku="SH-EP5",
                                    price=2000, roof_squares=5.0,
                                    lot_code="LOT-EP5", company_name="EP5 Co")
        line = first_order_line(ctx["order"]["id"])
        ret = validate_success(api_client.request_return(
            ctx["order"]["id"],
            request_return_payload(line["id"], quantity_bundles=5,
                                   opened_bundles=0),
            make_contractor_headers(ctx["account"]["id"])), expected_status=201)
        get_success_data(api_client.approve_return(ret["id"], MANAGER))
        get_success_data(api_client.receive_return(ret["id"], "LOT-EP5",
                                                   WAREHOUSE))
        registration = validate_success(api_client.register_warranty(
            ctx["order"]["id"],
            make_contractor_headers(ctx["account"]["id"])),
            expected_status=201)
        assert_warranty_registration(registration)
        assert registration["registered_bundles"] == 10
