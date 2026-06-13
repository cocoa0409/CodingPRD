"""Resource creation, input validation, referential checks, and RBAC / auth gates.

All instances here are queue-B corner translations.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    create_customer, create_profile, create_fabric, create_draft_order,
    create_customer_payload, create_measurement_profile_payload,
    create_order_payload, create_option_line_payload, create_fabric_payload,
    TEST_USERS, FAKE_UUID,
)

SA = TEST_USERS["sales_associate_headers"]
SM = TEST_USERS["shop_manager_headers"]
CUST = TEST_USERS["customer_headers"]


# ─── Queue B: entities corners ──────────────────────────────────────────

def test_create_customer_returns_system_fields(api):
    """PRD §3.1: "`store_credit_cents` begins at 0 and is a non-negative ledger of store credit"
    PRD §3.1: "`completed_order_count` begins at 0 and counts every one of their orders that reached pickup; and `remake_risk_band` begins at `STANDARD`"
    PRD §2.4: "an integer `version` that begins at 1 when the resource is created".

    Design: Corner/entities/create_customer_returns_201_with_system_fields
    """
    res = api.create_customer(create_customer_payload(full_name="Ann Tailor"), SA)
    customer = validate_success(res, 201)
    assert customer["store_credit_cents"] == 0
    assert customer["remake_count"] == 0
    assert customer["completed_order_count"] == 0
    assert customer["remake_risk_band"] == "STANDARD"
    assert customer["version"] == 1


def test_get_nonexistent_order_returns_not_found(api):
    """PRD §2.6: "A request against a fitting under a non-existent order therefore fails with `ERR_ORDER_NOT_FOUND` (HTTP 404)".
    PRD §5 (error catalogue): ERR_ORDER_NOT_FOUND -> 404.

    Design: Corner/entities/get_order_nonexistent_returns_order_not_found
    """
    res = api.get_order(FAKE_UUID, SA)
    validate_error(res, "ERR_ORDER_NOT_FOUND")


def test_create_order_missing_required_field_rejected(api):
    """PRD §2.7: "Malformed request bodies — a missing required field, a wrong type, or an enum value outside the allowed set — are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.2: "a `base_labor_cents` charge (an integer strictly greater than 0)".

    Omitting required base_labor_cents -> 400 ERR_INVALID_REQUEST.

    Design: Corner/entities/create_order_missing_required_field_rejected
    """
    customer = create_customer()
    profile = create_profile(customer["id"])
    payload = create_order_payload(customer["id"], profile["id"], garment_type="SHIRT",
                                   fabric_meters_required=3.0)
    del payload["base_labor_cents"]
    res = api.create_order(payload, SA)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_order_default_is_rush_false(api):
    """PRD §3.2: "An order may optionally be marked `is_rush` at draft time (defaulting to false)".

    Omitting is_rush defaults it to false (PRD names the server-side default explicitly).

    Design: Corner/entities/create_order_default_is_rush_false_applied
    """
    customer = create_customer()
    profile = create_profile(customer["id"])
    payload = create_order_payload(customer["id"], profile["id"], garment_type="SHIRT",
                                   base_labor_cents=20000, fabric_meters_required=3.0)
    payload.pop("is_rush", None)
    order = validate_success(api.create_order(payload, SA), 201)
    assert order["is_rush"] is False
    assert order["status"] == "DRAFT"


def test_create_order_forces_draft_and_zero_quote(api):
    """PRD §3.2: "A freshly created order has `status` `DRAFT` and a `quoted_total_cents` of 0."

    The server forces the initial status and quote regardless of input.

    Design: Corner/entities/create_order_system_fields_input_ignored
    """
    customer = create_customer()
    profile = create_profile(customer["id"])
    payload = create_order_payload(customer["id"], profile["id"], garment_type="SHIRT",
                                   base_labor_cents=20000, fabric_meters_required=3.0)
    order = validate_success(api.create_order(payload, SA), 201)
    assert order["status"] == "DRAFT"
    assert order["quoted_total_cents"] == 0


def test_create_profile_invalid_source_enum_rejected(api):
    """PRD §2.7: "Malformed request bodies — a missing required field, a wrong type, or an enum value outside the allowed set — are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "The profile's `source` is either `MANUAL` or `BODY_SCAN`".

    source='LASER' is outside the allowed enum set -> 400 ERR_INVALID_REQUEST.

    Design: Corner/entities/create_profile_invalid_source_enum_rejected
    """
    customer = create_customer()
    payload = create_measurement_profile_payload(customer["id"], source="LASER")
    res = api.create_measurement_profile(payload, SA)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_order_unknown_customer_rejected(api):
    """PRD §2.6: "Body-level foreign-key references — `customer_id`, `measurement_profile_id`, `fabric_id`, `tailor_id`, `room_id`, and `group_order_id` — are likewise resolved and, if they do not exist, rejected with `ERR_CUSTOMER_NOT_FOUND`, `ERR_PROFILE_NOT_FOUND`, `ERR_FABRIC_NOT_FOUND`, `ERR_TAILOR_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, or `ERR_GROUP_NOT_FOUND` respectively (all HTTP 404)."

    A non-existent customer_id -> 404 ERR_CUSTOMER_NOT_FOUND.

    Design: Corner/entities/create_order_parent_customer_not_found
    """
    # A valid profile exists for a real customer, but the order cites a fake customer.
    real = create_customer()
    profile = create_profile(real["id"])
    payload = create_order_payload(FAKE_UUID, profile["id"], garment_type="SHIRT",
                                   base_labor_cents=20000, fabric_meters_required=3.0)
    res = api.create_order(payload, SA)
    validate_error(res, "ERR_CUSTOMER_NOT_FOUND")


def test_list_customers_pagination_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the count of matching resources before pagination".

    Design: Corner/entities/list_customers_pagination_envelope
    """
    create_customer()
    create_customer()
    data, meta = validate_paginated(api.list_customers(SA))
    assert meta["total_count"] >= 2
    assert isinstance(data, list)


