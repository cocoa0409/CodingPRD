"""Registry creation, response envelope, pagination, and authentication claims."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    is_valid_uuid, NON_EXISTENT_UUID,
    create_customer_payload, create_field_payload, create_product_payload,
    create_work_order_payload, create_calibration_record_payload,
    create_applicator_payload, create_equipment_payload,
    create_prescription_payload,
    create_customer, create_field, create_product,
    make_grower_headers, make_applicator_headers,
    assert_customer, assert_calibration_record,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
AGRONOMIST = TEST_USERS["agronomist_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_customer_creation_applies_computed_defaults(api):
    """PRD §3.1: "The new account's `outstanding_cents` starts at zero and
    changes only through the invoice events described in §2.10."
    PRD §2.4: "Every resource in the system carries an `id` — a server-minted
    UUID with no type prefix — and a `created_at` timestamp recording when the
    resource was first persisted."

    Design: Corner/entities/customer_creation_applies_defaults
    """
    payload = create_customer_payload(name="Solo Farm", billing_email="s@farm.test",
                                      rate_per_acre_cents=900, credit_limit_cents=500000)
    payload["outstanding_cents"] = 999999  # client-supplied computed field must not stick
    customer = validate_success(api.create_customer(payload, ADMIN), 201)
    assert_customer(customer)
    assert customer["outstanding_cents"] == 0, \
        f"outstanding_cents must start at zero, got {customer['outstanding_cents']}"
    assert is_valid_uuid(customer["id"]), "id must be a server-minted UUID"


def test_field_create_missing_required_acres_rejected(api):
    """PRD §2.9: "required fields present, types valid, enum members valid,
    numbers positive where required, else `ERR_VALIDATION`."
    PRD §3.1: "Each field records a human `label` such as "North 40", the
    `crop` under treatment, its total `acres`, and `buffer_clearance_ft`"

    Design: Corner/entities/field_create_missing_required_acres
    """
    customer = create_customer(name="Solo Farm", billing_email="s@farm.test",
                               rate_per_acre_cents=900, credit_limit_cents=500000)
    payload = {"customer_id": customer["id"], "label": "No Acres",
               "crop": "CORN", "buffer_clearance_ft": 100}
    res = api.create_field(payload, make_grower_headers(customer["id"]))
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_get_nonexistent_work_order_returns_not_found(api):
    """PRD §2.9: "path identifiers and body foreign-key references exist,
    else `ERR_NOT_FOUND`."

    Design: Corner/entities/get_nonexistent_work_order_returns_not_found
    """
    res = api.get_work_order(NON_EXISTENT_UUID, DISPATCHER)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_work_order_create_with_nonexistent_field_returns_not_found(api):
    """PRD §2.9: "path identifiers and body foreign-key references exist,
    else `ERR_NOT_FOUND`."

    Design: Corner/entities/work_order_create_with_nonexistent_field_returns_not_found
    """
    customer = create_customer(name="Solo Farm", billing_email="s@farm.test",
                               rate_per_acre_cents=900, credit_limit_cents=500000)
    payload = create_work_order_payload(customer["id"], NON_EXISTENT_UUID,
                                        NON_EXISTENT_UUID, acres_to_treat=10)
    res = api.create_work_order(payload, make_grower_headers(customer["id"]))
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_product_create_invalid_category_enum_rejected(api):
    """PRD §3.1: "a `category` of `HERBICIDE`, `INSECTICIDE`, or `FUNGICIDE`"
    PRD §2.9: "required fields present, types valid, enum members valid,
    numbers positive where required, else `ERR_VALIDATION`."

    Design: Corner/entities/product_create_invalid_category_enum
    """
    payload = create_product_payload(name="Mystery", epa_registration_no="EPA-9",
                                     category="RODENTICIDE", required_buffer_ft=0,
                                     unit_cost_cents=1000)
    res = api.create_product(payload, ADMIN)
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_calibration_records_are_append_only_evidence(api):
    """PRD §2.4: "Four resources are append-only evidence records and carry
    only `id` and `created_at`: CompatibilityRule, CalibrationRecord,
    WeatherObservation, and RinsateRecord. On those four, both `updated_at`
    and `version` are absent."
    PRD §3.3: "From the two flow figures the server computes `error_pct`: the
    absolute difference between `measured_gpa` and `target_gpa`, divided by
    `target_gpa`, multiplied by 100, rounded half-up to two decimal places."

    Design: Corner/entities/calibration_records_are_immutable_log
    """
    applicator = api_client.create_applicator(
        create_applicator_payload(license_categories=["HERBICIDE"]), ADMIN)
    applicator = validate_success(applicator, 201)
    equipment = validate_success(
        api.create_equipment(create_equipment_payload(), ADMIN), 201)

    first = validate_success(api.create_calibration_record(
        create_calibration_record_payload(equipment["id"], target_gpa=20.0, measured_gpa=20.5),
        make_applicator_headers(applicator["id"])), 201)
    validate_success(api.create_calibration_record(
        create_calibration_record_payload(equipment["id"], target_gpa=20.0, measured_gpa=20.6),
        make_applicator_headers(applicator["id"])), 201)

    # The earlier record is untouched by the later posting.
    reread = validate_success(api.get_calibration_record(first["id"], ADMIN), 200)
    assert_calibration_record(reread)
    assert reread["error_pct"] == 2.5, \
        f"first record error_pct must remain 2.5, got {reread['error_pct']}"

    # Both records remain visible in the list.
    data, meta = validate_paginated(api.list_calibration_records(ADMIN))
    ids = {row["id"] for row in data}
    assert len(data) == 2 and first["id"] in ids


def test_initial_states_on_creation(api):
    """PRD §3.4: "A new work order is `DRAFT`: `applicator_id`, `equipment_id`,
    `scheduled_start`, and `scheduled_end` are all null until scheduling,
    `uses_adjuvant` defaults to false, `started_at` and `completed_at` are
    null, `estimated_total_cents` is null while the order remains a draft, and
    both rinsate counters start at zero."
    PRD §3.2: "A new prescription is born `DRAFT`"
    PRD §3.3: "New applicators start `ACTIVE` with `penalty_points_lifetime`
    and `rolling_score_365` both zero."
    PRD §3.3: "New equipment starts `AVAILABLE` with `calibration_valid_until`
    null — uncalibrated, and therefore not yet schedulable."

    Design: Corner/state_machines/initial_states_on_creation
    """
    customer = create_customer(name="Solo Farm", billing_email="s@farm.test",
                               rate_per_acre_cents=900, credit_limit_cents=500000)
    field = create_field(customer["id"], label="F")
    product = create_product()
    rx = validate_success(api.create_prescription(
        create_prescription_payload(field["id"],
                                    [{"product_id": product["id"], "rate_per_acre": 1.5}]),
        AGRONOMIST), 201)
    applicator = validate_success(api.create_applicator(
        create_applicator_payload(license_categories=["HERBICIDE"]), ADMIN), 201)
    equipment = validate_success(
        api.create_equipment(create_equipment_payload(), ADMIN), 201)
    wo = validate_success(api.create_work_order(
        create_work_order_payload(customer["id"], field["id"], rx["id"], acres_to_treat=100),
        make_grower_headers(customer["id"])), 201)

    assert wo["status"] == "DRAFT"
    assert wo["applicator_id"] is None
    assert wo["equipment_id"] is None
    assert wo["scheduled_start"] is None and wo["scheduled_end"] is None
    assert wo["uses_adjuvant"] is False
    assert wo["estimated_total_cents"] is None
    assert wo["rinsate_generated_gal"] == 0 and wo["rinsate_balance_gal"] == 0
    assert rx["status"] == "DRAFT"
    assert applicator["status"] == "ACTIVE"
    assert applicator["penalty_points_lifetime"] == 0
    assert applicator["rolling_score_365"] == 0
    assert equipment["status"] == "AVAILABLE"
    assert equipment["calibration_valid_until"] is None


def test_response_envelope_shape_success_and_error(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."
    PRD §2.2 (error format): "The `meta` object for error responses contains
    only `api_request_id` and `api_request_timestamp`."

    Design: Corner/endpoints/response_envelope_shape_success_and_error
    """
    res = api.create_customer(create_customer_payload(
        name="Env Farm", billing_email="e@farm.test",
        rate_per_acre_cents=100, credit_limit_cents=1000), ADMIN)
    assert res.status_code == 201
    body = res.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert isinstance(body["data"], dict) and body["data"]["name"] == "Env Farm"

    err_res = api.get_work_order(NON_EXISTENT_UUID, DISPATCHER)
    err_body = err_res.json()
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(err_body["data"]["message"], str) and err_body["data"]["message"].strip()
    assert set(err_body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}


