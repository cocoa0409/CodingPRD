"""Cross-entity state dependencies: WorkOrder x Inspection, BRC x WorkOrder."""
from test_helpers import (
    ApiErrorId, TEST_USERS, add_car_with_inspection, add_price_entry, api_client,
    assign_slot_current_wo, authorize_current_wo, build_work_order,
    get_work_order, make_repair_foreman_headers, scenario_authorized_wo,
    setup_shop_ctx, start_current_wo, submit_current_wo, validate_error,
    validate_paginated, validate_success,
)

ADMIN = TEST_USERS["shop_admin"]
BILLING = TEST_USERS["billing_clerk"]
FOREMAN = "foreman-1"


def test_submit_blocked_after_inspection_reopened():
    """PRD §3.3: "the source inspection must still be `COMPLETED` — an
    inspection reopened after lines were drafted blocks submission with
    `ERR_INSPECTION_NOT_COMPLETED`".

    Design: Difficulty/cross_entity_state_dependency/wo_submit_blocked_when_inspection_reopened
    """
    ctx = setup_shop_ctx()
    add_price_entry(ctx)
    add_car_with_inspection(ctx, car_number="1414")
    build_work_order(ctx)
    # The order is still DRAFT, so the inspection lock does not apply to reopen.
    reopened = validate_success(api_client.reopen_inspection(
        ctx["inspection"]["id"], make_repair_foreman_headers(FOREMAN)))
    assert reopened["status"] == "REOPENED"
    assert reopened["reopened_count"] == 1

    resp = api_client.submit_work_order(ctx["wo"]["id"],
                                        make_repair_foreman_headers(FOREMAN))
    validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_COMPLETED, expected_status=409)


def test_blocked_submit_leaves_work_order_in_draft():
    """PRD §3.3: "Submission moves `auth_status` from `DRAFT` to
    `PENDING_AUTHORIZATION` and is itself guarded: the work order must still be
    `DRAFT`, the source inspection must still be `COMPLETED`".

    Design: Difficulty/cross_entity_state_dependency/wo_submit_blocked_when_inspection_reopened
    """
    ctx = setup_shop_ctx()
    add_price_entry(ctx)
    add_car_with_inspection(ctx, car_number="1415")
    build_work_order(ctx)
    validate_success(api_client.reopen_inspection(
        ctx["inspection"]["id"], make_repair_foreman_headers(FOREMAN)))
    resp = api_client.submit_work_order(ctx["wo"]["id"],
                                        make_repair_foreman_headers(FOREMAN))
    validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_COMPLETED, expected_status=409)
    wo = validate_success(api_client.get_work_order(ctx["wo"]["id"], ADMIN))
    assert wo["auth_status"] == "DRAFT", "a rejected submit never leaves DRAFT"
    insp = validate_success(api_client.get_inspection(ctx["inspection"]["id"], ADMIN))
    assert insp["status"] == "REOPENED"
    assert insp["reopened_count"] == 1


def test_brc_create_blocked_until_work_order_completed():
    """PRD §3.7: "Drafting requires the work order's execution to be
    `COMPLETED` — otherwise `ERR_WORK_ORDER_NOT_COMPLETED`".

    Design: Difficulty/cross_entity_state_dependency/brc_create_blocked_until_work_order_completed
    """
    ctx = scenario_authorized_wo()
    assign_slot_current_wo(ctx)
    start_current_wo(ctx)
    assert ctx["wo"]["exec_status"] == "IN_PROGRESS"
    wo = get_work_order(ctx["wo"]["id"])
    resp = api_client.create_billing_repair_card(
        {"work_order_id": wo["id"], "expected_work_order_version": wo["version"]},
        BILLING)
    validate_error(resp, ApiErrorId.ERR_WORK_ORDER_NOT_COMPLETED, expected_status=409)


def test_rejected_brc_create_persists_nothing_and_preserves_version():
    """PRD §3.7: "Drafting requires the work order's execution to be
    `COMPLETED` — otherwise `ERR_WORK_ORDER_NOT_COMPLETED`".

    Design: Difficulty/cross_entity_state_dependency/brc_create_blocked_until_work_order_completed
    """
    ctx = scenario_authorized_wo()
    assign_slot_current_wo(ctx)
    start_current_wo(ctx)
    wo_before = get_work_order(ctx["wo"]["id"])
    resp = api_client.create_billing_repair_card(
        {"work_order_id": wo_before["id"],
         "expected_work_order_version": wo_before["version"]}, BILLING)
    validate_error(resp, ApiErrorId.ERR_WORK_ORDER_NOT_COMPLETED, expected_status=409)
    _data, meta = validate_paginated(
        api_client.list_billing_repair_cards(
            ADMIN, params={"work_order_id": wo_before["id"]}))
    assert meta["total_count"] == 0, "no draft card is created"
    wo_after = get_work_order(ctx["wo"]["id"])
    assert wo_after["version"] == wo_before["version"], (
        "a rejected draft creation must not bump the work order version")
