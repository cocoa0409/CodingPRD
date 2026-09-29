"""Unit conservation across every operation that touches the four buckets:
reserve, commit, receipt, preempt, release and consume."""

from test_helpers import (
    MATERIALS_PLANNER,
    assert_component_buckets,
    assert_component_conservation,
    assert_order_state,
    commit_allocation,
    create_allocation,
    create_bay,
    create_component,
    create_order,
    create_supplier,
    read_component,
    read_order,
    release_design,
    run_fat_to_conclusion,
    set_clock,
    start_production,
)
from prd_bench_local_runner.testing import validate_success


def test_the_conserved_unit_total_only_ever_moves_when_a_receipt_or_a_consume_says_so(api):
    """PRD 2.9: "`quantity_on_hand` always equals `quantity_available` plus
    `quantity_reserved` plus `quantity_committed` after every mutation"; PRD 3.4:
    "Goods receipts are the
    only operation that grows the pool"; and the preemption selector admits
    allocations "in status `RESERVED`, whose `priority_class` is a strictly larger
    number than the incoming allocation's `priority_class`, whose
    `engineered_order_id` differs from the incoming allocation's order, and only
    when the component's `allocation_policy` is `PREEMPTIBLE`".

    Design: Difficulty/compensating_invariant/component_unit_conservation_across_reserve_commit_receipt_preempt_release_and_consume
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    order_a = create_order(
        api,
        order_number="TX-CON-0001",
        customer_name="Summit Grid",
        product_family="POWER_TRANSFORMER",
        rated_kv=12,
        contract_value_cents=20000000,
        sold_at="2026-02-01T00:00:00Z",
        promised_ship_at="2026-12-01T00:00:00Z",
    )
    release_design(api, order_a, drawing_set_code="DS-CON-A")
    order_b = create_order(
        api,
        order_number="TX-CON-0002",
        customer_name="Summit Grid",
        product_family="MV_SWITCHGEAR",
        rated_kv=15,
        contract_value_cents=5000000,
        sold_at="2026-02-02T00:00:00Z",
        promised_ship_at="2027-01-15T00:00:00Z",
    )
    supplier = create_supplier(
        api, supplier_code="SUP-CON", legal_name="Summit Bushing Co", region="NA"
    )
    component = create_component(
        api,
        supplier["id"],
        part_number="CON-BSH",
        category="HV_BUSHING",
        lead_time_days=20,
        quantity_on_hand=10,
        allocation_policy="PREEMPTIBLE",
    )
    bay = create_bay(
        api, bay_code="BAY-CON", max_kv=145, changeover_buffer_hours=2,
        supports_impulse=False,
    )

    # Observation 1 -- reserve moves units out of available into reserved.
    alloc_a = create_allocation(
        api,
        component["id"],
        order_a["id"],
        quantity=6,
        priority_class=4,
        need_by_date="2026-10-01T00:00:00Z",
    )
    assert alloc_a["status"] == "RESERVED"
    after_reserve = read_component(api, component["id"])
    assert_component_buckets(
        after_reserve,
        quantity_on_hand=10,
        quantity_reserved=6,
        quantity_committed=0,
        quantity_consumed=0,
        quantity_available=4,
    )
    assert_component_conservation(after_reserve, 10)

    # Observation 2 -- commit is a pure internal move between two buckets.
    assert commit_allocation(api, alloc_a["id"])["status"] == "COMMITTED"
    after_commit = read_component(api, component["id"])
    assert_component_buckets(
        after_commit,
        quantity_on_hand=10,
        quantity_reserved=0,
        quantity_committed=6,
        quantity_consumed=0,
        quantity_available=4,
    )
    assert_component_conservation(after_commit, 10)
    assert read_order(api, order_a["id"])["fulfillment_status"] == "MATERIAL_ALLOCATED"

    # Observation 3 -- the only operation permitted to grow the conserved total.
    # PRD 4: "A successful creation returns HTTP 201; every other successful
    # operation... returns HTTP 200." A receipt creates no resource of its own;
    # it mutates the component, which is what the response body carries.
    validate_success(
        api.create_component_receipt(component["id"], {"quantity": 2}, MATERIALS_PLANNER)
    )
    after_receipt = read_component(api, component["id"])
    assert_component_buckets(
        after_receipt,
        quantity_on_hand=12,
        quantity_reserved=0,
        quantity_committed=6,
        quantity_consumed=0,
        quantity_available=6,
    )
    assert_component_conservation(after_receipt, 12)

    # Observation 4 -- a second order drains availability to exactly zero.
    alloc_b = create_allocation(
        api,
        component["id"],
        order_b["id"],
        quantity=6,
        priority_class=4,
        need_by_date="2026-11-01T00:00:00Z",
    )
    assert alloc_b["status"] == "RESERVED"
    after_second_reserve = read_component(api, component["id"])
    assert_component_buckets(
        after_second_reserve,
        quantity_on_hand=12,
        quantity_reserved=6,
        quantity_committed=6,
        quantity_available=0,
    )
    assert_component_conservation(after_second_reserve, 12)

    # Observation 5 -- a 2-unit shortfall displaces a whole 6-unit reservation,
    # and the preempted row then contributes to no bucket at all.
    alloc_c = create_allocation(
        api,
        component["id"],
        order_a["id"],
        quantity=2,
        priority_class=1,
        need_by_date="2026-10-01T00:00:00Z",
    )
    assert alloc_c["status"] == "RESERVED"
    preempted = validate_success(
        api.get_component_allocation(alloc_b["id"], MATERIALS_PLANNER)
    )
    assert preempted["status"] == "PREEMPTED"
    assert preempted["preempted_for_allocation_id"] == alloc_c["id"]
    victim_order = read_order(api, order_b["id"])
    assert victim_order["production_posture"] == "RESTRICTED"
    assert "MATERIAL_PREEMPTED" in victim_order["posture_reason_codes"]
    after_preempt = read_component(api, component["id"])
    assert_component_buckets(
        after_preempt,
        quantity_on_hand=12,
        quantity_reserved=2,
        quantity_committed=6,
        quantity_consumed=0,
        quantity_available=4,
    )
    assert_component_conservation(after_preempt, 12)

    # Observation 6 -- releasing a reserved row returns its units and accrues no
    # penalty, and it does not drag the order's fulfilment backwards because a
    # committed row survives.
    released = validate_success(
        api.release_component_allocation(
            alloc_c["id"],
            {"reason": "Design shrank the bushing count"},
            MATERIALS_PLANNER,
        )
    )
    assert released["status"] == "RELEASED"
    assert released["release_penalty_cents"] == 0
    after_release = read_component(api, component["id"])
    assert_component_buckets(
        after_release,
        quantity_on_hand=12,
        quantity_reserved=0,
        quantity_committed=6,
        quantity_available=6,
    )
    assert_component_conservation(after_release, 12)
    assert_order_state(
        read_order(api, order_a["id"]),
        fulfillment_status="MATERIAL_ALLOCATED",
        production_posture="OPEN",
        posture_reason_codes=[],
    )

    # Observation 7 -- consume moves units between the two conserved terms.
    start_production(api, order_a["id"])
    run_fat_to_conclusion(
        api,
        order_a["id"],
        bay["id"],
        "2026-06-20T08:00:00Z",
        "2026-06-20T09:00:00Z",
        result="PASS",
        fat_overrides={"test_duration_hours": 6, "witness_required": False},
        report_overrides={
            "winding_temp_rise_c": 55,
            "temp_rise_limit_c": 65,
            "short_circuit_current_ka": 25,
            "arc_duration_ms": 200,
            "working_distance_mm": 455,
        },
    )
    assert validate_success(
        api.get_component_allocation(alloc_a["id"], MATERIALS_PLANNER)
    )["status"] == "CONSUMED"
    after_consume = read_component(api, component["id"])
    assert_component_buckets(
        after_consume,
        quantity_on_hand=6,
        quantity_reserved=0,
        quantity_committed=0,
        quantity_consumed=6,
        quantity_available=6,
    )
    assert_component_conservation(after_consume, 12)
