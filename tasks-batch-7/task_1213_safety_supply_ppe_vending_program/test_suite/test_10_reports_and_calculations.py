"""Rolling-window boundary, pricing fallback, fit-test expiry, par trigger,
override-consumption equality, audit findings, consumption report, and
consistency-model visibility (PRD §3.2, §3.4, §3.5, §3.6, §3.7, §3.8)."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ADMIN,
    ANY,
    ApiErrorId,
    AUDITOR,
    FINANCE,
    SAFETY,
    TECH,
    create_issuance_policy_payload,
    grant_override,
    open_audit,
    open_batch,
    reverse_ok,
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
# Queue B: calculations / rolling_window_exact_inclusion_boundary
# ---------------------------------------------------------------------------


def test_rolling_window_exact_inclusion_boundary(api):
    """PRD §3.4: "The employee's rolling usage is then computed: the sum of
    `qty` over the employee's `POSTED` issuance lines for the item whose
    age — the logical clock minus the line's `vended_at` — is at least zero
    and at most the policy's `period_window_days` multiplied by twenty-four
    hours. A line whose age equals exactly that many hours still counts; a
    line one second older does not; `REVERSED` lines never count."

    Design: Corner/calculations/rolling_window_exact_inclusion_boundary
    """
    sc = setup_vend_scenario(sku="CALC-RW", base_price=100, period_limit_qty=2,
                             period_window_days=30, capacity=20, par_level=0,
                             initial_stock=10)
    # Vend qty 2 at default clock 2026-05-01T00:00:00Z (uses whole limit).
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=2,
            idempotency_key="rw-1")

    # At exactly 30 days of age the prior vend still counts -> reject.
    set_clock("2026-05-31T00:00:00Z")
    resp = vend(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
                idempotency_key="rw-2")
    validate_error(resp, ApiErrorId.ERR_ISSUANCE_LIMIT_EXCEEDED)

    # At 30 days + 1 second the prior vend aged out -> vend succeeds.
    set_clock("2026-05-31T00:00:01Z")
    ok = vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
                 idempotency_key="rw-3")
    assert ok["qty"] == 1
    slot_now = get_success_data(api.get_slot(sc["slot"]["id"], ANY))
    assert slot_now["on_hand_qty"] == 7


# ---------------------------------------------------------------------------
# Queue B: calculations / contract_price_fallback_to_base_list
# ---------------------------------------------------------------------------


def test_contract_price_fallback_to_base_list(api):
    """PRD §3.4: "When no tier breakpoint has been reached, the fallback
    ladder looks at rows covering the vend date regardless of breakpoint:
    if none cover, the price is the item's `base_list_price_cents`".

    Design: Corner/calculations/contract_price_fallback_to_base_list
    """
    sc = setup_vend_scenario(sku="CALC-FB", base_price=250, period_limit_qty=10,
                             period_window_days=30, capacity=20, par_level=0,
                             initial_stock=10)
    iss = vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=2,
                  idempotency_key="fb-1")
    assert iss["unit_price_cents"] == 250
    assert iss["line_total_cents"] == 500


# ---------------------------------------------------------------------------
# Queue B: calculations / fit_test_expiry_boundary
# ---------------------------------------------------------------------------


def test_fit_test_expiry_boundary(api):
    """PRD §3.2: "A `PASS` earns an `expires_on` of the test date plus 365
    days and a `VALID` status". §3.8: "The fit-test sweep moves a `VALID`
    fit-test entry whose `expires_on` is now in the past to `EXPIRED`; the
    expiry date itself remains valid."

    Design: Corner/calculations/fit_test_expiry_boundary
    """
    item = setup_item(sku="CALC-FT", name="Half Mask", category="RESPIRATOR",
                      base_list_price_cents=900)
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
    # PASS fit test 2026-01-10 -> expires_on 2027-01-10.
    get_success_data(
        api.record_fit_test(emp["id"],
                            {"item_id": item["id"], "tested_on": "2026-01-10",
                             "result": "PASS"},
                            SAFETY),
    )
    machine, slot = setup_machine_with_slot(item["id"], capacity=20, par_level=0,
                                            slot_code="R1")
    stock_slot(machine, slot, 10)

    # On expires_on (2027-01-10): vend succeeds (inclusive).
    set_clock("2027-01-10T08:00:00Z")
    ok = vend_ok(emp_headers, machine, slot, qty=1, idempotency_key="ft-1")
    assert ok["qty"] == 1

    # Day after expiry: entry swept EXPIRED -> vend fails.
    set_clock("2027-01-11T08:00:00Z")
    resp = vend(emp_headers, machine, slot, qty=1, idempotency_key="ft-2")
    validate_error(resp, ApiErrorId.ERR_FIT_TEST_REQUIRED)




# ---------------------------------------------------------------------------
# Queue B: calculations / restock_par_trigger_exact_threshold
# ---------------------------------------------------------------------------


def test_restock_par_trigger_exact_threshold(api):
    """PRD §3.6: "After any decrease of a non-serialized slot's
    `on_hand_qty` — in practice, a vend — the trigger fires when
    `on_hand_qty` is at or below `par_level` and no restock order for the
    slot is in `SUGGESTED` or `PICKED`: the system creates an order with
    `source` `AUTO_PAR` whose `qty` fills the slot to capacity, that is,
    `capacity` minus the current `on_hand_qty`. A slot sitting exactly at
    par triggers; one unit above par does not."

    Design: Corner/calculations/restock_par_trigger_exact_threshold
    """
    item = setup_item(sku="CALC-PT", base_list_price_cents=100)
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
    # Slot A: par 5 -> vend 1 to land at on_hand 5 == par (triggers).
    slot_a = setup_slot_for_machine(machine, item_id=item["id"], capacity=20,
                                    par_level=5, slot_code="A1")
    # Slot B: par 4 -> vend 1 to land at on_hand 5 > par (no trigger).
    slot_b = setup_slot_for_machine(machine, item_id=item["id"], capacity=20,
                                    par_level=4, slot_code="B1")
    machine = get_success_data(
        api.update_machine(machine["id"], {"status": "ACTIVE"}, TECH)
    )
    stock_slot(machine, slot_a, 6)
    stock_slot(machine, slot_b, 6)

    vend_ok(emp_headers, machine, slot_a, qty=1, idempotency_key="pt-a")
    vend_ok(emp_headers, machine, slot_b, qty=1, idempotency_key="pt-b")

    orders_a = get_success_data(
        api.list_restock_orders(ANY, params={"slot_id": slot_a["id"],
                                             "status": "SUGGESTED"})
    )
    assert len(orders_a) == 1
    assert orders_a[0]["qty"] == 15
    assert orders_a[0]["source"] == "AUTO_PAR"
    assert orders_a[0]["status"] == "SUGGESTED"

    orders_b = get_success_data(
        api.list_restock_orders(ANY, params={"slot_id": slot_b["id"],
                                             "status": "SUGGESTED"})
    )
    assert orders_b == [], "slot B at par+1 spawns no order"


# ---------------------------------------------------------------------------
# Queue B: calculations / override_consumed_exact_equality_consumes
# ---------------------------------------------------------------------------


def test_override_consumed_exact_equality_consumes(api):
    """PRD §3.4: "a drawn override's `consumed_qty` rises by
    `override_drawn_qty` and flips the override to `CONSUMED` the moment
    consumption reaches `approved_qty`, leaving `remaining_qty` at zero".

    Design: Corner/calculations/override_consumed_exact_equality_consumes
    """
    sc = setup_vend_scenario(sku="CALC-OC", base_price=100, period_limit_qty=1,
                             period_window_days=30, capacity=20, par_level=0,
                             initial_stock=10, with_manager=True)
    # usage 1 (base limit 1)
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
            idempotency_key="oc-0")
    ov = grant_override(sc["manager_headers"], employee_id=sc["employee"]["id"],
                        item_id=sc["item"]["id"], approved_qty=2,
                        valid_from="2026-05-01", valid_until="2026-05-31",
                        reason_code="INCIDENT")

    # Two 1-unit draws against the override.
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
            idempotency_key="oc-1", manager_override_id=ov["id"])
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
            idempotency_key="oc-2", manager_override_id=ov["id"])

    ov_now = get_success_data(api.get_manager_override(ov["id"], ANY))
    assert ov_now["consumed_qty"] == 2
    assert ov_now["remaining_qty"] == 0
    assert ov_now["status"] == "CONSUMED", "exact-equality transition"

    # Third draw against CONSUMED override fails.
    resp = vend(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
                idempotency_key="oc-3", manager_override_id=ov["id"])
    validate_error(resp, ApiErrorId.ERR_OVERRIDE_NOT_ACTIVE)


# ---------------------------------------------------------------------------
# Queue B: calculations / audit_detects_override_consumption_mismatch
# ---------------------------------------------------------------------------


def test_audit_detects_override_consumption_mismatch(api):
    """PRD §3.8: "Under `OVERRIDE_USAGE`, every manager override — of any
    status — whose closed window from `valid_from` to `valid_until`
    intersects the audit's closed period, and whose `consumed_qty` differs
    from the sum of `override_drawn_qty` over the `POSTED` issuance lines
    referencing it, becomes a finding whose `finding_type` is
    `OVERRIDE_CONSUMPTION_MISMATCH` and whose `entity_id` is the override's
    id".
    PRD §3.5: "the override's `consumed_qty` is never restored: consumption
    is final, and the audit of §3.8 reconciles any divergence."

    Design: Corner/calculations/audit_detects_override_consumption_mismatch
    """
    sc = setup_vend_scenario(sku="CALC-AM", base_price=100, period_limit_qty=1,
                             period_window_days=30, capacity=20, par_level=0,
                             initial_stock=10, with_manager=True)
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
            idempotency_key="am-0")
    ov = grant_override(sc["manager_headers"], employee_id=sc["employee"]["id"],
                        item_id=sc["item"]["id"], approved_qty=2,
                        valid_from="2026-05-01", valid_until="2026-05-31",
                        reason_code="INCIDENT")
    drawn = vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
                    idempotency_key="am-1", manager_override_id=ov["id"])
    reverse_ok(sc["manager_headers"], drawn["id"])

    audit = open_audit(scope="OVERRIDE_USAGE")
    get_success_data(api.begin_audit_fieldwork(audit["id"], AUDITOR))
    filed = validate_success(api.file_audit_findings(audit["id"], AUDITOR), 200)
    assert filed["status"] == "FINDINGS_FILED"
    assert filed["exceptions_count"] == 1, (
        "consumed_qty 1 != POSTED drawn sum 0 after reversal"
    )
    findings = filed["findings_detail"]
    assert isinstance(findings, list) and len(findings) == 1
    assert findings[0]["finding_type"] == "OVERRIDE_CONSUMPTION_MISMATCH"
    assert findings[0]["entity_id"] == ov["id"]


# ---------------------------------------------------------------------------
# Queue B: endpoints / consumption_report_aggregates_posted_only
# ---------------------------------------------------------------------------


def test_consumption_report_aggregates_posted_only(api):
    """PRD §3.7: "a computed read returns, for a `cost_center_id` and a
    half-open period from `period_start` to `period_end`, an aggregate over
    the `POSTED` (non-reversed) issuance lines of that cost center in the
    window: the `line_count`, the `total_qty` of units vended, and the
    `total_amount_cents` they sum to."

    Design: Corner/endpoints/consumption_report_aggregates_posted_only
    """
    sc = setup_vend_scenario(sku="EP-RP", base_price=450, period_limit_qty=10,
                             period_window_days=30, capacity=20, par_level=0,
                             initial_stock=10, with_manager=True)
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=3,
            idempotency_key="rp-1")
    iss2 = vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=2,
                   idempotency_key="rp-2")
    reverse_ok(sc["manager_headers"], iss2["id"])

    resp = api.get_consumption_report(
        ANY,
        params={"cost_center_id": sc["cost_center"]["id"],
                "period_start": "2026-05-01", "period_end": "2026-06-01"},
    )
    data = validate_success(resp, 200)
    assert data["cost_center_id"] == sc["cost_center"]["id"]
    assert data["line_count"] == 1, "reversed line excluded"
    assert data["total_qty"] == 3
    assert data["total_amount_cents"] == 1350  # 3 * 450


# ---------------------------------------------------------------------------
# Queue B: consistency_model / immediate_visibility_after_vend
# ---------------------------------------------------------------------------


def test_immediate_visibility_after_vend(api):
    """PRD §3.4: "A successful vend writes an issuance in `POSTED` status
    whose `item_id` is copied from the slot, whose `cost_center_id` is
    copied from the employee's `home_cost_center_id`, whose `vended_at` is
    the logical clock, and whose `chargeback_batch_id` stays null until a
    batch sweeps it. Physical effects land in the same breath: the slot's
    `on_hand_qty` drops by `qty`".

    Design: Corner/consistency_model/immediate_visibility_after_vend
    """
    sc = setup_vend_scenario(sku="CM-IV", base_price=100, period_limit_qty=10,
                             period_window_days=30, capacity=20, par_level=0,
                             initial_stock=12)
    iss = vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
                  idempotency_key="cm-1")
    # Immediate read of slot reflects decrement.
    slot_now = get_success_data(api.get_slot(sc["slot"]["id"], ANY))
    assert slot_now["on_hand_qty"] == 11
    # Immediate read of issuance: POSTED with computed fields populated.
    got = validate_success(api.get_issuance(iss["id"], ANY), 200)
    assert got["status"] == "POSTED"
    assert got["unit_price_cents"] == 100
    assert got["line_total_cents"] == 100
    assert got["cost_center_id"] == sc["cost_center"]["id"]
    assert got["item_id"] == sc["item"]["id"]

