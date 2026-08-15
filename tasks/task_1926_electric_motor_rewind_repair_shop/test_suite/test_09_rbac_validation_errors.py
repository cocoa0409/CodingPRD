"""Auth/RBAC denials, the global validation order, field-shape violations, the
core-loss release veto, and list pagination/filtering (PRD §2.1, §2.3, §2.7,
§2.11, §3.2, §3.5)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_customer,
    create_diagnosis_payload,
    create_motor,
    create_quote_issue_payload,
    create_shop,
    create_work_order_payload,
    get_work_order_version,
    intake_work_order,
    make_customer_headers,
    record_core_loss_test,
    record_incoming_test,
    setup_diagnosed_work_order,
    setup_final_test_work_order,
    setup_shop_customer_motor,
    setup_work_order_intake,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["shop_admin_headers"]
MANAGER = TEST_USERS["service_manager_headers"]
TECH = TEST_USERS["technician_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]


def test_missing_auth_headers_returns_400(api):
    """PRD §2.1: "A request with either header missing, or with a role the
    system does not recognize, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_headers_returns_400
    """
    shop = create_shop()
    res = api.get_shop(shop["id"], headers={"X-User-ID": "test-admin-1"})
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", expected_status=400)


def test_nonexistent_work_order_returns_404(api):
    """PRD §2.7: "the first identifier that does not resolve yields
    `ERR_NOT_FOUND` (HTTP 404) without evaluating the rest of the path."

    Design: Corner/validations/nonexistent_work_order_returns_404
    """
    shop = create_shop()
    res = api.get_work_order(shop["id"], NON_EXISTENT_UUID, MANAGER)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_work_order_create_with_dangling_motor_reference(api):
    """PRD §3.2: "a payload naming the `customer_id` and the `motor_id`;
    either reference failing to resolve is rejected with
    `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/validations/work_order_create_with_dangling_motor_reference
    """
    bundle = setup_shop_customer_motor()
    res = api.create_work_order(
        bundle["shop"]["id"],
        create_work_order_payload(bundle["customer"]["id"], NON_EXISTENT_UUID, priority="STANDARD"),
        TECH,
    )
    validate_error(res, "ERR_REFERENCE_NOT_FOUND", expected_status=422)


def test_diagnose_with_zero_rewind_hours_returns_invalid_input(api):
    """PRD §3.2: "Violations of the input shape — non-positive `rewind_hours`
    or `replacement_cost_cents`, negative `materials_cents` — surface as
    `ERR_INVALID_INPUT`."

    Design: Corner/validations/diagnose_with_zero_rewind_hours_returns_invalid_input
    """
    bundle = setup_work_order_intake()
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]
    record_incoming_test(shop_id, wo_id)

    res = api.diagnose_work_order(
        shop_id, wo_id, create_diagnosis_payload(rewind_hours=0), TECH
    )
    validate_error(res, "ERR_INVALID_INPUT", expected_status=400)


def test_error_priority_existence_beats_state(api):
    """PRD §2.11: "The order is: first the presence and validity of the
    user-context headers; then role authorization for the target endpoint;
    then existence and parent-chain ownership of every path identifier,
    validated left to right; then resolution of foreign keys carried in the
    request body, such as the `motor_id` and `customer_id` on work-order
    intake or the `work_order_id` and `spare_motor_id` on pool checkout,
    rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 422); then whether the
    target entity sits in a valid from-state for the requested transition,
    rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/validations/error_priority_existence_beats_state
    """
    shop = create_shop()
    res = api.diagnose_work_order(
        shop["id"], NON_EXISTENT_UUID, create_diagnosis_payload(), TECH
    )
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_technician_cannot_issue_quote(api):
    """PRD §2.1: "A request whose role is recognized but not permitted on the
    target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."
    PRD §2.1: "`Estimator` issues, sends, and revises quotes."

    Design: Corner/rbac/technician_cannot_issue_quote
    """
    bundle = setup_diagnosed_work_order()
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]
    version = get_work_order_version(shop_id, wo_id)

    res = api.issue_quote(shop_id, wo_id, create_quote_issue_payload(version), TECH)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


def test_customer_cannot_record_tests_or_release(api):
    """PRD §2.1: "A request whose role is recognized but not permitted on the
    target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."
    PRD §2.1: "`Technician` is the test technician responsible for intake,
    incoming/core-loss/final test records, and diagnosis."

    Design: Corner/rbac/customer_cannot_record_tests_or_release
    """
    bundle = setup_work_order_intake()
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]
    as_customer = make_customer_headers(bundle["customer"]["id"])

    res1 = api.record_test(shop_id, wo_id, {"kind": "INCOMING", "insulation_megohms": 500}, as_customer)
    validate_error(res1, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
    res2 = api.release_work_order(shop_id, wo_id, as_customer)
    validate_error(res2, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


def test_shop_admin_cannot_perform_operations_only_config(api):
    """PRD §2.1: "`ShopAdmin` is the shop owner or administrator: it alone
    configures the service center and drives the test clock, and it has read
    access to everything."
    PRD §2.1: "A request whose role is recognized but not permitted on the
    target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."

    Design: Corner/rbac/shop_admin_cannot_perform_operations_only_config
    """
    shop = create_shop()
    res = api.create_customer(shop["id"], {"company_name": "C"}, ADMIN)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


def test_core_loss_fail_vetoes_release_despite_final_pass(api):
    """PRD §3.5: "Two gates guard it, and a violation of either is rejected
    with `ERR_FINAL_TEST_NOT_PASS` (HTTP 409): the latest final test record's
    verdict must be `PASS`, and if any core-loss test record exists for the
    order its verdict must also be `PASS`."

    Design: Corner/errors/err_final_test_not_pass_direct
    """
    bundle = setup_final_test_work_order(
        core_loss_watts=3800,  # 3800/75000 > 5% -> FAIL
        vibration_mm_s=2.0,    # FINAL verdict PASS
        motor_overrides={"rated_kw": 75, "frame_mm": 200, "manufacture_year": 2020},
    )
    assert bundle["work_order"]["status"] == "FINAL_TEST"

    res = api.release_work_order(bundle["shop"]["id"], bundle["work_order"]["id"], MANAGER)
    validate_error(res, "ERR_FINAL_TEST_NOT_PASS", expected_status=409)


def test_list_work_orders_pagination_and_filter(api):
    """PRD §2.3: "`limit` caps the number of items returned; it defaults to
    10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Paginated list responses carry `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope."
    PRD §3.2: "The work-order list filters by `customer_id`, `status`, and
    `priority`."

    Design: Corner/endpoints/list_work_orders_pagination_and_filter
    """
    bundle = setup_shop_customer_motor()
    shop_id, cust_id = bundle["shop"]["id"], bundle["customer"]["id"]
    motor2 = create_motor(shop_id, cust_id, serial_number="M-L2")
    wo1 = intake_work_order(shop_id, cust_id, bundle["motor"]["id"], "STANDARD")
    wo2 = intake_work_order(shop_id, cust_id, motor2["id"], "RUSH")

    res = api.list_work_orders(shop_id, MANAGER, params={"status": "INTAKE", "limit": 1, "offset": 0})
    body = res.json()
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["response_type"] == "array"
    data, meta = validate_paginated(res)
    assert len(data) == 1
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert data[0]["status"] == "INTAKE"

    # The status filter narrows the set once one order leaves INTAKE.
    record_incoming_test(shop_id, wo1["id"])  # wo1 -> INCOMING_TEST
    data2, meta2 = validate_paginated(
        api.list_work_orders(shop_id, MANAGER, params={"status": "INTAKE"})
    )
    assert meta2["total_count"] == 1
    assert [wo["id"] for wo in data2] == [wo2["id"]]
