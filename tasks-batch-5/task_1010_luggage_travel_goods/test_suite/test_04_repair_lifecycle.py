"""Repair lifecycle: the IN_REPAIR<->PARTS_HOLD cycle, bench scheduling overlap, and state guards."""
import test_helpers as H


# ==========================================================================
# Queue A — non-linear state machine: cyclic parts-hold / resume
# ==========================================================================
def test_parts_hold_moves_in_repair_to_parts_hold(api, associate_headers):
    """PRD §3.4: "Work then proceeds `SCHEDULED → IN_REPAIR` when the bench begins, may loop
    `IN_REPAIR → PARTS_HOLD` and back `PARTS_HOLD → IN_REPAIR` as many times as parts availability
    dictates, and reaches `IN_REPAIR → READY` when the item is ready for pickup."

    Design: Difficulty/non_linear_state_machine/repair_order_cyclic_parts_hold_resume
    """
    bench = H.new_bench(api)
    product = H.new_product(api)
    customer = H.new_customer(api)
    ro = H.in_repair_order(customer["id"], product["id"], bench["id"],
                           "2026-07-02T09:00:00Z", "2026-07-02T10:00:00Z", api=api)
    data = H.validate_success(api.parts_hold_repair_order(ro["id"], associate_headers))
    assert data["status"] == "PARTS_HOLD"


def test_resume_returns_parts_hold_to_in_repair(api, associate_headers):
    """PRD §3.4: "Work then proceeds `SCHEDULED → IN_REPAIR` when the bench begins, may loop
    `IN_REPAIR → PARTS_HOLD` and back `PARTS_HOLD → IN_REPAIR` as many times as parts availability
    dictates, and reaches `IN_REPAIR → READY` when the item is ready for pickup."

    Design: Difficulty/non_linear_state_machine/repair_order_cyclic_parts_hold_resume
    """
    bench = H.new_bench(api)
    product = H.new_product(api)
    customer = H.new_customer(api)
    ro = H.in_repair_order(customer["id"], product["id"], bench["id"],
                           "2026-07-02T09:00:00Z", "2026-07-02T10:00:00Z", api=api)
    H.get_success_data(api.parts_hold_repair_order(ro["id"], associate_headers))
    data = H.validate_success(api.resume_repair_order(ro["id"], associate_headers))
    assert data["status"] == "IN_REPAIR"


# ==========================================================================
# Queue A — resource temporal overlap: half-open bench windows
# ==========================================================================
def test_bench_adjacent_window_is_allowed(api, associate_headers):
    """PRD §2.10: "Two repairs conflict on the same bench when their half-open windows overlap;
    adjacency, where one window's end instant equals the next window's start instant, is allowed
    and is not a conflict."

    Design: Difficulty/resource_temporal_overlap/bench_half_open_adjacency_allowed_overlap_rejected
    """
    bench = H.new_bench(api)
    product = H.new_product(api)
    customer = H.new_customer(api)
    H.scheduled_repair(customer["id"], product["id"], bench["id"],
                       "2026-07-04T09:00:00Z", "2026-07-04T10:00:00Z", api=api)
    ro_b, _ = H.approved_repair(customer["id"], product["id"],
                                [{"repair_type": "HANDLE", "labor_hours": 1, "parts_cost_cents": 500}], api=api)
    data = H.validate_success(api.schedule_repair_order(
        ro_b["id"], {"bench_id": bench["id"], "bench_start": "2026-07-04T10:00:00Z",
                     "bench_end": "2026-07-04T11:00:00Z"}, associate_headers))
    assert data["status"] == "SCHEDULED"


def test_bench_overlapping_window_is_rejected(api, associate_headers):
    """PRD §2.10: "Two repairs conflict on the same bench when their half-open windows overlap;
    adjacency, where one window's end instant equals the next window's start instant, is allowed
    and is not a conflict."

    Design: Difficulty/resource_temporal_overlap/bench_half_open_adjacency_allowed_overlap_rejected
    """
    bench = H.new_bench(api)
    product = H.new_product(api)
    customer = H.new_customer(api)
    H.scheduled_repair(customer["id"], product["id"], bench["id"],
                       "2026-07-04T09:00:00Z", "2026-07-04T10:00:00Z", api=api)
    ro_c, _ = H.approved_repair(customer["id"], product["id"],
                                [{"repair_type": "ZIPPER", "labor_hours": 1, "parts_cost_cents": 500}], api=api)
    H.validate_error(api.schedule_repair_order(
        ro_c["id"], {"bench_id": bench["id"], "bench_start": "2026-07-04T09:30:00Z",
                     "bench_end": "2026-07-04T10:30:00Z"}, associate_headers),
        H.ApiErrorId.ERR_SCHEDULE_CONFLICT)
    after = H.get_repair_order(ro_c["id"], api)
    assert after["status"] == "APPROVED"


# ==========================================================================
# Queue B — state machines: approve from INTAKE is not a defined transition
# ==========================================================================
def test_approve_repair_from_intake_returns_invalid_state(api, manager_headers):
    """PRD §2.8: "4. **State validity** — the target resource is in a state from which the
    requested transition is defined, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/approve_repair_from_intake_returns_invalid_state
    """
    customer = H.new_customer(api)
    product = H.new_product(api)
    ro = H.new_repair_order(customer["id"], product["id"], api)
    H.validate_error(api.approve_repair_order(ro["id"], manager_headers), H.ApiErrorId.ERR_INVALID_STATE)
