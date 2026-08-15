"""Test-record verdicts, the FINAL-fail rework loop, and shop-floor
segregation of duties (PRD §2.9, §3.2, §3.4)."""
from test_helpers import (
    TEST_USERS,
    accept_quote,
    create_customer,
    create_motor,
    create_shop,
    diagnose_work_order,
    get_work_order,
    intake_work_order,
    issue_quote,
    make_technician_headers,
    make_winding_technician_headers,
    record_coil_data,
    record_core_loss_test,
    record_final_test,
    record_incoming_test,
    send_quote,
    setup_balancing_work_order,
    setup_incoming_tested_work_order,
    start_rewind,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["service_manager_headers"]


def test_final_test_fail_triggers_rework_loop(api):
    """PRD §3.4: "A `FAIL` on the latest final test triggers an automatic
    rework loop: the system returns the work order from `FINAL_TEST` to
    `IN_REWIND`, the version bump on the work order serves as the rework
    counter, and a fresh coil data record is required before the order can
    pass through `BALANCING` again."

    Design: Difficulty/non_linear_state_machine/work_order_rework_loop_final_test_fail_returns_to_in_rewind
    """
    bundle = setup_balancing_work_order(
        motor_overrides={"rated_kw": 30, "frame_mm": 200, "manufacture_year": 2020}
    )
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]

    record = validate_success(
        api.record_test(
            shop_id, wo_id,
            {"kind": "FINAL", "vibration_mm_s": 2.81, "insulation_megohms": 900},
            make_technician_headers("op-t2"),
        ),
        201,
    )
    assert record["verdict"] == "FAIL"  # 2.81 > 2.8 limit for frame <= 315

    wo = validate_success(api.get_work_order(shop_id, wo_id, MANAGER), 200)
    assert wo["status"] == "IN_REWIND"


def test_rework_loop_recovers_with_fresh_coil_data_and_boundary_pass(api):
    """PRD §3.4: "A reading at or below the applicable limit is a `PASS`;
    anything strictly above is a `FAIL`."
    PRD §3.4: "a fresh coil data record is required before the order can pass
    through `BALANCING` again."

    Design: Difficulty/non_linear_state_machine/work_order_rework_loop_final_test_fail_returns_to_in_rewind
    """
    bundle = setup_balancing_work_order(
        motor_overrides={"rated_kw": 30, "frame_mm": 200, "manufacture_year": 2020}
    )
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]

    # First loop: FAIL at 2.81 -> automatic return to IN_REWIND.
    failed = validate_success(
        api.record_test(
            shop_id, wo_id,
            {"kind": "FINAL", "vibration_mm_s": 2.81, "insulation_megohms": 900},
            make_technician_headers("op-t2"),
        ),
        201,
    )
    assert failed["verdict"] == "FAIL"
    assert get_work_order(shop_id, wo_id)["status"] == "IN_REWIND"

    # Fresh coil data moves the order back to BALANCING.
    record_coil_data(shop_id, wo_id, user_id="op-w", turns_per_coil=23, winding_resistance_ohms=0.43)
    assert get_work_order(shop_id, wo_id)["status"] == "BALANCING"

    # Boundary: measured == limit passes.
    passed = validate_success(
        api.record_test(
            shop_id, wo_id,
            {"kind": "FINAL", "vibration_mm_s": 2.8, "insulation_megohms": 900},
            make_technician_headers("op-t2"),
        ),
        201,
    )
    assert passed["verdict"] == "PASS"
    assert get_work_order(shop_id, wo_id)["status"] == "FINAL_TEST"


def test_coil_data_recorder_may_not_equal_incoming_test_recorder(api):
    """PRD §2.9: "The winding technician who records the coil data record may
    not be the same `X-User-ID` that recorded the incoming test on that work
    order."

    Design: Difficulty/priority_pair_validation_conflict/coil_data_segregation_safety_beats_duplicate_uniqueness
    """
    shop = create_shop()
    customer = create_customer(shop["id"])
    motor = create_motor(shop["id"], customer["id"], serial_number="M-9", rated_kw=30)
    wo = intake_work_order(shop["id"], customer["id"], motor["id"], "STANDARD")
    record_incoming_test(shop["id"], wo["id"], user_id="op-shared-1")
    diagnose_work_order(shop["id"], wo["id"], user_id="op-shared-1")
    quote = issue_quote(shop["id"], wo["id"])
    send_quote(shop["id"], wo["id"], quote["id"])
    accept_quote(shop["id"], wo["id"], quote["id"], customer["id"])
    start_rewind(shop["id"], wo["id"], user_id="op-winder-9")

    res = api.create_coil_data(
        shop["id"], wo["id"],
        {"wire_gauge_awg": "14", "turns_per_coil": 22, "coils_per_phase": 6,
         "connection": "WYE", "winding_resistance_ohms": 0.42},
        make_winding_technician_headers("op-shared-1"),
    )
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
    assert get_work_order(shop["id"], wo["id"])["status"] == "IN_REWIND"


