"""Supplier scoring: the two index variants, probation, suspension and the
exact reversal a retraction owes."""

from test_helpers import (
    CONTRACT_ADMIN,
    MATERIALS_PLANNER,
    PLANT_ADMIN,
    QUALITY_ENGINEER,
    assert_component_buckets,
    assert_order_state,
    assert_quality_indices,
    create_allocation,
    create_bay,
    create_component,
    create_order,
    create_supplier,
    drive_order_to_closed,
    failure_analysis_report_payload,
    read_component,
    read_order,
    set_clock,
    warranty_claim_payload,
)
from prd_bench_local_runner.testing import validate_success

QE_AUTHOR = "u_qe_2"


def _open_and_publish(
    api,
    order_id,
    supplier_id,
    component_id,
    claim_number,
    rma_number,
    defect_weight,
    quarantine_recommended,
    parts_claim_cents,
    failure_reported_at,
):
    claim = validate_success(
        api.create_warranty_claim(
            order_id,
            warranty_claim_payload(
                claim_number=claim_number,
                suspect_component_id=component_id,
                failure_reported_at=failure_reported_at,
                parts_claim_cents=parts_claim_cents,
                labor_claim_cents=0,
                freight_claim_cents=0,
            ),
            CONTRACT_ADMIN,
        ),
        201,
    )
    validate_success(
        api.issue_rma(claim["id"], {"rma_number": rma_number}, CONTRACT_ADMIN)
    )
    validate_success(api.receive_unit(claim["id"], {}, QUALITY_ENGINEER))
    report = validate_success(
        api.create_failure_analysis_report(
            claim["id"],
            failure_analysis_report_payload(
                attributed_supplier_id=supplier_id,
                root_cause_code="SUPPLIER_DEFECT",
                authored_by_user_id=QE_AUTHOR,
                quarantine_recommended=quarantine_recommended,
                defect_weight=defect_weight,
            ),
            QUALITY_ENGINEER,
        ),
        201,
    )
    validate_success(
        api.publish_failure_analysis_report(report["id"], {}, QUALITY_ENGINEER)
    )
    return claim, report


def test_trailing_denominator_floor_diverges_from_lifetime_suspension_gate(api):
    """PRD 3.9: for the trailing variant "its denominator is the greater of the
    supplier's `receipt_event_count` and 8", while for the lifetime variant "its
    denominator is the greater of `receipt_event_count` and 1"; a `PlantAdmin` may
    "suspend a supplier, with an optional `reason`, and only when
    `quality_index_lifetime` is strictly below 60."

    Design: Difficulty/dual_variant_calc/supplier_quality_trailing_denominator_floor_vs_lifetime_suspension_gate
    """
    set_clock(api, "2026-01-05T00:00:00Z")
    supplier = create_supplier(
        api, supplier_code="SUP-QI", legal_name="Northbank Bushings", region="NA"
    )
    validate_success(
        api.create_receipt_event(supplier["id"], {"event_count": 2}, MATERIALS_PLANNER)
    )
    component = create_component(
        api,
        supplier["id"],
        part_number="QI-BSH",
        category="HV_BUSHING",
        lead_time_days=25,
        quantity_on_hand=10,
        allocation_policy="PROTECTED",
    )
    order = create_order(
        api,
        order_number="TX-QI-0001",
        product_family="MV_SWITCHGEAR",
        rated_kv=15,
        contract_value_cents=4000000,
    )
    bay = create_bay(api, bay_code="BAY-QI", max_kv=145, changeover_buffer_hours=2)
    drive_order_to_closed(
        api,
        order,
        component["id"],
        bay["id"],
        fat_window_start_at="2026-02-10T08:00:00Z",
        fat_start_clock_at="2026-02-10T09:00:00Z",
        mobilization_at="2026-04-20T08:00:00Z",
        energize_clock_at="2026-05-01T08:00:00Z",
        quantity=2,
        need_by_date="2026-12-01T00:00:00Z",
        carrier_reference="CR-QI",
    )

    set_clock(api, "2026-06-01T00:00:00Z")
    baseline = validate_success(api.get_supplier(supplier["id"], PLANT_ADMIN))
    assert baseline["receipt_event_count"] == 2
    assert baseline["attributed_failure_count"] == 0
    assert_quality_indices(baseline, 100.00, 100.00)

    # Three attributed defects of weight 10 each, published one at a time.
    expected = [(1, 87.50, 50.00, "APPROVED"), (2, 75.00, 0.00, "APPROVED"),
                (3, 62.50, 0.00, "PROBATION")]
    last_claim = None
    for round_index, (count, trailing, lifetime, status) in enumerate(expected, start=1):
        last_claim, _ = _open_and_publish(
            api,
            order["id"],
            supplier["id"],
            component["id"],
            claim_number=f"WC-QI-{round_index}",
            rma_number=f"RMA-QI-{round_index}",
            defect_weight=10,
            quarantine_recommended=False,
            parts_claim_cents=100000,
            failure_reported_at="2026-06-01T00:00:00Z",
        )
        refreshed = validate_success(api.get_supplier(supplier["id"], PLANT_ADMIN))
        assert refreshed["attributed_failure_count"] == count
        assert_quality_indices(refreshed, trailing, lifetime)
        assert refreshed["status"] == status

    probationed = validate_success(api.get_supplier(supplier["id"], PLANT_ADMIN))
    assert probationed["probation_entered_at"] is not None

    # The lifetime variant, clamped to 0.00, is what unlocks suspension even
    # though the trailing variant still reads 62.50.
    suspended = validate_success(
        api.suspend_supplier(supplier["id"], {"reason": "Sustained defect rate"}, PLANT_ADMIN)
    )
    assert suspended["status"] == "SUSPENDED"

    assert validate_success(api.get_warranty_claim(last_claim["id"], CONTRACT_ADMIN))[
        "status"
    ] == "WARRANTABLE"