# ─── Queue B: validations corners ───────────────────────────────────────

def test_profile_customer_mismatch_on_order_create(api):
    """PRD §3.2: "The referenced measurement profile must belong to the same customer named by `customer_id`; if it belongs to a different customer the creation is rejected with `ERR_PROFILE_CUSTOMER_MISMATCH`."

    Design: Corner/validations/profile_customer_mismatch_on_order_create
    """
    owner = create_customer()
    profile_a = create_profile(owner["id"])
    other = create_customer()
    payload = create_order_payload(other["id"], profile_a["id"], garment_type="SHIRT",
                                   base_labor_cents=20000, fabric_meters_required=3.0)
    res = api.create_order(payload, SA)
    validate_error(res, "ERR_PROFILE_CUSTOMER_MISMATCH")


def test_scan_ref_required_when_body_scan(api):
    """PRD §3.1: "When `source` is `BODY_SCAN`, a `body_scan_ref` (an opaque scan asset reference) is required; when `source` is `MANUAL`, `body_scan_ref` must be absent."
    PRD §3.1: "A request that supplies a body-scan source without a reference, or a manual source with a reference present, is rejected with `ERR_SCAN_REF_REQUIRED`."

    Design: Corner/validations/scan_ref_required_when_body_scan
    """
    customer = create_customer()
    payload = create_measurement_profile_payload(customer["id"], source="BODY_SCAN")
    res = api.create_measurement_profile(payload, SA)
    validate_error(res, "ERR_SCAN_REF_REQUIRED")


def test_discontinued_fabric_on_option_line_rejected(api):
    """PRD §3.2: "The referenced fabric must be `AVAILABLE` at the moment the line is created; a line against a discontinued fabric is rejected with `ERR_FABRIC_DISCONTINUED`."

    Design: Corner/validations/discontinued_fabric_on_option_line_rejected
    """
    customer = create_customer()
    profile = create_profile(customer["id"])
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=50)
    get_success_data(api.update_fabric(fabric["id"], {"status": "DISCONTINUED"}, SM))
    order = get_success_data(api.create_order(
        create_order_payload(customer["id"], profile["id"], garment_type="SUIT",
                             base_labor_cents=40000, fabric_meters_required=7.0), SA))
    res = api.create_option_line(order["id"], create_option_line_payload(fabric["id"], "MONOGRAM"), SA)
    validate_error(res, "ERR_FABRIC_DISCONTINUED")


def test_confirm_with_insufficient_fabric_rejected(api):
    """PRD §3.3: "the selected fabric's `bolt_meters_remaining` must be at least the order's `fabric_meters_required` (otherwise `ERR_FABRIC_INSUFFICIENT`, HTTP 409)".

    Bolt 5m, order needs 7.0m -> confirm rejected, order stays DRAFT.

    Design: Corner/validations/confirm_with_insufficient_fabric_rejected
    """
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=5)
    bundle = create_draft_order(option_codes=("MONOGRAM",), fabric=fabric,
                                base_labor_cents=40000, fabric_meters_required=7.0,
                                bolt_meters_initial=5)
    res = api.confirm_order(bundle["order"]["id"], SA)
    validate_error(res, "ERR_FABRIC_INSUFFICIENT")
    after = get_success_data(api.get_order(bundle["order"]["id"], SA))
    assert after["status"] == "DRAFT"


# ─── Queue B: rbac corners ──────────────────────────────────────────────

def test_customer_cannot_confirm_order(api):
    """PRD §2.1: "When the headers are well-formed and the role is known, but that role is not permitted to perform the requested operation, the request is rejected instead with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4 endpoint table: POST /orders/{id}/confirm is authorized for SalesAssociate,
    ShopManager.

    A Customer calling confirm -> 403 ERR_INSUFFICIENT_PERMISSIONS; order stays DRAFT.

    Design: Corner/rbac/customer_cannot_confirm_order
    """
    from test_helpers import make_customer_headers
    customer = create_customer()
    cust_headers = make_customer_headers(customer["id"])
    profile = get_success_data(api.create_measurement_profile(
        create_measurement_profile_payload(customer["id"]), cust_headers))
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=50)
    order = get_success_data(api.create_order(
        create_order_payload(customer["id"], profile["id"], garment_type="SUIT",
                             base_labor_cents=40000, fabric_meters_required=7.0), cust_headers))
    get_success_data(api.create_option_line(
        order["id"], create_option_line_payload(fabric["id"], "MONOGRAM"), cust_headers))

    res = api.confirm_order(order["id"], cust_headers)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")
    after = get_success_data(api.get_order(order["id"], SA))
    assert after["status"] == "DRAFT"


def test_sales_associate_cannot_create_fabric(api):
    """PRD §4 endpoint table: POST /fabrics is authorized for ShopManager only.
    PRD §2.1: "that role is not permitted to perform the requested operation, the request is rejected instead with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/sales_associate_cannot_create_fabric
    """
    res = api.create_fabric(create_fabric_payload(name="Wool SA"), SA)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")


def test_unknown_role_rejected_with_auth_error(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` names a role the system does not recognize, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 401)."

    An unknown X-User-Role -> 401 before any other check.

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    from test_helpers import build_user_headers
    ghost = build_user_headers("ghost-1", "Ghost")
    res = api.create_customer(create_customer_payload(full_name="No Auth"), ghost)
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
