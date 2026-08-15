"""Shop execution: verdict variants and tolerance boundaries, the repair-test
rework loop, SRV certification gating, segregation of duties, and voids."""
import pytest

from test_helpers import (
    POINT_CLEAR_FAIL,
    POINT_ZERO_DEVIATION,
    TEST_USERS,
    VARIANT_POINTS,
    ApiErrorId,
    api_client,
    assert_certification,
    assert_test_run,
    create_asset,
    create_certification_payload,
    create_customer,
    create_repair_order,
    create_test_run_payload,
    get_repair_order,
    get_success_data,
    make_certifier_headers,
    make_technician_headers,
    record_test_run,
    setup_authorized_shop,
    setup_in_test_shop,
    setup_srv_ready_for_cert_shop,
    validate_error,
    validate_success,
)

SM = TEST_USERS["service_manager_headers"]
IC = TEST_USERS["intake_coordinator_headers"]
TECH = TEST_USERS["technician_headers"]


class TestVerdictVariants:
    def test_identical_points_diverge_per_point_vs_weighted_avg(self, api):
        """PRD §3.7: "Under the per-point variant selected by an `API_610_PER_POINT` asset, the `verdict` is `PASS` only when `max_deviation_pct` is at most 5.00; every point stands alone, and cancelling deviations cannot rescue a bad point."
        PRD §3.7: "Under the weighted-average variant of a `SHOP_WEIGHTED_AVG` asset, the run passes when the absolute `weighted_deviation_pct` is at most 5.00, so opposing deviations cancel and identical data can pass here while failing per-point."
        PRD §3.7: "A `FAIL` loops the order `IN_TEST` → `IN_REPAIR` and increments `repair_round` by one — the rework loop that later separates a first-time fix from a re-repair."

        Design: Difficulty/dual_variant_calc/test_verdict_per_point_vs_weighted_avg_variant
        """
        # Deviations +8.00 / -8.00 / -2.00 on duty 80/100/120.
        per_point_shop = setup_in_test_shop(
            asset_over={"equipment_class": "PUMP",
                        "test_standard": "API_610_PER_POINT"})
        weighted_shop = setup_in_test_shop(
            asset_over={"equipment_class": "PUMP",
                        "test_standard": "SHOP_WEIGHTED_AVG"})

        run1 = record_test_run(per_point_shop["ro"]["id"],
                               measured_points=VARIANT_POINTS)
        assert_test_run(run1)
        assert run1["verdict"] == "FAIL", "max deviation 8.00 exceeds 5.00 per-point"
        assert run1["max_deviation_pct"] == pytest.approx(8.00, abs=1e-9)
        ro1 = get_repair_order(per_point_shop["ro"]["id"])
        assert ro1["status"] == "IN_REPAIR"
        assert ro1["repair_round"] == 1

        run2 = record_test_run(weighted_shop["ro"]["id"],
                               measured_points=VARIANT_POINTS)
        assert_test_run(run2)
        assert run2["verdict"] == "PASS", "weighted mean -1.33 is within tolerance"
        assert run2["weighted_deviation_pct"] == pytest.approx(-1.33, abs=1e-9)
        ro2 = get_repair_order(weighted_shop["ro"]["id"])
        assert ro2["status"] == "COMPLETE", "a passing run completes non-SRV work"

    def test_both_deviation_metrics_recorded_on_every_run(self, api):
        """PRD §3.7: "The run's `max_deviation_pct` is the largest absolute value among the rounded per-point deviations."
        PRD §3.7: "Its `weighted_deviation_pct` is the duty-weighted average of the rounded per-point deviations — each deviation multiplied by its point's `duty_pct`, the products summed and divided by the sum of all `duty_pct` values — itself rounded half-up to two decimal places."
        PRD §3.7: "Runs are numbered with a 1-based chronological `run_number` per repair order, and the recorder's `X-User-ID` is stored as `tested_by_id`."

        Design: Difficulty/dual_variant_calc/test_verdict_per_point_vs_weighted_avg_variant
        """
        per_point_shop = setup_in_test_shop(
            asset_over={"equipment_class": "PUMP",
                        "test_standard": "API_610_PER_POINT"},
            technician_id="tech-041")
        weighted_shop = setup_in_test_shop(
            asset_over={"equipment_class": "PUMP",
                        "test_standard": "SHOP_WEIGHTED_AVG"},
            technician_id="tech-042")

        run1 = record_test_run(per_point_shop["ro"]["id"],
                               measured_points=VARIANT_POINTS,
                               technician_id="tech-041")
        run2 = record_test_run(weighted_shop["ro"]["id"],
                               measured_points=VARIANT_POINTS,
                               technician_id="tech-042")

        # Both metrics are computed on every run regardless of the verdict variant.
        assert run1["max_deviation_pct"] == pytest.approx(8.00, abs=1e-9)
        assert run1["weighted_deviation_pct"] == pytest.approx(-1.33, abs=1e-9)
        assert run2["max_deviation_pct"] == pytest.approx(8.00, abs=1e-9)
        assert run2["weighted_deviation_pct"] == pytest.approx(-1.33, abs=1e-9)
        assert run1["verdict"] == "FAIL" and run2["verdict"] == "PASS"
        assert run1["run_number"] == 1 and run2["run_number"] == 1
        assert run1["tested_by_id"] == "tech-041"
        assert run2["tested_by_id"] == "tech-042"