def test_retracting_a_published_analysis_restores_indices_but_not_allocations(api):
    """PRD 3.9: retracting a published report "decreases the attributed
    supplier's `attributed_failure_count` by 1 and recomputes both index
    variants, and returns the suspect component `QUARANTINED → ACTIVE` provided
    no other published report still recommends its quarantine" -- the released
    allocations of the third hop are not restored.

    Design: Difficulty/compensating_invariant/far_retract_restores_supplier_indices_exactly_but_never_un_releases_the_allocations
    """
    set_clock(api, "2026-01-05T00:00:00Z")
    supplier = create_supplier(
        api, supplier_code="SUP-FAR", legal_name="Farland Components", region="EU"
    )
    validate_success(
        api.create_receipt_event(supplier["id"], {"event_count": 4}, MATERIALS_PLANNER)
    )
    component = create_component(
        api,
        supplier["id"],
        part_number="FAR-BSH",
        category="HV_BUSHING",
        lead_time_days=25,
        quantity_on_hand=10,
        allocation_policy="PREEMPTIBLE",
    )
    order_a = create_order(
        api,
        order_number="TX-FAR-0001",
        product_family="POWER_TRANSFORMER",
        rated_kv=12,
        contract_value_cents=30000000,
    )
    bay = create_bay(api, bay_code="BAY-FAR", max_kv=145, changeover_buffer_hours=2)
    drive_order_to_closed(
        api,
        order_a,
        component["id"],
        bay["id"],
        fat_window_start_at="2026-02-10T08:00:00Z",
        fat_start_clock_at="2026-02-10T09:00:00Z",
        mobilization_at="2026-04-20T08:00:00Z",
        energize_clock_at="2026-05-01T08:00:00Z",
        quantity=2,
        need_by_date="2026-12-01T00:00:00Z",
        carrier_reference="CR-FAR",
    )

    order_c = create_order(
        api,
        order_number="TX-FAR-0003",
        product_family="MV_SWITCHGEAR",
        rated_kv=15,
        contract_value_cents=4000000,
    )
    allocation_c = create_allocation(
        api,
        component["id"],
        order_c["id"],
        quantity=3,
        priority_class=3,
        need_by_date="2026-12-01T00:00:00Z",
    )

    baseline_supplier = validate_success(api.get_supplier(supplier["id"], PLANT_ADMIN))
    assert baseline_supplier["status"] == "APPROVED"
    assert baseline_supplier["attributed_failure_count"] == 0
    assert baseline_supplier["receipt_event_count"] == 4
    assert_quality_indices(baseline_supplier, 100.00, 100.00)
    baseline_component = read_component(api, component["id"])
    assert baseline_component["status"] == "ACTIVE"
    assert_component_buckets(
        baseline_component,
        quantity_on_hand=8,
        quantity_consumed=2,
        quantity_reserved=3,
        quantity_available=5,
    )

    set_clock(api, "2026-06-01T00:00:00Z")
    claim_1, report_1 = _open_and_publish(
        api,
        order_a["id"],
        supplier["id"],
        component["id"],
        claim_number="WC-FAR-1",
        rma_number="RMA-FAR-1",
        defect_weight=7,
        quarantine_recommended=True,
        parts_claim_cents=100000,
        failure_reported_at="2026-06-01T00:00:00Z",
    )
    after_first = validate_success(api.get_supplier(supplier["id"], PLANT_ADMIN))
    assert after_first["attributed_failure_count"] == 1
    assert_quality_indices(after_first, 91.25, 82.50)
    assert after_first["status"] == "APPROVED"
    quarantined = read_component(api, component["id"])
    assert quarantined["status"] == "QUARANTINED"
    assert_component_buckets(
        quarantined, quantity_reserved=0, quantity_available=8, quantity_on_hand=8
    )
    released = validate_success(
        api.get_component_allocation(allocation_c["id"], MATERIALS_PLANNER)
    )
    assert released["status"] == "RELEASED"
    assert released["release_penalty_cents"] == 0
    assert_order_state(
        read_order(api, order_c["id"]),
        production_posture="FROZEN",
        posture_reason_codes=["COMPONENT_QUARANTINE", "MATERIAL_INCOMPLETE"],
    )
    assert validate_success(api.get_warranty_claim(claim_1["id"], CONTRACT_ADMIN))[
        "status"
    ] == "WARRANTABLE"

    claim_2, report_2 = _open_and_publish(
        api,
        order_a["id"],
        supplier["id"],
        component["id"],
        claim_number="WC-FAR-2",
        rma_number="RMA-FAR-2",
        defect_weight=5,
        quarantine_recommended=False,
        parts_claim_cents=80000,
        failure_reported_at="2026-06-01T00:00:00Z",
    )
    after_second = validate_success(api.get_supplier(supplier["id"], PLANT_ADMIN))
    assert after_second["attributed_failure_count"] == 2
    assert_quality_indices(after_second, 85.00, 70.00)
    assert validate_success(
        api.get_component_allocation(allocation_c["id"], MATERIALS_PLANNER)
    )["status"] == "RELEASED"

    validate_success(
        api.retract_failure_analysis_report(
            report_2["id"], {"retraction_reason": "Second finding withdrawn"}, QUALITY_ENGINEER
        )
    )
    after_retract_two = validate_success(api.get_supplier(supplier["id"], PLANT_ADMIN))
    assert after_retract_two["attributed_failure_count"] == 1
    assert_quality_indices(after_retract_two, 91.25, 82.50)
    reverted_claim_2 = validate_success(
        api.get_warranty_claim(claim_2["id"], CONTRACT_ADMIN)
    )
    assert reverted_claim_2["status"] == "ANALYSIS_IN_PROGRESS"
    assert reverted_claim_2["analysis_round"] == 1
    assert reverted_claim_2["credit_issued_cents"] == 0
    assert read_component(api, component["id"])["status"] == "QUARANTINED"

    validate_success(
        api.retract_failure_analysis_report(
            report_1["id"], {"retraction_reason": "First finding withdrawn"}, QUALITY_ENGINEER
        )
    )
    after_retract_one = validate_success(api.get_supplier(supplier["id"], PLANT_ADMIN))
    assert after_retract_one["attributed_failure_count"] == 0
    assert_quality_indices(after_retract_one, 100.00, 100.00)
    assert validate_success(api.get_warranty_claim(claim_1["id"], CONTRACT_ADMIN))[
        "status"
    ] == "ANALYSIS_IN_PROGRESS"
    restored_component = read_component(api, component["id"])
    assert restored_component["status"] == "ACTIVE"
    assert restored_component["quarantine_reason"] is None

    # The asymmetry: the supplier score is restored bit for bit, the allocation
    # released by the third hop is not.
    assert validate_success(
        api.get_component_allocation(allocation_c["id"], MATERIALS_PLANNER)
    )["status"] == "RELEASED"
    assert_component_buckets(
        restored_component, quantity_reserved=0, quantity_available=8, quantity_on_hand=8
    )
    assert (
        restored_component["quantity_on_hand"] + restored_component["quantity_consumed"]
    ) == 10
    order_a_final = read_order(api, order_a["id"])
    assert order_a_final["warranty_credit_total_cents"] == 0
    assert order_a_final["net_contract_value_cents"] == 30000000
