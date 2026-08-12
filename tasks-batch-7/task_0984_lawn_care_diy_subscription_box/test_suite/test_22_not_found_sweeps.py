"""Resource-specific 404 identifiers on GET of a random UUID (PRD 2.8)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]

MISSING = "11111111-1111-1111-1111-111111111111"


def test_not_found_sweep_core(api):
    """PRD 2.8: "path identifiers and body foreign-key references must exist, validated left to right along the URL and payload. Each missing resource surfaces its own 404 identifier: `ERR_CUSTOMER_NOT_FOUND`, `ERR_LAWN_NOT_FOUND`, `ERR_SOIL_TEST_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_ADD_ON_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, or `ERR_PRODUCT_NOT_FOUND` when a referenced catalog sku does not exist."

    Design: Corner/entities/not_found_sweep_core
    """
    th.validate_error(api.get_customer(MISSING, ADMIN),
                      th.ApiErrorId.ERR_CUSTOMER_NOT_FOUND)
    th.validate_error(api.get_lawn(MISSING, ADMIN),
                      th.ApiErrorId.ERR_LAWN_NOT_FOUND)
    th.validate_error(api.get_plan(MISSING, ADMIN),
                      th.ApiErrorId.ERR_PLAN_NOT_FOUND)
    th.validate_error(api.get_soil_test(MISSING, ADMIN),
                      th.ApiErrorId.ERR_SOIL_TEST_NOT_FOUND)


def test_not_found_sweep_commerce(api):
    """PRD 2.8: "path identifiers and body foreign-key references must exist, validated left to right along the URL and payload. Each missing resource surfaces its own 404 identifier: `ERR_CUSTOMER_NOT_FOUND`, `ERR_LAWN_NOT_FOUND`, `ERR_SOIL_TEST_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_ADD_ON_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, or `ERR_PRODUCT_NOT_FOUND` when a referenced catalog sku does not exist."

    Design: Corner/entities/not_found_sweep_commerce
    """
    th.validate_error(api.get_subscription(MISSING, ADMIN),
                      th.ApiErrorId.ERR_SUBSCRIPTION_NOT_FOUND)
    th.validate_error(api.get_shipment(MISSING, ADMIN),
                      th.ApiErrorId.ERR_SHIPMENT_NOT_FOUND)
    th.validate_error(api.get_invoice(MISSING, ADMIN),
                      th.ApiErrorId.ERR_INVOICE_NOT_FOUND)


def test_not_found_sweep_engagement(api):
    """PRD 2.8: "path identifiers and body foreign-key references must exist, validated left to right along the URL and payload. Each missing resource surfaces its own 404 identifier: `ERR_CUSTOMER_NOT_FOUND`, `ERR_LAWN_NOT_FOUND`, `ERR_SOIL_TEST_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_ADD_ON_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, or `ERR_PRODUCT_NOT_FOUND` when a referenced catalog sku does not exist."

    Design: Corner/entities/not_found_sweep_engagement
    """
    th.validate_error(api.get_application(MISSING, ADMIN),
                      th.ApiErrorId.ERR_APPLICATION_NOT_FOUND)
    th.validate_error(api.get_add_on(MISSING, ADMIN),
                      th.ApiErrorId.ERR_ADD_ON_NOT_FOUND)
    th.validate_error(api.get_claim(MISSING, ADMIN),
                      th.ApiErrorId.ERR_CLAIM_NOT_FOUND)
    th.validate_error(api.get_referral(MISSING, ADMIN),
                      th.ApiErrorId.ERR_REFERRAL_NOT_FOUND)