class TestToleranceBoundary:
    def test_deviation_exactly_at_tolerance_passes_one_centiliter_over_fails(self, api):
        """PRD §3.7: "Both boundaries are inclusive — a deviation of exactly 5.00 passes, 5.01 fails — and every comparison uses the rounded values."

        Design: Difficulty/boundary_precision_check/test_verdict_tolerance_boundary_inclusive
        """
        pass_shop = setup_in_test_shop(
            asset_over={"equipment_class": "PUMP",
                        "test_standard": "API_610_PER_POINT"})
        fail_shop = setup_in_test_shop(
            asset_over={"equipment_class": "PUMP",
                        "test_standard": "API_610_PER_POINT"})

        run_pass = record_test_run(
            pass_shop["ro"]["id"],
            measured_points=[{"duty_pct": 100, "measured_value": 105,
                              "reference_value": 100}])
        assert run_pass["max_deviation_pct"] == pytest.approx(5.00, abs=1e-9)
        assert run_pass["verdict"] == "PASS", "deviation exactly 5.00 passes (inclusive)"
        assert get_repair_order(pass_shop["ro"]["id"])["status"] == "COMPLETE"

        run_fail = record_test_run(
            fail_shop["ro"]["id"],
            measured_points=[{"duty_pct": 100, "measured_value": 105.01,
                              "reference_value": 100}])
        assert run_fail["max_deviation_pct"] == pytest.approx(5.01, abs=1e-9)
        assert run_fail["verdict"] == "FAIL"
        ro = get_repair_order(fail_shop["ro"]["id"])
        assert ro["status"] == "IN_REPAIR"
        assert ro["repair_round"] == 1

    def test_negative_deviation_boundary_on_weighted_variant(self, api):
        """PRD §3.7: "Under the weighted-average variant of a `SHOP_WEIGHTED_AVG` asset, the run passes when the absolute `weighted_deviation_pct` is at most 5.00, so opposing deviations cancel and identical data can pass here while failing per-point."
        PRD §3.7: "Both boundaries are inclusive — a deviation of exactly 5.00 passes, 5.01 fails — and every comparison uses the rounded values."

        Design: Difficulty/boundary_precision_check/test_verdict_tolerance_boundary_inclusive
        """
        low_pass_shop = setup_in_test_shop(
            asset_over={"equipment_class": "PUMP",
                        "test_standard": "SHOP_WEIGHTED_AVG"})
        low_fail_shop = setup_in_test_shop(
            asset_over={"equipment_class": "PUMP",
                        "test_standard": "SHOP_WEIGHTED_AVG"})

        run_pass = record_test_run(
            low_pass_shop["ro"]["id"],
            measured_points=[{"duty_pct": 100, "measured_value": 95,
                              "reference_value": 100}])
        assert run_pass["weighted_deviation_pct"] == pytest.approx(-5.00, abs=1e-9)
        assert run_pass["verdict"] == "PASS", "absolute value 5.00 is within tolerance"

        run_fail = record_test_run(
            low_fail_shop["ro"]["id"],
            measured_points=[{"duty_pct": 100, "measured_value": 94.99,
                              "reference_value": 100}])
        assert run_fail["weighted_deviation_pct"] == pytest.approx(-5.01, abs=1e-9)
        assert run_fail["verdict"] == "FAIL"
        assert get_repair_order(low_fail_shop["ro"]["id"])["repair_round"] == 1


