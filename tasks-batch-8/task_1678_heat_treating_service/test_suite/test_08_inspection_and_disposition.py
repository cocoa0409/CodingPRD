"""Hardness inspection, disposition of failed lots, segregation of duties,
and the re-treat cycle (PRD §3.5, §3.6, §3.7, §3.8)."""
from test_helpers import (
    USER_QUALITY_ENGINEER,
    USER_QUALITY_ENGINEER_2,
    ApiErrorId,
    TEST_USERS,
    assert_inspection_test,
    assign_order,
    create_approved_recipe,
    create_customer,
    create_load,
    create_work_order,
    decide_case,
    get_disposition_case,
    get_open_case_for_order,
    get_work_order,
    list_disposition_cases,
    make_quality_engineer_headers,
    process_order_to_processed,
    record_inspection,
    retreat_order_once,
    run_load_to_completed,
    setup_failed_order,
    setup_shop,
    validate_error,
    validate_success,
)

CSR = TEST_USERS["customer_service_rep"]
SCHED = TEST_USERS["shop_scheduler"]
QE = TEST_USERS["quality_engineer"]  # qe-1
QE2 = TEST_USERS["quality_engineer_2"]  # qe-2


# ---------------------------------------------------------------------------
# Corner: state_machines / test_before_processed_returns_not_testable
# ---------------------------------------------------------------------------

def test_before_processed_returns_not_testable(api):
    """PRD §3.7: "An empty readings array is rejected with
    `ERR_INVALID_REQUEST`, and testing an order whose `processing_status` is
    not `PROCESSED` or whose `quality_status` is not `PENDING_TEST` fails with
    `ERR_WORK_ORDER_NOT_TESTABLE` (HTTP 409)."

    Design: Corner/state_machines/test_before_processed_returns_not_testable
    """
    customer = create_customer(name="Early Co")
    recipe = create_approved_recipe()
    order = create_work_order(customer["id"], recipe["id"])
    assert order["processing_status"] == "RECEIVED"
    res = api.create_inspection_test(
        {
            "work_order_id": order["id"],
            "hardness_readings": [40, 42, 41],
            "measured_distortion_in": 0.004,
        },
        QE,
    )
    validate_error(res, ApiErrorId.ERR_WORK_ORDER_NOT_TESTABLE.value)


# ---------------------------------------------------------------------------
# Corner: state_machines / inspection_fail_creates_open_disposition_case
# ---------------------------------------------------------------------------

def test_inspection_fail_creates_open_disposition_case(api):
    """PRD §3.7: "The test outcome cascades into the order's independent
    quality dimension. A `PASS` moves `quality_status` from `PENDING_TEST` to
    `PASSED`. A `FAIL` moves it from `PENDING_TEST` to `FAILED` and opens a
    DispositionCase in `OPEN` status, capturing the failing lot's
    `work_order_id` and the test's `inspection_test_id`."

    Design: Corner/state_machines/inspection_fail_creates_open_disposition_case
    """
    bundle = process_order_to_processed()
    order = bundle["order"]

    test = record_inspection(order["id"], readings=[50, 50])
    assert_inspection_test(test)
    assert test["result"] == "FAIL", "avg 50.0 exceeds hardness_max_hrc 44"
    assert get_work_order(order["id"])["quality_status"] == "FAILED"

    case = get_open_case_for_order(order["id"])
    assert case["status"] == "OPEN"
    assert case["inspection_test_id"] == test["id"]
    assert case["work_order_id"] == order["id"]

    # A PASS outcome opens no case. The second shop needs a distinct
    # (alloy_code, spec_code) pair and furnace_code — PRD §3.2 rejects
    # duplicate pairs and duplicate furnace codes.
    other = process_order_to_processed(
        recipe_overrides={"alloy_code": "8620"},
        furnace_overrides={"furnace_code": "F-2"},
    )
    passing = record_inspection(other["order"]["id"], readings=[40, 42, 41])
    assert passing["result"] == "PASS"
    assert get_work_order(other["order"]["id"])["quality_status"] == "PASSED"
    assert list_disposition_cases(
        params={"work_order_id": other["order"]["id"]}
    ) == []


# ---------------------------------------------------------------------------
# Corner: calculations / hardness_and_distortion_inclusive_boundaries
# ---------------------------------------------------------------------------

