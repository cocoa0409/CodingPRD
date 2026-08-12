"""Vend gate ordering, fit-test linkage, structural rules (PRD §2.10, §3.4)."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ADMIN,
    ANY,
    ApiErrorId,
    SAFETY,
    TECH,
    create_issuance_policy_payload,
    create_issuance_payload,
    create_serialized_unit_payload,
    grant_override,
    register_serialized_unit,
    set_clock,
    setup_cost_center,
    setup_employee,
    setup_item,
    setup_job_role,
    setup_machine,
    setup_machine_with_slot,
    setup_manager,
    setup_slot_for_machine,
    setup_vend_scenario,
    stock_slot,
    vend,
    vend_ok,
)


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict / vend_machine_offline_beats_missing_fit_test
# ---------------------------------------------------------------------------


def test_vend_machine_offline_beats_missing_fit_test(api):
    """PRD §2.10: "Every request is validated in a fixed order, and the
    first failing check determines the response." The pinned sequence lists
    "8. Machine state gates (`ERR_MACHINE_NOT_ACTIVE`)" before
    "11. Respirator fit-test linkage (`ERR_FIT_TEST_REQUIRED`)".

    Design: Difficulty/priority_pair_validation_conflict/vend_machine_offline_beats_missing_fit_test
    """
    sc = setup_vend_scenario(sku="RESP-PP", base_price=900,
                             item_category="RESPIRATOR",
                             period_limit_qty=10, period_window_days=30,
                             capacity=20, par_level=0, initial_stock=10)
    get_success_data(
        api.update_machine(sc["machine"]["id"], {"status": "OFFLINE"}, TECH)
    )
    resp = vend(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
                idempotency_key="pp-1")
    validate_error(resp, ApiErrorId.ERR_MACHINE_NOT_ACTIVE)


def test_vend_machine_offline_with_no_fit_test_does_not_leak_fit_error(api):
    """PRD §2.10: "8. Machine state gates (`ERR_MACHINE_NOT_ACTIVE`)."
    PRD §2.10: "11. Respirator fit-test linkage (`ERR_FIT_TEST_REQUIRED`)."

    Design: Difficulty/priority_pair_validation_conflict/vend_machine_offline_beats_missing_fit_test
    """
    sc = setup_vend_scenario(sku="RESP-PP", base_price=900,
                             item_category="RESPIRATOR",
                             period_limit_qty=10, period_window_days=30,
                             capacity=20, par_level=0, initial_stock=10)
    get_success_data(
        api.update_machine(sc["machine"]["id"], {"status": "OFFLINE"}, TECH)
    )
    resp = vend(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
                idempotency_key="pp-1")
    data = resp.json().get("data", {})
    assert data.get("error_id") == "ERR_MACHINE_NOT_ACTIVE", (
        "state gate (priority 5) wins over fit-test gate (priority 8): "
        "no ERR_FIT_TEST_REQUIRED leak"
    )


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict / vend_fit_test_missing_beats_limit_exceeded
# ---------------------------------------------------------------------------


def test_vend_fit_test_missing_beats_limit_exceeded(api):
    """PRD §2.10: "11. Respirator fit-test linkage (`ERR_FIT_TEST_REQUIRED`)."
    PRD §2.10: "21. Issuance limits and override draw
    (`ERR_ISSUANCE_LIMIT_EXCEEDED`, `ERR_OVERRIDE_QTY_EXCEEDED`)."

    Design: Difficulty/priority_pair_validation_conflict/vend_fit_test_missing_beats_limit_exceeded
    """
    sc = setup_vend_scenario(sku="RESP-PQ", base_price=900,
                             item_category="RESPIRATOR",
                             period_limit_qty=1, period_window_days=30,
                             capacity=20, par_level=0, initial_stock=10)
    resp = vend(sc["employee_headers"], sc["machine"], sc["slot"], qty=2,
                idempotency_key="pq-1")
    validate_error(resp, ApiErrorId.ERR_FIT_TEST_REQUIRED)


def test_vend_fit_test_missing_does_not_leak_limit_error(api):
    """PRD §2.10: "11. Respirator fit-test linkage (`ERR_FIT_TEST_REQUIRED`)."
    PRD §2.10: "21. Issuance limits and override draw
    (`ERR_ISSUANCE_LIMIT_EXCEEDED`, `ERR_OVERRIDE_QTY_EXCEEDED`)."

    Design: Difficulty/priority_pair_validation_conflict/vend_fit_test_missing_beats_limit_exceeded
    """
    sc = setup_vend_scenario(sku="RESP-PQ", base_price=900,
                             item_category="RESPIRATOR",
                             period_limit_qty=1, period_window_days=30,
                             capacity=20, par_level=0, initial_stock=10)
    resp = vend(sc["employee_headers"], sc["machine"], sc["slot"], qty=2,
                idempotency_key="pq-1")
    data = resp.json().get("data", {})
    assert data.get("error_id") == "ERR_FIT_TEST_REQUIRED", (
        "safety gate (priority 8) wins over fiscal gate (priority 18): "
        "no ERR_ISSUANCE_LIMIT_EXCEEDED leak"
    )


# ---------------------------------------------------------------------------
# Queue B: validations / vend_item_not_entitled
# ---------------------------------------------------------------------------


def test_vend_item_not_entitled(api):
    """PRD §3.4: "An issuance policy must exist pairing the employee's
    `job_role_id` with the item, otherwise `ERR_ITEM_NOT_ENTITLED`."

    Design: Corner/validations/vend_item_not_entitled
    """
    item = setup_item(sku="VA-NE", base_list_price_cents=100)
    cc = setup_cost_center()
    role = setup_job_role()
    emp, emp_headers = setup_employee(role["id"], cc["id"])
    machine, slot = setup_machine_with_slot(item["id"], capacity=20, par_level=0)
    stock_slot(machine, slot, 10)

    resp = vend(emp_headers, machine, slot, qty=1, idempotency_key="vn-1")
    validate_error(resp, ApiErrorId.ERR_ITEM_NOT_ENTITLED)
    slot_now = get_success_data(api.get_slot(slot["id"], ANY))
    assert slot_now["on_hand_qty"] == 10, "no decrement on rejection"


# ---------------------------------------------------------------------------
# Queue B: validations / vend_serialized_qty_must_be_one
# ---------------------------------------------------------------------------


def test_vend_serialized_qty_must_be_one(api):
    """PRD §3.4: "Third, a serialized vend must request exactly one unit
    (`ERR_SERIALIZED_QTY_INVALID`)."

    Design: Corner/validations/vend_serialized_qty_must_be_one
    """
    item = setup_item(sku="VA-Q2", name="Harness", category="FALL_PROTECTION",
                      base_list_price_cents=12000, inspection_interval_days=90)
    cc = setup_cost_center()
    role = setup_job_role()
    get_success_data(
        api.create_issuance_policy(
            create_issuance_policy_payload(
                job_role_id=role["id"], item_id=item["id"],
                period_limit_qty=10, period_window_days=30,
            ),
            ADMIN,
        )
    )
    emp, emp_headers = setup_employee(role["id"], cc["id"])
    machine = setup_machine()
    slot = setup_slot_for_machine(machine, item_id=item["id"], capacity=4,
                                  par_level=0, slot_code="H1")
    unit = register_serialized_unit(item["id"], slot["id"],
                                    serial_number="SN-VQ-001")
    machine = get_success_data(api.update_machine(machine["id"], {"status": "ACTIVE"}, TECH))

    payload = create_issuance_payload(
        machine_id=machine["id"], slot_id=slot["id"], qty=2,
        idempotency_key="vq-1", serialized_unit_id=unit["id"],
    )
    resp = api.create_issuance(payload, emp_headers)
    validate_error(resp, ApiErrorId.ERR_SERIALIZED_QTY_INVALID)
    unit_now = get_success_data(api.get_serialized_unit(unit["id"], ANY))
    assert unit_now["status"] == "IN_STOCK"
    slot_now = get_success_data(api.get_slot(slot["id"], ANY))
    assert slot_now["on_hand_qty"] == 1


# ---------------------------------------------------------------------------
# Queue B: validations / vend_fall_protection_requires_unit
# ---------------------------------------------------------------------------


def test_vend_fall_protection_requires_unit(api):
    """PRD §3.4: "Second, a vend of a serialized item must name a
    `serialized_unit_id`, and a vend of a non-serialized item must not —
    either violation is `ERR_SERIALIZED_UNIT_REQUIRED`."

    Design: Corner/validations/vend_fall_protection_requires_unit
    """
    fp_item = setup_item(sku="VA-RU", name="Harness", category="FALL_PROTECTION",
                         base_list_price_cents=12000, inspection_interval_days=90)
    g_item = setup_item(sku="VA-RG", name="Gloves", category="GENERAL",
                        base_list_price_cents=100)
    cc = setup_cost_center()
    role = setup_job_role()
    for it in (fp_item, g_item):
        get_success_data(
            api.create_issuance_policy(
                create_issuance_policy_payload(
                    job_role_id=role["id"], item_id=it["id"],
                    period_limit_qty=10, period_window_days=30,
                ),
                ADMIN,
            )
        )
    emp, emp_headers = setup_employee(role["id"], cc["id"])
    machine = setup_machine()
    fp_slot = setup_slot_for_machine(machine, item_id=fp_item["id"], capacity=4,
                                     par_level=0, slot_code="H1")
    unit = register_serialized_unit(fp_item["id"], fp_slot["id"],
                                    serial_number="SN-VR-001")
    g_slot = setup_slot_for_machine(machine, item_id=g_item["id"], capacity=10,
                                    par_level=0, slot_code="G1")
    machine = get_success_data(api.update_machine(machine["id"], {"status": "ACTIVE"}, TECH))
    stock_slot(machine, g_slot, 5)

    # FALL_PROTECTION vend without serialized_unit_id.
    r1 = api.create_issuance(
        create_issuance_payload(machine_id=machine["id"], slot_id=fp_slot["id"],
                                qty=1, idempotency_key="vr-1"),
        emp_headers,
    )
    validate_error(r1, ApiErrorId.ERR_SERIALIZED_UNIT_REQUIRED)

    # GENERAL vend WITH serialized_unit_id.
    r2 = api.create_issuance(
        create_issuance_payload(machine_id=machine["id"], slot_id=g_slot["id"],
                                qty=1, idempotency_key="vr-2",
                                serialized_unit_id=unit["id"]),
        emp_headers,
    )
    validate_error(r2, ApiErrorId.ERR_SERIALIZED_UNIT_REQUIRED)


# ---------------------------------------------------------------------------
# Queue B: validations / vend_blocked_while_holding_lapsed_unit
# ---------------------------------------------------------------------------


def test_vend_blocked_while_holding_lapsed_unit(api):
    """PRD §3.4: "the employee must not currently hold another unit of the
    same item in `INSPECTION_DUE` or `QUARANTINED`; holding such a lapsed
    unit fails with `ERR_REGULATED_ITEM_INSPECTION_DUE`."

    Design: Corner/validations/vend_blocked_while_holding_lapsed_unit
    """
    item = setup_item(sku="VA-LP", name="Harness", category="FALL_PROTECTION",
                      base_list_price_cents=12000, inspection_interval_days=90)
    cc = setup_cost_center()
    role = setup_job_role()
    get_success_data(
        api.create_issuance_policy(
            create_issuance_policy_payload(
                job_role_id=role["id"], item_id=item["id"],
                period_limit_qty=10, period_window_days=400,
            ),
            ADMIN,
        )
    )
    emp, emp_headers = setup_employee(role["id"], cc["id"])
    machine = setup_machine()
    slot = setup_slot_for_machine(machine, item_id=item["id"], capacity=4,
                                  par_level=0, slot_code="H1")
    u1 = register_serialized_unit(item["id"], slot["id"], serial_number="SN-VL-001")
    u2 = register_serialized_unit(item["id"], slot["id"], serial_number="SN-VL-002")
    machine = get_success_data(api.update_machine(machine["id"], {"status": "ACTIVE"}, TECH))

    # Vend U1 at default clock -> next_inspection_due_on 2026-07-30.
    vend_ok(emp_headers, machine, slot, qty=1, idempotency_key="vl-1",
            serialized_unit_id=u1["id"])
    set_clock("2026-07-31T00:00:00Z")

    # U1 is INSPECTION_DUE; attempting to vend U2 of the same item is blocked.
    resp = api.create_issuance(
        create_issuance_payload(machine_id=machine["id"], slot_id=slot["id"],
                                qty=1, idempotency_key="vl-2",
                                serialized_unit_id=u2["id"]),
        emp_headers,
    )
    validate_error(resp, ApiErrorId.ERR_REGULATED_ITEM_INSPECTION_DUE)

    # PASS inspection on U1 unblocks the vend.
    get_success_data(
        api.inspect_serialized_unit(u1["id"], {"result": "PASS",
                                               "inspected_on": "2026-08-01"}, SAFETY)
    )
    ok = validate_success(
        api.create_issuance(
            create_issuance_payload(machine_id=machine["id"], slot_id=slot["id"],
                                    qty=1, idempotency_key="vl-3",
                                    serialized_unit_id=u2["id"]),
            emp_headers,
        ),
        201,
    )
    u2_now = get_success_data(api.get_serialized_unit(u2["id"], ANY))
    assert u2_now["issued_to_employee_id"] == emp["id"]


# ---------------------------------------------------------------------------
# Queue B: validations / vend_with_expired_override_rejected
# ---------------------------------------------------------------------------


def test_vend_with_expired_override_rejected(api):
    """PRD §3.4: "an id that names no override, an inactive one, or one
    whose window does not cover today fails with `ERR_OVERRIDE_NOT_ACTIVE`."
    PRD §3.8: "The override-expiry sweep moves an `ACTIVE` override whose
    `valid_until` is now in the past to `EXPIRED`".

    Design: Corner/validations/vend_with_expired_override_rejected
    """
    sc = setup_vend_scenario(sku="VA-EO", base_price=100, period_limit_qty=1,
                             period_window_days=400, capacity=20, par_level=0,
                             initial_stock=10, with_manager=True)
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
            idempotency_key="ve-0")
    ov = grant_override(sc["manager_headers"],
                        employee_id=sc["employee"]["id"], item_id=sc["item"]["id"],
                        approved_qty=2, valid_from="2026-05-01",
                        valid_until="2026-05-10", reason_code="PROJECT")

    set_clock("2026-05-11T00:00:00Z")
    ov_now = get_success_data(api.get_manager_override(ov["id"], ANY))
    assert ov_now["status"] == "EXPIRED"

    resp = vend(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
                idempotency_key="ve-1", manager_override_id=ov["id"])
    validate_error(resp, ApiErrorId.ERR_OVERRIDE_NOT_ACTIVE)
    slot_now = get_success_data(api.get_slot(sc["slot"]["id"], ANY))
    assert slot_now["on_hand_qty"] == 9


# ---------------------------------------------------------------------------
# Queue B: validations / vend_with_unknown_machine_id_returns_not_found
# ---------------------------------------------------------------------------


def test_vend_with_unknown_machine_id_returns_not_found(api):
    """PRD §2.7: "After path identifiers, the foreign keys in the request body
    (`machine_id`, `slot_id`, `item_id`, `job_role_id`, `home_cost_center_id`,
    `employee_id`, `serialized_unit_id`, `manager_override_id`) are resolved,
    and any miss produces the resource-specific 404".

    Design: Corner/validations/vend_with_unknown_machine_id_returns_not_found
    """
    cc = setup_cost_center()
    role = setup_job_role()
    emp, emp_headers = setup_employee(role["id"], cc["id"])

    resp = api.create_issuance(
        create_issuance_payload(
            machine_id="11111111-2222-4333-8444-555555555555",
            slot_id="22222222-3333-4333-8444-666666666666",
            qty=1, idempotency_key="va-1",
        ),
        emp_headers,
    )
    validate_error(resp, ApiErrorId.ERR_MACHINE_NOT_FOUND)


# ---------------------------------------------------------------------------
# Queue B: validations / create_item_missing_required_sku_returns_400
# ---------------------------------------------------------------------------


def test_create_item_missing_required_sku_returns_400(api):
    """PRD §2.10: "3. Request-body shape: required fields present, types
    valid, enum members valid, integer ranges enforced — `qty` above zero,
    `capacity` above zero, `par_level` within zero up to but not including
    `capacity`, window ends after starts (`ERR_VALIDATION_FAILED`)."

    Design: Corner/validations/create_item_missing_required_sku_returns_400
    """
    setup_job_role(role_name="VIEWER-VA")
    resp = api.create_item(
        {"name": "No SKU Gloves", "category": "GENERAL",
         "base_list_price_cents": 100},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED)