class TestReworkCycle:
    def test_fail_rework_pass_then_close_records_re_repair(self, api):
        """PRD §3.7: "A `FAIL` loops the order `IN_TEST` → `IN_REPAIR` and increments `repair_round` by one — the rework loop that later separates a first-time fix from a re-repair."
        PRD §3.7: "A `PASS` on an order that requires certification advances it `IN_TEST` → `READY_FOR_CERT`; a `PASS` on any other order completes the technical work, `IN_TEST` → `COMPLETE`."
        PRD §3.9: "Closing an order moves it `COMPLETE` → `CLOSED` and settles every open ledger at once: `closed_at` stamps the current logical clock; `invoiced_total_cents` snapshots the approved quote's `total_cents`; `repair_outcome` resolves to `FIRST_TIME_FIX` when `repair_round` is zero and `RE_REPAIR` otherwise; the order's `estimated_bay_hours` are subtracted from its window's `bay_hours_reserved`, recomputing the window's posture; and, where a pool unit stands `RESERVED` for this order, the exchange settles — the reserved unit moves `RESERVED` → `ISSUED`, and a fresh pool unit carrying this order's `customer_id` and `asset_id` is created `IN_POOL` as replenishment."

        Design: Difficulty/non_linear_state_machine/repair_order_test_fail_rework_cycle
        """
        shop = setup_in_test_shop(
            asset_over={"equipment_class": "PUMP",
                        "test_standard": "API_610_PER_POINT"})

        # First run: deviation 10.00 -> FAIL -> back to IN_REPAIR.
        run1 = record_test_run(shop["ro"]["id"], measured_points=[POINT_CLEAR_FAIL])
        assert run1["verdict"] == "FAIL"
        ro = get_repair_order(shop["ro"]["id"])
        assert ro["status"] == "IN_REPAIR"
        assert ro["repair_round"] == 1

        # Rework and resubmit; second run at exactly 5.00 passes (inclusive).
        get_success_data(api_client.submit_for_test(shop["ro"]["id"], TECH))
        run2 = record_test_run(
            shop["ro"]["id"],
            measured_points=[{"duty_pct": 100, "measured_value": 105,
                              "reference_value": 100}])
        assert run2["verdict"] == "PASS", "5.00 <= 5.0 inclusive"
        assert get_repair_order(shop["ro"]["id"])["status"] == "COMPLETE"

        closed = get_success_data(api_client.close_repair_order(shop["ro"]["id"], IC))
        assert closed["status"] == "CLOSED"
        assert closed["repair_round"] == 1
        assert closed["repair_outcome"] == "RE_REPAIR"

    def test_two_fail_loops_increment_repair_round_and_run_number(self, api):
        """PRD §3.7: "A `FAIL` loops the order `IN_TEST` → `IN_REPAIR` and increments `repair_round` by one — the rework loop that later separates a first-time fix from a re-repair."
        PRD §3.7: "Runs are numbered with a 1-based chronological `run_number` per repair order, and the recorder's `X-User-ID` is stored as `tested_by_id`."
        PRD §3.9: "Closing an order moves it `COMPLETE` → `CLOSED` and settles every open ledger at once: `closed_at` stamps the current logical clock; `invoiced_total_cents` snapshots the approved quote's `total_cents`; `repair_outcome` resolves to `FIRST_TIME_FIX` when `repair_round` is zero and `RE_REPAIR` otherwise; the order's `estimated_bay_hours` are subtracted from its window's `bay_hours_reserved`, recomputing the window's posture; and, where a pool unit stands `RESERVED` for this order, the exchange settles — the reserved unit moves `RESERVED` → `ISSUED`, and a fresh pool unit carrying this order's `customer_id` and `asset_id` is created `IN_POOL` as replenishment."

        Design: Difficulty/non_linear_state_machine/repair_order_test_fail_rework_cycle
        """
        shop = setup_in_test_shop(
            asset_over={"equipment_class": "PUMP",
                        "test_standard": "API_610_PER_POINT"})

        for expected_round in (1, 2):
            run = record_test_run(shop["ro"]["id"], measured_points=[POINT_CLEAR_FAIL])
            assert run["verdict"] == "FAIL"
            ro = get_repair_order(shop["ro"]["id"])
            assert ro["status"] == "IN_REPAIR"
            assert ro["repair_round"] == expected_round
            get_success_data(api_client.submit_for_test(shop["ro"]["id"], TECH))

        run3 = record_test_run(shop["ro"]["id"], measured_points=[POINT_ZERO_DEVIATION])
        assert run3["verdict"] == "PASS"

        runs = get_success_data(api_client.list_test_runs(shop["ro"]["id"], SM))
        assert [r["run_number"] for r in runs] == [1, 2, 3], (
            "1-based chronological numbering per repair order"
        )

        closed = get_success_data(api_client.close_repair_order(shop["ro"]["id"], IC))
        assert closed["repair_round"] == 2
        assert closed["repair_outcome"] == "RE_REPAIR"
        assert closed["status"] == "CLOSED"


