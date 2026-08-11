"""Quality-gate segregation of duties and railcar departure guards."""
from test_helpers import (
    ApiErrorId, TEST_USERS, add_car_with_inspection, api_client,
    complete_current_wo, create_railcar, create_wo_for_car,
    make_quality_inspector_headers, make_repair_foreman_headers,
    scenario_authorized_wo, set_clock, setup_shop_ctx, start_current_wo,
    assign_slot_current_wo, validate_error, validate_success,
)

ADMIN = TEST_USERS["shop_admin"]
YARD = TEST_USERS["yard_clerk"]
INSPECTOR = TEST_USERS["car_inspector"]
FOREMAN = "foreman-1"


def test_qa_review_by_creator_returns_segregation_error():
    """PRD §3.5: "Segregation of duties is enforced: the reviewer's `X-User-ID`
    must differ from the work order's `created_by_user_id`, or the review is
    rejected with `ERR_SEGREGATION_OF_DUTIES` (403)."

    Design: Corner/state_machines/qa_review_by_creator_returns_segregation_error
    """
    ctx = scenario_authorized_wo()
    assign_slot_current_wo(ctx)
    start_current_wo(ctx)
    complete_current_wo(ctx, actual_hours=1.5)
    # Reviewer carries the creator's opaque id — same person, different role.
    resp = api_client.qa_review_work_order(
        ctx["wo"]["id"], {"result": "PASS"}, make_quality_inspector_headers(FOREMAN))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
    wo = validate_success(api_client.get_work_order(ctx["wo"]["id"], ADMIN))
    assert wo["exec_status"] == "QA_REVIEW", "rejected review leaves the gate pending"


def test_depart_from_departed_returns_invalid_state():
    """PRD §2.12: "eighth whether the target resource is in a from-state of the
    requested transition (else `ERR_INVALID_STATE_TRANSITION`, 409)".
    PRD §3.6: "When actual hours minus shop delay is less than or equal to the
    free allowance the charge is exactly zero — only a strictly greater excess
    bills."

    Design: Corner/state_machines/depart_from_departed_returns_invalid_state
    """
    ctx = setup_shop_ctx()
    car = create_railcar(ctx["shop"]["id"], ctx["owner"]["id"], ctx["line"]["id"],
                         car_number="4003")
    set_clock("2026-05-02T08:00:00Z")
    departed = validate_success(api_client.depart_railcar(car["id"], YARD))
    assert departed["dwell_charge_cents"] == 0, "24h is within the 48h free allowance"
    resp = api_client.depart_railcar(car["id"], YARD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
    car_now = validate_success(api_client.get_railcar(car["id"], ADMIN))
    assert car_now["status"] == "DEPARTED"
    assert car_now["dwell_charge_cents"] == 0, "a rejected depart must not recompute dwell"


def test_depart_blocked_by_condemnable_defect_then_released():
    """PRD §3.6: "the safety gate forbids departure while any finding on the
    car's inspections has `severity` `CONDEMNABLE` and a status outside
    `REPAIRED` or `DECLINED`; a blocked departure is rejected with
    `ERR_UNRESOLVED_SAFETY_DEFECT`."
    PRD §3.2: "A finding that no repair line references may also be declined by
    a `RepairForeman`, moving the defect addressed by `defectId` from `OPEN` to
    `DECLINED`".

    Design: Corner/state_machines/depart_blocked_by_condemnable_defect_then_released
    """
    ctx = setup_shop_ctx()
    add_car_with_inspection(
        ctx, car_number="4007",
        defects=[{"aar_defect_code": "AAR-2001", "defect_group": "WHEELSET",
                  "cause_code": "WEAR", "severity": "CONDEMNABLE", "location": "L1"}])
    resp = api_client.depart_railcar(ctx["car"]["id"], YARD)
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_SAFETY_DEFECT, expected_status=409)

    declined = validate_success(api_client.decline_defect(
        ctx["inspection"]["id"], ctx["defects"][0]["id"],
        make_repair_foreman_headers(FOREMAN)))
    assert declined["status"] == "DECLINED"

    departed = validate_success(api_client.depart_railcar(ctx["car"]["id"], YARD))
    assert departed["status"] == "DEPARTED"


def test_depart_blocked_by_open_work_order():
    """PRD §3.6: "From `ARRIVED`, departure additionally requires that no work
    order of the car remains outside `COMPLETED` or `CANCELLED` — a car with
    open work cannot leave, and the attempt is rejected with
    `ERR_OPEN_WORK_ORDERS`."

    Design: Corner/state_machines/depart_blocked_by_open_work_order
    """
    ctx = setup_shop_ctx()
    add_car_with_inspection(ctx, car_number="4008", defects=[])
    create_wo_for_car(ctx, routing="SHOP")
    resp = api_client.depart_railcar(ctx["car"]["id"], YARD)
    validate_error(resp, ApiErrorId.ERR_OPEN_WORK_ORDERS, expected_status=409)
    car = validate_success(api_client.get_railcar(ctx["car"]["id"], ADMIN))
    assert car["status"] == "ARRIVED", "blocked departure leaves the car ARRIVED"