def test_coil_data_segregation_passes_for_distinct_operators(api):
    """PRD §3.4: "The segregation rule of §2.9 applies: the coil data recorder
    may not be the technician who recorded this order's incoming test, on pain
    of `ERR_SEGREGATION_OF_DUTIES`. A completed record moves the work order
    from `IN_REWIND` to `BALANCING`."

    Design: Difficulty/priority_pair_validation_conflict/coil_data_segregation_safety_beats_duplicate_uniqueness
    """
    shop = create_shop()
    customer = create_customer(shop["id"])
    motor = create_motor(shop["id"], customer["id"], serial_number="M-9B", rated_kw=30)
    wo = intake_work_order(shop["id"], customer["id"], motor["id"], "STANDARD")
    record_incoming_test(shop["id"], wo["id"], user_id="op-shared-1")
    diagnose_work_order(shop["id"], wo["id"], user_id="op-shared-1")
    quote = issue_quote(shop["id"], wo["id"])
    send_quote(shop["id"], wo["id"], quote["id"])
    accept_quote(shop["id"], wo["id"], quote["id"], customer["id"])
    start_rewind(shop["id"], wo["id"], user_id="op-winder-9")

    record = record_coil_data(shop["id"], wo["id"], user_id="op-winder-9")
    assert record["recorded_by"] == "op-winder-9"
    assert get_work_order(shop["id"], wo["id"])["status"] == "BALANCING"


def test_core_loss_exactly_five_percent_passes(api):
    """PRD §3.2: "the record passes when the measured watts are at or below
    five percent of the rated watts and fails above, with exact decimal
    division and no pre-rounding of the ratio, so a measured loss of exactly
    five percent is a `PASS`".

    Design: Difficulty/boundary_precision_check/core_loss_exactly_five_percent_passes
    """
    bundle = setup_incoming_tested_work_order(
        motor_overrides={"rated_kw": 75, "frame_mm": 200, "manufacture_year": 2020}
    )
    record = record_core_loss_test(
        bundle["shop"]["id"], bundle["work_order"]["id"], 3750
    )
    assert record["verdict"] == "PASS"  # 3750/75000 == 0.05 exactly; <= passes


def test_core_loss_one_watt_above_five_percent_fails(api):
    """PRD §3.2: "the record passes when the measured watts are at or below
    five percent of the rated watts and fails above, with exact decimal
    division and no pre-rounding of the ratio, so a measured loss of exactly
    five percent is a `PASS`".

    Design: Difficulty/boundary_precision_check/core_loss_exactly_five_percent_passes
    """
    bundle = setup_incoming_tested_work_order(
        motor_overrides={"rated_kw": 75, "frame_mm": 200, "manufacture_year": 2020}
    )
    record = record_core_loss_test(
        bundle["shop"]["id"], bundle["work_order"]["id"], 3751
    )
    assert record["verdict"] == "FAIL"  # 3751/75000 > 0.05


def test_vibration_frame_tier_boundaries(api):
    """PRD §3.4: "The verdict comes from the vibration limit for the motor's
    frame: 2.8 mm/s when `frame_mm` is at or below 315, 3.5 mm/s above 315 and
    at or below 630, and 4.5 mm/s above 630. A reading at or below the
    applicable limit is a `PASS`; anything strictly above is a `FAIL`."

    Design: Corner/calculations/vibration_frame_tier_boundaries
    """
    bundle = setup_balancing_work_order(
        motor_overrides={"rated_kw": 30, "frame_mm": 315, "manufacture_year": 2020}
    )
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]

    failed = validate_success(
        api.record_test(
            shop_id, wo_id,
            {"kind": "FINAL", "vibration_mm_s": 2.81, "insulation_megohms": 900},
            make_technician_headers("op-t2"),
        ),
        201,
    )
    assert failed["verdict"] == "FAIL"  # frame 315 <= 315 -> small tier, 2.81 > 2.8
    assert get_work_order(shop_id, wo_id)["status"] == "IN_REWIND"

    record_coil_data(shop_id, wo_id, user_id="op-w", turns_per_coil=23, winding_resistance_ohms=0.43)
    assert get_work_order(shop_id, wo_id)["status"] == "BALANCING"

    passed = validate_success(
        api.record_test(
            shop_id, wo_id,
            {"kind": "FINAL", "vibration_mm_s": 2.8, "insulation_megohms": 900},
            make_technician_headers("op-t2"),
        ),
        201,
    )
    assert passed["verdict"] == "PASS"  # 2.8 <= 2.8 boundary passes
    assert get_work_order(shop_id, wo_id)["status"] == "FINAL_TEST"


def test_segregation_of_duties_final_test_vs_coil_data(api):
    """PRD §2.9: "The technician who records the final test may not be the same
    `X-User-ID` that recorded the coil data."

    Design: Corner/rbac/segregation_of_duties_final_test_vs_coil_data
    """
    bundle = setup_balancing_work_order()  # coil data recorded by op-w
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]

    res = api.record_test(
        shop_id, wo_id,
        {"kind": "FINAL", "vibration_mm_s": 2.0, "insulation_megohms": 900},
        make_technician_headers("op-w"),
    )
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