def test_customer_list_pagination_limit_offset(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter skips that many items from the front of the result set and
    defaults to 0."
    PRD §2.3: "Paginated list responses carry four fields in the `meta` object
    of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_pagination_limit_offset
    """
    for i in range(12):
        validate_success(api.create_customer(create_customer_payload(
            name=f"C{i + 1:02d}", billing_email=f"c{i + 1:02d}@farm.test",
            rate_per_acre_cents=100, credit_limit_cents=1000), ADMIN), 201)

    data, meta = validate_paginated(api.list_customers(ADMIN))
    assert len(data) == 10, f"default page must hold 10 items, got {len(data)}"
    assert meta["limit"] == 10 and meta["offset"] == 0
    assert meta["total_count"] == 12 and meta["has_more"] is True

    data2, meta2 = validate_paginated(api.list_customers(ADMIN, params={"offset": 10}))
    assert len(data2) == 2, f"offset=10 page must hold the remaining 2, got {len(data2)}"
    assert meta2["total_count"] == 12 and meta2["has_more"] is False


def test_missing_or_unknown_role_header_returns_unauthenticated(api):
    """PRD §2.1: "A request whose `X-User-Role` header names no declared role,
    or whose `X-User-ID` header is missing, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_header_returns_unauthenticated
    """
    payload = create_customer_payload(name="X", billing_email="x@farm.test",
                                      rate_per_acre_cents=100, credit_limit_cents=1000)
    # No X-User-Role header at all.
    res = api.create_customer(payload, {"X-User-ID": "someone",
                                        "Content-Type": "application/json"})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
    # X-User-Role present but naming no declared role.
    res2 = api.create_customer(payload, {"X-User-ID": "someone",
                                         "X-User-Role": "Anonymous",
                                         "Content-Type": "application/json"})
    validate_error(res2, "ERR_UNAUTHENTICATED", expected_status=401)
