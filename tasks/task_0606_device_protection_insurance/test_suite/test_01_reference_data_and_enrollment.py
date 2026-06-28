"""Reference-data creation, enrollment creation/validation, and enrollment listing.

Covers corner-design `entities` instances and the IMEI-validity rules from PRD 3.2.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, assert_customer, assert_enrollment,
    create_customer_payload, create_plan_payload, create_replacement_sku_payload,
    create_enrollment_payload, NON_EXISTENT_UUID, IMEI_A, IMEI_BAD, PURCHASE_DATE,
)
from test_helpers import fixtures as fx


def _ref_data(api, admin, carrier="CA-REF-1"):
    cust = validate_success(api.create_customer(
        create_customer_payload(carrier_account_number=carrier), admin), 201)
    plan = validate_success(api.create_plan(create_plan_payload(), admin), 201)
    sku = validate_success(api.create_replacement_sku(create_replacement_sku_payload(), admin), 201)
    return cust, plan, sku


def test_create_customer_defaults_green_and_version_one(api, admin_headers):
    """PRD 3.1: "A new customer begins with `risk_flag` set to `GREEN` and
    `lifetime_approved_claim_count` set to 0".
    PRD 2.4: "The `version` starts at 1 when the resource is created".

    Design: Corner/entities/create_customer_returns_201_with_green_risk_flag
    """
    data = validate_success(api.create_customer(
        create_customer_payload(carrier_account_number="CA-CUST-1"), admin_headers), 201)
    assert_customer(data)
    assert data["risk_flag"] == "GREEN", f"expected GREEN, got {data['risk_flag']}"
    assert data["version"] == 1, f"expected version 1, got {data['version']}"
    assert data["lifetime_approved_claim_count"] == 0


def test_get_nonexistent_enrollment_returns_not_found(api, admin_headers):
    """PRD 2.7: "The first identifier that does not resolve to an existing resource
    causes the request to be rejected immediately with `ERR_NOT_FOUND`".

    Design: Corner/entities/get_enrollment_not_found_returns_404
    """
    resp = api.get_enrollment(NON_EXISTENT_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_create_enrollment_missing_imei_returns_validation(api, admin_headers):
    """PRD 3.2: "It is created ... with `customer_id`, `plan_id`, `imei`, `device_model`,
    `device_purchase_date`, and `replacement_sku_id`."
    PRD 5 error catalogue: `ERR_VALIDATION` 422 (generic missing/invalid required field).

    Design: Corner/entities/create_enrollment_missing_imei_returns_validation
    """
    cust, plan, sku = _ref_data(api, admin_headers, carrier="CA-ENR-2")
    payload = create_enrollment_payload(cust["id"], plan["id"], sku["id"])
    payload.pop("imei")
    resp = api.create_enrollment(payload, admin_headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)


def test_create_enrollment_imei_fails_luhn_returns_invalid_imei(api, admin_headers):
    """PRD 3.2: "At creation the `imei` must be exactly 15 digits and pass the Luhn
    checksum; a value that is not 15 digits or fails Luhn is rejected with
    `ERR_INVALID_IMEI`."

    Design: Corner/entities/enrollment_invalid_imei_luhn_returns_invalid_imei
    """
    cust, plan, sku = _ref_data(api, admin_headers, carrier="CA-ENR-3")
    resp = api.create_enrollment(
        create_enrollment_payload(cust["id"], plan["id"], sku["id"], imei=IMEI_BAD),
        admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_IMEI.value, 422)


def test_new_enrollment_starts_pending_eligibility(api, admin_headers):
    """PRD 3.2: "A freshly created enrollment begins in `PENDING_ELIGIBILITY`."
    PRD 3.2: "`premium_paid_through_cycle`, the highest billing-cycle index marked
    paid, which is -1 until any invoice is paid ... The `enrolled_at` timestamp is
    null until activation."

    Design: Corner/entities/enrollment_computed_status_pending_eligibility_on_create
    """
    cust, plan, sku = _ref_data(api, admin_headers, carrier="CA-ENR-4")
    data = validate_success(api.create_enrollment(
        create_enrollment_payload(cust["id"], plan["id"], sku["id"]), admin_headers), 201)
    assert_enrollment(data)
    assert data["status"] == "PENDING_ELIGIBILITY"
    assert data["premium_paid_through_cycle"] == -1
    assert data["enrolled_at"] is None


def test_list_enrollments_returns_paginated_envelope(api, admin_headers):
    """PRD 2.3: "List responses include the following fields in the `meta` object of
    the response envelope: `limit`, `offset`, `total_count`, and `has_more`."
    PRD 2.2: "The `response_type` is either "object" for a single resource or "array"
    for a list of resources."

    Design: Corner/entities/list_enrollments_pagination_envelope
    """
    cust, plan, sku = _ref_data(api, admin_headers, carrier="CA-ENR-5")
    validate_success(api.create_enrollment(
        create_enrollment_payload(cust["id"], plan["id"], sku["id"]), admin_headers), 201)
    resp = api.list_enrollments(admin_headers, params={"customer_id": cust["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert meta["has_more"] is False
