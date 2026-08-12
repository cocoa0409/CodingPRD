"""Validation-order conflicts resolved by the PRD's fixed evaluation order."""
from test_helpers import (
    ApiErrorId, TEST_USERS, add_car_with_inspection, add_price_entry, api_client,
    authorize_current_wo, build_work_order, counter_item,
    create_brc_for_current_wo, create_slot, get_railcar, list_brc_lines,
    make_car_owner_rep_headers, make_repair_foreman_headers,
    run_wo_to_completed, scenario_completed_wo, setup_shop_ctx,
    submit_current_wo, validate_error, validate_paginated, validate_success,
)

ADMIN = TEST_USERS["shop_admin"]
FOREMAN = "foreman-1"


def test_state_error_beats_fiscal_ceiling_on_counter_create():
    """PRD §2.12: "eighth whether the target resource is in a from-state of the
    requested transition (else `ERR_INVALID_STATE_TRANSITION`, 409)".
    PRD §2.12: "and fourteenth the fiscal ceilings
    (`ERR_COUNTER_BILL_EXCEEDS_CEILING`, `ERR_CREDIT_EXCEEDS_REMAINING`, both
    409)."
    PRD §3.8: "Either responsible party may file a counter-bill against a card
    in `SUBMITTED` or `DISPUTED`".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_counter_create
    """
    ctx = scenario_completed_wo(actual_hours=1.5)
    create_brc_for_current_wo(ctx)  # left in DRAFT, never submitted
    lines = list_brc_lines(ctx["brc"]["id"])
    resp = api_client.create_counter_bill(
        ctx["brc"]["id"],
        {"items": [counter_item(lines[0]["id"], 999999, "over everything")]},
        make_car_owner_rep_headers(ctx["owner"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)


def test_rejected_counter_create_leaves_no_trace():
    """PRD §3.8: "Either responsible party may file a counter-bill against a
    card in `SUBMITTED` or `DISPUTED`".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_counter_create
    """
    ctx = scenario_completed_wo(actual_hours=1.5)
    create_brc_for_current_wo(ctx)
    lines = list_brc_lines(ctx["brc"]["id"])
    resp = api_client.create_counter_bill(
        ctx["brc"]["id"],
        {"items": [counter_item(lines[0]["id"], 999999, "over everything")]},
        make_car_owner_rep_headers(ctx["owner"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
    _data, meta = validate_paginated(
        api_client.list_counter_bills(ctx["brc"]["id"], ADMIN))
    assert meta["total_count"] == 0, "the rejected filing creates no counter-bill"
    brc = validate_success(api_client.get_billing_repair_card(ctx["brc"]["id"], ADMIN))
    assert brc["status"] == "DRAFT"


def test_slot_overlap_beats_window_too_short_on_assign():
    """PRD §2.12: "twelfth the temporal rules (`ERR_SLOT_OVERLAP`,
    `ERR_SLOT_IN_PAST`, `ERR_PRICE_WINDOW_OVERLAP`,
    `ERR_COUNTER_BILL_WINDOW_CLOSED`, `ERR_WARRANTY_WINDOW_EXPIRED`, all 409);
    thirteenth the business constraints (`ERR_SHOP_AT_CAPACITY`,
    `ERR_SLOT_WINDOW_TOO_SHORT`, `ERR_MOBILE_ROUTE_NOT_ELIGIBLE`,
    `ERR_PART_STOCK_INSUFFICIENT`, `ERR_BRC_ALREADY_ACTIVE`,
    `ERR_COUNTER_BILL_ACTIVE`, `ERR_WARRANTY_CLAIM_ACTIVE`,
    `ERR_WARRANTY_NOT_APPLICABLE`, `ERR_DUPLICATE_PART_NUMBER`,
    `ERR_DUPLICATE_WHEELSET_SERIAL`, `ERR_WORK_ORDER_NO_LINES`, all 409)".
    PRD §3.5: "its half-open window must not overlap any other slot on the same
    stall that is `RESERVED` or `OCCUPIED`".

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_assign_slot
    """
    ctx = setup_shop_ctx(clock="2026-05-01T08:00:00Z")
    add_price_entry(ctx, job_code="J-WHEEL-REPL", description="Wheelset replacement",
                    labor_rate_cents_per_hour=12000, mobile_labor_rate_cents_per_hour=15000,
                    standard_labor_hours=4.0, mobile_trip_surcharge_cents=25000,
                    mobile_eligible=False)
    add_car_with_inspection(ctx, car_number="1111", defects=[
        {"aar_defect_code": "AAR-2001", "defect_group": "WHEELSET",
         "cause_code": "WEAR", "severity": "CONDEMNABLE", "location": "L1 wheel"},
        {"aar_defect_code": "AAR-2002", "defect_group": "WHEELSET",
         "cause_code": "WEAR", "severity": "CONDEMNABLE", "location": "R1 wheel"},
    ])
    slot_x = create_slot(ctx["shop"]["id"], starts_at="2026-05-02T08:00:00Z",
                         ends_at="2026-05-02T16:00:00Z")
    slot_y = create_slot(ctx["shop"]["id"], starts_at="2026-05-02T10:00:00Z",
                         ends_at="2026-05-02T12:00:00Z")

    build_work_order(ctx, lines=[{"job_code": "J-WHEEL-REPL", "defect_index": 0}])
    submit_current_wo(ctx)
    authorize_current_wo(ctx)
    resp = api_client.assign_slot(ctx["wo"]["id"], {"slot_id": slot_x["id"]},
                                  make_repair_foreman_headers(FOREMAN))
    validate_success(resp)

    build_work_order(ctx, lines=[{"job_code": "J-WHEEL-REPL", "defect_index": 1}])
    submit_current_wo(ctx)
    authorize_current_wo(ctx)
    wo2_id = ctx["wo"]["id"]

    # Slot Y both overlaps reserved slot X and is shorter than the 4.0
    # standard hours of the job: the temporal error must surface first.
    resp = api_client.assign_slot(wo2_id, {"slot_id": slot_y["id"]},
                                  make_repair_foreman_headers(FOREMAN))
    validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP, expected_status=409)


def test_rejected_assign_leaves_order_and_slot_untouched():
    """PRD §3.5: "Success moves `exec_status` `NOT_STARTED` → `SHOP_QUEUED`,
    moves the slot `OPEN` → `RESERVED`".

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_assign_slot
    """
    ctx = setup_shop_ctx(clock="2026-05-01T08:00:00Z")
    add_price_entry(ctx, job_code="J-WHEEL-REPL", description="Wheelset replacement",
                    labor_rate_cents_per_hour=12000, mobile_labor_rate_cents_per_hour=15000,
                    standard_labor_hours=4.0, mobile_trip_surcharge_cents=25000,
                    mobile_eligible=False)
    add_car_with_inspection(ctx, car_number="1112", defects=[
        {"aar_defect_code": "AAR-2001", "defect_group": "WHEELSET",
         "cause_code": "WEAR", "severity": "CONDEMNABLE", "location": "L1 wheel"},
        {"aar_defect_code": "AAR-2002", "defect_group": "WHEELSET",
         "cause_code": "WEAR", "severity": "CONDEMNABLE", "location": "R1 wheel"},
    ])
    slot_x = create_slot(ctx["shop"]["id"], starts_at="2026-05-02T08:00:00Z",
                         ends_at="2026-05-02T16:00:00Z")
    slot_y = create_slot(ctx["shop"]["id"], starts_at="2026-05-02T10:00:00Z",
                         ends_at="2026-05-02T12:00:00Z")
    build_work_order(ctx, lines=[{"job_code": "J-WHEEL-REPL", "defect_index": 0}])
    submit_current_wo(ctx)
    authorize_current_wo(ctx)
    validate_success(api_client.assign_slot(ctx["wo"]["id"], {"slot_id": slot_x["id"]},
                                            make_repair_foreman_headers(FOREMAN)))
    build_work_order(ctx, lines=[{"job_code": "J-WHEEL-REPL", "defect_index": 1}])
    submit_current_wo(ctx)
    authorize_current_wo(ctx)
    wo2_id = ctx["wo"]["id"]

    resp = api_client.assign_slot(wo2_id, {"slot_id": slot_y["id"]},
                                  make_repair_foreman_headers(FOREMAN))
    validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP, expected_status=409)
    wo2 = validate_success(api_client.get_work_order(wo2_id, ADMIN))
    assert wo2["exec_status"] == "NOT_STARTED", "a rejected assign leaves the order queued-off"
    slot = validate_success(api_client.get_shop_slot(slot_y["id"], ADMIN))
    assert slot["status"] == "OPEN", "a rejected assign leaves the slot OPEN"
