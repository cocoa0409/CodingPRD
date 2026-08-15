"""Discount schedules, grade sheets, finalize rules, re-grade cascades, OCC."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_warehouse,
    api_client,
    assert_grade_sheet,
    clear_aflatoxin,
    compute_settlement,
    create_discount_schedule_payload,
    create_sheet,
    finalize_sheet,
    get_load,
    make_lab_technician_headers,
    report_load,
    setup_active_schedule,
    setup_buying_point,
    setup_computed_settlement,
    setup_grower,
    setup_settlement_foundation,
    setup_stored_load,
    store_load,
    validate_error,
    validate_paginated,
    validate_success,
    weigh_load,
)

ADMIN = TEST_USERS["admin_headers"]
LAB_1 = TEST_USERS["lab_tech_headers"]


class TestScheduleLifecycle:

    def test_schedule_window_overlap_rejected_adjacency_allowed(self):
        """PRD section 3.1: "Activating a `DRAFT` schedule moves it to
        `ACTIVE`, but only if its half-open window does not overlap the window
        of any other `ACTIVE` schedule — an overlap is rejected with
        `ERR_SCHEDULE_WINDOW_OVERLAP`, so at most one active schedule covers
        any instant."
        PRD section 3.1: "a half-open coverage window from `effective_from`
        (inclusive) to `effective_to` (exclusive)".

        Design: Corner/entities/schedule_window_overlap_rejected_adjacency_allowed
        """
        setup_buying_point()
        flat = dict(
            moisture_tiers=[{"up_to_pct": None, "discount_cents_per_ton": 0}],
            foreign_material_tiers=[{"up_to_pct": None, "discount_cents_per_ton": 0}],
        )

        s1 = validate_success(api_client.create_discount_schedule(
            create_discount_schedule_payload(
                schedule_code="S1", effective_from="2026-08-01T00:00:00Z",
                effective_to="2026-10-01T00:00:00Z", **flat), ADMIN),
            expected_status=201)
        api_client.activate_discount_schedule(s1["id"], ADMIN)

        s2 = validate_success(api_client.create_discount_schedule(
            create_discount_schedule_payload(
                schedule_code="S2", effective_from="2026-09-15T00:00:00Z",
                effective_to="2026-11-01T00:00:00Z", **flat), ADMIN),
            expected_status=201)
        s3 = validate_success(api_client.create_discount_schedule(
            create_discount_schedule_payload(
                schedule_code="S3", effective_from="2026-10-01T00:00:00Z",
                effective_to="2027-01-01T00:00:00Z", **flat), ADMIN),
            expected_status=201)

        resp = api_client.activate_discount_schedule(s2["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_WINDOW_OVERLAP)

        resp = api_client.activate_discount_schedule(s3["id"], ADMIN)
        activated = validate_success(resp)
        assert activated["status"] == "ACTIVE", \
            "S3 starts exactly at S1's effective_to — half-open adjacency is legal"

        s1_after = api_client.get_discount_schedule(s1["id"], ADMIN).json()["data"]
        assert s1_after["status"] == "ACTIVE"

    def test_schedule_pinning_uses_weighed_at_and_survives_retire(self):
        """PRD section 3.1: "Retirement is not retroactive: grade sheets
        already finalized keep the `schedule_id` they pinned (version-pinning
        of policy), but any finalization after the retire requires some other
        `ACTIVE` schedule to cover the load's weigh timestamp, and fails with
        `ERR_NO_ACTIVE_SCHEDULE` when none does."
        PRD section 3.4: "The finalize step requires an `ACTIVE` discount
        schedule whose half-open window covers the load's `weighed_at`; absent
        one, the finalize fails with `ERR_NO_ACTIVE_SCHEDULE`."

        Design: Corner/validations/schedule_pinning_uses_weighed_at_and_survives_retire
        """
        bp = setup_buying_point(clock="2026-09-15T09:00:00Z")
        s1 = validate_success(api_client.create_discount_schedule(
            create_discount_schedule_payload(
                schedule_code="S1", effective_from="2026-08-01T00:00:00Z",
                effective_to="2026-10-01T00:00:00Z",
                moisture_tiers=[{"up_to_pct": None, "discount_cents_per_ton": 100}],
                foreign_material_tiers=[{"up_to_pct": None, "discount_cents_per_ton": 0}]),
            ADMIN), expected_status=201)
        api_client.activate_discount_schedule(s1["id"], ADMIN)
        s2 = validate_success(api_client.create_discount_schedule(
            create_discount_schedule_payload(
                schedule_code="S2", effective_from="2026-10-01T00:00:00Z",
                effective_to="2027-01-01T00:00:00Z",
                moisture_tiers=[{"up_to_pct": None, "discount_cents_per_ton": 200}],
                foreign_material_tiers=[{"up_to_pct": None, "discount_cents_per_ton": 0}]),
            ADMIN), expected_status=201)

        add_warehouse(bp["id"])
        grower = setup_grower()

        load_a = report_load(grower["id"])
        weighed_a = weigh_load(load_a["id"], 25.0)
        load_b = report_load(grower["id"])
        weighed_b = weigh_load(load_b["id"], 25.0)

        # Sheet B finalizes while S1 is ACTIVE: pins S1.
        sheet_b = create_sheet(load_b["id"], weighed_b["version"])
        finalized_b = finalize_sheet(sheet_b["id"])
        assert finalized_b["schedule_id"] == s1["id"]

        # Sheet A stays DRAFT across the retire + re-activate boundary.
        sheet_a = create_sheet(load_a["id"], weighed_a["version"])

        api_client.retire_discount_schedule(s1["id"], ADMIN)
        api_client.activate_discount_schedule(s2["id"], ADMIN)
        api_client.set_clock({"to_iso8601": "2026-10-05T09:00:00Z"}, ADMIN)

        # Pinned schedule survives retirement.
        sheet_b_after = api_client.get_grade_sheet(sheet_b["id"], ADMIN).json()["data"]
        assert sheet_b_after["schedule_id"] == s1["id"]
        assert sheet_b_after["status"] == "FINALIZED"

        # Sheet A's load was weighed inside S1's window; S2 does not cover it.
        resp = api_client.finalize_grade_sheet(sheet_a["id"],
                                               TEST_USERS["inspector_headers"])
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_SCHEDULE)
        sheet_a_after = api_client.get_grade_sheet(sheet_a["id"], ADMIN).json()["data"]
        assert sheet_a_after["status"] == "DRAFT"
        assert get_load(load_a["id"])["status"] == "WEIGHED"


class TestGradeSheetRules:

    def test_grade_sheet_pct_over_100_rejected(self):
        """PRD section 2.6: "**Percentages** supplied by clients (`moisture_pct`,
        `foreign_material_pct`, `damage_pct`, `lsk_pct`) carry two decimal
        places and must each lie between 0 and 100 inclusive."
        PRD section 2.9: "**Request schema** — required fields present, types
        valid, enum values in range, and numeric constraints satisfied
        (positive tonnages, percentages within 0 to 100, positive
        `amount_cents`): `ERR_INVALID_REQUEST`."

        Design: Corner/entities/grade_sheet_pct_over_100_rejected
        """
        f = setup_settlement_foundation()
        load = report_load(f["grower"]["id"])
        weighed = weigh_load(load["id"], 25.0)
        resp = api_client.create_grade_sheet(
            load["id"],
            {"moisture_pct": 100.01, "foreign_material_pct": 5.5,
             "damage_pct": 2.0, "lsk_pct": 1.0,
             "expected_farmer_stock_load_version": weighed["version"]},
            TEST_USERS["inspector_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert get_load(load["id"])["status"] == "WEIGHED"

    def test_rejected_load_terminal_lockdown(self):
        """PRD section 3.4: "when the measured moisture exceeds 15.00 percent,
        the sheet still finalizes — it remains the grade of record — but the
        load moves `WEIGHED` → `REJECTED`, a terminal state, and may never be
        stored."
        PRD section 3.5: "the load must be `WEIGHED` or `GRADED` (any other
        state is rejected with `ERR_INVALID_STATE`)".

        Design: Corner/state_machines/rejected_load_terminal_lockdown
        """
        f = setup_settlement_foundation()
        load = report_load(f["grower"]["id"])
        weighed = weigh_load(load["id"], 25.0)
        sheet = create_sheet(load["id"], weighed["version"], moisture_pct=16.0)
        finalize_sheet(sheet["id"])

        load_after = get_load(load["id"])
        assert load_after["status"] == "REJECTED"
        sheet_after = api_client.get_grade_sheet(sheet["id"], ADMIN).json()["data"]
        assert sheet_after["status"] == "FINALIZED", "sheet remains grade of record"

        resp = api_client.create_aflatoxin_certificate(
            load["id"], {"sample_ref": "SAMP-X"}, LAB_1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        resp = api_client.create_storage_receipt(
            {"load_id": load["id"], "warehouse_id": f["warehouse"]["id"]}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        resp = api_client.create_grade_sheet(
            load["id"],
            {"moisture_pct": 9.0, "foreign_material_pct": 5.5, "damage_pct": 2.0,
             "lsk_pct": 1.0,
             "expected_farmer_stock_load_version": load_after["version"]},
            TEST_USERS["inspector_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_regrade_supersede_marks_settlement_stale(self):
        """PRD section 3.4: "The prior `FINALIZED` sheet becomes `SUPERSEDED`,
        a terminal read-only record that retains its pinned `schedule_id`; the
        new sheet finalizes; `payable_tons`, the drying axis, and the
        provisional estimate are all recomputed; the load's `version`
        increments; and every settlement in `COMPUTED` or `DISPUTED` whose
        `included_load_ids` contains this load is swept to `STALE`."
        PRD section 3.4: "A re-grade of a `STORED` load follows the same
        supersede-and-recompute pattern with the same settlement lock and the
        same `STALE` cascade, and the load remains `STORED`".

        Design: Corner/state_machines/regrade_supersede_marks_settlement_stale
        """
        env = setup_computed_settlement()
        s1 = env["settlement"]
        assert s1["status"] == "COMPUTED"
        assert env["load"]["id"] in s1["included_load_ids"]

        load_now = get_load(env["load"]["id"])
        new_sheet = create_sheet(load_now["id"], load_now["version"],
                                 foreign_material_pct=7.5, inspector="insp-2")
        finalized = finalize_sheet(new_sheet["id"], inspector="insp-2")

        old_sheet = api_client.get_grade_sheet(env["sheet"]["id"], ADMIN).json()["data"]
        assert old_sheet["status"] == "SUPERSEDED"
        assert old_sheet["schedule_id"] == env["schedule"]["id"]
        assert finalized["status"] == "FINALIZED"
        assert finalized["schedule_id"] == env["schedule"]["id"]

        load_after = get_load(env["load"]["id"])
        assert load_after["status"] == "STORED"
        # fm 7.5% of 25.0 = 1.875; lsk 0.250; payable = 25 - 1.875 - 0.25
        assert load_after["payable_tons"] == 22.875
        # gross 22.875 x 56000 = 1281000; discounts 5719 + 22875 + 6863 = 35457
        assert load_after["provisional_net_estimate_cents"] == 1245543

        s1_after = api_client.get_settlement(s1["id"], ADMIN).json()["data"]
        assert s1_after["status"] == "STALE"

    def test_approved_settlement_locks_regrade(self):
        """PRD section 3.4: "Finalizing a newer `DRAFT` sheet on a load already
        `GRADED` requires that the load's `settlement_id` is still null — once
        a load is locked into an approved settlement, re-grade attempts are
        rejected with `ERR_LOAD_LOCKED_BY_SETTLEMENT`".
        PRD section 3.9: "writes this settlement's id into every included
        load's `settlement_id` — which is what locks those loads against
        re-grade per §3.4."

        Design: Corner/state_machines/approved_settlement_locks_regrade
        """
        env = setup_computed_settlement()
        s1 = env["settlement"]
        api_client.approve_settlement(s1["id"], TEST_USERS["clerk_2_headers"])

        load_now = get_load(env["load"]["id"])
        assert load_now["settlement_id"] == s1["id"]

        new_sheet = create_sheet(load_now["id"], load_now["version"],
                                 foreign_material_pct=7.5, inspector="insp-2")
        resp = api_client.finalize_grade_sheet(new_sheet["id"],
                                               TEST_USERS["inspector_2_headers"])
        validate_error(resp, ApiErrorId.ERR_LOAD_LOCKED_BY_SETTLEMENT)

        sheet_after = api_client.get_grade_sheet(new_sheet["id"], ADMIN).json()["data"]
        assert sheet_after["status"] == "DRAFT", "failed finalize must not consume the sheet"
        old_sheet = api_client.get_grade_sheet(env["sheet"]["id"], ADMIN).json()["data"]
        assert old_sheet["status"] == "FINALIZED"
        s1_after = api_client.get_settlement(s1["id"], ADMIN).json()["data"]
        assert s1_after["status"] == "APPROVED"

    def test_occ_grade_sheet_create_stale_load_version(self):
        """PRD section 2.8: "Creating a grade sheet on a load requires
        `expected_farmer_stock_load_version`, carrying the client's
        last-observed `version` of the load."
        PRD section 2.8: "if the supplied value does not match the parent
        entity's current `version` — because another writer has advanced that
        version since the client last read the parent — the request is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."
        PRD section 3.4: "creating it increments the load's `version` — which
        is precisely what makes the OCC field meaningful".

        Design: Corner/cross_cutting/occ_grade_sheet_create_stale_load_version
        """
        f = setup_settlement_foundation()
        load = report_load(f["grower"]["id"])
        weighed = weigh_load(load["id"], 25.0)
        observed_v = weighed["version"]

        payload = {"moisture_pct": 9.2, "foreign_material_pct": 5.5,
                   "damage_pct": 2.0, "lsk_pct": 1.0,
                   "expected_farmer_stock_load_version": observed_v}
        resp = api_client.create_grade_sheet(load["id"], payload,
                                             TEST_USERS["inspector_headers"])
        sheet = validate_success(resp, expected_status=201)
        assert_grade_sheet(sheet)
        assert sheet["status"] == "DRAFT"

        load_after = get_load(load["id"])
        assert load_after["version"] == observed_v + 1, \
            "sheet create must bump the load version (OCC basis)"

        resp = api_client.create_grade_sheet(load["id"], payload,
                                             TEST_USERS["inspector_2_headers"])
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        resp = api_client.list_grade_sheets(ADMIN, params={"load_id": load["id"]})
        _data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1

    def test_lab_technician_cannot_finalize_grade_sheet_returns_forbidden(self):
        """PRD section 4: the grade-sheet finalize row lists only
        `GradingInspector`.
        PRD section 3.4: "Grading is the exclusive province of a
        `GradingInspector`."
        PRD section 2.1: "A request whose role is recognized but not permitted
        for the target operation is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/lab_technician_cannot_finalize_grade_sheet_returns_forbidden
        """
        f = setup_settlement_foundation()
        load = report_load(f["grower"]["id"])
        weighed = weigh_load(load["id"], 25.0)
        sheet = create_sheet(load["id"], weighed["version"])
        resp = api_client.finalize_grade_sheet(sheet["id"], LAB_1)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        sheet_after = api_client.get_grade_sheet(sheet["id"], ADMIN).json()["data"]
        assert sheet_after["status"] == "DRAFT"


class TestLoadValuation:

    def test_payable_tons_per_component_rounding(self):
        """PRD section 3.4: "the foreign-material tonnage is the load's
        `gross_tons` multiplied by the foreign-material percentage divided by
        one hundred, rounded half up to three decimal places; the
        loose-shelled-kernel tonnage is computed the same way from `lsk_pct`;
        and payable tonnage is the gross tonnage minus those two rounded
        deduction tonnages, itself rounded half up to three decimals."
        PRD section 3.4: "The per-component rounding must happen first —
        computing a single combined deduction percentage against gross weight
        in one multiplication is not permitted, because the two orders differ
        at the third decimal."

        Design: Difficulty/combinatorial_formula/load_value_per_line_rounding_order
        """
        f = setup_settlement_foundation()
        load = report_load(f["grower"]["id"])
        weighed = weigh_load(load["id"], 25.0)
        sheet = create_sheet(load["id"], weighed["version"],
                             moisture_pct=9.2, foreign_material_pct=5.5,
                             damage_pct=2.0, lsk_pct=1.0)
        finalized = finalize_sheet(sheet["id"])
        # fm = round_half_up(25.0 * 5.5 / 100) = 1.375; lsk = 0.250
        # payable = 25.0 - 1.375 - 0.250 = 23.375
        assert finalized["payable_tons"] == 23.375
        assert finalized["status"] == "FINALIZED"
        assert finalized["schedule_id"] == f["schedule"]["id"]

    def test_provisional_estimate_per_line_discount_rounding(self):
        """PRD section 3.9: "`discount_cents` sums the per-load discount
        amounts, and for each load the three discount lines — payable tonnage
        times the moisture per-ton rate, times the foreign-material per-ton
        rate, and times the damage per-ton rate — are each rounded half up to
        whole cents before being summed; summing the rates first and
        multiplying once is not permitted, as the two orders produce different
        cent totals."
        PRD section 3.4: "Its `provisional_net_estimate_cents` is computed as a
        forward-looking estimate of settlement value: the per-load net value of
        §3.9 computed with quota headroom taken as the grower's annual quota
        minus already-consumed quota with no intra-settlement consumption,
        minus an estimated drying charge when drying is `REQUIRED`, with hull
        credit and loan offset treated as zero."

        Design: Difficulty/combinatorial_formula/load_value_per_line_rounding_order
        """
        f = setup_settlement_foundation()
        load = report_load(f["grower"]["id"])
        weighed = weigh_load(load["id"], 25.0)
        sheet = create_sheet(load["id"], weighed["version"],
                             moisture_pct=9.2, foreign_material_pct=5.5,
                             damage_pct=2.0, lsk_pct=1.0)
        finalize_sheet(sheet["id"])
        load_after = get_load(load["id"])
        # gross = 23.375 x 56000 = 1309000; per-line discounts:
        #   round(23.375 x 250) = 5844, round(23.375 x 400) = 9350,
        #   round(23.375 x 300) = 7013 -> total 22207 (sum-then-round would be 22206)
        assert load_after["provisional_net_estimate_cents"] == 1286793, \
            "1309000 - 22207 = 1286793 (per-line round-then-sum)"

    def test_moisture_1049_drying_not_required_and_stores(self):
        """PRD section 3.4: "Its drying axis becomes `REQUIRED` when the
        measured moisture is above 10.49 percent and `NOT_REQUIRED` otherwise."

        Design: Difficulty/boundary_precision_check/moisture_drying_threshold_exact_boundary
        """
        f = setup_settlement_foundation()
        load = report_load(f["grower"]["id"])
        weighed = weigh_load(load["id"], 20.0)
        sheet = create_sheet(load["id"], weighed["version"], moisture_pct=10.49,
                             foreign_material_pct=2.0, damage_pct=0.0, lsk_pct=0.0)
        finalize_sheet(sheet["id"])
        load_after = get_load(load["id"])
        assert load_after["drying_status"] == "NOT_REQUIRED", \
            "10.49 is not above 10.49 — boundary is inclusive-safe"
        assert load_after["payable_tons"] == 19.6  # fm 2% of 20.0 = 0.4

        clear_aflatoxin(load["id"], result_ppb=5.0)
        receipt = store_load(load["id"], f["warehouse"]["id"])
        assert receipt["status"] == "OPEN"
        assert get_load(load["id"])["status"] == "STORED"

    def test_moisture_1050_drying_required_blocks_storage(self):
        """PRD section 3.4: "Its drying axis becomes `REQUIRED` when the
        measured moisture is above 10.49 percent and `NOT_REQUIRED` otherwise."
        PRD section 3.7: "The drying axis must be `NOT_REQUIRED` or `DRIED`
        (`ERR_DRYING_REQUIRED`)."

        Design: Difficulty/boundary_precision_check/moisture_drying_threshold_exact_boundary
        """
        f = setup_settlement_foundation()
        load = report_load(f["grower"]["id"])
        weighed = weigh_load(load["id"], 20.0)
        sheet = create_sheet(load["id"], weighed["version"], moisture_pct=10.50,
                             foreign_material_pct=2.0, damage_pct=0.0, lsk_pct=0.0)
        finalize_sheet(sheet["id"])
        load_after = get_load(load["id"])
        assert load_after["drying_status"] == "REQUIRED"

        resp = api_client.create_storage_receipt(
            {"load_id": load["id"], "warehouse_id": f["warehouse"]["id"]}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_DRYING_REQUIRED)
        assert get_load(load["id"])["status"] == "GRADED"

    def test_provisional_includes_estimated_drying(self):
        """PRD section 3.4: "The estimated drying charge divides the gross
        tonnage by the smallest `cycle_capacity_tons` among the buying point's
        dryers, rounds up to whole cycles, multiplies by
        `drying_rate_per_cycle_cents` and by the moisture multiplier of §3.6,
        and rounds half up to whole cents; when the buying point has no dryers,
        the drying estimate is zero because no estimate is possible."

        Design: Corner/calculations/provisional_includes_estimated_drying
        """
        f = setup_settlement_foundation(with_dryer=True)
        load = report_load(f["grower"]["id"])
        weighed = weigh_load(load["id"], 25.0)
        sheet = create_sheet(load["id"], weighed["version"], moisture_pct=11.2,
                             foreign_material_pct=3.0, damage_pct=0.0, lsk_pct=0.0)
        finalize_sheet(sheet["id"])
        load_after = get_load(load["id"])
        assert load_after["drying_status"] == "REQUIRED"  # 11.2 > 10.49
        assert load_after["payable_tons"] == 24.25  # fm 3% of 25 = 0.75
        # gross = 24.25 x 56000 = 1358000; moisture tier (10.49,12.0] = 700
        #   -> discount 16975; estimated drying = ceil(25/12)=3 x 9000 x 1.00 = 27000
        assert load_after["provisional_net_estimate_cents"] == 1314025
