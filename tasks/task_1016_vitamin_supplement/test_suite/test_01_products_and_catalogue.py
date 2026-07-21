"""Product/SKU catalogue: required-field validation, existence, the computed
FDA-disclaimer flag, DSHEA disease-claim refusal, and role gating on creation.
"""
from test_helpers import (
    api_client, validate_success, validate_error, NON_EXISTENT_UUID,
    create_product_payload, assert_product, TEST_USERS, make_customer_headers,
    new_customer,
)

OPERATOR = TEST_USERS["store_operator_headers"]


def test_create_product_missing_unit_price_rejected(api):
    """PRD §2.8: "A request that supplies a required field of the wrong type,
    omits a required field, or supplies an out-of-range enum value is rejected
    with `ERR_VALIDATION`."

    Design: Corner/entities/corner_product_missing_unit_price_returns_validation
    """
    payload = create_product_payload()
    del payload["unit_price_cents"]
    res = api.create_product(payload, OPERATOR)
    validate_error(res, "ERR_VALIDATION", expected_status=422)


def test_get_nonexistent_product_returns_not_found(api):
    """PRD §2.8: "The system validates every such reference for existence in
    left-to-right order — path identifiers first, then body foreign keys in the
    order they appear — and rejects the request with `ERR_NOT_FOUND` at the
    first identifier that does not resolve to an existing resource."

    Design: Corner/entities/corner_product_get_nonexistent_returns_not_found
    """
    res = api.get_product(NON_EXISTENT_UUID, OPERATOR)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_structure_function_product_requires_disclaimer(api):
    """PRD §3.1: "The system computes `requires_fda_disclaimer` as a stored
    boolean that is true exactly when `dshea_claim_type` is `STRUCTURE_FUNCTION`,
    and false otherwise."

    Design: Corner/entities/corner_product_computed_disclaimer_true
    """
    payload = create_product_payload(dshea_claim_type="STRUCTURE_FUNCTION",
                                     unit_price_cents=1000)
    prod = validate_success(api.create_product(payload, OPERATOR), 201)
    assert_product(prod)
    assert prod["requires_fda_disclaimer"] is True, (
        "STRUCTURE_FUNCTION product must have requires_fda_disclaimer == true"
    )


def test_disease_claim_product_rejected(api):
    """PRD §3.1: "a submitted value of `DISEASE` is refused with
    `ERR_DSHEA_DISEASE_CLAIM` (see Section 2.11) and never stored."

    Design: Corner/validations/corner_dshea_disease_claim_rejected
    """
    payload = create_product_payload(dshea_claim_type="DISEASE", unit_price_cents=1000)
    res = api.create_product(payload, OPERATOR)
    validate_error(res, "ERR_DSHEA_DISEASE_CLAIM", expected_status=422)


def test_customer_cannot_create_product(api):
    """PRD §2.1: "When a caller's role is not permitted to invoke the requested
    operation per the access matrix in Section 4, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/corner_customer_cannot_create_product_unauthorized
    """
    cust = new_customer(email="r1@x.com", full_name="R One")
    res = api.create_product(create_product_payload(), make_customer_headers(cust["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)
