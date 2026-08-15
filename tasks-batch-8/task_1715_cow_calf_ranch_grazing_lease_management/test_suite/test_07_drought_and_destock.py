"""Drought assessments: posture thresholds, the destock cascade, single-pass
reduction allocation, zero-deficit boundary, measurement completeness, OCC,
and herd reductions."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_aum,
    assert_date_field,
    assert_pct1,
    create_drought_assessment,
    create_herd_group,
    create_pasture,
    create_ranch,
    finalize_assessment,
    get_herd_group,
    get_pasture,
    get_ranch,
    get_success_data,
    list_destock_orders,
    record_reduction,
    setup_critical_drought,
    setup_drought_ranch,
    validate_error,
    validate_success,
)

RANCH_MGR = TEST_USERS["ranch_manager_headers"]
RANGE_MGR = TEST_USERS["range_manager_headers"]


class TestSinglePassReductionAllocation:
    def test_critical_assessment_figures(self, api):
        """PRD §3.8: "The `resulting_posture` maps that percentage onto the four
        postures: 90 or higher yields `NORMAL`, at least 75 but below 90 yields
        `WATCH`, at least 55 but below 75 yields `ALERT`, and below 55 yields
        `CRITICAL`."
        PRD §3.8: "The `deficit_aum_per_30d` is the demand minus the supply,
        rounded half-up to 2 decimal places."

        Design: Difficulty/combinatorial_formula/destock_single_pass_class_priority
        """
        ctx = setup_critical_drought()
        data = get_success_data(api.get_drought_assessment(
            ctx["assessment"]["id"], RANGE_MGR))
        assert_pct1(data["ranch_production_pct"], 44.0,
                    "(300x40 + 200x50) / 500")
        assert data["resulting_posture"] == "CRITICAL", "44.0 < 55"
        assert_aum(data["monthly_supply_aum"], 50.0, "500 x 0.50 / 5")
        assert_aum(data["monthly_demand_aum"], 105.8,
                   "30.0 GROWING + 61.8 MATURE_COW + 14.0 REPLACEMENT_HEIFER")
        assert_aum(data["deficit_aum_per_30d"], 55.8)
        assert data["assessment_status"] == "FINALIZED"

    def test_required_reduction_single_pass_ceil_per_group(self, api):
        """PRD §3.8: "The order's `required_reduction_head` is computed by a
        single left-to-right pass with no re-iteration, so the result is fully
        determined. Candidate herd groups are sorted by class priority —
        `GROWING` groups first, then `MATURE_COW`, then `REPLACEMENT_HEIFER` —
        within a class by descending `avg_weight_lbs` so heavier groups are
        drawn first, and remaining ties by each group's `created_at` in
        ascending order."
        PRD §3.8: "its `deadline_date` is the assessment's `assessment_date`
        plus the ranch's `destock_grace_days`"

        Design: Difficulty/combinatorial_formula/destock_single_pass_class_priority
        """
        ctx = setup_critical_drought()
        assert len(ctx["orders"]) == 1, "exactly one destock order is created"
        order = ctx["orders"][0]
        # 55.8 deficit: all 40 GROWING (30.0 AUM), then ceil(25.8 / 1.03) = 26
        # MATURE_COW; the REPLACEMENT_HEIFER group is never touched.
        assert order["required_reduction_head"] == 66
        assert order["received_reduction_head"] == 0
        assert order["order_status"] == "OPEN"
        assert_date_field(order["deadline_date"], "2026-08-31",
                          "2026-08-01 + 30 grace days")


class TestCriticalFinalizeCascade:
    def test_finalize_flips_posture_groups_and_blocks_commitments(self, api):
        """PRD §3.8: "When the finalized `deficit_aum_per_30d` is strictly
        greater than zero — whatever posture resulted — finalization also
        creates a destock order whose `order_status` opens at `OPEN`, and that
        single creation is the cause of a ranch-wide cascade: every herd group
        on the ranch whose `group_status` is `ACTIVE` flips to `DESTOCKING`."
        PRD §2.11: "When both gates could fire, the destock-order check is
        evaluated first, so a ranch under an open order always surfaces
        `ERR_DESTOCK_ORDER_BLOCKING` rather than the posture error."

        Design: Difficulty/transitive_cascade/drought_finalize_critical_cascade
        """
        ctx = setup_critical_drought()
        ranch = get_ranch(ctx["ranch"]["id"])
        assert ranch["drought_posture"] == "CRITICAL"
        assert ranch["version"] == ctx["ranch"]["version"] + 1
        for g in (ctx["g1"], ctx["g2"], ctx["g3"]):
            assert get_herd_group(g["id"])["group_status"] == "DESTOCKING"

        p3 = create_pasture(ctx["ranch"]["id"], name="Spare", acreage=400,
                            base_capacity_aum=100)
        resp = api.create_grazing_assignment(
            {"pasture_id": p3["id"], "herd_group_id": ctx["g3"]["id"],
             "ranch_id": ctx["ranch"]["id"], "start_date": "2026-08-05",
             "planned_end_date": "2026-09-04"}, RANGE_MGR)
        validate_error(resp, ApiErrorId.ERR_DESTOCK_ORDER_BLOCKING,
                       expected_status=422)

    def test_reductions_credit_order_and_compliance_restores_groups(self, api):
        """PRD §3.8: "when a `destock_order_id` is supplied and that order is
        `OPEN` or `EXPIRED`, the order's `received_reduction_head` grows by the
        reduced head"
        PRD §3.8: "when the received head has reached the requirement, the order
        becomes `COMPLIANT`, and this holds whether the order was `OPEN` or had
        already slipped to `EXPIRED`"
        PRD §3.8: "Whenever an order reaches `COMPLIANT` or `WAIVED`, herd
        groups return from `DESTOCKING` to `ACTIVE`"

        Design: Difficulty/transitive_cascade/drought_finalize_critical_cascade
        """
        ctx = setup_critical_drought()
        order = ctx["orders"][0]
        g1 = record_reduction(ctx["g1"]["id"], 40, "LIQUIDATION",
                              destock_order_id=order["id"])
        assert g1["head_count"] == 0
        assert g1["group_status"] == "LIQUIDATED"
        g2 = record_reduction(ctx["g2"]["id"], 26, "CULL",
                              destock_order_id=order["id"])
        assert g2["head_count"] == 34

        after = get_success_data(api.get_destock_order(order["id"], RANGE_MGR))
        assert after["received_reduction_head"] == 66

        resolved = validate_success(api.verify_compliance(order["id"], RANGE_MGR))
        assert resolved["order_status"] == "COMPLIANT"
        assert get_herd_group(ctx["g2"]["id"])["group_status"] == "ACTIVE"
        assert get_herd_group(ctx["g3"]["id"])["group_status"] == "ACTIVE"
        # The liquidated group stays out of the cycle.
        assert get_herd_group(ctx["g1"]["id"])["group_status"] == "LIQUIDATED"


class TestZeroDeficitBoundary:
    def _setup_zero_deficit(self, api):
        ranch = create_ranch(name="ZeroDef Ranch", hq_state="MT")
        p1 = create_pasture(ranch["id"], name="N", acreage=1500,
                            base_capacity_aum=300)
        p2 = create_pasture(ranch["id"], name="S", acreage=1000,
                            base_capacity_aum=200)
        group = create_herd_group(ranch["id"], group_name="Cows",
                                  head_count=100, avg_weight_lbs=1000)
        assessment = create_drought_assessment(
            ranch["id"], "2026-08-01",
            [{"pasture_id": p1["id"], "production_pct_of_normal": 95},
             {"pasture_id": p2["id"], "production_pct_of_normal": 95}])
        return ranch, group, assessment

    def test_zero_deficit_creates_no_destock_order(self, api):
        """PRD §3.8: "When the finalized `deficit_aum_per_30d` is strictly
        greater than zero — whatever posture resulted — finalization also
        creates a destock order whose `order_status` opens at `OPEN`"

        Design: Difficulty/boundary_precision_check/destock_zero_deficit_no_order
        """
        ranch, group, assessment = self._setup_zero_deficit(api)
        data = finalize_assessment(assessment["id"], ranch["version"])
        assert_aum(data["deficit_aum_per_30d"], 0.0,
                   "demand 100.0 == supply 100.0")
        assert data["resulting_posture"] == "NORMAL"
        orders, meta = list_destock_orders(ranch["id"])
        assert meta["total_count"] == 0, (
            "deficit == 0 does not trigger an order (strictly-greater rule)"
        )
        assert orders == []
        assert get_herd_group(group["id"])["group_status"] == "ACTIVE", (
            "no DESTOCKING flip without an order"
        )

    def test_zero_deficit_finalize_still_updates_ranch(self, api):
        """PRD §3.8: "A successful finalize — permitted only from `DRAFT` —
        writes the assessment's `resulting_posture` onto the ranch's
        `drought_posture`, copies the assessment's `ranch_production_pct` onto
        the ranch, increments the ranch's `assessment_seq` by one, and
        increments the ranch's `version` by one."

        Design: Difficulty/boundary_precision_check/destock_zero_deficit_no_order
        """
        ranch, _group, assessment = self._setup_zero_deficit(api)
        finalize_assessment(assessment["id"], ranch["version"])
        after = get_ranch(ranch["id"])
        assert after["drought_posture"] == "NORMAL"
        assert_pct1(after["ranch_production_pct"], 95.0)
        assert after["assessment_seq"] == 1
        assert after["version"] == ranch["version"] + 1


class TestPostureThresholds:
    def test_posture_threshold_constants_applied(self, api):
        """PRD §3.8: "The `resulting_posture` maps that percentage onto the four
        postures: 90 or higher yields `NORMAL`, at least 75 but below 90 yields
        `WATCH`, at least 55 but below 75 yields `ALERT`, and below 55 yields
        `CRITICAL`."
        PRD §2.9: "The pasture's `effective_capacity_aum` scales that rating by
        the ranch's current drought posture: the full base capacity under
        `NORMAL`, 85 percent of it under `WATCH`, 70 percent under `ALERT`, and
        50 percent under `CRITICAL`, with the product rounded half-up to 2
        decimal places."

        Design: Corner/calculations/posture_threshold_constants_applied
        """
        ranch = create_ranch(name="R")
        pasture = create_pasture(ranch["id"], name="P", acreage=400,
                                 base_capacity_aum=100)
        create_herd_group(ranch["id"], group_name="G", animal_class="GROWING",
                          head_count=10, avg_weight_lbs=800)
        version = ranch["version"]
        for pct, expected_posture in ((90, "NORMAL"), (74, "ALERT"),
                                      (54, "CRITICAL")):
            assessment = create_drought_assessment(
                ranch["id"], "2026-08-01",
                [{"pasture_id": pasture["id"], "production_pct_of_normal": pct}])
            finalize_assessment(assessment["id"], version)
            after = get_ranch(ranch["id"])
            assert after["drought_posture"] == expected_posture, (
                f"pct {pct} must yield {expected_posture}"
            )
            version = after["version"]
        # CRITICAL halves the effective capacity.
        assert_aum(get_pasture(pasture["id"])["effective_capacity_aum"], 50.0,
                   "100 x 0.50")
        orders, meta = list_destock_orders(ranch["id"])
        assert meta["total_count"] == 0, "demand 7.5 is always below supply"


class TestMeasurementCompleteness:
    def test_assessment_incomplete_measurements_rejected(self, api):
        """PRD §3.8: "The measurements must cover every pasture of the ranch
        that is not closed exactly once: a missing pasture, a duplicated
        pasture, or a reference to an unknown pasture all fail creation with
        `ERR_ASSESSMENT_MEASUREMENT_INCOMPLETE` (HTTP 422)."

        Design: Corner/validations/assessment_incomplete_measurements_rejected
        """
        ranch = create_ranch(name="R")
        p1 = create_pasture(ranch["id"], name="P1", base_capacity_aum=100)
        p2 = create_pasture(ranch["id"], name="P2", base_capacity_aum=100)
        resp = api.create_drought_assessment(
            {"ranch_id": ranch["id"], "assessment_date": "2026-08-01",
             "pasture_measurements": [
                 {"pasture_id": p1["id"], "production_pct_of_normal": 80}]},
            RANGE_MGR)
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_MEASUREMENT_INCOMPLETE,
                       expected_status=422)

        data = create_drought_assessment(
            ranch["id"], "2026-08-01",
            [{"pasture_id": p1["id"], "production_pct_of_normal": 80},
             {"pasture_id": p2["id"], "production_pct_of_normal": 80}])
        assert data["assessment_status"] == "DRAFT"
        assert_pct1(data["ranch_production_pct"], 80.0)
        assert data["resulting_posture"] == "WATCH", "75 <= 80 < 90"


class TestAssessmentFinalizeOcc:
    def test_finalize_with_stale_ranch_version_rejected(self, api):
        """PRD §2.7: "Finalizing a drought assessment requires the request to
        carry `expected_ranch_version`, holding the `version` of the ranch the
        client last observed."
        PRD §2.7: "When the supplied expectation does not equal the parent
        resource's current `version` — because another write has advanced that
        version since the client last read it — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_assessment_finalize_stale_version_rejected
        """
        ranch = create_ranch(name="R")
        pasture = create_pasture(ranch["id"], name="P", acreage=400,
                                 base_capacity_aum=100)
        create_herd_group(ranch["id"], group_name="G", animal_class="GROWING",
                          head_count=10, avg_weight_lbs=800)
        stale_version = ranch["version"]
        patched = validate_success(api.patch_ranch(
            ranch["id"], {"destock_grace_days": 21}, RANCH_MGR))
        assessment = create_drought_assessment(
            ranch["id"], "2026-08-01",
            [{"pasture_id": pasture["id"], "production_pct_of_normal": 80}])

        resp = api.finalize_assessment(
            assessment["id"], {"expected_ranch_version": stale_version},
            RANGE_MGR)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        done = finalize_assessment(assessment["id"], patched["version"])
        assert done["assessment_status"] == "FINALIZED"
        after = get_ranch(ranch["id"])
        assert after["drought_posture"] == "WATCH", "75 <= 80 < 90"
        assert_pct1(after["ranch_production_pct"], 80.0)
        assert after["assessment_seq"] == 1
        assert after["version"] == patched["version"] + 1


class TestReductions:
    def test_reduction_exceeds_head_rejected(self, api):
        """PRD §3.8: "The reduction may not exceed the group's current
        `head_count`, and a `LIQUIDATION` must take the group's full remaining
        head exactly; either violation is rejected with
        `ERR_DESTOCK_REDUCTION_EXCEEDS_HEAD` (HTTP 422)."
        PRD §3.8: "A liquidation additionally moves the group to `LIQUIDATED`,
        zeroes its head, and removes it from all future destock demand
        calculations."

        Design: Corner/validations/reduction_exceeds_head_rejected
        """
        ranch = create_ranch(name="R")
        group = create_herd_group(ranch["id"], group_name="G", head_count=60)
        resp = api.record_reduction(
            group["id"], {"head_count": 61, "reason": "LIQUIDATION"},
            TEST_USERS["herd_manager_headers"])
        validate_error(resp, ApiErrorId.ERR_DESTOCK_REDUCTION_EXCEEDS_HEAD,
                       expected_status=422)
        resp = api.record_reduction(
            group["id"], {"head_count": 59, "reason": "LIQUIDATION"},
            TEST_USERS["herd_manager_headers"])
        validate_error(resp, ApiErrorId.ERR_DESTOCK_REDUCTION_EXCEEDS_HEAD,
                       expected_status=422)

        done = record_reduction(group["id"], 60, "LIQUIDATION")
        assert done["head_count"] == 0
        assert done["group_status"] == "LIQUIDATED"

    def test_reduction_response_reflects_head_decrement(self, api):
        """PRD §3.8: "Every reduction subtracts its head from the group's
        `head_count`"
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/endpoints/reduction_response_reflects_head_decrement
        """
        ranch = create_ranch(name="R")
        group = create_herd_group(ranch["id"], group_name="G", head_count=60)
        after = record_reduction(group["id"], 10, "SALE")
        assert after["head_count"] == 50, "the action response carries the mutation"
        assert after["group_status"] == "ACTIVE", "no destock order involved"
        assert get_herd_group(group["id"])["head_count"] == 50
