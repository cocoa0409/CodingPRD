"""Serialized-unit inspection cycles and regulated-item gates (PRD §3.3, §3.4, §3.8)."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ADMIN,
    ANY,
    ApiErrorId,
    SAFETY,
    TECH,
    create_issuance_policy_payload,
    create_machine_payload,
    create_serialized_unit_payload,
    create_slot_payload,
    register_serialized_unit,
    set_clock,
    setup_cost_center,
    setup_employee,
    setup_item,
    setup_job_role,
    setup_machine,
    setup_machine_with_slot,
    setup_slot_for_machine,
    setup_vend_scenario,
    stock_slot,
    vend,
    vend_ok,
)


def _setup_fall_protection_scenario(api, sku="HARN-CY", interval_days=90, period_window_days=30):
    """FALL_PROTECTION item + policy + employee + machine + slot; unit registered
    while machine COMMISSIONING, then machine commissioned to ACTIVE."""
    item = setup_item(sku=sku, name="Full Body Harness", category="FALL_PROTECTION",
                      base_list_price_cents=12000,
                      inspection_interval_days=interval_days)
    cc = setup_cost_center()
    role = setup_job_role()
    get_success_data(
        api.create_issuance_policy(
            create_issuance_policy_payload(
                job_role_id=role["id"], item_id=item["id"],
                period_limit_qty=10, period_window_days=period_window_days,
            ),
            ADMIN,
        )
    )
    emp, emp_headers = setup_employee(role["id"], cc["id"])
    # Build the machine COMMISSIONING first so we can register the unit pre-activation.
    machine = setup_machine()
    slot = setup_slot_for_machine(machine, item_id=item["id"], capacity=10,
                                  par_level=0, slot_code="H1")
    unit = register_serialized_unit(item["id"], slot["id"], serial_number="SN-00001")
    machine = get_success_data(api.update_machine(machine["id"], {"status": "ACTIVE"}, TECH))
    return {
        "item": item, "cc": cc, "role": role, "employee": emp,
        "employee_headers": emp_headers, "machine": machine, "slot": slot,
        "unit": unit,
    }


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine / serialized_unit_inspection_cycle_loops
# ---------------------------------------------------------------------------


def test_serialized_unit_due_boundary_inclusive(api):
    """PRD §3.8: "The inspection sweep moves an `ISSUED` unit whose
    `next_inspection_due_on` is now in the past to `INSPECTION_DUE` — the
    due date itself keeps the unit `ISSUED`, with the unit becoming due the
    following day".

    Design: Difficulty/non_linear_state_machine/serialized_unit_inspection_cycle_loops
    """
    sc = _setup_fall_protection_scenario(api, sku="HARN-CY")
    # Vend at default clock 2026-05-01 -> next_inspection_due_on 2026-07-30.
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
            idempotency_key="cy-1", serialized_unit_id=sc["unit"]["id"])

    # On the due date itself: still ISSUED.
    set_clock("2026-07-30T00:00:00Z")
    unit = get_success_data(api.get_serialized_unit(sc["unit"]["id"], ANY))
    assert unit["status"] == "ISSUED", "due date itself keeps the unit ISSUED"
    assert unit["next_inspection_due_on"] == "2026-07-30"

    # Day after: INSPECTION_DUE.
    set_clock("2026-07-31T00:00:00Z")
    unit = get_success_data(api.get_serialized_unit(sc["unit"]["id"], ANY))
    assert unit["status"] == "INSPECTION_DUE"


def test_serialized_unit_pass_inspection_refreshes_and_cycle_repeats(api):
    """PRD §3.3: "A `PASS` on a unit in `ISSUED` or `INSPECTION_DUE` returns
    it to — or keeps it in — `ISSUED`: `last_inspected_on` becomes the
    inspection date, `next_inspection_due_on` is recomputed as the
    inspection date plus the item's `inspection_interval_days`, and the log
    is appended".

    Design: Difficulty/non_linear_state_machine/serialized_unit_inspection_cycle_loops
    """
    sc = _setup_fall_protection_scenario(api, sku="HARN-CY")
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
            idempotency_key="cy-1", serialized_unit_id=sc["unit"]["id"])
    set_clock("2026-07-31T00:00:00Z")

    # PASS on 2026-08-01 -> next_inspection_due_on 2026-10-30.
    passed = validate_success(
        api.inspect_serialized_unit(
            sc["unit"]["id"], {"result": "PASS", "inspected_on": "2026-08-01"}, SAFETY
        ),
        200,
    )
    assert passed["status"] == "ISSUED"
    assert passed["next_inspection_due_on"] == "2026-10-30"
    assert passed["issued_to_employee_id"] == sc["employee"]["id"]

    # Cycle loops a second time: at 2026-10-31 the unit is INSPECTION_DUE again.
    set_clock("2026-10-31T00:00:00Z")
    unit = get_success_data(api.get_serialized_unit(sc["unit"]["id"], ANY))
    assert unit["status"] == "INSPECTION_DUE"
    assert unit["issued_to_employee_id"] == sc["employee"]["id"]


# ---------------------------------------------------------------------------
# Queue B: calculations / inspection_overdue_quarantine_boundary
# ---------------------------------------------------------------------------


def test_inspection_overdue_quarantine_at_30_days_stays_due(api):
    """PRD §3.8: "moves an `INSPECTION_DUE` unit more than thirty full days
    past due, a current date later than `next_inspection_due_on` plus
    thirty days, to `QUARANTINED` without appending any `inspection_log`
    entry; exactly thirty days past keeps the unit in `INSPECTION_DUE`,
    with quarantine landing on day thirty-one."

    Design: Corner/calculations/inspection_overdue_quarantine_boundary
    """
    sc = _setup_fall_protection_scenario(api, sku="CALC-IQ", period_window_days=400)
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
            idempotency_key="iq-1", serialized_unit_id=sc["unit"]["id"])
    set_clock("2026-07-31T00:00:00Z")
    unit = get_success_data(api.get_serialized_unit(sc["unit"]["id"], ANY))
    assert unit["status"] == "INSPECTION_DUE"

    # due + 30 days = 2026-08-29: still INSPECTION_DUE.
    set_clock("2026-08-29T00:00:00Z")
    unit = get_success_data(api.get_serialized_unit(sc["unit"]["id"], ANY))
    assert unit["status"] == "INSPECTION_DUE", "grace boundary inclusive"


def test_inspection_overdue_quarantine_at_31_days_quarantined(api):
    """PRD §3.8: "moves an `INSPECTION_DUE` unit more than thirty full days
    past due, a current date later than `next_inspection_due_on` plus
    thirty days, to `QUARANTINED` without appending any `inspection_log`
    entry".

    Design: Corner/calculations/inspection_overdue_quarantine_boundary
    """
    sc = _setup_fall_protection_scenario(api, sku="CALC-IQ", period_window_days=400)
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
            idempotency_key="iq-1", serialized_unit_id=sc["unit"]["id"])
    set_clock("2026-07-31T00:00:00Z")

    set_clock("2026-08-30T00:00:00Z")
    unit = get_success_data(api.get_serialized_unit(sc["unit"]["id"], ANY))
    assert unit["status"] == "QUARANTINED", "overdue sweep at due+31"
