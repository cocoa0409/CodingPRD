"""The restocking penalty on a released allocation: every branch of the tier
table plus the ceiling and the reserved edge that never computes at all."""

from test_helpers import (
    MATERIALS_PLANNER,
    assert_component_buckets,
    commit_allocation,
    create_allocation,
    create_component,
    create_order,
    create_supplier,
    read_component,
    read_order,
    release_design,
    set_clock,
)
from prd_bench_local_runner.testing import validate_success


def test_release_penalty_spans_both_tier_edges_the_ceiling_and_the_reserved_edge(api):
    """PRD 3.4: "A component whose `lead_time_days` is 30 or fewer attracts no
    per-unit penalty at all... between 31 and 120 inclusive attracts twenty-five
    thousand cents... 121 or more attracts sixty thousand cents... A ceiling then
    applies: the order's `contract_value_cents` multiplied by five and divided by
    one hundred... A release out of `RESERVED` never runs this computation and
    its `release_penalty_cents` stays 0."

    Design: Difficulty/combinatorial_formula/release_penalty_lead_time_tier_120_vs_121_vs_five_percent_ceiling_vs_reserved_release
    """
    set_clock(api, "2026-01-05T00:00:00Z")
    order = create_order(
        api,
        order_number="TX-REL-0004",
        customer_name="Cascade Power",
        product_family="POWER_TRANSFORMER",
        rated_kv=69,
        contract_value_cents=4000000,
        promised_ship_at="2026-12-01T00:00:00Z",
    )
    release_design(api, order, drawing_set_code="DS-R")

    supplier = create_supplier(
        api, supplier_code="SUP-R04", legal_name="Cascade Components", region="NA"
    )

    def component(part_number, category, lead_time_days):
        return create_component(
            api,
            supplier["id"],
            part_number=part_number,
            category=category,
            lead_time_days=lead_time_days,
            quantity_on_hand=20,
            allocation_policy="PROTECTED",
        )

    cmp_a = component("CMP-A", "HV_BUSHING", 30)
    cmp_b = component("CMP-B", "TAP_CHANGER", 120)
    cmp_c = component("CMP-C", "CORE_STEEL_COIL", 121)

    def allocate(comp, quantity):
        return create_allocation(
            api,
            comp["id"],
            order["id"],
            quantity=quantity,
            priority_class=3,
            need_by_date="2026-08-01T00:00:00Z",
        )

    alloc_a = allocate(cmp_a, 3)
    alloc_b = allocate(cmp_b, 2)
    alloc_c = allocate(cmp_c, 2)
    alloc_d = allocate(cmp_c, 4)
    alloc_e = allocate(cmp_a, 1)

    for allocation in (alloc_a, alloc_b, alloc_c, alloc_d):
        assert commit_allocation(api, allocation["id"])["status"] == "COMMITTED"

    def release(allocation):
        return validate_success(
            api.release_component_allocation(
                allocation["id"], {"reason": "Scope change"}, MATERIALS_PLANNER
            )
        )

    # Lead time exactly at the first tier limit: no per-unit rate at all.
    released_a = release(alloc_a)
    assert released_a["release_penalty_cents"] == 0

    # 120 days is still the middle tier; 121 days multiplies the rate by 2.4.
    assert release(alloc_b)["release_penalty_cents"] == 50000
    assert release(alloc_c)["release_penalty_cents"] == 120000

    # A raw 240000 is clamped to the five-percent ceiling of 200000.
    assert release(alloc_d)["release_penalty_cents"] == 200000

    # The reserved edge never runs the computation.
    released_e = release(alloc_e)
    assert released_e["release_penalty_cents"] == 0

    for allocation in (alloc_a, alloc_b, alloc_c, alloc_d, alloc_e):
        assert validate_success(
            api.get_component_allocation(allocation["id"], MATERIALS_PLANNER)
        )["status"] == "RELEASED"

    final_c = read_component(api, cmp_c["id"])
    assert_component_buckets(final_c, quantity_available=20, quantity_committed=0)
    final_a = read_component(api, cmp_a["id"])
    assert_component_buckets(final_a, quantity_reserved=0, quantity_committed=0)

    # One allocation stayed RESERVED for the whole recipe, so the order never
    # reached MATERIAL_ALLOCATED and the ceiling never had to be re-derived.
    assert read_order(api, order["id"])["fulfillment_status"] == "PLANNING"