def test_hardness_and_distortion_inclusive_boundaries(api):
    """PRD §3.7: "The server records the caller's identity in
    `recorded_by_user_id` and computes two derived values:
    `avg_hardness_hrc`, the mean of `hardness_readings` rounded to one decimal
    place half-up, and `result`, which is `PASS` when the average lies between
    `hardness_min_hrc` and `hardness_max_hrc` inclusive and
    `measured_distortion_in` does not exceed the recipe's
    `fixture_distortion_allowance_in`, and `FAIL` otherwise."

    Design: Corner/calculations/hardness_and_distortion_inclusive_boundaries
    """
    shop = setup_shop()  # band [38, 44], distortion allowance 0.005
    order_a = create_work_order(shop["customer"]["id"], shop["recipe"]["id"])
    order_b = create_work_order(shop["customer"]["id"], shop["recipe"]["id"])
    order_c = create_work_order(shop["customer"]["id"], shop["recipe"]["id"])
    load = create_load(shop["furnace"]["id"], shop["recipe"]["id"])
    assign_order(load["id"], order_a["id"])
    assign_order(load["id"], order_b["id"])
    assign_order(load["id"], order_c["id"])
    run_load_to_completed(load["id"])

    # Average exactly at the inclusive lower band edge passes.
    test_a = record_inspection(order_a["id"], readings=[38, 38])
    assert test_a["avg_hardness_hrc"] == 38.0
    assert test_a["result"] == "PASS"

    # Distortion exactly at the allowance passes.
    test_b = record_inspection(order_b["id"], distortion=0.005)
    assert test_b["result"] == "PASS"

    # Distortion above the allowance fails despite in-band hardness.
    test_c = record_inspection(order_c["id"], readings=[40], distortion=0.006)
    assert test_c["result"] == "FAIL"
    assert get_work_order(order_c["id"])["quality_status"] == "FAILED"
    case = get_open_case_for_order(order_c["id"])
    assert case["inspection_test_id"] == test_c["id"]


# ---------------------------------------------------------------------------
# Corner: state_machines / decide_twice_returns_not_open
# ---------------------------------------------------------------------------

def test_decide_twice_returns_not_open(api):
    """PRD §3.7: "The case must still be `OPEN`, failing with
    `ERR_DISPOSITION_NOT_OPEN` (HTTP 409) otherwise, and the `decision` must
    be one of three values, each with its own cascade."
    PRD §3.7: "`RETURN_AS_IS` waives the failure: `quality_status` moves from
    `FAILED` to `WAIVED` while `processing_status` stays `PROCESSED`, leaving
    the lot shippable. In every branch the server records
    `decided_by_user_id` from the caller's header, and the case moves to
    `DECIDED`, which is terminal."
    PRD §3.8: "Liability claims exist only because a disposition decided
    `SCRAP`; each is created in `PENDING` with `work_order_id` and
    `customer_id` copied from the scrapped order."

    Design: Corner/state_machines/decide_twice_returns_not_open
    """
    bundle = setup_failed_order()
    case = bundle["case"]

    decided = decide_case(case["id"], "RETURN_AS_IS")
    assert decided["status"] == "DECIDED"
    assert decided["decision"] == "RETURN_AS_IS"
    order = get_work_order(bundle["order"]["id"])
    assert order["quality_status"] == "WAIVED"
    assert order["processing_status"] == "PROCESSED"

    res = api.decide_disposition_case(case["id"], {"decision": "SCRAP"}, QE2)
    validate_error(res, ApiErrorId.ERR_DISPOSITION_NOT_OPEN.value)

    # The rejected second decide produces no liability claim.
    claims = validate_success(
        api.list_liability_claims(
            CSR, params={"work_order_id": bundle["order"]["id"]}
        ),
        200,
    )
    assert claims == []


# ---------------------------------------------------------------------------
# Corner: validations / segregation_of_duties_blocks_same_user_decide
# ---------------------------------------------------------------------------

