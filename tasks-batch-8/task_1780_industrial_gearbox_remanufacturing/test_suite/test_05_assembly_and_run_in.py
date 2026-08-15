"""Assembly tolerance gate, run-in certification, and the FAIL rework cascade."""
from test_helpers import (
    ApiErrorId,
    add_shipment,
    assert_assembly_record,
    get_order,
    record_assembly,
    setup_order_in_assembly,
    setup_order_in_run_in,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBacklashBoundary:
    def test_backlash_at_max_boundary_within_tolerance(
            self, api, quality_inspector_headers):
        """PRD §3.4: "backlash must lie within the band from 0.08 mm to
        0.18 mm inclusive at both ends — a measured 0.18 mm is within
        tolerance — and each of the two clearances must be no greater than
        0.05 mm."

        Design: Difficulty/boundary_precision_check/backlash_exactly_at_max_is_within_tolerance
        """
        ctx = setup_order_in_assembly(serial_number="GBX-E1")
        resp = api.create_assembly_record(
            ctx["order"]["id"],
            {"backlash_mm": 0.18, "radial_clearance_mm": 0.05,
             "axial_clearance_mm": 0.05},
            quality_inspector_headers)
        data = validate_success(resp, expected_status=201)
        assert data["within_tolerance"] is True
        assert data["status"] == "ACTIVE"
        assert_assembly_record(data)

    def test_backlash_just_outside_band_fails_and_min_is_inclusive(
            self, api, quality_inspector_headers):
        """PRD §3.4: "computes its own `within_tolerance` verdict: backlash
        must lie within the band from 0.08 mm to 0.18 mm inclusive at both
        ends — a measured 0.18 mm is within tolerance — and each of the two
        clearances must be no greater than 0.05 mm. Several records may
        accumulate on an order; the gate reads the latest active one."

        Design: Difficulty/boundary_precision_check/backlash_exactly_at_max_is_within_tolerance
        """
        ctx = setup_order_in_assembly(serial_number="GBX-E2")
        order_id = ctx["order"]["id"]

        above = validate_success(api.create_assembly_record(
            order_id, {"backlash_mm": 0.19, "radial_clearance_mm": 0.05,
                       "axial_clearance_mm": 0.05},
            quality_inspector_headers), expected_status=201)
        assert above["within_tolerance"] is False

        below = validate_success(api.create_assembly_record(
            order_id, {"backlash_mm": 0.07, "radial_clearance_mm": 0.02,
                       "axial_clearance_mm": 0.02},
            quality_inspector_headers), expected_status=201)
        assert below["within_tolerance"] is False

        at_min = validate_success(api.create_assembly_record(
            order_id, {"backlash_mm": 0.08, "radial_clearance_mm": 0.02,
                       "axial_clearance_mm": 0.02},
            quality_inspector_headers), expected_status=201)
        assert at_min["within_tolerance"] is True

        clearance_over = validate_success(api.create_assembly_record(
            order_id, {"backlash_mm": 0.10, "radial_clearance_mm": 0.06,
                       "axial_clearance_mm": 0.02},
            quality_inspector_headers), expected_status=201)
        assert clearance_over["within_tolerance"] is False


class TestSubmitAssemblyGate:
    def test_submit_assembly_out_of_tolerance_rejected(
            self, api, quality_inspector_headers):
        """PRD §3.4: "Submitting the assembly for run-in (`ASSEMBLY →
        RUN_IN`) enforces the quality gate: an `ACTIVE` assembly record must
        exist for the order (`ERR_NO_ASSEMBLY_RECORD`), and that latest
        active record's `within_tolerance` must be true
        (`ERR_TOLERANCE_EXCEEDED`)."

        Design: Corner/state_machines/submit_assembly_with_out_of_tolerance_record_rejected
        """
        ctx = setup_order_in_assembly(serial_number="GBX-TOL")
        record = record_assembly(ctx["order"]["id"], backlash_mm=0.25)
        assert record["within_tolerance"] is False

        resp = api.submit_assembly(ctx["order"]["id"],
                                   quality_inspector_headers)
        validate_error(resp, ApiErrorId.ERR_TOLERANCE_EXCEEDED.value)
        assert get_order(ctx["order"]["id"])["status"] == "ASSEMBLY"
        # The rejected gate does not mutate the record.
        records, _ = validate_paginated(
            api.list_assembly_records(ctx["order"]["id"],
                                      quality_inspector_headers))
        assert records[0]["status"] == "ACTIVE"


class TestRunInCertification:
    def test_run_in_duration_must_equal_120(self, api, quality_inspector_headers):
        """PRD §3.4: "its `result` is computed as `PASS` only when all four
        conditions hold together — the duration is exactly 120 minutes,
        `max_temp_c` is no greater than 95.0, `vibration_mm_s` is no greater
        than 4.5, and `oil_particle_count` is no greater than 3,200 — and
        `FAIL` otherwise."

        Design: Corner/state_machines/run_in_wrong_duration_fails
        """
        ctx = setup_order_in_run_in(serial_number="GBX-DUR")
        resp = api.create_run_in_test(
            ctx["order"]["id"],
            {"duration_minutes": 119, "max_temp_c": 80.0,
             "vibration_mm_s": 2.0, "oil_particle_count": 1_500},
            quality_inspector_headers)
        data = validate_success(resp, expected_status=201)
        assert data["result"] == "FAIL"
        assert data["oil_baseline_established"] is False
        assert data["status"] == "SUPERSEDED"
        # A FAIL returns the order to IN_BUILD for rework.
        assert get_order(ctx["order"]["id"])["status"] == "IN_BUILD"

    def test_coordinator_cannot_record_run_in(
            self, api, intake_coordinator_headers):
        """PRD §4: the run-in-tests row of the endpoint table authorizes only
        QualityInspector.
        PRD §2.1: "A request whose role is not permitted for the target
        endpoint — or that fails an entity-backed ownership check — is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/roles/intake_coordinator_cannot_record_run_in
        """
        ctx = setup_order_in_run_in(serial_number="GBX-RB2")
        resp = api.create_run_in_test(
            ctx["order"]["id"],
            {"duration_minutes": 120, "max_temp_c": 80.0,
             "vibration_mm_s": 2.0, "oil_particle_count": 1_500},
            intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestRunInFailCascade:
    def test_run_in_fail_three_hop_cascade(self, api, quality_inspector_headers,
                                           reman_engineer_headers):
        """PRD §3.4: "On a `FAIL`, the test's `status` is `SUPERSEDED` and
        its `oil_baseline_established` stays false; the order automatically
        falls back `RUN_IN → IN_BUILD` for rework, and the currently `ACTIVE`
        assembly record is flipped to `INVALIDATED`, forcing fresh clearance
        and backlash measurements on the rebuild. That invalidation is a leaf
        mutation — it triggers no further cascade."

        Design: Difficulty/transitive_cascade/run_in_fail_cascades_order_then_assembly_record_then_gate
        """
        ctx = setup_order_in_run_in(serial_number="GBX-C1")
        order_id = ctx["order"]["id"]
        record = ctx["assembly_record"]

        resp = api.create_run_in_test(
            order_id,
            {"duration_minutes": 120, "max_temp_c": 99.0,
             "vibration_mm_s": 2.0, "oil_particle_count": 1_500},
            quality_inspector_headers)
        data = validate_success(resp, expected_status=201)
        assert data["result"] == "FAIL"  # 99.0 > 95.0
        assert data["status"] == "SUPERSEDED"
        assert data["oil_baseline_established"] is False

        # Hop 1: order falls back to IN_BUILD.
        assert get_order(order_id)["status"] == "IN_BUILD"

        # Hop 2: the formerly ACTIVE record is invalidated.
        records, _ = validate_paginated(
            api.list_assembly_records(order_id, quality_inspector_headers))
        by_id = {r["id"]: r for r in records}
        assert by_id[record["id"]]["status"] == "INVALIDATED"

        # Hop 3: after legitimately re-walking IN_BUILD → ASSEMBLY, the gate
        # finds no ACTIVE record and rejects submit-assembly.
        api.start_assembly(order_id, reman_engineer_headers)
        resp = api.submit_assembly(order_id, quality_inspector_headers)
        validate_error(resp, ApiErrorId.ERR_NO_ASSEMBLY_RECORD.value)

    def test_run_in_fail_rebuild_requires_fresh_measurements_then_recovers(
            self, api, quality_inspector_headers, reman_engineer_headers):
        """PRD §3.4: "the order automatically falls back `RUN_IN → IN_BUILD`
        for rework, and the currently `ACTIVE` assembly record is flipped to
        `INVALIDATED`, forcing fresh clearance and backlash measurements on
        the rebuild."
        PRD §3.4: "On a `PASS`, the test's `status` is `RECORDED`, its
        `oil_baseline_established` flag is set true — this row becomes the
        warranty oil baseline referenced in §3.7 — the order advances
        `RUN_IN → READY_TO_SHIP`".

        Design: Difficulty/transitive_cascade/run_in_fail_cascades_order_then_assembly_record_then_gate
        """
        ctx = setup_order_in_run_in(serial_number="GBX-C2")
        order_id = ctx["order"]["id"]

        # Fail the first run-in (vibration 5.0 > 4.5).
        first = validate_success(api.create_run_in_test(
            order_id,
            {"duration_minutes": 120, "max_temp_c": 80.0,
             "vibration_mm_s": 5.0, "oil_particle_count": 1_500},
            quality_inspector_headers), expected_status=201)
        assert first["result"] == "FAIL"
        assert get_order(order_id)["status"] == "IN_BUILD"

        # Rebuild with fresh in-tolerance measurements.
        api.start_assembly(order_id, reman_engineer_headers)
        fresh = record_assembly(order_id, backlash_mm=0.11)
        assert fresh["status"] == "ACTIVE"
        data = validate_success(
            api.submit_assembly(order_id, quality_inspector_headers))
        assert data["status"] == "RUN_IN"

        # A passing run-in now certifies the order.
        passed = validate_success(api.create_run_in_test(
            order_id,
            {"duration_minutes": 120, "max_temp_c": 80.0,
             "vibration_mm_s": 2.0, "oil_particle_count": 1_500},
            quality_inspector_headers), expected_status=201)
        assert passed["result"] == "PASS"
        assert passed["status"] == "RECORDED"
        assert passed["oil_baseline_established"] is True
        assert get_order(order_id)["status"] == "READY_TO_SHIP"


class TestImmediateConsistency:
    def test_run_in_pass_side_effects_immediately_visible(
            self, api, quality_inspector_headers, service_manager_headers):
        """PRD §3.4: "On a `PASS`, the test's `status` is `RECORDED`, its
        `oil_baseline_established` flag is set true — this row becomes the
        warranty oil baseline referenced in §3.7 — the order advances
        `RUN_IN → READY_TO_SHIP`, and the `final_invoice_cents` is computed:
        the sum of `line_total_cents` over the order's `APPROVED` decisions,
        plus the `freight_charge_cents` of every shipment on the order whose
        own status is not `CANCELLED`."

        Design: Corner/consistency_model/cascade_visible_immediately_in_same_request_chain
        """
        ctx = setup_order_in_run_in(
            serial_number="GBX-IM", quoted_estimate_cents=500_000,
            components=[
                ("PINION_1", "REGRINDABLE", 3, "REGRIND", 4.0, 12_000),
                ("GEAR_2", "CUT_ONLY", 4, "CUT_NEW", 6.5, 450_000),
            ])
        order_id = ctx["order"]["id"]
        version_before = get_order(order_id)["version"]
        add_shipment(order_id, direction="OUTBOUND", weight_kg=1_500,
                     rigging_bay_date="2026-08-17", rigging_bay_hours=4)

        api.create_run_in_test(
            order_id,
            {"duration_minutes": 120, "max_temp_c": 88.0,
             "vibration_mm_s": 3.1, "oil_particle_count": 2_400},
            quality_inspector_headers)

        # The very next read reflects every side effect: status, invoice.
        order = get_order(order_id)
        assert order["status"] == "READY_TO_SHIP"
        # 46000 + 542300 scope + (120000 + 4*9500) freight = 746300.
        assert order["final_invoice_cents"] == 746_300
        assert order["version"] > version_before
