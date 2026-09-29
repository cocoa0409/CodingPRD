"""Error catalogue reachability: each refusal reached through its own rule.

Every test builds its own state from an empty database through the documented
endpoints only.
"""

import pytest

from test_helpers import (
    HTTP_STATUS_CODES,
    ApiErrorId,
    api_client,
    assert_lot_piece_conservation,
    build_allocatable_plant,
    build_assembly_line,
    build_product_model,
    build_production_ready_plant,
    build_released_order_plant,
    build_safety_certification,
    build_supplier,
    create_build_order_payload,
    create_component_lot_payload,
    create_engine_unit_payload,
    create_line_audit_payload,
    deviation_accept_lot,
    inspect_component_lot,
    plan_build_order,
    read_engine_unit,
    read_family,
    read_lot,
    read_model,
    receive_component_lot,
    record_line_audit_payload,
    schedule_line_audit,
    stage_engine_unit,
    torque_readings_at,
    torque_record_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def _expect_error(response, error_id: ApiErrorId) -> dict:
    """Assert the documented error identifier and its documented HTTP status."""
    return validate_error(
        response, error_id.value, HTTP_STATUS_CODES[error_id.value]
    )


class TestTorqueReadingCount:
    """The reading array must match the platform's fastener count exactly."""

    @pytest.mark.parametrize("reading_count", [3, 5])
    def test_torque_recording_refuses_a_reading_count_off_by_one_either_way(
        self, released_order_plant, quality_engineer_headers, reading_count
    ):
        """
        PRD §3.7: "The array must contain **exactly** the platform's `required_fastener_count` entries — neither fewer nor more — and a mismatch is refused with `ERR_TORQUE_READING_COUNT_MISMATCH`."
        PRD §3.1: "A platform carries a `platform_code` of 1 to 30 characters, unique across all platforms; a `displacement_cc` between 50 and 1000 which must fall inside the owning family's declared band inclusively — a displacement below `displacement_min_cc` or above `displacement_max_cc` is refused with `ERR_DISPLACEMENT_OUT_OF_FAMILY`; a nominal fastener torque `torque_spec_nm` above zero at 1 decimal place; a fractional `torque_tolerance_pct` between 0.01 and 0.20 at 2 decimal places, so a value of 0.05 means a band of plus or minus five percent; a `required_fastener_count` between 1 and 12, being the number of torque readings each engine on that platform must report; and a governed-speed window for the hot test given as `hot_test_min_rpm` between 500 and 8000 and `hot_test_max_rpm` strictly above it and at most 8000, both bounds inclusive when the window is applied."
        PRD §3.7: "A successful staging creates the unit with `build_state` `STAGED` and `conformance_state` `PENDING`, `rework_count` at 0, and `torque_readings`, `out_of_spec_fastener_count`, `measured_rpm`, `measured_emission_g_per_kwh`, `hot_test_emission_threshold` and `released_at` all empty."

        Design: Corner/errors/torque_reading_count_must_equal_the_platform_fastener_count
        """
        scenario = released_order_plant
        assert scenario.platform["required_fastener_count"] == 4
        unit = stage_engine_unit(scenario, "SN-0001")

        readings = torque_readings_at(*([22.0] * reading_count))
        response = api_client.torque_record_engine_unit(
            unit["id"], torque_record_payload(readings), quality_engineer_headers
        )
        _expect_error(response, ApiErrorId.ERR_TORQUE_READING_COUNT_MISMATCH)

        unchanged = read_engine_unit(unit["id"])
        assert unchanged["build_state"] == "STAGED"
        assert unchanged["conformance_state"] == "PENDING"
        assert unchanged["torque_readings"] in (None, [])
        assert unchanged["out_of_spec_fastener_count"] is None

    def test_torque_recording_accepts_exactly_the_fastener_count(
        self, released_order_plant, quality_engineer_headers
    ):
        """
        PRD §3.7: "The array must contain **exactly** the platform's `required_fastener_count` entries — neither fewer nor more — and a mismatch is refused with `ERR_TORQUE_READING_COUNT_MISMATCH`."
        PRD §3.7: "A platform specified at 22.0 Nm with a tolerance of 0.05 therefore accepts everything from 20.90 through 23.10 inclusive."
        PRD §3.7: "The unit's `build_state` advances `STAGED → ASSEMBLED` regardless of the count, and its `conformance_state` becomes `NONCONFORMING` when `out_of_spec_fastener_count` is greater than zero, or is left at `PENDING` when every fastener was in band."

        Design: Corner/errors/torque_reading_count_must_equal_the_platform_fastener_count
        """
        scenario = released_order_plant
        unit = stage_engine_unit(scenario, "SN-0001")

        recorded = validate_success(
            api_client.torque_record_engine_unit(
                unit["id"],
                torque_record_payload(
                    torque_readings_at(20.90, 22.0, 23.10, 22.5)
                ),
                quality_engineer_headers,
            ),
            200,
        )
        assert len(recorded["torque_readings"]) == 4
        assert recorded["out_of_spec_fastener_count"] == 0
        assert recorded["build_state"] == "ASSEMBLED"
        assert recorded["conformance_state"] == "PENDING"


class TestBuildOrderLineGates:
    """The line's product-line scope and the line's running state fail apart."""

    def test_line_scope_refuses_the_plan_while_a_down_line_refuses_the_release(
        self, canonical_clock, production_planner_headers
    ):
        """
        PRD §3.6: "The model's `product_line` must appear in the line's `supported_product_lines`, else `ERR_LINE_PRODUCT_LINE_UNSUPPORTED`."
        PRD §3.6: "The assembly line's `status` must be `RUNNING`, else `ERR_ASSEMBLY_LINE_DOWN`."
        PRD §3.6: "`build_value_cents` is `planned_quantity` multiplied by the model's `standard_cost_cents`."
        PRD §3.6: "`carry_weeks` is 0 for an `IN_SEASON` order; for a `PRE_SEASON` order it is the number of whole weeks from `production_week` to the product line's season start, that is, the day count between the two dates divided by 7 and rounded **down**."
        PRD §3.6: "`carry_cost_cents` is `build_value_cents` multiplied by `carry_rate` multiplied by `carry_weeks`, rounded half up to whole cents."
        PRD §3.6: "`total_committed_cents` is `build_value_cents` plus `carry_cost_cents`."
        PRD §3.6: "The four season starts are fixed dates: walk-behind mowers open on 2027-03-01, riding mowers on 2027-03-15, snow equipment much earlier on 2026-11-02, and generators on 2027-05-03."
        PRD §3.6: "On success the order moves `PLANNED → RELEASED` and `released_at` is stamped from the clock."

        Design: Corner/errors/build_order_line_scope_and_line_posture_produce_distinct_errors
        """
        scenario = build_production_ready_plant(
            line_overrides={"supported_product_lines": ["SNOW_THROWER"]}
        )
        assert scenario.model["product_line"] == "WALK_MOWER"

        unsupported = api_client.create_build_order(
            create_build_order_payload(scenario.model_id, scenario.line_id),
            production_planner_headers,
        )
        _expect_error(unsupported, ApiErrorId.ERR_LINE_PRODUCT_LINE_UNSUPPORTED)

        down_line = build_assembly_line(
            line_code="L2",
            supported_product_lines=["WALK_MOWER"],
            status="DOWN",
        )
        planned = plan_build_order(scenario.model_id, down_line["id"])
        assert planned["status"] == "PLANNED"
        assert planned["build_value_cents"] == 126000
        assert planned["carry_rate"] == pytest.approx(0.0040, abs=0.0001)
        assert planned["carry_weeks"] == 24
        assert planned["carry_cost_cents"] == 12096
        assert planned["total_committed_cents"] == 138096

        _expect_error(
            api_client.release_build_order(planned["id"], production_planner_headers),
            ApiErrorId.ERR_ASSEMBLY_LINE_DOWN,
        )

        running_line = build_assembly_line(
            line_code="L3", supported_product_lines=["WALK_MOWER"], status="RUNNING"
        )
        second = plan_build_order(scenario.model_id, running_line["id"])
        released = validate_success(
            api_client.release_build_order(second["id"], production_planner_headers), 200
        )
        assert released["status"] == "RELEASED"
        assert released["released_at"] is not None


class TestModelReleaseSafetyChain:
    """Release demands a latest-passing bench test, not merely any bench test."""

    def test_model_release_requires_a_latest_passing_safety_certification(
        self, certified_platform, plant_admin_headers
    ):
        """
        PRD §3.3: "The release looks for the model's **latest passing** safety certification — the rows whose `result` is `PASSED`, ordered by `tested_on` descending and, for ties on that date, by `created_at` descending, taking the first."
        PRD §3.3: "If no passing certification exists at all, the release is refused with `ERR_SAFETY_CERTIFICATION_MISSING`."
        PRD §3.3: "The `result` is `PASSED` when both checks pass and `FAILED` otherwise."
        PRD §3.3: "A measured blade stop time passes when it is absent altogether or when it is at most 3000 milliseconds; a measured operator-presence response — which for a generator is the carbon-monoxide shutoff response — passes when it is at most 1000 milliseconds."
        PRD §3.3: "On success the model moves to `RELEASED` and `released_at` is stamped from the clock."
        PRD §3.3: "A model's certifications can be listed from the model, newest `tested_on` first."

        Design: Corner/errors/model_release_requires_a_currently_passing_safety_certification
        """
        model = build_product_model(certified_platform.platform_id)
        assert model["status"] == "DRAFT"

        _expect_error(
            api_client.release_product_model(model["id"], plant_admin_headers),
            ApiErrorId.ERR_SAFETY_CERTIFICATION_MISSING,
        )

        failed = build_safety_certification(model["id"], opc_stop_time_ms=1200)
        assert failed["result"] == "FAILED"

        _expect_error(
            api_client.release_product_model(model["id"], plant_admin_headers),
            ApiErrorId.ERR_SAFETY_CERTIFICATION_MISSING,
        )
        assert read_model(model["id"])["status"] == "DRAFT"

        passed = build_safety_certification(
            model["id"], tested_on="2026-07-20", expires_on="2027-07-20"
        )
        assert passed["result"] == "PASSED"

        released = validate_success(
            api_client.release_product_model(model["id"], plant_admin_headers), 200
        )
        assert released["status"] == "RELEASED"
        assert released["released_at"] is not None

        rows, meta = validate_paginated(
            api_client.list_model_safety_certifications(
                model["id"], plant_admin_headers, {"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 2
        assert [row["id"] for row in rows] == [passed["id"], failed["id"]]


class TestLineAuditGates:
    """Scheduling and recording each carry their own refusals."""

    def test_audit_scheduling_and_recording_gates_are_all_reachable(
        self, canonical_clock, compliance_officer_headers
    ):
        """
        PRD §3.8: "An order may carry at most one open audit: scheduling a second while one is still `SCHEDULED` is refused with `ERR_AUDIT_ALREADY_OPEN`."
        PRD §3.8: "Its `required_sample_size` is the larger of 2 units and two percent of the order's `built_quantity` rounded **up** to a whole unit, and it is likewise frozen — later releases on the order do not enlarge it."
        PRD §3.8: "The sample must be at least as large as the frozen `required_sample_size`, else `ERR_AUDIT_SAMPLE_TOO_SMALL`, and it cannot exceed the order's `built_quantity`, else `ERR_AUDIT_SAMPLE_EXCEEDS_POPULATION`."
        PRD §3.8: "Only a `SCHEDULED` audit may be recorded — one already `PASSED` or `FAILED` cannot be re-recorded and the attempt is refused with `ERR_AUDIT_STATE_INVALID`."
        PRD §3.8: "`failure_rate` is `units_failed` divided by `units_tested`, rounded half up to 4 decimal places."
        PRD §3.8: "When neither holds the audit is `PASSED` with `failure_reason` left empty."
        PRD §3.8: "A passing audit changes nothing outside its own row — in particular the family's status and its `cumulative_audit_failures` are untouched."

        Design: Corner/errors/audit_scheduling_and_recording_gates_are_all_reachable
        """
        scenario = build_allocatable_plant(released_units=2)
        order = scenario.refresh_build_order()
        assert order["built_quantity"] == 2

        audit = schedule_line_audit(order["id"])
        assert audit["status"] == "SCHEDULED"
        assert audit["required_sample_size"] == 2
        assert audit["certification_family_id"] == scenario.family_id
        assert audit["units_tested"] is None
        assert audit["failure_rate"] is None

        _expect_error(
            api_client.create_line_audit(
                order["id"],
                create_line_audit_payload("2026-09-21"),
                compliance_officer_headers,
            ),
            ApiErrorId.ERR_AUDIT_ALREADY_OPEN,
        )

        _expect_error(
            api_client.record_line_audit(
                audit["id"],
                record_line_audit_payload(units_tested=1, units_failed=0),
                compliance_officer_headers,
            ),
            ApiErrorId.ERR_AUDIT_SAMPLE_TOO_SMALL,
        )

        _expect_error(
            api_client.record_line_audit(
                audit["id"],
                record_line_audit_payload(units_tested=3, units_failed=0),
                compliance_officer_headers,
            ),
            ApiErrorId.ERR_AUDIT_SAMPLE_EXCEEDS_POPULATION,
        )

        recorded = validate_success(
            api_client.record_line_audit(
                audit["id"],
                record_line_audit_payload(
                    units_tested=2, units_failed=0, max_measured_emission_g_per_kwh=5.60
                ),
                compliance_officer_headers,
            ),
            200,
        )
        assert recorded["status"] == "PASSED"
        assert recorded["failure_rate"] == pytest.approx(0.0000, abs=0.01)
        assert recorded["failure_reason"] is None
        assert recorded["recorded_by_user_id"] == compliance_officer_headers["X-User-ID"]

        _expect_error(
            api_client.record_line_audit(
                audit["id"],
                record_line_audit_payload(units_tested=2, units_failed=0),
                compliance_officer_headers,
            ),
            ApiErrorId.ERR_AUDIT_STATE_INVALID,
        )

        family = read_family(scenario.family_id)
        assert family["status"] == "CERTIFIED"
        assert family["cumulative_audit_failures"] == 0

        _, meta = validate_paginated(
            api_client.list_line_audits(
                order["id"], compliance_officer_headers, {"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 1


class TestSuspendedSupplier:
    """Suspension stops material at the receiving dock."""

    def test_suspended_supplier_cannot_ship_a_further_lot(
        self, canonical_clock, quality_engineer_headers
    ):
        """
        PRD §3.4: "At `NORMAL` it is the larger of 8 pieces and five percent of `lot_quantity` rounded up."
        PRD §3.4: "The acceptance number — the maximum number of defective pieces in the sample that still permits acceptance — is 0 for a `CRITICAL` supplier, and for a `MAJOR` supplier it is ten percent of the resulting sample size rounded **down** to a whole number."
        PRD §3.4: "The pooled rate is the sum of `defects_found` across that population, divided by the sum of `sample_size` across the same population, multiplied by one million, rounded half up to a whole number, and stored as `rolling_defect_ppm`."
        PRD §3.4: "Otherwise: if the recomputed pooled rate is **greater than** 100,000 parts per million, the supplier becomes `SUSPENDED` and its `incoming_inspection_level` becomes `TIGHTENED`; else if the pooled rate is **greater than** 25,000 parts per million, the supplier becomes `PROBATION` and its level becomes `TIGHTENED`; else the supplier becomes `APPROVED` and its level is chosen from the accepted-lot streak — `SKIP_LOT` when `consecutive_accepted_lots` is at least 5, `REDUCED` when it is at least 3, and `NORMAL` otherwise."
        PRD §3.4: "A lot may not be received at all from a supplier whose `approval_status` is `SUSPENDED`; the attempt is refused with `ERR_SUPPLIER_SUSPENDED`."
        PRD §3.4: "A rejection sets `accepted_qty` to 0 and `remaining_qty` to 0, writes `defect_ppm` in exactly the same way, records `inspected_by_user_id` in exactly the same way, adds 1 to the supplier's `inspected_lot_count`, **resets** the supplier's `consecutive_accepted_lots` to 0, and recomputes `rolling_defect_ppm`."

        Design: Corner/errors/suspended_supplier_cannot_ship_further_lots
        """
        supplier = build_supplier(
            supplier_code="SUP-CARB",
            name="Kirin Carburetor Works",
            component_category="CARBURETOR",
        )
        lot = receive_component_lot(
            supplier["id"], lot_code="CB-001", lot_quantity=100
        )
        assert lot["sample_size"] == 8
        assert lot["acceptance_number"] == 0

        rejected = inspect_component_lot(lot["id"], defects_found=2)
        assert rejected["status"] == "REJECTED"
        assert rejected["defect_ppm"] == 250000
        assert rejected["accepted_qty"] == 0
        assert rejected["remaining_qty"] == 0

        scorecard = validate_success(
            api_client.get_supplier_scorecard(supplier["id"], quality_engineer_headers),
            200,
        )
        assert scorecard["approval_status"] == "SUSPENDED"
        assert scorecard["incoming_inspection_level"] == "TIGHTENED"
        assert scorecard["rolling_defect_ppm"] == 250000
        assert scorecard["consecutive_accepted_lots"] == 0

        _expect_error(
            api_client.create_component_lot(
                create_component_lot_payload(
                    supplier["id"], lot_code="CB-002", lot_quantity=100
                ),
                quality_engineer_headers,
            ),
            ApiErrorId.ERR_SUPPLIER_SUSPENDED,
        )

        _, meta = validate_paginated(
            api_client.list_component_lots(
                quality_engineer_headers,
                {"supplier_id": supplier["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1


class TestFullyDeviatedLot:
    """A deviation on a wholly defective lot releases nothing."""

    def test_fully_deviated_lot_is_releasable_but_has_no_pieces_left(
        self, canonical_clock, quality_engineer_headers
    ):
        """
        PRD §3.7: "Each consumed lot's status must be `ACCEPTED` or `DEVIATION_ACCEPTED`, else `ERR_COMPONENT_LOT_NOT_RELEASABLE`."
        PRD §3.7: "Then two quota checks: staging one more unit must not push the order's `staged_quantity` plus `built_quantity` past its `planned_quantity`, else `ERR_BUILD_ORDER_QUANTITY_EXCEEDED`; and each consumed lot must have `remaining_qty` of at least 1, else `ERR_COMPONENT_LOT_DEPLETED`."
        PRD §3.4: "On success the lot moves to `DEVIATION_ACCEPTED`, `deviation_flag` becomes true, `deviation_approved_by_user_id` records the approver, and the released quantity is recomputed: `accepted_qty` becomes `lot_quantity` minus `defects_found`, with `remaining_qty` set equal to it."
        PRD §2.11: "On a component lot, the pieces released to the line are conserved: `accepted_qty` always equals `consumed_qty` plus `remaining_qty`."

        Design: Corner/errors/fully_deviated_lot_has_no_releasable_pieces_left
        """
        scenario = build_released_order_plant()
        spare_supplier = build_supplier(
            supplier_code="SUP-CARB-2",
            name="Second Carburetion Source",
            component_category="CARBURETOR",
        )
        spare_lot = receive_component_lot(
            spare_supplier["id"], lot_code="CB-900", lot_quantity=8
        )
        assert spare_lot["sample_size"] == 8
        assert spare_lot["acceptance_number"] == 0

        rejected = inspect_component_lot(spare_lot["id"], defects_found=8)
        assert rejected["status"] == "REJECTED"
        assert rejected["accepted_qty"] == 0

        _expect_error(
            api_client.create_engine_unit(
                create_engine_unit_payload(
                    scenario.build_order_id,
                    scenario.machining_run_id,
                    spare_lot["id"],
                    scenario.ignition_lot_id,
                    "SN-0100",
                ),
                quality_engineer_headers,
            ),
            ApiErrorId.ERR_COMPONENT_LOT_NOT_RELEASABLE,
        )

        deviated = deviation_accept_lot(spare_lot["id"])
        assert deviated["status"] == "DEVIATION_ACCEPTED"
        assert deviated["deviation_flag"] is True
        assert deviated["accepted_qty"] == 0
        assert deviated["remaining_qty"] == 0
        assert_lot_piece_conservation(deviated)

        _expect_error(
            api_client.create_engine_unit(
                create_engine_unit_payload(
                    scenario.build_order_id,
                    scenario.machining_run_id,
                    spare_lot["id"],
                    scenario.ignition_lot_id,
                    "SN-0101",
                ),
                quality_engineer_headers,
            ),
            ApiErrorId.ERR_COMPONENT_LOT_DEPLETED,
        )
        assert read_lot(scenario.ignition_lot_id)["consumed_qty"] == 0
