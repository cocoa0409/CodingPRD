"""Two multi-hop cascades that no endpoint can be aimed at directly."""

from test_helpers import (
    COMPLIANCE_OFFICER,
    CONTRACT_ADMIN,
    LOGISTICS_COORDINATOR,
    MATERIALS_PLANNER,
    PLANT_ADMIN,
    QUALITY_ENGINEER,
    TEST_ENGINEER,
    assert_arc_flash_values,
    assert_bay_scheduled_hours,
    assert_bucket_allocation,
    assert_component_buckets,
    assert_order_state,
    assert_instant_equals,
    assert_quality_indices,
    assert_reason_codes_sorted,
    conclude_fat,
    create_allocation,
    create_bay,
    create_component,
    create_fat,
    create_order,
    create_release,
    create_report,
    create_supplier,
    drive_order_to_closed,
    drive_order_to_in_production,
    failure_analysis_report_payload,
    issue_label,
    issue_report,
    read_component,
    read_order,
    run_fat_to_conclusion,
    read_bay,
    schedule_fat,
    set_clock,
    start_fat,
    warranty_claim_payload,
)
from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers.api_errors import ApiErrorId


def test_concluding_fail_voids_the_label_reverts_the_release_and_freezes_the_order(api):
    """PRD 3.5: "every compliance label whose pinned test report belongs to this
    test and whose status is `GENERATED`, `VERIFIED` or `ISSUED` becomes `VOIDED`
    with `void_reason` of `FAT_FAILED`. Second, because those labels were voided,
    every shipment release on the order in status `CLEARED` reverts to `HELD`.
    Third, because releases reverted to `HELD`, the order's `production_posture`
    recomputes to `FROZEN` with the reason `LABEL_VOID`."

    Design: Difficulty/transitive_cascade/fat_fail_voids_label_then_reverts_cleared_release_then_freezes_posture_then_blocks_reclear
    """
    set_clock(api, "2026-02-01T00:00:00Z")
    supplier = create_supplier(
        api, supplier_code="SUP-C07", legal_name="Mesa Valley Cores", region="NA"
    )
    component = create_component(
        api,
        supplier["id"],
        part_number="CORE-C7",
        category="CORE_STEEL_COIL",
        lead_time_days=60,
        quantity_on_hand=10,
        allocation_policy="PROTECTED",
    )
    order = create_order(
        api,
        order_number="TX-CAS-0007",
        customer_name="Mesa Valley Power",
        product_family="POWER_TRANSFORMER",
        rated_kv=69,
        contract_value_cents=2000000,
        sold_at="2026-02-01T00:00:00Z",
        promised_ship_at="2026-12-01T00:00:00Z",
    )
    material = drive_order_to_in_production(
        api,
        order,
        component["id"],
        quantity=3,
        need_by_date="2026-07-01T00:00:00Z",
        drawing_set_code="DS-C7",
    )
    bay = create_bay(
        api, bay_code="BAY-C7", max_kv=145, changeover_buffer_hours=4,
        supports_impulse=True,
    )
    run_fat_to_conclusion(
        api,
        order["id"],
        bay["id"],
        "2026-02-10T08:00:00Z",
        "2026-02-10T09:00:00Z",
        result="PASS",
        fat_overrides={"test_duration_hours": 8, "witness_required": False},
    )
    assert read_order(api, order["id"])["fulfillment_status"] == "FAT_COMPLETE"

    second_fat = create_fat(
        api, order["id"], test_duration_hours=8, witness_required=False
    )
    schedule_fat(api, second_fat["id"], bay["id"], "2026-02-11T08:00:00Z")
    set_clock(api, "2026-02-11T09:00:00Z")
    start_fat(api, second_fat["id"])
    report_two = create_report(api, second_fat["id"])
    issue_report(api, report_two["id"])

    label = issue_label(
        api, order["id"], material["drawing"]["id"], report_two["id"]
    )
    assert label["status"] == "ISSUED"
    assert_arc_flash_values(
        label,
        incident_energy_cal_cm2=19.8,
        ppe_category=3,
        arc_flash_boundary_mm=1848,
    )

    release = create_release(api, order["id"])
    cleared = validate_success(
        api.clear_shipment_release(release["id"], {}, LOGISTICS_COORDINATOR)
    )
    assert cleared["status"] == "CLEARED"
    assert_order_state(
        read_order(api, order["id"]),
        production_posture="OPEN",
        posture_reason_codes=[],
    )

    # A third report supersedes the pinned one; an ISSUED label is not staled.
    report_three = create_report(
        api, second_fat["id"], winding_temp_rise_c=70, temp_rise_limit_c=65
    )
    issued_three = issue_report(api, report_three["id"])
    assert issued_three["pass_result"] == "FAIL"
    assert issued_three["failed_criteria"] == ["TEMP_RISE"]
    assert validate_success(
        api.get_test_report(report_two["id"], TEST_ENGINEER)
    )["status"] == "SUPERSEDED"
    assert validate_success(
        api.get_compliance_label(label["id"], COMPLIANCE_OFFICER)
    )["status"] == "ISSUED"

    failed = conclude_fat(api, second_fat["id"], "FAIL")
    assert failed["status"] == "FAILED"

    voided = validate_success(
        api.get_compliance_label(label["id"], COMPLIANCE_OFFICER)
    )
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "FAT_FAILED"
    reverted = validate_success(
        api.get_shipment_release(release["id"], LOGISTICS_COORDINATOR)
    )
    assert reverted["status"] == "HELD"
    frozen = read_order(api, order["id"])
    assert_order_state(
        frozen,
        fulfillment_status="FAT_COMPLETE",
        production_posture="FROZEN",
        posture_reason_codes=["LABEL_VOID"],
    )

    # The FAIL arm returns the bay hours and consumes no further material: the
    # PASSED first attempt never occupied the bay either, so the total is 0.
    assert_bay_scheduled_hours(read_bay(api, bay["id"]), 0)
    assert validate_success(
        api.get_component_allocation(material["allocation"]["id"], MATERIALS_PLANNER)
    )["status"] == "CONSUMED"
    assert read_component(api, component["id"])["quantity_consumed"] == 3

    # The fourth-order consequence of that one conclude call.
    validate_error(
        api.clear_shipment_release(release["id"], {}, LOGISTICS_COORDINATOR),
        ApiErrorId.POSTURE_BLOCKED,
        409,
    )
    assert validate_success(
        api.get_shipment_release(release["id"], LOGISTICS_COORDINATOR)
    )["status"] == "HELD"


