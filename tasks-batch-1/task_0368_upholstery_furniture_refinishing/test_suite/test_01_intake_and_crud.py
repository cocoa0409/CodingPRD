"""Intake CRUD, system fields, listing envelope, line-item & catalog validations.

Work-order creation defaults, required/enum/FK validation, condition-photo
sequencing and immutability, the listing envelope, line-item service-type field
rules, catalog availability, and not-found resolution.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_work_order, assert_condition_photo,
    create_work_order_payload, create_condition_photo_payload, create_line_item_payload,
    register_customer, register_fabric_sku, register_discontinued_fabric_sku,
    open_intake_work_order, create_estimating_work_order,
    reupholstery_line_item,
    TEST_USERS,
)

CLERK = TEST_USERS["intake_clerk_headers"]
MANAGER = TEST_USERS["shop_manager_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]

NONEXISTENT = "00000000-0000-4000-8000-000000000000"


def test_create_work_order_returns_201_with_intake_defaults(api):
    """PRD §3.1: "A newly opened order sits in `INTAKE` status with its estimate,
    invoice, and balance counters all at 0, no committed materials, and no promised
    turnaround yet."
    PRD §2.4: "a `version` integer that begins at its initial value and increments
    by one with each mutation."

    Design: Corner/entities/create_work_order_returns_201_with_intake_defaults
    """
    cust = register_customer()
    res = api.create_work_order(
        create_work_order_payload(cust["id"], service_type="REUPHOLSTERY", rush_requested=False),
        CLERK,
    )
    wo = validate_success(res, 201)
    assert_work_order(wo)
    assert wo["status"] == "INTAKE"
    assert wo["estimate_total_cents"] == 0
    assert wo["amount_paid_cents"] == 0
    assert wo["balance_due_cents"] == 0
    assert wo["version"] == 1


def test_create_work_order_missing_service_type_returns_invalid_request(api):
    """PRD §2.9: "a request whose required body fields are missing, ill-typed, or carry
    an invalid enum value is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_work_order_missing_service_type_returns_invalid_request
    """
    cust = register_customer()
    res = api.create_work_order({"customer_id": cust["id"]}, CLERK)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_work_order_invalid_enum_service_type_returns_invalid_request(api):
    """PRD §2.9: "a request whose required body fields are missing, ill-typed, or carry
    an invalid enum value is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_work_order_invalid_enum_service_type_returns_invalid_request
    """
    cust = register_customer()
    res = api.create_work_order(
        {"customer_id": cust["id"], "service_type": "STAINING"}, CLERK)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_work_order_unknown_customer_returns_fk_not_found(api):
    """PRD §3.1: "If the `customer_id` names no existing customer, the create is rejected
    with `ERR_FK_NOT_FOUND`."

    Design: Corner/entities/create_work_order_unknown_customer_returns_fk_not_found
    """
    res = api.create_work_order(
        {"customer_id": NONEXISTENT, "service_type": "REPAIR"}, CLERK)
    validate_error(res, "ERR_FK_NOT_FOUND", expected_status=404)


def test_get_work_order_nonexistent_returns_not_found(api):
    """PRD §2.8: "The parent work order's existence is checked first, and if it does not
    exist the request fails with `ERR_WORK_ORDER_NOT_FOUND` before any child is considered."

    Design: Corner/entities/get_work_order_nonexistent_returns_not_found
    """
    res = api.get_work_order(NONEXISTENT, MANAGER)
    validate_error(res, "ERR_WORK_ORDER_NOT_FOUND", expected_status=404)


def test_condition_photo_sequence_no_assigned_by_created_at(api):
    """PRD §3.1: "Each photo receives a server-assigned `sequence_no`, a 1-based intake
    ordinal computed by ordering the order's photos by `created_at` ascending."

    Design: Corner/entities/condition_photo_sequence_no_assigned_by_created_at
    """
    cust = register_customer()
    wo = validate_success(api.create_work_order(
        create_work_order_payload(cust["id"], service_type="REPAIR"), CLERK), 201)
    p1 = validate_success(api.create_condition_photo(
        create_condition_photo_payload(wo["id"], image_uri="s3://c/1.jpg"), CLERK), 201)
    p2 = validate_success(api.create_condition_photo(
        create_condition_photo_payload(wo["id"], image_uri="s3://c/2.jpg"), CLERK), 201)
    assert p1["sequence_no"] == 1
    assert p2["sequence_no"] == 2


def test_condition_photo_immutable_entity_no_version_field(api):
    """PRD §2.4: "A `ConditionPhoto` is immutable once created: it carries only `id` and
    `created_at`, and it has neither an `updated_at` field nor a `version` field."

    Design: Corner/entities/condition_photo_immutable_entity_no_version_field
    """
    cust = register_customer()
    wo = validate_success(api.create_work_order(
        create_work_order_payload(cust["id"], service_type="REPAIR"), CLERK), 201)
    photo = validate_success(api.create_condition_photo(
        create_condition_photo_payload(wo["id"], image_uri="s3://c/3.jpg"), CLERK), 201)
    got = validate_success(api.get_condition_photo(photo["id"], CLERK), 200)
    assert_condition_photo(got)
    assert got["id"] == photo["id"]
    assert "version" not in got, "ConditionPhoto must not carry a version field"
    assert "updated_at" not in got, "ConditionPhoto must not carry an updated_at field"


def test_list_work_orders_pagination_envelope(api):
    """PRD §2.3: "Each list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count` is the count
    of all matching records and `has_more` indicates whether records remain beyond the
    current page."

    Design: Corner/entities/list_work_orders_pagination_envelope
    """
    cust = register_customer()
    validate_success(api.create_work_order(
        create_work_order_payload(cust["id"], service_type="REPAIR"), CLERK), 201)
    res = api.list_work_orders(MANAGER)
    data, meta = validate_paginated(res)
    assert isinstance(data, list)
    assert "total_count" in meta
    assert "has_more" in meta
    body = res.json()
    assert body["response_type"] == "array"
    assert "api_request_id" in body["meta"]


# ---------------------------------------------------------------------------
# Line-item service-type field rules + catalog availability
# ---------------------------------------------------------------------------
def test_reupholstery_line_item_missing_fabric_returns_fields_invalid(api):
    """PRD §3.2: "When the order's `service_type` is `REUPHOLSTERY`, the line item must
    name a `fabric_sku_id` and must carry a `yardage_required` greater than zero."
    PRD §3.2: "A line item that violates these field rules is rejected with
    `ERR_LINE_ITEM_FIELDS_INVALID`."

    Design: Corner/validations/reupholstery_line_item_missing_fabric_returns_fields_invalid
    """
    _, wo = open_intake_work_order(service_type="REUPHOLSTERY")
    res = api.create_line_item(
        wo["id"],
        create_line_item_payload(piece_label="No fabric", yardage_required=0, labor_hours=3),
        CLERK,
    )
    validate_error(res, "ERR_LINE_ITEM_FIELDS_INVALID", expected_status=422)


def test_line_item_with_discontinued_fabric_returns_catalog_unavailable(api):
    """PRD §3.2: "any selected `fabric_sku_id` or `foam_spec_id` must reference a catalog
    item that is currently `LISTED`, and a positive `board_feet_required` without a foam
    spec is itself invalid; a violation of these catalog-availability constraints is
    rejected with `ERR_CATALOG_ITEM_UNAVAILABLE`."

    Design: Corner/validations/line_item_with_discontinued_fabric_returns_catalog_unavailable
    """
    fab = register_discontinued_fabric_sku()
    _, wo = open_intake_work_order(service_type="REUPHOLSTERY")
    res = api.create_line_item(
        wo["id"],
        reupholstery_line_item(fab["id"], yardage_required=4, labor_hours=3, piece_label="X"),
        CLERK,
    )
    validate_error(res, "ERR_CATALOG_ITEM_UNAVAILABLE", expected_status=422)


def test_list_work_orders_bad_pagination_returns_error(api):
    """PRD §2.3: "The `limit` parameter caps how many items a response returns; it defaults
    to 10 when omitted, may be no smaller than 1, and may be no larger than 100."
    PRD §2.3: "A request whose `limit` or `offset` falls outside these bounds is rejected
    with `ERR_INVALID_PAGINATION`."

    Design: Corner/validations/list_work_orders_bad_pagination_returns_error
    """
    res = api.list_work_orders(MANAGER, params={"limit": 0})
    validate_error(res, "ERR_INVALID_PAGINATION", expected_status=400)


def test_receive_nonexistent_material_order_returns_resource_not_found(api):
    """PRD §2.8: "For collection endpoints addressed by a single id that is not a work
    order — an estimate, a material order, a fulfillment leg, a warranty claim, a shop day,
    a customer, a fabric SKU, or a foam spec — a missing target yields
    `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/errors/receive_nonexistent_material_order_returns_resource_not_found
    """
    res = api.receive_material_order(
        NONEXISTENT, {"received_fabric_price_cents_per_yard": 1800}, MANAGER)
    validate_error(res, "ERR_RESOURCE_NOT_FOUND", expected_status=404)