class TestCertificationGates:
    def test_srv_submit_for_test_requires_assembly_record(self, api):
        """PRD §3.7: "Submitting the order for test moves it `IN_REPAIR` → `IN_TEST` — but an order whose `requires_certification` is true needs an assembly record first: submitting with no `assembled_by_id` logged is rejected with `ERR_ASSEMBLY_NOT_RECORDED`."
        PRD §3.3: "The `requires_certification` flag is derived from the asset: true exactly when the unit is a `SAFETY_RELIEF_VALVE`."

        Design: Corner/state_machines/srv_submit_for_test_requires_assembly_record
        """
        shop = setup_authorized_shop(
            asset_over={"equipment_class": "SAFETY_RELIEF_VALVE",
                        "manufacturer": "Consolidated", "model": "1900",
                        "set_pressure_psig": 100},
            ro_over={"failure_mode": "SPRING_DRIFT"})
        assert shop["ro"]["requires_certification"] is True

        get_success_data(api_client.start_repair(
            shop["ro"]["id"], make_technician_headers("tech-001")))
        resp = api_client.submit_for_test(
            shop["ro"]["id"], make_technician_headers("tech-001"))
        validate_error(resp, ApiErrorId.ERR_ASSEMBLY_NOT_RECORDED)
        assert get_repair_order(shop["ro"]["id"])["status"] == "IN_REPAIR"

    def test_certification_not_applicable_on_pump(self, api):
        """PRD §3.8: "The applicability gate is permanent and runs before any state check — attempting certification on an order whose asset is not a `SAFETY_RELIEF_VALVE` is rejected with `ERR_CERTIFICATION_NOT_APPLICABLE` regardless of the order's status."
        PRD §3.3: "The `requires_certification` flag is derived from the asset: true exactly when the unit is a `SAFETY_RELIEF_VALVE`."

        Design: Corner/validations/certification_not_applicable_on_pump
        """
        customer = create_customer(name="Pearsall", account_number="PA-480",
                                   credit_limit_cents=99999999, warranty_terms_days=365)
        asset = create_asset(customer["id"], serial_number="P-4801",
                             equipment_class="PUMP", rated_flow_gpm=500)
        ro = create_repair_order(customer["id"], asset["id"],
                                 failure_mode="SEAL_LEAK", estimated_bay_hours=5)
        assert ro["requires_certification"] is False

        # Even from RECEIVED (also an invalid from-state), the applicability
        # gate fires first within the state tier.
        resp = api_client.create_certification(
            ro["id"], create_certification_payload(set_pressure_psig=100),
            make_certifier_headers("cert-002"))
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_NOT_APPLICABLE)


