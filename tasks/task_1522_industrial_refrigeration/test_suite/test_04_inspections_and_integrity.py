"""Mechanical integrity: inspection completion variants, the FAIL recheck rule,
the FAIL -> permit-suspension cascade, and inspection list filtering."""
from test_helpers import (
    MLEAD,
    api_client,
    assert_equipment,
    assert_timestamp_instant,
    complete_inspection_payload,
    create_equipment,
    schedule_inspection,
    set_clock,
    setup_issued_permit,
    setup_facility_with_system,
    validate_paginated,
    validate_success,
)


class TestInspectionDueDateVariants:

    def _two_vessels(self):
        """One FIXED and one CONDITION_BASED vessel, each with an inspection
        due 2026-08-05; the clock is at 2026-08-10 for completion."""
        facility, system = setup_facility_with_system(name="Freezeworks")
        eq_fixed = create_equipment(system["id"], tag_number="V-101",
                                    inspection_interval_days=180,
                                    inspection_method="FIXED")
        eq_cond = create_equipment(system["id"], tag_number="V-102",
                                   inspection_interval_days=180,
                                   inspection_method="CONDITION_BASED")
        insp_fixed = schedule_inspection(eq_fixed["id"], "2026-08-05T00:00:00Z")
        insp_cond = schedule_inspection(eq_cond["id"], "2026-08-05T00:00:00Z")
        set_clock("2026-08-10T00:00:00Z")
        return eq_fixed, eq_cond, insp_fixed, insp_cond

    def test_inspection_due_fixed_method(self):
        """PRD section 3.3: "Under `FIXED`, the next due date is exactly the
        base `inspection_interval_days` after completion, regardless of result."
        PRD section 3.3: "The platform stamps `completed_at` from the logical
        clock and sets `completed_late` to true only when the inspection stood
        `OVERDUE` at completion; an on-cycle completion from `SCHEDULED`
        records `completed_late` false."

        Design: Difficulty/dual_variant_calc/inspection_due_fixed_vs_condition_based
        """
        eq_fixed, eq_cond, insp_fixed, insp_cond = self._two_vessels()
        done = validate_success(
            api_client.complete_inspection(
                insp_fixed["id"], complete_inspection_payload(result="PASS"),
                MLEAD),
            expected_status=200)
        assert done["result"] == "PASS"
        assert done["status"] == "COMPLETED"
        assert done["completed_late"] is False
        assert_timestamp_instant(done["completed_at"], "2026-08-10T00:00:00Z")

        eq_after = validate_success(api_client.get_equipment(eq_fixed["id"], MLEAD),
                                    expected_status=200)
        assert_equipment(eq_after)
        # FIXED: 2026-08-10 + 180 days exactly
        assert_timestamp_instant(eq_after["next_due_at"], "2027-02-06T00:00:00Z")
        assert eq_after["last_result"] == "PASS"
        assert eq_after["integrity_status"] == "CURRENT"

    def test_inspection_due_condition_based_method(self):
        """PRD section 3.3: "Under `CONDITION_BASED`, a `PASS` extends the
        interval to one and a half times the base — the product rounded down to
        a whole number of days — but never beyond 1095 days after completion,
        while a `FAIL` forces a recheck 30 days after completion."

        Design: Difficulty/dual_variant_calc/inspection_due_fixed_vs_condition_based
        """
        eq_fixed, eq_cond, insp_fixed, insp_cond = self._two_vessels()
        done = validate_success(
            api_client.complete_inspection(
                insp_cond["id"], complete_inspection_payload(result="PASS"),
                MLEAD),
            expected_status=200)
        assert done["result"] == "PASS"
        assert_timestamp_instant(done["completed_at"], "2026-08-10T00:00:00Z")

        eq_after = validate_success(api_client.get_equipment(eq_cond["id"], MLEAD),
                                    expected_status=200)
        # CONDITION_BASED PASS: floor(180 * 1.5) = 270 days after completion;
        # identical completion data as the FIXED vessel, divergent next_due_at
        assert_timestamp_instant(eq_after["next_due_at"], "2027-05-07T00:00:00Z")
        assert eq_after["integrity_status"] == "CURRENT"