def test_publishing_one_analysis_walks_five_hops_and_stops_at_the_probation_guard(api):
    """PRD 3.9: "The third hop follows from that quarantine: every allocation on
    the component in status `RESERVED` becomes `RELEASED`... The fourth hop
    follows from those releases: each affected order recomputes its
    `production_posture` to `FROZEN`... The sixth hop follows from the trailing
    index falling below 70.00".

    Design: Difficulty/transitive_cascade/far_publish_six_hop_quarantine_chain_freezes_a_second_order_but_stops_at_probation_guard
    """
    set_clock(api, "2026-01-05T00:00:00Z")
    supplier = create_supplier(
        api, supplier_code="SUP-C08", legal_name="Redstone Bushings", region="NA"
    )
    component = create_component(
        api,
        supplier["id"],
        part_number="BSH-C8",
        category="HV_BUSHING",
        lead_time_days=60,
        quantity_on_hand=10,
        allocation_policy="PREEMPTIBLE",
    )
    order_a = create_order(
        api,
        order_number="TX-CAS-0008",
        customer_name="Redstone Municipal",
        product_family="POWER_TRANSFORMER",
        rated_kv=12,
        contract_value_cents=2000000,
        promised_ship_at="2026-11-01T00:00:00Z",
    )
    bay = create_bay(api, bay_code="BAY-C8", max_kv=145, changeover_buffer_hours=4)
    pipeline = drive_order_to_closed(
        api,
        order_a,
        component["id"],
        bay["id"],
        fat_window_start_at="2026-02-10T08:00:00Z",
        fat_start_clock_at="2026-02-10T09:00:00Z",
        mobilization_at="2026-02-20T08:00:00Z",
        energize_clock_at="2026-03-01T08:00:00Z",
        quantity=3,
        need_by_date="2026-07-01T00:00:00Z",
        carrier_reference="CR-C8",
    )

    order_b = create_order(
        api,
        order_number="TX-CAS-0008B",
        customer_name="Redstone Industrial Park",
        product_family="MV_SWITCHGEAR",
        rated_kv=15,
        contract_value_cents=500000,
        sold_at="2026-03-02T00:00:00Z",
        promised_ship_at="2026-12-01T00:00:00Z",
    )
    allocation_b = create_allocation(
        api,
        component["id"],
        order_b["id"],
        quantity=2,
        priority_class=3,
        need_by_date="2026-12-01T00:00:00Z",
    )
    assert allocation_b["status"] == "RESERVED"
    assert_component_buckets(
        read_component(api, component["id"]),
        quantity_on_hand=7,
        quantity_consumed=3,
        quantity_reserved=2,
        quantity_available=5,
    )

    set_clock(api, "2026-05-10T00:00:00Z")
    claim = validate_success(
        api.create_warranty_claim(
            order_a["id"],
            warranty_claim_payload(
                claim_number="WC-C8-1",
                suspect_component_id=component["id"],
                failure_reported_at="2026-05-10T00:00:00Z",
                parts_claim_cents=50000,
                labor_claim_cents=0,
                freight_claim_cents=0,
            ),
            CONTRACT_ADMIN,
        ),
        201,
    )
    pinned = validate_success(
        api.issue_rma(claim["id"], {"rma_number": "RMA-C8-1"}, CONTRACT_ADMIN)
    )
    assert pinned["liability_cap_cents"] == 500000
    validate_success(api.receive_unit(claim["id"], {}, QUALITY_ENGINEER))
    report = validate_success(
        api.create_failure_analysis_report(
            claim["id"],
            failure_analysis_report_payload(
                attributed_supplier_id=supplier["id"],
                root_cause_code="SUPPLIER_DEFECT",
                authored_by_user_id="u_qe_2",
                quarantine_recommended=True,
                defect_weight=10,
            ),
            QUALITY_ENGINEER,
        ),
        201,
    )

    published = validate_success(
        api.publish_failure_analysis_report(report["id"], {}, QUALITY_ENGINEER)
    )
    assert published["status"] == "PUBLISHED"
    assert_instant_equals(published["published_at"], "2026-05-10T00:00:00Z")

    # Hop 1: the claim decides warrantable and runs the waterfall.
    warrantable = validate_success(api.get_warranty_claim(claim["id"], CONTRACT_ADMIN))
    assert warrantable["status"] == "WARRANTABLE"
    assert_bucket_allocation(warrantable, 50000, 0, 0, 0)

    # Hop 2 and hop 3: the component quarantines and the reserved sibling
    # allocation on a completely different order is released for nothing.
    quarantined = read_component(api, component["id"])
    assert quarantined["status"] == "QUARANTINED"
    assert quarantined["quarantine_reason"]
    released = validate_success(
        api.get_component_allocation(allocation_b["id"], MATERIALS_PLANNER)
    )
    assert released["status"] == "RELEASED"
    assert released["release_penalty_cents"] == 0
    assert_component_buckets(
        quarantined,
        quantity_reserved=0,
        quantity_committed=0,
        quantity_consumed=3,
        quantity_on_hand=7,
        quantity_available=7,
    )

    # Hop 4: the second order freezes on two collected reason codes.
    frozen_b = read_order(api, order_b["id"])
    assert_order_state(
        frozen_b,
        fulfillment_status="PLANNING",
        production_posture="FROZEN",
        posture_reason_codes=["COMPONENT_QUARANTINE", "MATERIAL_INCOMPLETE"],
    )
    assert_reason_codes_sorted(frozen_b)

    # Hop 5 fires and hop 6 does not: the guard reads the trailing index.
    scored = validate_success(api.get_supplier(supplier["id"], QUALITY_ENGINEER))
    assert scored["attributed_failure_count"] == 1
    assert scored["receipt_event_count"] == 0
    assert_quality_indices(scored, 87.50, 0.00)
    assert scored["status"] == "APPROVED"
    assert scored["probation_entered_at"] is None

    # Order A is untouched: a CONSUMED allocation is not a RELEASED one, and the
    # credit only reaches the order at settlement.
    assert validate_success(
        api.get_component_allocation(
            pipeline["allocation"]["id"], MATERIALS_PLANNER
        )
    )["status"] == "CONSUMED"
    final_a = read_order(api, order_a["id"])
    assert_order_state(
        final_a,
        production_posture="RESTRICTED",
        posture_reason_codes=["ORDER_FULFILLED"],
    )
    assert final_a["warranty_credit_total_cents"] == 0
    assert final_a["net_contract_value_cents"] == 2000000
    validate_success(api.get_supplier(supplier["id"], PLANT_ADMIN))
