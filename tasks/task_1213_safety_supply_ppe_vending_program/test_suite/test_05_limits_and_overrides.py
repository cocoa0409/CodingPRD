"""Issuance limits, override draws, and boundary precision (PRD §3.4, §3.5)."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ADMIN,
    ANY,
    ApiErrorId,
    TECH,
    grant_override,
    make_employee_headers,
    make_manager_headers,
    open_batch,
    reverse_ok,
    set_clock,
    setup_cost_center,
    setup_employee,
    setup_item,
    setup_job_role,
    setup_machine_with_slot,
    setup_manager,
    setup_vend_scenario,
    stock_slot,
    vend,
    vend_ok,
)


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / usage_limit_exact_boundary
# ---------------------------------------------------------------------------


def test_usage_limit_exact_boundary_pass_at_equality(api):
    """PRD §3.4: "The employee's rolling usage is then computed: the sum of
    `qty` over the employee's `POSTED` issuance lines for the item whose age
    — the logical clock minus the line's `vended_at` — is at least zero and
    at most the policy's `period_window_days` multiplied by twenty-four
    hours."
    PRD §3.4: "The effective limit is the base limit plus the override's
    `remaining_qty` when a covering override exists, and the base limit
    alone otherwise."

    Design: Difficulty/boundary_precision_check/usage_limit_exact_boundary
    """
    sc = setup_vend_scenario(sku="LIM-B", base_price=300, period_limit_qty=5,
                             period_window_days=30, capacity=30, par_level=0,
                             initial_stock=20)
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=2,
            idempotency_key="lb-1")
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=2,
            idempotency_key="lb-2")
    # usage 4 + qty 1 == 5 == limit: must succeed.
    c = vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
                idempotency_key="lb-3")
    assert c["qty"] == 1


def test_usage_limit_exceeded_above_equality(api):
    """PRD §3.4: "beyond the base limit with no covering override, the vend
    dies with `ERR_ISSUANCE_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/usage_limit_exact_boundary
    """
    sc = setup_vend_scenario(sku="LIM-B", base_price=300, period_limit_qty=5,
                             period_window_days=30, capacity=30, par_level=0,
                             initial_stock=20)
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=2,
            idempotency_key="lb-1")
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=2,
            idempotency_key="lb-2")
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
            idempotency_key="lb-3")
    # usage 5 + qty 1 = 6 > 5 -> reject.
    resp = vend(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
                idempotency_key="lb-4")
    validate_error(resp, ApiErrorId.ERR_ISSUANCE_LIMIT_EXCEEDED)
    slot_now = get_success_data(api.get_slot(sc["slot"]["id"], ANY))
    assert slot_now["on_hand_qty"] == 15


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / restock_load_capacity_exact_boundary
# ---------------------------------------------------------------------------


def _setup_capacity_boundary(api):
    item = setup_item(sku="CAP-B", base_list_price_cents=300)
    machine, slot = setup_machine_with_slot(item["id"], capacity=10, par_level=2)
    stock_slot(machine, slot, 6)  # order A loaded: on_hand 6
    order_b = get_success_data(
        api.create_restock_order({"machine_id": machine["id"], "slot_id": slot["id"],
                                  "qty": 4}, TECH)
    )
    get_success_data(api.pick_restock_order(order_b["id"], TECH))
    order_c = get_success_data(
        api.create_restock_order({"machine_id": machine["id"], "slot_id": slot["id"],
                                  "qty": 1}, TECH)
    )
    get_success_data(api.pick_restock_order(order_c["id"], TECH))
    return machine, slot, order_b, order_c


def test_restock_load_at_capacity_equality_succeeds(api):
    """PRD §3.6: "Loading moves `PICKED` to `LOADED`, requires the machine to
    be `ACTIVE` or `OFFLINE` (`ERR_MACHINE_NOT_ACTIVE`), requires that
    `on_hand_qty` plus the order's `qty` not exceed `capacity`
    (`ERR_CAPACITY_EXCEEDED`), and on success adds the `qty` into
    `on_hand_qty`."

    Design: Difficulty/boundary_precision_check/restock_load_capacity_exact_boundary
    """
    machine, slot, order_b, _ = _setup_capacity_boundary(api)
    # on_hand 6 + qty 4 == capacity 10: must succeed (<= semantics).
    loaded = validate_success(api.load_restock_order(order_b["id"], TECH), 200)
    assert loaded["status"] == "LOADED"
    slot_now = get_success_data(api.get_slot(slot["id"], ANY))
    assert slot_now["on_hand_qty"] == 10


def test_restock_load_above_capacity_rejected(api):
    """PRD §3.6: "requires that `on_hand_qty` plus the order's `qty` not
    exceed `capacity` (`ERR_CAPACITY_EXCEEDED`)".

    Design: Difficulty/boundary_precision_check/restock_load_capacity_exact_boundary
    """
    machine, slot, order_b, order_c = _setup_capacity_boundary(api)
    get_success_data(api.load_restock_order(order_b["id"], TECH))
    # on_hand now 10; order C qty 1 -> 10 + 1 > 10.
    resp = api.load_restock_order(order_c["id"], TECH)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)
    # State untouched.
    order_c_now = get_success_data(api.get_restock_order(order_c["id"], ANY))
    assert order_c_now["status"] == "PICKED"
    slot_now = get_success_data(api.get_slot(slot["id"], ANY))
    assert slot_now["on_hand_qty"] == 10


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / effective_limit_draw_split_evaluation_order
# ---------------------------------------------------------------------------


def _setup_draw_split():
    sc = setup_vend_scenario(sku="SPLIT-CF", base_price=300, period_limit_qty=5,
                             period_window_days=30, capacity=50, par_level=0,
                             initial_stock=40, with_manager=True)
    # usage -> 4
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=2,
            idempotency_key="sp-1")
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=2,
            idempotency_key="sp-2")
    ov = grant_override(sc["manager_headers"], employee_id=sc["employee"]["id"],
                        item_id=sc["item"]["id"], approved_qty=3,
                        valid_from="2026-05-01", valid_until="2026-05-31",
                        reason_code="PROJECT")
    sc["override"] = ov
    return sc


def test_effective_limit_draw_split_partial_draw(api):
    """PRD §3.4: "The draw split decides who pays: if the current usage plus
    the requested `qty` stays within the base limit, `override_drawn_qty` is
    zero; beyond the base limit with a covering override, the needed draw
    equals usage plus `qty` minus the larger of the base limit and the
    current usage, it may not exceed the override's `remaining_qty`
    (`ERR_OVERRIDE_QTY_EXCEEDED`), and it becomes the line's
    `override_drawn_qty`".

    Design: Difficulty/combinatorial_formula/effective_limit_draw_split_evaluation_order
    """
    sc = _setup_draw_split()
    # usage 4 + qty 3: needed = 7 - max(5, 4) = 2 from override.
    drawn = vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=3,
                    idempotency_key="sp-3", manager_override_id=sc["override"]["id"])
    assert drawn["override_drawn_qty"] == 2
    ov_now = get_success_data(api.get_manager_override(sc["override"]["id"], ANY))
    assert ov_now["consumed_qty"] == 2
    assert ov_now["remaining_qty"] == 1
    assert ov_now["status"] == "ACTIVE", "CONSUMED only at exact equality"


def test_effective_limit_draw_split_overflow_rejected(api):
    """PRD §3.4: "it may not exceed the override's `remaining_qty`
    (`ERR_OVERRIDE_QTY_EXCEEDED`)".

    Design: Difficulty/combinatorial_formula/effective_limit_draw_split_evaluation_order
    """
    sc = _setup_draw_split()
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=3,
            idempotency_key="sp-3", manager_override_id=sc["override"]["id"])
    # Now usage 7 + qty 4: needed = 11 - max(5, 7) = 4 > remaining 1 -> reject.
    resp = vend(sc["employee_headers"], sc["machine"], sc["slot"], qty=4,
                idempotency_key="sp-4", manager_override_id=sc["override"]["id"])
    validate_error(resp, ApiErrorId.ERR_OVERRIDE_QTY_EXCEEDED)


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant / vend_reverse_restores_slot_on_hand
# ---------------------------------------------------------------------------


def test_vend_then_reverse_restores_on_hand(api):
    """PRD §3.5: "The slot's `on_hand_qty` rises by the vended `qty` — one
    unit for a serialized line".

    Design: Difficulty/compensating_invariant/vend_reverse_restores_slot_on_hand
    """
    sc = setup_vend_scenario(sku="INV-K", base_price=300, period_limit_qty=10,
                             period_window_days=30, capacity=20, par_level=0,
                             initial_stock=10, with_manager=True)
    iss = vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=3,
                  idempotency_key="ik-1")
    mid = get_success_data(api.get_slot(sc["slot"]["id"], ANY))
    assert mid["on_hand_qty"] == 7

    rev = reverse_ok(sc["manager_headers"], iss["id"])
    assert rev["status"] == "REVERSED"
    end = get_success_data(api.get_slot(sc["slot"]["id"], ANY))
    assert end["on_hand_qty"] == 10, "invariant: on_hand after reverse == pre-vend"


def test_reverse_marks_issuance_and_only_reverse_visible(api):
    """PRD §3.5: "Reversal unwinds a vend without rewriting history. A
    `Manager` reverses an issuance currently in `POSTED` — any other state
    fails with `ERR_ISSUANCE_ALREADY_REVERSED`".

    Design: Difficulty/compensating_invariant/vend_reverse_restores_slot_on_hand
    """
    sc = setup_vend_scenario(sku="INV-K", base_price=300, period_limit_qty=10,
                             period_window_days=30, capacity=20, par_level=0,
                             initial_stock=10, with_manager=True)
    iss = vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=3,
                  idempotency_key="ik-1")
    reverse_ok(sc["manager_headers"], iss["id"])

    rows = get_success_data(
        api.list_issuances(ANY, params={"slot_id": sc["slot"]["id"]})
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "REVERSED"
    posted = get_success_data(
        api.list_issuances(ANY, params={"slot_id": sc["slot"]["id"], "status": "POSTED"})
    )
    assert posted == []


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant / override_grant_revoke_restores_effective_limit
# ---------------------------------------------------------------------------


def _setup_grant_revoke():
    sc = setup_vend_scenario(sku="LIM-K", base_price=300, period_limit_qty=5,
                             period_window_days=30, capacity=30, par_level=0,
                             initial_stock=20, with_manager=True)
    # Push usage to 5 (at base limit).
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=3,
            idempotency_key="lk-1")
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=2,
            idempotency_key="lk-2")
    return sc


def test_override_grant_extends_effective_limit(api):
    """PRD §3.4: "The effective limit is the base limit plus the override's
    `remaining_qty` when a covering override exists, and the base limit
    alone otherwise."

    Design: Difficulty/compensating_invariant/override_grant_revoke_restores_effective_limit
    """
    sc = _setup_grant_revoke()
    ov = grant_override(sc["manager_headers"], employee_id=sc["employee"]["id"],
                        item_id=sc["item"]["id"], approved_qty=3,
                        valid_from="2026-05-01", valid_until="2026-05-31",
                        reason_code="INCIDENT")
    # 6th unit (usage 5) requires drawing 1 from override.
    drawn = vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
                    idempotency_key="lk-3", manager_override_id=ov["id"])
    assert drawn["override_drawn_qty"] == 1


def test_override_revoke_restores_base_limit(api):
    """PRD §3.4: "beyond the base limit with no covering override, the vend
    dies with `ERR_ISSUANCE_LIMIT_EXCEEDED`."
    PRD §3.5: "Revocation is a `Manager`'s explicit act — revoking works
    only from `ACTIVE` (otherwise `ERR_OVERRIDE_NOT_ACTIVE`), preserves
    `consumed_qty` for audit, drops `remaining_qty` to zero".

    Design: Difficulty/compensating_invariant/override_grant_revoke_restores_effective_limit
    """
    sc = _setup_grant_revoke()
    ov = grant_override(sc["manager_headers"], employee_id=sc["employee"]["id"],
                        item_id=sc["item"]["id"], approved_qty=3,
                        valid_from="2026-05-01", valid_until="2026-05-31",
                        reason_code="INCIDENT")
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
            idempotency_key="lk-3", manager_override_id=ov["id"])
    revoked = validate_success(
        api.revoke_manager_override(ov["id"], sc["manager_headers"]), 200
    )
    assert revoked["status"] == "REVOKED"
    # Usage is 6; base limit 5; no covering override -> reject.
    resp = vend(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
                idempotency_key="lk-4")
    validate_error(resp, ApiErrorId.ERR_ISSUANCE_LIMIT_EXCEEDED)
