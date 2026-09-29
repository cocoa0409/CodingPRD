"""The validation ladder: when several rungs hold at once, only the lowest
rung number is allowed to surface."""

from test_helpers import (
    COMPLIANCE_OFFICER,
    DESIGN_ENGINEER,
    LOGISTICS_COORDINATOR,
    MATERIALS_PLANNER,
    USER_COMPLIANCE_1,
    USER_DESIGN_1,
    USER_QUALITY_1,
    assert_component_buckets,
    assert_order_state,
    component_allocation_payload,
    create_bay,
    create_component,
    create_drawing,
    create_label,
    create_order,
    create_release,
    create_supplier,
    drive_order_to_in_production,
    issue_label,
    make_headers,
    read_component,
    read_order,
    run_fat_to_conclusion,
    set_clock,
    submit_drawing,
)
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId

_FAT_READINGS = {
    "winding_temp_rise_c": 50,
    "temp_rise_limit_c": 65,
    "short_circuit_current_ka": 20,
    "arc_duration_ms": 150,
    "working_distance_mm": 455,
}


def test_segregation_of_duties_outranks_the_staleness_of_the_very_same_label(api):
    """PRD 2.11: "The ladder has eighty-two rungs grouped into nine bands, and the
    band order is: authentication and authorisation (rungs 1–6), existence
    resolution (7–26), payload shape and enum domains (27–31), optimistic
    concurrency (32–33), state preconditions (34–41), safety and compliance
    (42–53)"; PRD 2.1: "Verifying a compliance label requires that the verifier
    differ from the operator who generated it."

    Design: Difficulty/priority_pair_validation_conflict/label_verify_sod_p5_beats_label_stale_p43_then_same_row_yields_p43_with_a_clean_actor
    """
    set_clock(api, "2026-02-01T00:00:00Z")
    order = create_order(
        api,
        order_number="TX-PRI-0009",
        customer_name="Coldwater Utilities",
        product_family="POWER_TRANSFORMER",
        rated_kv=12,
        contract_value_cents=1500000,
        sold_at="2026-02-01T00:00:00Z",
        promised_ship_at="2026-12-01T00:00:00Z",
    )
    supplier = create_supplier(
        api, supplier_code="SUP-P09", legal_name="Coldwater Cores", region="NA"
    )
    component = create_component(
        api,
        supplier["id"],
        part_number="CORE-P9",
        category="CORE_STEEL_COIL",
        lead_time_days=40,
        quantity_on_hand=6,
        allocation_policy="PROTECTED",
    )
    material = drive_order_to_in_production(
        api,
        order,
        component["id"],
        quantity=2,
        need_by_date="2026-07-01T00:00:00Z",
        drawing_set_code="DS-P9-R1",
    )
    bay = create_bay(
        api, bay_code="BAY-P9", max_kv=145, changeover_buffer_hours=4,
        supports_impulse=True,
    )
    outcome = run_fat_to_conclusion(
        api,
        order["id"],
        bay["id"],
        "2026-02-10T08:00:00Z",
        "2026-02-10T09:00:00Z",
        result="PASS",
        report_overrides=dict(_FAT_READINGS),
    )

    # The generating operator is deliberately the same person who will later be
    # asked to verify, and the label is left un-verified.
    generator = make_headers(USER_QUALITY_1, "ComplianceOfficer")
    label = create_label(
        api,
        order["id"],
        material["drawing"]["id"],
        outcome["report"]["id"],
        generated_by_user_id=USER_QUALITY_1,
    )
    generated = validate_success(
        api.generate_compliance_label(label["id"], {}, generator)
    )
    assert generated["status"] == "GENERATED"
    assert generated["generated_by_user_id"] == USER_QUALITY_1
    assert generated["pinned_drawing_revision"] == 1

    # A second revision re-opens engineering and stales the label, so the
    # staleness rung (43) is live on exactly the row we are about to verify.
    revision_two = create_drawing(
        api, order["id"], drawing_set_code="DS-P9-R2", authored_by_user_id=USER_DESIGN_1
    )
    submitted = submit_drawing(api, revision_two["id"])
    assert submitted["revision_round"] == 2
    stale = validate_success(
        api.get_compliance_label(label["id"], COMPLIANCE_OFFICER)
    )
    assert stale["status"] == "STALE"
    assert stale["pinned_drawing_revision"] == 1
    reopened = read_order(api, order["id"])
    assert reopened["engineering_status"] == "SUBMITTAL_IN_REVIEW"
    assert reopened["released_drawing_revision"] == 1
    stale_version = stale["version"]

    # Both the authorisation rung and the compliance rung hold on this one row.
    # The authorisation band is evaluated first, so 403 must surface, not 409.
    validate_error(
        api.verify_compliance_label(
            label["id"],
            {"verified_by_user_id": USER_QUALITY_1},
            make_headers(USER_QUALITY_1, "QualityEngineer"),
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        403,
    )

    untouched = validate_success(
        api.get_compliance_label(label["id"], COMPLIANCE_OFFICER)
    )
    assert untouched["status"] == "STALE"
    assert untouched["verified_by_user_id"] is None
    assert untouched["version"] == stale_version


def test_a_frozen_posture_outranks_both_compliance_rungs_it_was_born_from(api):
    """PRD 2.11: "state preconditions (34–41), safety and compliance (42–53)... A
    capacity failure never masks a state failure"; and "five posture-gated
    operations — starting production, clearing a release, shipping a release,
    committing an allocation and issuing a label — reject a blocking posture with
    `ERR_POSTURE_BLOCKED` (HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/shipment_clear_posture_p39_beats_label_stale_p43_and_label_not_issued_p44_from_one_fact
    """
    set_clock(api, "2026-02-01T00:00:00Z")
    order = create_order(
        api,
        order_number="TX-PRI-0010",
        customer_name="Ridgeline Cooperative",
        product_family="POWER_TRANSFORMER",
        rated_kv=12,
        contract_value_cents=1500000,
        sold_at="2026-02-01T00:00:00Z",
        promised_ship_at="2026-12-01T00:00:00Z",
    )
    supplier = create_supplier(
        api, supplier_code="SUP-P10", legal_name="Ridgeline Cores", region="NA"
    )
    component = create_component(
        api,
        supplier["id"],
        part_number="CORE-P10",
        category="CORE_STEEL_COIL",
        lead_time_days=40,
        quantity_on_hand=6,
        allocation_policy="PROTECTED",
    )
    material = drive_order_to_in_production(
        api,
        order,
        component["id"],
        quantity=2,
        need_by_date="2026-07-01T00:00:00Z",
        drawing_set_code="DS-P10-R1",
    )
    bay = create_bay(
        api, bay_code="BAY-P10", max_kv=145, changeover_buffer_hours=4,
        supports_impulse=True,
    )
    outcome = run_fat_to_conclusion(
        api,
        order["id"],
        bay["id"],
        "2026-02-10T08:00:00Z",
        "2026-02-10T09:00:00Z",
        result="PASS",
        report_overrides=dict(_FAT_READINGS),
    )
    label = issue_label(
        api,
        order["id"],
        material["drawing"]["id"],
        outcome["report"]["id"],
        generated_by_user_id=USER_COMPLIANCE_1,
        verified_by_user_id=USER_QUALITY_1,
    )
    assert label["status"] == "ISSUED"
    release = create_release(api, order["id"])
    assert release["status"] == "HELD"
    assert_order_state(
        read_order(api, order["id"]),
        production_posture="OPEN",
        posture_reason_codes=[],
    )

    revision_two = create_drawing(
        api, order["id"], drawing_set_code="DS-P10-R2",
        authored_by_user_id=USER_DESIGN_1,
    )
    validate_success(api.submit_drawing(revision_two["id"], {}, DESIGN_ENGINEER))

    # One fact -- the order's only label is no longer ISSUED -- makes three
    # separate clear-time rungs true simultaneously.
    staled = validate_success(
        api.get_compliance_label(label["id"], COMPLIANCE_OFFICER)
    )
    assert staled["status"] == "STALE"
    assert staled["void_reason"] == "DRAWING_SUPERSEDED"
    frozen = read_order(api, order["id"])
    assert_order_state(
        frozen,
        fulfillment_status="FAT_COMPLETE",
        production_posture="FROZEN",
        posture_reason_codes=["LABEL_STALE"],
    )

    validate_error(
        api.clear_shipment_release(release["id"], {}, LOGISTICS_COORDINATOR),
        ApiErrorId.POSTURE_BLOCKED,
        409,
    )

    held = validate_success(
        api.get_shipment_release(release["id"], LOGISTICS_COORDINATOR)
    )
    assert held["status"] == "HELD"
    assert held["cleared_at"] is None
    # The two order dimensions moved independently.
    final = read_order(api, order["id"])
    assert final["engineering_status"] == "SUBMITTAL_IN_REVIEW"
    assert final["fulfillment_status"] == "FAT_COMPLETE"


def test_one_allocation_payload_peels_four_rungs_in_ladder_order(api):
    """PRD 2.11: "When a single request could fail several checks at once, the
    server evaluates them in one fixed global order and returns the **first**
    failure it finds"; the bands run "existence resolution (7–26)", "optimistic
    concurrency (32–33)", "temporal admissibility (67–74)", then "capacity, quota
    and fiscal checks (75–82)".

    Design: Difficulty/priority_pair_validation_conflict/allocation_create_four_rung_ladder_p13_then_p33_then_p71_then_p75_on_one_payload_shape
    """
    set_clock(api, "2026-03-01T00:00:00Z")
    order = create_order(
        api,
        order_number="TX-PRI-0011",
        customer_name="Foothill Substation LLC",
        product_family="MV_SWITCHGEAR",
        rated_kv=15,
        contract_value_cents=800000,
        sold_at="2026-03-01T00:00:00Z",
        promised_ship_at="2026-12-01T00:00:00Z",
    )
    supplier = create_supplier(
        api, supplier_code="SUP-P11", legal_name="Foothill Steel", region="NA"
    )
    component = create_component(
        api,
        supplier["id"],
        part_number="CORE-P11",
        category="CORE_STEEL_COIL",
        lead_time_days=35,
        quantity_on_hand=2,
        allocation_policy="PREEMPTIBLE",
    )
    version_at_creation = component["version"]

    def attempt(component_id, quantity, need_by_date, expected_version):
        return api.create_component_allocation(
            component_allocation_payload(
                component_id,
                order["id"],
                expected_version,
                quantity=quantity,
                priority_class=3,
                need_by_date=need_by_date,
            ),
            MATERIALS_PLANNER,
        )

    # Every rejected call below carries the same four defects; only the rung
    # ordering decides which one is reported.
    validate_error(
        attempt(NON_EXISTENT_UUID, 999, "2026-01-15T00:00:00Z", version_at_creation + 1),
        ApiErrorId.COMPONENT_NOT_FOUND,
        404,
    )
    validate_error(
        attempt(component["id"], 999, "2026-01-15T00:00:00Z", version_at_creation + 1),
        ApiErrorId.STALE_COMPONENT_VERSION,
        412,
    )
    validate_error(
        attempt(component["id"], 999, "2026-01-15T00:00:00Z", version_at_creation),
        ApiErrorId.NEED_BY_DATE_PASSED,
        422,
    )
    # One unit past quantity_available, with nothing lower-priority to displace.
    validate_error(
        attempt(component["id"], 3, "2026-09-01T00:00:00Z", version_at_creation),
        ApiErrorId.COMPONENT_INSUFFICIENT,
        409,
    )

    # The stale-version rung is the proof that none of the four rejected calls
    # mutated the component: the original version is still accepted.
    accepted = validate_success(
        attempt(component["id"], 2, "2026-09-01T00:00:00Z", version_at_creation), 201
    )
    assert accepted["status"] == "RESERVED"
    assert accepted["quantity"] == 2
    assert accepted["release_penalty_cents"] == 0

    assert_component_buckets(
        read_component(api, component["id"]),
        quantity_on_hand=2,
        quantity_reserved=2,
        quantity_available=0,
    )
    rows = api.list_component_allocations(
        MATERIALS_PLANNER, {"long_lead_component_id": component["id"], "limit": 50}
    ).json()["data"]
    assert len(rows) == 1
    assert rows[0]["id"] == accepted["id"]
