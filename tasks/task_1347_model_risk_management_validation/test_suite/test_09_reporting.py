"""Board and regulatory reporting: snapshot fields, the inventory risk index, and
report-period overlap (PRD §3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_instant_equal,
    create_draft_report,
    create_finding,
    create_model,
    create_report_payload,
    create_submitted_report,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

OWNER_A = TEST_USERS["model_owner_a_headers"]
OFFICER = TEST_USERS["risk_officer_headers"]
REPORTER = TEST_USERS["reporter_headers"]


class TestReportSnapshots:
    def test_regulatory_report_snapshot_counts(self, api):
        """PRD §3.9: "The report is created in `DRAFT`, and all of its snapshot fields
        are computed once at creation and never recomputed afterward, so a report is a
        frozen view of the inventory as it stood at creation time."
        PRD §3.9: "From that set the server derives: `total_models`, the count of
        models in the set; `tier_1_count`, those with `risk_tier` `TIER_1`;
        `open_findings_total`, the findings on input-set models with status `OPEN`,
        `OVERDUE`, or `ESCALATED`; `open_critical_count`, the same restricted to
        severity `CRITICAL`; `breach_event_count`, the `OPEN` breach events on metrics
        of input-set models; and `overdue_validation_count`, the input-set models whose
        `validation_due_at` lies before the report's creation time."

        M1 TIER_1 (70), M2 TIER_3 (30) with one OPEN LOW finding: total 2, tier_1 1,
        open findings 1, open critical 0, breach events 0.

        Design: Corner/entities/regulatory_report_snapshot_counts
        """
        create_model(name="Snap M1", declared_complexity="HIGH", usage_scope="SINGLE_DESK",
                     exposure_amount=100)
        m2 = create_model(name="Snap M2", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                          exposure_amount=100)
        create_finding(m2["id"], severity="LOW", title="snap finding")
        report = validate_success(
            api.create_report(
                create_report_payload(report_type="BOARD_QUARTERLY",
                                      period_start="2026-07-01T00:00:00Z",
                                      period_end="2026-09-30T00:00:00Z",
                                      aggregation_method="EQUAL_WEIGHTED"),
                REPORTER,
            ),
            expected_status=201,
        )
        assert report["status"] == "DRAFT"
        assert report["total_models"] == 2
        assert report["tier_1_count"] == 1
        assert report["open_findings_total"] == 1
        assert report["open_critical_count"] == 0
        assert report["breach_event_count"] == 0

    def test_inventory_index_snapshot_not_recomputed(self, api):
        """PRD §3.9: "The report is created in `DRAFT`, and all of its snapshot fields
        are computed once at creation and never recomputed afterward, so a report is a
        frozen view of the inventory as it stood at creation time."

        Design: Corner/calculations/inventory_index_snapshot_not_recomputed
        """
        create_model(name="SnapA M1", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                     exposure_amount=100)
        report = create_draft_report(report_type="BOARD_QUARTERLY",
                                     period_start="2026-07-01T00:00:00Z",
                                     period_end="2026-09-30T00:00:00Z",
                                     aggregation_method="EQUAL_WEIGHTED")
        assert float(report["inventory_risk_index"]) == pytest.approx(30.00, abs=1e-9)
        assert report["total_models"] == 1
        create_model(name="SnapA M2", declared_complexity="HIGH", usage_scope="SINGLE_DESK",
                     exposure_amount=100)
        after = validate_success(api.get_report(report["id"], REPORTER))
        assert float(after["inventory_risk_index"]) == pytest.approx(30.00, abs=1e-9)
        assert after["total_models"] == 1, "snapshot, not live recompute"

    def test_validation_due_at_schedule_per_tier(self, api):
        """PRD §3.1: "A model's `validation_due_at` is anchored to `last_validated_at`
        when set, otherwise to `created_at`, and equals the anchor plus the tier's
        revalidation interval: six months for `TIER_1`, twelve months for `TIER_2`,
        twenty-four months for `TIER_3`."

        Registered at the 2026-08-01 default clock: TIER_1 -> 2027-02-01, TIER_2 ->
        2027-08-01, TIER_3 -> 2028-08-01.

        Design: Corner/calculations/validation_due_at_schedule_per_tier
        """
        t1 = create_model(name="Due T1", declared_complexity="HIGH", usage_scope="SINGLE_DESK",
                          exposure_amount=100)
        t2 = create_model(name="Due T2", declared_complexity="MEDIUM", usage_scope="SINGLE_DESK",
                          exposure_amount=100)
        t3 = create_model(name="Due T3", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                          exposure_amount=100)
        assert_instant_equal(t1["validation_due_at"], "2027-02-01T00:00:00Z", "TIER_1 + 6 months")
        assert_instant_equal(t2["validation_due_at"], "2027-08-01T00:00:00Z", "TIER_2 + 12 months")
        assert_instant_equal(t3["validation_due_at"], "2028-08-01T00:00:00Z", "TIER_3 + 24 months")

    def test_report_overdue_validation_count_uses_strict_comparison(self, api):
        """PRD §3.9: "and `overdue_validation_count`, the input-set models whose
        `validation_due_at` lies before the report's creation time."
        PRD §3.1: "A model's validation is overdue when the logical clock reads
        strictly after `validation_due_at`; at the exact due instant it is not yet
        overdue."

        At exactly 2027-02-01 the TIER_1 model due 2027-02-01 is NOT overdue; one day
        later a fresh report counts it.

        Design: Corner/calculations/report_overdue_validation_count_uses_strict_comparison
        """
        create_model(name="OD M1", declared_complexity="HIGH", usage_scope="SINGLE_DESK",
                     exposure_amount=100)
        create_model(name="OD M2", declared_complexity="MEDIUM", usage_scope="SINGLE_DESK",
                     exposure_amount=100)
        set_clock("2027-02-01T00:00:00Z")
        report = create_draft_report(report_type="BOARD_QUARTERLY",
                                     period_start="2026-10-01T00:00:00Z",
                                     period_end="2027-03-31T00:00:00Z",
                                     aggregation_method="EQUAL_WEIGHTED")
        assert report["overdue_validation_count"] == 0, "due exactly at creation time is not overdue"
        set_clock("2027-02-02T00:00:00Z")
        report2 = create_draft_report(report_type="BOARD_QUARTERLY",
                                      period_start="2026-10-01T00:00:00Z",
                                      period_end="2027-03-31T00:00:00Z",
                                      aggregation_method="EQUAL_WEIGHTED")
        assert report2["overdue_validation_count"] == 1, "one day past due, M1 counts"

    def test_report_zero_exposure_weighted_index_when_exposure_sum_zero(self, api):
        """PRD §3.9: "When the input set is empty, or when exposure weighting is
        requested and the set's total exposure is zero, the index is exactly 0.00."

        Design: Corner/calculations/report_zero_exposure_weighted_index_when_exposure_sum_zero
        """
        create_model(name="Zero A", declared_complexity="HIGH", usage_scope="SINGLE_DESK",
                     exposure_amount=0)
        create_model(name="Zero B", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                     exposure_amount=0)
        report = create_draft_report(report_type="REGULATOR_ANNUAL",
                                     period_start="2026-01-01T00:00:00Z",
                                     period_end="2026-12-31T00:00:00Z",
                                     aggregation_method="EXPOSURE_WEIGHTED")
        assert report["total_models"] == 2
        assert float(report["inventory_risk_index"]) == pytest.approx(0.00, abs=1e-9)


class TestInventoryRiskIndexVariants:
    def _two_model_inventory(self, api):
        create_model(name="Agg M1", declared_complexity="HIGH", usage_scope="SINGLE_DESK",
                     exposure_amount=1000000)   # 60 + 0 + 20 = 80
        create_model(name="Agg M2", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                     exposure_amount=9000000)   # 20 + 0 + 20 = 40

    def test_equal_weighted_index(self, api):
        """PRD §3.9: "Under `EQUAL_WEIGHTED` it is the plain arithmetic mean of the
        input set's `risk_score` values."

        Scores 80 and 40 -> (80 + 40) / 2 = 60.00.

        Design: Difficulty/dual_variant_calc/inventory_risk_index_equal_vs_exposure_weighted
        """
        self._two_model_inventory(api)
        report = create_draft_report(report_type="BOARD_QUARTERLY",
                                     period_start="2026-08-01T00:00:00Z",
                                     period_end="2026-09-01T00:00:00Z",
                                     aggregation_method="EQUAL_WEIGHTED")
        assert report["total_models"] == 2
        assert float(report["inventory_risk_index"]) == pytest.approx(60.00, abs=1e-9)

    def test_exposure_weighted_index(self, api):
        """PRD §3.9: "Under `EXPOSURE_WEIGHTED` each model's `risk_score` is multiplied
        by its `exposure_amount`, the products are summed, and the total is divided by
        the sum of all `exposure_amount` values in the set."

        Same two-model inventory: (80*1,000,000 + 40*9,000,000) / 10,000,000 = 44.00 —
        same input set, two variants, different index.

        Design: Difficulty/dual_variant_calc/inventory_risk_index_equal_vs_exposure_weighted
        """
        self._two_model_inventory(api)
        report = create_draft_report(report_type="REGULATOR_ANNUAL",
                                     period_start="2026-08-01T00:00:00Z",
                                     period_end="2026-09-01T00:00:00Z",
                                     aggregation_method="EXPOSURE_WEIGHTED")
        assert float(report["inventory_risk_index"]) == pytest.approx(44.00, abs=1e-9)


class TestInventoryIndexRoundingOrder:
    def _three_model_inventory(self, api):
        """30@1, 30@2, and 46@4 (30 base + two HIGH + three MEDIUM findings)."""
        create_model(name="Round M1", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                     exposure_amount=1)
        create_model(name="Round M2", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                     exposure_amount=2)
        m3 = create_model(name="Round M3", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                          exposure_amount=4)
        create_finding(m3["id"], severity="HIGH", title="penalty +5 (a)")
        create_finding(m3["id"], severity="HIGH", title="penalty +5 (b)")
        create_finding(m3["id"], severity="MEDIUM", title="penalty +2 (a)")
        create_finding(m3["id"], severity="MEDIUM", title="penalty +2 (b)")
        create_finding(m3["id"], severity="MEDIUM", title="penalty +2 (c)")
        return m3

    def test_exposure_weighted_single_final_rounding(self, api):
        """PRD §3.9: "Rounding order is pinned: no intermediate rounding is applied
        anywhere — each product is kept at full precision, the division is performed
        once, and a single round-half-up to two decimal places happens at the very end;
        rounding each contribution before summing is a different, forbidden order."

        (30*1 + 30*2 + 46*4) / 7 = 274/7 = 39.142857... -> 39.14; the forbidden
        per-contribution order would give 39.15.

        Design: Difficulty/combinatorial_formula/inventory_risk_index_nested_rounding_order
        """
        m3 = self._three_model_inventory(api)
        m3_after = validate_success(api.get_model(m3["id"], OFFICER))
        assert m3_after["risk_score"] == 46, "30 + 5*2 + 2*3"
        report = create_draft_report(report_type="BOARD_QUARTERLY",
                                     period_start="2026-08-01T00:00:00Z",
                                     period_end="2026-09-01T00:00:00Z",
                                     aggregation_method="EXPOSURE_WEIGHTED")
        assert float(report["inventory_risk_index"]) == pytest.approx(39.14, abs=1e-9)

    def test_equal_weighted_same_input_set(self, api):
        """PRD §3.9: "Under `EQUAL_WEIGHTED` it is the plain arithmetic mean of the
        input set's `risk_score` values."
        PRD §3.9: "Rounding order is pinned: no intermediate rounding is applied
        anywhere — each product is kept at full precision, the division is performed
        once, and a single round-half-up to two decimal places happens at the very end".

        The same inventory under EQUAL_WEIGHTED: (30 + 30 + 46) / 3 = 35.333... ->
        35.33, distinct from the exposure-weighted 39.14.

        Design: Difficulty/combinatorial_formula/inventory_risk_index_nested_rounding_order
        """
        self._three_model_inventory(api)
        report = create_draft_report(report_type="BOARD_QUARTERLY",
                                     period_start="2026-08-01T00:00:00Z",
                                     period_end="2026-09-01T00:00:00Z",
                                     aggregation_method="EQUAL_WEIGHTED")
        assert float(report["inventory_risk_index"]) == pytest.approx(35.33, abs=1e-9)


class TestReportSubmission:
    def test_report_submit_twice_returns_already_submitted(self, api):
        """PRD §3.9: "Submitting a report — a `RegulatoryReporter` action allowed only
        from `DRAFT`, else `ERR_REPORT_ALREADY_SUBMITTED` — moves it to the terminal
        `SUBMITTED` and stamps `submitted_at` with the logical-clock now."

        Design: Corner/state_machines/report_submit_twice_returns_already_submitted
        """
        report = create_submitted_report(report_type="REGULATOR_ANNUAL",
                                         period_start="2026-01-01T00:00:00Z",
                                         period_end="2026-12-31T00:00:00Z",
                                         aggregation_method="EQUAL_WEIGHTED")
        assert report["status"] == "SUBMITTED"
        err = validate_error(api.submit_report(report["id"], REPORTER),
                             ApiErrorId.ERR_REPORT_ALREADY_SUBMITTED)
        assert err["error_id"] == "ERR_REPORT_ALREADY_SUBMITTED"

    def test_touching_period_boundaries_conflict_on_submit(self, api):
        """PRD §3.9: "Report periods are closed intervals — both bounds inclusive — so
        overlap means the existing report's `period_start` falls on or before the new
        report's `period_end` and the new report's `period_start` falls on or before
        the existing report's `period_end`; two periods that merely touch at a boundary
        date are in conflict, unlike validation windows where adjacency is allowed. A
        conflicting submission is rejected with `ERR_REPORT_PERIOD_OVERLAP`."

        R1 SUBMITTED [2026-04-01, 2026-06-30]; R2 [2026-06-30, 2026-09-30] touches the
        boundary date and is rejected.

        Design: Difficulty/resource_temporal_overlap/report_periods_closed_interval_adjacency_conflicts
        """
        create_submitted_report(report_type="BOARD_QUARTERLY",
                                period_start="2026-04-01T00:00:00Z",
                                period_end="2026-06-30T00:00:00Z",
                                aggregation_method="EQUAL_WEIGHTED")
        r2 = create_draft_report(report_type="BOARD_QUARTERLY",
                                 period_start="2026-06-30T00:00:00Z",
                                 period_end="2026-09-30T00:00:00Z",
                                 aggregation_method="EQUAL_WEIGHTED")
        err = validate_error(api.submit_report(r2["id"], REPORTER),
                             ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)
        assert err["error_id"] == "ERR_REPORT_PERIOD_OVERLAP"
        after = validate_success(api.get_report(r2["id"], REPORTER))
        assert after["status"] == "DRAFT", "rejected submission leaves the report DRAFT"

    def test_disjoint_period_submit_succeeds(self, api):
        """PRD §3.9: "Report periods are closed intervals — both bounds inclusive — so
        overlap means the existing report's `period_start` falls on or before the new
        report's `period_end` and the new report's `period_start` falls on or before
        the existing report's `period_end`; two periods that merely touch at a boundary
        date are in conflict, unlike validation windows where adjacency is allowed."

        R3 [2026-07-01, 2026-09-30] starts after R1's inclusive end 2026-06-30 and is
        accepted.

        Design: Difficulty/resource_temporal_overlap/report_periods_closed_interval_adjacency_conflicts
        """
        create_submitted_report(report_type="BOARD_QUARTERLY",
                                period_start="2026-04-01T00:00:00Z",
                                period_end="2026-06-30T00:00:00Z",
                                aggregation_method="EQUAL_WEIGHTED")
        r3 = create_draft_report(report_type="BOARD_QUARTERLY",
                                 period_start="2026-07-01T00:00:00Z",
                                 period_end="2026-09-30T00:00:00Z",
                                 aggregation_method="EQUAL_WEIGHTED")
        submitted = validate_success(api.submit_report(r3["id"], REPORTER))
        assert submitted["status"] == "SUBMITTED"

    def test_reports_list_filters_by_type_and_status(self, api):
        """PRD §3.9: "The report list can be filtered by `report_type` and by
        `status`."

        Design: Corner/endpoints/reports_list_filters_by_type_and_status
        """
        create_submitted_report(report_type="BOARD_QUARTERLY",
                                period_start="2026-04-01T00:00:00Z",
                                period_end="2026-06-30T00:00:00Z",
                                aggregation_method="EQUAL_WEIGHTED")
        create_draft_report(report_type="REGULATOR_ANNUAL",
                            period_start="2026-01-01T00:00:00Z",
                            period_end="2026-12-31T00:00:00Z",
                            aggregation_method="EXPOSURE_WEIGHTED")
        rows, _ = validate_paginated(
            api.list_reports(REPORTER, params={"report_type": "BOARD_QUARTERLY", "status": "SUBMITTED"})
        )
        assert len(rows) == 1
        drafts, _ = validate_paginated(api.list_reports(REPORTER, params={"status": "DRAFT"}))
        assert len(drafts) == 1 and drafts[0]["report_type"] == "REGULATOR_ANNUAL"
