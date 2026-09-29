"""Read-your-write behaviour: denormalised counters, the derived money view and
the supplier index all settle inside the write that moved them."""

from test_helpers import (
    CONTRACT_ADMIN,
    MATERIALS_PLANNER,
    PLANT_ADMIN,
    QUALITY_ENGINEER,
    assert_component_buckets,
    assert_quality_indices,
    component_allocation_payload,
    create_component,
    create_order,
    create_supplier,
    set_clock,
)
from prd_bench_local_runner.testing import validate_success

_CLOCK = "2026-03-02T08:00:00Z"


def _order(api, order_number):
    return create_order(
        api,
        order_number=order_number,
        customer_name="Riverbend Utility",
        product_family="MV_SWITCHGEAR",
        rated_kv=15,
        contract_value_cents=4000000,
        sold_at="2026-01-05T00:00:00Z",
        promised_ship_at="2026-10-01T00:00:00Z",
    )


def test_the_reservation_counters_are_settled_by_the_time_the_write_returns(api):
    """PRD 2.9: "`quantity_on_hand` always equals `quantity_available` plus
    `quantity_reserved` plus `quantity_committed` after every mutation."

    Design: Corner/consistency_model/component_reservation_counters_are_visible_without_any_re_read_delay
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-CM1")
    supplier = create_supplier(
        api,
        supplier_code="SUP-CM1",
        legal_name="Northline Copperworks GmbH",
        region="NA",
    )
    component = create_component(
        api,
        supplier["id"],
        part_number="PN-CM1-1",
        category="HV_BUSHING",
        lead_time_days=150,
        quantity_on_hand=10,
        allocation_policy="PREEMPTIBLE",
    )

    allocation = validate_success(
        api.create_component_allocation(
            component_allocation_payload(
                component["id"],
                order["id"],
                component["version"],
                quantity=4,
                priority_class=3,
                need_by_date="2026-06-01T00:00:00Z",
            ),
            MATERIALS_PLANNER,
        ),
        201,
    )
    assert allocation["status"] == "RESERVED"
    assert allocation["quantity"] == 4

    first_read = validate_success(
        api.get_long_lead_component(component["id"], MATERIALS_PLANNER)
    )
    assert_component_buckets(
        first_read,
        quantity_on_hand=10,
        quantity_reserved=4,
        quantity_committed=0,
        quantity_available=6,
    )

    # Nothing settles later: a repeat read is identical.
    second_read = validate_success(
        api.get_long_lead_component(component["id"], MATERIALS_PLANNER)
    )
    assert_component_buckets(
        second_read,
        quantity_on_hand=10,
        quantity_reserved=4,
        quantity_committed=0,
        quantity_available=6,
    )


def test_the_money_view_is_derived_and_never_serves_the_pre_patch_figure(api):
    """PRD 3.1: "amending re-derives `net_contract_value_cents` and increments the
    order's `version`"; the financial-summary read returns "`contract_value_cents`,
    `escalation_accepted_total_cents`, `warranty_credit_total_cents`,
    `net_contract_value_cents` and `billed_to_date_cents` together."

    Design: Corner/consistency_model/financial_summary_recomputes_from_the_patched_contract_value_on_the_next_request
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-CM2")

    before = validate_success(
        api.get_order_financial_summary(order["id"], CONTRACT_ADMIN)
    )
    assert before["contract_value_cents"] == 4000000
    assert before["net_contract_value_cents"] == 4000000

    validate_success(
        api.patch_engineered_order(
            order["id"], {"contract_value_cents": 7000000}, CONTRACT_ADMIN
        )
    )
    after = validate_success(
        api.get_order_financial_summary(order["id"], CONTRACT_ADMIN)
    )
    assert after["contract_value_cents"] == 7000000
    assert after["net_contract_value_cents"] == 7000000

    for summary in (before, after):
        assert summary["escalation_accepted_total_cents"] == 0
        assert summary["warranty_credit_total_cents"] == 0
        assert summary["billed_to_date_cents"] == 0


def test_the_receipt_counter_and_the_index_move_together_in_one_write(api):
    """PRD 3.9: "The supplier quality index exists in two variants that are always
    computed together, after any report enters `PUBLISHED` or `RETRACTED` and after a
    receipt event is recorded."

    Design: Corner/consistency_model/supplier_receipt_counter_and_quality_index_move_in_the_same_write
    """
    set_clock(api, _CLOCK)
    supplier = create_supplier(
        api,
        supplier_code="SUP-CM3",
        legal_name="Northline Copperworks GmbH",
        region="APAC",
    )

    before = validate_success(api.get_supplier(supplier["id"], QUALITY_ENGINEER))
    assert before["receipt_event_count"] == 0
    assert before["attributed_failure_count"] == 0
    assert_quality_indices(before, 100.00, 100.00)

    validate_success(
        api.create_receipt_event(supplier["id"], {"event_count": 1}, MATERIALS_PLANNER)
    )
    after = validate_success(api.get_supplier(supplier["id"], QUALITY_ENGINEER))
    assert after["receipt_event_count"] == 1
    assert after["attributed_failure_count"] == 0
    assert_quality_indices(after, 100.00, 100.00)

    repeat = validate_success(api.get_supplier(supplier["id"], PLANT_ADMIN))
    assert repeat["receipt_event_count"] == 1
    assert_quality_indices(repeat, 100.00, 100.00)
