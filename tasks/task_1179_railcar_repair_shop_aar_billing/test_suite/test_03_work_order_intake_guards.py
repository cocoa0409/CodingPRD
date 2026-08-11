"""Work-order intake guards: payload validity, inspection state, lines, locks."""
from test_helpers import (
    ApiErrorId, TEST_USERS, add_car_with_inspection, add_defect, add_price_entry,
    api_client, build_work_order, complete_inspection, create_wo_for_car,
    create_work_order_payload, open_inspection, setup_shop_ctx, submit_current_wo,
    validate_error, validate_paginated, validate_success,
    make_repair_foreman_headers,
)

ADMIN = TEST_USERS["shop_admin"]
YARD = TEST_USERS["yard_clerk"]
INSPECTOR = TEST_USERS["car_inspector"]
FOREMAN = "foreman-1"


def test_work_order_create_invalid_enum_routing():
    """PRD §2.12: "A malformed body, a missing required field, an invalid enum
    literal, a negative or zero quantity, or a slot whose `ends_at` is not
    after its `starts_at` is rejected with `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/work_order_create_invalid_enum_routing
    """
    ctx = setup_shop_ctx()
    add_car_with_inspection(ctx, car_number="2001", defects=[])
    car = validate_success(api_client.get_railcar(ctx["car"]["id"], ADMIN))
    resp = api_client.create_work_order(
        create_work_order_payload(ctx["car"]["id"], ctx["inspection"]["id"],
                                  car["version"], routing="AIR"),
        make_repair_foreman_headers(FOREMAN))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_wo_create_requires_completed_inspection():
    """PRD §3.3: "Creation is refused when the day's posture is `FULL`
    (`ERR_SHOP_AT_CAPACITY`), when the referenced inspection is not `COMPLETED`
    (`ERR_INSPECTION_NOT_COMPLETED`), or when the railcar version is stale."

    Design: Corner/validations/wo_create_requires_completed_inspection
    """
    ctx = setup_shop_ctx()
    add_car_with_inspection(ctx, car_number="6005", defects=[], complete=False)
    assert ctx["inspection"]["status"] == "IN_PROGRESS"
    resp = api_client.create_work_order(
        create_work_order_payload(ctx["car"]["id"], ctx["inspection"]["id"],
                                  ctx["car"]["version"]),
        make_repair_foreman_headers(FOREMAN))
    validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_COMPLETED, expected_status=409)
    _data, meta = validate_paginated(
        api_client.list_work_orders(ADMIN, params={"railcar_id": ctx["car"]["id"]}))
    assert meta["total_count"] == 0, "rejected create must not persist a work order"


def test_submit_work_order_with_no_lines_rejected():
    """PRD §3.3: "at least one line must exist (`ERR_WORK_ORDER_NO_LINES`)".

    Design: Corner/errors/submit_work_order_with_no_lines_rejected
    """
    ctx = setup_shop_ctx()
    add_car_with_inspection(ctx, car_number="9101", defects=[])
    build_work_order(ctx, lines=[])
    resp = api_client.submit_work_order(ctx["wo"]["id"],
                                        make_repair_foreman_headers(FOREMAN))
    validate_error(resp, ApiErrorId.ERR_WORK_ORDER_NO_LINES, expected_status=409)
    wo = validate_success(api_client.get_work_order(ctx["wo"]["id"], ADMIN))
    assert wo["auth_status"] == "DRAFT", "rejected submit leaves the order in DRAFT"


def test_inspection_reopen_locked_by_pending_work_order():
    """PRD §3.2: "A `RepairForeman` may later reopen a `COMPLETED` inspection —
    provided no work order referencing it is currently `PENDING_AUTHORIZATION`
    or `AUTHORIZED`, a lock whose violation is rejected with
    `ERR_INSPECTION_LOCKED`".

    Design: Corner/state_machines/inspection_reopen_locked_by_pending_work_order
    """
    ctx = setup_shop_ctx()
    add_price_entry(ctx)
    add_car_with_inspection(ctx, car_number="4001")
    build_work_order(ctx)
    submit_current_wo(ctx)
    resp = api_client.reopen_inspection(ctx["inspection"]["id"],
                                        make_repair_foreman_headers(FOREMAN))
    validate_error(resp, ApiErrorId.ERR_INSPECTION_LOCKED, expected_status=409)
    insp = validate_success(api_client.get_inspection(ctx["inspection"]["id"], ADMIN))
    assert insp["status"] == "COMPLETED", "locked inspection must stay COMPLETED"