def test_segregation_of_duties_blocks_same_user_decide(api):
    """PRD §3.7: "Disposition is decided by a `QualityEngineer` — but never
    the same one who recorded the failing test: if the decider's `X-User-ID`
    equals the test's `recorded_by_user_id`, the decision is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.7: "The server records the caller's identity in
    `recorded_by_user_id` and computes two derived values:
    `avg_hardness_hrc`, the mean of `hardness_readings` rounded to one decimal
    place half-up, and `result`, which is `PASS` when the average lies between
    `hardness_min_hrc` and `hardness_max_hrc` inclusive and
    `measured_distortion_in` does not exceed the recipe's
    `fixture_distortion_allowance_in`, and `FAIL` otherwise."

    Design: Corner/validations/segregation_of_duties_blocks_same_user_decide
    """
    bundle = setup_failed_order(recipe_overrides={"max_retreats": 2})
    test = bundle["test"]
    case = bundle["case"]
    assert test["recorded_by_user_id"] == USER_QUALITY_ENGINEER

    # The recording engineer cannot decide.
    res = api.decide_disposition_case(
        case["id"], {"decision": "RE_TREAT"},
        make_quality_engineer_headers(USER_QUALITY_ENGINEER),
    )
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert get_disposition_case(case["id"], QE2)["status"] == "OPEN"

    # A different QualityEngineer decides successfully.
    decided = decide_case(case["id"], "RE_TREAT")
    assert decided["status"] == "DECIDED"
    assert decided["decision"] == "RE_TREAT"
    assert decided["decided_by_user_id"] == USER_QUALITY_ENGINEER_2


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / work_order_retreat_cycle
# ---------------------------------------------------------------------------

def test_work_order_retreat_cycle(api):
    """PRD §3.7: "`RE_TREAT` is available only while the order's
    `retreat_count` remains strictly below the recipe's `max_retreats` — once
    the count has reached the cap, a re-treat attempt fails with
    `ERR_RETREAT_LIMIT_REACHED` (HTTP 422); a successful re-treat moves the
    order from `PROCESSED` to `AWAITING_RETREAT`, increments `retreat_count`
    by one, and resets `quality_status` from `FAILED` to `PENDING_TEST`,
    ready to be scheduled onto a new load."
    PRD §3.5: "The order's `processing_status` must be `RECEIVED` or
    `AWAITING_RETREAT` (`ERR_WORK_ORDER_NOT_ASSIGNABLE`, HTTP 409), and the
    order's `recipe_id` must equal the load's `recipe_id`
    (`ERR_RECIPE_MISMATCH`, HTTP 422)."

    Design: Difficulty/non_linear_state_machine/work_order_retreat_cycle
    """
    bundle = setup_failed_order(recipe_overrides={"max_retreats": 2})
    order_id = bundle["order"]["id"]
    shop = bundle["shop"]

    order = retreat_order_once(bundle)
    assert order["processing_status"] == "AWAITING_RETREAT"
    assert order["quality_status"] == "PENDING_TEST"
    assert order["retreat_count"] == 1

    # Second run through the cycle head: AWAITING_RETREAT -> SCHEDULED ->
    # IN_PROCESS -> PROCESSED.
    load2 = create_load(
        shop["furnace"]["id"], shop["recipe"]["id"],
        scheduled_start_at="2026-08-03T08:00:00Z",
        scheduled_end_at="2026-08-03T12:00:00Z",
    )
    assign_order(load2["id"], order_id)
    assert get_work_order(order_id)["processing_status"] == "SCHEDULED"
    run_load_to_completed(load2["id"])
    assert get_work_order(order_id)["processing_status"] == "PROCESSED"

    passing = record_inspection(order_id, readings=[40, 42, 41])
    assert passing["result"] == "PASS"
    final = get_work_order(order_id)
    assert final["quality_status"] == "PASSED"
    assert final["retreat_count"] == 1

    shipped = validate_success(api.ship_work_order(order_id, CSR), 200)
    assert shipped["processing_status"] == "SHIPPED"
    assert shipped["quality_status"] == "PASSED"
    assert shipped["retreat_count"] == 1


