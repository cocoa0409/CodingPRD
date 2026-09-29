"""Endpoint behaviours: the clock capability, package issuance and actuator approval.

The clock capability moves the instant every date-dependent rule reads without touching
stored rows, while the issuance and approval endpoints each enforce their own gate.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    DocPackageStatus,
    ErrorId,
    ModelStatus,
    OrderStatus,
    SizingStatus,
    assert_percentage,
    assert_torque,
    factories,
    fixtures,
    make_quality_manager_headers,
)


def test_01_setting_the_clock_moves_the_logical_now_without_rewriting_rows(api):
    """The design is untouched by the clock move, and the next release stamps the new
    instant rather than the one the design was created under.

    PRD §2.5: "On a fresh system the clock reads `2026-08-01T00:00:00Z`, and it moves only
    when an operator calls the clock-setting capability with a `to_iso8601` instant." PRD §2.5:
    "Setting the clock rewrites nothing." PRD §3.1: "Release moves `IN_REVIEW → RELEASED`, sets
    `released_at` to the current logical-clock instant".

    Design: Corner/endpoints/corner_clock_endpoint_moves_the_logical_now
    """
    model = fixtures.create_model(api, model_code="BV-300-CLOCK")

    fixtures.set_logical_clock(api, "2027-03-01T00:00:00Z")

    untouched = fixtures.read_model(api, model["id"])
    assert untouched["status"] == ModelStatus.DRAFT
    assert untouched["spec_revision"] == 1
    assert untouched["released_at"] is None

    # ``release_model`` walks DRAFT -> IN_REVIEW -> RELEASED itself.
    released = fixtures.release_model(api, model["id"])

    assert released["status"] == ModelStatus.RELEASED
    assert released["released_at"].startswith("2027-03-01"), (
        "Release reads the logical clock, which the capability moved"
    )


def test_02_issuing_a_half_scored_documentation_package_is_refused(api):
    """Two of the six categories are evidenced, which scores fifty per cent, and issuance
    demands a complete package.

    PRD §3.8: "A `QualityManager` then issues it, moving `COMPLETE → ISSUED`; issuing
    requires the package to be `COMPLETE`, otherwise `ERR_DOC_PACKAGE_INCOMPLETE`, requires the
    order's `status` to be `IN_PRODUCTION` or `HELD`, and requires `certified_unit_count` to be
    at or above `ordered_qty`, otherwise `ERR_ORDER_UNITS_INCOMPLETE`." PRD §3.8: "For each
    category, the fraction earned is 1.00 outright when the required count is zero; otherwise
    it is the smaller of the present count and the required count, divided by the required
    count, **rounded half up to 2 decimal places at this point**."

    Design: Corner/endpoints/corner_issue_doc_package_blocked_below_full_completeness
    """
    model = fixtures.create_released_model(api, model_code="BV-300-DOCS")
    order = fixtures.build_order_in_production(
        api, model["id"], order_code="ETO-C12", ordered_qty=1
    )
    fixtures.append_documents(api, order["id"], ["MATERIAL_TEST_REPORT", "DIMENSIONAL_REPORT"])

    response = api.engineered_order_lifecycle_action(
        order["id"],
        factories.lifecycle_action_payload("ISSUE_DOC_PACKAGE"),
        make_quality_manager_headers(),
    )

    validate_error(response, ErrorId.DOC_PACKAGE_INCOMPLETE, 409)
    unchanged = fixtures.read_order(api, order["id"])
    # 0.25 for the material test report, 0.15 for the dimensional report, and 0.10 for the
    # actuator datasheet category whose required count is zero.
    assert_percentage(
        unchanged["documentation_completeness_pct"], 50.00, "documentation_completeness_pct"
    )
    assert unchanged["doc_package_status"] == DocPackageStatus.ASSEMBLING
    assert unchanged["status"] == OrderStatus.IN_PRODUCTION


def test_03_approving_an_actuator_below_the_sized_torque_is_refused(api):
    """The proposal is accepted and sized, and the approval decision is what measures the
    actuator against that sizing.

    PRD §3.5: "Approving moves `PROPOSED → APPROVED` and requires two things: the actuator's
    `output_torque_nm` must be at or above the computed `sized_torque_nm`, otherwise
    `ERR_ACTUATOR_TORQUE_INSUFFICIENT`; and a non-electric actuator must have a
    `supply_pressure_bar` greater than zero, otherwise `ERR_INVALID_REQUEST` — a pneumatic or
    hydraulic actuator with no supply is not a sizing that can be approved." PRD §3.5: "The
    package opens at `sizing_status` `PROPOSED` with `approved_by_user_id` null; states run
    `PROPOSED → APPROVED`, with `REJECTED` and `SUPERSEDED` terminal."

    Design: Corner/endpoints/corner_actuator_decision_rejects_insufficient_output_torque
    """
    line = fixtures.build_traceable_line(
        api,
        foundry_code="FDY-C12",
        foundry_name="Corner Actuator Castings",
        heat_number="H-C1201",
        mtr_document_ref="MTR-C1201",
        model_code="BV-300-ACT",
        license_code="MON-C12",
        scope_valve_types=["BALL"],
        grant_license=False,
    )
    unit = fixtures.open_unit(
        api,
        line["model"]["id"],
        line["component"]["id"],
        line["license"]["id"],
        serial_number="SN-C12-1",
    )
    package = fixtures.propose_actuator_package(
        api,
        unit["id"],
        unit["version"],
        actuator_type="PNEUMATIC",
        output_torque_nm=600.0,
        sizing_basis="CATALOG",
        supply_pressure_bar=5.5,
    )
    # 420.0 times the 1.03 pressure factor and the 1.30 metal-seat factor is 562.4, whose
    # 0.25 tier sizes the actuator at 703.0.
    assert_torque(package["required_torque_nm"], 562.4, "required_torque_nm")
    assert_torque(package["sized_torque_nm"], 703.0, "sized_torque_nm")

    response = api.actuator_package_decision(
        package["id"],
        factories.actuator_decision_payload("APPROVE"),
        make_quality_manager_headers(),
    )

    validate_error(response, ErrorId.ACTUATOR_TORQUE_INSUFFICIENT, 422)
    unchanged = fixtures.read_package(api, package["id"])
    assert unchanged["sizing_status"] == SizingStatus.PROPOSED
    assert unchanged["approved_by_user_id"] is None
