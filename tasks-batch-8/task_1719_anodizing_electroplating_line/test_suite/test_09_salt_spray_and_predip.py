"""Salt-spray qualification, conditional-alloy predip gate, lot state gates."""
from test_helpers import (
    ApiErrorId,
    CHEM,
    EHS,
    MGR,
    OP,
    QC,
    complete_load_run,
    create_compat_rule,
    create_customer,
    create_salt_spray_lot,
    create_titrated_bath,
    get_bath_version,
    get_success_data,
    get_work_order,
    inspect_work_order,
    route_work_order,
    set_clock,
    setup_awaiting_inspection,
    setup_awaiting_lot_test,
    setup_routed_order,
    start_load_run,
    strip_and_replate,
    validate_error,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_salt_spray_lot_payload


def test_salt_spray_failure_reenters_rework_loop_then_passes():
    """PRD §3.6: "Otherwise the lot is `FAILED` and the order moves to `REJECTED` with
    `pending_strip` true and `last_defect_type` set to `LOT_CORROSION` — unless the
    order's `rework_count` has already reached two, in which case the order goes
    straight to `SCRAPPED`."
    PRD §3.6: "a `PASSED` lot moves the linked order from `AWAITING_LOT_TEST` to
    `COMPLETE`."

    Design: Corner/state_machines/salt_spray_failure_reenters_rework_loop
    """
    customer = create_customer(company_name="Salt Co")
    create_compat_rule()
    bath = create_titrated_bath(bath_code="ANO-S", routing_modes_supported=["BARREL"])
    wo = setup_awaiting_lot_test(customer["id"], bath["id"], part_number="PN-S")
    assert wo["status"] == "AWAITING_LOT_TEST"
    lot1 = create_salt_spray_lot(wo["id"], sample_count=5, hours_required=96)
    assert lot1["allowed_failures"] == 1
    # Advance clock exactly 96 hours (2026-08-01 -> 2026-08-05).
    set_clock("2026-08-05T00:00:00Z")
    res1 = get_success_data(api_client.evaluate_salt_spray_lot(
        lot1["id"], {"panels_failed": 2}, CHEM
    ))
    assert res1["result"] == "FAILED"  # 2 > 1 allowed
    rejected = get_work_order(wo["id"])
    assert rejected["status"] == "REJECTED"
    assert rejected["last_defect_type"] == "LOT_CORROSION"
    assert rejected["pending_strip"] is True
    # Strip-replate lap, second clean pass, second lot passes at 1 <= 1.
    after_strip = strip_and_replate(wo["id"])
    assert after_strip["rework_count"] == 1
    route_work_order(wo["id"], bath["id"])
    lr2 = start_load_run(wo["id"], bath_id=bath["id"])
    complete_load_run(lr2["id"])
    inspect_work_order(wo["id"], defect_type="NONE")
    lot2 = create_salt_spray_lot(wo["id"], sample_count=5, hours_required=96)
    set_clock("2026-08-09T00:00:00Z")
    res2 = get_success_data(api_client.evaluate_salt_spray_lot(
        lot2["id"], {"panels_failed": 1}, CHEM
    ))
    assert res2["result"] == "PASSED"  # 1 <= 1 inclusive
    assert get_work_order(wo["id"])["status"] == "COMPLETE"


def test_lot_create_wrong_state_rejected():
    """PRD §3.6: "A `LabChemist` or `ShopManager` creates a **SaltSprayLot** for an
    order in `AWAITING_LOT_TEST` — any other state rejects with
    `ERR_WORK_ORDER_NOT_AWAITING_LOT_TEST`"

    Design: Corner/state_machines/lot_create_wrong_state_rejected
    """
    customer = create_customer(company_name="Lot Co")
    create_compat_rule()
    bath = create_titrated_bath(bath_code="ANO-N", routing_modes_supported=["BARREL"])
    wo, _lr = setup_awaiting_inspection(customer["id"], bath["id"], part_number="PN-N")
    inspect_work_order(wo["id"], defect_type="NONE")
    assert get_work_order(wo["id"])["status"] == "COMPLETE"
    resp = api_client.create_salt_spray_lot(
        create_salt_spray_lot_payload(work_order_id=wo["id"], sample_count=5,
                                      hours_required=96),
        CHEM,
    )
    validate_error(resp, ApiErrorId.ERR_WORK_ORDER_NOT_AWAITING_LOT_TEST)


def test_lot_hours_gate_and_allowance_boundaries():
    """PRD §3.6: "Evaluating a lot takes the observed `panels_failed` and runs two
    gates in cascade order: the lot's `result` must still be `PENDING` (else
    `ERR_LOT_NOT_RUNNING`), and `hours_run` must be at least `hours_required` (else
    `ERR_LOT_HOURS_INSUFFICIENT`). A lot passes when `panels_failed` is at most
    `allowed_failures`, inclusive"
    PRD §3.6: "The lot's `allowed_failures` is computed at creation: two when the
    sample count is at least ten, one when it is at least five but below ten, and zero
    below five — so counts of 4, 5, 9, and 10 yield 0, 1, 1, and 2 respectively."

    Design: Corner/calculations/lot_hours_gate_and_allowance_boundaries
    """
    customer = create_customer(company_name="Hours Co")
    create_compat_rule()
    bath = create_titrated_bath(bath_code="ANO-HR", routing_modes_supported=["BARREL"])
    w5 = setup_awaiting_lot_test(customer["id"], bath["id"], part_number="PN-H5")
    lot5 = create_salt_spray_lot(w5["id"], sample_count=4, hours_required=96)
    assert lot5["allowed_failures"] == 0
    w10 = setup_awaiting_lot_test(customer["id"], bath["id"], part_number="PN-H10")
    lot10 = create_salt_spray_lot(w10["id"], sample_count=10, hours_required=96)
    assert lot10["allowed_failures"] == 2
    # At 95 hours (2026-08-04T23:00:00Z): the hours gate rejects.
    set_clock("2026-08-04T23:00:00Z")
    resp_early = api_client.evaluate_salt_spray_lot(lot5["id"], {"panels_failed": 0}, CHEM)
    validate_error(resp_early, ApiErrorId.ERR_LOT_HOURS_INSUFFICIENT)
    # At exactly 96 hours: allowed.
    set_clock("2026-08-05T00:00:00Z")
    res5 = get_success_data(api_client.evaluate_salt_spray_lot(
        lot5["id"], {"panels_failed": 1}, CHEM
    ))
    assert res5["result"] == "FAILED"  # 1 > 0 allowed
    assert get_work_order(w5["id"])["status"] == "REJECTED"
    # Double evaluate -> ERR_LOT_NOT_RUNNING.
    resp_2x = api_client.evaluate_salt_spray_lot(lot5["id"], {"panels_failed": 0}, CHEM)
    validate_error(resp_2x, ApiErrorId.ERR_LOT_NOT_RUNNING)
    res10 = get_success_data(api_client.evaluate_salt_spray_lot(
        lot10["id"], {"panels_failed": 2}, CHEM
    ))
    assert res10["result"] == "PASSED"  # 2 <= 2 inclusive
    assert get_work_order(w10["id"])["status"] == "COMPLETE"


def test_conditional_alloy_requires_predip():
    """PRD §3.5: "a `CONDITIONAL` rule is allowed with its pre-dip gate deferred to
    load start"
    PRD §3.5: "when the applicable compatibility rule is `CONDITIONAL`,
    `predip_completed` must be true (else `ERR_PREDIP_REQUIRED`)"
    PRD §3.5: "Separately, recording pre-dip completion sets `predip_completed` to
    true; the flag matters only at load start for conditionally compatible alloys, and
    a completed strip later resets it."

    Design: Corner/validations/conditional_alloy_requires_predip
    """
    customer = create_customer(company_name="Predip Co")
    create_compat_rule(alloy_code="TI64", process_type="ANODIZE",
                       chemistry_family="SULFURIC", compatibility="CONDITIONAL",
                       notes="Requires desmut pre-dip")
    bath = create_titrated_bath(bath_code="ANO-PD", routing_modes_supported=["BARREL"])
    # CONDITIONAL allows routing.
    wo = setup_routed_order(customer["id"], bath["id"], part_number="PN-PD",
                            alloy_code="TI64")
    assert wo["status"] == "ROUTED"
    # Load start without predip is rejected.
    resp = api_client.start_load_run(
        wo["id"],
        {"duration_minutes": 40, "current_density_a_dm2": 1.5,
         "expected_bath_version": get_bath_version(bath["id"])},
        OP,
    )
    validate_error(resp, ApiErrorId.ERR_PREDIP_REQUIRED)
    # complete-predip sets the flag; load start then succeeds.
    predip = get_success_data(api_client.complete_predip(wo["id"], OP))
    assert predip["predip_completed"] is True
    lr = start_load_run(wo["id"], bath_id=bath["id"])
    assert lr["status"] == "RUNNING"