class TestSegregationOfDuties:
    def test_state_error_outranks_sod_when_both_violated(self, api):
        """PRD §2.6: "Incoming requests are validated in a fixed priority order; a failure at an earlier tier is never masked by a later one."
        PRD §2.6: "5. **State validity** — the target entity must be in a valid from-state for the requested transition, terminal states are locked, and the quote-creation version check must match (`ERR_INVALID_STATE`, HTTP 409; the version mismatch carries `ERR_STALE_VERSION`, HTTP 412, on quote creation)."
        PRD §2.6: "6. **Certification safety** — segregation of duties and set-pressure tolerance (`ERR_SOD_VIOLATION` and `ERR_SET_PRESSURE_OUT_OF_TOLERANCE`, HTTP 422), evaluated only on certification issuance."

        Design: Difficulty/priority_pair_validation_conflict/certify_state_vs_sod_priority_conflict
        """
        # Order is IN_TEST (not READY_FOR_CERT) AND the certifier id equals the
        # assembler id: the state-tier error must surface.
        shop = setup_in_test_shop(
            technician_id="tech-001",
            asset_over={"equipment_class": "SAFETY_RELIEF_VALVE",
                        "manufacturer": "Consolidated", "model": "1900",
                        "set_pressure_psig": 100},
            ro_over={"failure_mode": "SPRING_DRIFT"})
        assert shop["ro"]["status"] == "IN_TEST"

        resp = api_client.create_certification(
            shop["ro"]["id"],
            create_certification_payload(set_pressure_psig=100),
            make_certifier_headers("tech-001"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_repair_order(shop["ro"]["id"])["status"] == "IN_TEST"
        certs = get_success_data(api_client.list_certifications(shop["ro"]["id"], SM))
        assert certs == [], "no certification is persisted"

    def test_sod_violation_when_state_is_clean(self, api):
        """PRD §3.8: "Segregation of duties: the certifier's `X-User-ID`, stored as `certified_by_id`, must differ from the order's `assembled_by_id`; a certifier who assembled the valve is rejected with `ERR_SOD_VIOLATION` (HTTP 422)."
        PRD §3.8: "For an applicable order, certification requires `READY_FOR_CERT`; any other state is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/certify_state_vs_sod_priority_conflict
        """
        shop = setup_srv_ready_for_cert_shop(assembler_id="tech-001")
        assert shop["ro"]["status"] == "READY_FOR_CERT"

        resp = api_client.create_certification(
            shop["ro"]["id"],
            create_certification_payload(set_pressure_psig=100),
            make_certifier_headers("tech-001"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        assert get_repair_order(shop["ro"]["id"])["status"] == "READY_FOR_CERT"
        certs = get_success_data(api_client.list_certifications(shop["ro"]["id"], SM))
        assert certs == []

    def test_assembler_rejected_other_certifier_succeeds_with_sequential_tag(self, api):
        """PRD §3.8: "Segregation of duties: the certifier's `X-User-ID`, stored as `certified_by_id`, must differ from the order's `assembled_by_id`; a certifier who assembled the valve is rejected with `ERR_SOD_VIOLATION` (HTTP 422)."
        PRD §3.8: "Each issued certification is tagged with a sequential `tag_number` minted in creation order — `SVT-000001`, `SVT-000002`, and so on — and begins with `cert_status` `ISSUED`. Issuance completes the order: `READY_FOR_CERT` → `COMPLETE`, incrementing its `version` by one."

        Design: Corner/rbac/sod_same_user_rejected_other_user_succeeds
        """
        shop = setup_srv_ready_for_cert_shop(assembler_id="tech-001")

        resp = api_client.create_certification(
            shop["ro"]["id"],
            create_certification_payload(set_pressure_psig=100),
            make_certifier_headers("tech-001"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

        cert = validate_success(api_client.create_certification(
            shop["ro"]["id"],
            create_certification_payload(set_pressure_psig=100.5),
            make_certifier_headers("cert-002")), 201)
        assert_certification(cert)
        assert cert["tag_number"] == "SVT-000001", "first tag minted on this server"
        assert cert["certified_by_id"] == "cert-002"
        assert cert["cert_status"] == "ISSUED"
        assert get_repair_order(shop["ro"]["id"])["status"] == "COMPLETE"


class TestSetPressureTolerance:
    def test_three_percent_boundary_inclusive(self, api):
        """PRD §3.8: "Set-pressure fidelity: the as-tested pressure must sit within three percent of the asset's nameplate `set_pressure_psig` in either direction — the absolute difference divided by the nameplate value must not exceed 0.03, so a deviation of exactly three percent passes and anything greater is rejected with `ERR_SET_PRESSURE_OUT_OF_TOLERANCE` (HTTP 422)."

        Design: Corner/validations/set_pressure_tolerance_boundary
        """
        shop = setup_srv_ready_for_cert_shop(assembler_id="tech-001")
        # Nameplate set pressure is 100 psig.

        over = api_client.create_certification(
            shop["ro"]["id"],
            create_certification_payload(set_pressure_psig=103.01),
            make_certifier_headers("cert-002"))
        validate_error(over, ApiErrorId.ERR_SET_PRESSURE_OUT_OF_TOLERANCE)
        assert get_repair_order(shop["ro"]["id"])["status"] == "READY_FOR_CERT", (
            "a rejected attempt leaves the order in place"
        )

        cert = validate_success(api_client.create_certification(
            shop["ro"]["id"],
            create_certification_payload(set_pressure_psig=103.00),
            make_certifier_headers("cert-002")), 201)
        assert cert["cert_status"] == "ISSUED", "exactly 3% passes (inclusive)"


class TestCertificationVoid:
    def test_void_reverts_order_and_recertification_completes(self, api):
        """PRD §3.8: "A `ServiceManager` may later void a certification, recording a `void_reason` — null while the certification is `ISSUED` — and moving it `ISSUED` → `VOIDED`. Voiding is a compensation revert: the order falls back `COMPLETE` → `READY_FOR_CERT`, and a fresh certification is required to complete it again."
        PRD §3.8: "Each issued certification is tagged with a sequential `tag_number` minted in creation order — `SVT-000001`, `SVT-000002`, and so on — and begins with `cert_status` `ISSUED`."

        Design: Corner/state_machines/certification_void_reverts_ro_to_ready_for_cert
        """
        shop = setup_srv_ready_for_cert_shop(assembler_id="tech-001")
        cert1 = validate_success(api_client.create_certification(
            shop["ro"]["id"],
            create_certification_payload(set_pressure_psig=100),
            make_certifier_headers("cert-002")), 201)
        assert cert1["tag_number"] == "SVT-000001"
        assert get_repair_order(shop["ro"]["id"])["status"] == "COMPLETE"

        voided = get_success_data(api_client.void_certification(
            cert1["id"], "tag misprint", SM))
        assert voided["cert_status"] == "VOIDED"
        assert voided["void_reason"] == "tag misprint"
        assert get_repair_order(shop["ro"]["id"])["status"] == "READY_FOR_CERT", (
            "compensation revert reopens the certification step"
        )

        cert2 = validate_success(api_client.create_certification(
            shop["ro"]["id"],
            create_certification_payload(set_pressure_psig=100.2),
            make_certifier_headers("cert-002")), 201)
        assert cert2["tag_number"] == "SVT-000002", "the sequence advances"
        assert get_repair_order(shop["ro"]["id"])["status"] == "COMPLETE"