def test_work_order_second_retreat_cycle(api):
    """PRD §3.7: "`RE_TREAT` is available only while the order's
    `retreat_count` remains strictly below the recipe's `max_retreats` — once
    the count has reached the cap, a re-treat attempt fails with
    `ERR_RETREAT_LIMIT_REACHED` (HTTP 422); a successful re-treat moves the
    order from `PROCESSED` to `AWAITING_RETREAT`, increments `retreat_count`
    by one, and resets `quality_status` from `FAILED` to `PENDING_TEST`,
    ready to be scheduled onto a new load."

    Design: Difficulty/non_linear_state_machine/work_order_retreat_cycle
    """
    # max_retreats 2 supports two full re-treat loops.
    bundle = setup_failed_order(recipe_overrides={"max_retreats": 2})
    order_id = bundle["order"]["id"]
    shop = bundle["shop"]
    open_case = bundle["case"]

    for cycle, (start, end) in enumerate(
        [("2026-08-03T08:00:00Z", "2026-08-03T12:00:00Z"),
         ("2026-08-04T08:00:00Z", "2026-08-04T12:00:00Z")],
        start=1,
    ):
        decide_case(open_case["id"], "RE_TREAT")
        order = get_work_order(order_id)
        assert order["processing_status"] == "AWAITING_RETREAT"
        assert order["quality_status"] == "PENDING_TEST"
        assert order["retreat_count"] == cycle

        load = create_load(
            shop["furnace"]["id"], shop["recipe"]["id"],
            scheduled_start_at=start, scheduled_end_at=end,
        )
        assign_order(load["id"], order_id)
        run_load_to_completed(load["id"])
        record_inspection(order_id, readings=[50, 50])
        assert get_work_order(order_id)["quality_status"] == "FAILED"
        open_case = get_open_case_for_order(order_id)

    assert get_work_order(order_id)["retreat_count"] == 2


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / retreat_count_at_max_rejected
# ---------------------------------------------------------------------------

def test_retreat_count_at_max_rejected(api):
    """PRD §3.7: "`RE_TREAT` is available only while the order's
    `retreat_count` remains strictly below the recipe's `max_retreats` — once
    the count has reached the cap, a re-treat attempt fails with
    `ERR_RETREAT_LIMIT_REACHED` (HTTP 422); a successful re-treat moves the
    order from `PROCESSED` to `AWAITING_RETREAT`, increments `retreat_count`
    by one, and resets `quality_status` from `FAILED` to `PENDING_TEST`,
    ready to be scheduled onto a new load."

    Design: Difficulty/boundary_precision_check/retreat_count_at_max_rejected
    """
    bundle = setup_failed_order(recipe_overrides={"max_retreats": 1})
    order_id = bundle["order"]["id"]
    shop = bundle["shop"]

    # First re-treat: retreat_count 0 < max 1, succeeds.
    order = retreat_order_once(bundle)
    assert order["retreat_count"] == 1

    # Re-run and fail again to open a second case at retreat_count == 1.
    load2 = create_load(
        shop["furnace"]["id"], shop["recipe"]["id"],
        scheduled_start_at="2026-08-03T08:00:00Z",
        scheduled_end_at="2026-08-03T12:00:00Z",
    )
    assign_order(load2["id"], order_id)
    run_load_to_completed(load2["id"])
    record_inspection(order_id, readings=[50, 50])
    case2 = get_open_case_for_order(order_id)

    # Second re-treat: retreat_count 1 == max 1, rejected.
    res = api.decide_disposition_case(case2["id"], {"decision": "RE_TREAT"}, QE2)
    validate_error(res, ApiErrorId.ERR_RETREAT_LIMIT_REACHED.value)
    assert get_disposition_case(case2["id"], QE2)["status"] == "OPEN"


def test_retreat_zero_max_rejected_immediately(api):
    """PRD §3.7: "`RE_TREAT` is available only while the order's
    `retreat_count` remains strictly below the recipe's `max_retreats` — once
    the count has reached the cap, a re-treat attempt fails with
    `ERR_RETREAT_LIMIT_REACHED` (HTTP 422); a successful re-treat moves the
    order from `PROCESSED` to `AWAITING_RETREAT`, increments `retreat_count`
    by one, and resets `quality_status` from `FAILED` to `PENDING_TEST`,
    ready to be scheduled onto a new load."

    Design: Difficulty/boundary_precision_check/retreat_count_at_max_rejected
    """
    # max_retreats 0: the very first re-treat already sits at the cap.
    bundle = setup_failed_order(recipe_overrides={"max_retreats": 0})
    res = api.decide_disposition_case(
        bundle["case"]["id"], {"decision": "RE_TREAT"}, QE2
    )
    validate_error(res, ApiErrorId.ERR_RETREAT_LIMIT_REACHED.value)
    assert get_disposition_case(bundle["case"]["id"], QE2)["status"] == "OPEN"
    assert get_work_order(bundle["order"]["id"])["retreat_count"] == 0
