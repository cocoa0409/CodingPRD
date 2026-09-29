"""Stale-view protection on the two repeatable writes, and read-your-write consistency.

The two writes that may legitimately be repeated are guarded on the parent's version
instead of on state, and a derived count on a parent is visible on the very next read.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import (
    CertStatus,
    OrderStatus,
    ErrorId,
    assert_percentage,
    assert_torque,
    factories,
    fixtures,
    make_product_engineer_headers,
    make_quality_manager_headers,
)


def test_01_proposing_an_actuator_against_a_stale_unit_version_is_refused(api):
    """The unit has moved on since the client last saw it, so the sizing is refused before
    any package is minted.

    PRD §2.8: "Proposing an actuator package requires the non-optional field
    `expected_valve_unit_version`, carrying the client's last observed `version` of the target
    `ValveUnit`. If that value does not equal the unit's current `version`, the creation is
    rejected with `ERR_STALE_VALVE_UNIT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/corner_actuator_create_with_stale_unit_version_returns_412
    """
    line = fixtures.build_traceable_line(
        api,
        foundry_code="FDY-C20",
        foundry_name="Corner Stale Castings",
        heat_number="H-C2001",
        mtr_document_ref="MTR-C2001",
        model_code="BV-300-STALE",
        license_code="MON-C20",
        scope_valve_types=["BALL"],
        grant_license=False,
    )
    unit = fixtures.open_unit(
        api,
        line["model"]["id"],
        line["component"]["id"],
        line["license"]["id"],
        serial_number="SN-C20-1",
    )
    fixtures.advance_to_assembled(api, unit["id"], technician_user_id="tech-c20")
    current = fixtures.read_unit(api, unit["id"])

    response = api.create_actuator_package(
        factories.actuator_package_payload(
            unit["id"],
            "PNEUMATIC",
            900.0,
            "CATALOG",
            current["version"] - 1,
            supply_pressure_bar=6.0,
        ),
        make_product_engineer_headers(),
    )

    validate_error(response, ErrorId.STALE_VALVE_UNIT_VERSION, 412)
    assert fixtures.read_unit(api, unit["id"])["version"] == current["version"]
    rows, _meta = validate_paginated(
        api.list_actuator_packages(
            make_quality_manager_headers(), params={"valve_unit_id": unit["id"]}
        )
    )
    assert rows == [], "The refused proposal minted no package"


def test_02_appending_a_datasheet_revision_against_a_stale_order_version_is_refused(api):
    """A revision authored against an out-of-date view of the order is refused, so the
    datasheet the review is waiting on is unchanged.

    PRD §2.8: "Appending a datasheet revision to an engineered order requires the
    non-optional field `expected_engineered_order_version`, carrying the client's last observed
    `version` of that `EngineeredOrder`. A mismatch with the order's current `version` is
    rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), preventing a revision authored against a
    superseded `datasheet_revision_no` from overwriting a newer one." PRD §3.8: "a successful
    revision increments `datasheet_revision_no` by 1, replaces the datasheet fields, increments
    the order's `version` by 1, and moves `CLARIFICATION_REQUESTED → UNDER_REVIEW`."

    Design: Corner/cross_cutting_complexity_layers/corner_datasheet_revision_with_stale_order_version_returns_412
    """
    model = fixtures.create_released_model(api, model_code="BV-300-REV")
    order = fixtures.create_order(
        api, model["id"], order_code="ETO-C20", datasheet_break_torque_nm=420.0
    )
    fixtures.review_action(api, order["id"], "SUBMIT_REVIEW")
    clarifying = fixtures.review_action(api, order["id"], "REQUEST_CLARIFICATION")
    assert clarifying["status"] == OrderStatus.CLARIFICATION_REQUESTED
    assert clarifying["clarification_round_count"] == 1

    response = api.create_datasheet_revision(
        order["id"],
        factories.datasheet_revision_payload(
            455.0, "VENDOR_MEASURED", clarifying["version"] - 1
        ),
        make_product_engineer_headers(),
    )

    validate_error(response, ErrorId.STALE_ORDER_VERSION, 412)
    unchanged = fixtures.read_order(api, order["id"])
    assert unchanged["status"] == OrderStatus.CLARIFICATION_REQUESTED
    assert unchanged["datasheet_revision_no"] == 1
    assert_torque(unchanged["datasheet_break_torque_nm"], 420.0, "datasheet_break_torque_nm")
    assert unchanged["version"] == clarifying["version"]


def test_03_a_certification_is_reflected_in_the_order_s_count_on_the_next_read(api):
    """The order's derived count is recomputed by the certification itself, so the very next
    read of the order already shows the certified unit.

    PRD §3.7: "A successful certification writes `certified_by_user_id` from `X-User-ID` and
    `certified_at` from the current logical-clock instant, freezes `final_emission_leak_class`
    from the time-weighted rule of §3.4, and recomputes the owning engineered order's
    `certified_unit_count` and `documentation_completeness_pct`". PRD §3.8:
    "`certified_unit_count`, for its part, is simply the number of the order's units whose
    `cert_status` is `CERTIFIED`."

    Design: Corner/consistency_model/corner_certified_unit_count_visible_in_the_same_request
    """
    line = fixtures.build_traceable_line(
        api,
        foundry_code="FDY-C21",
        foundry_name="Corner Consistency Castings",
        heat_number="H-C2101",
        mtr_document_ref="MTR-C2101",
        model_code="BV-300-COUNT",
        license_code="MON-C21",
        scope_valve_types=["BALL"],
        lead_auditor_user_id="aud-c21",
    )
    order = fixtures.build_order_in_production(
        api, line["model"]["id"], order_code="ETO-C21", ordered_qty=1
    )
    before = fixtures.read_order(api, order["id"])
    assert before["certified_unit_count"] == 0
    unit = fixtures.open_unit(
        api,
        line["model"]["id"],
        line["component"]["id"],
        line["license"]["id"],
        serial_number="SN-C21-1",
        engineered_order_id=order["id"],
    )
    fixtures.advance_to_assembled(api, unit["id"], technician_user_id="tech-c21")
    fixtures.record_pass_run(
        api, unit["id"], test_bench_code="BENCH-C21", technician_user_id="tech-c21"
    )

    certified = fixtures.certify_unit(api, unit["id"], quality_manager_user_id="qm-c21")

    assert certified["cert_status"] == CertStatus.CERTIFIED
    after = fixtures.read_order(api, order["id"])
    assert after["certified_unit_count"] == 1
    assert after["status"] == OrderStatus.IN_PRODUCTION
    # No document entry has been appended, so only the actuator-datasheet category, whose
    # required count is zero, earns its 0.10 weight.
    assert_percentage(
        after["documentation_completeness_pct"], 10.00, "documentation_completeness_pct"
    )