class TestFailRecheck:

    def test_inspection_fail_forces_thirty_day_recheck(self):
        """PRD section 3.3: "Under `CONDITION_BASED`, a `PASS` extends the
        interval to one and a half times the base — the product rounded down to
        a whole number of days — but never beyond 1095 days after completion,
        while a `FAIL` forces a recheck 30 days after completion."
        PRD section 3.3: "The equipment's `integrity_status` is then
        re-derived: `FAILED` whenever `last_result` is `FAIL`; otherwise
        `OVERDUE` when a linked inspection stands `OVERDUE` or the recomputed
        `next_due_at` lies strictly in the past; otherwise `DUE_SOON` when
        `next_due_at` falls no more than 30 days ahead; otherwise `CURRENT`."

        Design: Corner/calculations/inspection_fail_forces_thirty_day_recheck
        """
        facility, system = setup_facility_with_system()
        equipment = create_equipment(system["id"], tag_number="P-301",
                                     equipment_type="PIPING_CIRCUIT",
                                     inspection_interval_days=180,
                                     inspection_method="CONDITION_BASED")
        inspection = schedule_inspection(equipment["id"], "2026-08-05T00:00:00Z")
        set_clock("2026-08-10T00:00:00Z")
        done = validate_success(
            api_client.complete_inspection(
                inspection["id"],
                complete_inspection_payload(result="FAIL",
                                            findings="wall thinning"),
                MLEAD),
            expected_status=200)
        assert done["result"] == "FAIL"

        eq_after = validate_success(api_client.get_equipment(equipment["id"], MLEAD),
                                    expected_status=200)
        # FAIL overrides the interval: recheck at completed + 30 days
        assert_timestamp_instant(eq_after["next_due_at"], "2026-09-09T00:00:00Z")
        assert eq_after["last_result"] == "FAIL"
        assert eq_after["integrity_status"] == "FAILED"


class TestFailCascadeSuspendsPermits:

    def test_equipment_fail_cascade_suspends_permits_then_resume(self):
        """PRD section 3.3: "A `FAIL` result carries a safety cascade beyond
        the equipment record: every hot work permit on the failed equipment's
        system standing `ISSUED` or `IN_PROGRESS` is automatically moved to
        `SUSPENDED`."
        PRD section 3.7: "The permit's own `ContractorRep` — identity pinned by
        `contractor_id`, else `ERR_FORBIDDEN` — moves the permit from `ISSUED`,
        or from `SUSPENDED` when resuming interrupted work, to `IN_PROGRESS`."

        Design: Corner/state_machines/equipment_fail_cascade_suspends_permits_then_resume
        """
        facility, system, contractor, permit, rep_headers = setup_issued_permit()
        equipment = create_equipment(system["id"], tag_number="C-201",
                                     equipment_type="COMPRESSOR",
                                     inspection_interval_days=180,
                                     inspection_method="FIXED")
        insp1 = schedule_inspection(equipment["id"], "2026-08-05T00:00:00Z")
        set_clock("2026-08-10T00:00:00Z")

        validate_success(
            api_client.complete_inspection(
                insp1["id"],
                complete_inspection_payload(result="FAIL",
                                            findings="corrosion under insulation"),
                MLEAD),
            expected_status=200)
        permit_after_fail = validate_success(
            api_client.get_hot_work_permit(permit["id"], MLEAD),
            expected_status=200)
        assert permit_after_fail["status"] == "SUSPENDED"
        eq_failed = validate_success(api_client.get_equipment(equipment["id"], MLEAD),
                                     expected_status=200)
        assert eq_failed["integrity_status"] == "FAILED"

        # a later PASS restores integrity; the SUSPENDED permit can start again
        insp2 = schedule_inspection(equipment["id"], "2026-08-10T00:00:00Z")
        validate_success(
            api_client.complete_inspection(
                insp2["id"],
                complete_inspection_payload(result="PASS",
                                            findings="remediated"),
                MLEAD),
            expected_status=200)
        eq_restored = validate_success(
            api_client.get_equipment(equipment["id"], MLEAD), expected_status=200)
        assert eq_restored["integrity_status"] == "CURRENT"

        set_clock("2026-09-01T09:00:00Z")
        started = validate_success(api_client.start_permit(permit["id"], rep_headers),
                                   expected_status=200)
        assert started["status"] == "IN_PROGRESS"


class TestInspectionListing:

    def test_inspections_filter_by_equipment_fk(self):
        """PRD section 3.3: "The inspections list filters by `equipment_id` and
        `status`."

        Design: Corner/endpoints/inspections_filter_by_equipment_fk
        """
        facility, system = setup_facility_with_system()
        eq_a = create_equipment(system["id"], tag_number="V-101",
                                inspection_interval_days=180,
                                inspection_method="FIXED")
        eq_b = create_equipment(system["id"], tag_number="C-201",
                                equipment_type="COMPRESSOR",
                                inspection_interval_days=90,
                                inspection_method="FIXED")
        schedule_inspection(eq_a["id"], "2026-09-01T00:00:00Z")
        schedule_inspection(eq_b["id"], "2026-09-01T00:00:00Z")
        schedule_inspection(eq_b["id"], "2026-12-01T00:00:00Z")

        data, meta = validate_paginated(api_client.list_inspections(
            MLEAD, params={"equipment_id": eq_a["id"]}))
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["equipment_id"] == eq_a["id"], \
            "a sibling equipment's inspections must not leak into the filter"
